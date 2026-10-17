import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4096
mode = "healthy"
mode_lock = threading.Lock()


@app.get("/health")
def health():
    with mode_lock:
        current = mode
    if current == "slow":
        time.sleep(6)
    if current == "down":
        return jsonify(status="error"), 503
    return jsonify(status="ok")


@app.post("/control")
def control():
    global mode
    expected = os.getenv("DEMO_CONTROL_KEY", "")
    supplied = request.headers.get("X-Demo-Key", "")
    if not expected or not secrets.compare_digest(expected, supplied):
        return jsonify(detail="Invalid demo control key."), 401
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(detail="Send a JSON object."), 400
    selected = data.get("mode")
    if selected not in {"healthy", "down", "slow"}:
        return jsonify(detail="Use healthy, down, or slow."), 400
    with mode_lock:
        mode = selected
    return jsonify(mode=mode)


@app.get("/work")
def work():
    with mode_lock:
        current = mode
    if current == "healthy":
        return jsonify(message="The demo request completed.")
    # Sending a log must not decide whether the application's own request succeeds.
    api = os.getenv("INCIDENTLENS_API_URL", "http://127.0.0.1:8000/api").rstrip("/")
    service_id = os.getenv("DEMO_SERVICE_ID", "")
    service_key = os.getenv("DEMO_SERVICE_KEY", "")
    if service_id and service_key:
        try:
            requests.post(
                f"{api}/services/{service_id}/events/",
                headers={"X-Service-Key": service_key},
                timeout=1,
                json={
                    "external_id": str(uuid.uuid4()),
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "message": "Demo dependency unavailable. This is a simulated error.",
                    "metadata": {"exception_type": "DemoDependencyError", "path": "/work"},
                },
            )
        except requests.RequestException:
            app.logger.warning("Could not send the demo error event.")
    return jsonify(message="Simulated dependency failure."), 503


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5055, threaded=True)
