"""Tests for the provider registry (providers.py).

Covers: the four preconfigured providers, dataclass field validity, env-override
resolution, and the aspect-ratio -> size mapping per size dialect.
"""

from __future__ import annotations

import pytest

from generate_image import providers
from generate_image.providers import (
    PROVIDERS,
    DEFAULT_PROVIDER,
    Provider,
    resolve_provider,
    ratio_to_size,
    VALID_EDIT_STYLES,
    VALID_SIZE_STYLES,
)


EXPECTED_PROVIDERS = {"openai", "302ai", "openrouter", "siliconflow"}


def test_registry_has_the_four_expected_providers():
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


def test_edit_styles_are_per_provider():
    assert PROVIDERS["openai"].edit_style == "multipart"
    assert PROVIDERS["302ai"].edit_style == "multipart"
    assert PROVIDERS["openrouter"].edit_style == "chat_image"
    assert PROVIDERS["siliconflow"].edit_style == "image_prompt"


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
    monkeypatch.setenv("OPENAI_BASE_URL", "https://relay.example.com/")
    monkeypatch.setenv("OPENAI_DEFAULT_MODEL", "gpt-image-9")
    p = resolve_provider("openai")
    # trailing slash stripped for clean path joining
    assert p.base_url == "https://relay.example.com"
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
    p = PROVIDERS["openai"]  # size_style == "openai"
    assert ratio_to_size(p, "1:1") == "1024x1024"
    assert ratio_to_size(p, "16:9") == "1536x1024"
    assert ratio_to_size(p, "9:16") == "1024x1536"


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


def test_ratio_to_size_unknown_ratio_falls_back():
    assert ratio_to_size(PROVIDERS["openai"], "7:3") == "1024x1024"
    assert ratio_to_size(PROVIDERS["siliconflow"], "7:3") == "1328x1328"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
