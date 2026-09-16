"""`--quality` — the capability guard, the cost model, and the spend guardrail.

The single most important test in this file is
`test_no_quality_flag_sends_no_quality_field`: the whole feature is required to be
invisible unless the caller opts in.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import sys

import httpx
import pytest

from generate_image import cli as generate
from generate_image.cli import ProviderError
from generate_image.providers import (
    EXTENDED_QUALITY_MODELS,
    EXTENDED_QUALITY_TIERS,
    PROVIDERS,
    VALID_QUALITY_TIERS,
    route_provider,
)

_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
        "IQAAAABJRU5ErkJggg==")
_TINY_PNG = base64.b64decode(_B64)

Q_PROVIDER = PROVIDERS["302ai"]          # measured to honor quality
Q_MODEL = "gpt-image-2.5-flare"


def _capture(provider, **kwargs):
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content.decode())
        return httpx.Response(200, json={"data": [{"b64_json": _B64}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        seen["out"] = generate.provider_generate(
            provider, "一只猫", kwargs.pop("model", Q_MODEL), "1:1", "k", c, **kwargs)
    return seen


# --- the default path must not move -------------------------------------------

def test_no_quality_flag_sends_no_quality_field():
    """Without --quality the request body is exactly what it was before the flag
    existed. This is the contract that makes the feature safe to ship."""
    seen = _capture(Q_PROVIDER)
    assert seen["out"] == _TINY_PNG
    assert "quality" not in seen["body"]


def test_quality_auto_is_also_not_sent():
    # 'auto' IS the server default; sending it would be noise, not intent.
    seen = _capture(Q_PROVIDER, quality="auto")
    assert "quality" not in seen["body"]


# --- it is sent where it is honored -------------------------------------------

@pytest.mark.parametrize("tier", ["low", "medium", "high", "xhigh", "max"])
def test_quality_is_sent_on_a_provider_that_honors_it(tier):
    seen = _capture(Q_PROVIDER, quality=tier)
    assert seen["body"]["quality"] == tier


# --- and refused where it is not ----------------------------------------------

def test_quality_refused_on_provider_that_silently_ignores_it():
    # Relays exist that accept `quality` and change nothing, so paying for it is
    # pure loss — refuse client-side rather than bill for a no-op. No registered
    # provider behaves that way here, so synthesize one.
    ignores = dataclasses.replace(Q_PROVIDER, name="relay", supports_quality=False)
    with pytest.raises(ProviderError, match="not honored"):
        generate._guard_quality(ignores, "gpt-image-2.5-flare", "high")


def test_extended_tiers_refused_on_pre_25_models():
    # Measured: the API returns 200 for xhigh on gpt-image-2 and ignores the tier,
    # so nothing on the wire would ever tell the caller.
    for tier in sorted(EXTENDED_QUALITY_TIERS):
        with pytest.raises(ProviderError, match="only exists on GPT Image 2.5"):
            generate._guard_quality(Q_PROVIDER, "gpt-image-2", tier)


def test_extended_tiers_allowed_on_25_models():
    for model in sorted(EXTENDED_QUALITY_MODELS):
        for tier in sorted(EXTENDED_QUALITY_TIERS):
            generate._guard_quality(Q_PROVIDER, model, tier)  # must not raise


def test_every_advertised_tier_is_guard_clean_on_a_25_model():
    for tier in VALID_QUALITY_TIERS:
        generate._guard_quality(Q_PROVIDER, Q_MODEL, tier)


# --- routing treats quality as a hard capability ------------------------------

def test_routing_skips_providers_that_ignore_quality(monkeypatch):
    monkeypatch.setenv("AI302_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")   # does NOT honor quality
    p = route_provider(quality="high", allow_unconfigured=True)
    assert p.supports_quality, f"routed to {p.name}, which ignores quality"


def test_routing_reports_quality_in_the_failure_detail(monkeypatch):
    # No provider honors an extended tier on a pre-2.5 model -> the error should
    # name quality as the unsatisfied constraint, not fail silently elsewhere.
    with pytest.raises(ValueError, match="quality"):
        route_provider(model="gpt-image-1", quality="max", allow_unconfigured=True)


# --- cost model ---------------------------------------------------------------

def test_unit_cost_is_tier_aware():
    low = generate._unit_cost("302ai", Q_MODEL, "low")
    mx = generate._unit_cost("302ai", Q_MODEL, "max")
    assert low is not None and mx is not None
    assert mx / low > 30, "the measured max/low spread is ~36x; the table lost it"


def test_unmeasured_tier_reports_unknown_rather_than_the_cheap_price():
    """The one failure mode that costs real money: quoting the un-toned price for
    a tier that bills many times more."""
    base = generate._unit_cost("302ai", "gpt-image-2")          # no tier pinned
    assert base is not None
    assert generate._unit_cost("302ai", "gpt-image-2", "max") is None


def test_unit_cost_without_quality_is_unchanged():
    assert generate._unit_cost("302ai", Q_MODEL) == generate._unit_cost("302ai", Q_MODEL, None)


# --- spend guardrail ----------------------------------------------------------

def _guard(n, quality, yes=None):
    generate._guard_run_cost({"302ai": n}, {"302ai": Q_MODEL}, quality, yes)


def test_guard_is_inert_without_a_pinned_tier():
    _guard(1000, None)          # must not raise: this is today's behaviour
    _guard(1000, "auto")


def test_guard_allows_a_single_expensive_image():
    _guard(1, "max")            # ~¥1.52, below the ¥5 ceiling — experiments stay easy


def test_guard_blocks_a_batch_at_a_high_tier():
    with pytest.raises(ProviderError, match="Nothing was sent"):
        _guard(5, "max")


def test_guard_error_names_the_amount_and_the_way_through():
    with pytest.raises(ProviderError) as e:
        _guard(5, "max")
    msg = str(e.value)
    assert "--yes-costs" in msg and "≈¥" in msg


def test_explicit_ceiling_lets_it_through():
    _guard(5, "max", yes=10.0)


def test_ceiling_below_the_estimate_still_blocks():
    with pytest.raises(ProviderError):
        _guard(5, "max", yes=1.0)


def test_unknown_price_at_an_extended_tier_is_blocked_not_waved_through():
    # An unpriced HIGH tier is more dangerous than a priced one, so ignorance must
    # not be a free pass.
    with pytest.raises(ProviderError, match="cannot be estimated"):
        generate._guard_run_cost({"302ai": 3}, {"302ai": "gpt-image-2"}, "max", None)


def test_unknown_price_at_a_normal_tier_is_allowed():
    generate._guard_run_cost({"302ai": 3}, {"302ai": "gpt-image-2"}, "medium", None)


# --- machine-readable output must not disagree with the human line -------------

def test_dry_run_json_estimate_carries_the_tier(tmp_path, monkeypatch, capsys):
    """A script reading estimated_cost_cny must see the tiered price, not the
    un-toned one — a wrong number is worse here than on the terminal."""
    monkeypatch.setenv("AI302_API_KEY", "k")
    monkeypatch.setattr(sys, "argv", [
        "g", "t", "-p", "302ai", "--dry-run", "--json", "--quality", "high",
        "-r", "1:1", "-o", str(tmp_path), "-n", "p", "--no-preview",
    ])
    generate.main()
    obj = json.loads(capsys.readouterr().out.strip())
    assert obj["estimated_cost_cny"] == generate._unit_cost("302ai", Q_MODEL, "high")


def test_dry_run_json_estimate_unchanged_without_the_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AI302_API_KEY", "k")
    monkeypatch.setattr(sys, "argv", [
        "g", "t", "-p", "302ai", "--dry-run", "--json",
        "-r", "1:1", "-o", str(tmp_path), "-n", "p", "--no-preview",
    ])
    generate.main()
    obj = json.loads(capsys.readouterr().out.strip())
    assert obj["estimated_cost_cny"] == generate._unit_cost("302ai", Q_MODEL)


def test_post_run_spent_line_carries_the_tier(tmp_path, monkeypatch, capsys):
    """The settled 'spent' line is the number a user reconciles against their bill;
    it must not report the un-toned price after a tiered run."""
    monkeypatch.setenv("AI302_API_KEY", "k")

    def handler(req):
        return httpx.Response(200, json={"data": [{"b64_json": _B64}]})

    monkeypatch.setattr(generate, "make_client",
                        lambda *a, **k: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(sys, "argv", [
        "g", "t", "-p", "302ai", "--quality", "high", "-r", "1:1",
        "-o", str(tmp_path), "-n", "p", "--no-preview",
    ])
    generate.main()
    err = capsys.readouterr().err
    expected = generate._unit_cost("302ai", Q_MODEL, "high")
    assert f"¥{expected:.2f}" in err, err


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
