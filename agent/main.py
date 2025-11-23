"""
ASGI entrypoint for the CV agent service.

Usage (development):

    uvicorn agent.main:app --reload --port 8000
"""

from .cv_agent.server.api import app

__all__ = ["app"]
