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
