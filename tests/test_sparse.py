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


class TestSparseSync(unittest.TestCase):
    """SparseOntoDAG.sync — the partially-resident multi-writer fold.

    Same oracle discipline as the writer itself: the sparse fold, the
    eager delta fold and the full-hydration merge must land on ONE
    byte-identical root (canonical roots make the three-way check three
    string comparisons); and the fold's cost is the divergence plus the
    touched cones, never the store."""

    def test_three_way_oracle(self):
        rng = random.Random(42)
        names = [f"n{i}" for i in range(12)]
        for trial in range(6):
            puts = [(name, rng.sample(names[:i], k=min(i, rng.randint(0, 2))))
                    for i, name in enumerate(names)]
            base, blobs = publish(puts)

            peer = EagerOntoDAG(RecordStore(blobs, root=base))
            for _ in range(3):
                i = rng.randint(1, len(names) - 1)
                peer.put(names[i],
                         rng.sample(names[:i], k=min(i, rng.randint(0, 2))))
            peer.put(f"peer-only-{trial}", [names[rng.randint(0, 5)]])
            other_root = peer.commit()

            sparse, eager = writers(base, blobs)
            for w in (sparse, eager):
                w.put("local", [names[3]])

            # The full-hydration oracle: same base, same local edit,
            # whole peer hydrated and merged.
            oracle = EagerOntoDAG(RecordStore(blobs, root=base))
            oracle.put("local", [names[3]])
            oracle.merge(EagerOntoDAG(RecordStore.at(other_root, blobs)))
            expected = oracle.commit()

            self.assertEqual(sparse.sync(other_root), expected,
                             f"sparse fold diverged at trial {trial}")
            self.assertEqual(eager.sync(other_root), expected,
                             f"eager delta fold diverged at trial {trial}")

    def test_local_remove_resurrected_by_union(self):
        """A local uncommitted remove loses to the peer's still-held copy —
        same union-of-states stance as the eager fold."""
        base, blobs = publish([("animal", []), ("dog", ["animal"])])
        peer = EagerOntoDAG(RecordStore(blobs, root=base))
        peer.put("cat", ["animal"])
        other_root = peer.commit()

        sparse, eager = writers(base, blobs)
        for w in (sparse, eager):
            w.remove("dog")
        self.assertEqual(sparse.sync(other_root), eager.sync(other_root))
        self.assertIn("dog", sparse.nodes)

    def test_peer_payload_survives_the_fold(self):
        """A peer record's payload must reach the committed union even
        though the sparse writer has no payload channel of its own."""
        base, blobs = publish([("docs", [])])
        peer = EagerOntoDAG(RecordStore(blobs, root=base))
        peer.put("report", ["docs"], payload="swarm-ref-123")
        other_root = peer.commit()

        sparse = SparseOntoDAG(RecordStore(blobs, root=base))
        sparse.put("local", ["docs"])
        merged = sparse.sync(other_root)
        again = EagerOntoDAG(RecordStore.at(merged, blobs))
        self.assertEqual(again._payloads.get("report"), "swarm-ref-123")

    def test_fold_cost_is_the_divergence(self):
        """One peer put on the 447-record store: the sparse fold's record
        fetches stay bounded by the touched cones, never the store."""
        base, blobs = publish(broad_fixture())
        peer = EagerOntoDAG(RecordStore(blobs, root=base))
        peer.put("theirs", ["m7"])
        other_root = peer.commit()

        sparse = SparseOntoDAG(RecordStore(blobs, root=base))
        sparse.put("mine", ["m3"])
        sparse.sync(other_root)
        self.assertIn("theirs", sparse.nodes)
        self.assertLess(sparse.fetches, 60,
                        f"the fold fetched {sparse.fetches} records")

    def test_rebound_store_is_refused(self):
        """The store must sit at this writer's own lineage: a handle at
        another root would serve foreign records to lazy expansions
        mid-fold (a raw, reduction-blind merge through the back door)."""
        base, blobs = publish([("a", [])])
        peer = EagerOntoDAG(RecordStore(blobs, root=base))
        peer.put("b", ["a"])
        other_root = peer.commit()

        sparse = SparseOntoDAG(RecordStore(blobs, root=base))
        sparse.store = RecordStore(blobs, root=other_root)   # rebound
        with self.assertRaises(ValueError):
            sparse.merge_delta(other_root)

    def test_plain_lazy_reader_has_no_sync(self):
        base, blobs = publish([("thing", [])])
        reader = LazyOntoDAG(RecordStore.at(base, blobs))
        self.assertFalse(hasattr(reader, "sync"))


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


class TestSparseReclassifyAndConeRemoval(unittest.TestCase):
    """The two newer mutations under partial residency, against the eager
    oracle — the assertion this module exists for.

    Both broke when first written, in ways only a store-backed writer shows:
    `remove_cone` recomputed the root's `descendant_count` as
    `len(self.nodes) - 1` (the *resident* count on a sparse writer), and it
    deleted nodes without staging their store deletes, so the committed root
    still contained everything it had just deleted.
    """

    PROJECTS = [("active", []), ("archive", []),
                ("A", ["active"]), ("B", ["active"]),
                ("C", ["A", "B"]), ("a1", ["A"]), ("deep", ["a1"])]

    def _both(self, operation):
        base, blobs = publish(self.PROJECTS)
        sparse, eager = writers(base, blobs)
        for dag in (sparse, eager):
            operation(dag)
        return sparse, eager

    def test_reclassify_matches_the_eager_writer(self):
        sparse, eager = self._both(
            lambda dag: dag.reclassify(["A"], to=["archive"], from_=["active"]))
        self.assertEqual(sparse.commit(), eager.commit())

    def test_reclassify_replacing_every_parent_matches(self):
        sparse, eager = self._both(
            lambda dag: dag.reclassify(["C"], to=["archive"]))
        self.assertEqual(sparse.commit(), eager.commit())

    def test_cone_removal_matches_the_eager_writer(self):
        sparse, eager = self._both(lambda dag: dag.remove_cone(["A"]))
        self.assertEqual(sparse.commit(), eager.commit())

    def test_cone_removal_actually_deletes_the_records(self):
        base, blobs = publish(self.PROJECTS)
        sparse = SparseOntoDAG(RecordStore(blobs, root=base))
        self.assertEqual(sparse.remove_cone(["A"]), {"A", "a1", "deep"})
        root = sparse.commit()
        rehydrated = EagerOntoDAG(RecordStore.at(root, blobs))
        for gone in ("A", "a1", "deep"):
            self.assertNotIn(gone, rehydrated.nodes)
        self.assertIn("C", rehydrated.nodes)          # also under B: survives

    def test_a_deleting_operation_stages_deletes_not_a_sweep(self):
        base, blobs = publish(self.PROJECTS)
        counting = CountingStore(RecordStore(blobs, root=base))
        sparse = SparseOntoDAG(counting)
        sparse.remove_cone(["A"])
        sparse.commit()
        self.assertEqual(counting.deletes, 3)         # A, a1, deep
        self.assertLessEqual(counting.puts, 4)        # only what actually moved

    def test_random_sequences_agree_with_the_eager_writer(self):
        base, blobs = publish(self.PROJECTS)
        names = [name for name, _ in self.PROJECTS]
        for seed in range(20):
            rng = random.Random(seed)
            picks = rng.sample(names, rng.choice([1, 2]))
            cone = rng.choice([True, False])

            def operation(dag, picks=picks, cone=cone):
                if cone:
                    dag.remove_cone(picks)
                else:
                    dag.reclassify(picks[:1], to=["archive"])

            sparse, eager = writers(base, blobs)
            try:
                operation(sparse)
                operation(eager)
            except ValueError:
                continue                  # cycles/root are refused on both
            self.assertEqual(sparse.commit(), eager.commit(),
                             f"seed {seed}: {'cone' if cone else 'reclassify'} "
                             f"{picks}")

    def test_the_reader_still_refuses_both(self):
        base, blobs = publish(self.PROJECTS)
        reader = LazyOntoDAG(RecordStore.at(base, blobs))
        with self.assertRaises(TypeError):
            reader.reclassify(["A"], to=["archive"])
        with self.assertRaises(TypeError):
            reader.remove_cone(["A"])
        # ...but planning is a query, so it works on a read-only view
        cone, deleted = reader.cone_removal_plan(["A"])
        self.assertEqual((cone, deleted),
                         ({"A", "C", "a1", "deep"}, {"A", "a1", "deep"}))
