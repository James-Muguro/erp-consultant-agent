import logging
import structlog
from typing import Optional

from src.config.settings import settings


def get_logger(name: Optional[str] = None):
    """
    Initializes and returns a structlog logger.
    """

    if not structlog.is_configured():
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer()
                if settings.log_format == "json"
                else structlog.dev.ConsoleRenderer(),
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

    return structlog.get_logger(name)


def setup_logging():
    """
    Sets up the root logger with the specified log level.
    """
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(message)s",
    )


class AgentLogger:
    """
    Unified logger class for all agents, orchestrators, memory systems, and tools.
    Provides flexible signatures (*args, **kwargs*) to prevent runtime failures.
    """

    def __init__(self, name: str = "Agent"):
        self.logger = get_logger(name)

    # ----------------------------
    # Basic Logging
    # ----------------------------
    def info(self, message: str, **kwargs):
        self.logger.info(message, **kwargs)

    def warning(self, message: str, **kwargs):
        self.logger.warning(message, **kwargs)

    def debug(self, message: str, **kwargs):
        self.logger.debug(message, **kwargs)

    def error(self, message: str, **kwargs):
        self.logger.error(message, **kwargs)

    # ----------------------------
    # Orchestrator Logging
    # ----------------------------
    def log_agent_start(self, action: str, details: dict):
        self.logger.info(
            "Agent action started",
            action=action,
            **details
        )

    def log_agent_error(self, action: str, exception: Exception):
        self.logger.error(
            "Agent encountered an error",
            action=action,
            error=str(exception)
        )

    def log_agent_complete(self, action: str, details: dict, duration: float):
        """Log completion of an agent task with a small details dict and duration."""
        self.logger.info(
            "Agent action completed",
            action=action,
            duration=duration,
            **(details or {})
        )

    # ----------------------------
    # MemoryBank Logging (Flexible)
    # ----------------------------
    def log_memory_operation(self, *args, **kwargs):
        """
        Accepts flexible arguments because MemoryBank may call with:
        - positional args
        - keyword args
        - mixed arguments
        """
        self.logger.info(
            "Memory operation executed",
            args=args,
            **kwargs
        )

    def log_memory_error(self, *args, **kwargs):
        """
        Accepts flexible arguments to avoid signature mismatch errors.
        """
        self.logger.error(
            "Memory operation failed",
            args=args,
            **kwargs
        )

    def log_tool_usage(self, action: str, details: dict, note: str = ""):
        """Log usage of a tool from within an agent or orchestrator."""
        self.logger.info(
            "Tool usage",
            action=action,
            note=note,
            **(details or {})
        )

    # ----------------------------
    # Generic Event Logger
    # ----------------------------
    def log_event(self, event_type: str, **kwargs):
        self.logger.info(
            "Event",
            event_type=event_type,
            **kwargs
        )


# Initialize logging on import
setup_logging()
import time
from typing import List, Dict, Any

class MetricsCollector:
    """Lightweight metrics aggregator for agent performance tracking."""

    def __init__(self):
        self.tasks: List[Dict[str, Any]] = []

    def record_task(self, agent_name: str, success: bool, duration: float):
        self.tasks.append({
            "agent": agent_name,
            "success": success,
            "duration": duration,
            "timestamp": time.time()
        })

    def get_metrics(self):
        """Return raw metrics"""
        return self.tasks

    def get_summary(self):
        """Return summary stats"""
        total = len(self.tasks)
        successes = len([t for t in self.tasks if t["success"]])
        failures = total - successes
        avg_time = sum(t["duration"] for t in self.tasks) / total if total > 0 else 0

        return {
            "total_tasks": total,
            "success_rate": successes / total if total > 0 else 0,
            "failure_rate": failures / total if total > 0 else 0,
            "avg_duration_sec": avg_time
        }


# Global metrics collector instance
metrics_collector = MetricsCollector()
