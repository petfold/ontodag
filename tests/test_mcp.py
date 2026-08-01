"""The read-only MCP agent surface (docs/AGENT_SURFACE.md, CONTRACT.md §2).

What must hold: every answer cites its root and carries the contract
version plus the namespaced `annotations` map; terms are echoed in
canonical form (the agent is shown what was answered, not what it typed);
errors teach and are tool errors, never protocol crashes; as_of pins a
snapshot; `certify` is reserved and says so; and a *file* store answers
with a real semantic root (equal knowledge, equal root — G1 through the
agent surface).
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

from ontodag import CONTRACT_VERSION
from ontodag.__main__ import Session, dispatch
from ontodag.dimensions import REGISTRY_VERSION
from ontodag.mcp import AgentSurface, MCPServer, TOOL_SPECS

REPO_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

FIXTURE = (
    "put dimension",
    "put calendar-dimension dimension",
    "put linear-dimension dimension",
    "put time calendar-dimension",
    "put weight linear-dimension",
    "put pet",
    "put cat pet",
)


def build_store(path, extra=()):
    session = Session(path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        for line in FIXTURE + tuple(extra):
            assert dispatch(line.split(), session) == 0, line
        assert dispatch(["put", "doc", "time(2026)"], session) == 0
        assert dispatch(["put", "light", "weight(500g)"], session) == 0
        assert dispatch(["put", "box", "weight(0.8kg..1.5kg)"], session) == 0
        assert dispatch(["put", "heavy", "weight(2kg)"], session) == 0
    return session


class SurfaceHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = os.path.join(self.tmp.name, "store.od")
        build_store(self.store)
        self.surface = AgentSurface(self.store)
        self.server = MCPServer(self.surface)

    def call(self, tool, arguments=None, expect_error=False):
        response = self.server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}}})
        result = response["result"]
        self.assertEqual(result.get("isError", False), expect_error,
                         result["content"][0]["text"])
        if expect_error:
            return result["content"][0]["text"]
        answer = result["structuredContent"]
        # The envelope, on every successful answer (CONTRACT.md §2):
        self.assertEqual(answer["contract"], CONTRACT_VERSION)
        self.assertEqual(answer["annotations"], {})
        self.assertTrue(answer["root"], "answers must cite a root")
        return answer


class TestProtocol(SurfaceHarness):
    def test_initialize_and_tools_list(self):
        response = self.server.handle(
            {"jsonrpc": "2.0", "id": 0, "method": "initialize",
             "params": {"protocolVersion": "2025-03-26"}})
        info = response["result"]
        self.assertEqual(info["serverInfo"]["name"], "odag-mcp")
        self.assertIn("tools", info["capabilities"])

        listed = self.server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {t["name"] for t in listed["result"]["tools"]}
        self.assertEqual(names, {"about", "query", "is_below",
                                 "overlapping", "describe", "canon"})
        for tool in listed["result"]["tools"]:
            self.assertIn("inputSchema", tool)
            self.assertTrue(tool["description"])

    def test_notifications_get_no_answer_and_unknown_methods_error(self):
        self.assertIsNone(self.server.handle(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}))
        response = self.server.handle(
            {"jsonrpc": "2.0", "id": 9, "method": "no/such"})
        self.assertEqual(response["error"]["code"], -32601)

    def test_tool_specs_match_handlers(self):
        from ontodag.mcp import TOOL_HANDLERS
        self.assertEqual({t["name"] for t in TOOL_SPECS},
                         set(TOOL_HANDLERS))


class TestTools(SurfaceHarness):
    CANONICAL_2026 = "time(2026-01-01T00:00:00Z..2026-12-31T23:59:59Z)"

    def test_about_is_the_discoverability_record(self):
        answer = self.call("about")
        self.assertEqual(answer["registry_version"], REGISTRY_VERSION)
        self.assertIn("pet", answer["top"])
        self.assertEqual(answer["dimensions"],
                         {"time": "calendar-dimension",
                          "weight": "linear-dimension"})
        self.assertGreater(answer["items"], 5)
        self.assertIn("query", answer["capabilities"])

    def test_query_conjunction_echoes_canonical_terms(self):
        answer = self.call("query", {"terms": ["time(2026)"]})
        self.assertEqual(answer["terms"], [self.CANONICAL_2026])
        self.assertIn("doc", answer["items"])
        self.assertEqual(answer["count"], len(answer["items"]))

    def test_query_dnf_and_unknown_names_fail_closed(self):
        answer = self.call("query", {"any_of": [["cat"], ["weight(..1kg)"]]})
        self.assertIn("light", answer["items"])
        self.assertNotIn("heavy", answer["items"])
        empty = self.call("query", {"terms": ["no-such-thing"]})
        self.assertEqual(empty["items"], [])

    def test_query_needs_exactly_one_shape(self):
        text = self.call("query", {}, expect_error=True)
        self.assertIn("exactly one", text)
        text = self.call("query", {"terms": ["a"], "any_of": [["b"]]},
                         expect_error=True)
        self.assertIn("exactly one", text)

    def test_is_below_fail_closed_with_canonical_echo(self):
        answer = self.call("is_below", {"sub": "weight(3kg)",
                                        "sup": "weight(..5kg)"})
        self.assertTrue(answer["result"])
        self.assertEqual(answer["sub"], "weight(3000000mg)")
        self.assertEqual(answer["sup"], "weight(..5000000mg)")
        self.assertFalse(self.call("is_below",
                                   {"sub": "nope", "sup": "pet"})["result"])

    def test_overlapping_names_its_modality(self):
        answer = self.call("overlapping", {"term": "weight(1kg..)"})
        self.assertIn("box", answer["candidates"])
        self.assertIn("heavy", answer["candidates"])
        self.assertNotIn("light", answer["candidates"])
        self.assertIn("possible coexistence", answer["note"])

    def test_describe_returns_display_beside_the_name(self):
        answer = self.call("describe", {"term": "weight(2kg)"})
        self.assertEqual(answer["name"], "weight(2000000mg)")
        self.assertEqual(answer["display"], "weight(2kg)")
        self.assertTrue(answer["exists"])
        self.assertIn("heavy", answer["children"])
        self.assertIn("weight", answer["parents"])
        ghost = self.call("describe", {"term": "no-such-thing"})
        self.assertFalse(ghost["exists"])

    def test_canon_is_the_canonical_echo(self):
        answer = self.call("canon", {"term": "time(2026)"})
        self.assertEqual(answer["canonical"], self.CANONICAL_2026)
        self.assertEqual(answer["display"], "time(2026)")
        self.assertEqual(answer["surface_version"], "0.1")

    def test_errors_teach_and_certify_is_reserved(self):
        text = self.call("query", {"terms": ["weight(3zz)"]},
                         expect_error=True)
        self.assertIn("unknown unit", text)
        text = self.call("is_below", {"sub": "a", "sup": "b",
                                      "certify": True}, expect_error=True)
        self.assertIn("certificates are not available yet", text)

    def test_as_of_current_root_answers_and_unknown_root_teaches(self):
        current = self.surface.root
        answer = self.call("query", {"terms": ["pet"], "as_of": current})
        self.assertEqual(answer["root"], current)
        self.assertIn("cat", answer["items"])
        text = self.call("query", {"terms": ["pet"], "as_of": "00" * 32},
                         expect_error=True)
        self.assertIn("not retrievable", text)


class TestFileStoreRootIsSemantic(unittest.TestCase):
    def test_equal_knowledge_equal_root_across_put_orders(self):
        # G1 through the agent surface: two file stores with the same
        # content, built in different orders, answer with the same root.
        with tempfile.TemporaryDirectory() as tmp:
            a_path = os.path.join(tmp, "a.od")
            b_path = os.path.join(tmp, "b.od")
            build_store(a_path)
            build_store(b_path, extra=("put zebra pet",))
            session = Session(b_path)
            buf = io.StringIO()
            with redirect_stdout(buf):
                dispatch(["remove", "zebra"], session)
            a, b = AgentSurface(a_path), AgentSurface(b_path)
            self.assertEqual(a.root, b.root)


class TestStdioEndToEnd(unittest.TestCase):
    def test_initialize_list_and_call_over_stdio(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "store.od")
            build_store(store)
            env = dict(os.environ, PYTHONPATH=REPO_SRC,
                       ONTODAG_HOME=tmp)
            messages = [
                {"jsonrpc": "2.0", "id": 0, "method": "initialize",
                 "params": {"protocolVersion": "2025-03-26"}},
                {"jsonrpc": "2.0",
                 "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "query",
                            "arguments": {"terms": ["time(2026)"]}}},
            ]
            feed = "".join(json.dumps(m) + "\n" for m in messages)
            proc = subprocess.run(
                [sys.executable, "-m", "ontodag.mcp", "-f", store],
                input=feed, capture_output=True, text=True, env=env,
                timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            responses = [json.loads(line)
                         for line in proc.stdout.splitlines() if line]
            by_id = {r["id"]: r for r in responses}
            self.assertEqual(set(by_id), {0, 1, 2})  # notification silent
            tools = {t["name"] for t in by_id[1]["result"]["tools"]}
            self.assertIn("about", tools)
            answer = by_id[2]["result"]["structuredContent"]
            self.assertIn("doc", answer["items"])
            self.assertTrue(answer["root"])


if __name__ == "__main__":
    unittest.main()
