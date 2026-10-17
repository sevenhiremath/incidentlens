# How the first version works

## Why these choices

I chose Django because I wanted practice with APIs, validation, models, and permissions in one project. Streamlit keeps the interface in Python. The important part for me is being able to follow a request from the dashboard through the API into the database.

SQLite makes the local setup easier. PostgreSQL is the more useful setup for learning what happens when two requests update the same record at the same time.

## Main files

| File | Responsibility |
| --- | --- |
| `incidents/models.py` | Service, Event, Incident, and ReportRevision tables |
| `incidents/logic.py` | Detection, recovery, event linking, and report revisions |
| `incidents/monitor.py` | HTTP checks with timeouts and no redirects |
| `incidents/serializers.py` | Input validation and API output |
| `incidents/views.py` | Authentication, ownership filtering, and API endpoints |
| `ui/app.py` | Streamlit pages and forms |
| `ui/api.py` | HTTP requests from the interface to the backend |

## Incident rules

Each service has counters for consecutive failures and successes. A success resets the failure streak; a failure resets the success streak. Three failures open an incident. Two successes recover it. Repeated failures stay with the open incident. A new outage after recovery creates a new incident.

There are three incident states:

```text
open -> recovered -> closed
```

The monitor owns the first transition. The developer owns the second after reviewing the incident. Service health and incident review status are separate.

Pausing or resuming monitoring clears the detection streak and latest check display. Old events remain in history. An open incident remains open until recovery is actually observed after monitoring resumes.

`started_at` is the first failed check in the streak. `detected_at` is when the third failure arrived. `recovered_at` is when the second successful check began. These are observation times, not exact physical outage boundaries. A monitor timeout or a gap between checks affects what can be inferred.

## Duplicate and concurrent requests

The database requires each `(service, external_id)` pair to be unique. An event sender should retry with the same UUID. Retrying with a new UUID looks like a new event.

Health processing and event ingestion lock the service row inside a short database transaction. On PostgreSQL, another operation on that service waits until the first update finishes. A separate database constraint allows only one open incident per service.

The network request happens before this transaction. A slow HTTP request should not hold a database lock. A check older than the latest recorded check is kept as a service event but cannot change the latest counters. Run only one monitor process in v0.1; row locks protect database updates, not overlapping network checks.

SQLite is useful for the serial local demo. It does not give this code PostgreSQL's row-locking behavior. The threaded concurrency tests deliberately require PostgreSQL.

## Attaching error events

An application error by itself does not open an outage. It is kept as evidence. If it falls within an incident's observed window, it is linked there. If it happened shortly before an incident, the code can attach it using a five-minute look-back window. The same window is used when opening an incident so earlier checks and errors can be included.

An error received late uses its occurrence timestamp. An exact incident window is preferred over the look-back window. This is a simple rule that can be wrong when separate issues happen close together. Linked evidence means nearby in time, not proof of a cause.

## Report revisions

A draft includes actual event IDs and a bounded snapshot of up to 100 recent linked events. The cause stays unconfirmed unless the developer has supplied it. Editing creates a new row instead of overwriting the old report.

Each save includes an `expected_revision`. If someone has already saved a newer revision, the backend returns HTTP 409. Each save also has a request UUID; retrying that request returns the existing revision. The interface does not automatically retry writes yet.

Saving a report locks its incident row, but not the joined service row. This avoids taking those two locks in the opposite order from the monitor.

The snapshot does not change when more logs arrive. Build a new draft to include newer evidence. Editing the Markdown is a human action; the backend does not verify every claim or every manually typed citation.

## Authentication and local safety

- Dashboard users receive a DRF token after login. Streamlit holds it in that user's session.
- The built-in token is shared by a user's logins. Logging out revokes it for the other sessions too. Token expiry and per-device sessions are future work.
- The backend checks ownership on list, detail, edit, and report endpoints. Hiding a widget is not an access check.
- Service keys are random and stored as SHA-256 hashes. Rotating a key invalidates the old one.
- Error messages have length limits and basic masking for common key/value secrets. This is not complete secret detection. Do not send real credentials or personal data.
- The operator sets the health-host allowlist. Redirects, URL credentials, query strings, and fragments are rejected. The allowlist is checked again before a request.
- Only trust hosts you control. DNS rebinding, shared-host path restrictions, and network-level egress controls are not handled here. The default configuration intentionally permits local demo services.
- Basic in-process throttling slows accidental repeated requests; it is not distributed rate limiting or denial-of-service protection.

## Planned AI integration

I want to add AI only after the incident data is reliable. The plan is to send a bounded evidence snapshot and require structured output with event IDs. The backend would validate the output shape and incident ownership of those IDs. It would still need checks for whether the text is actually supported by the evidence.

There is no model API call, AI evaluation, automatic remediation, or root-cause classifier in v0.1.

## Follow-up: list query performance

The service list now uses a database `Exists` annotation to fetch whether a service has an open incident. The incident list uses a `Count` annotation for linked events. This avoids querying once for each row on a page. The incident query has an explicit detection-time and ID order so pagination remains stable after grouping.

Query-budget tests check both small and larger lists. [The performance notes](performance.md) explain the before/after measurements and include the raw request timings.
