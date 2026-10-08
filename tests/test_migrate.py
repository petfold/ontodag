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


if __name__ == "__main__":
    unittest.main()
