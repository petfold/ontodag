"""The identifier kind (registry 4.3, 2026-10-01): values compared by
equality only — the home of `item(h)`, a term naming one individual
(loopmarket's I1: a car by its VIN's hash, a plot by its land register
number). Under the prefix kind, the nearest before it, a shorter value
meant "every id with this prefix", so `item(ab)` covered every item whose
hash starts `ab`; here a value means only itself, a short one included.
The kind node is a consumer's declaration outside the prelude, a role head
under an identifier head (`lot → item`) keeps its own star, and a head
declared under the prefix kind re-declares here with no stored name
changing (the linear → calendar precedent)."""

import unittest

import pytest

from ontodag.dag import OntoDAG
from ontodag.dimensions import (
    KIND_IDENTIFIER, KIND_PREFIX, KINDS, REGISTRY_VERSION, canonicalize, contains, intersect, space_of,
)

H = "3f" * 32                      # a whole 64-hex id, as loopmarket derives them
H2 = "3f" * 31 + "40"


def make_dag():
    dag = OntoDAG()
    dag.put("dimension", [])
    dag.put("identifier-dimension", ["dimension"])
    dag.put("item", ["identifier-dimension"])
    return dag


def names(items):
    return {item.name for item in items}


class TestTheKind(unittest.TestCase):
    def test_the_kind_is_registered_at_4_3(self):
        self.assertIn(KIND_IDENTIFIER, KINDS)
        self.assertEqual(REGISTRY_VERSION, "4.3")

    def test_containment_is_equality(self):
        self.assertTrue(contains(f"item({H})", f"item({H})", KIND_IDENTIFIER))
        self.assertFalse(contains(f"item({H})", f"item({H2})", KIND_IDENTIFIER))
        # the reason the kind exists: a short value contains nothing but itself
        self.assertFalse(contains("item(3f)", f"item({H})", KIND_IDENTIFIER))
        self.assertTrue(contains("item(3f)", f"item({H})", KIND_PREFIX))   # where the prefix kind went wrong
        self.assertTrue(contains("item(3f)", "item(3f)", KIND_IDENTIFIER))

    def test_the_meet_is_the_value_or_nothing(self):
        self.assertEqual(intersect(f"item({H})", f"item({H})", KIND_IDENTIFIER), f"item({H})")
        self.assertIsNone(intersect(f"item({H})", f"item({H2})", KIND_IDENTIFIER))
        self.assertIsNone(intersect("item(3f)", f"item({H})", KIND_IDENTIFIER))

    def test_malformed_values_are_refused(self):
        for bad in ("item(a b)", "item(..)", "item(-x)", "item(3f..40)"):
            with pytest.raises(ValueError):
                canonicalize(bad, KIND_IDENTIFIER)

    def test_the_prefix_kinds_grammar_and_canonical_form(self):
        # so a head declared under the prefix kind re-declares here unchanged
        for value in (H, "978-0-306-40615-7", "u2e4x", "ISBN.9780306406157"):
            self.assertEqual(canonicalize(f"item({value})", KIND_IDENTIFIER),
                             canonicalize(f"item({value})", KIND_PREFIX))
        self.assertEqual(space_of(f"item({H})", KIND_IDENTIFIER), "identifier")


class TestInTheGraph(unittest.TestCase):
    def test_an_item_is_below_only_itself(self):
        dag = make_dag()
        dag.put("my-car", [f"item({H})"])
        dag.put("other-car", [f"item({H2})"])
        self.assertTrue(dag.is_below(f"item({H})", f"item({H})"))
        self.assertFalse(dag.is_below(f"item({H})", f"item({H2})"))
        self.assertFalse(dag.is_below(f"item({H})", "item(3f)"))
        self.assertEqual(names(dag.get([f"item({H})"], items_only=True)), {"my-car"})
        self.assertEqual(names(dag.get(["item(3f)"], items_only=True)), set())   # no subtree query

    def test_a_role_head_keeps_its_own_star(self):
        dag = make_dag()
        dag.put("lot", ["item"])                    # a lot is named like an item
        self.assertEqual(dag._dimension_of("lot"), (KIND_IDENTIFIER, "item"))
        dag.put("batch-7", [f"lot({H})"])
        self.assertTrue(dag.is_below(f"lot({H})", f"lot({H})"))
        self.assertFalse(dag.is_below(f"lot({H})", f"lot({H2})"))
        self.assertEqual(names(dag.get([f"lot({H})"], items_only=True)), {"batch-7"})

    def test_a_prefix_declared_head_re_declares_without_renaming(self):
        dag = OntoDAG()
        dag.put("dimension", [])
        dag.put("prefix-dimension", ["dimension"])
        dag.put("item", ["prefix-dimension"])
        dag.put("my-car", [f"item({H})"])
        stored = set(dag.nodes)
        self.assertTrue(dag.is_below(f"item({H})", "item(3f)"))       # the stopgap's hole
        dag.put("identifier-dimension", ["dimension"])
        dag.remove_edge(dag.nodes["prefix-dimension"], dag.nodes["item"])   # one kind at a time
        dag.add_edge(dag.nodes["identifier-dimension"], dag.nodes["item"])
        self.assertEqual(dag._dimension_of("item"), (KIND_IDENTIFIER, "item"))
        self.assertEqual(set(dag.nodes), stored | {"identifier-dimension"})
        self.assertFalse(dag.is_below(f"item({H})", "item(3f)"))      # closed
        self.assertEqual(names(dag.get([f"item({H})"], items_only=True)), {"my-car"})
