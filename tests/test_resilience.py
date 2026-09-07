import time
import pytest

from src.utils.resilience import run_with_timeout, call_with_retries, OperationTimeoutError


class TestRunWithTimeout:
    def test_returns_result_when_fast_enough(self):
        result = run_with_timeout(lambda: 42, timeout=1.0)
        assert result == 42

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


class TestCallWithRetries:
    def test_returns_result_on_first_success_without_retrying(self):
        calls = []

        def fn():
            calls.append(1)
            return "ok"

        result = call_with_retries(fn, max_attempts=3)
        assert result == "ok"
        assert len(calls) == 1

    def test_retries_on_failure_then_succeeds(self):
        calls = []

        def fn():
            calls.append(1)
            if len(calls) < 2:
                raise RuntimeError("transient")
            return "ok"

        result = call_with_retries(fn, max_attempts=3, base_delay=0.001)
        assert result == "ok"
        assert len(calls) == 2

    def test_raises_last_exception_after_exhausting_attempts(self):
        def always_fails():
            raise RuntimeError("permanent failure")

        with pytest.raises(RuntimeError, match="permanent failure"):
            call_with_retries(always_fails, max_attempts=3, base_delay=0.001)

    def test_respects_max_attempts_exactly(self):
        calls = []

        def always_fails():
            calls.append(1)
            raise RuntimeError("nope")

        with pytest.raises(RuntimeError):
            call_with_retries(always_fails, max_attempts=4, base_delay=0.001)
        assert len(calls) == 4

    def test_calls_on_retry_callback_with_attempt_index_and_exception(self):
        seen = []

        def fails_once():
            if not seen:
                raise ValueError("first failure")
            return "ok"

        def on_retry(attempt, exc):
            seen.append((attempt, str(exc)))

        result = call_with_retries(fails_once, max_attempts=2, base_delay=0.001, on_retry=on_retry)
        assert result == "ok"
        assert seen == [(0, "first failure")]

    def test_a_timeout_counts_as_a_failed_attempt_and_is_retried(self):
        calls = []

        def maybe_slow():
            calls.append(1)
            if len(calls) < 2:
                time.sleep(0.3)
            return "ok"

        result = call_with_retries(maybe_slow, max_attempts=2, base_delay=0.001, timeout=0.05)
        assert result == "ok"
        assert len(calls) == 2

    def test_raises_operation_timeout_error_if_every_attempt_times_out(self):
        def always_slow():
            time.sleep(0.3)

        with pytest.raises(OperationTimeoutError):
            call_with_retries(always_slow, max_attempts=2, base_delay=0.001, timeout=0.05)
