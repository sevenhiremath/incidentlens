import math
import statistics


def percentile(values, quantile):
    if not values:
        raise ValueError("At least one sample is required.")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def summarize(latencies, seconds, statuses):
    return {
        "requests": len(latencies),
        "wall_seconds": round(seconds, 4),
        "requests_per_second": round(len(latencies) / seconds, 2),
        "p50_ms": round(percentile(latencies, 0.50), 3),
        "p95_ms": round(percentile(latencies, 0.95), 3),
        "status_counts": {str(status): statuses.count(status) for status in sorted(set(statuses))},
    }


def aggregate(runs, workload):
    samples = [run[workload] for run in runs]
    return {
        "median_p50_ms": round(statistics.median(s["p50_ms"] for s in samples), 3),
        "median_p95_ms": round(statistics.median(s["p95_ms"] for s in samples), 3),
        "p95_range_ms": [min(s["p95_ms"] for s in samples), max(s["p95_ms"] for s in samples)],
        "median_requests_per_second": round(
            statistics.median(s["requests_per_second"] for s in samples),
            2,
        ),
        "total_measured_requests": sum(s["requests"] for s in samples),
    }
