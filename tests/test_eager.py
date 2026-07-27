"""Tests for EagerOntoDAG — OntoDAG persisted through a RecordStore.

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
from ontodag.eager import EagerOntoDAG
from recordstore import MemoryBytesStore, RecordStore


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
    return RecordStore(MemoryBytesStore())


def build(dag_or_store, puts):
    dag = dag_or_store if isinstance(dag_or_store, EagerOntoDAG) \
        else EagerOntoDAG(dag_or_store)
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
        blobs = MemoryBytesStore()
        dag = build(RecordStore(blobs), VEHICLES)
        root = dag.commit()
        self.assertIsNotNone(root)

        again = EagerOntoDAG(RecordStore.at(root, blobs))
        self.assertEqual(edge_set(dag), edge_set(again))
        self.assertEqual(counts(dag), counts(again))
        self.assertEqual(sorted(dag.nodes), sorted(again.nodes))

    def test_query_after_rehydrate(self):
        blobs = MemoryBytesStore()
        dag = build(RecordStore(blobs), VEHICLES)
        root = dag.commit()

        again = EagerOntoDAG(RecordStore.at(root, blobs))
        result = again.get([again.nodes["vehicle"], again.nodes["electric"]])
        self.assertEqual({"ev", "ebike"}, {item.name for item in result})

    def test_query_after_rehydrate_with_fresh_items(self):
        # The natural rehydrated-store usage: the caller has no live node
        # objects, only names. Regression for the 2026-07-19 real-node smoke,
        # where fresh Items silently returned the empty set.
        blobs = MemoryBytesStore()
        dag = build(RecordStore(blobs), VEHICLES)
        root = dag.commit()

        again = EagerOntoDAG(RecordStore.at(root, blobs))
        result = again.get([Item("vehicle"), Item("electric")])
        self.assertEqual({"ev", "ebike"}, {item.name for item in result})

    def test_empty_dag_roundtrip(self):
        blobs = MemoryBytesStore()
        dag = EagerOntoDAG(RecordStore(blobs))
        root = dag.commit()  # just the root node record
        again = EagerOntoDAG(RecordStore.at(root, blobs))
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
        blobs = MemoryBytesStore()
        dag = build(RecordStore(blobs), VEHICLES)
        root = dag.commit()
        again = EagerOntoDAG(RecordStore.at(root, blobs))

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
        blobs = MemoryBytesStore()
        pointer_root = build(RecordStore(blobs), VEHICLES).commit()

        again = EagerOntoDAG(RecordStore.at(pointer_root, blobs))
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
        blobs = MemoryBytesStore()
        dag = EagerOntoDAG(RecordStore(blobs))
        dag.put(Item("photos"), [])
        dag.put(
            Item("IMG_1234"), [Item("photos")],
            payload="deadbeef" * 8,
            meta={"Content-Type": "image/jpeg"},
        )
        root = dag.commit()

        again = EagerOntoDAG(RecordStore.at(root, blobs))
        record = again.store.get("IMG_1234")
        self.assertEqual(record["payload"], "deadbeef" * 8)
        self.assertEqual(record["meta"], {"Content-Type": "image/jpeg"})
        # extras survive a second, unrelated commit cycle
        again2 = EagerOntoDAG(RecordStore(blobs, root=root))
        again2.put(Item("unrelated"), [])
        again3 = EagerOntoDAG(RecordStore.at(again2.commit(), blobs))
        self.assertEqual(again3.store.get("IMG_1234")["payload"], "deadbeef" * 8)

    def test_meta_lives_on_item_metadata(self):
        # meta is Item.metadata (one source of truth), and in-place edits
        # after a commit are still detected as changes by the next commit
        blobs = MemoryBytesStore()
        dag = EagerOntoDAG(RecordStore(blobs))
        dag.put("photos", [])
        dag.put("IMG_1234", ["photos"], meta={"label": "sunset.jpg"})
        self.assertEqual(dag.nodes["IMG_1234"].metadata, {"label": "sunset.jpg"})
        root = dag.commit()

        editable = EagerOntoDAG(RecordStore(blobs, root=root))
        editable.nodes["IMG_1234"].metadata["label"] = "dawn.jpg"
        root2 = editable.commit()
        self.assertNotEqual(root, root2)

        again = EagerOntoDAG(RecordStore.at(root2, blobs))
        self.assertEqual(again.nodes["IMG_1234"].metadata,
                         {"label": "dawn.jpg"})
        self.assertEqual(again.store.get("IMG_1234")["meta"],
                         {"label": "dawn.jpg"})

    def test_string_api_with_extras(self):
        # Plain strings work at the adapter boundary too, including the
        # payload/meta bookkeeping keyed by name.
        blobs = MemoryBytesStore()
        dag = EagerOntoDAG(RecordStore(blobs))
        dag.put("photos", [])
        dag.put("IMG_1234", ["photos"], payload="cafebabe" * 8,
                meta={"Content-Type": "image/png"})
        root = dag.commit()

        again = EagerOntoDAG(RecordStore.at(root, blobs))
        self.assertEqual(again.store.get("IMG_1234")["payload"], "cafebabe" * 8)
        self.assertEqual({"IMG_1234"},
                         {i.name for i in again.get(["photos"])})

        editable = EagerOntoDAG(RecordStore(blobs, root=root))
        editable.remove("IMG_1234")
        self.assertNotIn("IMG_1234", editable._payloads)
        self.assertNotIn("IMG_1234", editable.nodes)


class TestRemoval(unittest.TestCase):
    def test_remove_persists(self):
        blobs = MemoryBytesStore()
        dag = build(RecordStore(blobs), VEHICLES)
        dag.commit()
        dag.remove(dag.nodes["ev"])
        root = dag.commit()

        again = EagerOntoDAG(RecordStore.at(root, blobs))
        self.assertNotIn("ev", again.nodes)
        self.assertFalse(again.store.contains("ev"))
        # and the root matches a store that never saw 'ev' at all
        never = build(fresh_store(), [p for p in VEHICLES if p[0] != "ev"])
        self.assertEqual(root, never.commit())


class CountingStore:
    """Wrapper that counts read calls, and can hide `items()` from the adapter.

    `items()` batches value-blob fetches; the point of the counts is that a
    cold hydrate goes through *one* batched call rather than one `get` per
    node, while a store lacking `items` still hydrates correctly.
    """

    def __init__(self, store, batched=True):
        self._store = store
        self._batched = batched
        self.gets = 0
        self.items_calls = 0

    def get(self, key):
        self.gets += 1
        return self._store.get(key)

    def keys(self, prefix=""):
        return self._store.keys(prefix)

    def __getattr__(self, name):
        if name == "items" and not self._batched:
            raise AttributeError(name)      # look like a store without items()
        if name == "items":
            def items(prefix=""):
                self.items_calls += 1
                return self._store.items(prefix)
            return items
        return getattr(self._store, name)


class TestBatchedHydration(unittest.TestCase):
    def test_hydrate_uses_items_when_available(self):
        blobs = MemoryBytesStore()
        root = build(RecordStore(blobs), VEHICLES).commit()

        store = CountingStore(RecordStore.at(root, blobs))
        dag = EagerOntoDAG(store)
        self.assertEqual(1, store.items_calls)
        self.assertEqual(0, store.gets)        # no per-node round trips
        self.assertEqual(6, len(dag.nodes) - 1)  # minus the root '*'

    def test_hydrate_falls_back_to_keys_and_get(self):
        blobs = MemoryBytesStore()
        root = build(RecordStore(blobs), VEHICLES).commit()

        store = CountingStore(RecordStore.at(root, blobs), batched=False)
        dag = EagerOntoDAG(store)
        self.assertEqual(0, store.items_calls)
        self.assertEqual(7, store.gets)        # one per record, root included
        self.assertEqual({"ev"}, {i.name for i in dag.get(["car", "electric"])})

    def test_both_paths_hydrate_identically(self):
        blobs = MemoryBytesStore()
        root = build(RecordStore(blobs), VEHICLES).commit()

        batched = EagerOntoDAG(CountingStore(RecordStore.at(root, blobs)))
        serial = EagerOntoDAG(
            CountingStore(RecordStore.at(root, blobs), batched=False))
        self.assertEqual(edge_set(serial), edge_set(batched))
        self.assertEqual(counts(serial), counts(batched))
        self.assertEqual(serial._synced, batched._synced)
        # and both re-commit to the root they came from
        self.assertEqual(root, EagerOntoDAG(
            RecordStore(blobs, root=root)).commit())


if __name__ == "__main__":
    unittest.main()
