"""The graph kind (registry 4.2, issue #19): a head under
`graph-dimension` takes as its parameter a conjunction of constraints on
the graph itself — category names and terms of other dimensions — and the
graph orders such terms: `H(X ...) ⊑ H(A ...)` iff every A is above some X.

loopmarket's consumer case: a courier's `transport(small-item weight(..8kg))`
is what the courier accepts, and the wanter's `transport(bicycle weight(5kg))`
fits within it. Which side must be inside is the consumer's rule; ontodag
only orders."""

import unittest

from ontodag import prelude
from ontodag.dag import OntoDAG
from ontodag.eager import EagerOntoDAG
from ontodag.surface import elaborate, render
from recordstore import MemoryBytesStore, RecordStore


def city():
    dag = OntoDAG()
    prelude.apply(dag)
    dag.put("graph-dimension", ["dimension"])    # not in the prelude: a seed line
    dag.put("transport", ["graph-dimension"])
    dag.put("goods", [])
    dag.put("small-item", ["goods"])
    dag.put("bicycle", ["small-item"])
    dag.put("racing-bicycle", ["bicycle"])
    dag.put("piano", ["goods"])
    return dag


class TestGrammar(unittest.TestCase):
    def test_constraints_are_sorted_deduplicated_and_each_canonical(self):
        dag = city()
        self.assertEqual(dag._canonical_name("transport(weight(..8000g) small-item)"),
                         "transport(small-item weight(..8kg))")
        self.assertEqual(dag._canonical_name("transport(bicycle bicycle)"),
                         "transport(bicycle)")
        self.assertEqual(elaborate("transport(weight(..8kg) small-item)", dag),
                         "transport(small-item weight(..8kg))")
        self.assertEqual(render("transport(small-item weight(..8kg))", dag),
                         "transport(small-item weight(..8kg))")

    def test_unknown_and_redundant_constraints_are_refused(self):
        dag = city()
        with self.assertRaisesRegex(ValueError, "unicorn"):
            dag.is_below("transport(unicorn)", "transport(goods)")
        with self.assertRaisesRegex(ValueError, "redundant"):
            dag.put("x", ["transport(bicycle small-item)"])
        with self.assertRaisesRegex(ValueError, "redundant"):
            dag.is_below("transport(weight(5kg) weight(..8kg))", "transport(goods)")
        # a kind node is not a constraint; an empty argument is not a term
        with self.assertRaises(ValueError):
            dag.is_below("transport(linear-dimension)", "transport(goods)")
        self.assertFalse(dag.is_below("transport()", "transport(goods)"))

    def test_the_flat_kinds_still_read_a_nested_parameter_as_opaque(self):
        dag = city()
        dag.put("weight(x(y))", [])                  # an opaque atom, as before
        self.assertIsNone(dag._parse_parametric("weight(x(y))"))
        self.assertTrue(dag.is_below("weight(x(y))", "weight(x(y))"))


class TestOrder(unittest.TestCase):
    def test_every_outer_constraint_above_some_inner_one(self):
        dag = city()
        below = dag.is_below
        self.assertTrue(below("transport(bicycle)", "transport(goods)"))
        self.assertTrue(below("transport(racing-bicycle)", "transport(bicycle)"))
        self.assertFalse(below("transport(goods)", "transport(bicycle)"))
        self.assertFalse(below("transport(piano)", "transport(bicycle)"))
        # a nested term is ordered by its own dimension
        self.assertTrue(below("transport(bicycle weight(5kg))",
                              "transport(small-item weight(..8kg))"))
        self.assertFalse(below("transport(bicycle weight(12kg))",
                               "transport(small-item weight(..8kg))"))
        # a constraint the inner term does not answer is not met
        self.assertFalse(below("transport(bicycle)", "transport(small-item weight(..8kg))"))
        # fewer constraints is the wider term
        self.assertTrue(below("transport(small-item weight(..8kg))", "transport(small-item)"))
        self.assertTrue(below("transport(bicycle)", "transport(bicycle)"))
        # roles keep their own star, as with every kind
        dag.put("bicycle-courier", ["transport"])
        self.assertTrue(below("bicycle-courier(racing-bicycle)", "bicycle-courier(bicycle)"))
        self.assertFalse(below("bicycle-courier(bicycle)", "transport(goods)"))

    def test_a_conjunction_is_the_same_as_its_constraints_as_separate_terms(self):
        """`H(A B)` ≡ `H(A) H(B)` as a QUERY: an item under the conjunction is
        found whichever way the question is spelled, and the two separate
        terms meet to the one canonical conjunction. (An ITEM filed under
        two separate same-head terms is not in the cone of their meet —
        the planner pre-intersects query terms but `put` does not refile
        parents under their meet; that is every kind's behaviour today,
        `weight(..8kg)` + `weight(5kg..)` alike, and not this kind's.)"""
        dag = city()
        dag.put("courier-1", ["transport(small-item weight(..8kg))"])
        dag.put("courier-3", ["transport(piano)"])
        names = lambda items: {i.name for i in items}
        for query in (["transport(small-item weight(..8kg))"],
                      ["transport(small-item)", "transport(weight(..8kg))"],
                      ["transport(goods weight(..10kg))"]):
            self.assertEqual(names(dag.get(query, items_only=True)), {"courier-1"}, query)
        self.assertEqual(names(dag.get(["transport(goods)"], items_only=True)),
                         {"courier-1", "courier-3"})
        self.assertEqual(names(dag.get(["transport(bicycle)"], items_only=True)), set())
        self.assertEqual(dag.meet("transport(small-item)", "transport(weight(..8kg))"),
                         "transport(small-item weight(..8kg))")
        self.assertEqual(dag.meet("transport(bicycle)", "transport(small-item)"),
                         "transport(bicycle)")
        self.assertTrue(dag.overlaps("transport(bicycle)", "transport(piano)"))
        # two same-head parents are admitted (no disjointness among categories)
        dag.put("courier-2", ["transport(small-item)", "transport(weight(..8kg))"])
        self.assertTrue(dag.is_below("courier-2", "transport(small-item)"))
        self.assertTrue(dag.is_below("courier-2", "transport(goods)"))

    def test_the_order_follows_the_graph(self):
        """A constraint names a node, so the term moves with it (the #15
        reading): when `piano` becomes a small item, the piano courier's
        term slides under the small-item one."""
        dag = city()
        dag.put("c", ["transport(piano)"])
        self.assertFalse(dag.is_below("c", "transport(small-item)"))
        dag.put("piano", ["small-item"])
        self.assertTrue(dag.is_below("c", "transport(small-item)"))
        self.assertEqual({i.name for i in dag.get(["transport(small-item)"], items_only=True)},
                         {"c"})


class TestPersistence(unittest.TestCase):
    def test_terms_with_spaces_round_trip_through_a_store_and_a_merge(self):
        store = RecordStore(MemoryBytesStore())
        dag = EagerOntoDAG(store)
        prelude.apply(dag)
        dag.put("graph-dimension", ["dimension"])
        dag.put("transport", ["graph-dimension"])
        dag.put("goods", []); dag.put("small-item", ["goods"]); dag.put("bicycle", ["small-item"])
        dag.put("courier", ["transport(small-item weight(..8kg))"])
        root = dag.commit()
        again = EagerOntoDAG(RecordStore.at(root, store.blobs))
        self.assertIn("transport(small-item weight(..8kg))", again.nodes)
        self.assertTrue(again.is_below("transport(bicycle weight(5kg))",
                                       "transport(small-item weight(..8kg))"))
        self.assertTrue(again.is_below("courier", "transport(goods)"))
        # a fresh DAG merging it lands the same name, edges before nodes or after
        fresh = EagerOntoDAG(RecordStore(MemoryBytesStore()))
        fresh.merge(again)
        self.assertEqual(fresh.commit(), root)
        self.assertTrue(fresh.is_below("courier", "transport(goods)"))


if __name__ == "__main__":
    unittest.main()
