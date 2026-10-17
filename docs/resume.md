# Describing this version

Use only features you can run and explain. The AI part is still planned, so I would describe the current project as an incident tracking application rather than an AI root-cause system.

## Possible project entry

**IncidentLens — Service Monitoring and Incident Tracking**

Python, Django REST Framework, Streamlit, PostgreSQL, pytest

- Built a Django REST API and Streamlit dashboard for service monitoring, incident timelines, and report revisions; tested with 100 services and 10,000 seeded events.
- Reduced service-list queries from 29 to 3 and p95 response time from 144.8 ms to 73.2 ms in an eight-client PostgreSQL load test, a 49.5% reduction using the median of three runs.
- Verified 6,000 error submissions, including 3,000 duplicate retries across three runs, without duplicate rows; added 52 automated tests covering permissions, recovery, concurrent updates, and query counts.

The measurements and their limits are in [the performance notes](performance.md). The 10,000 events are synthetic test data, not real users. AI generation is still planned.

## Things to understand before using it in an interview

- Why three failures and two successes were chosen, and what their limitations are.
- How a duplicate event ID prevents repeated inserts.
- Why PostgreSQL row locks matter and why SQLite tests cannot prove the same concurrency behavior.
- Why a recovered service can still have an incident waiting for review.
- Why health checks cannot establish root cause or actual user impact.
- How report revision conflicts avoid overwriting someone else's work.
- What p95 means, why the benchmark uses three runs, and why the request rate is not a maximum-capacity claim.
- How `Exists` and `Count` avoid one extra database request for each displayed row.

Avoid claims like “production-ready,” “zero downtime,” “AI-powered diagnosis,” or measured performance improvements unless you implement and verify those separately.
