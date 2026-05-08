import json
from typing import Any, Callable, Dict, List, Optional

import httpx

from app.env import settings
from app.llm.career_event_extractor_client import CareerEventExtractorClient


class LLMClient:
    """Thin wrapper around DashScope /chat/completions for the Career Agent."""

    CAREER_EVENT_EXTRACTION_TIMEOUT_SECONDS = 5.0

    def __init__(self) -> None:
        self.model = settings.default_model
        self.career_event_extractor = CareerEventExtractorClient()

    def is_configured(self) -> bool:
        return bool(settings.openai_api_key)

    # ── Model / endpoint helpers ─────────────────────────────────────────────

    def _planner_api_key(self) -> str:
        return settings.planner_api_key

    def _planner_base_url(self) -> str:
        return settings.planner_base_url

    def _planner_model(self) -> str:
        return settings.planner_model

    def _classifier_model(self) -> str:
        return settings.classifier_model or self._planner_model()

    def _generator_model(self) -> str:
        return settings.generator_model or self._planner_model()

    def _diagnostic_model(self) -> str:
        return settings.diagnostic_model or self._classifier_model()

    # ── Public API ───────────────────────────────────────────────────────────

    def simple_chat(
        self,
        system_prompt: str,
        user_content: str,
        timeout: float = 30.0,
    ) -> str:
        """Single-turn chat completion. Returns the assistant text content."""
        request: Dict[str, Any] = {
            "model": self._generator_model(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        self._disable_thinking(request)
        payload = self._post_responses(
            f"{self._planner_base_url().rstrip('/')}/chat/completions",
            api_key=self._planner_api_key(),
            payload=request,
            timeout=timeout,
        )
        return self._extract_chat_completion_text(payload).strip()

    def chat_with_tools(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Call /chat/completions with function-calling tool schemas.

        Returns the raw assistant message dict:
        - If LLM wants to call tools: {"role": "assistant", "tool_calls": [...]}
        - If LLM produces a final answer: {"role": "assistant", "content": "..."}
        """
        request: Dict[str, Any] = {
            "model": self._generator_model(),
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "tools": tools,
            "tool_choice": "auto",
        }
        self._disable_thinking(request)
        payload = self._post_responses(
            f"{self._planner_base_url().rstrip('/')}/chat/completions",
            api_key=self._planner_api_key(),
            payload=request,
            timeout=timeout,
        )
        choices = payload.get("choices", [])
        if not choices:
            raise ValueError("chat_with_tools: no choices in response")
        return choices[0].get("message", {})

    def stream_chat_with_tools(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        on_token: Callable[[str], None],
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        """Streaming version of chat_with_tools.

        Calls on_token(text) for each content token as it arrives.
        on_token is only called when the LLM is generating a final answer
        (no tool_calls in the stream). Returns the same dict as chat_with_tools.
        """
        request: Dict[str, Any] = {
            "model": self._generator_model(),
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
        }
        self._disable_thinking(request)

        url = f"{self._planner_base_url().rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._planner_api_key()}",
            "Content-Type": "application/json",
        }

        content_parts: List[str] = []
        tool_calls_map: Dict[int, Dict] = {}  # index → accumulated tool_call
        has_tool_calls = False

        with httpx.stream("POST", url, headers=headers, json=request, timeout=timeout) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[len("data:"):].strip()
                if raw == "[DONE]":
                    break
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                choices = chunk.get("choices") or [{}]
                delta = choices[0].get("delta", {})

                token = delta.get("content") or ""
                if token:
                    content_parts.append(token)
                    if not has_tool_calls:
                        on_token(token)

                for tc_delta in delta.get("tool_calls") or []:
                    idx = tc_delta.get("index", 0)
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {"id": "", "type": "function",
                                               "function": {"name": "", "arguments": ""}}
                    tc = tool_calls_map[idx]
                    tc["id"] = tc.get("id") or tc_delta.get("id", "")
                    fn = tc_delta.get("function", {})
                    tc["function"]["name"] += fn.get("name") or ""
                    tc["function"]["arguments"] += fn.get("arguments") or ""
                    has_tool_calls = True

        content = "".join(content_parts)
        if tool_calls_map:
            return {
                "role": "assistant",
                "content": content or None,
                "tool_calls": list(tool_calls_map.values()),
            }
        return {"role": "assistant", "content": content}

    def extract_career_events(
        self,
        user_id: str,
        message: str,
    ) -> List[Dict[str, str]]:
        if not self._career_event_extractor_is_configured():
            return []
        try:
            responses_req = self._build_career_event_extract_request(
                user_id=user_id,
                message=message,
            )
            chat_request = {
                "model": responses_req["model"],
                "messages": [
                    {"role": turn["role"], "content": turn["content"]}
                    for turn in responses_req["input"]
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": responses_req["text"]["format"]["name"],
                        "strict": True,
                        "schema": responses_req["text"]["format"]["schema"],
                    },
                },
            }
            if settings.planner_disable_thinking:
                self._disable_thinking(chat_request)
            response_payload = self._post_responses(
                f"{self._planner_base_url().rstrip('/')}/chat/completions",
                api_key=self._planner_api_key(),
                payload=chat_request,
                timeout=self.CAREER_EVENT_EXTRACTION_TIMEOUT_SECONDS,
            )
            text = self._extract_chat_completion_text(response_payload)
            return self.career_event_extractor.normalize(json.loads(text)) if text else []
        except (RuntimeError, ValueError, TypeError, json.JSONDecodeError, httpx.HTTPError):
            return []

    # ── Private helpers ──────────────────────────────────────────────────────

    def _post_responses(
        self,
        url: str,
        api_key: str,
        payload: Dict[str, Any],
        timeout: float = 45.0,
    ) -> Dict[str, Any]:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    def _disable_thinking(self, request: Dict[str, Any]) -> None:
        # DashScope qwen3 parameter to disable chain-of-thought mode.
        request["enable_thinking"] = False

    def _build_career_event_extract_request(
        self,
        user_id: str,
        message: str,
    ) -> Dict[str, Any]:
        request = self.career_event_extractor.build_request(
            planner_model=self._diagnostic_model(),
            user_id=user_id,
            message=message,
        )
        self._disable_thinking(request)
        return request

    def _extract_chat_completion_text(self, payload: Dict[str, Any]) -> str:
        choices = payload.get("choices", [])
        for choice in choices:
            message = choice.get("message", {})
            content = message.get("content")
            if isinstance(content, str) and content:
                return content
            if isinstance(content, list):
                parts: List[str] = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text = part.get("text")
                        if isinstance(text, str) and text:
                            parts.append(text)
                if parts:
                    return "".join(parts)
        return ""

    def _career_event_extractor_is_configured(self) -> bool:
        return bool(self._planner_api_key())
