"""The property report as a branded PDF, in the same style as every other report."""

from __future__ import annotations

from app.modules.documents.render import brand_logo, brand_style, html_to_pdf, sandbox
from app.modules.property_report.schemas import PropertyReportOut, ReportChart

_TEMPLATE = """<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<title>Property report - {{ r.address }}</title>
<style>{{ style }}
.headline li { margin-bottom: 4px; }
.status { color: #4b5b74; font-size: 9pt; }
td.num { white-space: nowrap; }
.scores { width: 100%; border-collapse: collapse; }
.scores td { padding: 4px 6px; vertical-align: top; }
.score { font-size: 16pt; font-weight: 700; color: #012455; white-space: nowrap; }
.score small { font-size: 9pt; font-weight: 400; color: #4b5b74; }
.overall { font-size: 26pt; font-weight: 700; color: #00776b; }
.chart { margin: 6px 0 12px; }
.chart td { padding: 2px 6px; border: none; }
.bar { height: 9px; background: #00776b; border-radius: 2px; }
.bar.compare { background: #b9c4d3; margin-top: 2px; }
.finance { border: 2px solid #00776b; border-radius: 8px; padding: 10px 14px; margin: 14px 0; }
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
{% if r.overall_score is not none %}
<h2>Neighbourhood scores</h2>
<p><span class="overall">{{ "%.1f"|format(r.overall_score) }}</span> out of 10 overall.
Each score is worked out from distances in this report.</p>
<table class="scores">
{% for sc in r.scores %}<tr><td class="score">{{ "%.1f"|format(sc.score) }}<small>/10</small></td>
<td><strong>{{ sc.label }}</strong><br>{{ sc.summary }}</td></tr>
{% endfor %}
</table>
{% endif %}
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
{% for c in s.charts %}
<h3>{{ c.title }}</h3>
<table class="chart">
{% set top = scale(c) %}
{% for b in c.bars %}<tr><td>{{ b.label }}</td><td style="width:45%">
<div class="bar" style="width:{{ b.value * 100 / top }}%"></div>
{%- if b.compare is not none %}<div class="bar compare" style="width:{{ b.compare * 100 / top }}%">
</div>{% endif %}</td>
<td class="num">{{ "%g"|format(b.value) }}% {% if b.compare is not none %}
<span class="status">({{ c.compare_label }} {{ "%g"|format(b.compare) }}%)</span>
{%- endif %}</td></tr>
{% endfor %}
</table>
{% endfor %}
{% if s.key == "market" %}
<div class="finance">
<h3>Buying your next place?</h3>
<p>Home loans, bridging finance while you sell, and refinancing. Send an enquiry and a
finance specialist will contact you: {{ r.finance_url }}</p>
</div>
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


def scale(chart: ReportChart) -> float:
    """The longest bar fills the column, so small shares stay readable."""
    values = [b.value for b in chart.bars] + [b.compare or 0 for b in chart.bars]
    return max([*values, 1.0])


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
            scale=scale,
            generated=report.generated_at.strftime("%d %B %Y").lstrip("0"),
        )
    )


def report_pdf(report: PropertyReportOut) -> bytes:
    return html_to_pdf(report_html(report))
