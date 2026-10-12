"""URL normalisation and the ids derived from it."""

import hashlib
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from kb.config import CAPTURED_AT_FORMAT, DEFAULT_PORTS, THOUGHT_ID_PREFIX, TRACKING_PARAMS, TRACKING_PREFIXES


def _is_tracking(name: str) -> bool:
    lowered = name.lower()
    return lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PREFIXES)


def normalise_url(url: str) -> str:
    """Canonical form of an absolute http(s) URL; raises ValueError otherwise."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS or not parts.hostname:
        raise ValueError(f"not an absolute http(s) URL: {url!r}")

    host = parts.hostname.lower()
    if parts.port and parts.port != DEFAULT_PORTS[scheme]:
        host = f"{host}:{parts.port}"

    path = parts.path.rstrip("/")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)))

    return urlunsplit((scheme, host, path, query, ""))


def item_id(normalised_url: str) -> str:
    return hashlib.sha256(normalised_url.encode("utf-8")).hexdigest()


def format_captured_at(captured_at: datetime) -> str:
    """Timezone-aware datetime -> UTC string used in ids and stored fields."""
    if captured_at.tzinfo is None:
        raise ValueError("captured_at must be timezone-aware")
    utc = captured_at.astimezone(UTC)
    return utc.strftime(CAPTURED_AT_FORMAT.format(ms=utc.microsecond // 1000))


def thought_id(written_at: datetime) -> str:
    """A Thought has no URL; it is identified by the instant it was first written."""
    return item_id(THOUGHT_ID_PREFIX + format_captured_at(written_at))


def version_id(item_id: str, captured_at: datetime) -> str:
    return f"{item_id}:{format_captured_at(captured_at)}"
