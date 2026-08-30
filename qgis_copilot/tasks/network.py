"""Qt thread wrapper for model calls; no QGIS or UI objects cross this boundary."""

from __future__ import annotations

from threading import Event

from qgis.PyQt.QtCore import QThread, pyqtSignal
from qgis_copilot.models.base import ModelCancelledError, ModelRequestError
from qgis_copilot.security.redaction import redact_text


class NetworkRequestThread(QThread):
    """Runs a synchronous adapter safely outside QGIS's UI thread using plain data."""

    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, adapter, messages: list[dict], tools: list[dict] | None = None, parent=None):
        super().__init__(parent)
        self._adapter = adapter
        self._messages = [dict(message) for message in messages]
        self._tools = [dict(tool) for tool in (tools or [])]
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            if self._tools:
                completion = self._adapter.complete(self._messages, self._cancel_event, self._tools)
            else:
                completion = self._adapter.complete(self._messages, self._cancel_event)
        except ModelCancelledError:
            self.cancelled.emit()
        except ModelRequestError as exc:
            self.failed.emit(redact_text(exc))
        except Exception as exc:  # Boundary: do not leak raw failures into UI.
            self.failed.emit(redact_text(f"模型请求发生未预期错误：{exc}"))
        else:
            if self._cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.completed.emit(completion)
