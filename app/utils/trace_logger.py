"""Structured JSON trace logger for the agent loop.

Writes one JSON object per line to logs/agent_trace.jsonl.
Each event type has a fixed schema so logs are grep-able and parseable.

Event types:
  llm_call   — one LLM request inside the ReAct loop
  tool_call  — one tool execution
  agent_turn — summary of a complete user→agent round-trip
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Log file lives at <project_root>/logs/agent_trace.jsonl
_LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
_LOG_FILE = _LOG_DIR / "agent_trace.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _write(record: Dict[str, Any]) -> None:
    """Append one JSON line to the trace file. Never raises."""
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("trace_logger write failed: %s", exc)


class TraceLogger:
    """Thin wrapper — call from AutonomousAgentService, never crash the loop."""

    def log_llm_call(
        self,
        *,
        user_id: str,
        iteration: int,
        latency_ms: int,
        had_tool_calls: bool,
        n_messages: int,
        error: Optional[str] = None,
    ) -> None:
        _write({
            "event": "llm_call",
            "ts": _now(),
            "user_id": user_id,
            "iteration": iteration,
            "latency_ms": latency_ms,
            "had_tool_calls": had_tool_calls,
            "n_messages": n_messages,
            "error": error,
        })

    def log_tool_call(
        self,
        *,
        user_id: str,
        tool_name: str,
        args: Dict[str, Any],
        latency_ms: int,
        ok: bool,
        error: Optional[str] = None,
    ) -> None:
        # Truncate large arg values so the log stays readable
        safe_args = {
            k: (v[:120] + "…" if isinstance(v, str) and len(v) > 120 else v)
            for k, v in args.items()
        }
        _write({
            "event": "tool_call",
            "ts": _now(),
            "user_id": user_id,
            "tool": tool_name,
            "args": safe_args,
            "latency_ms": latency_ms,
            "ok": ok,
            "error": error,
        })

    def log_agent_turn(
        self,
        *,
        user_id: str,
        total_latency_ms: int,
        tool_trace: List[str],
        stage: str,
        iterations: int,
    ) -> None:
        _write({
            "event": "agent_turn",
            "ts": _now(),
            "user_id": user_id,
            "stage": stage,
            "iterations": iterations,
            "tool_trace": tool_trace,
            "total_latency_ms": total_latency_ms,
        })


# Module-level singleton — import and use directly
tracer = TraceLogger()
