"""Retry classification wired through the provider boundary (all providers).

reliability.is_retryable_status is unit-tested in test_reliability.py. Here we
assert provider_generate actually threads each provider's billing flags into that
classifier, so retryability is correct per provider — not just in isolation.
"""

from __future__ import annotations

import httpx
import pytest

from generate_image import cli as generate
from generate_image.providers import PROVIDERS
from generate_image.reliability import ProviderError, build_client, is_retryable_status

ALL_PROVIDERS = sorted(PROVIDERS)


def _client(status: int, headers: dict | None = None) -> httpx.Client:
    def handler(req):
        return httpx.Response(status, headers=headers or {}, text="err")

    return build_client(transport=httpx.MockTransport(handler))


def _gen(provider_name: str, client: httpx.Client):
    p = PROVIDERS[provider_name]
    return generate.provider_generate(p, "p", p.default_model, "16:9", "key", client)


@pytest.mark.parametrize("name", ALL_PROVIDERS)
def test_500_retryability_matches_billing_flags(name):
    p = PROVIDERS[name]
    expected = is_retryable_status(
        500, bills_on_failure=p.bills_on_failure, supports_idempotency=p.supports_idempotency
    )
    with _client(500) as c:
        with pytest.raises(ProviderError) as ei:
            _gen(name, c)
    assert ei.value.retryable is expected


@pytest.mark.parametrize("name", ALL_PROVIDERS)
def test_429_always_retryable(name):
    with _client(429, headers={"Retry-After": "3"}) as c:
        with pytest.raises(ProviderError) as ei:
            _gen(name, c)
    assert ei.value.retryable is True
    assert ei.value.retry_after == 3.0


@pytest.mark.parametrize("name", ALL_PROVIDERS)
def test_400_never_retryable(name):
    with _client(400) as c:
        with pytest.raises(ProviderError) as ei:
            _gen(name, c)
    assert ei.value.retryable is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


# --- broken-transport retry (147ai) -------------------------------------------

def test_broken_transport_retries_when_the_failure_is_billed_anyway():
    """A mid-flight SSL EOF on 147ai is billed regardless, so refusing to retry
    costs the same money and returns no image. Measured 2026-07."""
    import httpx
    from generate_image import cli
    from generate_image.providers import PROVIDERS

    p = PROVIDERS["147ai"]
    assert p.bills_on_failure and not p.supports_idempotency
    # the conservative rule alone would refuse...
    assert cli._net_retryable(p) is False
    # ...but the measured-billing override allows it
    assert cli._transport_retryable(p) is True


def test_broken_transport_override_is_off_for_other_billing_gateways():
    from generate_image import cli
    from generate_image.providers import PROVIDERS

    for name in ("openai", "302ai", "volcengine"):
        assert cli._transport_retryable(PROVIDERS[name]) is cli._net_retryable(
            PROVIDERS[name])


def test_read_timeout_stays_conservative_on_147ai():
    """A timeout may mean the image WAS produced; only a broken connection is
    known to have delivered nothing."""
    from generate_image import cli
    from generate_image.providers import PROVIDERS

    assert cli._net_retryable(PROVIDERS["147ai"]) is False


def test_backoff_floor_prevents_an_immediate_retry():
    from generate_image.reliability import backoff_delay

    for attempt in (1, 2, 3, 4):
        assert backoff_delay(attempt, floor=20.0) >= 20.0
    # default behavior is unchanged (may wait ~0s)
    assert backoff_delay(1, floor=0.0) >= 0.0


def test_backoff_floor_never_inverts_the_jitter_window():
    """floor > the exponential ceiling must not produce uniform(hi, lo)."""
    from generate_image.reliability import backoff_delay

    d = backoff_delay(1, base=0.5, cap=8.0, floor=30.0)
    assert d >= 30.0


def test_147ai_declares_the_measured_throttle_settings():
    from generate_image.providers import PROVIDERS

    p = PROVIDERS["147ai"]
    assert p.retry_broken_transport is True
    assert p.backoff_floor >= 20.0
    assert p.default_concurrency == 1  # back-to-back requests get cut
    assert p.rpm <= 12
