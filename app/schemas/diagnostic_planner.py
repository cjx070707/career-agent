from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


BottleneckType = Literal[
    "insufficient_evidence",
    "application_volume",
    "resume_positioning",
    "interview_performance",
    "skill_gap",
    "job_targeting",
]

EvidenceSource = Literal[
    "profile",
    "applications",
    "interviews",
    "feedback",
    "resume",
    "job_detail",
]

EvidencePriority = Literal["low", "medium", "high"]


class DiagnosticHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bottleneck_type: BottleneckType
    summary: str = Field(..., min_length=1)
    rationale: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_refs: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cap_confidence_without_evidence_refs(self) -> "DiagnosticHypothesis":
        if not self.evidence_refs and self.confidence > 0.55:
            self.confidence = 0.55
        return self


class EvidenceToCollect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: EvidenceSource
    reason: str = Field(..., min_length=1)
    priority: EvidencePriority
    required: bool


class DiagnosticPlannerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1)
    plan_semantics: Dict[str, Any] = Field(default_factory=dict)
    profile: Dict[str, Any] = Field(default_factory=dict)
    context_resolution: Dict[str, Any] = Field(default_factory=dict)
    memory_context: List[str] = Field(default_factory=list)


class DiagnosticPlannerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnostic_hypotheses: List[DiagnosticHypothesis] = Field(
        default_factory=list,
        max_length=3,
    )
    evidence_to_collect: List[EvidenceToCollect] = Field(
        default_factory=list,
        max_length=5,
    )
    next_question: Optional[str] = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    stop_criteria: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cap_global_confidence_without_evidence_refs(self) -> "DiagnosticPlannerOutput":
        if self.diagnostic_hypotheses and all(
            not item.evidence_refs for item in self.diagnostic_hypotheses
        ):
            if self.confidence > 0.6:
                self.confidence = 0.6
        return self
