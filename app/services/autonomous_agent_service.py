"""True autonomous agent: LLM decides which tools to call via function calling.

Replaces the intent-classifier → fixed-tool-chain pattern with a genuine
ReAct loop where the LLM sees all available tools and autonomously decides
what to do at each step.
"""
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.llm.client import LLMClient
from app.schemas.chat import ChatSource
from app.services.goal_service import GoalService
from app.services.memory_service import MemoryService
from app.tools.registry import ToolRegistry, build_default_tool_registry


@dataclass
class AutonomousAgentResult:
    answer: str
    stage: str
    memory_used: bool
    sources: List[ChatSource] = field(default_factory=list)
    tool_used: Optional[str] = None
    tool_trace: List[str] = field(default_factory=list)


class AutonomousAgentService:
    """Goal-aware autonomous agent using true LLM function calling.

    Decision flow per turn:
      1. Load goals + conversation history
      2. Build system prompt (goal-aware)
      3. Call LLM with tool schemas — LLM decides what to do
      4. If tool_calls → execute, feed results back, repeat
      5. If no tool_calls → final answer
      6. Hard cap at MAX_ITERATIONS to prevent runaway loops
    """

    MAX_ITERATIONS = 6
    TOOL_TIMEOUT = 30.0

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        tool_registry: Optional[ToolRegistry] = None,
        memory_service: Optional[MemoryService] = None,
        goal_service: Optional[GoalService] = None,
    ) -> None:
        self.llm = llm_client or LLMClient()
        self.tools = tool_registry or build_default_tool_registry()
        self.memory = memory_service or MemoryService()
        self.goals = goal_service or GoalService()

    def respond(
        self,
        user_id: str,
        message: str,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> AutonomousAgentResult:
        """Run the autonomous agent loop.

        `on_status` is called synchronously from this thread whenever a
        status update is ready (e.g. "🔧 调用工具: search_jobs").  The
        SSE layer in chat.py uses call_soon_threadsafe to forward these
        to the async event stream without blocking the loop.
        """

        def emit(text: str) -> None:
            if on_status:
                on_status(text)

        # ── 1. Context ───────────────────────────────────────────────
        goals = self.goals.get_active_goals(user_id)
        history = self.memory.load_recent_messages(user_id)

        # ── 2. System prompt with goal state ────────────────────────
        system_prompt = self._build_system_prompt(goals)

        # ── 3. Conversation messages ─────────────────────────────────
        messages: List[Dict[str, Any]] = self._build_messages(history, message)

        # ── 4. Tool schemas (OpenAI function calling format) ─────────
        tool_schemas = self._build_tool_schemas()

        # ── 5. True ReAct loop ───────────────────────────────────────
        tool_trace: List[str] = []
        answer = ""

        for iteration in range(self.MAX_ITERATIONS):
            emit("🤔 正在思考..." if iteration == 0 else "🔄 继续分析...")

            try:
                response_msg = self.llm.chat_with_tools(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=tool_schemas,
                    timeout=self.TOOL_TIMEOUT,
                )
            except Exception as exc:
                answer = f"抱歉，暂时无法回答：{exc}"
                break

            tool_calls = response_msg.get("tool_calls")

            if not tool_calls:
                # LLM produced a final text answer — exit loop
                answer = str(response_msg.get("content") or "").strip()
                if not answer:
                    answer = "抱歉，暂时无法生成回答，请稍后再试。"
                break

            # LLM wants to call tools — execute and feed results back
            # Append the assistant message (with tool_calls) to history
            messages.append({
                "role": "assistant",
                "content": response_msg.get("content"),
                "tool_calls": tool_calls,
            })

            for tool_call in tool_calls:
                func = tool_call.get("function", {})
                tool_name = func.get("name", "unknown")
                args_raw = func.get("arguments", "{}")
                call_id = tool_call.get("id", "")

                emit(f"🔧 调用工具：{tool_name}")

                try:
                    args = json.loads(args_raw)
                except (json.JSONDecodeError, TypeError):
                    args = {}

                result = self.tools.run(tool_name, args)
                tool_trace.append(tool_name)

                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
        else:
            # Exceeded MAX_ITERATIONS without a final answer
            if not answer:
                answer = "抱歉，这个问题需要更多信息，请换一种方式描述。"

        # ── 6. Persist to memory ─────────────────────────────────────
        self.memory.save_turn(user_id, message, answer)

        stage = "tool" if tool_trace else "direct"
        return AutonomousAgentResult(
            answer=answer,
            stage=stage,
            memory_used=bool(history),
            tool_used=tool_trace[-1] if tool_trace else None,
            tool_trace=tool_trace,
        )

    # ── Helpers ──────────────────────────────────────────────────────

    def _build_system_prompt(self, goals: List[Dict[str, Any]]) -> str:
        base = (
            "你是一个专业的求职辅导 Agent，可以自主决定调用哪些工具来帮助用户。\n\n"
            "行为准则：\n"
            "- 简单问候或闲聊：直接回答，不需要调用工具\n"
            "- 求职相关问题：主动使用合适的工具获取信息后再回答\n"
            "- 回答控制在 300 字以内，除非用户明确要求详细展开\n"
            "- 给出结论和 1-3 个具体行动建议，避免空泛铺垫\n"
            "- 每次对话开始时先调用 get_goals 了解用户是否有进行中的目标需要跟进\n"
        )

        if goals:
            lines = []
            for g in goals:
                line = f"• [{g['id']}] {g['goal_text']}"
                if g.get("deadline"):
                    line += f"（截止：{g['deadline']}）"
                if g.get("recent_progress"):
                    latest = g["recent_progress"][0]["note"]
                    line += f"\n  最新进展：{latest}"
            lines.append(line)
            base += (
                "\n\n用户当前求职目标：\n"
                + "\n".join(lines)
                + "\n\n如果用户上次说要做某件事，可以主动询问进展并用 log_progress 记录。"
            )
        else:
            base += (
                "\n\n用户目前尚未设定求职目标。"
                "如果用户表达了明确的求职意向，引导并调用 set_goal 帮他设定目标。"
            )

        return base

    def _build_messages(
        self,
        history: List[Any],
        current_message: str,
    ) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        last_role = ""
        for turn in history:
            role = str(getattr(turn, "role", "")).strip().lower()
            content = str(getattr(turn, "content", "")).strip()
            if not content or role not in {"user", "assistant"}:
                continue
            if role == last_role:
                continue
            last_role = role
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": current_message})
        return messages

    def _build_tool_schemas(self) -> List[Dict[str, Any]]:
        schemas = []
        for tool in self.tools.describe_tools():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            })
        return schemas
