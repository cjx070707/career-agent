from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.llm.vision_client import VisionClient
from app.schemas.vision import ResumeImageParseResponse

router = APIRouter(tags=["vision"])
vision_client = VisionClient()

_ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024


@router.post("/vision/resume-image", response_model=ResumeImageParseResponse)
async def parse_resume_image(file: UploadFile = File(...)) -> ResumeImageParseResponse:
    content_type = (file.content_type or "").lower().strip()
    if content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Use PNG, JPEG, or WEBP.",
        )

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is too large. Max size is 5MB.",
        )

    return vision_client.parse_resume_image(
        image_bytes=image_bytes,
        mime_type=content_type,
    )
