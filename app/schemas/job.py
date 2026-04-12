from typing import Optional

from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    title: str = Field(..., min_length=1)


class JobPosting(BaseModel):
    id: Optional[int] = None
    title: str
