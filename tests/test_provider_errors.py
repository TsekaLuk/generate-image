"""Provider HTTP-boundary error classification.

Exercises provider_generate against an injected httpx.MockTransport and asserts
that HTTP errors / network faults surface as ProviderError with the correct
`.retryable` / `.retry_after` / `.status`, per the billing-aware rules in
reliability.is_retryable_status. `302ai` is the representative billing provider
(bills_on_failure=True, supports_idempotency=True).
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from generate_image import cli as generate
from generate_image.providers import PROVIDERS
from generate_image.reliability import ProviderError, build_client

BILLING = PROVIDERS["302ai"]

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _client(handler) -> httpx.Client:
    return build_client(transport=httpx.MockTransport(handler))


def _gen(client):
    return generate.provider_generate(BILLING, "p", "gpt-image-2", "16:9", "key", client)


def test_http_401_is_non_retryable():
    def handler(req):
        return httpx.Response(401, text="unauthorized")

    with _client(handler) as c:
        with pytest.raises(ProviderError) as ei:
            _gen(c)
    assert ei.value.retryable is False
    assert ei.value.status == 401


def test_http_500_is_retryable_because_302ai_supports_idempotency():
    def handler(req):
        return httpx.Response(500, text="server exploded")

    with _client(handler) as c:
        with pytest.raises(ProviderError) as ei:
            _gen(c)
    assert ei.value.retryable is True


def test_http_429_is_retryable_with_retry_after():
    def handler(req):
        return httpx.Response(429, headers={"Retry-After": "7"}, json={"error": "slow down"})

    with _client(handler) as c:
        with pytest.raises(ProviderError) as ei:
            _gen(c)
    assert ei.value.retryable is True
    assert ei.value.retry_after == 7.0
    assert ei.value.status == 429


def test_timeout_is_retryable():
    def handler(req):
        raise httpx.ReadTimeout("timed out", request=req)

    with _client(handler) as c:
        with pytest.raises(ProviderError) as ei:
            _gen(c)
    assert ei.value.retryable is True


def test_network_error_is_retryable():
    def handler(req):
        raise httpx.ConnectError("connection refused", request=req)

    with _client(handler) as c:
        with pytest.raises(ProviderError) as ei:
            _gen(c)
    assert ei.value.retryable is True


def test_non_billing_provider_5xx_is_retryable():
    # siliconflow does not bill failures -> 5xx retryable even without idempotency
    sf = PROVIDERS["siliconflow"]

    def handler(req):
        return httpx.Response(503, text="overloaded")

    with _client(handler) as c:
        with pytest.raises(ProviderError) as ei:
            generate.provider_generate(sf, "p", sf.default_model, "16:9", "key", c)
    assert ei.value.retryable is True


def test_success_returns_image_bytes():
    payload = {"data": [{"b64_json": base64.b64encode(_TINY_PNG).decode("ascii")}]}

    def handler(req):
        return httpx.Response(200, json=payload)

    with _client(handler) as c:
        out = _gen(c)
    assert out == _TINY_PNG


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
