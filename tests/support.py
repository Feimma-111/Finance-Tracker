"""Shared helpers for the web API tests."""

from finance_tracker import auth

# The real passcode hash is deliberately slow (600,000 rounds); tests don't need that.
auth.ITERATIONS = 1_000

PASSCODE = "246810"


def sign_in(client) -> None:
    """Set the passcode on a fresh app; the test client keeps the session cookie."""
    response = client.post("/api/auth/setup", json={"passcode": PASSCODE})
    assert response.status_code == 200, response.text
