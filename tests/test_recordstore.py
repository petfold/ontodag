"""Tests for recordstore.

The properties tested here are the ones the OntoDAG-on-Swarm design
depends on:

  R1  Roundtrip & staging      - put/get/delete with read-your-writes
  R2  Canonical roots          - same content => same root, regardless of
                                 insertion order or history (CRDT precondition)
  R3  Snapshot isolation       - a reader pinned to a root is unaffected by
                                 later commits; commits are all-or-nothing
  R4  Structural sharing       - a small change writes O(depth) chunks,
                                 not O(dataset)
  R5  Prefix iteration         - sorted, namespace-style key listing,
                                 staged overlay included
  R6  No aliasing              - mutating a returned record never mutates
                                 the store
  R7  Pointer persistence      - FilePointer survives process restart and
                                 is updated atomically on commit
"""

import os
import tempfile
import unittest

from recordstore import FilePointer, MemoryChunkStore, MemoryPointer, RecordStore


def make(chunks=None, pointer=None):
    return RecordStore(chunks or MemoryChunkStore(), pointer=pointer)


class TestRoundtrip(unittest.TestCase):
    def test_put_get_commit_get(self):
        store = MemoryChunkStore()
        rs = RecordStore(store)
        rec = {"up": ["vehicle"], "down": [], "count": 0}
        rs.put("car", rec)
        self.assertEqual(rs.get("car"), rec)          # read-your-writes
        root = rs.commit()
        self.assertIsNotNone(root)
        again = RecordStore.at(root, store)
        self.assertEqual(again.get("car"), rec)

    def test_delete(self):
        rs = make()
        rs.put("a", 1)
        rs.put("ab", 2)
        rs.commit()
        rs.delete("a")
        self.assertFalse(rs.contains("a"))
        self.assertTrue(rs.contains("ab"))
        rs.commit()
        self.assertFalse(rs.contains("a"))
        with self.assertRaises(KeyError):
            rs.get("a")
        with self.assertRaises(KeyError):
            rs.delete("never-existed")

    def test_empty_and_missing(self):
        rs = make()
        with self.assertRaises(KeyError):
            rs.get("nothing")
        with self.assertRaises(ValueError):
            rs.put("", 1)
        self.assertIsNone(rs.commit())               # empty commit, empty store


class TestCanonicalRoots(unittest.TestCase):
    RECORDS = {f"ns:key{i:03d}": {"n": i, "tags": ["a", "b"]} for i in range(60)}

    def _root_via(self, order, extra_churn=False):
        store = MemoryChunkStore()
        rs = RecordStore(store)
        for k in order:
            rs.put(k, self.RECORDS[k])
            rs.commit()                              # one commit per key
        if extra_churn:                              # divergent history
            rs.put("ephemeral", {"x": 1})
            rs.commit()
            rs.delete("ephemeral")
            rs.commit()
        return rs.root

    def test_order_and_history_independent_root(self):
        keys = list(self.RECORDS)
        forward = self._root_via(keys)
        backward = self._root_via(list(reversed(keys)))
        churned = self._root_via(sorted(keys, key=hash), extra_churn=True)
        self.assertEqual(forward, backward)
        self.assertEqual(forward, churned)

    def test_batched_vs_incremental_same_root(self):
        keys = list(self.RECORDS)
        incremental = self._root_via(keys)
        store = MemoryChunkStore()
        rs = RecordStore(store)
        for k in keys:
            rs.put(k, self.RECORDS[k])
        batched = rs.commit()                        # single commit
        self.assertEqual(incremental, batched)


class TestSnapshotIsolation(unittest.TestCase):
    def test_reader_pinned_to_old_root(self):
        store = MemoryChunkStore()
        writer = RecordStore(store)
        writer.put("car", {"count": 1})
        root1 = writer.commit()
        reader = RecordStore.at(root1, store)

        writer.put("car", {"count": 2})
        writer.put("bike", {"count": 0})
        writer.commit()

        self.assertEqual(reader.get("car"), {"count": 1})
        self.assertFalse(reader.contains("bike"))
        self.assertEqual(list(reader.keys()), ["car"])

    def test_snapshot_is_readonly(self):
        store = MemoryChunkStore()
        rs = RecordStore(store)
        rs.put("a", 1)
        snap = RecordStore.at(rs.commit(), store)
        with self.assertRaises(TypeError):
            snap.put("b", 2)
        with self.assertRaises(TypeError):
            snap.commit()

    def test_pointer_moves_only_on_commit(self):
        ptr = MemoryPointer()
        rs = make(pointer=ptr)
        rs.put("a", 1)
        self.assertIsNone(ptr.get())                 # staged, not visible
        root = rs.commit()
        self.assertEqual(ptr.get(), root)


class TestStructuralSharing(unittest.TestCase):
    def test_small_update_writes_few_chunks(self):
        store = MemoryChunkStore()
        rs = RecordStore(store)
        for i in range(200):
            rs.put(f"node{i:04d}", {"payload": i})
        rs.commit()
        before = len(store)
        rs.put("node0042", {"payload": "changed"})
        rs.commit()
        added = len(store) - before
        # one value chunk + the rewritten trie path; must be far below 200
        self.assertLess(added, 12, f"update rewrote {added} chunks")


class TestPrefixIteration(unittest.TestCase):
    def test_sorted_namespace_listing_with_overlay(self):
        rs = make()
        for k in ["veh:car", "veh:bike", "food:apple", "veh:boat"]:
            rs.put(k, {})
        rs.commit()
        rs.put("veh:van", {})                        # staged add
        rs.delete("veh:bike")                        # staged delete
        self.assertEqual(list(rs.keys("veh:")),
                         ["veh:boat", "veh:car", "veh:van"])
        self.assertEqual(list(rs.keys("food:")), ["food:apple"])
        self.assertEqual(list(rs.keys("nope:")), [])


class TestFilePointer(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._dir.name, "root")

    def tearDown(self):
        self._dir.cleanup()

    def test_missing_file_reads_as_none(self):
        self.assertIsNone(FilePointer(self.path).get())

    def test_set_get_roundtrip(self):
        ptr = FilePointer(self.path)
        ptr.set("abc123")
        self.assertEqual(ptr.get(), "abc123")
        self.assertEqual(FilePointer(self.path).get(), "abc123")  # fresh instance

    def test_commit_persists_root_across_restart(self):
        store = MemoryChunkStore()
        rs = RecordStore(store, pointer=FilePointer(self.path))
        rs.put("car", {"up": ["vehicle"]})
        root = rs.commit()
        self.assertEqual(FilePointer(self.path).get(), root)
        # a fresh store + fresh pointer resumes at the committed root
        again = RecordStore(store, pointer=FilePointer(self.path))
        self.assertEqual(again.get("car"), {"up": ["vehicle"]})

    def test_second_commit_replaces_root_without_tmp_residue(self):
        store = MemoryChunkStore()
        rs = RecordStore(store, pointer=FilePointer(self.path))
        rs.put("a", 1)
        first = rs.commit()
        rs.put("b", 2)
        second = rs.commit()
        self.assertNotEqual(first, second)
        self.assertEqual(FilePointer(self.path).get(), second)
        self.assertFalse(os.path.exists(self.path + ".tmp"))


class TestNoAliasing(unittest.TestCase):
    def test_returned_records_are_detached(self):
        rs = make()
        original = {"up": ["a"], "meta": {"kind": "class"}}
        rs.put("x", original)
        original["up"].append("HACK")                # mutate after put
        self.assertEqual(rs.get("x")["up"], ["a"])
        fetched = rs.get("x")
        fetched["meta"]["kind"] = "instance"         # mutate a returned copy
        self.assertEqual(rs.get("x")["meta"]["kind"], "class")
        rs.commit()
        self.assertEqual(rs.get("x")["up"], ["a"])


if __name__ == "__main__":
    unittest.main()
