"""Structured logging configuration for article_agent using structlog."""

import logging
import sys

import structlog


def configure_structlog():
    """Configure structlog with JSON output for production and console for development."""
    
    # Determine if we're in development mode (could be env var)
    # For now, defaulting to JSON for container environments
    use_json = True
    
    processors = [
        # Add log level to event dict
        structlog.stdlib.add_log_level,
        # Add timestamp
        structlog.processors.TimeStamper(fmt="iso"),
        #Stack info and exception formatting
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        # Decode the event dict
        structlog.processors.UnicodeDecoder(),
    ]
    
    if use_json:
        # JSON output for production/containers
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Console output for development
        processors.append(structlog.dev.ConsoleRenderer())
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard logging to use structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


__all__ = ["configure_structlog", "get_logger"]
