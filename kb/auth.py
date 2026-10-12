"""The single Owner token: sent as a bearer header by API clients, held in a cookie by the web UI."""

import secrets


def valid_token(expected: str | None, given: str | None) -> bool:
    """False whenever no token is configured."""
    return bool(expected) and secrets.compare_digest(given or "", expected)
