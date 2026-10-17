# Describing this version

Use only features you can run and explain. The AI part is still planned, so I would describe the current project as an incident tracking application rather than an AI root-cause system.

## Possible project entry

**IncidentLens — Service Monitoring and Incident Tracking**

Python, Django REST Framework, Streamlit, PostgreSQL, pytest

- Built a Python web app to register services, track failed health checks, and view incident timelines through a Streamlit dashboard.
- Added authenticated APIs, service-specific ingestion keys, duplicate-event handling, and rules for outage detection and recovery.
- Implemented editable incident reports with saved revisions and tests for permissions, recovery rules, and conflicting updates.

## Things to understand before using it in an interview

- Why three failures and two successes were chosen, and what their limitations are.
- How a duplicate event ID prevents repeated inserts.
- Why PostgreSQL row locks matter and why SQLite tests cannot prove the same concurrency behavior.
- Why a recovered service can still have an incident waiting for review.
- Why health checks cannot establish root cause or actual user impact.
- How report revision conflicts avoid overwriting someone else's work.

Avoid claims like “production-ready,” “zero downtime,” “AI-powered diagnosis,” or measured performance improvements unless you implement and verify those separately.
