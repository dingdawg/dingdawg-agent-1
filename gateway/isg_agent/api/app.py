"""Backward-compatible re-export of the application factory.

The canonical application factory lives at isg_agent.app.create_app.
This module re-exports it for backward compatibility with existing imports.
"""

from isg_agent.app import create_app

__all__ = ["create_app"]
