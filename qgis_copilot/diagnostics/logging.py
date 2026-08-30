"""Privacy-preserving runtime diagnostics for QGIS Copilot."""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any

from qgis_copilot.security.redaction import redact_text

LOGGER_NAME = "qgis_copilot"


def _safe_summary(value: Any, *, max_length: int = 500) -> str:
    """Return a bounded, redacted diagnostic summary without raw model/tool payloads."""
    if isinstance(value, Mapping):
        text = json.dumps(dict(value), ensure_ascii=False, default=str, sort_keys=True)
    else:
        text = str(value)
    return redact_text(text)[:max_length]


class DiagnosticsLogger:
    """Emit structured, secret-safe events through Python's standard logging system."""

    def __init__(self, logger: logging.Logger | None = None):
        self._logger = logger or logging.getLogger(LOGGER_NAME)

    def event(self, name: str, *, status: str, duration_ms: int | None = None, summary: Any = "") -> None:
        fields = {"event": str(name), "status": str(status)}
        if duration_ms is not None:
            fields["duration_ms"] = max(0, int(duration_ms))
        if summary not in (None, ""):
            fields["summary"] = _safe_summary(summary)
        self._logger.info("QGIS_COPILOT_DIAGNOSTIC %s", json.dumps(fields, ensure_ascii=False, sort_keys=True))

    def timed(self, name: str):
        return _TimedDiagnostic(self, name)


class _TimedDiagnostic:
    def __init__(self, diagnostics: DiagnosticsLogger, name: str):
        self._diagnostics = diagnostics
        self._name = name
        self._started = 0.0

    def __enter__(self):
        self._started = time.monotonic()
        return self

    def success(self, summary: Any = "") -> None:
        self._diagnostics.event(self._name, status="success", duration_ms=self._elapsed_ms(), summary=summary)

    def failure(self, summary: Any = "") -> None:
        self._diagnostics.event(self._name, status="failure", duration_ms=self._elapsed_ms(), summary=summary)

    def _elapsed_ms(self) -> int:
        return int((time.monotonic() - self._started) * 1000)

    def __exit__(self, exc_type, exc, _traceback):
        if exc_type is not None:
            self.failure(exc)
        return False
