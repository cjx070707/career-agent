from dataclasses import dataclass
from typing import Any, Callable, Dict, Type

from pydantic import BaseModel


ToolHandler = Callable[[BaseModel], Any]


@dataclass
class ToolResult:
    ok: bool
    tool_name: str
    data: Any = None
    error: str = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "tool_name": self.tool_name,
            "data": self.data,
            "error": self.error,
        }


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_model: Type[BaseModel]
    handler: ToolHandler
    category: str = "general"
