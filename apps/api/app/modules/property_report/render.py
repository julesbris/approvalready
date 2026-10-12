"""The property report as a branded PDF, in the same style as every other report."""

from __future__ import annotations

from app.modules.documents.render import brand_logo, brand_style, html_to_pdf, sandbox
from app.modules.property_report.schemas import PropertyReportOut

_TEMPLATE = """<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<title>Property report - {{ r.address }}</title>
<style>{{ style }}
.headline li { margin-bottom: 4px; }
.status { color: #4b5b74; font-size: 9pt; }
td.num { white-space: nowrap; }
</style>
</head>
<body>
<div class="cover">
<div class="cover-logo">{{ logo }}</div>
<h1>Property report</h1>
<p class="cover-project">{{ r.address }}</p>
</div>
<table class="details">
<tr><th>Suburb</th><td>{{ r.suburb or "" }}</td></tr>
<tr><th>Council</th><td>{{ r.council or "Not known" }}</td></tr>
<tr><th>Prepared</th><td>{{ generated }}</td></tr>
</table>
{% if r.headline %}
<h2>At a glance</h2>
<ul class="headline">{% for h in r.headline %}<li>{{ h }}</li>{% endfor %}</ul>
{% endif %}
{% for s in r.sections %}
<h2>{{ s.title }}</h2>
<p>{{ s.intro }}</p>
{% if s.status == "unavailable" %}
<p class="note">We couldn't check this just now. Try the report again later.</p>
{% elif s.status == "partial" %}
<p class="status">Some of this couldn't be checked just now.</p>
{% endif %}
{% if s.facts %}
<table>
{% for f in s.facts %}<tr><th>{{ f.label }}</th><td>{{ f.value }}
{%- if f.compare %}<br><em>{{ f.compare }}</em>{% endif %}
{%- if f.note %}<br>{{ f.note }}{% endif %}</td></tr>
{% endfor %}
</table>
{% endif %}
{% if s.items %}
<table>
{% for i in s.items %}<tr><td>{{ i.label }}{% if i.detail %}<br>{{ i.detail }}{% endif %}</td>
<td class="num">{% if i.distance_m is not none %}{{ distance(i.distance_m) }}{% endif %}</td></tr>
{% endfor %}
</table>
{% endif %}
{% if s.links %}
<h3>Where to check</h3>
<ul>{% for l in s.links %}<li><strong>{{ l.label }}</strong>: {{ l.why }} {{ l.url }}</li>
{% endfor %}</ul>
{% endif %}
{% if s.sources %}
<p class="status">Source: {% for src in s.sources %}{{ src.name }} ({{ src.as_at }})
{%- if not loop.last %}; {% endif %}{% endfor %}.</p>
{% endif %}
{% endfor %}
<footer data-section="disclaimer">
<h2>Important</h2>
<p>{{ r.disclaimer }}</p>
</footer>
</body>
</html>
"""


def distance(metres: int) -> str:
    if metres < 1000:
        return f"{round(metres / 10) * 10} m"
    return f"{metres / 1000:.1f} km"


def report_html(report: PropertyReportOut) -> str:
    return (
        sandbox()
        .from_string(_TEMPLATE)
        .render(
            r=report,
            style=brand_style(),
            logo=brand_logo(),
            distance=distance,
            generated=report.generated_at.strftime("%d %B %Y").lstrip("0"),
        )
    )


def report_pdf(report: PropertyReportOut) -> bytes:
    return html_to_pdf(report_html(report))
