from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Event, Incident, ReportRevision, Service
from .security import redact


@transaction.atomic
def record_check(service_id, *, external_id, healthy, latency_ms, message, checked_at=None):
    service = Service.objects.select_for_update().get(pk=service_id)
    if Event.objects.filter(service=service, external_id=external_id).exists():
        return False
    if not service.enabled:
        return False
    at = checked_at or timezone.now()
    event = Event.objects.create(
        service=service,
        external_id=external_id,
        kind=Event.Kind.CHECK,
        occurred_at=at,
        healthy=healthy,
        latency_ms=latency_ms,
        message=redact(message),
    )
    # A late check remains evidence but must not overwrite newer health state.
    if service.last_checked_at and at <= service.last_checked_at:
        return True
    incident = service.incidents.filter(status=Incident.Status.OPEN).first()
    service.last_checked_at = at
    service.last_check_ok = healthy
    service.last_latency_ms = latency_ms
    if healthy:
        service.consecutive_failures = 0
        service.first_failure_at = None
        service.consecutive_successes += 1
        if incident and service.consecutive_successes >= 2:
            incident.status = Incident.Status.RECOVERED
            incident.recovered_at = at
            incident.save(update_fields=["status", "recovered_at"])
    else:
        service.consecutive_successes = 0
        service.consecutive_failures += 1
        if service.first_failure_at is None:
            service.first_failure_at = at
        if incident is None and service.consecutive_failures >= 3:
            incident = Incident.objects.create(
                service=service,
                started_at=service.first_failure_at,
                detected_at=at,
            )
            # Include the failed checks before detection and nearby application errors.
            service.events.filter(
                incident__isnull=True,
                occurred_at__gte=incident.started_at - timedelta(minutes=5),
                occurred_at__lte=at,
            ).update(incident=incident)
    if incident:
        event.incident = incident
        event.save(update_fields=["incident"])
    service.save()
    return True


@transaction.atomic
def ingest_error(service_id, data):
    service = Service.objects.select_for_update().get(pk=service_id)
    existing = Event.objects.filter(service=service, external_id=data["external_id"]).first()
    if existing:
        return existing, False
    # Use occurrence time for late logs, not whichever incident happens to be open now.
    incident = (
        service.incidents.filter(started_at__lte=data["occurred_at"])
        .filter(Q(recovered_at__isnull=True) | Q(recovered_at__gte=data["occurred_at"]))
        .first()
    )
    if incident is None:
        incident = (
            service.incidents.filter(
                started_at__gt=data["occurred_at"],
                started_at__lte=data["occurred_at"] + timedelta(minutes=5),
            )
            .order_by("started_at")
            .first()
        )
    event = Event.objects.create(
        service=service,
        incident=incident,
        kind=Event.Kind.ERROR,
        external_id=data["external_id"],
        occurred_at=data["occurred_at"],
        message=redact(data["message"]),
        metadata={key: redact(value) for key, value in data.get("metadata", {}).items()},
    )
    return event, True


def template_report(incident):
    events = list(incident.events.order_by("-occurred_at", "-received_at")[:100])
    events.reverse()
    recovered = incident.recovered_at.isoformat() if incident.recovered_at else "Not confirmed"
    duration = (
        f"{int((incident.recovered_at - incident.started_at).total_seconds())} seconds"
        if incident.recovered_at
        else "Still open"
    )
    lines = [
        f"# Incident: {incident.service.name}",
        "",
        "Draft built from recorded events. This version does not use AI.",
        "",
        "## What was observed",
        "",
        "The monitor recorded three consecutive failed health checks.",
        f"- First observed failure (UTC): {incident.started_at.isoformat()}",
        f"- Detection threshold reached (UTC): {incident.detected_at.isoformat()}",
        f"- Recovery confirmed (UTC): {recovered}",
        f"- Observed incident window: {duration}",
        "- User impact: Not measured by this monitor.",
        "",
        "## Timeline and evidence",
        "",
    ]
    lines.extend(
        f"- {event.occurred_at.isoformat()} [{event.id}] {event.message}" for event in events
    )
    if incident.events.count() > 100:
        lines.append("Only the latest 100 events are included in this snapshot.")
    lines.extend(
        [
            "",
            "## Confirmed cause",
            "",
            incident.confirmed_cause
            or "Not confirmed. Health checks alone do not explain the cause.",
            "",
            "## Resolution",
            "",
            incident.resolution or "Add the fix after investigating.",
            "",
            "## Follow-up",
            "",
            "Add one practical step to reduce the chance of this happening again.",
        ]
    )
    return "\n".join(lines), [str(event.id) for event in events]


class RevisionConflict(Exception):
    pass


@transaction.atomic
def save_report(incident_id, user, *, request_id, expected_revision, content=None):
    incident = Incident.objects.select_for_update().select_related("service").get(pk=incident_id)
    existing = incident.reports.filter(request_id=request_id).first()
    if existing:
        return existing, False
    latest = incident.reports.first()
    current = latest.number if latest else 0
    if current != expected_revision:
        raise RevisionConflict("A newer report exists. Reload it before saving.")
    if content is None:
        content, evidence_ids = template_report(incident)
        source = "template"
    else:
        evidence_ids = latest.evidence_ids if latest else []
        source = "human"
    report = ReportRevision.objects.create(
        incident=incident,
        number=current + 1,
        request_id=request_id,
        source=source,
        content=content,
        evidence_ids=evidence_ids,
        created_by=user,
    )
    return report, True
