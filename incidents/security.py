import hashlib
import re
import secrets
from urllib.parse import urlsplit

from django.conf import settings
from rest_framework.exceptions import ValidationError


def validate_health_url(value):
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValidationError("Enter a valid health URL.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.hostname.lower() not in settings.MONITOR_ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
        or port == 0
    ):
        raise ValidationError(
            "Use an allowed HTTP(S) host without credentials, query, or fragment."
        )
    return value


def key_digest(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def new_service_key():
    raw = "il_" + secrets.token_urlsafe(32)
    return raw, key_digest(raw)


def redact(message):
    # This handles common examples, not every possible secret format.
    message = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", message)
    return re.sub(
        r"(?i)\b(password|token|api[_-]?key|secret)\s*[:=]\s*[^\s,;]+",
        r"\1=[redacted]",
        message,
    )[:2000]
