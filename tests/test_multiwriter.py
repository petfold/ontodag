"""The multi-writer merge rule (SWARM_DESIGN.md §5): EagerOntoDAG.sync.

Two (or three) writers diverge from a common committed base over one shared
blob store; each folds the other's published root with sync(). The
load-bearing property is CONVERGENCE — after mutual syncs the roots are
byte-identical strings — plus the semantics that follow from union: parent
sets union and re-reduce (against the combined order, so parametric
dimension terms renormalize exactly as DIMENSIONS.md §5 promises), removals
lose to concurrent re-adds (the documented grow-only stance), and
conflicting dimension-kind declarations surface loudly at first parametric
use rather than corrupting anything silently."""

import unittest

from ontodag.eager import EagerOntoDAG
from recordstore import MemoryBytesStore, RecordStore


def writer(blobs, base=None):
    """A writable EagerOntoDAG hydrated at `base` over shared blobs."""
    return EagerOntoDAG(RecordStore(blobs, root=base))


def base_graph(blobs, puts):
    dag = writer(blobs)
    for name, supers in puts:
        dag.put(name, supers)
    return dag.commit()


def parents(dag, name):
    return {p.name for p in dag.nodes[name].parents
            if dag.nodes.get(p.name) is p}


class TestConvergence(unittest.TestCase):
    def test_two_writers_converge_to_identical_roots(self):
        blobs = MemoryBytesStore()
        base = base_graph(blobs, [("animal", []), ("pet", [])])

        alice = writer(blobs, base)
        alice.put("dog", ["animal", "pet"])
        root_a = alice.commit()

        bob = writer(blobs, base)
        bob.put("cat", ["animal", "pet"])
        root_b = bob.commit()

        self.assertNotEqual(root_a, root_b)          # genuinely diverged
        merged_a = alice.sync(root_b)
        merged_b = bob.sync(root_a)
        self.assertEqual(merged_a, merged_b)          # convergence
        # Idempotence: folding what you already have moves nothing.
        self.assertEqual(alice.sync(merged_b), merged_a)

    def test_converges_when_the_redundancy_spans_writers(self):
        """The bypassed-edge shape: base holds Z->B; alice asserts p->B,
        bob asserts Z->p. Only the UNION makes Z->B redundant (via the
        cross-writer path Z->p->B), so a one-sided prune cannot see it.

        BUG (pre-fix, 2026-08-04): _remove_unneeded_edges pruned only
        edges into the new child, so whichever writer folded second kept
        or dropped Z->B depending on replay order — sync(a<-b) and
        sync(b<-a) landed on DIFFERENT roots (8861f5ae vs 0a819aa0),
        breaking I7's byte-identical convergence."""
        blobs = MemoryBytesStore()
        base = base_graph(blobs, [("Z", []), ("B", ["Z"])])

        alice = writer(blobs, base)
        alice.put("p", [])
        alice.put("B", ["p"])
        root_a = alice.commit()

        bob = writer(blobs, base)
        bob.put("p", ["Z"])
        root_b = bob.commit()

        merged_a = alice.sync(root_b)
        merged_b = bob.sync(root_a)
        self.assertEqual(merged_a, merged_b)
        # And the surviving form is the reduction: Z->p->B, no Z->B.
        self.assertEqual(parents(alice, "B"), {"p"})
        self.assertEqual(parents(bob, "B"), {"p"})

    def test_three_writers_any_gossip_order(self):
        blobs = MemoryBytesStore()
        base = base_graph(blobs, [("thing", [])])
        writers = []
        for i in range(3):
            w = writer(blobs, base)
            w.put(f"item-{i}", ["thing"])
            w.commit()
            writers.append(w)
        roots = [w.store.root for w in writers]

        # Gossip in two different orders; all must land on one root.
        r0 = writers[0].sync(roots[1])
        r0 = writers[0].sync(roots[2])
        r2 = writers[2].sync(roots[0])
        r2 = writers[2].sync(roots[1])
        r1 = writers[1].sync(r0)
        self.assertEqual(r1, writers[1].sync(r2))
        self.assertEqual(r0, r2)


class TestConvergenceFuzz(unittest.TestCase):
    def test_random_divergent_writers_converge_both_ways(self):
        """Randomized commutativity (I7 in persisted form): for seeded
        random divergent writer pairs, the two sync directions must land
        on byte-identical roots. This is the property the one-sided prune
        broke on shapes no hand-written test had; seeded so any failure
        reproduces. Every edge respects the name-index order (supers only
        from lower-indexed names), so the union is acyclic by construction
        and every seed exercises a real merge rather than a refusal."""
        import random

        names = [f"n{i}" for i in range(10)]
        for seed in range(12):
            rng = random.Random(seed)
            blobs = MemoryBytesStore()
            base_puts = []
            for i, name in enumerate(names):
                supers = rng.sample(names[:i], k=min(i, rng.randint(0, 2)))
                base_puts.append((name, supers))
            base = base_graph(blobs, base_puts)

            def diverge(rng2):
                w = writer(blobs, base)
                for _ in range(4):
                    i = rng2.randint(1, len(names))
                    if i == len(names):          # a fresh sink node
                        target = f"x{rng2.randint(0, 3)}"
                        pool = names
                    else:                        # reparent an existing one
                        target = names[i]
                        pool = names[:i]
                    supers = rng2.sample(pool,
                                         k=min(len(pool), rng2.randint(0, 2)))
                    w.put(target, supers)
                return w, w.commit()

            alice, root_a = diverge(random.Random(seed * 2 + 1))
            bob, root_b = diverge(random.Random(seed * 2 + 2))
            self.assertEqual(alice.sync(root_b), bob.sync(root_a),
                             f"sync directions diverged at seed {seed}")

    def test_union_cycle_refused_from_both_directions(self):
        """When the UNION of two acyclic replicas contains a cycle, the
        merge must refuse from EITHER direction — one side refusing while
        the other commits would be divergence by another name. (Which edge
        the error names is replay-order-dependent and deliberately
        unpinned.)"""
        blobs = MemoryBytesStore()
        base = base_graph(blobs, [("a", []), ("b", [])])
        alice = writer(blobs, base)
        alice.put("b", ["a"])
        root_a = alice.commit()
        bob = writer(blobs, base)
        bob.put("a", ["b"])
        root_b = bob.commit()

        with self.assertRaises(ValueError):
            alice.sync(root_b)
        with self.assertRaises(ValueError):
            bob.sync(root_a)


class _CountingBytes:
    """Duck-typed bytes-store wrapper counting every blob read."""

    def __init__(self, store):
        self._store = store
        self.reads = 0

    def get(self, ref):
        self.reads += 1
        return self._store.get(ref)

    def get_many(self, refs):
        refs = list(refs)
        self.reads += len(refs)
        return self._store.get_many(refs)   # keep the mapping contract

    def __getattr__(self, name):
        return getattr(self._store, name)


class TestDeltaFold(unittest.TestCase):
    """merge_delta must be indistinguishable from the full-hydration fold
    in RESULT (byte-identical roots) and proportional to the DIVERGENCE in
    cost (blob reads)."""

    def _full_merge_root(self, blobs, base, other_root):
        """The full-hydration oracle: hydrate the peer whole, merge()."""
        from recordstore import RecordStore
        oracle = writer(blobs, base)
        oracle.merge(EagerOntoDAG(RecordStore.at(other_root, blobs)))
        return oracle.commit()

    def test_delta_fold_equals_full_hydration_merge(self):
        import random

        names = [f"n{i}" for i in range(12)]
        for seed in range(8):
            rng = random.Random(1000 + seed)
            blobs = MemoryBytesStore()
            base_puts = [(name, rng.sample(names[:i],
                                           k=min(i, rng.randint(0, 2))))
                         for i, name in enumerate(names)]
            base = base_graph(blobs, base_puts)

            def diverge(rng2):
                w = writer(blobs, base)
                for _ in range(3):
                    i = rng2.randint(1, len(names) - 1)
                    w.put(names[i], rng2.sample(names[:i],
                                                k=min(i, rng2.randint(0, 2))))
                if rng2.random() < 0.5:
                    w.remove(names[rng2.randint(1, len(names) - 1)])
                return w, w.commit()

            alice, root_a = diverge(random.Random(seed * 3 + 1))
            _bob, root_b = diverge(random.Random(seed * 3 + 2))

            expected = self._full_merge_root(blobs, root_a, root_b)
            self.assertEqual(alice.sync(root_b), expected,
                             f"delta != full merge at seed {seed}")

    def test_fold_reads_only_the_divergence(self):
        """One peer put on a ~300-record store: the fold's blob reads are
        bounded by the divergence (records + trie path + the touched
        cones), never by the store."""
        blobs = MemoryBytesStore()
        puts = [("top", [])]
        puts += [(f"mid{i}", ["top"]) for i in range(20)]
        puts += [(f"leaf{i}", [f"mid{i % 20}"]) for i in range(280)]
        base = base_graph(blobs, puts)

        alice = writer(blobs, base)
        alice.put("mine", ["mid3"])

        bob = writer(blobs, base)
        bob.put("theirs", ["mid7"])
        root_b = bob.commit()

        counting = _CountingBytes(blobs)
        alice.sync(root_b, bytes_store=counting)
        self.assertIn("theirs", alice.nodes)
        self.assertLess(counting.reads, 60,
                        "fold read like a hydration, not like a diff")

    def test_sync_into_empty_writer(self):
        """base_root None (hydrated empty): the diff degenerates to the
        peer's full content and the fold is a plain adoption."""
        blobs = MemoryBytesStore()
        published = base_graph(blobs, [("animal", []), ("dog", ["animal"])])
        fresh = writer(blobs)                     # empty, base_root None
        merged = fresh.sync(published)
        self.assertEqual(merged, published)       # canonical: same content
        self.assertEqual(parents(fresh, "dog"), {"animal"})


class TestUnionSemantics(unittest.TestCase):
    def test_divergent_parents_union_and_reduce(self):
        blobs = MemoryBytesStore()
        base = base_graph(blobs, [("animal", []), ("pet", []),
                                  ("dog", ["animal"])])
        alice = writer(blobs, base)
        alice.put("dog", ["pet"])                    # dog also a pet
        bob = writer(blobs, base)
        bob.put("spaniel", ["dog"])
        merged = bob.sync(alice.commit())
        alice.sync(bob.store.root)
        self.assertEqual(parents(alice, "dog"), {"animal", "pet"})
        self.assertEqual(parents(alice, "spaniel"), {"dog"})
        self.assertEqual(merged, alice.store.root)

    def test_remove_loses_to_concurrent_readd(self):
        blobs = MemoryBytesStore()
        base = base_graph(blobs, [("animal", []), ("dog", ["animal"])])
        alice = writer(blobs, base)
        alice.remove("dog")
        root_a = alice.commit()
        bob = writer(blobs, base)
        bob.put("spaniel", ["dog"])                  # re-affirms dog's edges
        root_b = bob.commit()
        self.assertEqual(alice.sync(root_b), bob.sync(root_a))
        self.assertIn("dog", alice.nodes)            # union: grow-only


class TestDimensionsAcrossWriters(unittest.TestCase):
    BASE = [("dimension", []), ("linear-dimension", ["dimension"]),
            ("weight", ["linear-dimension"])]

    def test_cross_writer_renormalization(self):
        # Alice asserts the coarse fact, Bob the fine one; after the fold
        # the fine one implies the coarse via a computed hop, so reduction-
        # modulo-computed must prune the coarse edge — on BOTH replicas.
        blobs = MemoryBytesStore()
        base = base_graph(blobs, self.BASE)
        alice = writer(blobs, base)
        alice.put("parcel", ["weight(..5kg)"])
        bob = writer(blobs, base)
        bob.put("parcel", ["weight(3kg)"])
        merged_a = alice.sync(bob.commit())
        merged_b = bob.sync(alice.store.root)
        self.assertEqual(merged_a, merged_b)
        self.assertEqual(parents(alice, "parcel"), {"weight(3kg)"})
        self.assertEqual(parents(bob, "parcel"), {"weight(3kg)"})
        # The coarse value survives as a value node (anchored), edge-pruned.
        self.assertIn("weight(..5kg)", alice.nodes)

    def test_conflicting_kind_declarations_surface_loudly(self):
        blobs = MemoryBytesStore()
        base = base_graph(blobs, [("dimension", []),
                                  ("linear-dimension", ["dimension"]),
                                  ("prefix-dimension", ["dimension"])])
        alice = writer(blobs, base)
        alice.put("zone", ["linear-dimension"])
        bob = writer(blobs, base)
        bob.put("zone", ["prefix-dimension"])
        alice.sync(bob.commit())                     # union: zone under both
        with self.assertRaises(ValueError):
            alice.put("x", ["zone(3)"])              # ambiguity is an error


if __name__ == "__main__":
    unittest.main()
