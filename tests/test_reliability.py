"""Tests for the reliability/scheduling layer (reliability.py).

All timing is made deterministic by injecting clock/sleep/rng — no real network
and no real sleeping.
"""

from __future__ import annotations

import random

import httpx
import pytest

from generate_image import reliability
from generate_image.reliability import (
    ProviderError,
    is_retryable_status,
    retry_after_seconds,
    backoff_delay,
    call_with_retry,
    new_idempotency_key,
    TokenBucket,
    AdaptiveConcurrency,
    build_client,
)


# --- is_retryable_status ------------------------------------------------------

@pytest.mark.parametrize("status", [408, 429])
def test_408_429_always_retryable_regardless_of_billing(status):
    assert is_retryable_status(status, bills_on_failure=True, supports_idempotency=False) is True
    assert is_retryable_status(status, bills_on_failure=False, supports_idempotency=False) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_other_4xx_never_retryable(status):
    assert is_retryable_status(status, bills_on_failure=False, supports_idempotency=True) is False


def test_5xx_retryable_only_when_safe_for_billing():
    # billing gateway, no idempotency -> do NOT retry (avoid double charge)
    assert is_retryable_status(500, bills_on_failure=True, supports_idempotency=False) is False
    assert is_retryable_status(503, bills_on_failure=True, supports_idempotency=False) is False
    # billing gateway WITH idempotency -> safe to retry (deduped)
    assert is_retryable_status(500, bills_on_failure=True, supports_idempotency=True) is True
    # non-billing provider -> always safe to retry 5xx
    assert is_retryable_status(502, bills_on_failure=False, supports_idempotency=False) is True


# --- retry_after_seconds ------------------------------------------------------

def test_retry_after_integer_seconds():
    assert retry_after_seconds({"Retry-After": "12"}) == 12.0


def test_retry_after_case_insensitive_header():
    assert retry_after_seconds({"retry-after": "3"}) == 3.0


def test_retry_after_absent_returns_none():
    assert retry_after_seconds({}) is None
    assert retry_after_seconds({"X-Other": "1"}) is None


def test_retry_after_http_date_form_returns_none():
    # HTTP-date form is not honored; backoff takes over.
    assert retry_after_seconds({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}) is None


# --- backoff_delay ------------------------------------------------------------

def test_backoff_delay_within_full_jitter_bounds():
    rng = random.Random(1234)
    for attempt in range(1, 8):
        d = backoff_delay(attempt, base=0.5, cap=8.0, rng=rng)
        ceiling = min(8.0, 0.5 * (2 ** (attempt - 1)))
        assert 0.0 <= d <= ceiling


def test_backoff_delay_ceiling_is_capped():
    # rng that always returns the top of the range
    class _MaxRng:
        def uniform(self, a, b):
            return b
    assert backoff_delay(1, base=0.5, cap=8.0, rng=_MaxRng()) == 0.5
    assert backoff_delay(2, base=0.5, cap=8.0, rng=_MaxRng()) == 1.0
    assert backoff_delay(10, base=0.5, cap=8.0, rng=_MaxRng()) == 8.0  # capped


# --- call_with_retry ----------------------------------------------------------

def test_call_with_retry_success_first_try_calls_once():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return "ok"

    assert call_with_retry(fn, max_attempts=3, sleep=lambda d: None) == "ok"
    assert calls["n"] == 1


def test_call_with_retry_retries_then_succeeds():
    calls = {"n": 0}
    slept: list[float] = []

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderError("transient", retryable=True)
        return "done"

    result = call_with_retry(
        fn, max_attempts=5, sleep=slept.append, rng=random.Random(0)
    )
    assert result == "done"
    assert calls["n"] == 3
    assert len(slept) == 2  # two retries -> two waits


def test_call_with_retry_honors_retry_after_over_backoff():
    calls = {"n": 0}
    slept: list[float] = []

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ProviderError("rate limited", retryable=True, retry_after=2.5)
        return "ok"

    call_with_retry(fn, max_attempts=5, sleep=slept.append)
    assert slept == [2.5, 2.5]


def test_call_with_retry_non_retryable_raises_immediately():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ProviderError("bad request", retryable=False)

    with pytest.raises(ProviderError):
        call_with_retry(fn, max_attempts=5, sleep=lambda d: None)
    assert calls["n"] == 1


def test_call_with_retry_exhausts_attempts_then_reraises():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ProviderError("always", retryable=True)

    with pytest.raises(ProviderError):
        call_with_retry(fn, max_attempts=3, sleep=lambda d: None, rng=random.Random(0))
    assert calls["n"] == 3


def test_idempotency_key_is_reused_across_retries():
    key = new_idempotency_key()
    seen: list[str] = []
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        seen.append(key)  # caller captures ONE key, reused every attempt
        if calls["n"] < 3:
            raise ProviderError("t", retryable=True)
        return "ok"

    call_with_retry(fn, max_attempts=5, sleep=lambda d: None)
    assert len(set(seen)) == 1  # same key across all attempts


def test_new_idempotency_key_is_unique():
    assert new_idempotency_key() != new_idempotency_key()


# --- TokenBucket --------------------------------------------------------------

def test_token_bucket_allows_burst_then_throttles():
    now = [0.0]
    slept: list[float] = []

    def clock():
        return now[0]

    def sleep(d):
        slept.append(d)
        now[0] += d

    tb = TokenBucket(60, clock=clock, sleep=sleep)  # rate 1/s, capacity 10
    for _ in range(10):
        assert tb.acquire() == 0.0  # burst capacity, no sleep
    wait = tb.acquire()  # 11th needs to wait ~1s at 1 token/s
    assert wait == pytest.approx(1.0, abs=1e-6)
    assert slept[-1] == pytest.approx(1.0, abs=1e-6)


def test_token_bucket_refills_over_time():
    now = [0.0]

    def clock():
        return now[0]

    tb = TokenBucket(60, clock=clock, sleep=lambda d: None)  # rate 1/s, cap 10
    for _ in range(10):
        tb.acquire()  # drain
    now[0] = 5.0  # 5 seconds pass -> ~5 tokens refilled
    assert tb.acquire() == 0.0  # a refilled token is available, no sleep


# --- AdaptiveConcurrency ------------------------------------------------------

def test_adaptive_starts_at_initial_clamped_to_max():
    assert AdaptiveConcurrency(3, 5).limit == 3
    assert AdaptiveConcurrency(9, 5).limit == 5  # clamped to max


def test_adaptive_throttle_halves_with_floor():
    ac = AdaptiveConcurrency(4, 8)
    ac.on_throttle()
    assert ac.limit == 2
    ac.on_throttle()
    assert ac.limit == 1
    ac.on_throttle()
    assert ac.limit == 1  # floor at min_limit (1)


def test_adaptive_success_streak_additively_increases_up_to_max():
    ac = AdaptiveConcurrency(2, 4)
    for _ in range(reliability.INCREASE_AFTER):
        ac.on_success()
    assert ac.limit == 3  # +1 after a full success streak
    for _ in range(reliability.INCREASE_AFTER):
        ac.on_success()
    assert ac.limit == 4
    for _ in range(reliability.INCREASE_AFTER * 3):
        ac.on_success()
    assert ac.limit == 4  # capped at max


def test_adaptive_slot_context_manager_acquires_and_releases():
    ac = AdaptiveConcurrency(1, 2)
    with ac.slot():
        pass  # acquire/release must not deadlock for a single holder
    # after release, a second slot is immediately available
    with ac.slot():
        pass


# --- build_client -------------------------------------------------------------

def test_build_client_uses_injected_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "path": request.url.path})

    client = build_client(transport=httpx.MockTransport(handler))
    try:
        r = client.get("https://example.test/v1/ping")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "path": "/v1/ping"}
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
