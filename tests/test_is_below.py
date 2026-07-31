"""is_below — the Boolean subsumption test, answered upward.

Oracle discipline: compared against naive downward reachability on a
fixture and a seeded random DAG. The dimension cases cover all four
present/virtual combinations, plus the cross-edge case that makes the
same-head arithmetic a shortcut rather than the whole answer."""

import random
import unittest

from ontodag.dag import OntoDAG
from ontodag.eager import EagerOntoDAG
from ontodag.lazy import LazyOntoDAG, SparseOntoDAG
from recordstore import MemoryBytesStore, RecordStore


def naive_below(dag, sub, sup):
    """Downward oracle: sub in reach(sup), or equal."""
    if sub == sup and sub in dag.nodes:
        return True
    if sub not in dag.nodes or sup not in dag.nodes:
        return False
    seen, stack = set(), [dag.nodes[sup]]
    while stack:
        for child in stack.pop().neighbors:
            if child.name == sub:
                return True
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return False


def zoo():
    dag = OntoDAG()
    for name, supers in [
        ("animal", []), ("pet", []), ("machine", []),
        ("dog", ["animal", "pet"]), ("cat", ["animal", "pet"]),
        ("aibo", ["machine", "pet"]), ("spaniel", ["dog"]),
    ]:
        dag.put(name, supers)
    return dag


class TestIsBelow(unittest.TestCase):
    def test_basics(self):
        dag = zoo()
        self.assertTrue(dag.is_below("spaniel", "animal"))
        self.assertTrue(dag.is_below("spaniel", "dog"))
        self.assertFalse(dag.is_below("spaniel", "machine"))
        self.assertFalse(dag.is_below("animal", "spaniel"))  # direction
        self.assertTrue(dag.is_below("dog", "dog"))          # reflexive

    def test_unknown_names_fail_closed(self):
        dag = zoo()
        self.assertFalse(dag.is_below("no-such", "animal"))
        self.assertFalse(dag.is_below("spaniel", "no-such"))
        self.assertFalse(dag.is_below("no-such", "no-such"))  # even to itself

    def test_oracle_over_all_pairs(self):
        dag = zoo()
        names = list(dag.nodes)
        for sub in names:
            for sup in names:
                self.assertEqual(dag.is_below(sub, sup),
                                 naive_below(dag, sub, sup), (sub, sup))

    def test_oracle_on_random_dag(self):
        rng = random.Random(13)
        dag = OntoDAG()
        names = [f"n{i}" for i in range(35)]
        for i, name in enumerate(names):
            dag.put(name, rng.sample(names[:i], min(i, rng.randint(0, 2))))
        for _ in range(300):
            sub, sup = rng.choice(names), rng.choice(names)
            self.assertEqual(dag.is_below(sub, sup),
                             naive_below(dag, sub, sup), (sub, sup))


class TestIsBelowDimensions(unittest.TestCase):
    def _dag(self):
        dag = OntoDAG()
        dag.put("dimension", [])
        dag.put("linear-dimension", ["dimension"])
        dag.put("weight", ["linear-dimension"])
        return dag

    def test_both_virtual_is_pure_arithmetic(self):
        dag = self._dag()
        self.assertTrue(dag.is_below("weight(3kg)", "weight(..5kg)"))
        self.assertFalse(dag.is_below("weight(9kg)", "weight(..5kg)"))
        self.assertTrue(dag.is_below("weight(3kg)", "weight(3000g)"))  # ≡
        # ... and nothing was materialized by asking:
        self.assertNotIn("weight(3000000mg)", dag.nodes)

    def test_item_against_virtual_bound(self):
        dag = self._dag()
        dag.put("parcel", ["weight(3kg)"])
        self.assertTrue(dag.is_below("parcel", "weight(..5kg)"))
        self.assertFalse(dag.is_below("parcel", "weight(..2kg)"))
        self.assertFalse(dag.is_below("parcel", "weight(5kg)"))  # point

    def test_virtual_subject_through_present_containers(self):
        dag = self._dag()
        dag.put("courier-ok", [])
        dag.put("weight(..5kg)", ["courier-ok"])   # cross edge into the dim
        # weight(2kg) has no node; it fits within the present interval,
        # which is asserted under courier-ok.
        self.assertTrue(dag.is_below("weight(2kg)", "courier-ok"))
        self.assertFalse(dag.is_below("weight(9kg)", "courier-ok"))

    def test_cross_edges_beat_the_arithmetic_shortcut(self):
        # Same-head arithmetic says weight(5kg) is NOT below weight(..2kg)
        # — but asserted cross edges through an item can put it there
        # (weight(..2kg) -> box -> weight(5kg)), and the walk must find
        # that where the arithmetic shortcut alone would say False.
        # (The reverse construction is a combined-order cycle and is
        # correctly refused by add_edge.)
        dag = self._dag()
        self.assertFalse(dag.is_below("weight(5kg)", "weight(..2kg)"))
        dag.put("box", ["weight(..2kg)"])
        dag.put("weight(5kg)", ["box"])
        self.assertTrue(dag.is_below("weight(5kg)", "weight(..2kg)"))

    def test_no_count_prefilter_footgun(self):
        # The point value has a large ASSERTED cone; the interval's is
        # empty — an asserted-count pre-filter would wrongly say False.
        dag = self._dag()
        for i in range(20):
            dag.put(f"parcel-{i}", ["weight(3kg)"])
        dag.put("weight(..5kg)", [])
        self.assertGreater(dag.nodes["weight(3000000mg)"].descendant_count,
                           dag.nodes["weight(..5000000mg)"].descendant_count)
        self.assertTrue(dag.is_below("weight(3kg)", "weight(..5kg)"))


class TestIsBelowResidencies(unittest.TestCase):
    def test_virtual_bound_is_streaming_on_the_lazy_reader(self):
        # The courier check on a published store: parcel ⊑ weight(..5kg)
        # with no such node. The containing value is a DIRECT parent of the
        # parcel, so the streaming climb answers from the parcel's own
        # record — it must NOT expand the deep category chain that also
        # sits above the parcel (materialize-then-scan would fetch all of
        # it: this budget is the regression test for that).
        blobs = MemoryBytesStore()
        eager = EagerOntoDAG(RecordStore(blobs))
        eager.put("dimension", [])
        eager.put("linear-dimension", ["dimension"])
        eager.put("weight", ["linear-dimension"])
        eager.put("c0", [])
        for i in range(1, 30):
            eager.put(f"c{i}", [f"c{i-1}"])
        eager.put("parcel", ["weight(3kg)", "c29"])
        root = eager.commit()

        reader = LazyOntoDAG(RecordStore.at(root, blobs))
        self.assertTrue(reader.is_below("parcel", "weight(..5kg)"))
        self.assertLess(reader.fetches, 10,
                        f"virtual-bound test fetched {reader.fetches} "
                        "records — the up-cone chain leaked in")
        # The False case must still exhaust (proving absence), chain and
        # all — same records the materializing version read.
        heavy = LazyOntoDAG(RecordStore.at(root, blobs))
        self.assertFalse(heavy.is_below("parcel", "weight(..2kg)"))
        self.assertGreater(heavy.fetches, 30)

    def test_lazy_and_sparse(self):
        blobs = MemoryBytesStore()
        eager = EagerOntoDAG(RecordStore(blobs))
        for name, supers in [("animal", []), ("dog", ["animal"]),
                             ("spaniel", ["dog"])]:
            eager.put(name, supers)
        root = eager.commit()
        reader = LazyOntoDAG(RecordStore.at(root, blobs))
        self.assertTrue(reader.is_below("spaniel", "animal"))
        self.assertFalse(reader.is_below("animal", "spaniel"))
        self.assertLess(reader.fetches, 6)   # upward: never the cone
        writer = SparseOntoDAG(RecordStore(blobs, root=root))
        writer.put("poodle", ["dog"])
        self.assertTrue(writer.is_below("poodle", "animal"))


if __name__ == "__main__":
    unittest.main()
