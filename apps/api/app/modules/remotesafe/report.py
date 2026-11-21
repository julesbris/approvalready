"""The journey plan as a branded PDF, in the same style as every other ApprovalReady report.

The PDF prints the plan, assessment, controls and approval exactly as stored for the
current revision, with the document version and when it was made, so a printed copy can be
matched to the record.
"""

from __future__ import annotations

from app.modules.documents.render import brand_logo, brand_style, html_to_pdf, sandbox
from app.modules.remotesafe.entitlements import LIMITATIONS
from app.modules.remotesafe.schemas import (
    ControlCheckOut,
    JourneyAssessmentOut,
    JourneyEventOut,
    JourneyOut,
)

_TEMPLATE = """<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<title>Journey plan {{ j.reference }}</title>
<style>{{ style }}
.rating { font-weight: 700; }
.rating-LOW { color: #1f6f43; }
.rating-MODERATE { color: #8a5a00; }
.rating-HIGH { color: #b04a00; }
.rating-CRITICAL { color: #b00020; }
.stop { border: 2px solid #b00020; border-radius: 6px; padding: 6px 10px; margin: 6px 0; }
.small { font-size: 8.5pt; color: #4b5b74; }
.limits li { margin-bottom: 3px; }
</style>
</head>
<body>
<div class="cover">
<div class="cover-logo">{{ logo }}</div>
<h1>Journey plan</h1>
<p class="cover-project">{{ j.reference }}: {{ j.title }}</p>
</div>
<table class="details">
<tr><th>Status</th><td>{{ j.status.replace("_", " ").title() }}</td></tr>
<tr><th>Document version</th><td>Revision {{ j.revision }}</td></tr>
<tr><th>Created</th><td>{{ created }}</td></tr>
<tr><th>Risk outcome</th>
<td><span class="rating rating-{{ a.outcome }}">{{ a.outcome.title() }}</span>:
{{ a.pathway }}</td></tr>
</table>

<h2 data-section="overview">Route overview</h2>
<table class="details">
<tr><th>Worker</th><td>{{ j.worker.display_name }}{% if j.worker_phone %},
{{ j.worker_phone }}{% endif %}{% if j.team %} ({{ j.team }}){% endif %}</td></tr>
<tr><th>Supervisor</th><td>{{ j.supervisor.display_name if j.supervisor else "Not set" }}</td></tr>
<tr><th>Journey monitor</th><td>{{ j.monitor.display_name if j.monitor else "Not set" }}</td></tr>
<tr><th>From</th><td>{{ j.origin }}</td></tr>
<tr><th>To</th><td>{{ j.destination }}</td></tr>
<tr><th>Departs</th><td>{{ j.departs.local }}</td></tr>
<tr><th>Arrives</th><td>{{ j.arrives.local }}</td></tr>
<tr><th>Returns</th><td>{{ j.returns.local if j.returns else "One way" }}</td></tr>
<tr><th>Purpose</th><td>{{ j.purpose }}</td></tr>
{% if j.activities %}<tr><th>Work</th><td>{{ j.activities }}</td></tr>{% endif %}
<tr><th>Vehicle</th><td>{{ j.vehicle_description or "Not set" }}
{% if j.vehicle_registration %}({{ j.vehicle_registration }}){% endif %},
{{ j.occupants }} on board</td></tr>
<tr><th>Remoteness</th><td>{{ j.remoteness.replace("_", " ").title() }} (as stated)</td></tr>
</table>

<h2 data-section="itinerary">Planned itinerary</h2>
<table>
<tr><th>#</th><th>Leg</th><th>Departs</th><th>Arrives</th><th>Road and coverage</th></tr>
{% for l in j.legs %}
<tr><td>{{ l.position }}</td><td>{{ l.origin }} to {{ l.destination }}
{% if l.distance_km %}({{ "%g"|format(l.distance_km) }} km){% endif %}</td>
<td>{{ l.departs.local }}</td><td>{{ l.arrives.local }}</td>
<td>{{ l.road_surface.title() }} surface, coverage {{ l.mobile_coverage.lower() }},
{{ l.crossings }} crossings, closures: {{ l.closure_status.replace("_", " ").lower() }}
{% if l.closure_source %}({{ l.closure_source }}){% endif %}</td></tr>
{% endfor %}
</table>
{% if j.alternative_route %}
<p><strong>Alternative route:</strong> {{ j.alternative_route }}</p>
{% endif %}
{% if j.contingency_plan %}<p><strong>Contingency:</strong> {{ j.contingency_plan }}</p>{% endif %}

<h2 data-section="risk">Risk assessment</h2>
{% for s in a.stop_conditions %}
<div class="stop"><strong>Stop condition:</strong> {{ s.reason }}</div>
{% endfor %}
<table>
<tr><th>Hazard</th><th>Evidence</th><th>Initial</th><th>Controls</th><th>Residual</th>
<th>Responsible</th></tr>
{% for f in a.findings %}
<tr><td><strong>{{ f.title }}</strong><br><span class="small">{{ f.description }}</span></td>
<td class="small">{% for e in f.evidence %}{{ e.fact }}: {{ e.value }}
<em>({{ e.source }})</em><br>{% endfor %}</td>
<td><span class="rating rating-{{ f.initial_rating }}">{{ f.initial_rating.title() }}</span>
<span class="small">L{{ f.likelihood }} x C{{ f.consequence }}</span></td>
<td class="small">{{ f.control_labels|join("; ") }}</td>
<td><span class="rating rating-{{ f.residual_rating }}">{{ f.residual_rating.title() }}</span>
<span class="small">L{{ f.residual_likelihood }} x C{{ f.consequence }}</span></td>
<td>{{ f.responsible.title() }}</td></tr>
{% else %}
<tr><td colspan="6">No hazards were triggered by the plan as entered.</td></tr>
{% endfor %}
</table>
<p class="small">{{ a.disclaimer }}</p>

<h2 data-section="controls">Required safety controls</h2>
<table>
<tr><th>Control</th><th>Mandatory</th><th>Status</th><th>By</th></tr>
{% for c in controls %}
<tr><td>{{ c.label }}</td><td>{{ "Yes" if c.mandatory else "No" }}</td>
<td>{{ c.status.replace("_", " ").title() }}{% if c.exception_reason %}:
{{ c.exception_reason }}{% endif %}</td>
<td>{{ c.completed_by_name or "" }}</td></tr>
{% endfor %}
</table>

<h2 data-section="communications">Communications schedule</h2>
<p>Carried: {% if j.comms_mobile %}mobile phone; {% endif %}
{% if j.comms_uhf %}UHF radio; {% endif %}
{% if j.comms_sat_phone %}satellite phone; {% endif %}{% if j.comms_sat_messenger %}satellite
messenger; {% endif %}{% if j.comms_notes %}{{ j.comms_notes }}{% endif %}</p>
<table>
<tr><th>#</th><th>Check in by</th><th>Where</th><th>How</th></tr>
{% for c in j.checkins %}
<tr><td>{{ c.position }}</td><td>{{ c.due.local }}</td><td>{{ c.location or "" }}</td>
<td>{{ c.method.replace("_", " ").title() }}</td></tr>
{% else %}<tr><td colspan="4">No check-ins planned.</td></tr>{% endfor %}
</table>
<p class="small">RemoteSafe does not yet receive check-ins or raise alarms. The journey monitor
follows this schedule and escalates under your emergency response plan.</p>

<h2 data-section="contacts">Emergency contacts</h2>
<table>
<tr><th>Order</th><th>Name</th><th>Relationship</th><th>Phone</th></tr>
{% for c in j.emergency_contacts|sort(attribute="escalation_order") %}
<tr><td>{{ c.escalation_order }}</td><td>{{ c.name }}</td><td>{{ c.relationship or "" }}</td>
<td>{{ c.phone }}</td></tr>
{% else %}<tr><td colspan="4">None recorded.</td></tr>{% endfor %}
</table>
<p>In an emergency call <strong>000</strong> (112 from a mobile).</p>

<h2 data-section="approval">Approval record</h2>
<table class="details">
<tr><th>Approved</th><td>{% if j.approved_at %}
{{ j.approved_by.display_name if j.approved_by else "" }}, {{ approved }}
(revision {{ j.approved_revision }}, {{ (j.approved_outcome or "").title() }})
{% else %}Not approved{% endif %}</td></tr>
{% if j.critical_alternative_process %}<tr><th>Alternative process</th>
<td>{{ j.critical_alternative_process }}</td></tr>{% endif %}
</table>
<table>
<tr><th>When (UTC)</th><th>What</th><th>Who</th><th>Note</th></tr>
{% for e in events %}
<tr><td class="small">{{ e.occurred_at.strftime("%d/%m/%Y %H:%M") }}</td>
<td>{{ e.kind.replace("_", " ").title() }}</td><td>{{ e.actor_name or "" }}</td>
<td class="small">{{ e.note or "" }}</td></tr>
{% endfor %}
</table>

<h2 data-section="limitations">Limitations</h2>
<ul class="limits">{% for l in limitations %}<li>{{ l }}</li>{% endfor %}</ul>
<footer><p class="small">{{ j.reference }}, revision {{ j.revision }}, created {{ created }}.
Data sources: {{ a.data_sources|join(" ") }}</p></footer>
</body>
</html>
"""


def plan_html(
    j: JourneyOut,
    a: JourneyAssessmentOut,
    controls: list[ControlCheckOut],
    events: list[JourneyEventOut],
    created: str,
    approved: str,
) -> str:
    return (
        sandbox()
        .from_string(_TEMPLATE)
        .render(
            j=j,
            a=a,
            controls=controls,
            events=events,
            created=created,
            approved=approved,
            limitations=LIMITATIONS,
            style=brand_style(),
            logo=brand_logo(),
        )
    )


def plan_pdf(html: str) -> bytes:
    return html_to_pdf(html)
