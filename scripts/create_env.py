"""Create/complete PostgreSQL development settings without replacing existing secrets."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
template = (root / ".env.example").read_text(encoding="utf-8")
for marker in ("replace-with-a-random-secret-before-starting", "replace-postgres-admin-password", "replace-identity-db-password", "replace-customers-db-password", "replace-workshop-db-password"):
    template = template.replace(marker, secrets.token_hex(32))
if not target.exists():
    target.write_text(template, encoding="utf-8")
    print("Created PostgreSQL settings. No secrets were printed.")
else:
    original = target.read_text(encoding="utf-8")
    existing = {line.split("=", 1)[0] for line in original.splitlines() if "=" in line and not line.startswith("#")}
    new_settings = [line for line in template.splitlines() if "=" in line and not line.startswith("#") and line.split("=", 1)[0] not in existing]
    if new_settings:
        target.write_text(original.rstrip() + "\n\n# PostgreSQL settings; existing values preserved.\n" + "\n".join(new_settings) + "\n", encoding="utf-8")
    print("Existing settings preserved; missing PostgreSQL settings added. SQLite data was not imported.")
