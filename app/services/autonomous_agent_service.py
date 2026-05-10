"""True autonomous agent: LLM decides which tools to call via function calling.

Replaces the intent-classifier → fixed-tool-chain pattern with a genuine
ReAct loop where the LLM sees all available tools and autonomously decides
what to do at each step.
"""
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.llm.client import LLMClient
from app.routing.fast_gate import fast_gate
from app.schemas.chat import ChatSource
from app.services.career_event_service import CareerEventService
from app.services.goal_service import GoalService
from app.services.memory_service import MemoryService
from app.services.user_profile_service import SummaryService, UserProfileService
from app.tools.registry import ToolRegistry, build_default_tool_registry
from app.utils.trace_logger import tracer


@dataclass
class AutonomousAgentResult:
    answer: str
    stage: str
    memory_used: bool
    sources: List[ChatSource] = field(default_factory=list)
    tool_used: Optional[str] = None
    tool_trace: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def is_error(self) -> bool:
        return self.error is not None


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
        self.profiler = UserProfileService(llm_client=self.llm, memory_service=self.memory)
        self.summarizer = SummaryService(llm_client=self.llm, memory_service=self.memory)
        self.career_events = CareerEventService(llm_client=self.llm)

    def respond(
        self,
        user_id: str,
        message: str,
        on_status: Optional[Callable[[str], None]] = None,
        on_token: Optional[Callable[[str], None]] = None,
        session_id: Optional[str] = None,
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

        # ── 0. Fast Gate — bypass ReAct for pure chitchat ────────────
        gate = fast_gate(message)
        if gate.is_chitchat:
            try:
                answer = self.llm.simple_chat(
                    system_prompt="你是一个友好的求职助手。简短自然地回复用户的问候或闲聊，不超过 30 字。",
                    user_content=message,
                    timeout=10.0,
                )
            except Exception:
                # Graceful fallback when LLM is unavailable (e.g. no API key in test env)
                answer = "你好！有什么求职相关的问题我可以帮你？"
            self.memory.save_turn(user_id, message, answer, session_id=session_id)
            tracer.log_agent_turn(
                user_id=user_id,
                total_latency_ms=0,
                tool_trace=[],
                stage="fast_gate",
                iterations=0,
            )
            return AutonomousAgentResult(
                answer=answer,
                stage="fast_gate",
                memory_used=False,
            )

        # ── 1. Context ───────────────────────────────────────────────
        goals = self.goals.get_active_goals(user_id)
        history = self.memory.load_recent_messages(user_id, session_id=session_id)
        summary = self.memory.load_summary(user_id)
        user_profile = self.memory.load_user_profile(user_id)

        # ── 2. System prompt with goal state ────────────────────────
        system_prompt = self._build_system_prompt(user_id, goals, summary, user_profile)

        # ── 3. Conversation messages ─────────────────────────────────
        messages: List[Dict[str, Any]] = self._build_messages(history, message)

        # ── 4. Tool schemas (OpenAI function calling format) ─────────
        tool_schemas = self._build_tool_schemas()

        # ── 5. True ReAct loop ───────────────────────────────────────
        tool_trace: List[str] = []
        answer = ""
        loop_exc: Optional[Exception] = None
        turn_start = time.monotonic()
        iterations_used = 0

        for iteration in range(self.MAX_ITERATIONS):
            iterations_used = iteration + 1
            emit("🤔 正在思考..." if iteration == 0 else "🔄 继续分析...")

            llm_start = time.monotonic()
            try:
                if on_token:
                    response_msg = self.llm.stream_chat_with_tools(
                        system_prompt=system_prompt,
                        messages=messages,
                        tools=tool_schemas,
                        on_token=on_token,
                        timeout=self.TOOL_TIMEOUT,
                    )
                else:
                    response_msg = self.llm.chat_with_tools(
                        system_prompt=system_prompt,
                        messages=messages,
                        tools=tool_schemas,
                        timeout=self.TOOL_TIMEOUT,
                    )
                llm_ms = int((time.monotonic() - llm_start) * 1000)
                tool_calls = response_msg.get("tool_calls")
                tracer.log_llm_call(
                    user_id=user_id,
                    iteration=iteration,
                    latency_ms=llm_ms,
                    had_tool_calls=bool(tool_calls),
                    n_messages=len(messages),
                )
            except Exception as exc:
                llm_ms = int((time.monotonic() - llm_start) * 1000)
                tracer.log_llm_call(
                    user_id=user_id,
                    iteration=iteration,
                    latency_ms=llm_ms,
                    had_tool_calls=False,
                    n_messages=len(messages),
                    error=str(exc),
                )
                loop_exc = exc
                answer = f"抱歉，暂时无法回答：{exc}"
                break

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
                "content": response_msg.get("content") or "",
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

                tool_start = time.monotonic()
                try:
                    result = self.tools.run(tool_name, args)
                    tool_ms = int((time.monotonic() - tool_start) * 1000)
                    tracer.log_tool_call(
                        user_id=user_id,
                        tool_name=tool_name,
                        args=args,
                        latency_ms=tool_ms,
                        ok=True,
                    )
                except Exception as exc:
                    tool_ms = int((time.monotonic() - tool_start) * 1000)
                    tracer.log_tool_call(
                        user_id=user_id,
                        tool_name=tool_name,
                        args=args,
                        latency_ms=tool_ms,
                        ok=False,
                        error=str(exc),
                    )
                    result = {"error": str(exc)}

                tool_trace.append(tool_name)

                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
        else:
            # Exceeded MAX_ITERATIONS without a final answer
            if not answer:
                answer = "抱歉，这个问题的处理步骤超出了预期，请稍后重试或把问题拆分得更具体一些。"

        # ── 6. Persist to memory (skip on agent loop error) ──────────
        total_ms = int((time.monotonic() - turn_start) * 1000)
        stage = "tool" if tool_trace else "direct"

        if loop_exc is None:
            self.memory.save_turn(user_id, message, answer, session_id=session_id)

        # Log the completed turn
        tracer.log_agent_turn(
            user_id=user_id,
            total_latency_ms=total_ms,
            tool_trace=tool_trace,
            stage=stage,
            iterations=iterations_used,
        )

        # ── 7. Post-turn background tasks ────────────────────────────
        if loop_exc is None:
            try:
                self.profiler.update_profile(user_id, message, answer)
            except Exception:
                pass
            try:
                self.career_events.sync_from_message(user_id, message)
            except Exception:
                pass

        try:
            self.summarizer.maybe_compress(user_id)
        except Exception:
            pass

        return AutonomousAgentResult(
            answer=answer,
            stage=stage,
            memory_used=bool(history),
            tool_used=tool_trace[-1] if tool_trace else None,
            tool_trace=tool_trace,
            error=str(loop_exc) if loop_exc else None,
        )

    # ── Helpers ──────────────────────────────────────────────────────

    def _build_system_prompt(
        self,
        user_id: str,
        goals: List[Dict[str, Any]],
        summary: str = "",
        user_profile: str = "",
    ) -> str:
        base = (
            "你是一个专业的求职辅导 Agent，可以自主决定调用哪些工具来帮助用户。\n\n"
            f"当前用户的 user_id 为：{user_id}（调用任何需要 user_id 的工具时必须使用此值）\n\n"
            "行为准则：\n"
            "- 简单问候或闲聊：直接回答，不需要调用工具\n"
            "- 求职相关问题：主动使用合适的工具获取信息后再回答\n"
            "- 意图边界：用户说’我想找/我要找/帮我找 + 岗位/实习’时，优先调用 search_jobs，不要因为有求职意愿就调用 set_goal\n"
            "- 只有当用户明确要求’设定目标/制定目标/目标规划’时才调用 set_goal\n"
            "- 当用户说’结合我的情况推荐适合投的岗位’且可用时，优先链路：get_candidate_profile -> get_resume_by_id -> search_jobs -> match_resume_to_jobs\n"
            "- 回答控制在 300 字以内，除非用户明确要求详细展开\n"
            "- 给出结论和 1-3 个具体行动建议，避免空泛铺垫\n"
            "- 【无简历引导】任何工具返回 error 字段且值含’未找到简历’时，必须回复：\n"
            "  ‘系统中还没有你的简历，gap 分析/岗位匹配需要先上传。上传方式：\n"
            "  ① 在聊天框直接 Cmd+V 粘贴简历截图\n"
            "  ② 点击输入框左侧 📎 按钮选择图片或 PDF\n"
            "  上传后系统自动解析，之后即可使用所有简历相关功能。’\n"
            "  不要在无简历时继续调用其他简历相关工具。\n"
        )

        # Inject long-term user preferences
        if user_profile and user_profile != "{}":
            try:
                import json
                prefs = json.loads(user_profile)
                pref_lines = [
                    f"  {k}: {v}" for k, v in prefs.items() if v is not None
                ]
                if pref_lines:
                    base += "\n\n【用户已知偏好（跨会话记忆）】\n" + "\n".join(pref_lines)
            except Exception:
                pass

        # Inject running summary of older conversations
        if summary:
            base += f"\n\n【历史对话摘要】\n{summary}"

        # Inject current goals
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
                "\n\n【用户当前求职目标】\n"
                + "\n".join(lines)
                + "\n\n如果用户上次说要做某件事，可以主动询问进展并用 log_progress 记录。"
            )
        else:
            base += (
                "\n\n用户目前尚未设定求职目标。"
                "不要因为用户表达求职意向就自动 set_goal。"
                "只有当用户明确要求设定目标时，才调用 set_goal。"
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
            # Skip persisted error responses — they poison future LLM context
            if role == "assistant" and content.startswith("抱歉，暂时无法回答："):
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
                    "parameters": self._inline_refs(tool["input_schema"]),
                },
            })
        return schemas

    @staticmethod
    def _inline_refs(schema: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve $defs/$ref in place so Qwen can parse nested object schemas."""
        import copy
        schema = copy.deepcopy(schema)
        defs = schema.pop("$defs", {})
        if not defs:
            return schema

        def resolve(node: Any) -> Any:
            if isinstance(node, dict):
                if "$ref" in node:
                    ref_name = node["$ref"].split("/")[-1]
                    return resolve(defs.get(ref_name, node))
                return {k: resolve(v) for k, v in node.items()}
            if isinstance(node, list):
                return [resolve(i) for i in node]
            return node

        return resolve(schema)
