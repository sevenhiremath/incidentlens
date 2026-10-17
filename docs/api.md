# API examples

All dashboard endpoints need `Authorization: Token <user-token>`, except login and `/api/health/`. Error ingestion uses `X-Service-Key` instead. List responses contain `count`, `next`, `previous`, and `results`; the default page size is 25.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/auth/login/` | Get a user token |
| POST | `/api/auth/logout/` | Revoke that token |
| GET, POST | `/api/services/` | List or register services |
| GET, PATCH | `/api/services/{id}/` | Read or update settings |
| POST | `/api/services/{id}/key/` | Create or rotate an ingestion key |
| POST | `/api/services/{id}/events/` | Send an application error |
| GET | `/api/services/{id}/history/` | Recent service events, newest first |
| GET | `/api/incidents/` | List and filter incidents |
| GET, PATCH | `/api/incidents/{id}/` | View or update investigation notes |
| GET | `/api/incidents/{id}/events/` | Timeline, oldest first |
| GET, POST | `/api/incidents/{id}/reports/` | Read or create report revisions |

The examples below use Python `requests`. Replace the example values with your local account. Do not paste real tokens into committed files.

```python
import getpass
import requests

api = "http://127.0.0.1:8000/api"
response = requests.post(
    f"{api}/auth/login/",
    json={"username": input("Username: "), "password": getpass.getpass()},
    timeout=5,
)
response.raise_for_status()
headers = {"Authorization": f"Token {response.json()['token']}"}

response = requests.post(
    f"{api}/services/",
    headers=headers,
    json={
        "name": "Demo API",
        "environment": "development",
        "health_url": "http://127.0.0.1:5055/health",
    },
    timeout=5,
)
response.raise_for_status()
service_id = response.json()["id"]
```

The health endpoint cannot be changed after registration, because existing incident history belongs to that endpoint. Register a new service for a different endpoint. Other editable service fields are `name`, `environment`, and `enabled`.

## Send an application error

Create a service key with the key endpoint or the Services page. The API returns the raw key only when creating it; service responses never include the stored hash.

```python
import uuid
from datetime import datetime, timezone

response = requests.post(f"{api}/services/{service_id}/key/", headers=headers, timeout=5)
response.raise_for_status()
service_key = response.json()["service_key"]

payload = {
    "external_id": str(uuid.uuid4()),
    "occurred_at": datetime.now(timezone.utc).isoformat(),
    "message": "Could not connect to the demo dependency.",
    "metadata": {"exception_type": "ConnectionError", "path": "/work"},
}
response = requests.post(
    f"{api}/services/{service_id}/events/",
    headers={"X-Service-Key": service_key},
    json=payload,
    timeout=5,
)
response.raise_for_status()
```

Reusing the same payload returns HTTP 200 with `duplicate: true`. The first insert returns HTTP 201. Retries must preserve `external_id`. Accepted metadata keys are `exception_type`, `path`, and `release`, with string values of at most 300 characters. Messages are limited to 2,000 characters. Occurrence timestamps must be within the last seven days and no more than 30 seconds in the future.

## Filter incidents

`GET /api/incidents/?status=recovered&search=demo&page=1`

Other filters: `service=<UUID>`, `since=YYYY-MM-DD`, and `until=YYYY-MM-DD`. Dates refer to detection time in UTC. Invalid filters return HTTP 400.

## Save a report

```json
{
  "request_id": "0773f75a-6ba8-45c4-b7ea-72c494165fa2",
  "expected_revision": 0
}
```

Post this to the incident's reports endpoint to build the first template draft. To save an edit, send a new request ID, `expected_revision: 1`, and a `content` string. Report content is limited to 30,000 characters. A revision conflict returns HTTP 409. A duplicate request ID returns its previously created revision instead of creating another one.

Investigation fields are `confirmed_cause` and `resolution`. The only user-driven status transition is `recovered` to `closed`; health processing controls recovery.
