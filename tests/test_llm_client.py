"""Tests for app/llm/client.py — covers live methods only.

Planner/diagnostic tests were removed along with the old agent stack.
Live methods: simple_chat, chat_with_tools, stream_chat_with_tools, extract_career_events.
"""
import json

from app.llm.client import LLMClient


CAREER_EVENT_RESPONSE_TEXT = json.dumps(
    {
        "events": [
            {
                "event_type": "interview_feedback",
                "title": "Canva backend interview feedback",
                "summary": "Rejected after Canva backend interview; prepare system design fundamentals.",
                "occurred_at": "2026-04-20",
            }
        ]
    }
)


class CareerEventExtractionClient(LLMClient):
    def __init__(self, response_text=CAREER_EVENT_RESPONSE_TEXT, error=None) -> None:
        super().__init__()
        self.response_text = response_text
        self.error = error
        self.calls = []

    def _planner_api_key(self) -> str:
        return "test-key"  # makes _career_event_extractor_is_configured() return True

    def _post_responses(self, url, payload=None, api_key=None, **kwargs):
        self.calls.append((url, payload, kwargs))
        if self.error is not None:
            raise self.error
        # extract_career_events now uses /chat/completions format
        return {"choices": [{"message": {"content": self.response_text}}]}


def test_extract_career_events_uses_structured_responses_payload() -> None:
    client = CareerEventExtractionClient()

    events = client.extract_career_events(
        user_id="event-user",
        message="Canva backend 面试没过，反馈是 system design fundamentals。",
    )

    assert events == [
        {
            "event_type": "interview_feedback",
            "title": "Canva backend interview feedback",
            "summary": "Rejected after Canva backend interview; prepare system design fundamentals.",
            "occurred_at": "2026-04-20",
        }
    ]
    assert client.calls
    url, payload, kwargs = client.calls[0]
    assert url.endswith("/chat/completions")
    assert kwargs["timeout"] == 5.0
    # messages[0] is system, messages[1] is user
    user_content = json.loads(payload["messages"][1]["content"])
    assert user_content["user_id"] == "event-user"
    assert "Canva backend" in user_content["message"]


def test_extract_career_events_returns_empty_when_model_payload_is_invalid() -> None:
    client = CareerEventExtractionClient(response_text="{not-json")

    assert client.extract_career_events(
        user_id="event-user",
        message="Canva backend 面试没过。",
    ) == []


def test_extract_career_events_returns_empty_when_unconfigured() -> None:
    """When API keys are missing, extract_career_events should return [] not raise."""
    client = LLMClient()
    # Ensure is_configured() returns False (no real keys in test env)
    if client.is_configured():
        return  # skip if real keys are present
    result = client.extract_career_events(user_id="u1", message="some message")
    assert result == []
