"""Create a throwaway local account for an automated walkthrough."""

import json
import os
import secrets
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402

account = {"username": f"review-{uuid.uuid4().hex[:6]}", "password": secrets.token_urlsafe(24)}
get_user_model().objects.create_user(**account)
target = ROOT / "local-artifacts" / "review-account.json"
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(account), encoding="utf-8")
print(
    "Created a throwaway review account. "
    "Credentials are in ignored local-artifacts/review-account.json."
)
