"""Accounts and roles: scrypt password hashes, signed JWT access tokens, login throttling.

Roles, from least to most privileged:

* ``viewer``  - can search, save bookmarks and set up e-mail alerts
* ``curator`` - can also ingest files and trigger model rebuilds
* ``admin``   - can also manage users and delete documents
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

import jwt

ROLES = ("viewer", "curator", "admin")
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


def role_at_least(role: str, minimum: str) -> bool:
    return ROLES.index(role) >= ROLES.index(minimum) if role in ROLES else False


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                                dklen=len(base64.b64decode(expected)))
        return hmac.compare_digest(digest, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def create_token(user: dict, secret: str, issuer: str, ttl_hours: int) -> str:
    now = int(time.time())
    claims = {"sub": str(user["id"]), "role": user["role"], "name": user["name"], "email": user["email"],
              "iss": issuer, "iat": now, "exp": now + ttl_hours * 3600}
    return jwt.encode(claims, secret, algorithm="HS256")


def decode_token(token: str, secret: str) -> dict | None:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        return None


class LoginThrottle:
    """At most ``limit`` failed logins per key (ip + e-mail) in a sliding window."""

    def __init__(self, limit: int = 8, window: float = 300.0):
        self.limit, self.window = limit, window
        self._failures: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str) -> deque:
        bucket = self._failures[key]
        cutoff = time.monotonic() - self.window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        return bucket

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._trim(key)) >= self.limit

    def failed(self, key: str) -> None:
        with self._lock:
            self._trim(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
