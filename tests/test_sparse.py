"""SparseOntoDAG — writing back from a partially-loaded graph (ROADMAP
item "Writing back from a partially-loaded graph", closed 2026-07-31).

Two assertions carry the feature, mirroring the roadmap's own analysis:

  ORACLE   the sparse writer and an eager writer applying the SAME
           operations from the SAME base produce byte-identical roots —
           reduction, counts, contraction and dimension renormalization
           are all correct under partial residency (canonical roots make
           this one string comparison per scenario);
  LOCALITY writes fetch what they touch (ancestors + the cones the
           operation walks), never the store — and commit() stages only
           the resident diff, not a full record sweep.
"""

import random
import unittest

from ontodag.eager import EagerOntoDAG
from ontodag.lazy import LazyOntoDAG, SparseOntoDAG
from recordstore import MemoryBytesStore, RecordStore


class CountingStore:
    """Duck-typed RecordStore wrapper counting put/delete staging calls."""

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


def publish(puts):
    blobs = MemoryBytesStore()
    dag = EagerOntoDAG(RecordStore(blobs))
    for name, supers in puts:
        dag.put(name, list(supers))
    return dag.commit(), blobs


def broad_fixture(seed=7, tops=5, mids=40, leaves=400):
    rng = random.Random(seed)
    puts = [(f"t{i}", []) for i in range(tops)]
    for m in range(mids):
        puts.append((f"m{m}", rng.sample([f"t{i}" for i in range(tops)], 2)))
    for leaf in range(leaves):
        puts.append((f"x{leaf}",
                     rng.sample([f"m{m}" for m in range(mids)], 2)))
    return puts


def writers(base, blobs):
    """(sparse, eager) writers over the same blobs at the same base."""
    return (SparseOntoDAG(RecordStore(blobs, root=base)),
            EagerOntoDAG(RecordStore(blobs, root=base)))


class TestEagerOracle(unittest.TestCase):
    """Same ops, same base ⇒ same root — the whole correctness story."""

    def _both(self, base, blobs, operations):
        sparse, eager = writers(base, blobs)
        for op, *args in operations:
            getattr(sparse, op)(*args)
            getattr(eager, op)(*args)
        return sparse.commit(), eager.commit()

    def test_basic_puts_and_pruning(self):
        base, blobs = publish([("animal", []), ("pet", []),
                               ("dog", ["animal"])])
        sparse_root, eager_root = self._both(base, blobs, [
            ("put", "dog", ["pet"]),                 # extra parent
            ("put", "spaniel", ["dog"]),             # fresh leaf
            ("put", "spaniel", ["animal"]),          # redundant: must prune
            ("put", "cat", ["animal", "pet"]),
        ])
        self.assertEqual(sparse_root, eager_root)

    def test_remove_with_contraction(self):
        base, blobs = publish([("animal", []), ("dog", ["animal"]),
                               ("spaniel", ["dog"])])
        sparse_root, eager_root = self._both(base, blobs, [
            ("remove", "dog"),                       # spaniel reattaches
            ("put", "poodle", ["animal"]),
        ])
        self.assertEqual(sparse_root, eager_root)

    def test_dimensions_under_partial_residency(self):
        base, blobs = publish([("dimension", []),
                               ("linear-dimension", ["dimension"]),
                               ("weight", ["linear-dimension"]),
                               ("parcel", ["weight(..5kg)"])])
        sparse_root, eager_root = self._both(base, blobs, [
            ("put", "parcel", ["weight(3kg)"]),      # prunes via computed hop
            ("put", "flour-bag", ["weight(1.2kg)"]),
            ("remove", "weight(3kg)"),               # contraction restores
        ])
        self.assertEqual(sparse_root, eager_root)

    def test_randomized_operation_sequences(self):
        base_puts = broad_fixture(tops=4, mids=12, leaves=60)
        base, blobs = publish(base_puts)
        categories = [f"t{i}" for i in range(4)] + [f"m{m}" for m in range(12)]
        for seed in range(4):
            rng = random.Random(seed)
            operations = []
            for i in range(25):
                kind = rng.random()
                if kind < 0.7:
                    operations.append(
                        ("put", f"new-{seed}-{i}",
                         rng.sample(categories, rng.randint(1, 3))))
                elif kind < 0.85 and i > 3:
                    operations.append(("put", f"new-{seed}-{rng.randrange(i)}",
                                       rng.sample(categories, 1)))
                else:
                    operations.append(("remove", f"x{rng.randrange(60)}"))
            sparse, eager = writers(base, blobs)
            for op, *args in operations:
                try:
                    result_sparse = getattr(sparse, op)(*args)
                    failed_sparse = None
                except ValueError as exc:
                    failed_sparse = str(exc)
                try:
                    getattr(eager, op)(*args)
                    failed_eager = None
                except ValueError as exc:
                    failed_eager = str(exc)
                # Both writers must agree even on refusals.
                self.assertEqual(failed_sparse is None, failed_eager is None,
                                 (op, args))
            self.assertEqual(sparse.commit(), eager.commit(),
                             f"root drift at seed {seed}")

    def test_incremental_commits_match(self):
        base, blobs = publish([("thing", [])])
        sparse, eager = writers(base, blobs)
        for i in range(5):
            sparse.put(f"item-{i}", ["thing"])
            eager.put(f"item-{i}", ["thing"])
            self.assertEqual(sparse.commit(), eager.commit(), f"step {i}")


class TestLocality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base, cls.blobs = publish(broad_fixture())   # 447 records

    def test_write_fetch_budget(self):
        sparse = SparseOntoDAG(RecordStore(self.blobs, root=self.base))
        sparse.put("new-leaf", ["m3", "m7"])
        self.assertLess(sparse.fetches, 60,
                        f"a localized put fetched {sparse.fetches} records")

    def test_commit_stages_only_the_diff(self):
        counting = CountingStore(RecordStore(self.blobs, root=self.base))
        sparse = SparseOntoDAG(counting)
        sparse.put("new-leaf", ["m3", "m7"])
        sparse.commit()
        # new-leaf + the two parents' down lists + ancestor count records:
        # a handful, never the 447-record store.
        self.assertLess(counting.puts, 15,
                        f"commit staged {counting.puts} records")
        # An idempotent re-commit stages nothing at all.
        counting.puts = 0
        sparse.commit()
        self.assertEqual(counting.puts, 0)

    def test_rehydrated_result_is_a_valid_graph(self):
        sparse = SparseOntoDAG(RecordStore(self.blobs, root=self.base))
        sparse.put("new-leaf", ["m3", "m7"])
        sparse.remove("x5")
        root = sparse.commit()
        again = EagerOntoDAG(RecordStore.at(root, self.blobs))
        # Counts exact everywhere (I5 oracle over raw neighbor sets).
        def reach(node):
            seen, stack = set(), [node]
            while stack:
                for child in stack.pop().neighbors:
                    if child not in seen:
                        seen.add(child)
                        stack.append(child)
            return seen
        for node in again.nodes.values():
            self.assertEqual(node.descendant_count, len(reach(node)),
                             node.name)
        self.assertIn("new-leaf", again.nodes)
        self.assertNotIn("x5", again.nodes)


class TestSparseSemantics(unittest.TestCase):
    def test_reader_stays_read_only(self):
        base, blobs = publish([("thing", [])])
        reader = LazyOntoDAG(RecordStore.at(base, blobs))
        with self.assertRaises(TypeError):
            reader.put("x", ["thing"])

    def test_queries_work_mid_edit(self):
        base, blobs = publish([("animal", []), ("dog", ["animal"])])
        sparse = SparseOntoDAG(RecordStore(blobs, root=base))
        sparse.put("spaniel", ["dog"])
        self.assertIn("spaniel",
                      {i.name for i in sparse.get({"animal"})})

    def test_readd_after_remove(self):
        base, blobs = publish([("animal", []), ("dog", ["animal"])])
        sparse, eager = writers(base, blobs)
        for dag in (sparse, eager):
            dag.remove("dog")
            dag.put("dog", ["animal"])
            dag.put("rex", ["dog"])
        self.assertEqual(sparse.commit(), eager.commit())


if __name__ == "__main__":
    unittest.main()
