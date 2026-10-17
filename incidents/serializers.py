from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from .models import Event, Incident, ReportRevision, Service
from .security import validate_health_url


class ServiceSerializer(serializers.ModelSerializer):
    health = serializers.SerializerMethodField()
    enabled = serializers.BooleanField(required=False, default=True)
    # Django's default URL field rejects single-label Compose names such as "demo".
    # Our explicit operator allowlist is used for these local monitoring targets.
    health_url = serializers.CharField(max_length=500)

    class Meta:
        model = Service
        fields = [
            "id",
            "name",
            "environment",
            "health_url",
            "enabled",
            "health",
            "last_checked_at",
            "last_latency_ms",
            "consecutive_failures",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "health",
            "last_checked_at",
            "last_latency_ms",
            "consecutive_failures",
            "created_at",
        ]

    def validate_health_url(self, value):
        return validate_health_url(value)

    def validate(self, attrs):
        owner = self.context["request"].user
        name = attrs.get("name", getattr(self.instance, "name", None))
        environment = attrs.get("environment", getattr(self.instance, "environment", "development"))
        matches = Service.objects.filter(owner=owner, name=name, environment=environment)
        if self.instance:
            matches = matches.exclude(pk=self.instance.pk)
            if attrs.get("health_url", self.instance.health_url) != self.instance.health_url:
                raise serializers.ValidationError(
                    {"health_url": "Register a new service to change the monitored endpoint."}
                )
        if matches.exists():
            raise serializers.ValidationError("A service with that name and environment exists.")
        return attrs

    def get_health(self, obj):
        if not obj.enabled:
            return "paused"
        if not obj.last_checked_at:
            return "unknown"
        if (timezone.now() - obj.last_checked_at).total_seconds() > settings.MONITOR_STALE_SECONDS:
            return "stale"
        if obj.incidents.filter(status=Incident.Status.OPEN).exists():
            return "down" if obj.last_check_ok is False else "recovering"
        return "healthy" if obj.last_check_ok else "suspected"


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = [
            "id",
            "kind",
            "occurred_at",
            "received_at",
            "message",
            "healthy",
            "latency_ms",
            "metadata",
        ]


class ErrorInputSerializer(serializers.Serializer):
    external_id = serializers.UUIDField()
    occurred_at = serializers.DateTimeField()
    message = serializers.CharField(max_length=2000)
    metadata = serializers.DictField(
        child=serializers.CharField(max_length=300),
        required=False,
        default=dict,
    )

    def validate_occurred_at(self, value):
        now = timezone.now()
        if value > now + timedelta(seconds=30) or value < now - timedelta(days=7):
            raise serializers.ValidationError("Use a timestamp within the last 7 days, in UTC.")
        return value

    def validate_metadata(self, value):
        if set(value) - {"exception_type", "path", "release"}:
            raise serializers.ValidationError("Allowed keys: exception_type, path, release.")
        return value


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportRevision
        fields = ["id", "number", "source", "content", "evidence_ids", "created_at"]


class ReportInputSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    expected_revision = serializers.IntegerField(min_value=0)
    content = serializers.CharField(max_length=30000, required=False)


class IncidentSerializer(serializers.ModelSerializer):
    confirmed_cause = serializers.CharField(max_length=10000, allow_blank=True, required=False)
    resolution = serializers.CharField(max_length=10000, allow_blank=True, required=False)
    service_name = serializers.CharField(source="service.name", read_only=True)
    environment = serializers.CharField(source="service.environment", read_only=True)
    duration_seconds = serializers.SerializerMethodField()
    event_count = serializers.IntegerField(source="events.count", read_only=True)

    class Meta:
        model = Incident
        fields = [
            "id",
            "service",
            "service_name",
            "environment",
            "status",
            "started_at",
            "detected_at",
            "recovered_at",
            "duration_seconds",
            "event_count",
            "confirmed_cause",
            "resolution",
        ]
        read_only_fields = [
            "id",
            "service",
            "started_at",
            "detected_at",
            "recovered_at",
        ]

    def get_duration_seconds(self, obj):
        if obj.recovered_at:
            return int((obj.recovered_at - obj.started_at).total_seconds())
        return None

    def validate_status(self, value):
        # Health processing owns open -> recovered. The user only reviews recovery.
        if not (self.instance.status == "recovered" and value == "closed"):
            raise serializers.ValidationError("Only a recovered incident can be closed.")
        return value
