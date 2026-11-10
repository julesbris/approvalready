from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ReportFact(BaseModel):
    label: str
    value: str
    compare: str | None = Field(default=None, description="e.g. 'Queensland: $1,675'.")
    note: str | None = None


class ReportItem(BaseModel):
    label: str
    detail: str | None = None
    distance_m: int | None = None
    url: str | None = None


class ReportLink(BaseModel):
    label: str
    url: str
    why: str


class ReportSource(BaseModel):
    name: str
    url: str
    as_at: str = Field(description="How current it is, e.g. 'Census 2021' or 'checked today'.")


class ReportBar(BaseModel):
    label: str
    value: float = Field(description="A percentage, 0 to 100.")
    compare: float | None = Field(default=None, description="The state's figure, if known.")


class ReportChart(BaseModel):
    title: str
    compare_label: str | None = Field(default=None, description="e.g. 'Queensland'.")
    bars: list[ReportBar]


class ReportScore(BaseModel):
    key: str
    label: str
    score: float = Field(ge=0, le=10, description="Out of 10.")
    summary: str = Field(description="How the score was worked out, in plain words.")


class ReportSection(BaseModel):
    key: str
    title: str
    intro: str
    status: Literal["ok", "partial", "unavailable"]
    facts: list[ReportFact] = []
    items: list[ReportItem] = []
    links: list[ReportLink] = []
    sources: list[ReportSource] = []
    charts: list[ReportChart] = []


class PropertyReportOut(BaseModel):
    property_id: uuid.UUID
    address: str
    suburb: str | None
    council: str | None
    headline: list[str] = Field(description="The few things worth knowing first.")
    scores: list[ReportScore] = Field(
        default=[], description="Neighbourhood scores out of 10, each with how it was worked out."
    )
    overall_score: float | None = None
    finance_url: str = Field(description="Where a finance enquiry goes.")
    sections: list[ReportSection]
    generated_at: datetime
    disclaimer: str
