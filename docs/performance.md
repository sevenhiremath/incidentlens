# Performance measurements

I measured the original API and the version with fewer database queries using the same workload. These numbers come from a synthetic PostgreSQL test on one GitHub Actions runner. They are not production traffic measurements.

[Benchmark run and downloadable artifact](https://github.com/sevenhiremath/incidentlens/actions/runs/39010825069) · [Raw request timings and results](benchmarks/2026-10-17-results.json) · [How to rerun it](../benchmarks/README.md)

## Results

Each timing below is the median of three runs. p95 means that 95% of requests in a run completed within that time. The query counts include the user-token lookup.

Individual raw samples are saved to four decimal places in milliseconds. The per-run percentiles were calculated before that rounding, so recomputing them from the saved samples can differ by 0.001 ms.

| Measurement | Original | Updated | Change |
| --- | ---: | ---: | --- |
| Service-list queries per 25-item page | 29 | 3 | 89.7% fewer queries |
| Service-list p95 response time | 144.845 ms | 73.165 ms | 49.5% lower |
| Service-list observed request rate | 60.94/s | 118.56/s | Same eight-client workload |
| Incident-list queries per 25-item page | 28 | 3 | 89.3% fewer queries |
| Incident-list p95 response time | 149.931 ms | 124.209 ms | 17.2% lower |
| Incident-list observed request rate | 57.79/s | 70.77/s | Same eight-client workload |

The updated service-list p95 ranged from 62.788 to 81.302 ms across the three runs. Incident-list p95 ranged from 121.404 to 127.594 ms. I report the median rather than picking the fastest result.

## What changed

The service list used to ask the database whether each service had an open incident. Loading 25 services meant repeating that question 25 times, even though the view had already prefetched incidents. Filtering the related manager made another query.

I replaced that with a database `Exists` annotation, so the service query brings back the open-incident flag along with each service.

The incident list had the same kind of problem when counting linked events. I moved those counts into a `Count` annotation and added an explicit sort order for stable pagination.

Reducing SQL calls by about 90% did not reduce both response times by 90%. Database connections, aggregation, serialization, and waiting behind the two workers still take time. The benchmark measures the whole HTTP request, not just SQL execution.

## Test conditions

- Measured on 17 October 2026, using Python 3.12.3 and a PostgreSQL 17 service container.
- One Linux GitHub runner with four logical CPUs.
- Two Gunicorn workers per checkout, with only one checkout under load at a time.
- Real loopback HTTP requests; no Django test client in the timed load test.
- 100 services, 100 incidents, and 10,000 seeded error events in each isolated database.
- 25 records per list page and eight concurrent HTTP clients.
- 40 warm-up requests followed by 500 measured requests per endpoint, per run.
- Three runs per version: 1,500 measured requests for each read endpoint per version.
- Alternating order: original/updated, updated/original, original/updated.
- Request throttling disabled in the benchmark-only settings. The stale threshold is extended so health status does not change during a run. Normal application settings are unchanged.

Original commit: [`11469ce`](https://github.com/sevenhiremath/incidentlens/tree/11469ce80705ab0fb7284c13e31514615e22837a). Updated commit: [`2a793e6`](https://github.com/sevenhiremath/incidentlens/tree/2a793e6cdd68fb0508605213eeefab0352936fe3).

The benchmark also compares the visible service names, health states, incident statuses, and event counts in the seeded responses. The signatures matched. The query optimization did not improve timing by leaving those fields out.

## Duplicate handling under load

Each run submitted 1,000 unique error IDs twice, shuffled across ten services and sent through eight clients.

For the updated version, all three runs recorded:

- 1,000 HTTP 201 responses for new events.
- 1,000 HTTP 200 responses for recognized duplicates.
- Exactly 1,000 new database rows, verified separately after the HTTP workload.
- No unexpected HTTP responses or extra incidents.

That is **6,000 submissions, including 3,000 duplicate retries, across three runs**. The generated rows were reset between runs, so this is not a claim that 3,000 new rows existed at once. The original version also passed this check; duplicate handling was already implemented.

The updated version's median ingestion rate was 125.24 **submissions** per second with p95 latency of 74.420 ms. Half the submissions were duplicates. This is not a claim of 125 new event inserts per second or the server's maximum capacity.

## Automated tests

The [correctness checks for the measured commit](https://github.com/sevenhiremath/incidentlens/actions/runs/39010824323) passed:

- **52 tests on PostgreSQL**, including simultaneous failures, duplicate ingestion, and conflicting report edits.
- **49 tests on SQLite**, with the three PostgreSQL locking tests explicitly skipped.
- Query-budget tests at 5 and 30 services/incidents. Each list uses two data queries when authentication is bypassed by the fixture; the benchmark's real token authentication adds the third query.
- A separate Docker walkthrough covering failure, recovery, duplicate delivery, and report editing.

The tests also check that users cannot access each other's data, that short failure streaks do not open incidents, and that report revisions are preserved.

## Limits of these numbers

This was one machine and one synthetic dataset, with warm application/database caches. The test does not measure Streamlit rendering, browser performance, internet latency, long-running monitoring, or AI generation. The request rate comes from clients waiting for each response before sending their next request. It is an observed rate for this workload, not a capacity test or an uptime guarantee.
