import hmac
import os

from fastapi import Header, HTTPException


def require_service_token(x_service_token: str | None = Header(default=None)) -> None:
    expected = os.getenv("INTERNAL_SERVICE_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Internal service authentication is not configured")
    if not x_service_token or not hmac.compare_digest(x_service_token, expected):
        raise HTTPException(403, "Internal service access denied")
