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

    def test_query_refuses_both_shapes_at_once(self):
        text = self.call("query", {"terms": ["a"], "any_of": [["b"]]},
                         expect_error=True)
        self.assertIn("at most one", text)

    def test_no_terms_is_everything_not_an_error(self):
        # The empty query is the universe; an agent asking "what is in this
        # store" should get the store, not a usage error.
        everything = self.call("query", {})
        self.assertEqual(everything, self.call("query", {"terms": []}))
        self.assertIn("pet", everything["items"])
        self.assertEqual(everything["count"], len(everything["items"]))

    def test_limit_truncates_visibly_and_count_stays_complete(self):
        full = self.call("query", {})
        capped = self.call("query", {"limit": 3})
        self.assertEqual(capped["items"], full["items"][:3])
        self.assertTrue(capped["truncated"])
        # The whole point: the caller can still see how much it is missing.
        self.assertEqual(capped["count"], full["count"])
        self.assertFalse(full["truncated"])

    def test_a_limit_that_does_not_bite_is_not_reported_as_truncation(self):
        answer = self.call("query", {"terms": ["pet"], "limit": 1000})
        self.assertFalse(answer["truncated"])

    def test_a_bad_limit_is_a_teaching_error(self):
        text = self.call("query", {"limit": -1}, expect_error=True)
        self.assertIn("non-negative", text)

    def test_is_below_fail_closed_with_canonical_echo(self):
        answer = self.call("is_below", {"sub": "weight(3kg)",
                                        "sup": "weight(..5kg)"})
        self.assertTrue(answer["result"])
        self.assertEqual(answer["sub"], "weight(3kg)")
        self.assertEqual(answer["sup"], "weight(..5kg)")
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
        self.assertEqual(answer["name"], "weight(2kg)")
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

    def test_errors_teach_and_query_certify_is_reserved(self):
        text = self.call("query", {"terms": ["weight(3zz)"]},
                         expect_error=True)
        self.assertIn("unknown unit", text)
        text = self.call("query", {"terms": ["pet"], "certify": True},
                         expect_error=True)
        self.assertIn("is_below", text)   # points at what IS certifiable

    def test_is_below_certify_returns_a_verifiable_certificate(self):
        from ontodag.certificates import verify_below
        answer = self.call("is_below", {"sub": "weight(3kg)",
                                        "sup": "weight(..5kg)",
                                        "certify": True})
        self.assertTrue(answer["result"])
        cert = answer["certificate"]
        # trustless: check it against the cited root alone, no store
        self.assertTrue(verify_below(cert, answer["root"]))
        negative = self.call("is_below", {"sub": "cat", "sup": "light",
                                          "certify": True})
        self.assertFalse(negative["result"])
        self.assertFalse(verify_below(negative["certificate"],
                                      negative["root"]))

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


class WritableHarness(unittest.TestCase):
    """The write surface over an injected in-memory swarm-shaped backend:
    the fixture is built through the propose → echo → confirm flow itself."""

    def setUp(self):
        import hashlib

        from recordstore import MemoryBytesStore, RecordStore

        from ontodag.__main__ import SwarmBackend

        class FakeSigner:
            address = "fake:agent"

            @staticmethod
            def sign(data):
                return hashlib.sha256(b"fake:agent" + data).hexdigest()

        self.knowledge_blobs = MemoryBytesStore()
        self.prov_store = RecordStore(MemoryBytesStore())
        self.backend = SwarmBackend(
            "t",
            store_factory=lambda: RecordStore(self.knowledge_blobs),
            prov_store_factory=lambda: self.prov_store)

        def fake_verify(record):
            from ontodag.provenance import record_payload_bytes
            expected = hashlib.sha256(
                record["author"].encode() +
                record_payload_bytes(record)).hexdigest()
            return record["sig"] == expected

        self.fake_verify = fake_verify
        self.surface = AgentSurface("swarm:t", backend=self.backend,
                                    signer=FakeSigner(), writable=True,
                                    verifier=fake_verify)
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
        self.assertEqual(answer["contract"], CONTRACT_VERSION)
        self.assertEqual(answer["annotations"], {})
        self.assertIn("root", answer)   # None is honest for an empty store
        return answer

    def write(self, item, supers=()):
        proposed = self.call("propose_put",
                             {"item": item, "supers": list(supers)})
        return self.call("put", {"item": item, "supers": list(supers),
                                 "proposal": proposed["proposal"]}), proposed

    def provenance_records(self):
        from ontodag.provenance import ProvenanceStore
        return list(ProvenanceStore(self.prov_store).records())


class TestWriteSurface(WritableHarness):
    def test_propose_echoes_canonical_and_flags_missing(self):
        for item, supers in [("dimension", []),
                             ("linear-dimension", ["dimension"]),
                             ("weight", ["linear-dimension"])]:
            self.write(item, supers)
        proposed = self.call("propose_put", {
            "item": "parcel", "supers": ["weight(3kg)", "nowhere"]})
        self.assertEqual(proposed["item"], "parcel")
        self.assertIn("weight(3kg)", proposed["supers"])  # echo
        self.assertEqual(proposed["missing_supers"], ["nowhere"])
        self.assertIn("proposal", proposed)
        self.assertFalse(proposed["already_below"]["weight(3kg)"])

    def test_put_needs_a_matching_proposal(self):
        text = self.call("put", {"item": "pet", "supers": [],
                                 "proposal": "bogus"}, expect_error=True)
        self.assertIn("propose_put again", text)

    def test_put_writes_the_pair_and_signs_the_claims(self):
        answer, proposed = self.write("pet")
        self.assertNotEqual(answer["root"], proposed["basis"])
        self.assertTrue(answer["provenance_root"])
        self.assertEqual(answer["author"], "fake:agent")
        answer2, _ = self.write("cat", ["pet"])
        records = self.provenance_records()
        self.assertEqual(len(records), 2)  # pet⊑* and cat⊑pet assertions
        claims = {(r["subject"]["sub"], r["subject"]["sup"])
                  for r in records}
        self.assertEqual(claims, {("pet", "*"), ("cat", "pet")})
        for record in records:
            self.assertEqual(record["type"], "assertion")
            self.assertEqual(record["author"], "fake:agent")
            self.assertTrue(record["group"])
            self.assertTrue(record["sig"])
        # and the knowledge is really there, queryable
        result = self.call("query", {"terms": ["pet"]})
        self.assertIn("cat", result["items"])
        self.assertEqual(result["root"], answer2["root"])

    def test_stale_proposal_is_refused_after_the_store_moves(self):
        proposed = self.call("propose_put", {"item": "pet", "supers": []})
        self.write("robot")                       # the store moves
        text = self.call("put", {"item": "pet", "supers": [],
                                 "proposal": proposed["proposal"]},
                         expect_error=True)
        self.assertIn("store moved", text)

    def test_reput_is_idempotent_in_knowledge_new_in_audit(self):
        self.write("pet")
        first, _ = self.write("cat", ["pet"])
        before = len(self.provenance_records())
        second, _ = self.write("cat", ["pet"])    # same knowledge again
        self.assertEqual(first["root"], second["root"])   # no-op in graph
        self.assertEqual(len(self.provenance_records()), before + 1)

    def test_remove_couples_retraction_records(self):
        self.write("pet")
        self.write("cat", ["pet"])
        proposed = self.call("propose_remove", {"item": "cat"})
        retracts = {(c["sub"], c["sup"]) for c in proposed["retracts"]}
        self.assertEqual(retracts, {("cat", "pet"), ("cat", "*")})
        answer = self.call("remove", {"item": "cat",
                                      "proposal": proposed["proposal"]})
        self.assertEqual(answer["records"], 2)
        gone = self.call("query", {"terms": ["pet"]})
        self.assertNotIn("cat", gone["items"])
        retractions = [r for r in self.provenance_records()
                       if r["type"] == "retraction"]
        self.assertEqual(len(retractions), 2)

    def test_about_reports_the_write_capabilities_and_author(self):
        answer = self.call("about")
        self.assertIn("propose_put", answer["capabilities"])
        self.assertEqual(answer["author"], "fake:agent")
        listed = self.server.handle({"jsonrpc": "2.0", "id": 1,
                                     "method": "tools/list"})
        names = {t["name"] for t in listed["result"]["tools"]}
        self.assertIn("put", names)


class TestReviewWorkflow(WritableHarness):
    """Claims merge, acceptance is policy: trusted authors ∩ verified
    signatures, with retraction sticky per author."""

    def setUp(self):
        super().setUp()
        self.write("pet")
        self.write("cat", ["pet"])

    def test_endorse_then_review_accepts_under_trust(self):
        endorsed = self.call("endorse", {"sub": "cat", "sup": "pet"})
        self.assertEqual(endorsed["subject"],
                         {"claim": "below", "sub": "cat", "sup": "pet"})
        self.assertTrue(endorsed["provenance_root"])
        review = self.call("review", {"sub": "cat", "sup": "pet",
                                      "trust": ["fake:agent"]})
        types = sorted(r["type"] for r in review["records"])
        self.assertEqual(types, ["assertion", "endorsement"])
        self.assertTrue(all(r["verified"] for r in review["records"]))
        self.assertEqual(review["standing"], {"fake:agent": "stands"})
        self.assertTrue(review["accepted"])
        self.assertEqual(review["accepted_by"], ["fake:agent"])

    def test_retraction_is_sticky_and_touches_no_knowledge(self):
        self.call("retract", {"sub": "cat", "sup": "pet"})
        review = self.call("review", {"sub": "cat", "sup": "pet",
                                      "trust": ["fake:agent"]})
        self.assertEqual(review["standing"], {"fake:agent": "retracted"})
        self.assertFalse(review["accepted"])
        still = self.call("query", {"terms": ["pet"]})
        self.assertIn("cat", still["items"])      # a speech act, not remove

    def test_unverified_signatures_never_count_toward_standing(self):
        import hashlib as _hl

        from ontodag.provenance import ProvenanceStore, below_subject

        class Mallory:
            address = "fake:mallory"

            @staticmethod
            def sign(data):
                return _hl.sha256(b"not-really" + data).hexdigest()

        forger = ProvenanceStore(self.prov_store, signer=Mallory())
        forger.assert_claim(below_subject("cat", "pet"), basis="x")
        forger.commit()
        review = self.call("review", {"sub": "cat", "sup": "pet",
                                      "trust": ["fake:mallory"]})
        bad = next(r for r in review["records"]
                   if r["author"] == "fake:mallory")
        self.assertFalse(bad["verified"])          # listed, but never
        self.assertNotIn("fake:mallory", review["standing"])  # standing
        self.assertFalse(review["accepted"])

    def test_existence_claims_and_canonical_echo(self):
        review = self.call("review", {"sub": "pet"})
        self.assertEqual(review["subject"],
                         {"claim": "below", "sub": "pet", "sup": "*"})
        self.assertEqual([r["type"] for r in review["records"]],
                         ["assertion"])

    def test_review_works_read_only_but_endorse_does_not(self):
        reader = AgentSurface("swarm:t", backend=self.backend,
                              verifier=self.fake_verify)   # not writable
        server = MCPServer(reader)
        response = server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "review",
                       "arguments": {"sub": "cat", "sup": "pet"}}})
        answer = response["result"]["structuredContent"]
        self.assertEqual(answer["standing"], {"fake:agent": "stands"})
        refused = server.handle({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "endorse", "arguments": {"sub": "cat"}}})
        self.assertTrue(refused["result"]["isError"])
        self.assertIn("--write", refused["result"]["content"][0]["text"])
        listed = server.handle({"jsonrpc": "2.0", "id": 3,
                                "method": "tools/list"})
        names = {t["name"] for t in listed["result"]["tools"]}
        self.assertIn("review", names)
        self.assertNotIn("endorse", names)


class TestWriteGating(SurfaceHarness):
    def test_review_needs_a_provenance_sibling(self):
        text = self.call("review", {"sub": "pet"}, expect_error=True)
        self.assertIn("provenance sibling", text)

    def test_read_only_surface_hides_and_refuses_write_tools(self):
        listed = self.server.handle({"jsonrpc": "2.0", "id": 1,
                                     "method": "tools/list"})
        names = {t["name"] for t in listed["result"]["tools"]}
        self.assertNotIn("put", names)
        text = self.call("put", {"item": "x", "proposal": "p"},
                         expect_error=True)
        self.assertIn("--write", text)

    def test_file_stores_refuse_write_mode(self):
        with self.assertRaises(ValueError) as ctx:
            AgentSurface(self.store, writable=True)
        self.assertIn("odag put", str(ctx.exception))

    def test_write_mode_needs_a_signer(self):
        from recordstore import MemoryBytesStore, RecordStore

        from ontodag.__main__ import SwarmBackend
        backend = SwarmBackend(
            "t",
            store_factory=lambda: RecordStore(MemoryBytesStore()),
            prov_store_factory=lambda: RecordStore(MemoryBytesStore()))
        env = os.environ.pop("BEE_SIGNER", None)
        home = os.environ.get("ONTODAG_HOME")
        os.environ["ONTODAG_HOME"] = self.tmp.name   # empty config
        try:
            with self.assertRaises(ValueError) as ctx:
                AgentSurface("swarm:t", backend=backend, writable=True)
            self.assertIn("signer", str(ctx.exception))
        finally:
            if env is not None:
                os.environ["BEE_SIGNER"] = env
            if home is not None:
                os.environ["ONTODAG_HOME"] = home
            else:
                os.environ.pop("ONTODAG_HOME", None)


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
