"""SOTA-ish scheduling / reliability layer for the generate-image skill.

Provides the primitives the orchestrator composes per request/batch:

  * build_client()          — a pooled httpx.Client with separate connect/read/
                              write/pool timeouts; accepts an injectable transport
                              (httpx.MockTransport) so tests never touch the network.
  * ProviderError           — typed error carrying .retryable and .retry_after.
  * is_retryable_status()   — billing-aware HTTP status classification.
  * retry_after_seconds()   — parse the Retry-After header (integer seconds form).
  * backoff_delay()         — full-jitter exponential backoff (AWS canonical).
  * call_with_retry()       — tenacity-driven retry loop honoring Retry-After first,
                              then full-jitter backoff, bounded by max_attempts.
  * new_idempotency_key()   — uuid4 hex; the caller creates ONE per logical request
                              and reuses it across retries so a billing gateway can
                              dedupe (avoids double-charging on ambiguous retries).
  * TokenBucket             — thread-safe client-side rate limiter (avoid 429s).
  * AdaptiveConcurrency     — AIMD limiter: multiplicative-decrease on throttle,
                              additive-increase on sustained success.

The billing tension (image generation bills success AND failure) is encoded in
is_retryable_status(): 429/408 are always safe to retry (rejected before
generation); other 4xx never retry; 5xx/network are retried ONLY when the
provider does not bill failures OR supports idempotency keys.
"""

from __future__ import annotations

import random
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Callable, Mapping

import httpx
from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
)

# --- tuning knobs -------------------------------------------------------------
BACKOFF_BASE = 0.5   # seconds; first-retry backoff scale
BACKOFF_CAP = 8.0    # seconds; max single backoff wait
INCREASE_AFTER = 3   # AIMD: successes before additive concurrency increase

# Statuses that are safe to retry regardless of billing: the request was rejected
# before any (billable) generation happened.
_ALWAYS_RETRYABLE = frozenset({408, 429})


# --- HTTP client --------------------------------------------------------------

def build_client(*, transport: httpx.BaseTransport | None = None,
                 read_timeout: float = 300.0) -> httpx.Client:
    """A pooled httpx.Client. `transport` (e.g. httpx.MockTransport) is injected
    by tests so no real network call is made."""
    timeout = httpx.Timeout(connect=10.0, read=read_timeout, write=60.0, pool=10.0)
    limits = httpx.Limits(max_connections=16, max_keepalive_connections=8)
    return httpx.Client(
        transport=transport,
        timeout=timeout,
        limits=limits,
        headers={"User-Agent": "generate-image/1.0"},
        follow_redirects=True,
    )


# --- typed error + classification ---------------------------------------------

class ProviderError(Exception):
    """A provider call failure. `.retryable` drives call_with_retry; `.retry_after`
    (seconds) overrides backoff when the server told us how long to wait."""

    def __init__(self, msg: str, *, retryable: bool,
                 retry_after: float | None = None, status: int | None = None):
        super().__init__(msg)
        self.retryable = retryable
        self.retry_after = retry_after
        self.status = status


def is_retryable_status(status: int, *, bills_on_failure: bool,
                        supports_idempotency: bool,
                        throttle_statuses: frozenset[int] | None = None) -> bool:
    """Billing-aware retry decision for an HTTP status code.

    * 408/429 -> always retryable (rejected before a billable generation).
    * a status listed in `throttle_statuses` -> retryable. This exists because some
      gateways report a *rate limit* with a status that normally means something
      permanent. sensenova answers a too-fast call with 403
      "model is not available in the current token plan", which reads like an
      entitlement problem but clears on its own after a cooldown (measured: 403 in
      1-2s, then HTTP 200 twenty seconds later, on the same key and model).
      Treating that as permanent would turn a throttle into a hard failure.
      Only list a status here where the transient behaviour was actually observed —
      the default (None) keeps the strict classification for everyone else.
    * other 4xx -> never retryable (the request itself is malformed/unauthorized).
    * 5xx -> ambiguous (the server may have generated + billed already); retry
      ONLY when the provider does not bill failures, or supports idempotency keys
      so a retry is deduped.
    """
    if status in _ALWAYS_RETRYABLE:
        return True
    if throttle_statuses and status in throttle_statuses:
        return True
    if 400 <= status < 500:
        return False
    if status >= 500:
        return (not bills_on_failure) or supports_idempotency
    return False  # 2xx/3xx never reach the error path


def retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    """Parse a Retry-After header (integer-seconds form). Returns None if absent
    or in HTTP-date form (which we do not honor — backoff takes over)."""
    if not headers:
        return None
    raw = None
    for k, v in headers.items():
        if k.lower() == "retry-after":
            raw = v
            break
    if raw is None:
        return None
    try:
        secs = float(raw)
        return secs if secs >= 0 else None
    except (TypeError, ValueError):
        return None  # HTTP-date form; let exponential backoff handle it


# --- retry / backoff ----------------------------------------------------------

def backoff_delay(attempt: int, *, base: float = BACKOFF_BASE,
                  cap: float = BACKOFF_CAP, rng: random.Random | None = None,
                  floor: float = 0.0) -> float:
    """Full-jitter exponential backoff: uniform(floor, min(cap, base * 2**(attempt-1))).

    `attempt` is 1-based (1 = first retry). AWS "exponential backoff and jitter".

    `floor` raises the lower bound for gateways that cut the connection on
    back-to-back requests — there, a jittered wait of ~0s reproduces the very
    failure being retried. It also lifts the ceiling when needed so the window
    never inverts.
    """
    r = rng or random
    ceiling = min(cap, base * (2 ** max(0, attempt - 1)))
    if floor > 0:
        ceiling = max(ceiling, floor)
    return r.uniform(min(floor, ceiling), ceiling)


def new_idempotency_key() -> str:
    """A fresh idempotency key. Create ONE per logical request and reuse it across
    retries so a billing gateway can dedupe the retried call."""
    return uuid.uuid4().hex


def call_with_retry(fn: Callable[[], object], *, max_attempts: int,
                    sleep: Callable[[float], None] = time.sleep,
                    rng: random.Random | None = None,
                    before_sleep: Callable[[object], None] | None = None,
                    backoff_floor: float = 0.0) -> object:
    """Call `fn` with bounded retries. Retries only on ProviderError.retryable.
    Waits Retry-After when present, otherwise full-jitter exponential backoff.
    Re-raises the last exception once attempts are exhausted.

    `before_sleep(retry_state)` is invoked before each backoff wait — used to feed
    throttle signals (e.g. a 429) into an AIMD limiter.
    """

    def _retry_predicate(exc: BaseException) -> bool:
        return isinstance(exc, ProviderError) and exc.retryable

    def _wait(retry_state) -> float:
        exc = retry_state.outcome.exception()
        if isinstance(exc, ProviderError) and exc.retry_after is not None:
            return exc.retry_after
        return backoff_delay(retry_state.attempt_number, rng=rng, floor=backoff_floor)

    retryer = Retrying(
        retry=retry_if_exception(_retry_predicate),
        stop=stop_after_attempt(max_attempts),
        wait=_wait,
        sleep=sleep,
        before_sleep=before_sleep,
        reraise=True,
    )
    return retryer(fn)


# --- client-side rate limiting (token bucket) ---------------------------------

class TokenBucket:
    """Thread-safe token-bucket rate limiter. `acquire()` blocks until a token is
    available, proactively keeping request rate under the provider's RPM so we do
    not trip 429s in the first place.

    clock/sleep are injectable for deterministic tests.
    """

    def __init__(self, rpm: int, *, capacity: int | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.rate = max(1e-9, rpm / 60.0)          # tokens per second
        self.capacity = capacity if capacity is not None else max(1, rpm // 6)
        self._tokens = float(self.capacity)
        self._clock = clock
        self._sleep = sleep
        self._last = clock()
        self._lock = threading.Lock()

    def acquire(self, n: int = 1) -> float:
        """Consume `n` tokens, sleeping if necessary. Returns the seconds slept."""
        with self._lock:
            now = self._clock()
            self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
            self._last = now
            if self._tokens >= n:
                self._tokens -= n
                return 0.0
            wait = (n - self._tokens) / self.rate
            self._sleep(wait)
            self._tokens = 0.0
            self._last = self._clock()
            return wait


# --- adaptive concurrency (AIMD) ----------------------------------------------

class AdaptiveConcurrency:
    """AIMD concurrency limiter. Start at `initial`; on throttle (429) halve the
    limit (multiplicative decrease, floor `min_limit`); after `INCREASE_AFTER`
    consecutive successes, raise it by one (additive increase, ceiling `maximum`).

    Use via `with limiter.slot(): ...` to gate an in-flight request.
    """

    def __init__(self, initial: int, maximum: int, *, min_limit: int = 1):
        self._max = max(1, maximum)
        self._min = max(1, min_limit)
        self._limit = max(self._min, min(initial, self._max))
        self._in_flight = 0
        self._success_streak = 0
        self._cond = threading.Condition()

    @property
    def limit(self) -> int:
        with self._cond:
            return self._limit

    def acquire(self) -> None:
        with self._cond:
            while self._in_flight >= self._limit:
                self._cond.wait()
            self._in_flight += 1

    def release(self) -> None:
        with self._cond:
            self._in_flight -= 1
            self._cond.notify()

    @contextmanager
    def slot(self):
        self.acquire()
        try:
            yield
        finally:
            self.release()

    def on_success(self) -> None:
        with self._cond:
            self._success_streak += 1
            if self._success_streak >= INCREASE_AFTER and self._limit < self._max:
                self._limit += 1
                self._success_streak = 0
                self._cond.notify()

    def on_throttle(self) -> None:
        """Called on a 429 / rate-limit signal: halve the limit."""
        with self._cond:
            self._limit = max(self._min, self._limit // 2)
            self._success_streak = 0
