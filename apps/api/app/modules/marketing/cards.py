"""The image card that goes with a guide's Facebook and Instagram posts.

A 1080 x 1080 JPEG (Instagram takes JPEG only) in the brand's navy, with the reversed logo
lockup exactly as supplied (rasterised from ``apps/web/public/brand``), the guide's title in
Outfit and its first sentence in Figtree. The fonts are the web app's own, converted to TTF
(SIL Open Font License, ``assets/OFL.txt``).

Cards are made from the guide alone, so the same guide always gives the same card: Facebook
and Instagram fetch it from ``/v1/marketing/cards/<ref>.jpg`` when a post is published.
"""

from __future__ import annotations

import io
from functools import cache, lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.modules.marketing.catalogue import Guide, find, first_sentence

ASSETS = Path(__file__).parent / "assets"
SIZE = 1080
MARGIN = 88
NAVY = (1, 36, 85)  # --ar-brand-navy #012455
WHITE = (255, 255, 255)
MUTED = (200, 214, 234)
TEAL = (0, 202, 181)  # a thin "ready" rule, never text


@cache
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / f"{name}.ttf"), size)


@cache
def _logo() -> Image.Image:
    logo = Image.open(ASSETS / "logo-reversed.png").convert("RGBA")
    width = 520
    return logo.resize((width, round(logo.height * width / logo.width)), Image.Resampling.LANCZOS)


def _wrap(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int
) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=font) <= width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _fit(
    draw: ImageDraw.ImageDraw,
    text: str,
    name: str,
    sizes: tuple[int, ...],
    width: int,
    max_lines: int,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """The largest size that fits in ``max_lines``; the last size is cut with an ellipsis."""
    for size in sizes:
        font = _font(name, size)
        lines = _wrap(draw, text, font, width)
        if len(lines) <= max_lines:
            return font, lines
    lines = lines[:max_lines]
    lines[-1] = lines[-1].rstrip(" ,.;:") + "…"
    return font, lines


def render(guide: Guide) -> bytes:
    image = Image.new("RGB", (SIZE, SIZE), NAVY)
    draw = ImageDraw.Draw(image)
    width = SIZE - 2 * MARGIN

    logo = _logo()
    image.paste(logo, (MARGIN - 10, MARGIN - 10), logo)

    y = MARGIN + logo.height + 70
    label = _font("Figtree-700", 30)
    draw.text((MARGIN, y), "STEP-BY-STEP GUIDE", font=label, fill=MUTED)
    y += 62

    title_font, title = _fit(draw, guide.title, "Outfit-700", (84, 76, 68, 60, 54), width, 5)
    step = round(title_font.size * 1.14)
    for line in title:
        draw.text((MARGIN, y), line, font=title_font, fill=WHITE)
        y += step
    y += 30
    draw.rectangle((MARGIN, y, MARGIN + 120, y + 8), fill=TEAL)
    y += 50

    room = (SIZE - MARGIN - 110 - y) // 50
    if room > 0:
        body_font, body = _fit(
            draw, first_sentence(guide.summary, 400), "Figtree-500", (38, 34), width, room
        )
        for line in body:
            draw.text((MARGIN, y), line, font=body_font, fill=MUTED)
            y += round(body_font.size * 1.35)

    footer = _font("Figtree-700", 34)
    cta = (
        "Read the full guide at approvalready.au"
        if guide.has_page
        else f"Free checklist in {guide.product} at approvalready.au"
    )
    draw.text((MARGIN, SIZE - MARGIN - 40), cta, font=footer, fill=WHITE)

    out = io.BytesIO()
    image.save(out, "JPEG", quality=90, optimize=True, progressive=False)
    return out.getvalue()


@lru_cache(maxsize=64)
def card(ref: str) -> bytes | None:
    """The card for a guide, or ``None`` when there is no such guide."""
    guide = find(ref)
    return render(guide) if guide is not None else None
