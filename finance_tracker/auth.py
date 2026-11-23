"""A 6-digit passcode lock for the web app (one user, no accounts).

How it works
------------
* The passcode is never stored. ``hash_passcode`` runs it through PBKDF2
  (600,000 rounds of SHA-256 with a random salt) and only that result is kept.
  Checking a guess takes a noticeable fraction of a second on purpose.
* Signing in creates a random session token. The browser keeps it in an
  HttpOnly cookie (page scripts can't read it); the database keeps only a
  SHA-256 of it, so a copied database can't be used to sign in either.
* Six digits is only a million combinations, so wrong guesses are rate
  limited: after 5 misses the app locks for 30 seconds, doubling with each
  further miss up to an hour.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

PASSCODE_LENGTH = 6
ITERATIONS = 600_000      # lowered in tests only
SESSION_DAYS = 30         # stay signed in on a device this long without using it
FREE_ATTEMPTS = 5         # wrong guesses allowed before the first lockout
FIRST_LOCKOUT = 30        # seconds
MAX_LOCKOUT = 3600        # seconds
COOKIE = "ft_session"


def validate_passcode(code: str) -> str:
    code = (code or "").strip()
    # [0-9], not \d: in Python \d also matches other scripts' digits (e.g. ١٢٣).
    if not re.fullmatch(rf"[0-9]{{{PASSCODE_LENGTH}}}", code):
        raise ValueError(f"the passcode must be exactly {PASSCODE_LENGTH} digits")
    return code


def hash_passcode(code: str) -> str:
    """'pbkdf2_sha256$<rounds>$<salt>$<hash>' -- the rounds are stored so they can be raised later."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode(), salt, ITERATIONS)
    return "$".join([
        "pbkdf2_sha256", str(ITERATIONS),
        base64.b64encode(salt).decode(), base64.b64encode(digest).decode(),
    ])


def verify_passcode(code: str, stored: str) -> bool:
    try:
        scheme, rounds, salt, expected = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", code.encode(), base64.b64decode(salt), int(rounds))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, base64.b64decode(expected))  # constant time


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def lockout_seconds(failures: int) -> int:
    """How long to lock after this many wrong guesses in a row."""
    if failures < FREE_ATTEMPTS:
        return 0
    return min(FIRST_LOCKOUT * 2 ** (failures - FREE_ATTEMPTS), MAX_LOCKOUT)
