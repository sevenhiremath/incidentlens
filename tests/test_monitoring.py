import uuid
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
import requests
from django.utils import timezone

from incidents.models import Event, Incident
from incidents.monitor import check_service
from incidents.serializers import ServiceSerializer

pytestmark = pytest.mark.django_db


def test_threshold_and_recovery(service, check):
    check(False)
    check(False)
    assert not service.incidents.exists()
    check(False)
    incident = service.incidents.get()
    assert incident.events.count() == 3
    assert incident.detected_at > incident.started_at
    check(False)
    assert service.incidents.count() == 1
    check(True)
    incident.refresh_from_db()
    assert incident.status == "open"
    check(True)
    incident.refresh_from_db()
    assert incident.status == "recovered"
    assert incident.recovered_at is not None


def test_failed_recovery_resets_success_streak(incident, check):
    check(True)
    check(False)
    check(True)
    incident.refresh_from_db()
    assert incident.status == "open"
    check(True)
    incident.refresh_from_db()
    assert incident.status == "recovered"


def test_new_outage_after_recovery_is_a_new_incident(incident, service, check):
    check(True)
    check(True)
    for _ in range(3):
        check(False)
    assert service.incidents.count() == 2
    assert service.incidents.filter(status="open").count() == 1


def test_duplicate_check_does_not_advance_failure_count(service, check):
    external_id = uuid.uuid4()
    assert check(False, external_id=external_id)
    assert not check(False, external_id=external_id)
    service.refresh_from_db()
    assert service.consecutive_failures == 1
    assert service.events.count() == 1


def test_late_check_does_not_overwrite_current_health(service, check):
    check(True)
    service.refresh_from_db()
    assert check(False, checked_at=service.last_checked_at - timedelta(minutes=1))
    service.refresh_from_db()
    assert service.last_check_ok is True
    assert service.consecutive_failures == 0
    assert service.events.count() == 2


def test_stale_health_is_not_displayed_as_healthy(service):
    service.last_checked_at = timezone.now() - timedelta(minutes=5)
    service.last_check_ok = True
    assert ServiceSerializer(service).data["health"] == "stale"


def test_paused_service_is_not_checked(service):
    service.enabled = False
    service.save()
    with patch("incidents.monitor.requests.Session") as session:
        assert not check_service(service)
    session.assert_not_called()
    assert not Event.objects.exists()


def test_timeout_is_recorded_without_storing_exception_details(service):
    with patch("incidents.monitor.requests.Session") as session:
        session.return_value.__enter__.return_value.get.side_effect = requests.Timeout(
            "secret text"
        )
        assert check_service(service)
    event = service.events.get()
    assert event.healthy is False
    assert "Timeout" in event.message
    assert "secret text" not in event.message


def test_redirect_is_not_followed(service):
    response = Mock(status_code=302)
    with patch("incidents.monitor.requests.Session") as session:
        client = session.return_value.__enter__.return_value
        client.get.return_value = response
        check_service(service)
        assert client.get.call_args.kwargs["allow_redirects"] is False
    assert service.events.get().healthy is False


def test_monitor_rechecks_allowlist(service, settings):
    settings.MONITOR_ALLOWED_HOSTS = {"different-host"}
    with patch("incidents.monitor.requests.Session") as session:
        check_service(service)
        session.assert_not_called()
    assert not service.events.get().healthy


def test_recovering_health_is_distinct_from_healthy(incident, service):
    service.last_checked_at = timezone.now()
    service.last_check_ok = True
    assert ServiceSerializer(service).data["health"] == "recovering"


def test_one_open_incident_database_constraint(service, incident):
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        Incident.objects.create(
            service=service,
            started_at=timezone.now(),
            detected_at=timezone.now(),
        )
