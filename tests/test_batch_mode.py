"""Tests for the (not-yet-implemented) run_batch entry point in generate.py.

run_batch(jobs, call_fn, *, concurrency=3, jitter_range=(0.1, 0.3)) -> list[dict]

Contract under test:
  - Each job in `jobs` is passed untouched to `call_fn(job)`.
  - Results are returned in the SAME ORDER as the input jobs, regardless of
    completion order.
  - At most `concurrency` jobs run call_fn concurrently at any instant.
  - A single job's exception must not abort the batch (failure isolation);
    that job's entry gets error set, all others still complete normally.
  - `jitter_range` kwarg must be accepted without erroring.
  - If failure rate > 30%, a degrade warning is printed to stderr mentioning
    "降级" or "concurrency" (case-insensitive).

This test file is written BEFORE run_batch exists (RED state of TDD). It must
never touch the real network -- everything is driven via
dependency-injected fake call_fn callables.
"""

from __future__ import annotations

import threading
import time

import pytest

from generate_image import cli as generate


# ---------------------------------------------------------------------------
# Order preservation
# ---------------------------------------------------------------------------


def test_run_batch_preserves_input_order_even_when_jobs_finish_out_of_order():
    """Jobs that sleep for varying (reversed) durations must still come back
    in the same order they were submitted, not completion order."""
    jobs = [{"prompt": f"job-{i}"} for i in range(5)]
    # Job 0 sleeps longest, job 4 sleeps shortest -> completion order is
    # reversed relative to input order if run_batch did NOT preserve order.
    sleep_times = [0.25, 0.2, 0.15, 0.1, 0.05]

    def call_fn(job):
        idx = int(job["prompt"].split("-")[1])
        time.sleep(sleep_times[idx])
        return f"result-{idx}"

    results = generate.run_batch(jobs, call_fn, concurrency=5)

    assert len(results) == 5
    for i, entry in enumerate(results):
        assert entry["job"] == jobs[i]
        assert entry["result"] == f"result-{i}"
        assert entry["error"] is None


# ---------------------------------------------------------------------------
# Bounded concurrency
# ---------------------------------------------------------------------------


def test_run_batch_bounds_concurrency_to_the_given_limit():
    """With 6 jobs and concurrency=2, no more than 2 should run call_fn at
    once, and wall-clock time should be roughly 3 * 0.2s (comfortably less
    than the fully-serial 6 * 0.2s)."""
    jobs = [{"prompt": f"job-{i}"} for i in range(6)]
    concurrency = 2

    lock = threading.Lock()
    current = 0
    max_seen = 0

    def call_fn(job):
        nonlocal current, max_seen
        with lock:
            current += 1
            max_seen = max(max_seen, current)
            assert current <= concurrency, (
                f"concurrency exceeded: {current} > {concurrency}"
            )
        time.sleep(0.2)
        with lock:
            current -= 1
        return job["prompt"]

    start = time.monotonic()
    results = generate.run_batch(jobs, call_fn, concurrency=concurrency)
    elapsed = time.monotonic() - start

    assert len(results) == 6
    assert max_seen <= concurrency
    assert max_seen >= 1  # sanity: work actually happened concurrently or not
    # 6 jobs / concurrency 2 => 3 sequential "waves" of ~0.2s each.
    # Generous margins to avoid flakiness on slow CI.
    assert 0.4 < elapsed < 1.2, f"unexpected elapsed time: {elapsed}"


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------


def test_run_batch_isolates_a_single_job_failure_without_aborting_the_batch():
    """5 jobs, job index 2 raises. The batch call itself must not raise;
    job 2's entry gets error set (result=None), the rest succeed normally."""
    jobs = [{"prompt": f"job-{i}"} for i in range(5)]

    def call_fn(job):
        idx = int(job["prompt"].split("-")[1])
        if idx == 2:
            raise ValueError("boom-job-2")
        return f"ok-{idx}"

    # Must not raise.
    results = generate.run_batch(jobs, call_fn, concurrency=3)

    assert len(results) == 5
    for i, entry in enumerate(results):
        assert entry["job"] == jobs[i]
        if i == 2:
            assert entry["result"] is None
            assert entry["error"] is not None
            assert "boom-job-2" in entry["error"]
        else:
            assert entry["result"] == f"ok-{i}"
            assert entry["error"] is None


# ---------------------------------------------------------------------------
# jitter_range kwarg acceptance
# ---------------------------------------------------------------------------


def test_run_batch_accepts_jitter_range_kwarg():
    """jitter_range must be accepted without erroring. Use (0, 0) to keep
    the test fast and deterministic -- no brittle timing assertions here."""
    jobs = [{"prompt": "only-job"}]

    def call_fn(job):
        return "done"

    results = generate.run_batch(
        jobs, call_fn, concurrency=3, jitter_range=(0, 0)
    )

    assert len(results) == 1
    assert results[0]["result"] == "done"
    assert results[0]["error"] is None


# ---------------------------------------------------------------------------
# Best-effort degrade signal
# ---------------------------------------------------------------------------


def test_run_batch_prints_degrade_warning_when_failure_rate_exceeds_30_percent(
    capsys,
):
    """5 jobs, 3 fail (60% failure rate, > 30% threshold) -> a warning
    mentioning '降级' or 'concurrency' (case-insensitive) must appear on
    stderr. Loose substring check only, per spec."""
    jobs = [{"prompt": f"job-{i}"} for i in range(5)]
    failing_indices = {0, 1, 2}

    def call_fn(job):
        idx = int(job["prompt"].split("-")[1])
        if idx in failing_indices:
            raise RuntimeError(f"fail-{idx}")
        return f"ok-{idx}"

    results = generate.run_batch(jobs, call_fn, concurrency=3)

    assert len(results) == 5

    captured = capsys.readouterr()
    stderr_lower = captured.err.lower()
    assert ("降级" in captured.err) or ("concurrency" in stderr_lower), (
        f"expected a degrade warning mentioning 降级/concurrency in stderr, "
        f"got: {captured.err!r}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
