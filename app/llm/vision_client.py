import base64
import json
import re
from typing import Any, Dict, List, Tuple

import httpx
from pydantic import ValidationError

from app.env import settings
from app.schemas.vision import ParsedResumeImage, ResumeImageParseResponse

_SYSTEM_PROMPT = (
    "You extract resume information from images. "
    "Return strict JSON only with fields: "
    "name, email, phone, education, skills, projects, experience, summary."
)
_USER_PROMPT = (
    "Parse this resume image into JSON fields: "
    "name, email, phone, education[{school,degree,dates}], "
    "skills[string], projects[{name,summary,technologies[string]}], "
    "experience[{company,role,dates,summary}], summary. "
    "Use null or empty arrays when unknown."
)


class VisionClient:
    TIMEOUT_SECONDS = 20.0

    def is_configured(self) -> bool:
        return bool(settings.vision_api_key)

    def parse_resume_image(
        self,
        image_bytes: bytes,
        mime_type: str,
    ) -> ResumeImageParseResponse:
        if not self.is_configured():
            return ResumeImageParseResponse(
                model=settings.vision_model,
                parsed=ParsedResumeImage(),
                warnings=["Vision model is not configured."],
            )

        payload = self._build_request(image_bytes=image_bytes, mime_type=mime_type)
        try:
            data = self._post_chat_completions(payload=payload)
            text = self._extract_chat_completion_text(data)
            parsed_payload = self._extract_json_object(text)
            parsed_resume = ParsedResumeImage.model_validate(parsed_payload)
            return ResumeImageParseResponse(
                model=settings.vision_model,
                parsed=parsed_resume,
            )
        except (RuntimeError, ValueError, TypeError, json.JSONDecodeError, ValidationError, httpx.HTTPError):
            return ResumeImageParseResponse(
                model=settings.vision_model,
                parsed=ParsedResumeImage(),
                warnings=["Vision parsing failed. Returned empty parsed payload."],
            )

    def _build_request(self, image_bytes: bytes, mime_type: str) -> Dict[str, Any]:
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        request: Dict[str, Any] = {
            "model": settings.vision_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _USER_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{image_b64}"},
                        },
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        return request

    def _post_chat_completions(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{settings.vision_base_url.rstrip('/')}/chat/completions"
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.vision_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    def _extract_chat_completion_text(self, payload: Dict[str, Any]) -> str:
        choices = payload.get("choices", [])
        for choice in choices:
            message = choice.get("message", {})
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, list):
                parts: List[str] = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text = part.get("text")
                        if isinstance(text, str) and text.strip():
                            parts.append(text)
                if parts:
                    return "".join(parts)
        raise ValueError("No text content returned by vision model")

    def _extract_json_object(self, text: str) -> Dict[str, Any]:
        candidate = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", candidate, flags=re.S)
        if fenced:
            candidate = fenced.group(1).strip()
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in vision response")
        return json.loads(candidate[start : end + 1])
