"""`ontodag.migrate` carries what a node carries (review, 2026-10-09).

The migration replays a store through `put` to re-canonicalize its names.
Until 2026-10-09 the replay read names and parents only: a native store's
`#:meta` lines and a record's `meta` and `payload` were dropped, although
the module calls a migration "a pure rename"."""

import os
import tempfile
import unittest

from recordstore import MemoryBytesStore, RecordStore

from ontodag import migrate, native
from ontodag.dag import OntoDAG
from ontodag.eager import EagerOntoDAG


class TestMigrationKeepsWhatNodesCarry(unittest.TestCase):
    def test_native_metadata_survives(self):
        dag = OntoDAG()
        dag.put("pet", [])
        dag.put("cat", ["pet"])
        dag.nodes["cat"].metadata["label"] = "Kitty"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "store.od")
            native.save(dag, path)
            migrate.migrate_native(path)
            again = native.load(path)
        self.assertEqual(again.nodes["cat"].metadata, {"label": "Kitty"})
        self.assertEqual({p.name for p in again.nodes["cat"].parents}, {"pet"})

    def test_record_meta_and_payload_survive(self):
        old = EagerOntoDAG(RecordStore(MemoryBytesStore()))
        old.put("pet", [])
        old.put("cat", ["pet"], payload="ref123", meta={"label": "Kitty"})
        old_root = old.commit()
        new_store = RecordStore(MemoryBytesStore())
        new_root = migrate.migrate_record_store(
            RecordStore.at(old_root, old.store.blobs), new_store)
        record = RecordStore.at(new_root, new_store.blobs).get("cat")
        self.assertEqual(record.get("payload"), "ref123")
        self.assertEqual(record.get("meta"), {"label": "Kitty"})
        self.assertEqual(record.get("up"), ["pet"])


class TestMigrationWritesTheseBytes(unittest.TestCase):
    """What `migrate` writes for one legacy store, pinned byte for byte
    (tests/fixtures/make_migrate.py): old spellings, metadata, an item a
    merge left under two overlapping values, a graph-kind compound stored
    folded, a role term naming a cell. A change here is a change to a
    registry minor's migrate step (CONTRACT.md G8): regenerate the fixture
    with it, deliberately, and read the diff of migrate-out.od."""

    def _migrated(self, source):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "store.od")
            shutil.copy(source, path)
            migrate.migrate_native(path)
            with open(path, "rb") as f:
                return f.read()

    def test_the_bytes_are_the_recorded_ones(self):
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
        with open(os.path.join(here, "migrate-out.od"), "rb") as f:
            expected = f.read()
        self.assertEqual(self._migrated(os.path.join(here, "migrate-in.od")), expected)

    def test_migrating_the_result_changes_nothing(self):
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
        out = os.path.join(here, "migrate-out.od")
        with open(out, "rb") as f:
            expected = f.read()
        self.assertEqual(self._migrated(out), expected)


if __name__ == "__main__":
    unittest.main()


class TestMigrationReadsItsVocabularyFirst(unittest.TestCase):
    def test_a_store_using_a_pack_s_units_migrates(self):
        # A value was filed before the declaration of its unit when it
        # sorted first (`price(...BTC)` before `unit-family(BTC)`), and the
        # migration stopped at "unknown unit" (until 2026-10-09).
        from ontodag import packs, prelude
        dag = OntoDAG()
        prelude.apply(dag)
        dag.merge(packs.pack_dag("crypto-core"))
        dag.put("price", ["linear-dimension"])
        dag.put("coffee", ["price(5000sat)"])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "store.od")
            native.save(dag, path)
            migrate.migrate_native(path)
            again = native.load(path)
        self.assertEqual(native.dumps(again), native.dumps(dag))
        self.assertTrue(again.is_below("coffee", "price(..1/1000BTC)"))

    def test_a_store_a_merge_made_migrates(self):
        # A merge keeps what an author would be refused; so must the
        # migration's replay, or the store cannot be migrated (until
        # 2026-10-09 it stopped at "cannot sit under both").
        from ontodag import prelude
        peers = []
        for value in ("mass(1kg)", "mass(2kg)"):
            peer = OntoDAG()
            prelude.apply(peer)
            peer.put("crate", [value])
            peers.append(peer)
        dag = OntoDAG()
        prelude.apply(dag)
        for peer in peers:
            dag.merge(peer)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "store.od")
            native.save(dag, path)
            migrate.migrate_native(path)
            again = native.load(path)
        self.assertEqual({p.name for p in again.nodes["crate"].parents},
                         {"mass(1kg)", "mass(2kg)"})
