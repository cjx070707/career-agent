from typing import Any, Dict, List

from app.tools.base import ToolDefinition, ToolResult
from app.tools.candidate_tools import build_candidate_tools
from app.tools.job_tools import build_job_tools
from app.tools.match_tools import build_match_tools
from app.tools.resume_tools import build_resume_tools


class ToolRegistry:
    def __init__(self, tools: List[ToolDefinition]) -> None:
        self._tool_order = [tool.name for tool in tools]
        self._tools = {tool.name: tool for tool in tools}

    def list_tool_names(self) -> List[str]:
        return list(self._tool_order)

    def describe_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": self._tools[name].name,
                "description": self._tools[name].description,
                "input_schema": self._tools[name].input_model.model_json_schema(),
            }
            for name in self._tool_order
        ]

    def run(self, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self._tools:
            return ToolResult(
                ok=False,
                tool_name=name,
                data=None,
                error=f"Tool {name} not registered",
            ).as_dict()

        tool = self._tools[name]
        try:
            parsed_payload = tool.input_model(**payload)
            result = tool.handler(parsed_payload)
            return ToolResult(
                ok=True,
                tool_name=name,
                data=result,
                error=None,
            ).as_dict()
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                ok=False,
                tool_name=name,
                data=None,
                error=str(exc),
            ).as_dict()


def build_default_tool_registry() -> ToolRegistry:
    tools: List[ToolDefinition] = []
    tools.extend(build_candidate_tools())
    tools.extend(build_resume_tools())
    tools.extend(build_job_tools())
    tools.extend(build_match_tools())
    return ToolRegistry(tools)
