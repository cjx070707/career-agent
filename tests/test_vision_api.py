from io import BytesIO

from fastapi.testclient import TestClient

from app.env import settings
from app.main import app
from app.services.candidate_service import CandidateService

client = TestClient(app)

_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xff\xff?"
    b"\x00\x05\xfe\x02\xfeA\xd9\x8f\x96\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_vision_api_missing_config_returns_warning_and_empty_payload(
    isolated_runtime,
) -> None:
    original_vision_api_key = settings.vision_api_key
    settings.vision_api_key = ""
    try:
        response = client.post(
            "/vision/resume-image",
            files={"file": ("resume.png", BytesIO(_PNG_1X1), "image/png")},
        )
    finally:
        settings.vision_api_key = original_vision_api_key

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "resume_image"
    assert body["model"] == settings.vision_model
    assert body["parsed"]["skills"] == []
    assert body["warnings"] == ["Vision model is not configured."]


def test_vision_api_rejects_unsupported_content_type(isolated_runtime) -> None:
    response = client.post(
        "/vision/resume-image",
        files={"file": ("resume.gif", BytesIO(b"GIF89a"), "image/gif")},
    )
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]


def test_vision_api_rejects_empty_file(isolated_runtime) -> None:
    response = client.post(
        "/vision/resume-image",
        files={"file": ("resume.png", BytesIO(b""), "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Uploaded file is empty."


def test_vision_api_rejects_large_file(isolated_runtime) -> None:
    response = client.post(
        "/vision/resume-image",
        files={"file": ("resume.png", BytesIO(b"x" * (5 * 1024 * 1024 + 1)), "image/png")},
    )
    assert response.status_code == 400
    assert "too large" in response.json()["detail"]


def test_vision_api_returns_structured_fields_from_mocked_client(
    isolated_runtime,
    monkeypatch,
) -> None:
    from app.api import vision as vision_api
    from app.schemas.vision import ParsedResumeImage, ResumeImageParseResponse

    original_vision_api_key = settings.vision_api_key
    settings.vision_api_key = "vision-key"

    def fake_parse_resume_image(image_bytes: bytes, mime_type: str) -> ResumeImageParseResponse:
        assert image_bytes
        assert mime_type == "image/png"
        return ResumeImageParseResponse(
            model=settings.vision_model,
            parsed=ParsedResumeImage(
                name="Jesse Chen",
                email="jesse@example.com",
                skills=["Python", "FastAPI", "SQL"],
                projects=[
                    {
                        "name": "Career Agent",
                        "summary": "Built a FastAPI and RAG based job coaching agent.",
                        "technologies": ["FastAPI", "SQLite", "ChromaDB"],
                    }
                ],
            ),
        )

    monkeypatch.setattr(vision_api.vision_client, "parse_resume_image", fake_parse_resume_image)
    try:
        response = client.post(
            "/vision/resume-image",
            files={"file": ("resume.png", BytesIO(_PNG_1X1), "image/png")},
        )
    finally:
        settings.vision_api_key = original_vision_api_key

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "resume_image"
    assert body["model"] == settings.vision_model
    assert body["parsed"]["skills"] == ["Python", "FastAPI", "SQL"]
    assert body["parsed"]["projects"][0]["name"] == "Career Agent"


def test_vision_save_parsed_resume_for_existing_candidate(isolated_runtime) -> None:
    candidate = CandidateService().create_candidate(
        name="Vision Save User",
        user_id="vision-save-user",
    )
    response = client.post(
        "/vision/resume-image/save",
        json={
            "user_id": "vision-save-user",
            "title": "Resume parsed from image",
            "version": "vision-v1",
            "parsed": {
                "name": "Jesse Chen",
                "email": "jesse@example.com",
                "education": [
                    {
                        "school": "University of Sydney",
                        "degree": "Bachelor of Computer Science",
                        "dates": "2023-2026",
                    }
                ],
                "skills": ["Python", "FastAPI"],
                "projects": [
                    {
                        "name": "Career Agent",
                        "summary": "Built a FastAPI and RAG based job coaching agent.",
                        "technologies": ["FastAPI", "SQLite", "ChromaDB"],
                    }
                ],
                "experience": [],
                "summary": "Backend-focused CS student.",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["candidate_id"] == candidate["id"]
    assert body["title"] == "Resume parsed from image"
    assert body["version"] == "vision-v1"
    assert "Jesse Chen" in body["content"]
    assert "Python" in body["content"]
    assert "Career Agent" in body["content"]
    assert "University of Sydney" in body["content"]


def test_vision_save_returns_404_when_candidate_missing(isolated_runtime) -> None:
    response = client.post(
        "/vision/resume-image/save",
        json={
            "user_id": "missing-user",
            "parsed": {"skills": ["Python"]},
        },
    )
    assert response.status_code == 404
    assert "Candidate not found" in response.json()["detail"]


def test_vision_formatting_handles_sparse_data(isolated_runtime) -> None:
    CandidateService().create_candidate(
        name="Sparse User",
        user_id="sparse-user",
    )
    response = client.post(
        "/vision/resume-image/save",
        json={
            "user_id": "sparse-user",
            "parsed": {"skills": ["Python"]},
        },
    )
    assert response.status_code == 200
    content = response.json()["content"]
    assert "# Parsed Resume" in content
    assert "Python" in content


def test_vision_save_does_not_call_vision_model(
    isolated_runtime,
    monkeypatch,
) -> None:
    from app.api import vision as vision_api

    CandidateService().create_candidate(
        name="No Vision Call User",
        user_id="no-vision-call-user",
    )

    def forbidden_call(*args, **kwargs):
        raise AssertionError("vision parse should not be called by save endpoint")

    monkeypatch.setattr(vision_api.vision_client, "parse_resume_image", forbidden_call)
    response = client.post(
        "/vision/resume-image/save",
        json={
            "user_id": "no-vision-call-user",
            "parsed": {"skills": ["Python"]},
        },
    )
    assert response.status_code == 200
