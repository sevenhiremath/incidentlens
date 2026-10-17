"""Benchmark-only settings. Never use this module to host a real application."""

from config.settings import *  # noqa: F403

if DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":  # noqa: F405
    raise RuntimeError("Benchmarks require their own PostgreSQL database.")
if not DATABASES["default"]["NAME"].startswith("il_bench_"):  # noqa: F405
    raise RuntimeError("Refusing to benchmark a database outside the il_bench_ prefix.")

DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
MONITOR_STALE_SECONDS = 3600
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}  # noqa: F405
