"""Summarize recorded health checks for use by the dashboard."""


def summarize_checks(events):
    """Return counts and simple statistics from a list of event dictionaries.

    Ignore application errors. Count healthy and failed checks separately.
    Average recorded latencies, including zero but excluding None. Round both
    statistics to two decimal places and use None when there is no denominator.

    Inputs are already validated API event dictionaries. For check events,
    healthy is a boolean and latency_ms is a non-negative number or None.

    Example input:
        [
            {"kind": "check", "healthy": True, "latency_ms": 100},
            {"kind": "check", "healthy": False, "latency_ms": 200},
            {"kind": "error", "healthy": None, "latency_ms": None},
        ]

    Expected output:
        {
            "total_checks": 2,
            "healthy_checks": 1,
            "failed_checks": 1,
            "success_rate_percent": 50.0,
            "average_latency_ms": 150.0,
        }

    This is a check success rate, not time-based uptime. No Django, database,
    network requests, or AI calls are needed. The function is not wired into
    the dashboard yet; that can be the next step once it works.
    """
    total_checks = 0
    healthy_checks = 0
    failed_checks = 0
    total_latency = 0
    latency_count = 0

    for event in events:
        if event["kind"] != "check":
            continue

        total_checks += 1
        if event["healthy"]:
            healthy_checks += 1
        else:
            failed_checks += 1

        # Zero is a valid measurement. None means it was not recorded.
        latency = event["latency_ms"]
        if latency is not None:
            total_latency += latency
            latency_count += 1

    success_rate = None
    if total_checks > 0:
        success_rate = round(healthy_checks / total_checks * 100, 2)

    average_latency = None
    if latency_count > 0:
        average_latency = round(total_latency / latency_count, 2)

    return {
        "total_checks": total_checks,
        "healthy_checks": healthy_checks,
        "failed_checks": failed_checks,
        "success_rate_percent": success_rate,
        "average_latency_ms": average_latency,
    }
