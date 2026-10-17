import time
import uuid

import requests
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .logic import record_check
from .models import Service
from .security import validate_health_url


def check_service(service):
    if not service.enabled:
        return False
    started = time.monotonic()
    checked_at = timezone.now()
    try:
        validate_health_url(service.health_url)
        with requests.Session() as client:
            # Do not forward local checks through a machine's proxy settings.
            client.trust_env = False
            response = client.get(
                service.health_url,
                timeout=5,
                allow_redirects=False,
                stream=True,
            )
            try:
                healthy = response.status_code == 200
                message = f"Health endpoint returned HTTP {response.status_code}."
            finally:
                response.close()
    except ValidationError:
        healthy, message = False, "Health URL is outside the monitor allowlist."
    except requests.RequestException as exc:
        healthy, message = False, f"Health request failed: {type(exc).__name__}."
    latency = round((time.monotonic() - started) * 1000)
    # The request happens before the short database transaction in record_check.
    return record_check(
        service.pk,
        external_id=uuid.uuid4(),
        healthy=healthy,
        latency_ms=latency,
        message=message,
        checked_at=checked_at,
    )


def check_all():
    count = 0
    for service in Service.objects.filter(enabled=True).iterator():
        count += bool(check_service(service))
    return count
