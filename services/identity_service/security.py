from __future__ import annotations

import hashlib
import hmac
import os
import re

from services.common.security import create_token, ensure_private_key, get_public_key_pem, verify_token


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = password_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False

    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return hmac.compare_digest(actual, expected)


def normalize_phone(phone: str) -> str:
    if not re.fullmatch(r"[+0-9()\-\s]{7,24}", phone):
        raise ValueError("Invalid phone number")
    normalized = re.sub(r"\D", "", phone)
    if not 7 <= len(normalized) <= 15:
        raise ValueError("Invalid phone number")
    return normalized
