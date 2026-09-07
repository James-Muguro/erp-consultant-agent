"""
Timeout and retry helpers used to bound and harden blocking calls (LLM
requests, agent phase execution) so a hung network call or a transient
provider blip can't stall or crash the whole application.

Honest limitation: run_with_timeout bounds how long the *caller* waits, not
how long the underlying call actually runs. Python has no safe way to kill
a running thread, so on timeout the original call keeps executing in an
orphaned background thread until it naturally finishes or errors - it just
stops being anyone's problem. This is the standard, documented tradeoff of
thread-based timeouts in Python; a hard-kill would require running the call
in a separate process instead, which is a much bigger change than this
stage's scope. What this DOES reliably guarantee: the caller (a phase
execution, an HTTP request) is never blocked longer than `timeout` seconds
waiting for a response.
"""
import time
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, TypeVar

from src.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# Real backoff delay is only valuable outside tests - under pytest it just
# adds seconds of real wall-clock sleep to tests that deliberately exercise
# the retry/fallback path (mocking every tier to fail), with no benefit,
# since nothing is actually transient in a mocked failure. Same pattern
# used for API rate limiting in orchestrator_api.py.
_TESTING = "pytest" in sys.modules
DEFAULT_RETRY_BASE_DELAY = 0.01 if _TESTING else 1.5

# A small shared pool rather than one-thread-per-call - callers of these
# helpers are already infrequent, latency-bound operations (LLM calls), not
# a hot path needing per-call executor setup/teardown cost.
_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="resilience")


class OperationTimeoutError(TimeoutError):
    """Raised when a call exceeds its allotted time. Distinct from the
    stdlib TimeoutError so callers can catch this specifically without also
    catching unrelated timeout errors from other libraries."""
    def __init__(self, timeout: float):
        super().__init__(f"Operation timed out after {timeout}s")
        self.timeout = timeout


def run_with_timeout(fn: Callable[..., T], *args, timeout: float, **kwargs) -> T:
    """Runs fn(*args, **kwargs) and waits at most `timeout` seconds for a
    result. Raises OperationTimeoutError if it doesn't finish in time -
    see module docstring for what that guarantee does and doesn't cover."""
    future = _executor.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError:
        raise OperationTimeoutError(timeout)


def call_with_retries(
    fn: Callable[..., T],
    *args,
    max_attempts: int = 2,
    base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    timeout: float | None = None,
    on_retry: Callable[[int, Exception], None] | None = None,
    **kwargs,
) -> T:
    """Calls fn(*args, **kwargs), retrying on any exception up to
    max_attempts total attempts, with exponential backoff (base_delay *
    2**attempt_index) between attempts. If `timeout` is given, each
    individual attempt is bounded via run_with_timeout - a timeout counts
    as a failed attempt like any other exception, so it's retried too
    (up to max_attempts).

    Retries on any exception rather than a curated list of "transient"
    exception types deliberately - the four LLM providers behind this raise
    different SDK-specific exception classes for the same underlying
    problem (rate limit, network blip), and maintaining a precise
    per-provider transient/permanent classification is a lot of ongoing
    maintenance for a nuance that mostly doesn't change the outcome here:
    a permanent error (e.g. a bad API key) will just fail max_attempts
    times quickly and move on to the next fallback tier exactly as it
    would have without retries, at the cost of a few extra seconds - not
    a correctness problem, just a small, bounded latency cost.

    Raises the last exception if every attempt fails.
    """
    last_exception: Exception | None = None
    for attempt in range(max_attempts):
        try:
            if timeout is not None:
                return run_with_timeout(fn, *args, timeout=timeout, **kwargs)
            return fn(*args, **kwargs)
        except Exception as e:
            last_exception = e
            is_last_attempt = attempt == max_attempts - 1
            if is_last_attempt:
                break
            if on_retry:
                on_retry(attempt, e)
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Attempt {attempt + 1}/{max_attempts} failed: {e}. Retrying in {delay:.1f}s")
            time.sleep(delay)

    assert last_exception is not None
    raise last_exception
