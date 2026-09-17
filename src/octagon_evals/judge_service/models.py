from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class JudgeRequest(BaseModel):
    task_id: str
    dimension_question: str
    anchors: list[dict[str, Any]] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any]
    lineage: dict[str, Any] = Field(default_factory=dict)


class JudgeResponse(BaseModel):
    task_id: str
    value: float
    reason: str | None = None
    raw: Any = None
    source: str = "agent_judge_agentic"
    lineage: dict[str, Any] = Field(default_factory=dict)
