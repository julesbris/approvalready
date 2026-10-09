from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.documents.models import (
    EvidenceStatus,
    GenerationStatus,
    OutputFormat,
    ReviewStatus,
    ScanStatus,
)


class DocumentOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    content_type: str = Field(description="Detected from the file's contents.")
    size_bytes: int
    scan_status: ScanStatus = Field(description="Only CLEAN documents can be downloaded or used.")
    created_at: datetime
    created_by: uuid.UUID | None


class UploadLimitsOut(BaseModel):
    max_bytes: int
    extensions: list[str]
    accept: str = Field(description="Value for an <input type=file accept=...> attribute.")


class EvidenceIn(BaseModel):
    evidence_requirement_id: uuid.UUID
    uploaded_document_id: uuid.UUID
    note: str | None = Field(default=None, max_length=500)


class EvidenceOut(BaseModel):
    id: uuid.UUID
    evidence_requirement_id: uuid.UUID
    status: EvidenceStatus
    note: str | None
    document: DocumentOut
    created_at: datetime


class GenerateIn(BaseModel):
    format: OutputFormat


class GeneratedDocumentOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    assessment_id: uuid.UUID | None
    format: OutputFormat
    status: GenerationStatus
    review_status: ReviewStatus
    filename: str
    size_bytes: int | None
    sha256: str | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None
