"""Tests for the provider registry (providers.py).

Covers: the preconfigured providers, dataclass field validity, env-override
resolution, and the aspect-ratio -> size mapping per size dialect.
"""

from __future__ import annotations

import base64
import dataclasses

import pytest


class _Stop(Exception):
    """Sentinel raised by fake transports to capture a request without sending it."""

from generate_image import cli
from generate_image import providers
from generate_image.providers import (
    PROVIDERS,
    DEFAULT_PROVIDER,
    Provider,
    resolve_provider,
    ratio_to_size,
    VALID_EDIT_STYLES,
    VALID_GEN_STYLES,
    VALID_SIZE_STYLES,
)


EXPECTED_PROVIDERS = {"openai", "302ai", "openrouter", "siliconflow",
                      "volcengine", "147ai"}


def test_registry_has_the_expected_providers():
    assert set(PROVIDERS) == EXPECTED_PROVIDERS


def test_default_provider_is_openai():
    assert DEFAULT_PROVIDER == "openai"
    assert DEFAULT_PROVIDER in PROVIDERS


@pytest.mark.parametrize("name", sorted(EXPECTED_PROVIDERS))
def test_each_provider_has_coherent_fields(name):
    p = PROVIDERS[name]
    assert isinstance(p, Provider)
    assert p.name == name
    assert p.base_url.startswith("https://")
    assert p.key_env.endswith("_API_KEY")
    assert p.gen_path.startswith("/")
    assert p.gen_style in VALID_GEN_STYLES
    # edit support is optional, but if present the style must be recognized
    if p.edit_path is not None:
        assert p.edit_style in VALID_EDIT_STYLES
    if p.size_style is not None:
        assert p.size_style in VALID_SIZE_STYLES
    assert p.default_model
    assert p.max_retries >= 1
    assert p.default_concurrency >= 1
    assert p.rpm >= 1
    # a provider with edit support must accept at least one reference image
    if p.edit_path is not None:
        assert p.max_ref_images >= 1


def test_billing_and_idempotency_flags_match_research():
    # 302ai is a relay that bills on failure; it supports idempotency keys.
    assert PROVIDERS["302ai"].bills_on_failure is True
    assert PROVIDERS["302ai"].supports_idempotency is True
    # openai / openrouter / siliconflow do not bill rejected requests.
    assert PROVIDERS["openai"].bills_on_failure is False
    assert PROVIDERS["openai"].supports_idempotency is False
    assert PROVIDERS["openrouter"].bills_on_failure is False
    assert PROVIDERS["siliconflow"].bills_on_failure is False
    # Ark debits credits per generation, failures included.
    assert PROVIDERS["volcengine"].bills_on_failure is True


def test_edit_styles_are_per_provider():
    assert PROVIDERS["openai"].edit_style == "multipart"
    assert PROVIDERS["302ai"].edit_style == "multipart"
    assert PROVIDERS["openrouter"].edit_style == "chat_image"
    assert PROVIDERS["siliconflow"].edit_style == "image_prompt"
    assert PROVIDERS["volcengine"].edit_style == "ark_json"


def test_volcengine_catalog_includes_seedream_5_pro():
    p = PROVIDERS["volcengine"]
    assert p.default_model == "doubao-seedream-5-0-260128"
    assert "doubao-seedream-5-0-lite-260128" in p.models
    assert "doubao-seedream-5-0-pro-260628" in p.models


def test_openrouter_gen_path_has_no_generations_suffix():
    # OpenRouter's image endpoint is /v1/images, NOT /v1/images/generations.
    assert PROVIDERS["openrouter"].gen_path == "/v1/images"


# --- resolve_provider ---------------------------------------------------------


def test_resolve_unknown_provider_raises_keyerror():
    with pytest.raises(KeyError):
        resolve_provider("does-not-exist")


def test_resolve_returns_registry_defaults_without_env(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_DEFAULT_MODEL", raising=False)
    p = resolve_provider("openai")
    assert p.base_url == PROVIDERS["openai"].base_url
    assert p.default_model == PROVIDERS["openai"].default_model


def test_resolve_applies_base_url_and_model_env_overrides(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://relay.internal.example/")
    monkeypatch.setenv("OPENAI_DEFAULT_MODEL", "gpt-image-9")
    p = resolve_provider("openai")
    # trailing slash stripped for clean path joining
    assert p.base_url == "https://relay.internal.example"
    assert p.default_model == "gpt-image-9"


def test_resolve_override_prefix_derives_from_key_env(monkeypatch):
    # 302ai's key_env is AI302_API_KEY -> override prefix AI302.
    monkeypatch.setenv("AI302_DEFAULT_MODEL", "flux-kontext-max")
    p = resolve_provider("302ai")
    assert p.default_model == "flux-kontext-max"


def test_resolve_does_not_mutate_the_registry(monkeypatch):
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://example.test")
    resolve_provider("openrouter")
    # registry entry stays pristine (frozen dataclass, replace returns a copy)
    assert PROVIDERS["openrouter"].base_url == "https://openrouter.ai/api"


# --- ratio_to_size ------------------------------------------------------------


def test_ratio_to_size_openai_style():
    # No registered provider uses the plain 3-value enum any more (both gpt-image
    # backends honor a custom WxH), but the style stays supported for a relay
    # swapped in via OPENAI_BASE_URL that ignores `size`. Cover it with a synthetic
    # provider rather than dropping the branch.
    p = dataclasses.replace(PROVIDERS["openai"], size_style="openai")
    assert ratio_to_size(p, "1:1") == "1024x1024"
    assert ratio_to_size(p, "16:9") == "1536x1024"
    assert ratio_to_size(p, "9:16") == "1024x1536"


def test_ratio_to_size_openai_custom_style_is_aspect_exact():
    # The registered gpt-image providers honor a custom WxH, so they get the
    # exact-aspect table instead of the 3-value enum that mapped 7 of 10 ratios
    # onto a wrong shape.
    for name in ("openai", "302ai"):
        p = PROVIDERS[name]
        assert p.size_style == "openai_custom", name
        # ratios the old enum already got right stay byte-identical
        assert ratio_to_size(p, "1:1") == "1024x1024"
        assert ratio_to_size(p, "3:2") == "1536x1024"
        assert ratio_to_size(p, "2:3") == "1024x1536"
        # the seven that were wrong now land on the requested aspect
        assert ratio_to_size(p, "16:9") == "1680x944"
        assert ratio_to_size(p, "21:9") == "1904x816"
        assert ratio_to_size(p, "9:16") == "944x1680"


def test_openai_custom_sizes_obey_the_published_gpt_image_contract():
    """Every custom size must satisfy OpenAI's documented constraints, else the
    API rejects it: multiples of 16, aspect 1:3..3:1, edges <= 3840, total pixels
    655,360..8,294,400 — and must match the ratio it claims to encode."""
    for ratio, size in providers.OPENAI_CUSTOM_RATIO_SIZE.items():
        w, h = (int(v) for v in size.split("x"))
        assert w % 16 == 0 and h % 16 == 0, f"{ratio}={size} not a multiple of 16"
        assert 1 / 3 <= w / h <= 3, f"{ratio}={size} outside the 1:3..3:1 window"
        assert max(w, h) <= 3840, f"{ratio}={size} exceeds the 3840 edge cap"
        assert 655_360 <= w * h <= 8_294_400, f"{ratio}={size} outside the pixel window"
        a, b = (int(v) for v in ratio.split(":"))
        assert abs((w / h) - (a / b)) / (a / b) < 0.01, (
            f"{ratio}={size} is {w / h:.3f}, more than 1% off the requested {a / b:.3f}"
        )


def test_every_ratio_the_cli_accepts_has_a_custom_size():
    assert cli.VALID_RATIOS <= set(providers.OPENAI_CUSTOM_RATIO_SIZE)


def test_ratio_to_size_wxh_style_uses_siliconflow_set():
    p = PROVIDERS["siliconflow"]  # size_style == "wxh"
    assert ratio_to_size(p, "1:1") == "1328x1328"
    assert ratio_to_size(p, "16:9") == "1664x928"
    assert ratio_to_size(p, "9:16") == "928x1664"
    # all mapped values must be from SiliconFlow's supported set
    supported = set(providers.SILICONFLOW_RATIO_SIZE.values())
    for ratio in ("1:1", "16:9", "9:16", "3:2", "2:3", "4:3", "3:4", "4:5", "5:4", "21:9"):
        assert ratio_to_size(p, ratio) in supported


def test_ratio_to_size_none_when_provider_takes_no_size():
    p = PROVIDERS["openrouter"]  # size_style is None
    assert ratio_to_size(p, "16:9") is None


def test_ratio_to_size_ark_uses_2k_tier():
    assert ratio_to_size(PROVIDERS["volcengine"], "1:1") == "2K"
    assert ratio_to_size(PROVIDERS["volcengine"], "16:9") == "2K"


def test_ratio_to_size_unknown_ratio_falls_back():
    assert ratio_to_size(PROVIDERS["openai"], "7:3") == "1024x1024"
    assert ratio_to_size(PROVIDERS["siliconflow"], "7:3") == "1328x1328"


def test_legacy_seedream_config_is_read_only_ark_key_fallback(tmp_path, monkeypatch):
    (tmp_path / ".seedream-config.json").write_text(
        '{"ARK_API_KEY":"legacy-test-key"}', encoding="utf-8")
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.setattr(cli, "_find_dotenv", lambda: None)
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))

    cli._load_dotenv()

    assert cli.require_key("ARK_API_KEY") == "legacy-test-key"


def test_ark_env_key_wins_over_legacy_seedream_config(tmp_path, monkeypatch):
    (tmp_path / ".seedream-config.json").write_text(
        '{"ARK_API_KEY":"legacy-test-key"}', encoding="utf-8")
    monkeypatch.setenv("ARK_API_KEY", "env-test-key")
    monkeypatch.setattr(cli, "_find_dotenv", lambda: None)
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))

    cli._load_dotenv()

    assert cli.require_key("ARK_API_KEY") == "env-test-key"


# --- 147ai: one base_url fronting two upstream protocols ----------------------

def test_147ai_defaults_to_the_gemini_chat_dialect():
    p = PROVIDERS["147ai"]
    assert p.base_url == "https://nn.147ai.com"
    assert p.key_env == "AI147_API_KEY"  # env vars may not start with a digit
    assert p.default_model == "gemini-3-pro-image-preview"
    assert p.gen_style == "chat_image_config"
    assert p.gen_path == "/v1/chat/completions"
    assert p.size_style == "image_config"


def test_147ai_gpt_image_models_switch_to_the_openai_images_dialect():
    from generate_image.providers import apply_model_dialect

    p = apply_model_dialect(PROVIDERS["147ai"], "gpt-image-2-high")

    assert p.gen_path == "/v1/images/generations"
    assert p.gen_style == "openai"
    assert p.edit_path == "/v1/images/edits"
    assert p.edit_style == "multipart"
    assert p.size_style == "openai_xl"
    # identity fields must survive specialization
    assert p.name == "147ai" and p.key_env == "AI147_API_KEY"


def test_147ai_gemini_models_keep_the_chat_dialect():
    from generate_image.providers import apply_model_dialect

    p = apply_model_dialect(PROVIDERS["147ai"], "gemini-2.5-flash-image")

    assert p.gen_style == "chat_image_config"
    assert p.gen_path == "/v1/chat/completions"


def test_apply_model_dialect_is_a_noop_for_single_dialect_providers():
    from generate_image.providers import apply_model_dialect

    for name in ("openai", "302ai", "openrouter", "siliconflow", "volcengine"):
        p = PROVIDERS[name]
        assert apply_model_dialect(p, "anything-at-all") is p


def test_image_config_size_style_returns_a_quality_tier_not_wxh():
    from generate_image.providers import IMAGE_CONFIG_SIZES

    p = PROVIDERS["147ai"]
    for ratio in ("1:1", "16:9", "21:9"):
        assert ratio_to_size(p, ratio) in IMAGE_CONFIG_SIZES


def test_openai_xl_sizes_preserve_orientation():
    from generate_image.providers import apply_model_dialect

    p = apply_model_dialect(PROVIDERS["147ai"], "gpt-image-2-medium")

    def wh(r):
        return tuple(int(x) for x in ratio_to_size(p, r).split("x"))

    w, h = wh("16:9")
    assert w > h
    w, h = wh("9:16")
    assert h > w
    w, h = wh("1:1")
    assert w == h
    # the gateway's XL enum must beat openai's ~1.57MP ceiling somewhere
    assert max(wh("1:1")[0] * wh("1:1")[1], wh("21:9")[0] * wh("21:9")[1]) > 1_572_516


def test_edit_multipart_pins_size_only_where_it_is_honored(monkeypatch, tmp_path):
    """147ai's /v1/images/edits honors `size`; openai/302ai ignore it, so sending one
    there would misreport control we don't have."""
    from generate_image import cli
    from generate_image.providers import apply_model_dialect

    ref = tmp_path / "r.png"
    ref.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
        "AAAABJRU5ErkJggg=="))
    seen = {}

    def fake_post(client, url, key, provider, *, json_body=None, files=None,
                  data=None, idem_key=None):
        seen["form"] = data
        raise _Stop()

    monkeypatch.setattr(cli, "_post", fake_post)

    xl = apply_model_dialect(PROVIDERS["147ai"], "gpt-image-2-high")
    with pytest.raises(_Stop):
        cli.provider_edit(xl, "p", "gpt-image-2-high", [str(ref)], "16:9", "k", None)
    assert seen["form"]["size"] == "2048x1152"

    with pytest.raises(_Stop):
        cli.provider_edit(PROVIDERS["openai"], "p", "gpt-image-2", [str(ref)], "16:9",
                          "k", None)
    assert "size" not in seen["form"]


def test_147ai_declared_styles_are_registered_as_valid():
    from generate_image.providers import apply_model_dialect

    p = PROVIDERS["147ai"]
    assert p.gen_style in VALID_GEN_STYLES
    assert p.size_style in VALID_SIZE_STYLES
    assert p.edit_style in VALID_EDIT_STYLES
    xl = apply_model_dialect(p, "gpt-image-2-low")
    assert xl.gen_style in VALID_GEN_STYLES
    assert xl.size_style in VALID_SIZE_STYLES
    assert xl.edit_style in VALID_EDIT_STYLES


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
