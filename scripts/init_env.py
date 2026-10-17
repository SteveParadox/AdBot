"""Create local configuration without overwriting an existing file."""
import secrets
import base64
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    raise SystemExit(".env already exists; kept unchanged")
example = (root / ".env.example").read_text()
example = example.replace("ADBOT_API_KEYS=\n", "ADBOT_API_KEYS=" + secrets.token_urlsafe(36) + "\n")
example = example.replace("ADBOT_POSTGRES_PASSWORD=\n", "ADBOT_POSTGRES_PASSWORD=" + secrets.token_urlsafe(32) + "\n")
example = example.replace("ADBOT_SESSION_ENCRYPTION_KEY=\n", "ADBOT_SESSION_ENCRYPTION_KEY=" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode() + "\n")
with target.open("x", encoding="utf-8") as file:
    file.write(example)
try:
    target.chmod(0o600)
except OSError:
    pass
print("Created .env. Read ADBOT_API_KEYS there to connect your dashboard.")
