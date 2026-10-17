import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class Service(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=80)
    environment = models.CharField(max_length=30, default="development")
    health_url = models.URLField(max_length=500)
    enabled = models.BooleanField(default=True)
    key_digest = models.CharField(max_length=64, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_check_ok = models.BooleanField(null=True)
    last_latency_ms = models.PositiveIntegerField(null=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    consecutive_successes = models.PositiveIntegerField(default=0)
    first_failure_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name", "environment"], name="unique_owned_service"
            )
        ]


class Incident(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RECOVERED = "recovered", "Recovered"
        CLOSED = "closed", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="incidents")
    status = models.CharField(max_length=12, choices=Status, default=Status.OPEN)
    started_at = models.DateTimeField()
    detected_at = models.DateTimeField()
    recovered_at = models.DateTimeField(null=True, blank=True)
    confirmed_cause = models.TextField(blank=True)
    resolution = models.TextField(blank=True)

    class Meta:
        ordering = ["-detected_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["service"], condition=Q(status="open"), name="one_open_incident_per_service"
            )
        ]


class Event(models.Model):
    class Kind(models.TextChoices):
        CHECK = "check", "Health check"
        ERROR = "error", "Application error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="events")
    incident = models.ForeignKey(
        Incident, null=True, blank=True, on_delete=models.SET_NULL, related_name="events"
    )
    external_id = models.UUIDField()
    kind = models.CharField(max_length=10, choices=Kind)
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    message = models.CharField(max_length=2000)
    healthy = models.BooleanField(null=True)
    latency_ms = models.PositiveIntegerField(null=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["occurred_at", "received_at"]
        constraints = [
            models.UniqueConstraint(fields=["service", "external_id"], name="unique_service_event")
        ]
        indexes = [models.Index(fields=["service", "occurred_at"])]


class ReportRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="reports")
    number = models.PositiveIntegerField()
    request_id = models.UUIDField()
    source = models.CharField(max_length=10, choices=[("template", "Template"), ("human", "Human")])
    content = models.TextField()
    evidence_ids = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["incident", "number"], name="unique_report_revision"),
            models.UniqueConstraint(
                fields=["incident", "request_id"], name="unique_report_request"
            ),
        ]
