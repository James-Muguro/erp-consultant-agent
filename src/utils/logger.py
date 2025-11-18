"""
Structured logging utility for observability
"""
import logging
import structlog
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
import json

from src.config.settings import settings


def setup_logging():
    """Configure structured logging with JSON output"""
    
    # Create logs directory
    log_dir = Path(settings.logs_dir)
    log_dir.mkdir(exist_ok=True)
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer() if settings.log_format == "json" 
            else structlog.dev.ConsoleRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard logging
    logging.basicConfig(
        level=logging.getLevelName(settings.log_level),
        format="%(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                log_dir / f"agent_{datetime.now().strftime('%Y%m%d')}.log"
            )
        ]
    )


class AgentLogger:
    """Structured logger for agent operations"""
    
    def __init__(self, agent_name: str):
        self.logger = structlog.get_logger()
        self.agent_name = agent_name
        self.context = {"agent": agent_name}
    
    def info(self, message: str, **kwargs):
        """Log info message"""
        self.logger.info(message, **{**self.context, **kwargs})
    
    def error(self, message: str, **kwargs):
        """Log error message"""
        self.logger.error(message, **{**self.context, **kwargs})
    
    def warning(self, message: str, **kwargs):
        """Log warning message"""
        self.logger.warning(message, **{**self.context, **kwargs})
    
    def debug(self, message: str, **kwargs):
        """Log debug message"""
        self.logger.debug(message, **{**self.context, **kwargs})
    
    def log_agent_start(self, task: str, inputs: Dict[str, Any]):
        """Log agent task start"""
        self.info(
            "Agent task started",
            task=task,
            inputs=inputs,
            timestamp=datetime.now().isoformat()
        )
    
    def log_agent_complete(self, task: str, outputs: Dict[str, Any], duration: float):
        """Log agent task completion"""
        self.info(
            "Agent task completed",
            task=task,
            outputs=outputs,
            duration_seconds=duration,
            timestamp=datetime.now().isoformat()
        )
    
    def log_agent_error(self, task: str, error: Exception):
        """Log agent error"""
        self.error(
            "Agent task failed",
            task=task,
            error=str(error),
            error_type=type(error).__name__,
            timestamp=datetime.now().isoformat()
        )
    
    def log_tool_usage(self, tool_name: str, inputs: Dict[str, Any], outputs: Any):
        """Log tool usage"""
        self.debug(
            "Tool executed",
            tool=tool_name,
            inputs=inputs,
            outputs=str(outputs)[:200],  # Truncate long outputs
            timestamp=datetime.now().isoformat()
        )
    
    def log_memory_operation(self, operation: str, details: Dict[str, Any]):
        """Log memory operations"""
        self.debug(
            "Memory operation",
            operation=operation,
            details=details,
            timestamp=datetime.now().isoformat()
        )


class MetricsCollector:
    """Collect and track agent metrics"""
    
    def __init__(self):
        self.metrics = {
            "total_tasks": 0,
            "successful_tasks": 0,
            "failed_tasks": 0,
            "total_duration": 0.0,
            "agent_metrics": {}
        }
    
    def record_task(self, agent_name: str, success: bool, duration: float):
        """Record task execution metrics"""
        self.metrics["total_tasks"] += 1
        
        if success:
            self.metrics["successful_tasks"] += 1
        else:
            self.metrics["failed_tasks"] += 1
        
        self.metrics["total_duration"] += duration
        
        # Track per-agent metrics
        if agent_name not in self.metrics["agent_metrics"]:
            self.metrics["agent_metrics"][agent_name] = {
                "tasks": 0,
                "successes": 0,
                "failures": 0,
                "total_duration": 0.0
            }
        
        agent_metrics = self.metrics["agent_metrics"][agent_name]
        agent_metrics["tasks"] += 1
        agent_metrics["successes" if success else "failures"] += 1
        agent_metrics["total_duration"] += duration
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics"""
        return self.metrics
    
    def get_summary(self) -> str:
        """Get formatted metrics summary"""
        avg_duration = (
            self.metrics["total_duration"] / self.metrics["total_tasks"]
            if self.metrics["total_tasks"] > 0 else 0
        )
        
        success_rate = (
            (self.metrics["successful_tasks"] / self.metrics["total_tasks"] * 100)
            if self.metrics["total_tasks"] > 0 else 0
        )
        
        return f"""
Agent Metrics Summary
====================
Total Tasks: {self.metrics["total_tasks"]}
Successful: {self.metrics["successful_tasks"]}
Failed: {self.metrics["failed_tasks"]}
Success Rate: {success_rate:.1f}%
Average Duration: {avg_duration:.2f}s
Total Duration: {self.metrics["total_duration"]:.2f}s
        """
    
    def save_metrics(self, filepath: str):
        """Save metrics to JSON file"""
        with open(filepath, 'w') as f:
            json.dump(self.metrics, f, indent=2)


# Global metrics collector
metrics_collector = MetricsCollector()

# Initialize logging
setup_logging()