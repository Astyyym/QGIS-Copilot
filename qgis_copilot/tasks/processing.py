"""QGIS Processing task runners for confirmed, non-overwriting outputs."""

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


class RasterSlopeProcessingTask(QObject):
    """Run confirmed GDAL slope, warping geographic DEMs to meters first."""
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, plan: dict[str, Any], parent=None):
        super().__init__(parent)
        self.plan = plan
        self._context = QgsProcessingContext(); self._context.setProject(QgsProject.instance())
        self._feedback = QgsProcessingFeedback(); self._task = None; self._cancel_requested = False; self._stage = ""
        self._temp_dir = Path(tempfile.mkdtemp(prefix="qgis_copilot_slope_"))

    def start(self):
        Path(self.plan["output_path"]).parent.mkdir(parents=True, exist_ok=True)
        if self.plan["parameters"].get("reproject_before_slope"):
            self._run_reproject()
        else:
            self._run_slope(self.plan["source_layer"])

    def _run_reproject(self):
        algorithm = QgsApplication.processingRegistry().algorithmById("gdal:warpreproject")
        if algorithm is None:
            self.failed.emit("当前 QGIS 未提供 gdal:warpreproject，未生成输出。")
            return
        self._stage = "reproject"
        parameters = {"INPUT": self.plan["source_layer"], "SOURCE_CRS": self.plan["source_metadata"]["crs"], "TARGET_CRS": self.plan["expected_output_crs"], "RESAMPLING": 1, "DATA_TYPE": 6, "MULTITHREADING": False, "OUTPUT": str(self._temp_dir / "dem_metric.tif")}
        self._task = QgsProcessingAlgRunnerTask(algorithm, parameters, self._context, self._feedback)
        self._task.executed.connect(self._done); QgsApplication.taskManager().addTask(self._task)

    def _run_slope(self, input_layer):
        algorithm = QgsApplication.processingRegistry().algorithmById("gdal:slope")
        if algorithm is None:
            self.failed.emit("当前 QGIS 未提供 gdal:slope，未生成输出。"); return
        self._stage = "slope"
        parameters = dict(self.plan["processing_parameters"]); parameters["INPUT"] = input_layer
        parameters["OUTPUT"] = self.plan["output_path"]
        self._task = QgsProcessingAlgRunnerTask(algorithm, parameters, self._context, self._feedback)
        self._task.executed.connect(self._done); QgsApplication.taskManager().addTask(self._task)

    def cancel(self):
        self._cancel_requested = True
        if self._task: self._task.cancel()

    def _done(self, successful, results):
        from qgis_copilot.tools.raster.dem_validators import validate_slope_output
        if self._cancel_requested or (self._task and self._task.isCanceled()):
            self._remove(); self._cleanup_temp(); self.cancelled.emit(); return
        if not successful:
            self._remove(); self._cleanup_temp(); self.failed.emit(f"坡度 Processing 阶段“{self._stage}”失败；未把结果添加到项目。"); return
        if self._stage == "reproject":
            metric_input = results.get("OUTPUT")
            if not metric_input or not Path(str(metric_input)).is_file():
                self._cleanup_temp(); self.failed.emit("DEM 临时重投影未生成有效栅格，未执行坡度。"); return
            self._run_slope(metric_input); return
        try:
            verified = validate_slope_output(self.plan["output_path"], self.plan)
        except ValueError as exc:
            self._remove(); self._cleanup_temp(); self.failed.emit(str(exc)); return
        layer = verified.pop("layer"); QgsProject.instance().addMapLayer(layer); self._cleanup_temp()
        self.completed.emit({"tool": "slope_from_dem", "output_path": self.plan["output_path"], "output_layer_id": layer.id(), "output_layer_name": layer.name(), "feature_count": 0, **verified})

    def _remove(self):
        try: Path(self.plan["output_path"]).unlink(missing_ok=True)
        except OSError: pass

    def _cleanup_temp(self):
        for path in self._temp_dir.glob("*"):
            try: path.unlink()
            except OSError: pass
        try: self._temp_dir.rmdir()
        except OSError: pass


class RasterOrganizationProcessingTask(QObject):
    """Run confirmed Goal 12 raster work and verify real output content."""
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()
    _ALGORITHMS = {"clip_raster_by_mask": "gdal:cliprasterbymasklayer", "reproject_raster": "gdal:warpreproject", "zonal_statistics": "native:zonalstatisticsfb"}

    def __init__(self, plan: dict[str, Any], parent=None):
        super().__init__(parent)
        self.plan = plan
        self._context = QgsProcessingContext(); self._context.setProject(QgsProject.instance())
        self._feedback = QgsProcessingFeedback(); self._task = None; self._cancel_requested = False

    def start(self):
        algorithm_id = self._ALGORITHMS.get(self.plan.get("tool"))
        algorithm = QgsApplication.processingRegistry().algorithmById(algorithm_id) if algorithm_id else None
        if algorithm is None:
            self.failed.emit(f"当前 QGIS 未提供 {algorithm_id or '所需'} Processing 算法，未生成输出。")
            return
        Path(self.plan["output_path"]).parent.mkdir(parents=True, exist_ok=True)
        self._task = QgsProcessingAlgRunnerTask(algorithm, self.plan["processing_parameters"], self._context, self._feedback)
        self._task.executed.connect(self._done); QgsApplication.taskManager().addTask(self._task)

    def cancel(self):
        self._cancel_requested = True
        if self._task: self._task.cancel()

    def _done(self, successful, _results):
        if self._cancel_requested or (self._task and self._task.isCanceled()):
            self._remove(); self.cancelled.emit(); return
        if not successful:
            self._remove(); self.failed.emit("栅格 Processing 失败；未把结果添加到项目。"); return
        try:
            if self.plan["tool"] == "zonal_statistics":
                from qgis_copilot.tools.raster.organization_validators import validate_zonal_output
                verified = validate_zonal_output(self.plan["output_path"], self.plan)
            else:
                from qgis_copilot.tools.raster.organization_validators import validate_raster_output
                verified = validate_raster_output(self.plan["output_path"], self.plan)
        except ValueError as exc:
            self._remove(); self.failed.emit(str(exc)); return
        layer = verified.pop("layer"); QgsProject.instance().addMapLayer(layer)
        self.completed.emit({"tool": self.plan["tool"], "output_path": self.plan["output_path"], "output_layer_id": layer.id(), "output_layer_name": layer.name(), "source_layer_id": self.plan["source_layer"].id(), **verified})

    def _remove(self):
        try: Path(self.plan["output_path"]).unlink(missing_ok=True)
        except OSError: pass


class ReprojectProcessingTask(QObject):
    """Execute a confirmed reprojection and verify the new layer before insertion."""

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
        self._cancel_requested = False

    def start(self) -> None:
        algorithm = QgsApplication.processingRegistry().algorithmById("native:reprojectlayer")
        if algorithm is None:
            self.failed.emit("当前 QGIS 未提供 native:reprojectlayer，未生成输出。")
            return
        self._task = QgsProcessingAlgRunnerTask(algorithm, self.plan["processing_parameters"], self._context, self._feedback)
        self._task.executed.connect(self._on_executed)
        QgsApplication.taskManager().addTask(self._task)

    def cancel(self) -> None:
        self._cancel_requested = True
        if self._task is not None:
            self._task.cancel()

    def _on_executed(self, successful: bool, results: dict) -> None:
        if self._cancel_requested or (self._task is not None and self._task.isCanceled()):
            self._remove_partial_output()
            self.cancelled.emit()
            return
        if not successful:
            self._remove_partial_output()
            self.failed.emit("重投影 Processing 失败；未把结果添加到项目。")
            return
        output_path = Path(self.plan["output_path"])
        if not output_path.is_file():
            self.failed.emit(f"Processing 已结束，但未找到输出文件：{output_path}")
            return
        layer = QgsVectorLayer(str(output_path), self.plan["output_layer_name"], "ogr")
        if not layer.isValid() or layer.crs().authid() != self.plan["target_crs"]:
            del layer
            self._remove_partial_output()
            self.failed.emit("输出文件无法验证为有效图层或目标 CRS 不正确；未加入项目。")
            return
        QgsProject.instance().addMapLayer(layer)
        self.completed.emit({"output_path": str(output_path), "output_layer_id": layer.id(),
                             "output_layer_name": layer.name(), "feature_count": layer.featureCount(),
                             "source_layer_id": self.plan["inputs"]["layer_id"], "target_crs": layer.crs().authid()})

    def _remove_partial_output(self) -> None:
        """The confirmed path was required to be new, so a failed partial file is safe to remove."""
        output = Path(self.plan["output_path"])
        try:
            if output.is_file():
                output.unlink()
        except OSError:
            pass


class VectorProcessingTask(QObject):
    """Shared confirmed runner for clip and filtered export; verifies before insertion."""
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, plan: dict[str, Any], parent=None):
        super().__init__(parent); self.plan = plan; self._task = None; self._cancel_requested = False
        self._context = QgsProcessingContext(); self._context.setProject(QgsProject.instance()); self._feedback = QgsProcessingFeedback()

    def start(self):
        if self.plan["tool"] == "export_filtered_features":
            kind = self.plan["parameters"]["filter_kind"]; source = self.plan["source_layer"]
            if kind == "selection" and sorted(source.selectedFeatureIds()) != self.plan["parameters"]["selected_feature_ids"]:
                self.failed.emit("当前选择集已变化；已拒绝导出，未生成输出。"); return
            if kind == "expression":
                algorithm_id = "native:extractbyexpression"
                self.plan["processing_parameters"]["EXPRESSION"] = self.plan["parameters"]["expression"]
            elif kind == "selection":
                algorithm_id = "native:saveselectedfeatures"
            else:
                algorithm_id = "native:extractbyexpression"
                self.plan["processing_parameters"]["EXPRESSION"] = "$id IN (" + ",".join(str(x) for x in self.plan["parameters"]["matched_feature_ids"]) + ")"
        elif self.plan["tool"] == "clip_vector":
            algorithm_id = "native:clip"
        elif self.plan["tool"] == "intersection":
            algorithm_id = "native:intersection"
        elif self.plan["tool"] == "dissolve":
            algorithm_id = "native:dissolve"
        else:
            self.failed.emit("未知的矢量 Processing 类型；未生成输出。"); return
        algorithm = QgsApplication.processingRegistry().algorithmById(algorithm_id)
        if algorithm is None: self.failed.emit(f"当前 QGIS 未提供 {algorithm_id}，未生成输出。"); return
        Path(self.plan["output_path"]).parent.mkdir(parents=True, exist_ok=True)
        self._task = QgsProcessingAlgRunnerTask(algorithm, self.plan["processing_parameters"], self._context, self._feedback)
        self._task.executed.connect(self._done); QgsApplication.taskManager().addTask(self._task)

    def cancel(self):
        self._cancel_requested = True
        if self._task: self._task.cancel()

    def _done(self, successful, _results):
        if self._cancel_requested or (self._task and self._task.isCanceled()): self._remove(); self.cancelled.emit(); return
        output = Path(self.plan["output_path"])
        if not successful or not output.is_file(): self._remove(); self.failed.emit("矢量 Processing 失败；未把结果添加到项目。"); return
        layer = QgsVectorLayer(str(output), self.plan["output_layer_name"], "ogr")
        if not layer.isValid(): self._remove(); self.failed.emit("输出无法重新打开为有效图层；未加入项目。"); return
        QgsProject.instance().addMapLayer(layer)
        result = {"output_path": str(output), "output_layer_id": layer.id(), "output_layer_name": layer.name(), "feature_count": layer.featureCount(), "source_layer_id": self.plan["inputs"].get("layer_id", self.plan["inputs"].get("input_layer_id")), "tool": self.plan["tool"]}
        self.completed.emit(result)

    def _remove(self):
        try: Path(self.plan["output_path"]).unlink(missing_ok=True)
        except OSError: pass
