import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from incidents.logic import record_check
from incidents.models import Service


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    cache.clear()


@pytest.fixture(autouse=True)
def fast_test_passwords(settings):
    # Keep the real password hasher in the application; speed up isolated tests.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def owner(db):
    return get_user_model().objects.create_user(
        "developer", password="test-only-example-passphrase"
    )


@pytest.fixture
def client(owner):
    api = APIClient()
    api.force_authenticate(user=owner)
    return api


@pytest.fixture
def service(owner):
    return Service.objects.create(
        owner=owner, name="Demo API", health_url="http://localhost:5055/health"
    )


@pytest.fixture
def check(service):
    start = timezone.now() - timedelta(minutes=3)
    index = 0

    def run(healthy, **kwargs):
        nonlocal index
        index += 1
        return record_check(
            service.pk,
            external_id=kwargs.pop("external_id", uuid.uuid4()),
            healthy=healthy,
            latency_ms=10,
            message="HTTP 200" if healthy else "HTTP 503",
            checked_at=kwargs.pop("checked_at", start + timedelta(seconds=index * 10)),
            **kwargs,
        )

    return run


@pytest.fixture
def incident(service, check):
    for _ in range(3):
        check(False)
    return service.incidents.get()
