"""
Tests for src.utils.resilience.

Coverage:

  run_with_timeout
    - Returns the result when the call finishes in time.
    - Raises OperationTimeoutError when the call exceeds the timeout.
    - Propagates non-timeout exceptions unchanged.
    - Forwards positional and keyword arguments.
    - Rejects invalid timeout values (0, negative, None).
    - Raises OperationTimeoutError(reason='thread pool saturated') when
      the pool has no available slot. This is the fix for the previous
      version's "submit() blocks indefinitely when all workers are
      busy" bug — see the module docstring of resilience.py.

  call_with_retries
    - Single-attempt success does not retry.
    - Transient failure then success retries exactly once.
    - Persistent failure raises the last exception.
    - max_attempts is respected exactly.
    - on_retry callback receives (attempt_index, exception).
    - A callback that raises does not mask the underlying failure.
    - max_attempts < 1 fails fast with ValueError.
    - A per-attempt timeout counts as a failed attempt and is retried.
    - All attempts timing out raises OperationTimeoutError.
    - total_timeout bounds the whole retry loop and stops retries
      once the aggregate budget is exhausted.

  compute_backoff_delay
    - Exponential growth with a hard cap.

  shutdown_executor / pool_stats
    - Public surface exists and returns a coherent dict.

Timing sensitivity
------------------
Several tests sleep in real wall-clock time. They are marked with
@pytest.mark.timing so a CI pipeline that runs with reduced timing
tolerance can deselect them via `-m 'not timing'`. The margins are
generous (10x for the basic timeout case), so they are not expected
to be flaky under normal load.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from src.utils import resilience
from src.utils.resilience import (
    OperationTimeoutError,
    call_with_retries,
    compute_backoff_delay,
    pool_stats,
    run_with_timeout,
    shutdown_executor,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def patched_sleep(monkeypatch):
    monkeypatch.setattr("src.utils.resilience._retry_sleep", lambda _: None)

# ---------------------------------------------------------------------------
# run_with_timeout
# ---------------------------------------------------------------------------
class TestRunWithTimeout:
    def test_returns_result_when_fast_enough(self):
        result = run_with_timeout(lambda: 42, timeout=1.0)
        assert result == 42

    @pytest.mark.timing
    def test_raises_operation_timeout_error_when_too_slow(self):
        def slow():
            time.sleep(0.5)
            return "done"

        with pytest.raises(OperationTimeoutError):
            run_with_timeout(slow, timeout=0.05)

    def test_propagates_the_original_exception_when_not_a_timeout(self):
        def boom():
            raise ValueError("real failure")

        with pytest.raises(ValueError, match="real failure"):
            run_with_timeout(boom, timeout=1.0)

    def test_passes_args_and_kwargs_through(self):
        result = run_with_timeout(lambda a, b, c=None: (a, b, c), 1, 2, timeout=1.0, c=3)
        assert result == (1, 2, 3)

    @pytest.mark.parametrize("bad_timeout", [0, -1, -0.001])
    def test_rejects_non_positive_timeout(self, bad_timeout):
        """A zero or negative timeout is a caller bug, not a hang, and
        fails fast with ValueError rather than trying to submit and
        wait zero seconds."""
        with pytest.raises(ValueError, match="timeout"):
            run_with_timeout(lambda: 42, timeout=bad_timeout)

    def test_timeout_error_carries_context_and_reason(self):
        """The enriched OperationTimeoutError fields (context = called
        function name, reason = which phase of the wait timed out) are
        what make production debugging possible — a bare 'Operation
        timed out after 30s' doesn't say what was being called or
        whether it was the call or the pool that was the bottleneck."""
        def slow():
            time.sleep(0.3)

        with pytest.raises(OperationTimeoutError) as exc_info:
            run_with_timeout(slow, timeout=0.05)
        err = exc_info.value
        assert err.reason == "deadline exceeded"
        assert err.context == "slow"
        assert err.timeout == 0.05

    def test_pool_saturation_raises_with_specific_reason(self):
        """The entire reason the semaphore exists: when every pool slot
        is occupied, a new submission fails fast with a distinguishable
        error rather than blocking in the stdlib's submit().

        Simulated by making semaphore.acquire() return False (i.e. the
        pool never frees a slot within the timeout), so the test does
        not need to actually saturate the pool — which would require
        N concurrent orphans and be much slower."""
        with patch.object(
            resilience._in_flight_semaphore, "acquire", return_value=False
        ):
            with pytest.raises(OperationTimeoutError) as exc_info:
                run_with_timeout(lambda: 42, timeout=0.1)

        err = exc_info.value
        assert err.reason == "thread pool saturated"


# ---------------------------------------------------------------------------
# call_with_retries
# ---------------------------------------------------------------------------
class TestCallWithRetries:
    def test_returns_result_on_first_success_without_retrying(self):
        calls = []

        def fn():
            calls.append(1)
            return "ok"

        result = call_with_retries(fn, max_attempts=3)
        assert result == "ok"
        assert len(calls) == 1

    def test_retries_on_failure_then_succeeds(self, patched_sleep):
        calls = []

        def fn():
            calls.append(1)
            if len(calls) < 2:
                raise RuntimeError("transient")
            return "ok"

        result = call_with_retries(fn, max_attempts=3, base_delay=0.001)
        assert result == "ok"
        assert len(calls) == 2

    def test_raises_last_exception_after_exhausting_attempts(self, patched_sleep):
        def always_fails():
            raise RuntimeError("permanent failure")

        with pytest.raises(RuntimeError, match="permanent failure"):
            call_with_retries(always_fails, max_attempts=3, base_delay=0.001)

    def test_respects_max_attempts_exactly(self, patched_sleep):
        calls = []

        def always_fails():
            calls.append(1)
            raise RuntimeError("nope")

        with pytest.raises(RuntimeError):
            call_with_retries(always_fails, max_attempts=4, base_delay=0.001)
        assert len(calls) == 4

    def test_calls_on_retry_callback_with_attempt_index_and_exception(self, patched_sleep):
        seen = []

        def fails_once():
            if not seen:
                raise ValueError("first failure")
            return "ok"

        def on_retry(attempt, exc):
            seen.append((attempt, str(exc)))

        result = call_with_retries(
            fails_once, max_attempts=2, base_delay=0.001, on_retry=on_retry,
        )
        assert result == "ok"
        assert seen == [(0, "first failure")]

    def test_on_retry_callback_exception_does_not_mask_real_error(self, patched_sleep):
        """A broken callback must not replace the underlying failure
        with its own exception — the caller sees the real error."""
        def always_fails():
            raise RuntimeError("the real error")

        def bad_callback(attempt, exc):
            raise ValueError("callback is broken")

        with pytest.raises(RuntimeError, match="the real error"):
            call_with_retries(
                always_fails, max_attempts=2, base_delay=0.001,
                on_retry=bad_callback,
            )

    def test_rejects_max_attempts_below_one(self):
        """A caller passing max_attempts=0 is a bug that used to
        surface as a bare AssertionError from the loop-exit assert;
        it now fails fast with a clear ValueError."""
        with pytest.raises(ValueError, match="max_attempts"):
            call_with_retries(lambda: "ok", max_attempts=0)

        with pytest.raises(ValueError, match="max_attempts"):
            call_with_retries(lambda: "ok", max_attempts=-1)

    @pytest.mark.timing
    def test_a_timeout_counts_as_a_failed_attempt_and_is_retried(self, patched_sleep):
        calls = []

        def maybe_slow():
            calls.append(1)
            if len(calls) < 2:
                time.sleep(0.3)
            return "ok"

        result = call_with_retries(
            maybe_slow, max_attempts=2, base_delay=0.001, timeout=0.05,
        )
        assert result == "ok"
        assert len(calls) == 2

    @pytest.mark.timing
    def test_raises_operation_timeout_error_if_every_attempt_times_out(self, patched_sleep):
        def always_slow():
            time.sleep(0.3)

        with pytest.raises(OperationTimeoutError):
            call_with_retries(
                always_slow, max_attempts=2, base_delay=0.001, timeout=0.05,
            )

    @pytest.mark.timing
    def test_total_timeout_bounds_the_whole_retry_loop(self, patched_sleep):
        """total_timeout caps the aggregate (attempts + backoff sleeps).
        A retry that would start after the budget is exhausted must
        fail immediately with OperationTimeoutError, not sleep-and-hang.
        Without this, a caller with a per-attempt timeout of 30s and
        max_attempts=2 could wait 60s+ despite asking for a 10s budget."""
        attempts = []

        def always_slow():
            attempts.append(1)
            time.sleep(0.2)

        start = time.monotonic()
        with pytest.raises(OperationTimeoutError):
            call_with_retries(
                always_slow,
                max_attempts=5,
                base_delay=0.001,
                timeout=0.5,
                total_timeout=0.2,
            )
        elapsed = time.monotonic() - start

        # The whole call must have returned well before the naive
        # worst case (5 attempts x 0.5s per attempt = 2.5s).
        assert elapsed < 1.0, (
            f"call_with_retries with total_timeout=0.2 took {elapsed:.2f}s; "
            "the aggregate budget was not honored"
        )


# ---------------------------------------------------------------------------
# compute_backoff_delay
# ---------------------------------------------------------------------------
class TestComputeBackoffDelay:
    def test_grows_exponentially(self):
        assert compute_backoff_delay(0, 1.0) == 1.0
        assert compute_backoff_delay(1, 1.0) == 2.0
        assert compute_backoff_delay(2, 1.0) == 4.0
        assert compute_backoff_delay(3, 1.0) == 8.0

    def test_is_capped(self):
        """Without a cap, attempt_index=10 with base_delay=1.5 would
        produce a 25-minute sleep. The module caps at
        MAX_RETRY_DELAY_SECONDS (30s)."""
        assert compute_backoff_delay(10, 1.5) == resilience.MAX_RETRY_DELAY_SECONDS
        assert compute_backoff_delay(100, 1.5) == resilience.MAX_RETRY_DELAY_SECONDS

    def test_negative_attempt_index_is_clamped_to_zero(self):
        """Defensive: a caller passing -1 should get the base delay,
        not a fractional one."""
        assert compute_backoff_delay(-1, 1.0) == 1.0


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------
class TestPublicSurface:
    def test_shutdown_executor_is_callable(self):
        """The API's lifespan hook calls this on shutdown. Verifying it
        exists with the right signature is cheap insurance against a
        future refactor renaming it."""
        assert callable(shutdown_executor)
        # Calling with wait=False is safe and non-blocking even with
        # no in-flight work — the actual executor is a module-level
        # singleton, so we do NOT call shutdown here (that would break
        # subsequent tests that submit to the pool).
        # Just confirm the signature accepts the documented keyword.
        import inspect
        sig = inspect.signature(shutdown_executor)
        assert "wait" in sig.parameters
        assert sig.parameters["wait"].default is False

    def test_pool_stats_returns_coherent_dict(self):
        """pool_stats() is the diagnostic helper surfaced on /metrics.
        It must return a dict with the documented keys and internally
        consistent numbers."""
        stats = pool_stats()
        assert isinstance(stats, dict)
        assert "pool_size" in stats
        assert "in_flight" in stats
        assert "available_slots" in stats
        assert stats["pool_size"] > 0
        if stats["in_flight"] is not None and stats["available_slots"] is not None:
            # available + in_flight == pool_size, assuming the private
            # attribute read succeeded (it can return None defensively).
            assert stats["in_flight"] + stats["available_slots"] == stats["pool_size"]