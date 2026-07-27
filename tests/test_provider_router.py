"""Capability-aware provider routing without network calls."""

from __future__ import annotations

import dataclasses

import pytest

from generate_image.providers import (PROVIDERS, ROUTER_PRIORITY, endpoint_unset,
                                      route_provider)

# The provider environment is already emptied by the autouse fixture in conftest.


def test_every_registered_provider_is_routable():
    """ROUTER_PRIORITY must stay in sync with the registry.

    A provider missing here is silently unreachable via `auto`, and list_models
    ranks by this tuple — so a new entry in PROVIDERS alone is never enough.
    """
    assert set(ROUTER_PRIORITY) == set(PROVIDERS)


def test_router_prefers_the_highest_priority_configured_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("AI302_API_KEY", "302-key")
    assert route_provider().name == "openai"


def test_router_selects_provider_with_seed_support(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-key")
    assert route_provider(seed=42).name == "siliconflow"


def test_router_filters_background_incompatible_default_model(monkeypatch):
    """Every Seedream model refuses --background, so volcengine must drop out.

    The official OpenAI API does support `background=transparent`, so this filter
    has to be exercised on a provider that genuinely lacks it.
    """
    monkeypatch.setenv("ARK_API_KEY", "ark-key")
    assert route_provider().name == "volcengine"
    with pytest.raises(ValueError, match="background=transparent"):
        route_provider(background="transparent")


def test_router_fails_clearly_when_nothing_is_configured():
    with pytest.raises(ValueError, match="no configured image provider"):
        route_provider()


def test_dry_run_can_select_an_unconfigured_builtin():
    assert route_provider(allow_unconfigured=True).name == "openai"


def test_a_placeholder_endpoint_is_never_usable(monkeypatch):
    """`requires_base_url` marks a provider that has nowhere real to send a request.

    No built-in provider ships a placeholder host, so the flag is exercised on a
    SYNTHETIC one: a deployment that adds a private gateway relies on it to keep
    credentials from going to a guessed address, in dry-runs too. The check reads
    `{PREFIX}_BASE_URL`, so it is the env — not the registry — that settles it.
    """
    gateway = dataclasses.replace(PROVIDERS["openai"], requires_base_url=True)
    assert endpoint_unset(gateway)

    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example.test")
    assert not endpoint_unset(gateway)


def test_a_provider_without_the_flag_needs_no_base_url_override():
    assert not endpoint_unset(PROVIDERS["openai"])


# --- providers added after the router: capability filters must cover them -----

def test_router_rejects_more_refs_than_a_provider_accepts(monkeypatch):
    """siliconflow takes a single ref; volcengine's Ark image[] takes up to 10."""
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sf-key")
    monkeypatch.setenv("ARK_API_KEY", "ark-key")
    assert route_provider(ref_count=1).name == "siliconflow"
    assert route_provider(ref_count=4).name == "volcengine"
    with pytest.raises(ValueError, match="11 reference image"):
        route_provider(ref_count=11)


def test_router_skips_volcengine_when_background_is_requested(monkeypatch):
    """Every Seedream model rejects --background, so the filter must fall through."""
    monkeypatch.setenv("ARK_API_KEY", "ark-key")
    monkeypatch.setenv("AI302_API_KEY", "302-key")
    assert route_provider().name == "302ai"  # 302ai already outranks volcengine
    assert route_provider(background="transparent").name == "302ai"

    monkeypatch.delenv("AI302_API_KEY")
    with pytest.raises(ValueError, match="background=transparent"):
        route_provider(background="transparent")


def test_router_matches_a_model_to_the_provider_that_lists_it(monkeypatch):
    """147ai sits last in priority but wins when its own model is requested."""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("AI147_API_KEY", "147-key")
    assert route_provider().name == "openai"
    assert route_provider(model="gemini-3-pro-image-preview").name == "147ai"
