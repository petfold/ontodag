"""Canonicity: same knowledge => same root, whatever history produced it.

This is the property the whole design rests on — share a root and you share an
ontology; two people who describe the same thing get the same address. It is
not one mechanism but a stack of them, and *any single failure breaks it*:

- transitive reduction is unique for a DAG, so the stored structure is a
  function of the knowledge rather than of the path taken to it;
- `descendant_count` lives *inside* each record and is therefore hashed, so a
  count that depended on history (or was merely stale) would change the root;
- records are canonically encoded (`up`/`down` sorted, canonical JSON);
- recordstore's trie is canonical by its own two structural invariants;
- `remove` contracts exactly, leaving no trace of a deleted node.

`test_eager.py` already checks a small version of this (S2). These cases are
deliberately harsher: each builds the *same* knowledge by a route that
exercises a different mechanism above, and all roots must be equal.
"""

import unittest

from ontodag import EagerOntoDAG, Item, OntoDAG
from recordstore import MemoryBytesStore, RecordStore


def store():
    return RecordStore(MemoryBytesStore())


# Animal > {Dog, Cat}; Pet > {Dog, Cat}; Dog > Spaniel  — a genuine DAG:
# Dog and Cat each have two parents, so this is not a tree.
TARGET = [
    ("Animal", []),
    ("Pet", []),
    ("Dog", ["Animal", "Pet"]),
    ("Cat", ["Animal", "Pet"]),
    ("Spaniel", ["Dog"]),
]


def build(pairs):
    dag = EagerOntoDAG(store())
    for name, supers in pairs:
        dag.put(Item(name), [Item(s) for s in supers])
    return dag


class TestCanonicalRoot(unittest.TestCase):
    """Every history below must reach the same root as `direct`."""

    def setUp(self):
        self.expected = build(TARGET).commit()

    def assertSameRoot(self, root, how):
        self.assertEqual(
            root, self.expected,
            f"{how} produced a different root — canonicity is broken")

    def test_insertion_order_and_super_order(self):
        """Neither the order items arrive in nor the order of a put's
        super-categories may leak into the stored form."""
        self.assertSameRoot(build([
            ("Pet", []),
            ("Animal", []),
            ("Cat", ["Pet", "Animal"]),
            ("Dog", ["Pet", "Animal"]),
            ("Spaniel", ["Dog"]),
        ]).commit(), "reversed insertion and super order")

    def test_cross_links_added_later(self):
        """Filing an item under one parent now and another later must land in
        the same place as declaring both at once."""
        dag = build([
            ("Animal", []), ("Pet", []),
            ("Dog", ["Animal"]), ("Cat", ["Animal"]), ("Spaniel", ["Dog"]),
        ])
        dag.put(Item("Dog"), [Item("Pet")])
        dag.put(Item("Cat"), [Item("Pet")])
        self.assertSameRoot(dag.commit(), "cross-links added after the fact")

    def test_redundant_edge_is_pruned_not_recorded(self):
        """`Spaniel` is already under `Animal` via `Dog`; offering the direct
        edge must change nothing (transitive reduction)."""
        dag = build(TARGET)
        dag.put(Item("Spaniel"), [Item("Animal")])
        self.assertSameRoot(dag.commit(), "a redundant edge")

    def test_churn_leaves_no_trace(self):
        """Nodes added, committed, and removed again must contract away
        completely — including from the counts of everything above them."""
        dag = build(TARGET)
        dag.put(Item("scratch"), [Item("Animal")])
        dag.commit()
        dag.put(Item("temp"), [Item("scratch")])
        dag.commit()
        dag.remove("temp")
        dag.remove("scratch")
        self.assertSameRoot(dag.commit(), "add/commit/remove churn")

    def test_removing_an_intermediate_contracts_exactly(self):
        """Build with an extra layer, then remove it: the children reconnect
        to the parents, which must reproduce the target exactly."""
        dag = build([
            ("Animal", []), ("Pet", []),
            ("Carnivore", ["Animal"]),                  # the doomed layer
            ("Dog", ["Carnivore", "Pet"]),
            ("Cat", ["Carnivore", "Pet"]),
            ("Spaniel", ["Dog"]),
        ])
        dag.remove("Carnivore")
        self.assertSameRoot(dag.commit(), "removing an intermediate layer")

    def test_built_in_halves_then_merged(self):
        """Two people build overlapping fragments; merging them must give the
        same ontology — and therefore the same address — as building it once."""
        left = OntoDAG()
        for name, supers in [("Animal", []), ("Dog", ["Animal"]),
                             ("Spaniel", ["Dog"])]:
            left.put(Item(name), [Item(s) for s in supers])

        right = OntoDAG()
        for name, supers in [("Animal", []), ("Pet", []),
                             ("Dog", ["Animal", "Pet"]),
                             ("Cat", ["Animal", "Pet"])]:
            right.put(Item(name), [Item(s) for s in supers])

        left.merge(right)

        dag = EagerOntoDAG(store())
        for node in left.topological_sort():          # parents before children
            if node.name == left.root.name:
                continue
            supers = [p.name for p in node.parents if p.name != left.root.name]
            dag.put(Item(node.name), supers)
        self.assertSameRoot(dag.commit(), "merging two halves")

    def test_all_histories_agree_pairwise(self):
        """Belt and braces: collect every route and assert one distinct root,
        so a future change cannot make two of them agree with each other but
        not with the direct build."""
        direct = build(TARGET)

        crosslinked = build([
            ("Animal", []), ("Pet", []),
            ("Dog", ["Animal"]), ("Cat", ["Animal"]), ("Spaniel", ["Dog"]),
        ])
        crosslinked.put(Item("Dog"), [Item("Pet")])
        crosslinked.put(Item("Cat"), [Item("Pet")])

        churned = build(TARGET)
        churned.put(Item("scratch"), [Item("Animal")])
        churned.commit()
        churned.remove("scratch")

        roots = {d.commit() for d in (direct, crosslinked, churned)}
        self.assertEqual(len(roots), 1, f"histories diverged: {roots}")


class TestCanonicalityDependsOnExactCounts(unittest.TestCase):
    """Counts are hashed, so canonicity *requires* them to be exact. This
    pins the connection explicitly: it is why the delta-maintained counts had
    to be verified against an oracle rather than merely made fast."""

    def test_a_stale_count_would_change_the_root(self):
        dag = build(TARGET)
        honest = dag.commit()

        tampered = build(TARGET)
        tampered.nodes["Animal"].descendant_count += 1      # simulate staleness
        self.assertNotEqual(
            tampered.commit(), honest,
            "counts must participate in the root, otherwise a stale count "
            "could travel unnoticed inside a published ontology")


class TestCanonicityIsExploited(unittest.TestCase):
    """Canonicity is not just a property to admire: `merge_published` turns
    "do I already have this version?" into a string comparison."""

    def test_merging_our_own_root_reads_nothing(self):
        blobs = MemoryBytesStore()
        dag = EagerOntoDAG(RecordStore(blobs))
        for name, supers in TARGET:
            dag.put(Item(name), [Item(s) for s in supers])
        root = dag.commit()

        class CountingBlobs:
            def __init__(self, inner):
                self.inner, self.gets = inner, 0

            def put(self, data):
                return self.inner.put(data)

            def get(self, ref):
                self.gets += 1
                return self.inner.get(ref)

        counting = CountingBlobs(blobs)
        watched = EagerOntoDAG(RecordStore.at(root, counting))
        before = counting.gets

        self.assertFalse(watched.merge_published(root),
                         "merging the root we already hold must report no change")
        self.assertEqual(counting.gets, before,
                         "an equal root must be settled by comparison, not by "
                         "reading records")

    def test_merging_a_different_root_still_works(self):
        blobs = MemoryBytesStore()
        mine = EagerOntoDAG(RecordStore(blobs))
        for name, supers in TARGET:
            mine.put(Item(name), [Item(s) for s in supers])
        mine.commit()

        theirs = EagerOntoDAG(RecordStore(blobs))
        theirs.put(Item("Animal"), [])
        theirs.put(Item("Bird"), [Item("Animal")])
        other_root = theirs.commit()

        self.assertTrue(mine.merge_published(other_root))
        self.assertIn("Bird", mine.nodes)
        # and the result is canonical: same as having built it in one go
        direct = build(TARGET + [("Bird", ["Animal"])])
        self.assertEqual(mine.commit(), direct.commit())

    def test_short_circuit_holds_with_local_uncommitted_changes(self):
        """Our uncommitted work makes us a superset of the shared root, so
        skipping is still correct — and must not discard that work."""
        blobs = MemoryBytesStore()
        dag = EagerOntoDAG(RecordStore(blobs))
        for name, supers in TARGET:
            dag.put(Item(name), [Item(s) for s in supers])
        root = dag.commit()

        dag.put(Item("Terrier"), [Item("Dog")])          # uncommitted
        self.assertFalse(dag.merge_published(root))
        self.assertIn("Terrier", dag.nodes)

if __name__ == "__main__":
    unittest.main()
