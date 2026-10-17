import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import close_old_connections, connection, connections
from django.utils import timezone

from incidents.logic import RevisionConflict, ingest_error, record_check, save_report
from incidents.models import Service

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(connection.vendor != "postgresql", reason="Requires PostgreSQL row locks"),
]


def run_together(fn):
    barrier = Barrier(2)

    def worker(index):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return fn(index)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(worker, range(2)))


def test_concurrent_failures_open_one_incident(service):
    Service.objects.filter(pk=service.pk).update(
        consecutive_failures=2,
        first_failure_at=timezone.now() - timedelta(minutes=1),
    )

    def fail(index):
        return record_check(
            service.pk,
            external_id=uuid.uuid4(),
            healthy=False,
            latency_ms=5,
            message="HTTP 503",
            checked_at=timezone.now(),
        )

    run_together(fail)
    assert service.incidents.filter(status="open").count() == 1
    assert service.events.count() == 2


def test_concurrent_duplicate_errors_are_stored_once(service):
    payload = {"external_id": uuid.uuid4(), "occurred_at": timezone.now(), "message": "One error"}
    results = run_together(lambda _: ingest_error(service.pk, payload)[1])
    assert sorted(results) == [False, True]
    assert service.events.count() == 1


def test_concurrent_report_edits_preserve_the_winner(incident, owner):
    save_report(incident.pk, owner, request_id=uuid.uuid4(), expected_revision=0)

    def edit(index):
        try:
            save_report(
                incident.pk,
                owner,
                request_id=uuid.uuid4(),
                expected_revision=1,
                content=f"Editor {index}",
            )
            return "saved"
        except RevisionConflict:
            return "conflict"

    assert sorted(run_together(edit)) == ["conflict", "saved"]
    assert incident.reports.count() == 2
