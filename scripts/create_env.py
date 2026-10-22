"""Create a local .env with a random internal key, without replacing existing settings."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    print(".env already exists; its values were preserved.")
else:
    template = (root / ".env.example").read_text(encoding="utf-8")
    target.write_text(template.replace("replace-with-a-random-secret-before-starting", secrets.token_hex(32)), encoding="utf-8")
    print("Created .env with a random internal key. Secret values were not printed.")
