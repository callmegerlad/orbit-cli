from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SourceType = Literal["pull_request", "issue", "commit", "workflow_run"]
Audience = Literal["engineering", "founder", "leadership"]
Confidence = Literal["High", "Medium", "Low"]
RiskFlag = Literal[
    "review_backlog",
    "delivery_risk",
    "ci_unhealthy",
    "low_activity",
    "declining_momentum",
]


class EvidenceItem(BaseModel):
    """A single normalised piece of GitHub-visible activity."""

    model_config = ConfigDict(frozen=True)

    source_type: SourceType
    venture: str
    repo: str
    title: str
    url: str
    author: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    state: str | None = None
    labels: list[str] = Field(default_factory=list)
    summary: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class RiskSignal(BaseModel):
    """A deterministic risk flag with the evidence that produced it."""

    flag: RiskFlag
    venture: str
    repo: str | None = None
    reason: str
    evidence_urls: list[str] = Field(default_factory=list)


class VentureSnapshot(BaseModel):
    """All evidence and signals collected for one venture in a period."""

    id: str | None = None
    name: str
    stakeholder: str | None = None
    milestone: str | None = None
    watch_items: list[str] = Field(default_factory=list)
    repos: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    signals: list[RiskSignal] = Field(default_factory=list)
    confidence: Confidence = "Medium"

    @property
    def merged_pr_count(self) -> int:
        return sum(
            1
            for e in self.evidence
            if e.source_type == "pull_request" and e.state == "merged"
        )

    @property
    def commit_count(self) -> int:
        return sum(1 for e in self.evidence if e.source_type == "commit")


class StudioSnapshot(BaseModel):
    """Top-level snapshot of all ventures in the reporting period."""

    studio_name: str
    period: str
    generated_at: datetime
    ventures: list[VentureSnapshot]
