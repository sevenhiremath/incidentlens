import uuid

import pytest

from incidents.logic import save_report, template_report

pytestmark = pytest.mark.django_db


def test_report_uses_real_evidence_without_claiming_ai(incident):
    content, evidence_ids = template_report(incident)
    assert "does not use AI" in content
    assert "Not confirmed" in content
    assert len(evidence_ids) == 3
    for event in incident.events.all():
        assert str(event.pk) in content
    assert "User impact: Not measured" in content


def test_report_revisions_idempotency_and_edit_conflict(client, incident):
    path = f"/api/incidents/{incident.pk}/reports/"
    request_id = str(uuid.uuid4())
    first = client.post(path, {"request_id": request_id, "expected_revision": 0})
    assert first.status_code == 201
    retry = client.post(path, {"request_id": request_id, "expected_revision": 0})
    assert retry.status_code == 200
    assert retry.data["id"] == first.data["id"]
    edited = client.post(
        path,
        {
            "request_id": str(uuid.uuid4()),
            "expected_revision": 1,
            "content": "# Investigation\nThe developer confirmed the fix.",
        },
    )
    assert edited.status_code == 201
    assert edited.data["number"] == 2
    assert edited.data["source"] == "human"
    conflict = client.post(
        path,
        {
            "request_id": str(uuid.uuid4()),
            "expected_revision": 1,
            "content": "Stale edit",
        },
    )
    assert conflict.status_code == 409
    assert incident.reports.count() == 2
    assert incident.reports.get(number=1).content == first.data["content"]
    assert edited.data["evidence_ids"] == first.data["evidence_ids"]


def test_regenerating_draft_keeps_previous_human_edit(incident, owner):
    save_report(
        incident.pk, owner, request_id=uuid.uuid4(), expected_revision=0, content="Manual note"
    )
    new, _ = save_report(incident.pk, owner, request_id=uuid.uuid4(), expected_revision=1)
    assert new.number == 2
    assert incident.reports.get(number=1).content == "Manual note"
