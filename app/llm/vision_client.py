import base64
from io import BytesIO
import json
import re
from typing import Any, Dict, List, Tuple

import httpx
from PIL import Image, ImageOps
from pydantic import ValidationError

from app.env import settings
from app.schemas.vision import ParsedResumeImage, ResumeImageParseResponse

_SYSTEM_PROMPT = (
    "You extract resume information from images. "
    "Return strict JSON only with fields: "
    "name, email, phone, education, skills, projects, experience, summary.\n\n"
    "CRITICAL field rules:\n"
    "- experience: ONLY real jobs/internships at a company (has company name + role/title + dates). "
    "e.g. '软件开发实习生 @ TikTok (2024-2025)' → experience.\n"
    "- projects: academic coursework, personal/open-source projects, research, competitions "
    "WITHOUT an employer. e.g. 'RAG 问答系统 (课程项目)' → projects.\n"
    "- If an entry has BOTH a company employer AND technical project details, put it in experience "
    "(not projects), and include the tech details in the summary field of that experience entry."
)
_USER_PROMPT = (
    "Parse this resume image into JSON fields:\n"
    "name(string), email(string), phone(string),\n"
    "education[{school, degree, dates}],\n"
    "skills[string],\n"
    "experience[{company, role, dates, summary}]  ← real jobs & internships with an employer,\n"
    "projects[{name, summary, technologies[string]}]  ← personal/academic/research projects only,\n"
    "summary(string).\n"
    "Use null or empty arrays when unknown. Return JSON only, no markdown."
)


class VisionClient:
    TIMEOUT_SECONDS = 60.0
    MAX_IMAGE_SIDE = 1200
    JPEG_QUALITY = 82
    RETRY_IMAGE_SPECS = ((1200, 82), (900, 76), (700, 70))

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

        warnings: List[str] = []
        for max_side, quality in self.RETRY_IMAGE_SPECS:
            payload = self._build_request(
                image_bytes=image_bytes,
                mime_type=mime_type,
                max_side=max_side,
                quality=quality,
            )
            try:
                data = self._post_chat_completions(payload=payload)
                text = self._extract_chat_completion_text(data)
                parsed_payload = self._extract_json_object(text)
                parsed_resume = ParsedResumeImage.model_validate(parsed_payload)
                if self._has_parsed_content(parsed_resume):
                    if warnings:
                        warnings.append("Vision parsing succeeded after retry.")
                    return ResumeImageParseResponse(
                        model=settings.vision_model,
                        parsed=parsed_resume,
                        warnings=warnings,
                    )
                warnings.append(f"Attempt {len(warnings) + 1} returned empty parsed content.")
            except (RuntimeError, ValueError, TypeError, json.JSONDecodeError, ValidationError, httpx.HTTPError) as exc:
                warnings.append(
                    f"Attempt {len(warnings) + 1} failed: {self._format_provider_error(exc)}."
                )

        return ResumeImageParseResponse(
            model=settings.vision_model,
            parsed=ParsedResumeImage(),
            warnings=warnings or ["Vision parsing failed. Returned empty parsed payload."],
        )

    def _build_request(
        self,
        image_bytes: bytes,
        mime_type: str,
        max_side: int = MAX_IMAGE_SIDE,
        quality: int = JPEG_QUALITY,
    ) -> Dict[str, Any]:
        prepared_bytes, prepared_mime_type = self._prepare_image_for_model(
            image_bytes=image_bytes,
            mime_type=mime_type,
            max_side=max_side,
            quality=quality,
        )
        image_b64 = base64.b64encode(prepared_bytes).decode("utf-8")
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
                            "image_url": {"url": f"data:{prepared_mime_type};base64,{image_b64}"},
                        },
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        return request

    def _prepare_image_for_model(
        self,
        image_bytes: bytes,
        mime_type: str,
        max_side: int = MAX_IMAGE_SIDE,
        quality: int = JPEG_QUALITY,
    ) -> Tuple[bytes, str]:
        try:
            image = Image.open(BytesIO(image_bytes))
            image = ImageOps.exif_transpose(image)
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            if max(image.size) > max_side:
                image.thumbnail((max_side, max_side))

            output = BytesIO()
            image.convert("RGB").save(
                output,
                format="JPEG",
                quality=quality,
                optimize=True,
            )
            prepared = output.getvalue()
            if prepared and len(prepared) < len(image_bytes):
                return prepared, "image/jpeg"
        except Exception:
            return image_bytes, mime_type
        return image_bytes, mime_type

    def _has_parsed_content(self, parsed: ParsedResumeImage) -> bool:
        return bool(
            parsed.name
            or parsed.email
            or parsed.phone
            or parsed.summary
            or parsed.education
            or parsed.skills
            or parsed.projects
            or parsed.experience
        )

    def _format_provider_error(self, exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            try:
                payload = exc.response.json()
                error = payload.get("error") if isinstance(payload, dict) else None
                if isinstance(error, dict):
                    code = str(error.get("code") or error.get("type") or "").strip()
                    message = str(error.get("message") or "").strip()
                    if code and message:
                        return f"{code}: {message}"
                    if code:
                        return code
            except (ValueError, TypeError):
                pass
            return f"HTTP {exc.response.status_code}"
        return type(exc).__name__

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
