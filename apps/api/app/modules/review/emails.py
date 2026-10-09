"""Review notifications (plain text, en-AU). They say what happened and link to the page;
they never carry findings, answers or file names."""

from __future__ import annotations

import uuid

from app.core.config import Settings
from app.core.email import OutgoingEmail

DECISION_WORDS = {
    "CHANGES_REQUIRED": "asked for some changes",
    "APPROVED": "approved the assessment",
    "COMPLETED": "finished the review with comments",
}


def _url(settings: Settings, path: str) -> str:
    return f"{settings.web_base_url.rstrip('/')}{path}"


def review_assigned(
    settings: Settings, to: str, name: str, review_id: uuid.UUID, reference: str
) -> OutgoingEmail:
    link = _url(settings, f"/review/{review_id}")
    return OutgoingEmail(
        to=to,
        kind="review.assigned",
        subject=f"New review: {reference}",
        text=(
            f"Hi {name},\n\n"
            f"You have been asked to review project {reference} on ApprovalReady.\n\n"
            f"Open the review: {link}\n\n"
            "If you can't take it on, decline it there and we will find someone else.\n"
        ),
        links={"review": link},
    )


def review_resubmitted(
    settings: Settings, to: str, name: str, review_id: uuid.UUID, reference: str
) -> OutgoingEmail:
    link = _url(settings, f"/review/{review_id}")
    return OutgoingEmail(
        to=to,
        kind="review.resubmitted",
        subject=f"Back for review: {reference}",
        text=(
            f"Hi {name},\n\n"
            f"The customer has made the changes you asked for on project {reference}.\n\n"
            f"Open the review: {link}\n"
        ),
        links={"review": link},
    )


def review_decided(
    settings: Settings,
    to: str,
    name: str,
    decision: str,
    project_id: uuid.UUID,
    assessment_id: uuid.UUID,
    reference: str,
) -> OutgoingEmail:
    link = _url(settings, f"/projects/{project_id}/assessments/{assessment_id}")
    return OutgoingEmail(
        to=to,
        kind="review.decided",
        subject=f"Your professional review: {reference}",
        text=(
            f"Hi {name},\n\n"
            f"The professional reviewing project {reference} has "
            f"{DECISION_WORDS.get(decision, 'updated the review')}.\n\n"
            f"See the details: {link}\n"
        ),
        links={"review": link},
    )
