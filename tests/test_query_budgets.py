import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from incidents.models import Event, Incident, Service

pytestmark = pytest.mark.django_db


def seed_services(owner, size):
    now = timezone.now()
    services = Service.objects.bulk_create(
        [
            Service(
                owner=owner,
                name=f"API {index:03d}",
                health_url="http://localhost/health",
                last_checked_at=now,
                last_check_ok=index != 0,
            )
            for index in range(size)
        ]
    )
    incidents = Incident.objects.bulk_create(
        [
            Incident(
                service=service,
                started_at=now - timedelta(minutes=2),
                detected_at=now,
                status="open" if index == 0 else "recovered",
                recovered_at=None if index == 0 else now,
            )
            for index, service in enumerate(services)
        ]
    )
    Event.objects.bulk_create(
        [
            Event(
                service_id=incident.service_id,
                incident=incident,
                external_id=uuid.uuid4(),
                occurred_at=now,
                kind="error",
                message="Seeded test error",
            )
            for incident in incidents
            for _ in range(3)
        ]
    )


@pytest.mark.parametrize("size", [5, 30])
def test_service_page_uses_two_queries_as_data_grows(client, owner, size):
    seed_services(owner, size)
    # The fixture authenticates directly, so these counts exclude the token lookup.
    with CaptureQueriesContext(connection) as queries:
        response = client.get("/api/services/")
    assert response.status_code == 200
    assert len(queries) == 2
    assert response.data["count"] == size
    assert response.data["results"][0]["health"] == "down"
    assert all(item["health"] == "healthy" for item in response.data["results"][1:])


@pytest.mark.parametrize("size", [5, 30])
def test_incident_counts_do_not_add_a_query_per_row(client, owner, size):
    seed_services(owner, size)
    with CaptureQueriesContext(connection) as queries:
        response = client.get("/api/incidents/")
    assert response.status_code == 200
    assert len(queries) == 2
    assert response.data["count"] == size
    assert all(item["event_count"] == 3 for item in response.data["results"])
