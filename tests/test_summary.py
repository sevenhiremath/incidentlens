import pytest

from incidents.summary import summarize_checks


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        ([], (0, 0, 0, None, None)),
        ([{"kind": "error", "latency_ms": 999}], (0, 0, 0, None, None)),
        (
            [
                {"kind": "check", "healthy": True, "latency_ms": 100},
                {"kind": "check", "healthy": False, "latency_ms": 200},
                {"kind": "error", "latency_ms": 999},
            ],
            (2, 1, 1, 50.0, 150.0),
        ),
        (
            [
                {"kind": "check", "healthy": True, "latency_ms": 0},
                {"kind": "check", "healthy": True, "latency_ms": None},
                {"kind": "check", "healthy": False, "latency_ms": 100},
            ],
            (3, 2, 1, 66.67, 50.0),
        ),
        (
            [
                {"kind": "check", "healthy": True, "latency_ms": None},
                {"kind": "check", "healthy": False, "latency_ms": None},
            ],
            (2, 1, 1, 50.0, None),
        ),
        (
            [
                {"kind": "check", "healthy": False, "latency_ms": 10},
                {"kind": "check", "healthy": False, "latency_ms": 20},
                {"kind": "check", "healthy": False, "latency_ms": 20},
            ],
            (3, 0, 3, 0.0, 16.67),
        ),
        ([{"kind": "check", "healthy": True, "latency_ms": 0}], (1, 1, 0, 100.0, 0.0)),
    ],
    ids=[
        "empty",
        "errors-only",
        "mixed",
        "zero-and-missing",
        "no-latencies",
        "all-failed",
        "healthy-zero",
    ],
)
def test_health_check_summary(events, expected):
    assert summarize_checks(events) == dict(
        zip(
            [
                "total_checks",
                "healthy_checks",
                "failed_checks",
                "success_rate_percent",
                "average_latency_ms",
            ],
            expected,
            strict=True,
        )
    )
