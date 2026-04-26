from typing import List, Optional

from pydantic import BaseModel, Field


class ResumeEducation(BaseModel):
    school: Optional[str] = None
    degree: Optional[str] = None
    dates: Optional[str] = None


class ResumeProject(BaseModel):
    name: Optional[str] = None
    summary: Optional[str] = None
    technologies: List[str] = Field(default_factory=list)


class ResumeExperience(BaseModel):
    company: Optional[str] = None
    role: Optional[str] = None
    dates: Optional[str] = None
    summary: Optional[str] = None


class ParsedResumeImage(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    education: List[ResumeEducation] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    projects: List[ResumeProject] = Field(default_factory=list)
    experience: List[ResumeExperience] = Field(default_factory=list)
    summary: Optional[str] = None


class ResumeImageParseResponse(BaseModel):
    type: str = "resume_image"
    model: str
    parsed: ParsedResumeImage
    raw_text: str = ""
    warnings: List[str] = Field(default_factory=list)
