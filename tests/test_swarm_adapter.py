"""Tests for SwarmOntoDAG — OntoDAG persisted through a RecordStore.

Follows the schema in docs/SWARM_DESIGN.md §3 (one record per node, keyed by
name: up/down sorted, count, payload, meta) and the usage pattern in §6
(hydrate into memory once, operate in RAM, sync through put/commit).

Properties:

  S1  Roundtrip      - commit then rehydrate reproduces the exact graph
  S2  Canonical root - same graph content => same root, regardless of the
                       operation history that produced it; commit is
                       idempotent when nothing changed
  S3  Incremental    - a commit only stages records that actually changed
  S4  Invariants     - a rehydrated graph is acyclic, transitively reduced,
                       and has consistent descendant counts
  S5  Convergence    - merge + commit from either side yields the same root
                       (the CRDT precondition from SWARM_DESIGN §5)
  S6  Node extras    - payload/meta survive the roundtrip
  S7  Removal        - removed nodes disappear from the store, not just RAM
"""

import unittest

from ontodag.dag import Item
from ontodag.swarm_adapter import SwarmOntoDAG
from recordstore import MemoryChunkStore, RecordStore


def reach(node):
    """All nodes strictly reachable from `node` (independent of dag code)."""
    seen = set()
    frontier = list(node.neighbors)
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        frontier.extend(current.neighbors)
    return seen


def edge_set(dag):
    return frozenset(
        (parent.name, child.name)
        for parent in dag.nodes.values()
        for child in parent.neighbors
    )


def counts(dag):
    return {name: node.descendant_count for name, node in dag.nodes.items()}


class RecordingStore:
    """RecordStore wrapper that counts staged puts/deletes (for S3)."""

    def __init__(self, store):
        self._store = store
        self.puts = 0
        self.deletes = 0

    def put(self, key, value):
        self.puts += 1
        self._store.put(key, value)

    def delete(self, key):
        self.deletes += 1
        self._store.delete(key)

    def __getattr__(self, name):
        return getattr(self._store, name)


def fresh_store():
    return RecordStore(MemoryChunkStore())


def build(dag_or_store, puts):
    dag = dag_or_store if isinstance(dag_or_store, SwarmOntoDAG) \
        else SwarmOntoDAG(dag_or_store)
    for name, supers in puts:
        dag.put(Item(name), [Item(s) for s in supers])
    return dag


VEHICLES = [
    ("vehicle", []), ("electric", []),
    ("car", ["vehicle"]), ("bike", ["vehicle"]),
    ("ev", ["car", "electric"]), ("ebike", ["bike", "electric"]),
]


class TestRoundtrip(unittest.TestCase):
    def test_commit_and_rehydrate(self):
        chunks = MemoryChunkStore()
        dag = build(RecordStore(chunks), VEHICLES)
        root = dag.commit()
        self.assertIsNotNone(root)

        again = SwarmOntoDAG(RecordStore.at(root, chunks))
        self.assertEqual(edge_set(dag), edge_set(again))
        self.assertEqual(counts(dag), counts(again))
        self.assertEqual(sorted(dag.nodes), sorted(again.nodes))

    def test_query_after_rehydrate(self):
        chunks = MemoryChunkStore()
        dag = build(RecordStore(chunks), VEHICLES)
        root = dag.commit()

        again = SwarmOntoDAG(RecordStore.at(root, chunks))
        result = again.get([again.nodes["vehicle"], again.nodes["electric"]])
        self.assertEqual({"ev", "ebike"}, {item.name for item in result})

    def test_empty_dag_roundtrip(self):
        chunks = MemoryChunkStore()
        dag = SwarmOntoDAG(RecordStore(chunks))
        root = dag.commit()  # just the root node record
        again = SwarmOntoDAG(RecordStore.at(root, chunks))
        self.assertEqual([again.root.name], list(again.nodes))


class TestCanonicalRoot(unittest.TestCase):
    def test_history_independent_root(self):
        # Same final content through different histories: one direct build,
        # one that adds and removes an extra node along the way.
        direct = build(fresh_store(), VEHICLES)
        churned = build(fresh_store(), VEHICLES[:3])
        churned.put(Item("ephemeral"), [Item("car")])
        churned.commit()
        churned.remove(churned.nodes["ephemeral"])
        build(churned, VEHICLES[3:])
        self.assertEqual(direct.commit(), churned.commit())

    def test_put_order_independent_root(self):
        ab = build(fresh_store(), [("A", []), ("B", ["A"]), ("X", ["A", "B"])])
        ba = build(fresh_store(), [("A", []), ("B", ["A"]), ("X", ["B", "A"])])
        self.assertEqual(ab.commit(), ba.commit())

    def test_commit_idempotent(self):
        dag = build(fresh_store(), VEHICLES)
        first = dag.commit()
        second = dag.commit()  # nothing changed in between
        self.assertEqual(first, second)


class TestIncrementalSync(unittest.TestCase):
    def test_unchanged_records_not_restaged(self):
        recording = RecordingStore(fresh_store())
        dag = build(recording, VEHICLES)
        dag.commit()

        baseline = recording.puts
        # A leaf under a leaf: touches ebike (down), the new node, and the
        # counts of ebike's ancestors — but never e.g. the 'car' subtree.
        dag.put(Item("cargo-ebike"), [Item("ebike")])
        dag.commit()

        staged = recording.puts - baseline
        self.assertLess(
            staged, len(dag.nodes),
            "a small change must not restage every record",
        )
        self.assertGreaterEqual(staged, 2)  # new node + its parent at least


class TestRehydratedInvariants(unittest.TestCase):
    def test_acyclic_reduced_consistent(self):
        chunks = MemoryChunkStore()
        dag = build(RecordStore(chunks), VEHICLES)
        root = dag.commit()
        again = SwarmOntoDAG(RecordStore.at(root, chunks))

        for node in again.nodes.values():
            self.assertNotIn(node, reach(node), "cycle after rehydration")
            self.assertEqual(
                len(reach(node)), node.descendant_count,
                f"stale count for {node.name!r} after rehydration",
            )
        for u in again.nodes.values():
            for v in u.neighbors:
                for w in u.neighbors:
                    if w is not v:
                        self.assertNotIn(
                            v, reach(w) | {w},
                            f"redundant edge {u.name}->{v.name} after rehydration",
                        )

    def test_mutation_after_rehydrate(self):
        chunks = MemoryChunkStore()
        pointer_root = build(RecordStore(chunks), VEHICLES).commit()

        again = SwarmOntoDAG(RecordStore.at(pointer_root, chunks))
        with self.assertRaises(ValueError):  # invariants still enforced
            again.put(Item("vehicle"), [Item("ev")])  # would create a cycle


class TestConvergence(unittest.TestCase):
    def _one(self, store):
        return build(store, [
            ("vehicle", []), ("electric", []),
            ("car", ["vehicle"]), ("ev", ["car", "electric"]),
        ])

    def _two(self, store):
        return build(store, [
            ("vehicle", []), ("bike", ["vehicle"]),
            ("electric", []), ("ebike", ["bike", "electric"]),
        ])

    def test_merge_converges_to_same_root(self):
        left = self._one(fresh_store())
        left.merge(self._two(fresh_store()))
        right = self._two(fresh_store())
        right.merge(self._one(fresh_store()))
        self.assertEqual(left.commit(), right.commit())

    def test_merge_idempotent_root(self):
        dag = self._one(fresh_store())
        first = dag.commit()
        dag.merge(self._one(fresh_store()))
        self.assertEqual(first, dag.commit())


class TestNodeExtras(unittest.TestCase):
    def test_payload_meta_roundtrip(self):
        chunks = MemoryChunkStore()
        dag = SwarmOntoDAG(RecordStore(chunks))
        dag.put(Item("photos"), [])
        dag.put(
            Item("IMG_1234"), [Item("photos")],
            payload="deadbeef" * 8,
            meta={"Content-Type": "image/jpeg"},
        )
        root = dag.commit()

        again = SwarmOntoDAG(RecordStore.at(root, chunks))
        record = again.store.get("IMG_1234")
        self.assertEqual(record["payload"], "deadbeef" * 8)
        self.assertEqual(record["meta"], {"Content-Type": "image/jpeg"})
        # extras survive a second, unrelated commit cycle
        again2 = SwarmOntoDAG(RecordStore(chunks, root=root))
        again2.put(Item("unrelated"), [])
        again3 = SwarmOntoDAG(RecordStore.at(again2.commit(), chunks))
        self.assertEqual(again3.store.get("IMG_1234")["payload"], "deadbeef" * 8)


class TestRemoval(unittest.TestCase):
    def test_remove_persists(self):
        chunks = MemoryChunkStore()
        dag = build(RecordStore(chunks), VEHICLES)
        dag.commit()
        dag.remove(dag.nodes["ev"])
        root = dag.commit()

        again = SwarmOntoDAG(RecordStore.at(root, chunks))
        self.assertNotIn("ev", again.nodes)
        self.assertFalse(again.store.contains("ev"))
        # and the root matches a store that never saw 'ev' at all
        never = build(fresh_store(), [p for p in VEHICLES if p[0] != "ev"])
        self.assertEqual(root, never.commit())


if __name__ == "__main__":
    unittest.main()
