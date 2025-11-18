
import logging
import structlog
from typing import Optional

from src.config.settings import settings

def get_logger(name: Optional[str] = None):
    """
    Initializes and returns a structlog logger.
    
    Args:
        name: The name of the logger.
        
    Returns:
        A structlog logger instance.
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
                structlog.processors.JSONRenderer() if settings.log_format == "json" else structlog.dev.ConsoleRenderer(),
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

# Initialize logging
setup_logging()
