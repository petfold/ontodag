"""A value is kept only while something is filed under it, or while it is
filed under an ordinary category (review item 21, question 24, decided by
Peter 2026-10-10: A). So the stored form is a function of what is filed:
any order of puts, any grouping of merges, one root."""

import itertools
import random
import unittest
from unittest import mock

from recordstore import MemoryBytesStore, RecordStore

from ontodag import native, prelude
from ontodag.dag import OntoDAG
from ontodag.eager import EagerOntoDAG


def store(filings=()):
    dag = EagerOntoDAG(RecordStore(MemoryBytesStore()))
    prelude.apply(dag)
    for name, supers in filings:
        dag.put(name, supers)
    return dag


def unused(dag):
    """The value nodes nothing is filed under and that sit under their head
    alone."""
    out = set()
    for name, node in dag.nodes.items():
        term = dag.parse_term(name)
        if term is not None and not node.neighbors \
                and {p.name for p in node.parents} == {term.head}:
            out.add(name)
    return out


def parents(dag, name):
    return {p.name for p in dag.nodes[name].parents}


class TestOneRootForWhatIsFiled(unittest.TestCase):

    VALUES = ["mass(1kg..6kg)", "mass(3kg..9kg)", "mass(2kg..5kg)"]

    def test_every_order_of_three_overlapping_values_has_one_root(self):
        roots = set()
        for order in itertools.permutations(self.VALUES):
            dag = store([("crate", [value]) for value in order])
            self.assertEqual(parents(dag, "crate"), {"mass(3kg..5kg)"})
            self.assertEqual(unused(dag), set(), order)
            roots.add(dag.commit())
        self.assertEqual(len(roots), 1)

    def test_the_meet_and_the_values_it_came_from_are_one_fact(self):
        meet = store([("x", ["mass(2kg..5kg)"])])
        two = store([("x", ["mass(..5kg)"]), ("x", ["mass(2kg..)"])])
        together = store([("x", ["mass(..5kg)", "mass(2kg..)"])])
        self.assertEqual(two.commit(), meet.commit())
        self.assertEqual(together.commit(), meet.commit())

    def test_a_finer_value_forgets_the_coarser_one_it_replaces(self):
        dag = store([("x", ["mass(..5kg)"]), ("x", ["mass(3kg)"])])
        self.assertEqual(parents(dag, "x"), {"mass(3kg)"})
        self.assertNotIn("mass(..5kg)", dag.nodes)

    def test_a_value_others_still_use_stays(self):
        dag = store([("x", ["mass(..5kg)"]), ("y", ["mass(..5kg)"]),
                     ("x", ["mass(3kg)"])])
        self.assertEqual(parents(dag, "y"), {"mass(..5kg)"})


class TestWritesThatEmptyAValue(unittest.TestCase):

    def test_removing_the_last_item_forgets_its_value(self):
        dag = store([("x", ["mass(3kg)"]), ("y", ["mass(3kg)"])])
        dag.remove("x")
        self.assertIn("mass(3kg)", dag.nodes)
        dag.remove("y")
        self.assertNotIn("mass(3kg)", dag.nodes)
        self.assertEqual(dag.commit(), store().commit())

    def test_moving_the_last_item_away_forgets_its_value(self):
        dag = store([("box", []), ("x", ["mass(3kg)"])])
        dag.reclassify(["x"], to=["box"], from_=["mass(3kg)"])
        self.assertNotIn("mass(3kg)", dag.nodes)
        self.assertEqual(dag.commit(), store([("box", []), ("x", ["box"])]).commit())

    def test_removing_a_cone_forgets_a_value_it_left_under_its_head_alone(self):
        # A value under an ordinary category survives that category's cone
        # removal (its head is a parent outside the cone), and then states
        # nothing; one something is filed under stays.
        dag = store([("heavy", []), ("mass(30kg..)", ["heavy"]),
                     ("mass(40kg..)", ["heavy"]), ("x", ["mass(40kg..)"])])
        dag.remove_cone(["heavy"])
        self.assertNotIn("mass(30kg..)", dag.nodes)
        self.assertIn("mass(40kg..)", dag.nodes)

    def test_counts_stay_exact(self):
        dag = store([("x", ["mass(..5kg)"]), ("x", ["mass(3kg)"])])
        dag.remove("x")
        for node in dag.nodes.values():
            self.assertEqual(node.descendant_count,
                             len(dag.get_descendants(node, computed=False)),
                             node.name)


class TestABareValue(unittest.TestCase):

    def test_a_value_alone_is_refused_and_says_what_to_do(self):
        dag = store()
        before = dag.commit()
        for supers in (["mass"], []):
            with self.assertRaises(ValueError) as caught:
                dag.put("mass(3kg)", supers)
            self.assertIn("filed under it", str(caught.exception))
        self.assertNotIn("mass(3kg)", dag.nodes)
        self.assertEqual(dag.commit(), before)

    def test_a_value_filed_under_an_ordinary_category_is_kept(self):
        dag = store([("heavy", []), ("mass(30kg..)", ["heavy"])])
        self.assertIn("mass(30kg..)", dag.nodes)
        self.assertEqual(parents(dag, "mass(30kg..)"), {"mass", "heavy"})

    def test_a_value_already_in_use_may_be_put_again(self):
        dag = store([("x", ["mass(3kg)"])])
        root = dag.commit()
        dag.put("mass(3kg)", ["mass"])
        self.assertEqual(dag.commit(), root)


class TestReplaysForgetThemToo(unittest.TestCase):

    def test_a_merge_drops_a_value_the_other_side_left_unused(self):
        old = OntoDAG()
        prelude.apply(old)
        old.put("x", ["mass(3kg)"])
        old._ensure_parametric_node("mass(7kg)", *old._parse_parametric("mass(7kg)")[:2])
        merged = store()
        merged.merge(old)
        self.assertNotIn("mass(7kg)", merged.nodes)
        self.assertEqual(merged.commit(), store([("x", ["mass(3kg)"])]).commit())

    def test_a_merge_forgets_the_value_its_meet_replaces(self):
        merged = store([("x", ["mass(..5kg)"])])
        merged.merge(store([("x", ["mass(3kg)"])]))
        self.assertEqual(unused(merged), set())
        self.assertEqual(merged.commit(), store([("x", ["mass(3kg)"])]).commit())

    def test_loading_an_unmarked_file_drops_unused_values(self):
        base = OntoDAG()
        prelude.apply(base)
        text = "\n".join(line for line in native.dumps(base).splitlines()
                         if not line.startswith("#:canonical"))
        dag = native.loads(text + "\n'mass(3kg)' mass\nx 'mass(4kg)'\n")
        self.assertNotIn("mass(3kg)", dag.nodes)
        self.assertIn("mass(4kg)", dag.nodes)

    def test_merges_in_any_grouping_reach_one_root(self):
        for seed in range(6):
            rng = random.Random(seed)
            filings = []
            for i in range(5):
                point = rng.randint(3, 30)
                for _ in range(rng.randint(1, 3)):
                    lo, hi = point - rng.randint(0, 3), point + rng.randint(0, 3)
                    filings.append((f"x{i}", [f"mass({lo}kg..{hi}kg)"]))
            shares = [[], [], []]
            for filing in filings:
                shares[rng.randrange(3)].append(filing)
            root = store(filings).commit()
            for order in itertools.permutations(range(3)):
                merged = store()
                for k in order:
                    merged.merge(store(shares[k]))
                self.assertEqual(merged.commit(), root, (seed, order))


class TestTheSweepCostsWhatAWriteTouched(unittest.TestCase):

    def test_a_put_looks_at_the_values_it_touched_not_every_value(self):
        dag = store([(f"x{i}", [f"mass({i + 1}kg)"]) for i in range(300)])
        seen = []
        real = OntoDAG._forget_unused

        def spy(self, names):
            seen.append(len(names))
            return real(self, names)

        with mock.patch.object(OntoDAG, "_forget_unused", spy):
            dag.put("y", ["mass(..5kg)"])
            dag.put("y", ["mass(2kg..)"])
        self.assertTrue(seen)
        self.assertLessEqual(max(seen), 4)


    def test_forgetting_a_value_keeps_its_heads_index(self):
        # The head's value index loses the one value, in place: rebuilt from
        # the star, every put that forgets a value would cost every value.
        from ontodag import dag as dag_module
        dag = store([(f"x{i}", [f"mass({i + 1}g..{i + 3}g)"]) for i in range(300)])
        dag.put("probe", ["mass(..9kg)"])
        dag.get(["mass(..1kg)"])                       # the index is built
        calls = []
        real = dag_module._Intervals.add

        def spy(self, *args, **kwargs):
            calls.append(1)
            return real(self, *args, **kwargs)

        with mock.patch.object(dag_module._Intervals, "add", spy):
            for i in range(5):
                dag.put(f"y{i}", [f"mass(..{i + 50}kg)"])
                dag.put(f"y{i}", [f"mass({i + 1}g)"])   # forgets the coarse value
                dag.get(["mass(..1kg)"])
        self.assertNotIn("mass(..50kg)", dag.nodes)
        self.assertLess(len(calls), 50)
        # nor the heads cache, rebuilt by a walk over the whole graph
        dag._heads()
        dag.put("z", ["mass(..60kg)"])
        dag.put("z", ["mass(7g)"])
        self.assertIsNotNone(dag._heads_cache)


if __name__ == "__main__":
    unittest.main()
