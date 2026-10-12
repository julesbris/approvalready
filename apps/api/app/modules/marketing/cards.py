"""The images that go with a guide: its page's share image and its social posts.

Three sizes of one design, all JPEG (Instagram takes JPEG only):

* ``square`` 1080 x 1080 for Facebook and Instagram feed posts;
* ``portrait`` 1080 x 1350, Instagram's tallest feed post, with the first steps listed;
* ``wide`` 1200 x 630, the Open Graph image search results, link previews and Facebook link
  posts show.

Each is in the brand's navy with the reversed logo lockup exactly as supplied (rasterised from
``apps/web/public/brand``), the guide's title in Outfit and the rest in Figtree. Fonts are
the web app's own, converted to TTF (SIL Open Font License, ``assets/OFL.txt``). Teal is used
only for the "ready" rule and the line drawing for the guide's scenario, never for text.

Cards are made from the guide alone, so the same guide always gives the same card: Facebook,
Instagram and search engines fetch them from ``/v1/marketing/cards/<ref>.jpg`` (with
``?format=`` for the other sizes) when a guide is posted or shared.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from enum import StrEnum
from functools import cache, lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.modules.marketing.catalogue import Guide, find, first_sentence

ASSETS = Path(__file__).parent / "assets"
NAVY = (1, 36, 85)  # --ar-brand-navy #012455
NAVY_LIGHT = (12, 58, 122)  # a lighter navy for shapes behind the text
NAVY_LINE = (31, 79, 146)
WHITE = (255, 255, 255)
MUTED = (200, 214, 234)
TEAL = (0, 202, 181)  # "ready": rules and drawings, never text
SUPERSAMPLE = 4


class CardFormat(StrEnum):
    SQUARE = "square"
    PORTRAIT = "portrait"
    WIDE = "wide"


SIZES: dict[CardFormat, tuple[int, int]] = {
    CardFormat.SQUARE: (1080, 1080),
    CardFormat.PORTRAIT: (1080, 1350),
    CardFormat.WIDE: (1200, 630),
}


@cache
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / f"{name}.ttf"), size)


@cache
def _logo(width: int) -> Image.Image:
    logo = Image.open(ASSETS / "logo-reversed.png").convert("RGBA")
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


# --- Line drawings, one per scenario ------------------------------------------------------
# Drawn on a 100 x 100 grid, then scaled up and smoothed. White outlines with teal details.

Pen = Callable[[list[tuple[float, float]], tuple[int, int, int]], None]


def _house(line: Pen, box: Callable[..., None]) -> None:
    line([(18, 50), (50, 22), (82, 50)], WHITE)
    line([(26, 44), (26, 80), (74, 80), (74, 44)], WHITE)
    box((43, 58, 57, 80), WHITE)
    box((31, 52, 39, 60), TEAL)
    box((61, 52, 69, 60), TEAL)


def _planning(line: Pen, box: Callable[..., None]) -> None:
    # A plan sheet with a house on it and a pencil.
    box((14, 18, 70, 84), WHITE)
    for y in (30, 42, 54, 66):
        line([(22, y), (62, y)], NAVY_LINE)
    line([(24, 56), (42, 40), (60, 56)], TEAL)
    line([(28, 52), (28, 72), (56, 72), (56, 52)], TEAL)
    line([(66, 82), (88, 30), (94, 33), (72, 85), (66, 82)], WHITE)
    line([(66, 82), (68, 76)], TEAL)


def _business(line: Pen, box: Callable[..., None]) -> None:
    # A shopfront with a striped awning.
    box((18, 40, 82, 84), WHITE)
    line([(14, 40), (20, 22), (80, 22), (86, 40), (14, 40)], WHITE)
    for x in (32, 44, 56, 68):
        line([(x - 3, 22), (x, 40)], TEAL)
    box((26, 52, 46, 84), WHITE)
    box((54, 52, 74, 70), TEAL)


def _trade(line: Pen, box: Callable[..., None]) -> None:
    # Stacked shipping containers on a ship.
    line([(10, 64), (90, 64), (80, 82), (20, 82), (10, 64)], WHITE)
    for x0, y0, colour in ((20, 46, WHITE), (46, 46, TEAL), (33, 28, WHITE), (59, 28, WHITE)):
        box((x0, y0, x0 + 24, y0 + 16), colour)
        for x in range(x0 + 6, x0 + 24, 6):
            line([(x, y0 + 3), (x, y0 + 13)], colour)
    line([(4, 90), (16, 87), (28, 90), (40, 87), (52, 90), (64, 87), (76, 90), (96, 87)], TEAL)


def _sell(line: Pen, box: Callable[..., None]) -> None:
    _house(line, box)
    # A "for sale" signboard on a post.
    line([(88, 84), (88, 34)], WHITE)
    line([(88, 38), (96, 38)], WHITE)
    box((78, 44, 98, 60), TEAL)


def _rent(line: Pen, box: Callable[..., None]) -> None:
    # A key.
    line(
        [(20, 30), (40, 30), (46, 36), (46, 56), (40, 62), (20, 62), (14, 56), (14, 36), (20, 30)],
        WHITE,
    )
    box((24, 40, 36, 52), TEAL)
    line([(46, 46), (90, 46), (90, 58)], WHITE)
    line([(78, 46), (78, 56)], WHITE)
    line([(68, 46), (68, 54)], TEAL)


def _vessel(line: Pen, box: Callable[..., None]) -> None:
    # A sailing boat on waves.
    line([(16, 66), (84, 66), (74, 80), (26, 80), (16, 66)], WHITE)
    line([(50, 66), (50, 14)], WHITE)
    line([(50, 18), (78, 60), (50, 60)], TEAL)
    line([(50, 26), (28, 60), (50, 60)], WHITE)
    line([(6, 88), (18, 84), (30, 88), (42, 84), (54, 88), (66, 84), (78, 88), (94, 84)], TEAL)


def _grant(line: Pen, box: Callable[..., None]) -> None:
    # A document with a tick and a coin.
    box((18, 14, 66, 82), WHITE)
    for y in (28, 38, 48):
        line([(26, y), (58, y)], NAVY_LINE)
    line([(28, 62), (36, 70), (52, 54)], TEAL)
    line([(66, 56), (80, 50), (94, 56), (94, 76), (80, 82), (66, 76), (66, 56)], WHITE)
    line([(80, 58), (80, 74)], TEAL)


def _guide(line: Pen, box: Callable[..., None]) -> None:
    # A checklist.
    box((22, 12, 78, 88), WHITE)
    for y in (32, 50, 68):
        line([(32, y), (37, y + 5), (45, y - 5)], TEAL)
        line([(52, y), (68, y)], WHITE)


DRAWINGS: dict[str, Callable[[Pen, Callable[..., None]], None]] = {
    "PLANNING": _planning,
    "BUSINESS": _business,
    "TRADE": _trade,
    "SELL": _sell,
    "RENT": _rent,
    "VESSEL": _vessel,
    "GRANT": _grant,
}


def _badge(vertical: str, size: int) -> Image.Image:
    """The scenario's drawing in a circle, ``size`` pixels across, with a clear background."""
    big = size * SUPERSAMPLE
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.ellipse((0, 0, big - 1, big - 1), fill=NAVY_LIGHT)
    ring = max(2, big // 60)
    draw.ellipse((0, 0, big - 1, big - 1), outline=TEAL, width=ring)
    pad = big * 0.15
    scale = (big - 2 * pad) / 100
    stroke = max(2, round(big / 70))

    def at(x: float, y: float) -> tuple[float, float]:
        return (pad + x * scale, pad + y * scale)

    def line(points: list[tuple[float, float]], colour: tuple[int, int, int]) -> None:
        draw.line([at(*p) for p in points], fill=colour, width=stroke, joint="curve")

    def box(rect: tuple[float, float, float, float], colour: tuple[int, int, int]) -> None:
        x0, y0 = at(rect[0], rect[1])
        x1, y1 = at(rect[2], rect[3])
        draw.rectangle((x0, y0, x1, y1), outline=colour, width=stroke)

    DRAWINGS.get(vertical, _guide)(line, box)
    return layer.resize((size, size), Image.Resampling.LANCZOS)


def _arcs(image: Image.Image, centre: tuple[int, int], radii: range) -> None:
    """Faint rings behind the text, so a plain navy card has some depth."""
    w, h = image.size
    big = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)
    cx, cy = centre[0] * 2, centre[1] * 2
    for r in radii:
        draw.ellipse(
            (cx - 2 * r, cy - 2 * r, cx + 2 * r, cy + 2 * r), outline=(*NAVY_LIGHT, 255), width=6
        )
    image.paste(
        big.resize((w, h), Image.Resampling.LANCZOS),
        (0, 0),
        big.resize((w, h), Image.Resampling.LANCZOS),
    )


def _whole(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int, max_lines: int
) -> list[str]:
    """The text's first sentence, or nothing when it won't fit whole: a sentence cut off
    mid-way reads worse than none."""
    lines = _wrap(draw, first_sentence(text, 400), font, width)
    return lines if len(lines) <= max_lines and not lines[-1].endswith("…") else []


def _label(guide: Guide) -> str:
    parts = [p for p in (guide.area, guide.scenario) if p]
    return "  ·  ".join(parts).upper() if parts else "STEP-BY-STEP GUIDE"


def _chips(guide: Guide) -> list[str]:
    chips: list[str] = []
    if guide.steps:
        chips.append(f"{len(guide.steps)} steps")
    if guide.forms:
        chips.append(f"{guide.forms} official form{'s' if guide.forms != 1 else ''}")
    chips.append("Costs and contacts" if guide.approval is not None else "Sources for every point")
    return chips


def _draw_chips(
    draw: ImageDraw.ImageDraw, chips: list[str], x: int, y: int, size: int, width: int
) -> int:
    """Pill chips in a row (wrapping), returning the y below them."""
    font = _font("Figtree-700", size)
    pad_x, height, gap = round(size * 0.8), round(size * 2), round(size * 0.5)
    cx = x
    for chip in chips:
        w = round(draw.textlength(chip, font=font)) + 2 * pad_x
        if cx + w > x + width and cx > x:
            cx = x
            y += height + gap
        draw.rounded_rectangle(
            (cx, y, cx + w, y + height),
            radius=height // 2,
            fill=NAVY_LIGHT,
            outline=NAVY_LINE,
            width=2,
        )
        draw.text((cx + pad_x, y + height / 2), chip, font=font, fill=WHITE, anchor="lm")
        cx += w + gap
    return y + height


def _render_tall(guide: Guide, fmt: CardFormat) -> Image.Image:
    w, h = SIZES[fmt]
    margin = 88
    image = Image.new("RGB", (w, h), NAVY)
    _arcs(image, (w + 40, h + 40), range(260, 900, 110))
    draw = ImageDraw.Draw(image)
    width = w - 2 * margin

    logo = _logo(470)
    image.paste(logo, (margin - 10, margin - 6), logo)
    badge = _badge(guide.vertical, 210)
    image.paste(badge, (w - margin - badge.width, margin - 30), badge)

    y = margin + 230
    draw.text((margin, y), _label(guide), font=_font("Figtree-700", 28), fill=MUTED)
    y += 58

    max_title = 5 if fmt == CardFormat.PORTRAIT else 4
    title_font, title = _fit(
        draw, guide.title, "Outfit-700", (84, 76, 68, 60, 54), width, max_title
    )
    step = round(title_font.size * 1.14)
    for line in title:
        draw.text((margin, y), line, font=title_font, fill=WHITE)
        y += step
    y += 26
    draw.rectangle((margin, y, margin + 120, y + 8), fill=TEAL)
    y += 44

    footer_top = h - margin - 44
    chips_height = 2 * 26 + 30
    room = footer_top - chips_height - 40 - y
    body = _font("Figtree-500", 36)
    leading = round(body.size * 1.35)
    if fmt == CardFormat.PORTRAIT and guide.steps:
        for line in _whole(draw, guide.summary, body, width, 3):
            draw.text((margin, y), line, font=body, fill=MUTED)
            y += leading
        y += 22
        number = _font("Outfit-700", 34)
        for i, text in enumerate(guide.steps, 1):
            item = _wrap(draw, text, _font("Figtree-700", 34), width - 70)
            needed = len(item[:2]) * 46 + 18
            if y + needed > footer_top - chips_height - 40:
                break
            draw.ellipse((margin, y - 2, margin + 50, y + 48), outline=TEAL, width=3)
            draw.text((margin + 25, y + 23), str(i), font=number, fill=WHITE, anchor="mm")
            for k, part in enumerate(item[:2]):
                if k == 1 and len(item) > 2:
                    part = part.rstrip(" ,.;:") + "…"
                draw.text(
                    (margin + 70, y + 2 + k * 46), part, font=_font("Figtree-700", 34), fill=WHITE
                )
            y += needed
    elif room >= leading:
        for line in _whole(draw, guide.summary, body, width, room // leading):
            draw.text((margin, y), line, font=body, fill=MUTED)
            y += leading

    _draw_chips(draw, _chips(guide), margin, footer_top - chips_height - 10, 26, width)
    draw.text(
        (margin, footer_top),
        "Free step-by-step guide at approvalready.au",
        font=_font("Figtree-700", 34),
        fill=WHITE,
    )
    return image


def _render_wide(guide: Guide) -> Image.Image:
    w, h = SIZES[CardFormat.WIDE]
    margin = 64
    image = Image.new("RGB", (w, h), NAVY)
    _arcs(image, (w - 190, h // 2), range(200, 700, 90))
    draw = ImageDraw.Draw(image)
    badge = _badge(guide.vertical, 300)
    image.paste(badge, (w - margin - badge.width, (h - badge.height) // 2), badge)
    width = w - 2 * margin - badge.width - 50

    logo = _logo(360)
    image.paste(logo, (margin - 8, margin - 8), logo)
    y = margin + 108
    draw.text((margin, y), _label(guide), font=_font("Figtree-700", 22), fill=MUTED)
    y += 44
    title_font, title = _fit(draw, guide.title, "Outfit-700", (60, 54, 48, 44), width, 4)
    step = round(title_font.size * 1.14)
    for line in title:
        draw.text((margin, y), line, font=title_font, fill=WHITE)
        y += step
    y += 20
    draw.rectangle((margin, y, margin + 96, y + 7), fill=TEAL)
    _draw_chips(draw, _chips(guide), margin, h - margin - 46, 20, width)
    return image


def render(guide: Guide, fmt: CardFormat = CardFormat.SQUARE) -> bytes:
    image = _render_wide(guide) if fmt == CardFormat.WIDE else _render_tall(guide, fmt)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90, optimize=True, progressive=False)
    return out.getvalue()


def alt_text(guide: Guide, fmt: CardFormat = CardFormat.SQUARE) -> str:
    """What the card shows, for screen readers and the post's alt text."""
    facts = ", ".join(_chips(guide))
    where = f" for {guide.area}" if guide.area else ""
    return f"ApprovalReady step-by-step guide{where}: {guide.title}. {facts}."


@lru_cache(maxsize=128)
def card(ref: str, fmt: CardFormat = CardFormat.SQUARE) -> bytes | None:
    """The card for a guide, or ``None`` when there is no such guide."""
    guide = find(ref)
    return render(guide, fmt) if guide is not None else None
