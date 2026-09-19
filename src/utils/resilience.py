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
in a separate process instead.

What this DOES reliably guarantee - and what the previous revision of this
module quietly failed to guarantee under load:

  * A caller of run_with_timeout waits at most `timeout` seconds for a
    result, *including* the time spent waiting for a pool slot.
  * When the pool is saturated (all workers occupied by hung calls), a new
    call fails fast with OperationTimeoutError(reason='pool saturated')
    rather than blocking in ThreadPoolExecutor.submit().

The saturation failure mode is real and was the previous version's
Achilles' heel: a hung tier-1 provider could occupy every worker, at which
point the next submit() blocked indefinitely inside the stdlib. Bounding
in-flight submissions with a semaphore prevents that, at the cost that
saturated calls fail fast and let the caller try the next fallback tier
(which may run in a different worker slot freed by a *successful* prior
call). If saturation is observed in production, the correct fix is to
raise LLM_MAX_CONCURRENT_CALLS, not to remove the semaphore.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
)
from typing import Any, Callable, Optional, Tuple, TypeVar

from src.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# Real backoff delay is only valuable outside tests - under pytest it just
# adds seconds of real wall-clock sleep to tests that deliberately exercise
# the retry/fallback path (mocking every tier to fail), with no benefit,
# since nothing is actually transient in a mocked failure. PYTEST_CURRENT_TEST
# is set per-test by pytest and is the more reliable signal; we fall back
# to the module-presence check for older pytest integrations.
_TESTING = bool(os.environ.get("PYTEST_CURRENT_TEST")) or ("pytest" in sys.modules)
DEFAULT_RETRY_BASE_DELAY = 0.01 if _TESTING else 1.5

# Cap exponential backoff so max_attempts=10 doesn't produce a 384s sleep.
MAX_RETRY_DELAY_SECONDS = 30.0

# Pool sizing. The default (16) is fine for a single chat endpoint; multi-
# agent pipelines running concurrently can saturate this quickly, so it's
# overridable via settings if present. We deliberately don't import
# settings at module load to avoid an import cycle with settings -> logger.
try:
    from src.config.settings import settings as _settings  # type: ignore
    _POOL_SIZE = int(getattr(_settings, "llm_max_concurrent_calls", 16) or 16)
except Exception:  # noqa: BLE001 - settings is optional at import time
    _POOL_SIZE = 16

# Pool state is lazily created and re-creatable. shutdown_executor()
# clears the reference rather than leaving a shut-down executor in
# place, so a subsequent call to run_with_timeout recreates the pool
# instead of raising RuntimeError. This matters because the API's
# lifespan hook calls shutdown_executor() on every TestClient context
# exit, and there are dozens of those in the test suite; without
# re-creation, the first lifespan shutdown would permanently break
# every later test that calls run_with_timeout.
_executor_lock = threading.Lock()
_executor: Optional[ThreadPoolExecutor] = None
_in_flight_semaphore: Optional[threading.BoundedSemaphore] = None


def _ensure_pool() -> Tuple[ThreadPoolExecutor, threading.BoundedSemaphore]:
    """Return the (executor, semaphore) pair, creating them if needed."""
    global _executor, _in_flight_semaphore
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=_POOL_SIZE,
                thread_name_prefix="resilience",
            )
            _in_flight_semaphore = threading.BoundedSemaphore(_POOL_SIZE)
        return _executor, _in_flight_semaphore


def shutdown_executor(wait: bool = False) -> None:
    """Release the shared executor. A subsequent run_with_timeout call
    will recreate the pool lazily, so this is safe to call more than
    once per process — a property the API's lifespan hook relies on
    in test runs where the app is entered and exited many times."""
    global _executor, _in_flight_semaphore
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=wait)
            _executor = None
            _in_flight_semaphore = None


def pool_stats() -> dict:
    """Lightweight observability into the shared pool."""
    with _executor_lock:
        if _in_flight_semaphore is None:
            return {
                "pool_size": _POOL_SIZE,
                "in_flight": 0,
                "available_slots": _POOL_SIZE,
            }
        try:
            available = _in_flight_semaphore._value  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            available = None
    in_flight = None if available is None else _POOL_SIZE - available
    return {
        "pool_size": _POOL_SIZE,
        "in_flight": in_flight,
        "available_slots": available,
    }


class OperationTimeoutError(TimeoutError):
    """Raised when a call exceeds its allotted time. Distinct from the
    stdlib TimeoutError so callers can catch this specifically without also
    catching unrelated timeout errors from other libraries."""

    def __init__(
        self,
        timeout: float,
        *,
        context: Optional[str] = None,
        reason: str = "deadline exceeded",
    ):
        msg = f"Operation timed out after {timeout}s ({reason})"
        if context:
            msg = f"{msg} [call={context}]"
        super().__init__(msg)
        self.timeout = timeout
        self.context = context
        self.reason = reason


def _describe_callable(fn: Any) -> str:
    """Best-effort human-readable name for a callable, used in error
    messages. functools.partial and bound methods have no __name__."""
    if fn is None:
        return "<unknown>"
    name = getattr(fn, "__name__", None)
    if name:
        return name
    inner = getattr(fn, "func", None)
    if inner is not None:
        inner_name = getattr(inner, "__name__", None)
        if inner_name:
            return inner_name
    return type(fn).__name__


def compute_backoff_delay(attempt_index: int, base_delay: float) -> float:
    """Exponential backoff with a hard cap. attempt_index is 0-based (the
    delay *after* attempt 0). Exposed so callers with their own retry loops
    (e.g. the streaming path in llm.py) can apply the same policy without
    duplicating the cap logic."""
    return min(base_delay * (2 ** max(0, attempt_index)), MAX_RETRY_DELAY_SECONDS)


def _release_when_done(sem: threading.BoundedSemaphore, fn: Callable[..., T], *args, **kwargs) -> T:
    """Runs fn and always releases the semaphore slot. The semaphore is
    released by the *worker thread* when the underlying call actually
    completes (or raises), not by the caller on timeout, because on timeout
    the call is still occupying a worker."""
    try:
        return fn(*args, **kwargs)
    finally:
        sem.release()


def run_with_timeout(
    fn: Callable[..., T],
    *args,
    timeout: float,
    **kwargs,
) -> T:
    """Runs fn(*args, **kwargs) and waits at most `timeout` seconds for a
    result, including the time spent acquiring a pool slot.

    Raises:
        OperationTimeoutError: if the wait exceeded `timeout` seconds for
            any reason - slow call, slow pool acquisition, or full pool.
    """
    if timeout is None or timeout <= 0:
        # A zero/negative timeout is a caller bug, not a hang; raise
        # immediately rather than trying to submit and wait zero seconds.
        raise ValueError(f"run_with_timeout requires timeout > 0, got {timeout!r}")

    deadline = time.monotonic() + timeout
    context = _describe_callable(fn)

    executor, semaphore = _ensure_pool()

    # Bound the acquire to the caller's deadline, so a saturated pool
    # fails the caller fast rather than blocking in submit().
    acquired = semaphore.acquire(timeout=timeout)
    if not acquired:
        raise OperationTimeoutError(
            timeout, context=context, reason="thread pool saturated"
        )

    # From here on, if we can't submit, we must release the slot we hold.
    try:
        future: Future = executor.submit(_release_when_done, semaphore, fn, *args, **kwargs)
    except RuntimeError:
        # Executor has been shut down (typically only during test teardown
        # or interpreter shutdown). Release and re-raise.
        semaphore.release()
        raise

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        # We spent our whole budget waiting for a slot; the worker will
        # still release the semaphore when it finishes.
        raise OperationTimeoutError(
            timeout, context=context, reason="deadline consumed before submit"
        )

    try:
        return future.result(timeout=remaining)
    except FutureTimeoutError:
        # Deliberately do NOT release the semaphore: the worker thread is
        # still running fn, and the semaphore slot must stay occupied
        # until _release_when_done sees it finish. Otherwise we'd allow
        # more concurrent submissions than we have workers.
        raise OperationTimeoutError(timeout, context=context, reason="deadline exceeded")

def _retry_sleep(delay: float) -> None:
    """Sleep between retry attempts.

    Kept behind a small wrapper so tests can disable retry backoff without
    replacing time.sleep globally. The latter would also disable the real
    sleep used by functions under test.
    """
    time.sleep(delay)

def call_with_retries(
    fn: Callable[..., T],
    *args,
    max_attempts: int = 2,
    base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    timeout: Optional[float] = None,
    total_timeout: Optional[float] = None,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
    **kwargs,
) -> T:
    """Calls fn(*args, **kwargs), retrying on any exception up to
    max_attempts total attempts, with exponential backoff (base_delay *
    2**attempt_index, capped at MAX_RETRY_DELAY_SECONDS) between attempts.

    If `timeout` is given, each individual attempt is bounded via
    run_with_timeout - a timeout counts as a failed attempt like any other
    exception, so it's retried too (up to max_attempts).

    If `total_timeout` is given, the *entire* retry loop (all attempts plus
    all backoff sleeps) is bounded to that many seconds. When the remaining
    budget is smaller than the per-attempt `timeout`, the smaller value is
    used, and if the budget is exhausted the call raises immediately rather
    than starting another attempt that would necessarily time out.

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

    if max_attempts is None or max_attempts < 1:
        # Fail loudly rather than silently skipping the loop and hitting
        # a bare assert (the previous behaviour when max_attempts=0).
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts!r}")

    context = _describe_callable(fn)
    overall_deadline = (
        time.monotonic() + total_timeout if total_timeout is not None else None
    )

    last_exception: Optional[Exception] = None

    for attempt in range(max_attempts):
        # Compute the effective per-attempt timeout: min(per-attempt,
        # remaining-total-budget). If the budget is already exhausted,
        # fail immediately rather than start a doomed attempt.
        effective_timeout = timeout
        if overall_deadline is not None:
            remaining = overall_deadline - time.monotonic()
            if remaining <= 0:
                if last_exception is not None:
                    # We already have a real failure to report; the total
                    # budget running out is what stopped further retries.
                    raise last_exception
                raise OperationTimeoutError(
                    total_timeout or 0.0,
                    context=context,
                    reason="total_timeout budget exhausted before first attempt",
                )
            if effective_timeout is None:
                effective_timeout = remaining
            else:
                effective_timeout = min(effective_timeout, remaining)

        try:
            if effective_timeout is not None:
                result = run_with_timeout(
                    fn, *args, timeout=effective_timeout, **kwargs
                )
            else:
                result = fn(*args, **kwargs)

            # The aggregate deadline applies to successful results too. A call
            # completing at or after the total deadline did not complete within
            # the caller's requested budget.
            if overall_deadline is not None and time.monotonic() >= overall_deadline:
                raise OperationTimeoutError(
                    total_timeout or 0.0,
                    context=context,
                    reason="total_timeout budget exhausted",
                )

            return result
        except Exception as e:
            last_exception = e
            is_last_attempt = attempt == max_attempts - 1
            if is_last_attempt:
                break

            if on_retry is not None:
                try:
                    on_retry(attempt, e)
                except Exception as cb_err:  # noqa: BLE001
                    # A broken callback must never mask the real error we
                    # are about to retry.
                    logger.warning(
                        f"on_retry callback raised and was ignored: {cb_err}"
                    )

            delay = compute_backoff_delay(attempt, base_delay)

            # Don't sleep longer than the remaining total budget; if
            # sleeping would exhaust it, fail now rather than sleep and
            # then immediately fail.
            if overall_deadline is not None:
                remaining = overall_deadline - time.monotonic()
                if remaining <= 0:
                    break
                delay = min(delay, remaining)

            logger.warning(
                f"Attempt {attempt + 1}/{max_attempts} failed for {context}: {e}. "
                f"Retrying in {delay:.1f}s"
            )
            _retry_sleep(delay)

    assert last_exception is not None
    raise last_exception