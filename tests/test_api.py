import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from incidents.logic import ingest_error
from incidents.models import Service

pytestmark = pytest.mark.django_db


def test_login_and_logout_revoke_token(owner):
    client = APIClient()
    result = client.post(
        "/api/auth/login/",
        {
            "username": "developer",
            "password": "test-only-example-passphrase",
        },
    )
    assert result.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Token {result.data['token']}")
    assert client.get("/api/services/").status_code == 200
    assert client.post("/api/auth/logout/").status_code == 204
    assert client.get("/api/services/").status_code == 401


def test_bad_login_returns_generic_error(owner):
    result = APIClient().post("/api/auth/login/", {"username": "developer", "password": "wrong"})
    assert result.status_code == 401
    assert "incorrect" in str(result.data)


def test_malformed_login_returns_validation_error():
    response = APIClient().post("/api/auth/login/", ["invalid"], format="json")
    assert response.status_code == 400


def test_unauthenticated_api_is_rejected():
    assert APIClient().get("/api/incidents/").status_code == 401


def test_service_registration_hides_keys(client):
    result = client.post(
        "/api/services/",
        {
            "name": "Billing",
            "health_url": "http://localhost:5055/health",
        },
    )
    assert result.status_code == 201
    assert result.data["health"] == "unknown"
    assert "key_digest" not in result.data
    assert "owner" not in result.data


def test_allowlisted_compose_hostname_can_be_registered(client):
    response = client.post(
        "/api/services/",
        {
            "name": "Container demo",
            "health_url": "http://demo:5055/health",
        },
        format="json",
    )
    assert response.status_code == 201


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://example.com/health",
        "http://user:password@localhost/health",
        "http://localhost/health?token=secret",
        "http://localhost/health#fragment",
        "ftp://localhost/file",
        "http://localhost:0/health",
    ],
)
def test_unsafe_monitor_targets_are_rejected(client, url):
    result = client.post("/api/services/", {"name": "Unsafe target", "health_url": url})
    assert result.status_code == 400


def test_service_endpoint_cannot_silently_change(client, service):
    result = client.patch(
        f"/api/services/{service.pk}/",
        {
            "health_url": "http://localhost:5056/health",
        },
    )
    assert result.status_code == 400


def test_duplicate_service_name_is_a_validation_error(client, service):
    result = client.post(
        "/api/services/",
        {
            "name": service.name,
            "health_url": service.health_url,
        },
    )
    assert result.status_code == 400


def test_pause_and_resume_reset_detection_streak(client, service, check):
    check(False)
    check(False)
    path = f"/api/services/{service.pk}/"
    assert client.patch(path, {"enabled": False}, format="json").status_code == 200
    assert client.patch(path, {"enabled": True}, format="json").status_code == 200
    check(False)
    service.refresh_from_db()
    assert service.consecutive_failures == 1
    assert not service.incidents.exists()


def test_other_users_cannot_read_or_modify_owned_data(client, service, incident):
    other = get_user_model().objects.create_user("other", password="another-test-passphrase")
    client.force_authenticate(user=other)
    assert client.get("/api/services/").data["count"] == 0
    assert client.get("/api/incidents/").data["count"] == 0
    for path in [
        f"services/{service.pk}/",
        f"services/{service.pk}/history/",
        f"incidents/{incident.pk}/",
        f"incidents/{incident.pk}/events/",
        f"incidents/{incident.pk}/reports/",
    ]:
        assert client.get(f"/api/{path}").status_code == 404
    assert client.patch(f"/api/incidents/{incident.pk}/", {"resolution": "bad"}).status_code == 404
    assert client.post(f"/api/services/{service.pk}/key/").status_code == 404
    assert (
        client.post(
            f"/api/incidents/{incident.pk}/reports/",
            {
                "request_id": str(uuid.uuid4()),
                "expected_revision": 0,
            },
        ).status_code
        == 404
    )


def test_rotated_service_key_and_duplicate_error(client, service):
    path = f"/api/services/{service.pk}/events/"
    first = client.post(f"/api/services/{service.pk}/key/").data["service_key"]
    second = client.post(f"/api/services/{service.pk}/key/").data["service_key"]
    sender = APIClient()
    payload = {
        "external_id": str(uuid.uuid4()),
        "occurred_at": timezone.now().isoformat(),
        "message": "Dependency failed token=abc password=def Bearer xyz",
        "metadata": {"exception_type": "ConnectionError"},
    }
    assert sender.post(path, payload, format="json", HTTP_X_SERVICE_KEY=first).status_code == 401
    accepted = sender.post(path, payload, format="json", HTTP_X_SERVICE_KEY=second)
    duplicate = sender.post(path, payload, format="json", HTTP_X_SERVICE_KEY=second)
    assert accepted.status_code == 201
    assert duplicate.status_code == 200
    assert duplicate.data["id"] == accepted.data["id"]
    assert duplicate.data["duplicate"] is True
    assert service.events.count() == 1
    event = service.events.get()
    assert "abc" not in event.message and "def" not in event.message and "xyz" not in event.message
    assert service.incidents.count() == 0
    service.refresh_from_db()
    assert first not in service.key_digest and second not in service.key_digest


def test_late_error_attaches_by_occurrence_time(service, incident, check):
    occurred_at = incident.detected_at
    check(True)
    check(True)
    for _ in range(3):
        check(False)
    event, _ = ingest_error(
        service.pk,
        {
            "external_id": uuid.uuid4(),
            "occurred_at": occurred_at,
            "message": "Late log from the first outage",
        },
    )
    assert event.incident_id == incident.pk


def test_future_error_timestamp_is_rejected(client, service):
    key = client.post(f"/api/services/{service.pk}/key/").data["service_key"]
    result = APIClient().post(
        f"/api/services/{service.pk}/events/",
        {
            "external_id": str(uuid.uuid4()),
            "occurred_at": (timezone.now() + timedelta(days=1)).isoformat(),
            "message": "Future log",
        },
        format="json",
        HTTP_X_SERVICE_KEY=key,
    )
    assert result.status_code == 400


def test_only_recovered_incidents_can_be_closed(client, incident, check):
    path = f"/api/incidents/{incident.pk}/"
    assert client.patch(path, {"status": "closed"}).status_code == 400
    assert client.patch(path, {"status": "recovered"}).status_code == 400
    check(True)
    check(True)
    assert client.patch(path, {"status": "closed"}).status_code == 200
    assert client.patch(path, {"status": "open"}).status_code == 400


@pytest.mark.parametrize("query", ["service=invalid", "since=2026-02-30", "status=broken"])
def test_bad_filters_return_validation_errors(client, query):
    assert client.get(f"/api/incidents/?{query}").status_code == 400


def test_service_list_is_paginated(client, owner):
    Service.objects.bulk_create(
        [
            Service(owner=owner, name=f"Service {index}", health_url="http://localhost/health")
            for index in range(30)
        ]
    )
    first = client.get("/api/services/").data
    assert first["count"] == 30
    assert len(first["results"]) == 25
    assert len(client.get("/api/services/?page=2").data["results"]) == 5
