"""Steps 2-4 of docs/DIMENSIONS.md §12: parametric dimensions wired into
OntoDAG — canonicalization at the boundary, anchor stars, the combined
(asserted + computed) order in reduction and queries, the put-time guards,
remove-contraction along combined covers, and virtual query terms.

The reachability helpers are independent of the traversal code under test
(same oracle discipline as tests/test_invariants.py); persisted counts are
asserted-only by design, so the count oracle walks `neighbors` alone."""

import unittest

from ontodag.dag import OntoDAG


def reach(node):
    """All nodes strictly ASSERTED-reachable from `node` (oracle: walks the
    raw neighbor sets, independent of dag.py's traversals)."""
    seen = set()
    stack = [node]
    while stack:
        for child in stack.pop().neighbors:
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def edge_set(dag):
    return {(parent.name, child.name)
            for parent in dag.nodes.values() for child in parent.neighbors}


def names(items):
    return {item.name for item in items}


def make_dag():
    """A DAG with the three v1 kinds declared and one dimension of each."""
    dag = OntoDAG()
    dag.put("dimension", [])
    dag.put("linear-dimension", ["dimension"])
    dag.put("prefix-dimension", ["dimension"])
    dag.put("dominance-dimension", ["dimension"])
    dag.put("weight", ["linear-dimension"])
    dag.put("geo", ["prefix-dimension"])
    dag.put("size", ["dominance-dimension"])
    return dag


class TestBoundaryAndAnchors(unittest.TestCase):
    def test_put_canonicalizes_and_anchors(self):
        dag = make_dag()
        dag.put("parcel", ["weight(3kg)"])
        self.assertIn("weight(3000000mg)", dag.nodes)
        self.assertNotIn("weight(3kg)", dag.nodes)
        value = dag.nodes["weight(3000000mg)"]
        self.assertEqual(names(value.parents), {"weight"})   # the anchor
        self.assertEqual(names(dag.nodes["parcel"].parents),
                         {"weight(3000000mg)"})

    def test_sugar_is_one_identity_everywhere(self):
        dag = make_dag()
        dag.put("parcel", ["weight(3kg)"])
        dag.put("parcel2", ["weight(3000g)"])  # same canonical value
        self.assertEqual(
            names(dag.nodes["weight(3000000mg)"].neighbors),
            {"parcel", "parcel2"})
        # Queries accept sugar too.
        self.assertIn(dag.nodes["parcel"],
                      dag.get_descendants("weight(3.0kg)"))

    def test_undeclared_head_stays_opaque(self):
        dag = make_dag()
        dag.put("foo(3kg)", [])       # `foo` is no dimension: opaque atom
        self.assertIn("foo(3kg)", dag.nodes)
        with self.assertRaises(ValueError):
            dag.put("y", ["bar(5kg)"])  # opaque AND missing, like any name

    def test_anchor_survives_cross_edges(self):
        dag = make_dag()
        dag.put("light", ["weight"])
        dag.put("weight(3kg)", ["light"])
        value = dag.nodes["weight(3000000mg)"]
        # `weight` is an ancestor of `light`, so reduction would prune the
        # direct weight -> value edge — but it is the anchor: schema, kept.
        self.assertEqual(names(value.parents), {"weight", "light"})

    def test_malformed_parameter_raises(self):
        dag = make_dag()
        with self.assertRaises(ValueError):
            dag.put("parcel", ["weight(3zz)"])
        with self.assertRaises(ValueError):
            dag.put("parcel", ["weight(0.0005g)"])  # finer than base unit


class TestComputedOrder(unittest.TestCase):
    def test_courier_and_flour_with_present_terms(self):
        dag = make_dag()
        dag.put("parcel", ["weight(3kg)"])
        dag.put("flour-bag", ["weight(1.2kg)"])
        dag.put("weight(..5kg)", [])   # materialized constraint terms
        dag.put("weight(1kg..)", [])
        below_max = names(dag.get_descendants("weight(..5kg)"))
        self.assertIn("parcel", below_max)
        self.assertIn("flour-bag", below_max)
        at_least = names(dag.get_descendants("weight(1kg..)"))
        self.assertIn("flour-bag", at_least)
        self.assertIn("parcel", at_least)

    def test_points_are_incomparable(self):
        dag = make_dag()
        dag.put("parcel", ["weight(3kg)"])
        dag.put("weight(5kg)", [])
        # A 3 kg parcel is NOT below the 5 kg point (DIMENSIONS.md §2).
        self.assertNotIn("parcel", names(dag.get_descendants("weight(5kg)")))
        self.assertEqual(names(dag.get({"weight(5kg)"})), set())

    def test_get_with_present_parametric_term(self):
        dag = make_dag()
        dag.put("parcel", ["weight(3kg)"])
        dag.put("heavy-parcel", ["weight(9kg)"])
        dag.put("weight(..5kg)", [])
        result = names(dag.get({"weight(..5kg)"}))
        self.assertIn("parcel", result)
        self.assertNotIn("heavy-parcel", result)

    def test_ordinary_term_cone_follows_computed_hops(self):
        # A cross edge INTO the dimension: an ordinary category above an
        # interval term. Its cone must pass through the computed hop to
        # reach items filed under contained values.
        dag = make_dag()
        dag.put("courier-ok", [])
        dag.put("weight(..5kg)", ["courier-ok"])
        dag.put("parcel", ["weight(3kg)"])
        self.assertIn("parcel", names(dag.get({"courier-ok"})))

    def test_prefix_and_dominance_dimensions(self):
        dag = make_dag()
        dag.put("cafe", ["geo(u2edk)"])
        dag.put("geo(u2)", [])
        self.assertIn("cafe", names(dag.get_descendants("geo(u2)")))
        dag.put("bag", ["size(19x23x39cm)"])
        dag.put("size(20x30x40cm)", [])
        self.assertIn("bag", names(dag.get_descendants("size(20x30x40cm)")))
        dag.put("big-box", ["size(50x60x70cm)"])
        self.assertNotIn("big-box",
                         names(dag.get_descendants("size(20x30x40cm)")))


class TestReductionModuloComputed(unittest.TestCase):
    def test_redundant_cross_edge_is_pruned(self):
        dag = make_dag()
        dag.put("parcel", ["weight(..5kg)"])
        dag.put("parcel", ["weight(3kg)"])
        # parcel under the point implies parcel under the interval via a
        # computed hop: the interval edge must be gone (canonical form).
        self.assertEqual(names(dag.nodes["parcel"].parents),
                         {"weight(3000000mg)"})
        self.assertIn("weight(..5000000mg)", dag.nodes)  # value stays

    def test_history_independence_of_stored_form(self):
        def build(order):
            dag = make_dag()
            for step in order:
                dag.put(*step)
            return dag

        steps = [("parcel", ["weight(..5kg)"]),
                 ("parcel", ["weight(3kg)"]),
                 ("flour-bag", ["weight(1.2kg)"]),
                 ("weight(1kg..)", [])]
        forward = build(steps)
        shuffled = build([steps[3], steps[2], steps[1], steps[0]])
        self.assertEqual(edge_set(forward), edge_set(shuffled))

    def test_same_dimension_asserted_edge_refused(self):
        dag = make_dag()
        dag.put("weight(..5kg)", [])
        with self.assertRaises(ValueError):
            dag.put("weight(3kg)", ["weight(..5kg)"])

    def test_cycle_via_computed_hops_refused(self):
        dag = make_dag()
        dag.put("x", ["weight(1kg)"])
        with self.assertRaises(ValueError):
            dag.put("weight(..5kg)", ["x"])


class TestPutGuards(unittest.TestCase):
    def test_disjoint_parents_within_one_call(self):
        dag = make_dag()
        with self.assertRaises(ValueError):
            dag.put("x", ["weight(..2kg)", "weight(3kg..)"])

    def test_disjoint_parents_across_calls(self):
        dag = make_dag()
        dag.put("x", ["weight(..2kg)"])
        with self.assertRaises(ValueError):
            dag.put("x", ["weight(3kg..)"])

    def test_overlapping_parents_are_fine(self):
        dag = make_dag()
        dag.put("x", ["weight(1kg..3kg)", "weight(2kg..5kg)"])
        self.assertEqual(names(dag.nodes["x"].parents),
                         {"weight(1000000mg..3000000mg)",
                          "weight(2000000mg..5000000mg)"})

    def test_unit_family_consistency_per_head(self):
        dag = make_dag()
        dag.put("a", ["weight(3kg)"])
        with self.assertRaises(ValueError):
            dag.put("b", ["weight(5s)"])   # duration in a mass dimension

    def test_ambiguous_kind_inheritance_is_an_error(self):
        dag = make_dag()
        dag.put("odd", ["linear-dimension"])
        dag.put("odd", ["prefix-dimension"])
        with self.assertRaises(ValueError):
            dag.put("x", ["odd(3)"])


class TestRemoveContraction(unittest.TestCase):
    def test_remove_restores_pruned_assertion(self):
        dag = make_dag()
        dag.put("parcel", ["weight(..5kg)"])
        dag.put("parcel", ["weight(3kg)"])   # prunes the interval edge
        dag.remove("weight(3kg)")            # sugar accepted here too
        # Contraction along the combined order restores exactly what
        # reduction-modulo-computed pruned.
        self.assertEqual(names(dag.nodes["parcel"].parents),
                         {"weight(..5000000mg)"})
        self.assertNotIn("weight(3000000mg)", dag.nodes)

    def test_remove_falls_back_to_the_head(self):
        dag = make_dag()
        dag.put("parcel", ["weight(3kg)"])
        dag.remove("weight(3kg)")
        # No containing term present: the anchor parent is all there is.
        self.assertEqual(names(dag.nodes["parcel"].parents), {"weight"})

    def test_counts_survive_contraction(self):
        dag = make_dag()
        dag.put("parcel", ["weight(..5kg)"])
        dag.put("parcel", ["weight(3kg)"])
        dag.put("flour-bag", ["weight(1.2kg)"])
        dag.remove("weight(3kg)")
        for node in dag.nodes.values():
            self.assertEqual(node.descendant_count, len(reach(node)),
                             f"count drift on {node.name}")


class TestCountsStayAssertedOnly(unittest.TestCase):
    def test_i5_after_parametric_operations(self):
        dag = make_dag()
        dag.put("parcel", ["weight(..5kg)"])
        dag.put("parcel", ["weight(3kg)"])       # prunes the interval edge
        dag.put("flour-bag", ["weight(1.2kg)"])
        dag.put("weight(1kg..)", [])
        dag.put("cafe", ["geo(u2edk)"])
        for node in dag.nodes.values():
            self.assertEqual(node.descendant_count, len(reach(node)),
                             f"count drift on {node.name}")


class TestVirtualQueryTerms(unittest.TestCase):
    def _market(self):
        dag = make_dag()
        dag.put("parcel", ["weight(3kg)"])
        dag.put("flour-bag", ["weight(1.2kg)"])
        dag.put("heavy-parcel", ["weight(9kg)"])
        return dag

    def test_courier_query_needs_no_node(self):
        dag = self._market()
        result = names(dag.get({"weight(..5kg)"}))
        self.assertIn("parcel", result)
        self.assertIn("flour-bag", result)
        self.assertNotIn("heavy-parcel", result)
        # Virtual means virtual: querying materialized nothing.
        self.assertNotIn("weight(..5000000mg)", dag.nodes)

    def test_flour_query(self):
        result = names(self._market().get({"weight(1kg..)"}))
        self.assertIn("flour-bag", result)
        self.assertIn("parcel", result)

    def test_same_head_terms_pre_intersect(self):
        dag = self._market()
        result = names(dag.get({"weight(..5kg)", "weight(2kg..)"}))
        self.assertEqual({"weight(3000000mg)", "parcel"}, result)
        # Provably disjoint terms: empty result, no error — a read is a
        # question, only put refuses (DIMENSIONS.md §9).
        self.assertEqual(dag.get({"weight(..2kg)", "weight(3kg..)"}), set())

    def test_mixed_ordinary_and_virtual(self):
        dag = self._market()
        dag.put("organic", [])
        dag.put("parcel", ["organic"])
        result = names(dag.get({"organic", "weight(..5kg)"}))
        self.assertEqual({"parcel"}, result)

    def test_time_window_query(self):
        dag = make_dag()
        dag.put("time", ["linear-dimension"])
        dag.put("summer-photo", ["time(2026-06-15)"])
        dag.put("winter-photo", ["time(2026-01-10)"])
        result = names(dag.get({"time(2026-06-01..2026-08-31)"}))
        self.assertIn("summer-photo", result)
        self.assertNotIn("winter-photo", result)

    def test_geo_prefix_query(self):
        dag = make_dag()
        dag.put("cafe", ["geo(u2edk)"])
        dag.put("far-cafe", ["geo(u3x)"])
        result = names(dag.get({"geo(u2)"}))
        self.assertIn("cafe", result)
        self.assertNotIn("far-cafe", result)

    def test_empty_query_still_raises(self):
        with self.assertRaises(TypeError):
            self._market().get(set())

    def test_unknown_ordinary_term_fails_closed(self):
        self.assertEqual(
            self._market().get({"no-such", "weight(..5kg)"}), set())


class TestEagerDimensions(unittest.TestCase):
    STEPS = [("weight", ["linear-dimension"]),
             ("parcel", ["weight(..5kg)"]),
             ("parcel", ["weight(3kg)"]),
             ("flour-bag", ["weight(1.2kg)"])]

    def _build(self, steps):
        from recordstore import MemoryBytesStore, RecordStore
        blobs = MemoryBytesStore()
        from ontodag.eager import EagerOntoDAG
        dag = EagerOntoDAG(RecordStore(blobs))
        dag.put("dimension", [])
        dag.put("linear-dimension", ["dimension"])
        for step in steps:
            dag.put(*step)
        return dag, blobs

    def test_canonical_roots_across_put_orders(self):
        dag_a, _ = self._build(self.STEPS)
        reordered = [self.STEPS[0], self.STEPS[3],
                     self.STEPS[1], self.STEPS[2]]
        dag_b, _ = self._build(reordered)
        self.assertEqual(dag_a.commit(), dag_b.commit())

    def test_rehydrated_virtual_query(self):
        from recordstore import RecordStore
        from ontodag.eager import EagerOntoDAG
        dag, blobs = self._build(self.STEPS)
        root = dag.commit()
        again = EagerOntoDAG(RecordStore.at(root, blobs))
        self.assertIn("parcel", names(again.get({"weight(..5kg)"})))
        # The anchor star survived the roundtrip as the enumeration index.
        self.assertEqual(names(again.nodes["weight(3000000mg)"].parents),
                         {"weight"})


if __name__ == "__main__":
    unittest.main()
