import fitz  # PyMuPDF
from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.llm.vision_client import VisionClient
from app.schemas.vision import (
    ParsedResumeImage,
    ResumeImageParseResponse,
    SaveParsedResumeRequest,
    SavedParsedResumeResponse,
)
from app.services.candidate_service import CandidateService
from app.services.resume_service import ResumeService

router = APIRouter(tags=["vision"])
vision_client = VisionClient()
candidate_service = CandidateService()
resume_service = ResumeService()

_ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
_ALLOWED_PDF_TYPES = {"application/pdf"}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_MAX_PDF_BYTES = 20 * 1024 * 1024


def _pdf_to_jpeg(pdf_bytes: bytes) -> bytes:
    """Render the first page of a PDF to JPEG bytes at 150 DPI."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.page_count == 0:
        raise ValueError("PDF has no pages")
    page = doc.load_page(0)
    # 150 DPI → matrix scale ≈ 2.08 (72 dpi baseline)
    mat = fitz.Matrix(150 / 72, 150 / 72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    jpeg_bytes = pix.tobytes("jpeg", jpg_quality=92)
    doc.close()
    return jpeg_bytes


def format_parsed_resume(parsed: ParsedResumeImage) -> str:
    lines = ["# Parsed Resume", ""]
    if parsed.name:
        lines.append(f"Name: {parsed.name}")
    if parsed.email:
        lines.append(f"Email: {parsed.email}")
    if parsed.phone:
        lines.append(f"Phone: {parsed.phone}")

    if parsed.summary:
        lines.extend(["", "## Summary", parsed.summary])

    if parsed.education:
        lines.extend(["", "## Education"])
        for item in parsed.education:
            parts = [item.school or "", item.degree or ""]
            core = " — ".join(part for part in parts if part)
            if item.dates:
                core = f"{core} ({item.dates})" if core else item.dates
            if core:
                lines.append(f"- {core}")

    if parsed.skills:
        lines.extend(["", "## Skills"])
        lines.extend([f"- {skill}" for skill in parsed.skills if skill])

    if parsed.projects:
        lines.extend(["", "## Projects"])
        for project in parsed.projects:
            title = project.name or "Unnamed project"
            lines.append(f"### {title}")
            if project.summary:
                lines.append(project.summary)
            if project.technologies:
                lines.append(f"Technologies: {', '.join(project.technologies)}")
            lines.append("")
        while lines and not lines[-1].strip():
            lines.pop()

    if parsed.experience:
        lines.extend(["", "## Experience"])
        for exp in parsed.experience:
            role = exp.role or ""
            company = exp.company or ""
            title_core = " — ".join(part for part in [role, company] if part)
            if exp.dates:
                title_core = f"{title_core} ({exp.dates})" if title_core else exp.dates
            lines.append(f"### {title_core or 'Experience'}")
            if exp.summary:
                lines.append(exp.summary)
            lines.append("")
        while lines and not lines[-1].strip():
            lines.pop()

    return "\n".join(lines).strip()


@router.post("/vision/resume-image", response_model=ResumeImageParseResponse)
async def parse_resume_image(file: UploadFile = File(...)) -> ResumeImageParseResponse:
    content_type = (file.content_type or "").lower().strip()
    is_pdf = content_type in _ALLOWED_PDF_TYPES
    is_image = content_type in _ALLOWED_IMAGE_TYPES

    if not is_pdf and not is_image:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Use PNG, JPEG, WEBP, or PDF.",
        )

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    max_bytes = _MAX_PDF_BYTES if is_pdf else _MAX_IMAGE_BYTES
    if len(raw_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File is too large. Max size is {max_bytes // (1024 * 1024)}MB.",
        )

    if is_pdf:
        try:
            image_bytes = _pdf_to_jpeg(raw_bytes)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not render PDF: {exc}",
            ) from exc
        mime_type = "image/jpeg"
    else:
        image_bytes = raw_bytes
        mime_type = content_type

    return vision_client.parse_resume_image(
        image_bytes=image_bytes,
        mime_type=mime_type,
    )


@router.post("/vision/resume-image/save", response_model=SavedParsedResumeResponse)
def save_parsed_resume(payload: SaveParsedResumeRequest) -> SavedParsedResumeResponse:
    try:
        candidate = candidate_service.get_latest_candidate(user_id=payload.user_id)
    except ValueError:
        # No candidate yet — auto-create one from the parsed name (or a default)
        inferred_name = (payload.parsed.name or "").strip() or "User"
        candidate = candidate_service.create_candidate(
            name=inferred_name, user_id=payload.user_id
        )

    content = format_parsed_resume(payload.parsed)
    title = (payload.title or "Resume parsed from image").strip() or "Resume parsed from image"
    version = (payload.version or "vision-v1").strip() or "vision-v1"
    saved = resume_service.create_resume(
        candidate_id=int(candidate["id"]),
        title=title,
        content=content,
        version=version,
    )
    return SavedParsedResumeResponse(
        resume_id=int(saved["id"]),
        candidate_id=int(saved["candidate_id"]),
        title=str(saved["title"]),
        version=str(saved["version"]),
        content=str(saved["content"]),
    )
