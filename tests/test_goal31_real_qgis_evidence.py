"""Goal 3-1 headless real-QGIS project evidence with local two-turn model seam."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from qgis.core import QgsApplication, QgsFeature, QgsField, QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtCore import QVariant

from qgis_copilot.agent.core import AgentCore
from qgis_copilot.models.openai_compatible import OpenAICompatibleAdapter
from qgis_copilot.models.settings import ModelSettings
from qgis_copilot.tools.qgis_tools import create_default_registry
from qgis_copilot.context.project_context import build_project_summary


class _DesktopLoopHandler(BaseHTTPRequestHandler):
    requests = []
    sequence = []

    def do_POST(self):
        request_body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.__class__.requests.append(request_body)
        second_turn = any(message["role"] == "tool" for message in request_body["messages"])
        request = self.__class__.sequence[0]
        if second_turn:
            response = {"model": "desktop-local", "choices": [{"message": {"content": request["answer"]}}]}
        else:
            response = {"model": "desktop-local", "choices": [{"message": {"content": None, "tool_calls": [{"id": request["id"], "type": "function", "function": {"name": request["tool"], "arguments": json.dumps(request["arguments"], ensure_ascii=False)}}]}}]}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response, ensure_ascii=False).encode())

    def log_message(self, _format, *_args):
        pass


class GoalThreeOneRealQgisEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qgis = QgsApplication([], False)
        cls.qgis.initQgis()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _DesktopLoopHandler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.adapter = OpenAICompatibleAdapter(ModelSettings(f"http://127.0.0.1:{cls.server.server_port}/v1", "desktop-local", 5), "test-only")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.qgis.exitQgis()

    def setUp(self):
        self.project = QgsProject.instance()
        self.project.clear()
        self.nine_line = self._memory_layer("九段线", [("segment", QVariant.String)], [{"segment": "A"}])
        self.stations = self._memory_layer("70个气象站点", [("station", QVariant.String), ("temp", QVariant.Int)], [{"station": f"S{i}", "temp": i} for i in range(70)])
        self.project.addMapLayers([self.nine_line, self.stations])
        self.before_layer_ids = sorted(self.project.mapLayers())
        self.before_counts = {layer.id(): layer.featureCount() for layer in self.project.mapLayers().values()}

    def tearDown(self):
        self.project.clear()

    @staticmethod
    def _memory_layer(name, fields, rows):
        layer = QgsVectorLayer("None", name, "memory")
        provider = layer.dataProvider()
        provider.addAttributes([QgsField(field_name, field_type) for field_name, field_type in fields])
        layer.updateFields()
        for row in rows:
            feature = QgsFeature(layer.fields())
            feature.setAttributes([row[field.name()] for field in layer.fields()])
            provider.addFeature(feature)
        layer.updateExtents()
        return layer

    def _run_turn(self, request):
        _DesktopLoopHandler.sequence = [request]
        _DesktopLoopHandler.requests.clear()
        registry = create_default_registry()
        agent = AgentCore("只读", max_steps=3, tool_registry=registry)
        first = self.adapter.complete(agent.begin(request["user"], {"project": "local test"}), Event(), registry.discover())
        agent.accept_completion(first)
        event, result = agent.execute_tool(first.tool_calls[0].name, first.tool_calls[0].arguments)
        self.assertTrue(result.ok, event.detail)
        agent.accept_tool_result(first.tool_calls[0], result)
        second = self.adapter.complete(agent.next_model_request(), Event(), registry.discover())
        self.assertEqual(len(_DesktopLoopHandler.requests), 2)
        self.assertTrue(_DesktopLoopHandler.requests[0]["tools"])
        self.assertTrue(any(message["role"] == "tool" for message in _DesktopLoopHandler.requests[1]["messages"]))
        self.assertEqual(sorted(self.project.mapLayers()), self.before_layer_ids)
        self.assertEqual({layer.id(): layer.featureCount() for layer in self.project.mapLayers().values()}, self.before_counts)
        return result.as_dict(), second.content

    def test_project_summary_supports_raster_without_attribute_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            raster_path = Path(temp_dir) / "single_cell.asc"
            raster_path.write_text(
                "ncols 1\nnrows 1\nxllcorner 0\nyllcorner 0\ncellsize 1\nNODATA_value -9999\n1\n",
                encoding="ascii",
            )
            raster = QgsRasterLayer(str(raster_path), "底图栅格", "gdal")
            self.assertTrue(raster.isValid())
            self.project.addMapLayer(raster)
            summary = build_project_summary(self.project)
            raster_summary = next(layer for layer in summary["layers"] if layer["id"] == raster.id())
            self.assertEqual(raster_summary["fields"], [])
            self.assertEqual(raster_summary["name"], "底图栅格")
            self.project.removeMapLayer(raster.id())
            del raster

    def test_three_required_real_project_requests(self):
        evidence = []
        cases = [
            {"id": "call-list", "user": "当前项目有哪些图层？", "tool": "list_layers", "arguments": {}, "answer": "当前项目有九段线和70个气象站点。"},
            {"id": "call-inspect", "user": "告诉我九段线的字段和 CRS", "tool": "inspect_layer", "arguments": {"layer_id": self.nine_line.id()}, "answer": "九段线字段为 segment，CRS 正确。"},
            {"id": "call-query", "user": "查询70个气象站点图层前 5 条属性表数据", "tool": "query_features", "arguments": {"layer_id": self.stations.id(), "limit": 5}, "answer": "已返回70个气象站点前5条属性。"},
        ]
        for case in cases:
            result, answer = self._run_turn(case)
            evidence.append({"request": case["user"], "tool": result["tool"], "data": result["data"], "answer": answer})
        self.assertEqual([item["tool"] for item in evidence], ["list_layers", "inspect_layer", "query_features"])
        self.assertEqual(evidence[1]["data"]["layer"]["fields"][0]["name"], "segment")
        self.assertEqual(len(evidence[2]["data"]["features"]), 5)
        self.assertTrue(evidence[2]["data"]["has_more"])
        print("GOAL_3_1_REAL_QGIS_EVIDENCE=" + json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
