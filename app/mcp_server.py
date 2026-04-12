from typing import Any, Dict, List

from app.tools.registry import build_default_tool_registry


def list_tools() -> List[str]:
    return build_default_tool_registry().list_tool_names()


def get_tool_schemas() -> List[Dict[str, Any]]:
    return build_default_tool_registry().describe_tools()


def call_tool(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return build_default_tool_registry().run(name, payload)
