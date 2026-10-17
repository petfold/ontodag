"""Knowledge ids (ontodag.knowledge): the Swarm reference of a store's
canonical `.od` text. Equal knowledge has one id however it was built and
whatever keeps it; the id is also where the published text is fetched, and
fetched bytes are checked against it before anything is read."""
import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from ontodag import knowledge, native
from ontodag.dag import OntoDAG
from ontodag.packs import pack_dag

HAVE_SWARMFS = importlib.util.find_spec("swarmfs") is not None

# Pinned like GOLDEN_ROOTS in test_packs.py, but they name the text, not a
# store: they move when a pack's content or the registry's spelling moves.
GOLDEN_KNOWLEDGE_IDS = {
    "prelude": "cb0c8b182d701625e079f84f32c2e03cd033f4a458e242148d62edfc10f16e8b",
    "crypto-core": "6a01b494dfe568d165cc74691f7cf26d29e6f8f3765bb0e2d7d4a38ae27b5c4c",
    "fiat-iso4217": "c0d8bc2598355060c234542144a01444f8b401af04003fbb93c10d88a46b4a2a",
}


class FakeSwarm:
    """A bytes store that addresses as Swarm does, offline."""

    def __init__(self):
        self.blobs = {}

    def put(self, data):
        from swarmfs.splitter import content_address
        ref = content_address(data).hex()
        self.blobs[ref] = data
        return ref

    def get(self, ref):
        return self.blobs[ref]


def _trip():
    dag = OntoDAG()
    dag.put("Travel", [])
    dag.put("Japan", [])
    dag.put("flight", ["Travel", "Japan"])
    return dag


@unittest.skipUnless(HAVE_SWARMFS, "knowledge ids need the swarm extra (Keccak)")
class TestKnowledgeId(unittest.TestCase):

    def test_equal_knowledge_one_id_whatever_the_build(self):
        other = OntoDAG()
        other.put("Japan", [])
        other.put("flight", [])
        other.put("Travel", [])
        other.put("flight", ["Japan"])
        other.put("flight", ["Travel"])
        self.assertEqual(knowledge.knowledge_id(_trip()), knowledge.knowledge_id(other))
        other.put("hotel", ["Travel"])
        self.assertNotEqual(knowledge.knowledge_id(_trip()), knowledge.knowledge_id(other))

    def test_it_is_the_swarm_reference_of_the_canonical_text(self):
        from swarmfs.splitter import content_address
        dag = _trip()
        self.assertEqual(knowledge.knowledge_id(dag),
                         content_address(native.dumps(dag).encode()).hex())

    def test_whatever_keeps_the_store(self):
        # a file and a record store keep the trip; the roots differ, the id not
        from ontodag.eager import EagerOntoDAG
        from recordstore import MemoryBytesStore, RecordStore
        eager = EagerOntoDAG(RecordStore(MemoryBytesStore()))
        eager.merge(_trip())
        root = eager.commit()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "trip.od")
            native.save(_trip(), path)
            from_file = native.load(path)
        ids = {knowledge.knowledge_id(x) for x in (_trip(), eager, from_file)}
        self.assertEqual(len(ids), 1)
        self.assertNotEqual(root, ids.pop())

    def test_shipped_packs_are_pinned(self):
        for name, expected in GOLDEN_KNOWLEDGE_IDS.items():
            self.assertEqual(knowledge.knowledge_id(pack_dag(name)), expected, name)


@unittest.skipUnless(HAVE_SWARMFS, "knowledge ids need the swarm extra (Keccak)")
class TestPublishAndFetch(unittest.TestCase):

    def test_round_trip(self):
        swarm = FakeSwarm()
        ref = knowledge.publish(_trip(), bytes_store=swarm)
        back = knowledge.fetch(knowledge.PREFIX + ref, bytes_store=swarm)
        self.assertEqual(knowledge.knowledge_id(back), ref)
        self.assertTrue(back.is_below("flight", "Japan"))

    def test_content_that_is_not_the_id_is_refused(self):
        swarm = FakeSwarm()
        ref = knowledge.publish(_trip(), bytes_store=swarm)
        swarm.blobs[ref] = swarm.blobs[ref].replace(b"Japan", b"Korea")
        with self.assertRaisesRegex(ValueError, "another reference"):
            knowledge.fetch(ref, bytes_store=swarm)

    def test_a_node_that_stores_it_elsewhere_is_refused(self):
        class Elsewhere(FakeSwarm):
            def put(self, data):
                return "0" * 64
        with self.assertRaisesRegex(ValueError, "not its knowledge id"):
            knowledge.publish(_trip(), bytes_store=Elsewhere())

    def test_a_malformed_id_is_refused(self):
        for bad in ("knowledge:abc", "x" * 64):
            with self.assertRaisesRegex(ValueError, "64 hex"):
                knowledge.fetch(bad, bytes_store=FakeSwarm())


@unittest.skipUnless(HAVE_SWARMFS, "knowledge ids need the swarm extra (Keccak)")
class TestCli(unittest.TestCase):
    """`status` says the id; `merge knowledge:ID` adopts by it, after
    `--diff` previews it, and `publish` refuses an encrypted store."""

    def _run(self, argv, path):
        from ontodag import __main__ as cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.dispatch(argv, cli.Session(path))
        return code, buf.getvalue()

    def test_status_says_the_knowledge_id(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "trip.od")
            native.save(_trip(), path)
            _, out = self._run(["status"], path)
            fields = dict(line.split(" = ", 1) for line in out.splitlines() if " = " in line)
            self.assertEqual(fields["knowledge"], knowledge.knowledge_id(_trip()))

    def test_merge_adopts_by_knowledge_id(self):
        swarm = FakeSwarm()
        ref = knowledge.publish(_trip(), bytes_store=swarm)
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(knowledge, "_bytes_store", return_value=swarm):
            path = os.path.join(d, "mine.od")
            code, out = self._run(["merge", "--diff", f"knowledge:{ref}"], path)
            self.assertEqual(code, 0)
            self.assertIn("flight", out)                   # previewed, not merged
            self.assertFalse(os.path.exists(path) and "flight" in open(path).read())
            self.assertEqual(self._run(["merge", f"knowledge:{ref}"], path)[0], 0)
            self.assertEqual(knowledge.knowledge_id(native.load(path)), ref)
