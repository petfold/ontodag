"""Conformance suite for docs/CONTRACT.md (contract version 0.1).

One named test class per guarantee G1-G6, plus the §4 as-of clause and the
version constant. Every test goes through the PUBLIC API only: the `ontodag`
package surface (plus recordstore's public surface where a guarantee is
about roots) — never submodule paths, never internals. This file is the
executable half of the contract: if a change breaks a test here, either the
change is wrong or CONTRACT.md needs a version bump (its §8, resolution 2).
"""

import unittest

import ontodag
from recordstore import MemoryBytesStore, RecordStore


def eager(blobs, base=None):
    return ontodag.EagerOntoDAG(RecordStore(blobs, root=base))


def names(items):
    return {i.name for i in items}


def declare_weight(dag):
    """The v1 kind registry plus one linear dimension (DIMENSIONS.md)."""
    dag.put("dimension", [])
    dag.put("linear-dimension", ["dimension"])
    dag.put("weight", ["linear-dimension"])
    return dag


class TestContractVersion(unittest.TestCase):
    def test_version_constant_matches_document(self):
        self.assertEqual(ontodag.CONTRACT_VERSION, "0.1")


class TestG1CanonicalRoot(unittest.TestCase):
    """Equal knowledge yields an equal root: history, insertion order and
    spelling of equal denotations do not affect it."""

    def test_put_order_does_not_affect_root(self):
        a = eager(MemoryBytesStore())
        a.put("pet", [])
        a.put("cat", ["pet"])
        a.put("dog", ["pet"])
        b = eager(MemoryBytesStore())  # separate blob store on purpose:
        b.put("pet", [])               # roots are content addresses
        b.put("dog", ["pet"])
        b.put("cat", ["pet"])
        self.assertEqual(a.commit(), b.commit())

    def test_redundant_parent_is_pruned_to_the_same_root(self):
        a = eager(MemoryBytesStore())
        a.put("animal", [])
        a.put("pet", ["animal"])
        a.put("cat", ["pet"])
        b = eager(MemoryBytesStore())
        b.put("animal", [])
        b.put("pet", ["animal"])
        b.put("cat", ["pet", "animal"])  # redundant: pet already ⊑ animal
        self.assertEqual(a.commit(), b.commit())

    def test_spellings_of_one_denotation_collapse_to_one_root(self):
        a = declare_weight(eager(MemoryBytesStore()))
        a.put("parcel", ["weight(3kg)"])
        b = declare_weight(eager(MemoryBytesStore()))
        b.put("parcel", ["weight(3000g)"])  # same denotation, other spelling
        self.assertEqual(a.commit(), b.commit())


class TestG2MonotonicityUnderMerge(unittest.TestCase):
    """Merge is union + re-reduction: true stays true, answers only grow."""

    def _pair(self):
        a = ontodag.OntoDAG()
        a.put("pet", [])
        a.put("cat", ["pet"])
        b = ontodag.OntoDAG()
        b.put("pet", [])
        b.put("dog", ["pet"])
        return a, b

    def test_answers_only_grow_and_truths_survive(self):
        a, b = self._pair()
        before = names(a.get(["pet"]))
        self.assertTrue(a.is_below("cat", "pet"))
        a.merge(b)
        after = names(a.get(["pet"]))
        self.assertLessEqual(before, after)          # nothing shrank
        self.assertIn("dog", after)                  # union arrived
        self.assertTrue(a.is_below("cat", "pet"))    # true stayed true
        self.assertTrue(a.is_below("dog", "pet"))

    def test_merge_is_idempotent_and_direction_free_in_answers(self):
        a, b = self._pair()
        a.merge(b)
        once = names(a.get(["pet"]))
        a.merge(b)
        self.assertEqual(once, names(a.get(["pet"])))  # idempotent
        c, d = self._pair()
        d.merge(c)
        self.assertEqual(once, names(d.get(["pet"])))  # either direction


class TestG3Determinism(unittest.TestCase):
    """Same root, same interpretation context: same answers on any
    residency (eager rehydration vs lazy on-demand)."""

    def setUp(self):
        self.blobs = MemoryBytesStore()
        w = eager(self.blobs)
        w.put("pet", [])
        w.put("robot", [])
        w.put("cat", ["pet"])
        w.put("dog", ["pet"])
        w.put("puppy", ["dog"])
        w.put("robodog", ["robot", "dog"])
        self.root = w.commit()

    def test_every_residency_gives_the_same_answers(self):
        readers = [
            ontodag.EagerOntoDAG(RecordStore.at(self.root, self.blobs)),
            ontodag.LazyOntoDAG(RecordStore.at(self.root, self.blobs)),
        ]
        queries = [["pet"], ["dog"], ["robot", "dog"], ["pet", "robot"]]
        expected = [names(readers[0].get(q)) for q in queries]
        for reader in readers[1:]:
            for q, want in zip(queries, expected):
                self.assertEqual(names(reader.get(q)), want, q)
        self.assertEqual(
            names(readers[0].get_any([["cat"], ["robot"]])),
            names(readers[1].get_any([["cat"], ["robot"]])),
        )


class TestG4IsBelowFailClosed(unittest.TestCase):
    """True only with a witness; false means not derivable, never error."""

    def setUp(self):
        self.dag = declare_weight(ontodag.OntoDAG())
        self.dag.put("pet", [])
        self.dag.put("cat", ["pet"])

    def test_reflexive_and_witnessed(self):
        self.assertTrue(self.dag.is_below("cat", "cat"))
        self.assertTrue(self.dag.is_below("cat", "pet"))
        self.assertFalse(self.dag.is_below("pet", "cat"))

    def test_unknown_names_fail_closed_not_loud(self):
        self.assertFalse(self.dag.is_below("nope", "pet"))
        self.assertFalse(self.dag.is_below("cat", "nope"))
        self.assertFalse(self.dag.is_below("nope", "alsonope"))

    def test_virtual_parametric_terms_decide_from_names_alone(self):
        # No weight *values* exist as nodes — arithmetic answers anyway.
        self.assertTrue(self.dag.is_below("weight(3kg)", "weight(..5kg)"))
        self.assertFalse(self.dag.is_below("weight(6kg)", "weight(..5kg)"))


class TestG5Convergence(unittest.TestCase):
    """Writers folding each other's published roots land byte-identically,
    whatever the gossip order."""

    def test_two_writers_converge(self):
        blobs = MemoryBytesStore()
        alice, bob = eager(blobs), eager(blobs)
        alice.put("pet", [])
        alice.put("cat", ["pet"])
        bob.put("pet", [])
        bob.put("dog", ["pet"])
        root_a, root_b = alice.commit(), bob.commit()
        merged_a = alice.sync(root_b)
        merged_b = bob.sync(root_a)
        self.assertEqual(merged_a, merged_b)
        self.assertEqual(alice.sync(merged_b), merged_a)  # idempotent


class TestG6GetOverlapping(unittest.TestCase):
    """Complete for possibility, silent on satisfaction."""

    def setUp(self):
        self.dag = declare_weight(ontodag.OntoDAG())
        self.dag.put("light", ["weight(500g)"])
        self.dag.put("box", ["weight(0.8kg..1.5kg)"])
        self.dag.put("heavy", ["weight(2kg)"])

    def test_candidates_are_recall_complete_but_not_asserted(self):
        need = "weight(1kg..)"
        candidates = names(self.dag.get_overlapping(need))
        satisfied = names(self.dag.get([need]))
        self.assertLessEqual(satisfied, candidates)   # recall-complete
        self.assertIn("heavy", satisfied)             # definite satisfier
        self.assertIn("box", candidates)              # possible satisfier...
        self.assertNotIn("box", satisfied)            # ...not asserted
        self.assertNotIn("light", candidates)         # provably disjoint

    def test_only_parametric_terms_of_declared_dimensions(self):
        with self.assertRaises(ValueError):
            self.dag.get_overlapping("light")

    def test_candidates_grow_monotonically(self):
        need = "weight(1kg..)"
        before = names(self.dag.get_overlapping(need))
        self.dag.put("crate", ["weight(1.2kg)"])
        after = names(self.dag.get_overlapping(need))
        self.assertLessEqual(before, after)
        self.assertIn("crate", after)


class TestAsOfClause(unittest.TestCase):
    """§4: a root-pinned answer is an immutable, replayable fact."""

    def test_answers_at_a_root_never_move(self):
        blobs = MemoryBytesStore()
        w = eager(blobs)
        w.put("pet", [])
        w.put("cat", ["pet"])
        root1 = w.commit()
        w.put("dog", ["pet"])
        root2 = w.commit()

        at1 = ontodag.LazyOntoDAG(RecordStore.at(root1, blobs))
        at2 = ontodag.LazyOntoDAG(RecordStore.at(root2, blobs))
        self.assertEqual(names(at1.get(["pet"])), {"cat"})
        self.assertEqual(names(at2.get(["pet"])), {"cat", "dog"})
        # replayable: a fresh reader at the old root answers identically
        again = ontodag.LazyOntoDAG(RecordStore.at(root1, blobs))
        self.assertEqual(names(again.get(["pet"])), {"cat"})


if __name__ == "__main__":
    unittest.main()
