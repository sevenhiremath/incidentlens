# Performance check

This compares the original list endpoints with the query optimization. It uses real HTTP requests to Gunicorn and PostgreSQL. Streamlit rendering, internet latency, monitoring schedules, and AI are not part of the measurement.

## Workload

- 100 services, 100 incidents, and 10,000 seeded error events per checkout.
- 25 items per list page; eight concurrent HTTP clients and two Gunicorn workers.
- 40 warm-up requests followed by 500 measured requests for each list endpoint.
- 1,000 unique error events, each submitted twice, spread across ten services.
- Three repetitions per checkout, alternating which checkout runs first.
- Both checkouts run on the same runner with separate databases and matching seed data.

The benchmark checks response facts, stored event counts, and HTTP status counts as well as timing. Failed requests fail the benchmark; they are not silently removed from latency samples. Results include raw per-request latencies, p50, p95, observed throughput, query counts, and all run summaries. The headline result is the median of the three per-run results, not the fastest run.

## Run it

The **Performance comparison** GitHub Actions workflow can be started manually. It creates a fresh PostgreSQL service and uploads `results.json`, `summary.md`, and server logs as an artifact. The default baseline is commit `11469ce`, before the optimization.

On a Linux machine with PostgreSQL and the project dependencies:

```text
git worktree add --detach ../incidentlens-baseline 11469ce
uv run python benchmarks/run.py --baseline ../incidentlens-baseline --candidate . --output local-artifacts/performance
```

Set `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, and `POSTGRES_PORT` in the environment first. The database role must be able to create disposable databases. The harness creates databases with unique `il_bench_` names and removes only those databases on exit. Use a local or disposable PostgreSQL instance, never a production database server.

The benchmark settings refuse other database names. They disable request throttling to measure the endpoints and extend the stale threshold so service health does not change halfway through the comparison. Normal application settings are unchanged.

These are synthetic workload results. The request rate is the rate observed with eight waiting clients; it is not a measurement of maximum server capacity. Query counts are collected separately using Django's test client with real token authentication, so query tracing does not add overhead to the timed HTTP requests.
