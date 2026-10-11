"""The guides marketing can post, and the first draft of a post for each channel.

Two kinds of guide:

* the public guide pages of the web app (``web_guides.json``, kept in step with
  ``apps/web/src/lib/guides.ts`` by a web test): posts link to the page;
* the step-by-step approval guides (``guidance/approval_guides.json``): there is no public
  page for these, so posts link to starting a free check in that product, and the email
  carries the guide itself (steps, costs, timeframe, who to contact).

Drafts are built from the guide's own reviewed text, never invented: staff edit them before
anything is posted. Links carry ``utm_*`` tags so visits from each channel can be told apart.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from app.modules.guidance.guides import ApprovalGuide
from app.modules.guidance.guides import guides as approval_guides
from app.modules.marketing.models import Channel
from app.modules.projects.models import Vertical

WEB_GUIDES_FILE = Path(__file__).parent / "web_guides.json"

PRODUCT_NAMES: dict[str, str] = {
    Vertical.PLANNING: "PlanningReady",
    Vertical.VESSEL: "VesselReady",
    Vertical.BUSINESS: "BusinessReady",
    Vertical.GRANT: "GrantReady",
    Vertical.SELL: "SellReady",
    Vertical.RENT: "RentReady",
    Vertical.TRADE: "TradeReady",
}

HASHTAGS: dict[str, tuple[str, ...]] = {
    Vertical.PLANNING: ("#ApprovalReady", "#PlanningApproval", "#Cairns", "#Queensland"),
    Vertical.BUSINESS: ("#ApprovalReady", "#SmallBusiness", "#StartABusiness", "#Queensland"),
    Vertical.TRADE: ("#ApprovalReady", "#Importing", "#Exporting", "#AustralianBusiness"),
}
DEFAULT_HASHTAGS = ("#ApprovalReady", "#Australia")

# Channel limits: Instagram captions 2,200 characters; Facebook allows far more, but short
# posts do better. Email subjects over about 70 characters are cut off by most mail apps.
CAPTION_LIMIT = {Channel.FACEBOOK: 2000, Channel.INSTAGRAM: 2200}
SUBJECT_LIMIT = 200
STEP_LIMIT = 5


@dataclass(frozen=True)
class Guide:
    ref: str
    title: str
    summary: str
    vertical: str
    # Path on the web app: the guide's page, or starting a check in its product.
    link_path: str
    # Short facts for the image card and the post.
    cost: str | None = None
    timeframe: str | None = None
    steps: list[str] = field(default_factory=list)
    checked_on: str | None = None
    approval: ApprovalGuide | None = None

    @property
    def product(self) -> str:
        return PRODUCT_NAMES.get(self.vertical, "ApprovalReady")

    @property
    def has_page(self) -> bool:
        return self.approval is None


def _approval_ref(kind: str) -> str:
    return "approval-" + kind.lower().replace("_", "-")


@cache
def _catalogue() -> tuple[Guide, ...]:
    out: list[Guide] = []
    for g in json.loads(WEB_GUIDES_FILE.read_text(encoding="utf-8"))["guides"]:
        out.append(
            Guide(
                ref=f"guide-{g['slug']}",
                title=g["title"],
                summary=g["description"],
                vertical=g["vertical"],
                link_path=f"/guides/{g['slug']}",
            )
        )
    for a in approval_guides():
        vertical = a.verticals[0]
        out.append(
            Guide(
                ref=_approval_ref(a.kind),
                title=a.title,
                summary=a.summary,
                vertical=vertical,
                link_path=f"/projects/new?vertical={vertical}",
                cost=a.cost_summary,
                timeframe=a.timeframe,
                steps=[s.title for s in a.steps],
                checked_on=a.checked_on.isoformat(),
                approval=a,
            )
        )
    return tuple(out)


def catalogue() -> list[Guide]:
    """Every guide that can be posted: guide pages first, then approval guides in plan
    order."""
    return list(_catalogue())


def find(ref: str) -> Guide | None:
    return next((g for g in _catalogue() if g.ref == ref), None)


def link(base_url: str, guide: Guide, channel: Channel) -> str:
    tags = {
        "utm_source": channel.value.lower(),
        "utm_medium": "email" if channel == Channel.EMAIL else "social",
        "utm_campaign": "guides",
        "utm_content": guide.ref,
    }
    sep = "&" if "?" in guide.link_path else "?"
    return f"{base_url.rstrip('/')}{guide.link_path}{sep}{urlencode(tags)}"


def first_sentence(text: str, limit: int = 280) -> str:
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    sentence = match.group(1) if match else text
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"


def _site(url: str) -> str:
    """``approvalready.au`` from ``https://app.approvalready.au/...``."""
    host = urlsplit(url).hostname or url
    return host.removeprefix("www.").removeprefix("app.")


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


@dataclass(frozen=True)
class Draft:
    channel: Channel
    body: str
    subject: str | None = None


def _social(guide: Guide, channel: Channel, url: str) -> str:
    lines = [guide.title, "", first_sentence(guide.summary)]
    facts = []
    if guide.cost:
        facts.append(f"Cost: {first_sentence(guide.cost, 200)}")
    if guide.timeframe:
        facts.append(f"Time: {first_sentence(guide.timeframe, 200)}")
    if facts:
        lines += ["", *facts]
    if guide.steps:
        lines += ["", "The steps:"]
        lines += [f"{i}. {s}" for i, s in enumerate(guide.steps[:STEP_LIMIT], 1)]
        if len(guide.steps) > STEP_LIMIT:
            lines.append(f"…and {len(guide.steps) - STEP_LIMIT} more.")
    lines.append("")
    if guide.has_page:
        lines.append("Read the full guide, with the official source for every point:")
    else:
        lines.append(
            f"Get your own checklist with every step, cost and form in {guide.product}, "
            "free to start:"
        )
    if channel == Channel.INSTAGRAM:
        # Links in Instagram captions aren't clickable, so name the site instead.
        lines.append(f"Link in bio, or visit {_site(url)}")
    else:
        lines.append(url)
    tags = HASHTAGS.get(guide.vertical, DEFAULT_HASHTAGS)
    lines += ["", " ".join(tags)]
    return _cut("\n".join(lines), CAPTION_LIMIT[channel])


def _email(guide: Guide, url: str) -> str:
    lines = [guide.title, "=" * min(len(guide.title), 60), "", guide.summary]
    a = guide.approval
    if a is not None:
        if a.cost_summary:
            lines += ["", f"What it costs: {a.cost_summary}"]
        if a.timeframe:
            lines += [f"How long it takes: {a.timeframe}"]
        if a.before_you_start:
            lines += ["", "Before you start:"]
            lines += [f"- {item}" for item in a.before_you_start]
        lines += ["", "Step by step:"]
        for i, step in enumerate(a.steps, 1):
            lines.append(f"{i}. {step.title}")
            lines.append(f"   {step.detail}")
            extra = [x for x in (step.timeframe, step.cost) if x]
            if extra:
                lines.append(f"   ({'; '.join(extra)})")
            if step.form is not None:
                lines.append(f"   Form: {step.form.name} {step.form.url}")
            elif step.url:
                lines.append(f"   More: {step.url}")
        if a.watch_out:
            lines += ["", "Watch out for:"]
            lines += [f"- {item}" for item in a.watch_out]
        if a.contacts:
            lines += ["", "Who to contact:"]
            for c in a.contacts:
                bits = [x for x in (c.phone, c.email, c.url) if x]
                lines.append(f"- {c.name}" + (f": {', '.join(bits)}" if bits else ""))
        lines += [
            "",
            f"We gathered this from official websites on {a.checked_on.strftime('%-d %B %Y')}. "
            "Fees and rules change, so check the official page before you apply.",
            "",
            f"Get your own checklist for your situation in {guide.product}, free to start:",
            url,
        ]
    else:
        lines += ["", "Read the full guide, with the official source for every point:", url]
    return "\n".join(lines)


def drafts(guide: Guide, base_url: str) -> list[Draft]:
    """A first draft for every channel."""
    return [
        Draft(
            Channel.FACEBOOK,
            _social(guide, Channel.FACEBOOK, link(base_url, guide, Channel.FACEBOOK)),
        ),
        Draft(
            Channel.INSTAGRAM,
            _social(guide, Channel.INSTAGRAM, link(base_url, guide, Channel.INSTAGRAM)),
        ),
        Draft(
            Channel.EMAIL,
            _email(guide, link(base_url, guide, Channel.EMAIL)),
            subject=_cut(f"Guide: {guide.title}", SUBJECT_LIMIT),
        ),
    ]


def draft_for(guide: Guide, channel: Channel, base_url: str) -> Draft:
    return next(d for d in drafts(guide, base_url) if d.channel == channel)
