"""Lazy singleton for the same ToolRegistry the FastAPI agent uses."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.tool_registry import ToolRegistry

_registry: "ToolRegistry | None" = None


def get_tool_registry() -> "ToolRegistry":
    global _registry
    if _registry is None:
        from app.tools.registry import build_default_tool_registry

        _registry = build_default_tool_registry()
    return _registry


def run_tool(name: str, payload: dict) -> dict:
    return get_tool_registry().run(name, payload)
