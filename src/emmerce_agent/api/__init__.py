"""Backward-compatible re-export — prefer emmerce_agent.interfaces.api """

from emmerce_agent.interfaces.api.main import app, create_app

__all__ = ["app", "create_app"]
