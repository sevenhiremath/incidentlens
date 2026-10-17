from pathlib import Path
from unittest.mock import patch

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
