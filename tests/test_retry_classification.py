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
