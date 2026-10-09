"""Rendering report templates to HTML, PDF and Word.

A template version's body is a Jinja template rendered in a sandbox with autoescaping, from
a plain-data context (no ORM objects, no callables). The result is placed inside a frame
that this module owns, so every generated document carries the required report metadata
whatever the template says: date, project reference, project status, review status, the
assumptions it relies on, missing information, sources, limitations and the disclaimer.
``check_required`` verifies those sections are present before anything is stored.

PDF comes from WeasyPrint with every external fetch refused (no file://, no http://). Word
comes from converting the same HTML, so all three formats say the same thing. Templates
should only use: h1-h3, p, ul, ol, li, table, tr, th, td, strong, b, em, i, br.
"""

from __future__ import annotations

import io
import re
from html.parser import HTMLParser
from typing import Any

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

REQUIRED_SECTIONS = (
    "metadata",
    "review-status",
    "assumptions",
    "missing-information",
    "sources",
    "limitations",
    "disclaimer",
)

DISCLAIMER = (
    "This report applies reviewed rules to the answers you gave. It is general information, "
    "not legal or planning advice, and it is not a council decision. Confidence levels show "
    "how far each result is supported by sources our team has verified. Check anything "
    "important with the authority or a qualified professional before acting on it."
)

_STYLE = """
@page { size: A4; margin: 18mm 16mm 20mm;
  @bottom-center { content: "Page " counter(page) " of " counter(pages); font-size: 8pt;
    color: #555; } }
body { font-family: "DejaVu Sans", Arial, sans-serif; font-size: 10pt; color: #18181b;
  line-height: 1.45; max-width: 800px; margin: 0 auto; padding: 16px; }
h1 { font-size: 18pt; margin: 0 0 4px; }
h2 { font-size: 13pt; margin: 18px 0 6px; border-bottom: 1px solid #d4d4d8;
  padding-bottom: 2px; }
h3 { font-size: 11pt; margin: 12px 0 4px; }
table { border-collapse: collapse; width: 100%; margin: 6px 0; }
th, td { border: 1px solid #d4d4d8; padding: 4px 6px; text-align: left; vertical-align: top; }
th { background: #f4f4f5; }
.note { border: 1px solid #a1a1aa; background: #fafafa; padding: 6px 8px; }
"""

_FRAME = """<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<title>{{ meta.title }} - {{ meta.project_reference }}</title>
<meta name="description" content="{{ meta.title }} for project {{ meta.project_reference }}">
<style>{{ style }}</style>
</head>
<body>
<header data-section="metadata">
<h1>{{ meta.title }}</h1>
<table>
<tr><th>Project</th><td>{{ meta.project_title }} ({{ meta.project_reference }})</td></tr>
<tr><th>Project status</th><td>{{ meta.project_status }}</td></tr>
<tr><th>Assessment date</th><td>{{ meta.assessed_on }}</td></tr>
<tr><th>Generated</th><td>{{ meta.generated_at }}</td></tr>
<tr><th>Document</th><td>{{ meta.document_id }}</td></tr>
<tr><th>Template</th><td>{{ meta.template_key }} version {{ meta.template_version }}</td></tr>
<tr><th>Rules engine</th><td>{{ meta.engine_version }}, facts {{ meta.facts_hash }}</td></tr>
</table>
</header>
<section data-section="review-status">
<p class="note"><strong>Review status: {{ meta.review_status }}.</strong>
{{ meta.review_status_detail }}</p>
{% if review.reviewer %}
<p>Reviewer: {{ review.reviewer }}
{%- if review.decided_on %}, {{ review.decided_on }}{% endif %}.</p>
{% endif %}
{% if review.notes %}<p>Reviewer's notes: {{ review.notes }}</p>{% endif %}
{% if review.changes %}
<h3>Changes made by the reviewer</h3>
<p>The reviewer changed these findings. The original result is kept for reference.</p>
<table>
<tr><th>Finding</th><th>Was</th><th>Now</th><th>Reason</th></tr>
{% for c in review.changes %}<tr><td>{{ c.finding }}</td><td>{{ c.before }}</td>
<td>{{ c.after }}</td>
<td>{{ c.reason }}{% if c.source %} (source: {{ c.source }}){% endif %}</td></tr>
{% endfor %}
</table>
{% endif %}
</section>
<main>
{{ body }}
</main>
<section data-section="assumptions">
<h2>Assumptions</h2>
<p>This report assumes the answers below are accurate and complete.</p>
{% if assumptions %}
<table>
<tr><th>Question</th><th>Your answer</th></tr>
{% for a in assumptions %}<tr><td>{{ a.label }}</td><td>{{ a.value }}</td></tr>{% endfor %}
</table>
{% else %}<p>No answers were recorded.</p>{% endif %}
</section>
<section data-section="missing-information">
<h2>Missing information</h2>
{% if missing %}
<p>These answers would make the results more certain:</p>
<ul>{% for m in missing %}<li>{{ m }}</li>{% endfor %}</ul>
{% else %}<p>None identified.</p>{% endif %}
</section>
<section data-section="sources">
<h2>Sources</h2>
{% if sources %}
<ul>{% for s in sources %}<li>{{ s.citation }}: {{ s.document_title }}, {{ s.organisation_name }}
({{ s.verification }}{% if not s.in_force %}, not in force on the assessment date{% endif %}).
{{ s.url }}</li>{% endfor %}</ul>
{% else %}<p>No sources were cited.</p>{% endif %}
</section>
<section data-section="limitations">
<h2>Limitations</h2>
{% if limitations %}
<ul>{% for l in limitations %}<li>{{ l }}</li>{% endfor %}</ul>
{% else %}<p>None recorded for the rules applied.</p>{% endif %}
</section>
<footer data-section="disclaimer">
<h2>Important</h2>
<p>{{ disclaimer }}</p>
</footer>
</body>
</html>
"""


class RenderError(ValueError):
    pass


def sandbox() -> SandboxedEnvironment:
    return SandboxedEnvironment(autoescape=True, undefined=StrictUndefined, trim_blocks=True)


def render_html(template_body: str, context: dict[str, Any]) -> str:
    """The complete HTML document: the template's body inside the required frame."""
    env = sandbox()
    try:
        body = env.from_string(template_body).render(**context)
        html = env.from_string(_FRAME).render(
            **context, body=_markup(body), style=_markup(_STYLE), disclaimer=DISCLAIMER
        )
    except Exception as exc:  # template bugs must never produce a half-rendered report
        raise RenderError(f"template could not be rendered: {exc}") from exc
    check_required(html)
    return html


def _markup(value: str) -> Any:
    from markupsafe import Markup

    return Markup(value)  # noqa: S704 - body was rendered by the sandbox with autoescaping


def check_required(html: str) -> None:
    present = set(re.findall(r'data-section="([a-z-]+)"', html))
    missing = [s for s in REQUIRED_SECTIONS if s not in present]
    if missing:
        raise RenderError(f"report is missing required sections: {', '.join(missing)}")


def html_to_pdf(html: str) -> bytes:
    from weasyprint import HTML, URLFetcher

    # An empty protocol allowlist refuses every URL: no local files, no network.
    pdf: bytes = HTML(string=html, url_fetcher=URLFetcher(allowed_protocols=())).write_pdf()
    return pdf


# --- HTML to Word ----------------------------------------------------------------------

_SKIP = {"head", "style", "script", "title"}
_WS = re.compile(r"\s+")


class _DocxBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        from docx import Document

        self.doc: Any = Document()
        self.para: Any = None
        self.skip = 0
        self.bold = 0
        self.italic = 0
        self.lists: list[str] = []
        self.rows: list[list[tuple[str, bool]]] | None = None
        self.cell: list[str] | None = None
        self.cell_header = False

    def _paragraph(self, style: str | None = None) -> Any:
        self.para = self.doc.add_paragraph(style=style)
        return self.para

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self.skip += 1
        elif self.skip:
            return
        elif tag in {"h1", "h2", "h3"}:
            self.para = self.doc.add_heading(level=int(tag[1]) - 1)  # h1 is the Title style
        elif tag == "p" and self.cell is None:
            self._paragraph()
        elif tag in {"ul", "ol"}:
            self.lists.append(tag)
        elif tag == "li":
            ordered = bool(self.lists) and self.lists[-1] == "ol"
            self._paragraph("List Number" if ordered else "List Bullet")
        elif tag == "table":
            self.rows = []
        elif tag == "tr" and self.rows is not None:
            self.rows.append([])
        elif tag in {"th", "td"} and self.rows is not None:
            self.cell = []
            self.cell_header = tag == "th"
        elif tag in {"strong", "b"}:
            self.bold += 1
        elif tag in {"em", "i"}:
            self.italic += 1
        elif tag == "br":
            if self.cell is not None:
                self.cell.append("\n")
            elif self.para is not None:
                self.para.add_run().add_break()

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self.skip = max(self.skip - 1, 0)
        elif self.skip:
            return
        elif tag in {"h1", "h2", "h3", "p", "li"}:
            self.para = None
        elif tag in {"ul", "ol"} and self.lists:
            self.lists.pop()
        elif tag in {"th", "td"} and self.rows is not None and self.cell is not None:
            if self.rows:
                text = _WS.sub(" ", "".join(self.cell)).strip()
                self.rows[-1].append((text, self.cell_header))
            self.cell = None
        elif tag == "table" and self.rows is not None:
            self._table(self.rows)
            self.rows = None
            self.para = None
        elif tag in {"strong", "b"}:
            self.bold = max(self.bold - 1, 0)
        elif tag in {"em", "i"}:
            self.italic = max(self.italic - 1, 0)

    def _table(self, rows: list[list[tuple[str, bool]]]) -> None:
        rows = [r for r in rows if r]
        if not rows:
            return
        width = max(len(r) for r in rows)
        table = self.doc.add_table(rows=len(rows), cols=width)
        table.style = "Table Grid"
        for i, row in enumerate(rows):
            for j, (text, header) in enumerate(row):
                cell = table.cell(i, j)
                run = cell.paragraphs[0].add_run(text)
                run.bold = header

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        if self.cell is not None:
            self.cell.append(data)
            return
        text = _WS.sub(" ", data)
        if self.para is None:
            if not text.strip():
                return
            self._paragraph()
        if not self.para.runs:
            text = text.lstrip()
        if text:
            run = self.para.add_run(text)
            run.bold = self.bold > 0 or None
            run.italic = self.italic > 0 or None


def html_to_docx(html: str, *, title: str) -> bytes:
    builder = _DocxBuilder()
    builder.doc.core_properties.title = title
    builder.feed(html)
    builder.close()
    out = io.BytesIO()
    builder.doc.save(out)
    return out.getvalue()
