"""Compare two checkouts over real loopback HTTP using disposable PostgreSQL databases."""

import argparse
import hashlib
import json
import os
import platform
import random
import secrets
import socket
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import requests
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmarks.stats import aggregate, summarize  # noqa: E402


def worker(source, env, action):
    result = subprocess.run(
        [sys.executable, str(ROOT / "benchmarks" / "worker.py"), action, "--source", str(source)],
        cwd=source,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def commit_at(source):
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()


def http_workload(base, jobs, *, headers, concurrency):
    local = threading.local()

    def perform(job):
        if not hasattr(local, "session"):
            local.session = requests.Session()
            local.session.trust_env = False
            local.session.headers.update(headers)
        method, endpoint, payload = job
        start = time.perf_counter()
        response = local.session.request(method, base + endpoint, json=payload, timeout=30)
        milliseconds = (time.perf_counter() - start) * 1000
        if response.status_code not in {200, 201}:
            raise RuntimeError(f"Unexpected HTTP {response.status_code} for {endpoint}")
        return milliseconds, response.status_code

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        values = list(pool.map(perform, jobs))
    wall = time.perf_counter() - started
    result = summarize([item[0] for item in values], wall, [item[1] for item in values])
    result["raw_latencies_ms"] = [round(item[0], 4) for item in values]
    return result


def free_port():
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return handle.getsockname()[1]


def wait_ready(base, process):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Benchmark server stopped. Inspect the saved server log.")
        try:
            if requests.get(base + "/api/health/", timeout=1).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.2)
    raise RuntimeError("Benchmark server did not become ready.")


def payload_signature(payloads):
    # IDs/times differ between seeded databases. Compare the user-visible facts.
    services = [
        (item["name"], item["environment"], item["health"])
        for item in payloads["services"]["results"]
    ]
    incidents = [
        (item["service_name"], item["status"], item["event_count"])
        for item in payloads["incidents"]["results"]
    ]
    canonical = json.dumps({"services": services, "incidents": incidents}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def prepare_variant(label, source, run_id, output, connection_args):
    database = f"il_bench_{run_id}_{label}"
    with psycopg.connect(**connection_args, dbname="postgres", autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    env = {
        **os.environ,
        "DATABASE_ENGINE": "postgres",
        "POSTGRES_DB": database,
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(40),
        "DJANGO_SETTINGS_MODULE": "benchmarks.settings",
        "PYTHONPATH": os.pathsep.join([str(source), str(ROOT)]),
    }
    variant = {"database": database, "env": env, "source": source, "process": None, "log": None}
    try:
        credentials = worker(source, env, "seed")
        initial = worker(source, env, "inspect")
        assert Path(initial["loaded_views"]).is_relative_to(source)
        variant.update(
            {
                "credentials": credentials,
                "initial": initial,
                "commit": commit_at(source),
                "runs": [],
                "base": f"http://127.0.0.1:{free_port()}",
            }
        )
        variant["log"] = (output / f"{label}-server.log").open("w", encoding="utf-8")
        variant["process"] = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "gunicorn",
                "config.wsgi:application",
                "--bind",
                variant["base"].removeprefix("http://"),
                "--workers",
                "2",
                "--timeout",
                "60",
            ],
            cwd=source,
            env=env,
            stdout=variant["log"],
            stderr=subprocess.STDOUT,
        )
        wait_ready(variant["base"], variant["process"])
        return variant
    except BaseException:
        cleanup_variant(variant, connection_args)
        raise


def cleanup_variant(variant, connection_args):
    process = variant.get("process")
    if process is not None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if variant.get("log"):
        variant["log"].close()
    database = variant["database"]
    if not database.startswith("il_bench_"):
        raise RuntimeError("Refusing to clean a database outside the benchmark prefix.")
    with psycopg.connect(**connection_args, dbname="postgres", autocommit=True) as admin:
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", [database]
        )
        admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def measure_variant(variant, args):
    source, env, base = variant["source"], variant["env"], variant["base"]
    assert worker(source, env, "reset")["events"] == 10000
    credentials = variant["credentials"]
    headers = {"Authorization": f"Token {credentials['token']}"}
    record = {}
    for endpoint in ["services", "incidents"]:
        http_workload(
            base,
            [("GET", f"/api/{endpoint}/", None)] * args.warmup,
            headers=headers,
            concurrency=args.clients,
        )
        record[endpoint] = http_workload(
            base,
            [("GET", f"/api/{endpoint}/", None)] * args.read_requests,
            headers=headers,
            concurrency=args.clients,
        )

    writes = []
    stamp = datetime.now(timezone.utc).isoformat()
    for index in range(args.unique_events):
        payload = {
            "external_id": str(uuid.uuid4()),
            "occurred_at": stamp,
            "message": "Synthetic load-test error.",
            "metadata": {"release": "benchmark-write"},
        }
        endpoint = f"/api/services/{credentials['services'][index % 10]}/events/"
        writes.extend([("POST", endpoint, payload)] * 2)
    random.Random(20261017).shuffle(writes)
    record["ingestion"] = http_workload(
        base,
        writes,
        headers={"X-Service-Key": credentials["service_key"]},
        concurrency=args.clients,
    )
    assert record["ingestion"]["status_counts"] == {
        "200": args.unique_events,
        "201": args.unique_events,
    }
    final = worker(source, env, "inspect")
    assert final["events"] == 10000 + args.unique_events
    assert final["benchmark_events"] == args.unique_events
    assert final["incidents"] == 100
    record["verified_unique_events"] = final["benchmark_events"]
    variant["runs"].append(record)


def write_results(variants, args, output, started_at):
    result = {
        "started_at_utc": started_at,
        "environment": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
            "gunicorn_workers_per_variant": 2,
            "database": "PostgreSQL 17 service container",
            "transport": "loopback HTTP",
            "ci_run_url": os.getenv("BENCHMARK_RUN_URL"),
        },
        "workload": {
            "services": 100,
            "incidents": 100,
            "seeded_events": 10000,
            "page_size": 25,
            "concurrent_clients": args.clients,
            "repetitions": args.repeats,
            "read_requests_per_endpoint_per_run": args.read_requests,
            "warmup_per_endpoint_per_run": args.warmup,
            "unique_error_events_per_run": args.unique_events,
            "error_submissions_per_run": args.unique_events * 2,
            "load_model": "closed-loop; each client sends its next request after completion",
            "aggregation": "median of per-run metrics; nearest-rank p95",
            "profile_changes": "throttling disabled; stale threshold 3600s; DEBUG=false",
            "run_order": "baseline/candidate, candidate/baseline, alternating thereafter",
        },
        "variants": {},
    }
    signatures = []
    for label, variant in variants.items():
        signature = payload_signature(variant["initial"]["payloads"])
        signatures.append(signature)
        result["variants"][label] = {
            "commit": variant["commit"],
            "payload_signature": signature,
            "queries_per_page_including_token_lookup": variant["initial"][
                "query_counts_including_token_lookup"
            ],
            "runs": variant["runs"],
            "aggregate": {
                name: aggregate(variant["runs"], name)
                for name in ["services", "incidents", "ingestion"]
            },
        }
    assert len(set(signatures)) == 1, "Optimized API changed the seeded response facts."
    (output / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = [
        "# IncidentLens benchmark",
        "",
        "Measured over loopback HTTP on one CI runner.",
        "",
        "| Endpoint | Baseline p95 (ms) | Candidate p95 (ms) | Change | Queries before → after |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for endpoint in ["services", "incidents"]:
        before = result["variants"]["baseline"]["aggregate"][endpoint]["median_p95_ms"]
        after = result["variants"]["candidate"]["aggregate"][endpoint]["median_p95_ms"]
        change = (before - after) / before * 100
        queries = [
            result["variants"][v]["queries_per_page_including_token_lookup"][endpoint]
            for v in ["baseline", "candidate"]
        ]
        lines.append(
            f"| {endpoint} | {before:.3f} | {after:.3f} | {change:.1f}% lower | "
            f"{queries[0]} → {queries[1]} |"
        )
    lines.extend(
        [
            "",
            "Use results.json for every run, throughput, status counts, and test conditions.",
            "These are synthetic workload measurements, not production capacity or an uptime SLA.",
        ]
    )
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--clients", type=int, default=8)
    parser.add_argument("--read-requests", type=int, default=500)
    parser.add_argument("--warmup", type=int, default=40)
    parser.add_argument("--unique-events", type=int, default=1000)
    args = parser.parse_args()
    if min(args.repeats, args.clients, args.read_requests, args.warmup, args.unique_events) < 1:
        parser.error("Workload values must be positive.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    connection_args = {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": os.getenv("POSTGRES_PORT", "5432"),
        "user": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
    }
    variants = {}
    run_id = uuid.uuid4().hex[:8]
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        for label, source in [("baseline", args.baseline), ("candidate", args.candidate)]:
            variants[label] = prepare_variant(
                label, source.resolve(), run_id, output, connection_args
            )
        for repetition in range(args.repeats):
            order = ["baseline", "candidate"] if repetition % 2 == 0 else ["candidate", "baseline"]
            for label in order:
                print(f"Measuring {label}, repetition {repetition + 1}/{args.repeats}.", flush=True)
                measure_variant(variants[label], args)
        write_results(variants, args, output, started_at)
    finally:
        for variant in variants.values():
            cleanup_variant(variant, connection_args)


if __name__ == "__main__":
    main()
