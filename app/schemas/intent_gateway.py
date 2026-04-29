from typing import Literal, Optional

from pydantic import BaseModel, Field


IntentCluster = Literal[
    "job_match",
    "job_recommend",
    "resume_analysis",
    "application_diag",
    "interview_prep",
    "unknown",
]

GatewayAction = Literal[
    "route",
    "clarify",
    "escalate_to_planner",
    "true_fallback",
]

FallbackType = Literal["none", "recoverable", "true", "system"]

GatewayDomain = Literal["career", "non_career"]


class IntentGatewayDecision(BaseModel):
    domain: GatewayDomain
    intent_cluster: IntentCluster = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    action: GatewayAction
    required_context: list[str] = Field(default_factory=list)
    missing_context: list[str] = Field(default_factory=list)
    reason: str = ""
    fallback_type: FallbackType = "none"
    # When action=route, this dict is used as the direct ChatPlan payload.
    local_plan_payload: Optional[dict] = None

