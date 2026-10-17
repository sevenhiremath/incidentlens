"""Create local settings without checking passwords into Git."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
target = root / ".env"
if target.exists():
    raise SystemExit(".env already exists. Keep it, or edit it yourself.")
text = (root / ".env.example").read_text(encoding="utf-8")
for placeholder in [
    "replace-with-a-long-random-local-secret",
    "replace-with-a-local-database-password",
    "replace-with-a-local-demo-control-key",
]:
    text = text.replace(placeholder, secrets.token_urlsafe(40))
target.write_text(text, encoding="utf-8")
print("Created .env with random local secrets. Do not commit this file.")
