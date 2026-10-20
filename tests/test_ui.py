from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parent.parent / "ui" / "app.py"


def test_login_page_renders_without_api():
    app = AppTest.from_file(APP_PATH).run(timeout=15)
    assert not app.exception
    assert app.title[0].value == "IncidentLens"
    assert [field.label for field in app.text_input] == ["Username", "Password"]


def test_empty_dashboard_handles_a_new_account():
    app = AppTest.from_file(APP_PATH)
    app.session_state["token"] = "ui-test-only-token"
    app.session_state["username"] = "developer"
    with patch("ui.api.page", return_value={"count": 0, "results": []}):
        app.run(timeout=15)
    assert not app.exception
    assert "Service overview" in [title.value for title in app.title]
    assert any("Register a service" in message.value for message in app.info)


@pytest.mark.parametrize(
    ("summary", "expected_rate", "expected_latency"),
    [
        (
            {
                "sample_limit": 100,
                "total_checks": 4,
                "failed_checks": 1,
                "success_rate_percent": 75.0,
                "average_latency_ms": 0.0,
            },
            "75.00%",
            "0.00 ms",
        ),
        (
            {
                "sample_limit": 100,
                "total_checks": 0,
                "failed_checks": 0,
                "success_rate_percent": None,
                "average_latency_ms": None,
            },
            "—",
            "—",
        ),
    ],
    ids=["recorded-checks-with-zero-latency", "no-checks-yet"],
)
def test_dashboard_displays_service_summary(summary, expected_rate, expected_latency):
    app = AppTest.from_file(APP_PATH)
    app.session_state["token"] = "ui-test-only-token"
    app.session_state["username"] = "developer"
    service = {
        "id": "b4f7c925-837e-408c-b2c6-515a685fe5a7",
        "name": "Demo API",
        "environment": "test",
        "health": "unknown",
        "last_checked_at": None,
        "last_latency_ms": None,
    }

    def fake_page(path, token, params=None):
        if path == "services/":
            return {"count": 1, "results": [service]}
        return {"count": 0, "results": []}

    with (
        patch("ui.api.page", side_effect=fake_page),
        patch("ui.api.call", return_value=summary) as api,
    ):
        app.run(timeout=15)
    assert not app.exception
    api.assert_called_once_with(
        "GET",
        f"services/{service['id']}/summary/",
        token="ui-test-only-token",
    )
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Check success rate"] == expected_rate
    assert metrics["Failed checks"] == str(summary["failed_checks"])
    assert metrics["Average response"] == expected_latency
