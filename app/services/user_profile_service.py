"""Extract and persist user job-search preferences from conversation turns."""

from __future__ import annotations

import json
import logging
from typing import Optional

from app.llm.client import LLMClient
from app.services.memory_service import MemoryService

logger = logging.getLogger(__name__)

_EXTRACT_SYSTEM = (
    "你是一个信息提取助手。从下面的对话中提取用户的求职偏好，"
    "输出严格的 JSON 对象，不要包含任何其他文字。\n"
    "字段说明（无法提取的字段设为 null）：\n"
    "  location     - 工作地点偏好（如 Sydney, remote, 不限等）\n"
    "  industry     - 行业偏好（如 fintech, consulting, tech 等）\n"
    "  job_type     - 工作类型（full-time / internship / part-time / 不限）\n"
    "  salary       - 薪资期望（如 '80k AUD' 或 null）\n"
    "  timeline     - 求职时间线（如 '2025 年 7 月前' 或 null）\n"
    "  avoid        - 明确不想要的（如 '不去外企', '不想做销售'）\n"
    "  other        - 其他重要偏好\n\n"
    "只输出 JSON，例如：\n"
    '{\"location\": \"Sydney\", \"industry\": \"fintech\", '
    '\"job_type\": \"internship\", \"salary\": null, '
    '\"timeline\": null, \"avoid\": null, \"other\": null}'
)

_COMPRESS_SYSTEM = (
    "你是一个对话摘要助手。将提供的对话历史和已有摘要合并为简洁的摘要。\n"
    "要求：\n"
    "- 保留关键信息：用户的求职意向、工具调用结果、重要决策、进展更新\n"
    "- 去掉寒暄、重复内容\n"
    "- 输出纯文本，不超过 400 字\n"
    "- 用中文输出"
)


class UserProfileService:
    """Extracts job-search preferences from conversation and persists them."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        memory_service: Optional[MemoryService] = None,
    ) -> None:
        self.llm = llm_client or LLMClient()
        self.memory = memory_service or MemoryService()

    def update_profile(self, user_id: str, user_message: str, assistant_message: str) -> None:
        """Extract preferences from this exchange and merge into stored profile."""
        conversation = f"用户：{user_message}\nAgent：{assistant_message}"
        try:
            raw = self.llm.simple_chat(
                system_prompt=_EXTRACT_SYSTEM,
                user_content=conversation,
                timeout=20.0,
            )
            new_prefs = json.loads(raw)
        except Exception as exc:
            logger.debug("Profile extraction skipped: %s", exc)
            return

        # Merge with existing profile (new values override only if not null)
        existing_raw = self.memory.load_user_profile(user_id)
        try:
            existing = json.loads(existing_raw) if existing_raw else {}
        except json.JSONDecodeError:
            existing = {}

        merged = {**existing}
        for key, val in new_prefs.items():
            if val is not None:
                merged[key] = val

        self.memory.save_user_profile(user_id, json.dumps(merged, ensure_ascii=False))


class SummaryService:
    """Compresses old conversation turns into a running summary."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        memory_service: Optional[MemoryService] = None,
    ) -> None:
        self.llm = llm_client or LLMClient()
        self.memory = memory_service or MemoryService()

    def maybe_compress(self, user_id: str) -> None:
        """If turn count exceeds threshold, compress old turns into summary."""
        if not self.memory.needs_archive(user_id):
            return

        candidates = self.memory.get_archive_candidates(user_id)
        if not candidates:
            return

        turns_text = "\n".join(
            f"{'用户' if t.role == 'user' else 'Agent'}：{t.content}"
            for t in candidates
        )
        existing_summary = self.memory.load_summary(user_id)

        user_content = ""
        if existing_summary:
            user_content += f"【已有摘要】\n{existing_summary}\n\n"
        user_content += f"【待压缩对话】\n{turns_text}"

        try:
            new_summary = self.llm.simple_chat(
                system_prompt=_COMPRESS_SYSTEM,
                user_content=user_content,
                timeout=30.0,
            )
        except Exception as exc:
            logger.warning("Summary compression failed: %s", exc)
            return

        self.memory.save_summary(user_id, new_summary.strip())
        self.memory.delete_turns_by_ids([t.id for t in candidates])
        logger.info(
            "Compressed %d turns into summary for user=%s", len(candidates), user_id
        )
