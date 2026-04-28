import json
from typing import Any, Dict, List

from app.llm.prompts import CAREER_EVENT_EXTRACTOR_SYSTEM_PROMPT


class CareerEventExtractorClient:
    def build_request(self, *, planner_model: str, user_id: str, message: str) -> Dict[str, Any]:
        return {
            "model": planner_model,
            "input": [
                {"role": "system", "content": CAREER_EVENT_EXTRACTOR_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"user_id": user_id, "message": message}, ensure_ascii=False)},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "career_events",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "events": {
                                "type": "array",
                                "maxItems": 3,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "event_type": {
                                            "type": "string",
                                            "enum": [
                                                "application_status",
                                                "interview_feedback",
                                                "assessment_result",
                                                "career_milestone",
                                            ],
                                        },
                                        "title": {"type": "string"},
                                        "summary": {"type": "string"},
                                        "occurred_at": {"type": ["string", "null"]},
                                    },
                                    "required": ["event_type", "title", "summary", "occurred_at"],
                                },
                            }
                        },
                        "required": ["events"],
                    },
                }
            },
        }

    def normalize(self, payload: Any) -> List[Dict[str, str]]:
        if isinstance(payload, list):
            raw_events = payload
        elif isinstance(payload, dict):
            raw_events = payload.get("events", [])
        else:
            return []

        allowed_event_types = {
            "application_status",
            "interview_feedback",
            "assessment_result",
            "career_milestone",
        }
        events: List[Dict[str, str]] = []
        for raw_event in raw_events[:3]:
            if not isinstance(raw_event, dict):
                continue
            event_type = str(raw_event.get("event_type") or "").strip()
            title = str(raw_event.get("title") or "").strip()
            summary = str(raw_event.get("summary") or "").strip()
            occurred_at = str(raw_event.get("occurred_at") or "").strip()
            if event_type not in allowed_event_types:
                continue
            if not title or not summary:
                continue
            events.append(
                {
                    "event_type": event_type,
                    "title": title,
                    "summary": summary,
                    "occurred_at": occurred_at,
                }
            )
        return events
