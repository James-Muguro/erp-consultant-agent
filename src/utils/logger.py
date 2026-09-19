"""
Logging and metrics for the ERP consultant backend.

Provides:
  * get_logger(name)         - structlog logger factory (unchanged API)
  * AgentLogger              - agent-facing wrapper (API extended additively)
  * MetricsCollector         - thread-safe, bounded task metrics
  * bind_log_context / log_context / clear_log_context
                             - request-scoped context binding so session_id,
                               user_id, request_id, and agent_name appear on
                               every log line automatically

Correlation context: structlog.contextvars.merge_contextvars is in the
processor chain, so any values bound via bind_log_context appear as
top-level fields in every JSON log line emitted inside the same async
task or thread. The API layer's middleware should bind session_id /
user_id / request_id once per request; agents optionally bind agent_name.
Without that, logs from concurrent requests are indistinguishable.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Any, Deque, Dict, Iterator, List, Optional

import structlog

from src.config.settings import settings


# ---------------------------------------------------------------------------
# structlog configuration
# ---------------------------------------------------------------------------
# Reserved structlog field names. Passing any of these as a keyword
# argument to a BoundLogger method raises TypeError ("got multiple values
# for argument"). AgentLogger sanitizes them below, so callers can still
# pass e.g. `level="high"` on a business log line without crashing.
_RESERVED_STRUCTLOG_KEYS: frozenset = frozenset({
    # structlog's own reserved keys.
    "event",
    "level",

    # stdlib logging.LogRecord reserved attributes. Passing any of these
    # as a keyword to a stdlib-backed logger raises
    #   KeyError("Attempt to overwrite '<name>' in LogRecord")
    # because Logger._log treats them as extra record fields and refuses
    # to overwrite the reserved attribute. They must be renamed before
    # the call reaches the stdlib layer. This set is the union of the
    # documented LogRecord attributes as of Python 3.11 — if a new
    # reserved attribute is added in a future Python release, add it
    # here and every AgentLogger call site is automatically protected.
    "name", "msg", "args",
    "levelname", "levelno",
    "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info",
    "lineno", "funcName",
    "created", "msecs", "relativeCreated",
    "thread", "threadName",
    "process", "processName", "taskName",

    # structlog's stdlib wrapper also treats these specially.
    "logger", "timestamp", "stacklevel",
})


def _configure_structlog() -> None:
    """Idempotent structlog setup. Safe to call multiple times."""
    if structlog.is_configured():
        return
    renderer = (
        structlog.processors.JSONRenderer()
        if (settings.log_format or "").strip().lower() == "json"
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            renderer,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: Optional[str] = None):
    """Return a structlog logger. Configures structlog on first call."""
    _configure_structlog()
    return structlog.get_logger(name)


# ---------------------------------------------------------------------------
# Request / session correlation context
# ---------------------------------------------------------------------------
# These wrap structlog.contextvars so the rest of the codebase never
# imports structlog directly. Contextvars are task-local under asyncio
# and thread-local under threads, which is what makes them safe to use
# across concurrent agent runs on different sessions.
def bind_log_context(**kwargs: Any) -> None:
    """Bind values (session_id, user_id, request_id, agent_name, ...)
    onto the current task/thread's log context. Every log line emitted
    inside this scope includes them as top-level fields."""
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_log_context(*keys: str) -> None:
    """Remove specific keys bound earlier. No-op for keys not bound."""
    structlog.contextvars.unbind_contextvars(*keys)


def clear_log_context() -> None:
    """Clear the entire bound context. Use at the outer boundary of a
    request; using this inside a nested scope wipes any outer bindings
    too - prefer unbind_log_context(*keys) for scoped cleanup."""
    structlog.contextvars.clear_contextvars()


@contextmanager
def log_context(**kwargs: Any) -> Iterator[None]:
    """Context manager that binds `kwargs` for the duration of the block
    and unbinds exactly those keys on exit. Safe to nest: unbinding is
    scoped to the keys this context added, so outer bindings survive."""
    if not kwargs:
        yield
        return
    bind_log_context(**kwargs)
    try:
        yield
    finally:
        unbind_log_context(*kwargs.keys())


# ---------------------------------------------------------------------------
# Logging setup for stdlib loggers
# ---------------------------------------------------------------------------
_setup_lock = threading.Lock()
_setup_done = False


def setup_logging() -> None:
    """Configure the stdlib root logger so non-structlog loggers (uvicorn,
    SQLAlchemy, boto3, ...) emit readable lines.

    Idempotent: subsequent calls are no-ops. The previous version ran
    `logging.basicConfig` unconditionally, which - because basicConfig is
    itself a no-op after the first successful call - silently had no
    effect when another framework had already configured logging. That
    made the intended `format="%(message)s"` unreliable in production.

    Note: this still respects basicConfig's first-call-wins semantics by
    design; we don't pass force=True because that would clobber uvicorn's
    own configuration. If a deployment wants structlog to fully own the
    root logger, configure it from the app's startup hook rather than
    relying on this import-time helper.
    """
    global _setup_done
    with _setup_lock:
        if _setup_done:
            return
        logging.basicConfig(
            level=(settings.log_level or "INFO").upper(),
            format="%(message)s",
        )
        _setup_done = True


# ---------------------------------------------------------------------------
# AgentLogger
# ---------------------------------------------------------------------------
class AgentLogger:
    """
    Unified logger for all agents, orchestrators, memory systems, and tools.

    The public method signatures are preserved from the previous version
    so existing call sites don't change. Additions:
      * `agent_operation(...)` context manager - encapsulates the
        start/complete/error + metric recording pattern that every agent
        currently repeats inline.
      * `bind`/`unbind` - set correlation fields (session_id, agent_name)
        for the scope of an operation so log lines carry them automatically.
      * Reserved structlog kwargs (`event`, `level`, ...) are sanitized
        rather than raising.
      * `log_agent_start` tolerates `details=None`.
      * `log_agent_error` accepts an Exception or a string.
      * `log_memory_error` captures tracebacks via exc_info when given an
        exception.
    """

    def __init__(self, name: str = "Agent"):
        self.name = name
        self.logger = get_logger(name)

    # ----------------------------
    # Internal helpers
    # ----------------------------
    @staticmethod
    def _sanitize_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Rename any reserved structlog key to a `user_<key>` form so a
        caller passing `level=...` or `event=...` as a business field
        doesn't crash the log call."""
        if not kwargs:
            return {}
        clean: Dict[str, Any] = {}
        for k, v in kwargs.items():
            if k in _RESERVED_STRUCTLOG_KEYS:
                clean[f"user_{k}"] = v
            else:
                clean[k] = v
        return clean

    # ----------------------------
    # Basic logging
    # ----------------------------
    def info(self, message: str, **kwargs: Any) -> None:
        self.logger.info(message, **self._sanitize_kwargs(kwargs))

    def warning(self, message: str, **kwargs: Any) -> None:
        self.logger.warning(message, **self._sanitize_kwargs(kwargs))

    def debug(self, message: str, **kwargs: Any) -> None:
        self.logger.debug(message, **self._sanitize_kwargs(kwargs))

    def error(self, message: str, **kwargs: Any) -> None:
        self.logger.error(message, **self._sanitize_kwargs(kwargs))

    def exception(self, message: str, **kwargs: Any) -> None:
        """Log at ERROR with the current exception's traceback attached.
        Call from inside an `except` block."""
        self.logger.exception(message, **self._sanitize_kwargs(kwargs))

    # ----------------------------
    # Orchestrator logging
    # ----------------------------
    def log_agent_start(self, action: str, details: Optional[dict] = None) -> None:
        self.logger.info(
            "Agent action started",
            action=action,
            agent=self.name,
            **self._sanitize_kwargs(details or {}),
        )

    def log_agent_error(self, action: str, exception: Any) -> None:
        """Log an agent error. `exception` may be an Exception instance or
        a string message; both are handled."""
        if isinstance(exception, BaseException):
            error_text = str(exception)
            error_type = type(exception).__name__
        else:
            error_text = str(exception)
            error_type = None
        payload = {
            "action": action,
            "agent": self.name,
            "error": error_text,
        }
        if error_type:
            payload["error_type"] = error_type
        self.logger.error("Agent encountered an error", **payload)

    def log_agent_complete(
        self,
        action: str,
        details: Optional[dict] = None,
        duration: float = 0.0,
    ) -> None:
        self.logger.info(
            "Agent action completed",
            action=action,
            agent=self.name,
            duration=duration,
            **self._sanitize_kwargs(details or {}),
        )

    # ----------------------------
    # MemoryBank logging
    # ----------------------------
    def log_memory_operation(self, *args: Any, **kwargs: Any) -> None:
        """Flexible signature preserved from the previous version - callers
        may pass a positional event name and a dict, or keyword fields."""
        self.logger.info(
            "Memory operation executed",
            agent=self.name,
            args=args,
            **self._sanitize_kwargs(kwargs),
        )

    def log_memory_error(self, *args: Any, **kwargs: Any) -> None:
        """Flexible signature preserved. If an `exception` kwarg is passed
        and it is an Exception, its traceback is captured via exc_info so
        memory failures are debuggable."""
        exc = kwargs.pop("exception", None)
        payload: Dict[str, Any] = {"agent": self.name, "args": args}
        if exc is not None:
            payload["error"] = str(exc)
            payload["error_type"] = type(exc).__name__ if isinstance(exc, BaseException) else None
        payload.update(self._sanitize_kwargs(kwargs))
        # exc_info=True attaches the *current* exception if we're inside an
        # except block; when `exception` was passed explicitly, the payload
        # above is what matters and there is no live traceback to attach.
        self.logger.error("Memory operation failed", **payload)

    def log_tool_usage(self, action: str, details: Optional[dict], note: str = "") -> None:
        self.logger.info(
            "Tool usage",
            action=action,
            note=note,
            agent=self.name,
            **self._sanitize_kwargs(details or {}),
        )

    # ----------------------------
    # Generic event logger
    # ----------------------------
    def log_event(self, event_type: str, **kwargs: Any) -> None:
        self.logger.info(
            "Event",
            event_type=event_type,
            agent=self.name,
            **self._sanitize_kwargs(kwargs),
        )

    # ----------------------------
    # Correlation binding
    # ----------------------------
    def bind(self, **kwargs: Any) -> None:
        """Bind correlation fields (session_id, agent_name, etc.) for the
        current task/thread. Passes through to structlog's contextvars so
        every subsequent log line inside this scope carries them."""
        bind_log_context(**kwargs)

    def unbind(self, *keys: str) -> None:
        unbind_log_context(*keys)

    @contextmanager
    def bound(self, **kwargs: Any) -> Iterator["AgentLogger"]:
        """`with logger.bound(session_id=sid):` - binds for the block."""
        with log_context(**kwargs):
            yield self

    # ----------------------------
    # Operation context manager
    # ----------------------------
    @contextmanager
    def agent_operation(
        self,
        action: str,
        details: Optional[dict] = None,
        *,
        metrics_agent_name: Optional[str] = None,
    ) -> Iterator[None]:
        """Context manager that wraps the start/complete/error + metric
        recording pattern. Additive - existing inline uses of the
        individual methods continue to work.

        Usage:
            with self.logger.agent_operation("gather_requirements", {"session_id": sid},
                                             metrics_agent_name=self.config.name):
                result = do_work()

        On success: logs completion with duration, records a successful
        metric. On exception: logs the error, records a failed metric,
        re-raises. The duration is measured with time.perf_counter, which
        is monotonic and unaffected by system clock adjustments."""
        start = time.perf_counter()
        self.log_agent_start(action, details or {})
        try:
            yield
        except Exception as e:
            duration = time.perf_counter() - start
            self.log_agent_error(action, e)
            if metrics_agent_name:
                metrics_collector.record_task(metrics_agent_name, False, duration)
            raise
        else:
            duration = time.perf_counter() - start
            self.log_agent_complete(action, details or {}, duration)
            if metrics_agent_name:
                metrics_collector.record_task(metrics_agent_name, True, duration)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
class MetricsCollector:
    """Thread-safe, bounded metrics aggregator for agent performance.

    Two design changes vs. the previous version:

      * The per-task list is a bounded ring buffer (default 10,000
        entries). Cumulative counters - total, successes, failures,
        total duration - are tracked separately and reflect the true
        process-lifetime totals even after older individual entries have
        been evicted. Previously the list grew forever, so every agent
        call leaked memory in a long-running server.

      * All mutations and reads are guarded by a lock, so concurrent
        record_task calls from FastAPI request handlers can't produce
        inconsistent totals (successes + failures == total) in
        get_summary().
    """

    def __init__(self, max_recent: int = 10_000):
        self._lock = threading.Lock()
        self._max_recent = max(1, int(max_recent))
        self._tasks: Deque[Dict[str, Any]] = deque(maxlen=self._max_recent)
        # Cumulative counters - survive buffer eviction.
        self._total = 0
        self._successes = 0
        self._failures = 0
        self._total_duration = 0.0
        # Per-agent breakdown for diagnosis ("which agent is failing?").
        self._per_agent: Dict[str, Dict[str, Any]] = {}

    def record_task(self, agent_name: str, success: bool, duration: float) -> None:
        entry = {
            "agent": agent_name,
            "success": bool(success),
            "duration": float(duration),
            "timestamp": time.time(),
        }
        with self._lock:
            self._tasks.append(entry)
            self._total += 1
            if success:
                self._successes += 1
            else:
                self._failures += 1
            self._total_duration += float(duration)

            agent = self._per_agent.setdefault(
                agent_name,
                {"total": 0, "successes": 0, "failures": 0, "total_duration": 0.0},
            )
            agent["total"] += 1
            if success:
                agent["successes"] += 1
            else:
                agent["failures"] += 1
            agent["total_duration"] += float(duration)

    def get_metrics(self) -> List[Dict[str, Any]]:
        """Return the most recent N task entries (bounded ring buffer).
        For cumulative totals across the process lifetime, use
        get_summary()."""
        with self._lock:
            return list(self._tasks)

    def get_summary(self) -> Dict[str, Any]:
        """Return cumulative metrics across the process lifetime, plus a
        per-agent breakdown. Total counts reflect every record_task call,
        not just those still present in the recent buffer."""
        with self._lock:
            total = self._total
            successes = self._successes
            failures = self._failures
            avg_time = self._total_duration / total if total else 0.0

            per_agent: Dict[str, Dict[str, Any]] = {}
            for name, data in self._per_agent.items():
                t = data["total"]
                per_agent[name] = {
                    "total": t,
                    "successes": data["successes"],
                    "failures": data["failures"],
                    "success_rate": (data["successes"] / t) if t else 0.0,
                    "avg_duration_sec": (data["total_duration"] / t) if t else 0.0,
                }

            return {
                "total_tasks": total,
                "successes": successes,
                "failures": failures,
                "success_rate": (successes / total) if total else 0.0,
                "failure_rate": (failures / total) if total else 0.0,
                "avg_duration_sec": avg_time,
                "recent_buffer_size": len(self._tasks),
                "recent_buffer_capacity": self._max_recent,
                "per_agent": per_agent,
            }

    def reset(self) -> None:
        """Clear all metrics. Intended for tests. Safe to call at any time;
        concurrent readers see a consistent post-reset state."""
        with self._lock:
            self._tasks.clear()
            self._total = 0
            self._successes = 0
            self._failures = 0
            self._total_duration = 0.0
            self._per_agent.clear()


# Global metrics collector instance.
metrics_collector = MetricsCollector()


# ---------------------------------------------------------------------------
# Import-time configuration
# ---------------------------------------------------------------------------
# Configure structlog once at import. This is the same side effect the
# previous version performed, but now guarded so re-import and test-suite
# reloads don't attempt to reconfigure a running process.
_configure_structlog()