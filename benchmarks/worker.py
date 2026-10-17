"""Seed and inspect an isolated benchmark database using either source checkout."""

import argparse
import json
import os
import secrets
import sys
import uuid
from datetime import timedelta
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["seed", "inspect", "reset"])
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    sys.path[:0] = [str(args.source.resolve()), str(HARNESS_ROOT)]
    os.environ["DJANGO_SETTINGS_MODULE"] = "benchmarks.settings"
    import django

    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from django.utils import timezone
    from rest_framework.authtoken.models import Token
    from rest_framework.test import APIClient

    from incidents.models import Event, Incident, Service
    from incidents.security import key_digest

    if args.action == "seed":
        call_command("migrate", verbosity=0)
        owner = get_user_model().objects.create_user("benchmark-user")
        token = Token.objects.create(user=owner)
        key = secrets.token_urlsafe(32)
        now = timezone.now()
        services = Service.objects.bulk_create(
            [
                Service(
                    id=uuid.uuid5(uuid.NAMESPACE_URL, f"incidentlens/benchmark/service/{index}"),
                    owner=owner,
                    name=f"API {index:03d}",
                    environment="benchmark",
                    health_url="http://localhost/health",
                    last_checked_at=now,
                    last_check_ok=index >= 20,
                    key_digest=key_digest(key),
                )
                for index in range(100)
            ]
        )
        incidents = Incident.objects.bulk_create(
            [
                Incident(
                    service=service,
                    started_at=now - timedelta(minutes=2),
                    detected_at=now - timedelta(minutes=1) + timedelta(milliseconds=index),
                    status="open" if index < 20 else "recovered",
                    recovered_at=None if index < 20 else now,
                )
                for index, service in enumerate(services)
            ]
        )
        Event.objects.bulk_create(
            [
                Event(
                    service_id=incident.service_id,
                    incident=incident,
                    external_id=uuid.uuid4(),
                    kind="error",
                    message="Synthetic benchmark evidence.",
                    occurred_at=now - timedelta(seconds=90) + timedelta(milliseconds=index),
                )
                for incident in incidents
                for index in range(100)
            ],
            batch_size=1000,
        )
        print(
            json.dumps(
                {"token": token.key, "service_key": key, "services": [str(s.id) for s in services]}
            )
        )
        return

    if args.action == "reset":
        Event.objects.filter(metadata__release="benchmark-write").delete()
        print(json.dumps({"events": Event.objects.count()}))
        return

    token = Token.objects.get(user__username="benchmark-user")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    query_counts = {}
    payloads = {}
    for endpoint in ["services", "incidents"]:
        client.get(f"/api/{endpoint}/")
        with CaptureQueriesContext(connection) as queries:
            response = client.get(f"/api/{endpoint}/")
        assert response.status_code == 200
        query_counts[endpoint] = len(queries)
        payloads[endpoint] = response.json()
    # A private token is never included in the saved result.
    import incidents.views

    print(
        json.dumps(
            {
                "query_counts_including_token_lookup": query_counts,
                "services": Service.objects.count(),
                "incidents": Incident.objects.count(),
                "events": Event.objects.count(),
                "benchmark_events": Event.objects.filter(
                    metadata__release="benchmark-write"
                ).count(),
                "payloads": payloads,
                "loaded_views": str(Path(incidents.views.__file__).resolve()),
            }
        )
    )


if __name__ == "__main__":
    main()
