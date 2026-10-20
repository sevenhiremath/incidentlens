import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from incidents.models import Event

pytestmark = pytest.mark.django_db


def test_summary_of_a_service_without_checks(client, service):
    response = client.get(f"/api/services/{service.pk}/summary/")
    assert response.status_code == 200
    assert response.data == {
        "sample_limit": 100,
        "total_checks": 0,
        "healthy_checks": 0,
        "failed_checks": 0,
        "success_rate_percent": None,
        "average_latency_ms": None,
    }


def test_summary_requires_login(service):
    response = APIClient().get(f"/api/services/{service.pk}/summary/")
    assert response.status_code == 401


def test_summary_cannot_read_another_users_service(client, service):
    other = get_user_model().objects.create_user("other-summary-user")
    client.force_authenticate(user=other)
    assert client.get(f"/api/services/{service.pk}/summary/").status_code == 404


def test_summary_uses_latest_100_checks_even_with_newer_application_errors(client, service):
    now = timezone.now()
    Event.objects.bulk_create(
        [
            Event(
                service=service,
                external_id=uuid.uuid4(),
                kind="check",
                healthy=index >= 5,
                latency_ms=index,
                occurred_at=now - timedelta(seconds=110 - index),
                message="Recorded health check",
            )
            for index in range(105)
        ]
    )
    Event.objects.bulk_create(
        [
            Event(
                service=service,
                external_id=uuid.uuid4(),
                kind="error",
                occurred_at=now,
                message="Application errors must not displace health checks in the sample",
            )
            for _ in range(100)
        ]
    )
    response = client.get(f"/api/services/{service.pk}/summary/")
    assert response.status_code == 200
    assert response.data["total_checks"] == 100
    assert response.data["healthy_checks"] == 100
    assert response.data["failed_checks"] == 0
    assert response.data["success_rate_percent"] == 100.0
    assert response.data["average_latency_ms"] == 54.5
