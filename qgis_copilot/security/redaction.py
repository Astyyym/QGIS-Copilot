"""Central redaction for secrets before UI, logs or errors receive text."""

from __future__ import annotations

import re
from collections.abc import Mapping

_SECRET_HEADER = re.compile(r"(?im)^(authorization\s*:\s*)(?:bearer\s+)?[^\s,;]+")
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+\-/=]+")
_JSON_SECRET = re.compile(
    r'(?i)(["\']?(?:api[_-]?key|authorization|token|password)["\']?\s*[:=]\s*["\']?)[^"\'\s,}]+'
)


def redact_text(value: object) -> str:
    """Return display-safe text without authorization headers or common secret fields."""
    text = str(value)
    text = _SECRET_HEADER.sub(r"\1[REDACTED]", text)
    text = _BEARER_TOKEN.sub("Bearer [REDACTED]", text)
    return _JSON_SECRET.sub(r"\1[REDACTED]", text)


def redact_headers(headers: Mapping[str, object]) -> dict[str, str]:
    """Copy headers while hiding credentials for diagnostic output."""
    return {
        str(name): "[REDACTED]" if str(name).lower() == "authorization" else redact_text(value)
        for name, value in headers.items()
    }
