"""Client-side --background guard at the provider boundary.

A model listed in `provider.background_unsupported` must make provider_generate /
provider_edit raise ProviderError(retryable=False) BEFORE any network I/O. No
built-in provider currently blacklists a model (the official OpenAI gpt-image
models support background=transparent), so the guard is exercised through a
SYNTHETIC provider whose background_unsupported set is non-empty — the mechanism
must keep working for any future provider/model that needs it.

The guard must NOT fire when background is falsy, and must NOT fire for providers
whose background_unsupported set is empty.
"""

from __future__ import annotations

import base64
import dataclasses

import httpx
import pytest

from generate_image import cli as generate
from generate_image.providers import PROVIDERS
from generate_image.reliability import ProviderError, build_client

# Synthetic provider: the openai entry with gpt-image-2 marked background-unsupported.
GUARDED = dataclasses.replace(
    PROVIDERS["openai"],
    name="guarded",
    background_unsupported=frozenset({"gpt-image-2"}),
)
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _exploding_client() -> httpx.Client:
    def handler(req):
        raise AssertionError("network must not be called when the guard fires")

    return build_client(transport=httpx.MockTransport(handler))


def _ok_client() -> httpx.Client:
    def handler(req):
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(_TINY_PNG).decode()}]})

    return build_client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("bg", ["transparent", "opaque", "auto"])
def test_generate_guard_fires_before_network(bg):
    with _exploding_client() as c:
        with pytest.raises(ProviderError) as ei:
            generate.provider_generate(GUARDED, "p", "gpt-image-2", "1:1", "key", c, background=bg)
    assert ei.value.retryable is False


@pytest.mark.parametrize("bg", ["transparent", "opaque", "auto"])
def test_edit_guard_fires_before_network(tmp_path, bg):
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    with _exploding_client() as c:
        with pytest.raises(ProviderError) as ei:
            generate.provider_edit(GUARDED, "p", "gpt-image-2", [str(ref)], "1:1", "key", c, background=bg)
    assert ei.value.retryable is False


def test_no_background_reaches_network_and_succeeds():
    with _ok_client() as c:
        out = generate.provider_generate(GUARDED, "p", "gpt-image-2", "1:1", "key", c, background=None)
    assert out == _TINY_PNG


def test_background_ok_on_provider_with_empty_unsupported_set():
    # openai has an empty background_unsupported set -> guard never fires.
    p = PROVIDERS["openai"]
    with _ok_client() as c:
        out = generate.provider_generate(p, "p", p.default_model, "1:1", "key", c, background="transparent")
    assert out == _TINY_PNG


def test_guard_only_fires_for_listed_models():
    # A model NOT in background_unsupported must pass through the guard.
    with _ok_client() as c:
        out = generate.provider_generate(GUARDED, "p", "gpt-image-1", "1:1", "key", c, background="transparent")
    assert out == _TINY_PNG


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
