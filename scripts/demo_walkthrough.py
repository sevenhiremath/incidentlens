"""Exercise the real API and Flask demo. Both servers must already be running."""

import argparse
import getpass
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
API = os.getenv("INCIDENTLENS_API_URL", "http://127.0.0.1:8000/api").rstrip("/")
DEMO = os.getenv("DEMO_BASE_URL", "http://127.0.0.1:5055").rstrip("/")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-account", action="store_true")
    parser.add_argument(
        "--docker", action="store_true", help="Run checks inside the Compose backend."
    )
    args = parser.parse_args()
    account = {}
    if args.review_account:
        account = json.loads((ROOT / "local-artifacts" / "review-account.json").read_text())
    username = (
        account.get("username")
        or os.getenv("WALKTHROUGH_USERNAME")
        or input("Dashboard username: ")
    )
    password = (
        account.get("password")
        or os.getenv("WALKTHROUGH_PASSWORD")
        or getpass.getpass("Dashboard password: ")
    )
    control_key = os.environ["DEMO_CONTROL_KEY"]
    session = requests.Session()

    def call(method, path, **kwargs):
        result = session.request(method, f"{API}/{path}", timeout=10, **kwargs)
        result.raise_for_status()
        return result.json()

    auth = call("POST", "auth/login/", json={"username": username, "password": password})
    session.headers["Authorization"] = f"Token {auth['token']}"
    service = call(
        "POST",
        "services/",
        json={
            "name": f"Demo API {uuid.uuid4().hex[:6]}",
            "environment": "walkthrough",
            "health_url": "http://demo:5055/health" if args.docker else f"{DEMO}/health",
        },
    )
    service_id = service["id"]
    key = call("POST", f"services/{service_id}/key/")["service_key"]

    def control(mode):
        response = requests.post(
            f"{DEMO}/control",
            headers={"X-Demo-Key": control_key},
            json={"mode": mode},
            timeout=5,
        )
        response.raise_for_status()

    def check_once():
        command = [sys.executable, "manage.py", "monitor", "--once"]
        if args.docker:
            command = ["docker", "compose", "run", "--rm", "backend", "python", *command[1:]]
        subprocess.run(command, cwd=ROOT, check=True)

    try:
        control("down")
        for _ in range(3):
            check_once()
        incidents = call("GET", "incidents/", params={"service": service_id})["results"]
        assert len(incidents) == 1 and incidents[0]["status"] == "open"
        incident_id = incidents[0]["id"]
        payload = {
            "external_id": str(uuid.uuid4()),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "message": "Demo was intentionally switched to HTTP 503 for this walkthrough.",
            "metadata": {"exception_type": "SimulatedFailure", "path": "/health"},
        }
        for expected_status in [201, 200]:
            response = requests.post(
                f"{API}/services/{service_id}/events/",
                headers={"X-Service-Key": key},
                json=payload,
                timeout=5,
            )
            assert response.status_code == expected_status
        control("healthy")
        check_once()
        check_once()
        incident = call("GET", f"incidents/{incident_id}/")
        assert incident["status"] == "recovered"
        assert incident["event_count"] == 6
        call(
            "PATCH",
            f"incidents/{incident_id}/",
            json={
                "confirmed_cause": "The walkthrough intentionally set the demo to down mode.",
                "resolution": "Restored healthy mode; two successful checks confirmed recovery.",
            },
        )
        first = call(
            "POST",
            f"incidents/{incident_id}/reports/",
            json={
                "request_id": str(uuid.uuid4()),
                "expected_revision": 0,
            },
        )
        second = call(
            "POST",
            f"incidents/{incident_id}/reports/",
            json={
                "request_id": str(uuid.uuid4()),
                "expected_revision": 1,
                "content": first["content"]
                + "\n\nDeveloper review: this was a controlled demo outage.\n",
            },
        )
        assert second["number"] == 2
        report_path = ROOT / "local-artifacts" / "demo-report.md"
        report_path.parent.mkdir(exist_ok=True)
        report_path.write_text(second["content"], encoding="utf-8")
        summary = {
            "service_id": service_id,
            "incident_id": incident_id,
            "status": incident["status"],
            "linked_events": incident["event_count"],
            "duplicate_event_stored_once": True,
            "report_revisions": second["number"],
            "report_mode": "template",
        }
        (ROOT / "local-artifacts" / "walkthrough.json").write_text(
            json.dumps(summary, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2))
    finally:
        control("healthy")
        session.close()


if __name__ == "__main__":
    main()
