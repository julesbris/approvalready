from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.modules.vessels.models import CertificateKind
from app.modules.vessels.service import CertificateState


class _CertificateFields(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    number: str | None = Field(default=None, max_length=60)
    issuer: str | None = Field(default=None, max_length=200)
    issued_on: date | None = None
    expires_on: date | None = None
    uploaded_document_id: uuid.UUID | None = Field(
        default=None, description="A clean upload holding a copy of the certificate."
    )
    notes: str | None = Field(default=None, max_length=1000)


class CertificateCreate(_CertificateFields):
    kind: CertificateKind


class CertificateUpdate(_CertificateFields):
    kind: CertificateKind | None = None


class CertificateOut(BaseModel):
    id: uuid.UUID
    vessel_id: uuid.UUID
    kind: CertificateKind
    title: str | None
    number: str | None
    issuer: str | None
    issued_on: date | None
    expires_on: date | None
    state: CertificateState = Field(
        description="EXPIRING within 60 days of expiry (Queensland date)."
    )
    uploaded_document_id: uuid.UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class SmsSourceOut(BaseModel):
    title: str
    organisation: str
    url: str


class SmsElementOut(BaseModel):
    key: str
    title: str
    guidance: str
    required: bool
    text: str | None = Field(description="What the customer has written so far.")
    suggestion: str | None = Field(
        description="Starting text from the vessel's details, offered only while empty."
    )


class SmsSectionOut(BaseModel):
    key: str
    title: str
    elements: list[SmsElementOut]


class SmsOut(BaseModel):
    project_id: uuid.UUID
    title: str
    description: str
    disclaimer: str
    sources: list[SmsSourceOut]
    sections: list[SmsSectionOut]
    written: int = Field(description="Required parts with text.")
    required: int
    saved_at: datetime | None
    outdated_structure: bool = Field(
        description="The structure changed since this SMS was last saved."
    )


class SmsSaveIn(BaseModel):
    content: dict[str, str | None] = Field(
        description="Element key → text; null or blank clears it. Other elements are kept.",
        max_length=200,
    )
