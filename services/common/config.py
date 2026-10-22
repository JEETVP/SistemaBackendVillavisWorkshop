"""Environment configuration shared by the local services and the launcher."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=False)


def app_origin() -> str:
    value = os.getenv("APP_ORIGIN", "http://localhost:5173").rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
        raise RuntimeError("APP_ORIGIN must be an HTTP(S) origin without a path")
    if os.getenv("APP_ENV", "development") == "production" and parsed.scheme != "https":
        raise RuntimeError("APP_ORIGIN must use HTTPS in production")
    return value
