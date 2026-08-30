"""Goal 3-1 read-only Agent loop tests using QGIS's bundled runtime."""

from __future__ import annotations

import json
import os
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from qgis.PyQt.QtCore import QCoreApplication

from qgis_copilot.agent.core import AgentCore
from qgis_copilot.models.base import ChatCompletion, ToolCall
from qgis_copilot.models.openai_compatible import OpenAICompatibleAdapter
from qgis_copilot.models.settings import DEFAULT_TIMEOUT_SECONDS, ModelSettings
from qgis_copilot.tasks.network import NetworkRequestThread
from qgis_copilot.tools.contracts import PermissionLevel, ToolSpec
from qgis_copilot.tools.qgis_tools import create_default_registry, inspect_layer, query_features
from qgis_copilot.tools.registry import ToolRegistry
from qgis_copilot.context.project_context import build_model_project_context, build_project_summary
from qgis_copilot.application.controller import format_timeout_error


class FakeCrs:
    def authid(self): return "EPSG:4326"
    def description(self): return "WGS 84"


class FakeExtent:
    def toString(self): return "0,0 : 1,1"


class FakeField:
    def __init__(self, name): self._name = name
    def name(self): return self._name
    def type(self): return 10
    def typeName(self): return "Text"
    def length(self): return 64
    def precision(self): return 0


class FakeFeature:
    def __init__(self, values): self.values = values
    def __getitem__(self, key): return self.values[key]


class FakeLayer:
    def __init__(self, lid, name, rows=None):
        self._id, self._name = lid, name
        self._rows = rows if rows is not None else [{"name": "a", "value": 1}, {"name": "b", "value": 2}]
    def id(self): return self._id
    def name(self): return self._name
    def fields(self): return [FakeField("name"), FakeField("value")]
    def getFeatures(self): return iter([FakeFeature(row) for row in self._rows])
    def providerType(self): return "memory"
    def source(self): return "memory"
    def type(self): return 0
    def geometryType(self): return 0
    def crs(self): return FakeCrs()
    def featureCount(self): return len(self._rows)
    def extent(self): return FakeExtent()
    def selectedFeatureIds(self): return []
    def attributeAlias(self, _index): return ""


class FakeProject:
    def __init__(self, layers=None): self.layers = layers or [FakeLayer("l1", "roads")]
    def mapLayer(self, lid): return next((layer for layer in self.layers if layer.id() == lid), None)
    def mapLayers(self): return {layer.id(): layer for layer in self.layers}


class _LoopHandler(BaseHTTPRequestHandler):
    requests = []
    layer_id = "l1"

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.__class__.requests.append(body)
        is_second_turn = any(message["role"] == "tool" for message in body["messages"])
        response = (
            {"model": "loop-test", "choices": [{"message": {"content": "项目包含 roads 图层；其前 1 条属性为 a。"}}]}
            if is_second_turn else
            {"model": "loop-test", "choices": [{"message": {"content": None, "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "query_features", "arguments": json.dumps({"layer_id": self.layer_id, "limit": 1})}}]}}]}
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def log_message(self, _format, *_args):
        pass


class _CapturingAdapter:
    def __init__(self): self.calls = []
    def complete(self, messages, cancel_event, tools=None):
        self.calls.append((messages, tools))
        return ChatCompletion("", tool_calls=(ToolCall("bad", "missing", {}),))


class GoalThreeOneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _LoopHandler)
        cls.server_thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_four_schemas_and_read_only_permissions(self):
        registry = create_default_registry()
        schemas = registry.discover()
        self.assertEqual([schema["function"]["name"] for schema in schemas], ["buffer_vector", "get_project_state", "inspect_layer", "list_layers", "query_features"])
        read_only = [schema for schema in schemas if schema["function"]["name"] != "buffer_vector"]
        self.assertTrue(all(schema["permission"] == "read_only" for schema in read_only))
        self.assertEqual(schemas[-1]["function"]["parameters"]["properties"]["limit"]["maximum"], 100)

    def test_inspect_layer_schema_and_query_boundary(self):
        project = FakeProject([FakeLayer("l1", "roads", [{"name": "a", "value": 1}, {"name": "b", "value": 2}])])
        inspected = inspect_layer({"project": project, "layer_id": "l1"})["layer"]
        self.assertEqual(inspected["crs"], "EPSG:4326")
        self.assertEqual(inspected["fields"][0]["type_name"], "Text")
        query = query_features({"project": project, "layer_id": "l1", "limit": 1})
        self.assertEqual(query["features"], [{"name": "a", "value": 1}])
        self.assertEqual(query["returned_count"], 1)
        self.assertTrue(query["has_more"])
        with self.assertRaises(ValueError): query_features({"project": project, "layer_id": "l1", "limit": 101})

    def test_structured_unknown_ambiguous_and_invalid_calls(self):
        project = FakeProject([FakeLayer("a", "same"), FakeLayer("b", "same")])
        registry = ToolRegistry()
        registry.register(ToolSpec("query", "query", PermissionLevel.READ_ONLY, query_features))
        self.assertFalse(registry.call("missing").ok)
        self.assertFalse(registry.call("query", {"project": project, "name": "same"}).ok)
        self.assertFalse(registry.call("query", {"project": project, "layer_id": "a", "limit": "bad"}).ok)

    def test_lightweight_model_context_excludes_details_but_tool_summary_keeps_them(self):
        project = FakeProject([FakeLayer("l1", "roads")])
        initial = build_model_project_context(project)
        layer = initial["layers"][0]
        self.assertEqual(initial["project"]["layer_count"], 1)
        self.assertEqual(layer["name"], "roads")
        self.assertNotIn("fields", layer)
        self.assertNotIn("source", layer)
        self.assertNotIn("extent", layer)
        self.assertNotIn("selected_count", layer)
        detailed = build_project_summary(project)["layers"][0]
        self.assertIn("fields", detailed)
        self.assertIn("source", detailed)
        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, 120)
        self.assertEqual(ModelSettings("http://localhost:1234/v1", "x").timeout_seconds, 120)

    def test_timeout_message_exposes_timeout_settings_and_manual_retry(self):
        detail = format_timeout_error("模型服务请求超时。", 120)
        self.assertIn("120 秒", detail)
        self.assertIn("设置", detail)
        self.assertIn("重试", detail)
        self.assertIn("不会自动重复请求", detail)

    def test_second_model_turn_omits_initial_project_context(self):
        agent = AgentCore("system", max_steps=3)
        agent.begin("查 roads", {"layers": [{"name": "roads", "fields": ["large"]}]})
        call = ToolCall("call-1", "query_features", {"layer_id": "l1", "limit": 1})
        agent.accept_completion(ChatCompletion("", tool_calls=(call,)))
        from qgis_copilot.tools.contracts import ToolResult
        agent.accept_tool_result(call, ToolResult("query_features", True, {"features": [{"name": "a"}]}))
        second = agent.next_model_request()
        self.assertEqual([message["role"] for message in second], ["system", "user", "assistant", "tool"])
        self.assertFalse(any("当前 QGIS 上下文：" in message.get("content", "") for message in second))
        self.assertEqual(second[-1]["tool_call_id"], "call-1")

    def test_two_real_local_http_turns_and_conversation_protocol(self):
        _LoopHandler.requests.clear()
        registry = create_default_registry()
        agent = AgentCore("system", max_steps=3, tool_registry=registry)
        adapter = OpenAICompatibleAdapter(ModelSettings(self.base_url, "loop-test", 5), "test-only")
        first = adapter.complete(agent.begin("查询 roads 前一条", {"layers": []}), Event(), registry.discover())
        self.assertEqual(first.content, "")
        self.assertEqual(first.tool_calls[0].arguments, {"layer_id": "l1", "limit": 1})
        agent.accept_completion(first)
        project = FakeProject([FakeLayer("l1", "roads")])
        original_call = agent.tool_registry.call
        agent.tool_registry.call = lambda name, arguments: original_call(name, {**arguments, "project": project})
        event, result = agent.execute_tool(first.tool_calls[0].name, first.tool_calls[0].arguments)
        self.assertTrue(result.ok)
        agent.accept_tool_result(first.tool_calls[0], result)
        second = adapter.complete(agent.next_model_request(), Event(), registry.discover())
        self.assertIn("roads", second.content)
        self.assertEqual(len(_LoopHandler.requests), 2)
        self.assertEqual(_LoopHandler.requests[0]["tools"][0]["type"], "function")
        second_messages = _LoopHandler.requests[1]["messages"]
        self.assertTrue(any(message["role"] == "assistant" and message.get("tool_calls") for message in second_messages))
        tool_message = next(message for message in second_messages if message["role"] == "tool")
        self.assertEqual(tool_message["tool_call_id"], "call-1")
        self.assertTrue(json.loads(tool_message["content"])["ok"])

    def test_budget_failure_and_unknown_tool_do_not_fake_success(self):
        agent = AgentCore("system", max_steps=1, tool_registry=create_default_registry())
        agent.begin("x")
        with self.assertRaises(RuntimeError): agent.next_model_request()
        event, result = agent.execute_tool("missing", {})
        self.assertIsNotNone(result)
        self.assertFalse(result.ok)
        self.assertEqual(event.type.value, "failed")

    def test_network_thread_receives_only_plain_data(self):
        adapter = _CapturingAdapter()
        thread = NetworkRequestThread(adapter, [{"role": "user", "content": "x"}], [{"type": "function"}])
        thread.run()
        messages, tools = adapter.calls[0]
        self.assertEqual(messages, [{"role": "user", "content": "x"}])
        self.assertEqual(tools, [{"type": "function"}])


if __name__ == "__main__":
    unittest.main()
