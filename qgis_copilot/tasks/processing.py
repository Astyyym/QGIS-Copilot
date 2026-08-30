"""QGIS Processing task runner for confirmed, non-overwriting metric buffers."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from qgis.core import (
    QgsApplication,
    QgsProcessingAlgRunnerTask,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QObject, pyqtSignal


class BufferProcessingTask(QObject):
    """Run a confirmed buffer through QGIS Task Manager and verify its output.

    Geographic inputs are reprojected to EPSG:3857 for the meter-distance buffer,
    then returned to their source CRS. Intermediate files remain private temp data.
    """

    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, plan: dict[str, Any], parent=None):
        super().__init__(parent)
        self.plan = plan
        self._context = QgsProcessingContext()
        self._context.setProject(QgsProject.instance())
        self._feedback = QgsProcessingFeedback()
        self._task = None
        self._stage = ""
        self._cancel_requested = False
        self._source_crs = plan["source_crs"]
        self._needs_metric_reprojection = bool(plan["needs_metric_reprojection"])
        self._temp_dir = Path(tempfile.mkdtemp(prefix="qgis_copilot_buffer_"))
        self._working_input = None

    def start(self) -> None:
        Path(self.plan["output_path"]).parent.mkdir(parents=True, exist_ok=True)
        if self._needs_metric_reprojection:
            self._run("reproject_input", "native:reprojectlayer", {
                "INPUT": self.plan["source_layer"],
                "TARGET_CRS": "EPSG:3857",
                "OUTPUT": str(self._temp_dir / "input_metric.gpkg"),
            })
            return
        self._run_buffer(self.plan["source_layer"])

    def cancel(self) -> None:
        self._cancel_requested = True
        if self._task is not None:
            self._task.cancel()

    def _run(self, stage: str, algorithm_id: str, parameters: dict[str, Any]) -> None:
        algorithm = QgsApplication.processingRegistry().algorithmById(algorithm_id)
        if algorithm is None:
            self._finish_failure(f"当前 QGIS 未提供 {algorithm_id} Processing 算法，未生成任何输出。")
            return
        self._stage = stage
        self._task = QgsProcessingAlgRunnerTask(algorithm, parameters, self._context, self._feedback)
        self._task.executed.connect(self._on_executed)
        QgsApplication.taskManager().addTask(self._task)

    def _run_buffer(self, input_layer: Any) -> None:
        params = dict(self.plan["processing_parameters"])
        params["INPUT"] = input_layer
        params["OUTPUT"] = str(self._temp_dir / "buffer_metric.gpkg") if self._needs_metric_reprojection else self.plan["output_path"]
        self._run("buffer", "native:buffer", params)

    def _on_executed(self, successful: bool, results: dict) -> None:
        if self._cancel_requested or (self._task is not None and self._task.isCanceled()):
            self._cleanup_temp()
            self.cancelled.emit()
            return
        if not successful:
            self._finish_failure(f"Processing 阶段“{self._stage}”失败；未把结果添加到项目。")
            return
        output = results.get("OUTPUT")
        if self._stage == "reproject_input":
            self._working_input = output
            self._run_buffer(output)
            return
        if self._stage == "buffer" and self._needs_metric_reprojection:
            self._run("reproject_output", "native:reprojectlayer", {
                "INPUT": output,
                "TARGET_CRS": self._source_crs,
                "OUTPUT": self.plan["output_path"],
            })
            return
        self._verify_and_add_result(results)

    def _verify_and_add_result(self, results: dict) -> None:
        output_path = Path(self.plan["output_path"])
        if not output_path.is_file():
            self._finish_failure(f"Processing 已结束，但未找到输出文件：{output_path}")
            return
        layer = QgsVectorLayer(str(output_path), self.plan["output_layer_name"], "ogr")
        if not layer.isValid():
            self._finish_failure(f"输出文件存在，但 QGIS 无法重新打开结果图层：{output_path}")
            return
        QgsProject.instance().addMapLayer(layer)
        self._cleanup_temp()
        self.completed.emit({
            "output_path": str(output_path),
            "output_layer_id": layer.id(),
            "output_layer_name": layer.name(),
            "feature_count": layer.featureCount(),
            "metric_reprojection": self._needs_metric_reprojection,
            "processing_output": results.get("OUTPUT", str(output_path)),
        })

    def _finish_failure(self, detail: str) -> None:
        self._cleanup_temp()
        self.failed.emit(detail)

    def _cleanup_temp(self) -> None:
        if not self._temp_dir.exists():
            return
        for path in sorted(self._temp_dir.glob("*"), reverse=True):
            try:
                path.unlink()
            except OSError:
                pass
        try:
            self._temp_dir.rmdir()
        except OSError:
            pass
