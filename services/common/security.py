from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

TOKEN_ISSUER = "villavis-identity"
TOKEN_AUDIENCE = "villavis-api"
TOKEN_TTL_SECONDS = 3600
PRIVATE_KEY_PATH = os.getenv("IDENTITY_PRIVATE_KEY_PATH", "data/jwt_private.pem")


def ensure_private_key(path: str = PRIVATE_KEY_PATH) -> bytes:
    key_path = Path(path)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        key_path.write_bytes(pem)
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
    return key_path.read_bytes()


def get_public_key_pem() -> bytes:
    private_key = serialization.load_pem_private_key(ensure_private_key(), password=None)
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _b64url_encode(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    import base64

    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_token(user: dict) -> str:
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "sub": user["id"],
        "role": user["role"],
        "phone": user.get("phone"),
        "customer_id": user.get("customer_id"),
        "primary_vehicle_id": user.get("primary_vehicle_id"),
        "iss": TOKEN_ISSUER,
        "aud": TOKEN_AUDIENCE,
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
        "jti": secrets.token_urlsafe(16),
    }
    signing_input = (
        f"{_b64url_encode(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64url_encode(json.dumps(claims, separators=(',', ':')).encode())}"
    )
    private_key = serialization.load_pem_private_key(ensure_private_key(), password=None)
    signature = private_key.sign(
        signing_input.encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return f"{signing_input}.{_b64url_encode(signature)}"


def verify_token(token: str, public_key_pem: str | bytes) -> dict:
    try:
        encoded_header, encoded_claims, encoded_signature = token.split(".")
        header = json.loads(_b64url_decode(encoded_header))
        claims = json.loads(_b64url_decode(encoded_claims))
        if header.get("alg") != "RS256" or header.get("typ") != "JWT":
            raise ValueError("Unsupported JWT algorithm")
        key_bytes = public_key_pem.encode() if isinstance(public_key_pem, str) else public_key_pem
        public_key = serialization.load_pem_public_key(key_bytes)
        public_key.verify(
            _b64url_decode(encoded_signature),
            f"{encoded_header}.{encoded_claims}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        now = int(time.time())
        if claims.get("iss") != TOKEN_ISSUER or claims.get("aud") != TOKEN_AUDIENCE:
            raise ValueError("Invalid JWT issuer or audience")
        if not isinstance(claims.get("exp"), int) or claims["exp"] <= now:
            raise ValueError("Expired JWT")
        if (
            not isinstance(claims.get("iat"), int)
            or claims["iat"] > now + 30
            or not isinstance(claims.get("sub"), str)
            or not claims.get("sub")
            or claims.get("role") not in {"client", "staff", "admin"}
            or not isinstance(claims.get("jti"), str)
            or not claims.get("jti")
        ):
            raise ValueError("Invalid JWT claims")
        return claims
    except Exception as exc:
        raise ValueError("Invalid access token") from exc
