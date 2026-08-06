"""ontodag.compare — comparing two stores, at the library level.

The module's one load-bearing decision is that **claims decide what is reported
and edges display it**, so most of this file is about the two ways a naive diff
lies: reporting a re-routed edge as a deletion, and drowning one change in the
cascade of claims it implies. The rest pins the additive fragment's defining
property (merging it lands on the same canonical root as merging the whole
store) and that the module works over any DAG shape, including a read-only lazy
view of a published root.

These tests exist as well as `tests/test_cli.py`'s `TestDiff`/`TestDiffAdditions`
because the logic is now a library: a consumer that is not the CLI can hit it
directly, so its semantics are pinned without going through argument parsing.
"""

import unittest

from ontodag.compare import compare, entailed_claims, parents_of, scope_of
from ontodag.dag import OntoDAG
from ontodag.eager import EagerOntoDAG
from ontodag.lazy import LazyOntoDAG
from recordstore import MemoryBytesStore, RecordStore


def build(rows, dag=None):
    dag = dag if dag is not None else OntoDAG()
    for row in rows:
        parts = row.split()
        dag.put(parts[0], parts[1:])
    return dag


TRAVEL = ("Travel", "Japan", "Flight Travel", "Hotel Travel",
          "JAL Flight Japan", "JAL-cheap JAL", "Ryokan Hotel Japan", "BA Flight")


def root_of(dag):
    """Canonical root of a plain DAG — one string comparison per scenario."""
    eager = EagerOntoDAG(RecordStore(MemoryBytesStore()))
    eager.merge(dag)
    return eager.commit()


class TestNothingToReport(unittest.TestCase):
    def test_identical_stores_compare_false(self):
        diff = compare(build(TRAVEL), build(TRAVEL))
        self.assertFalse(diff)
        self.assertEqual((diff.only_ours, diff.only_theirs), ([], []))
        self.assertEqual((diff.added, diff.removed), ([], []))

    def test_history_does_not_count_as_difference(self):
        # Same content by a different route: canonical form, so nothing differs.
        theirs = build(("Japan", "Travel", "Hotel Travel", "Flight Travel",
                        "Ryokan Hotel Japan", "JAL Flight Japan",
                        "JAL-cheap JAL", "BA Flight"))
        self.assertFalse(compare(build(TRAVEL), theirs))


class TestClaimsDecideEdgesDisplay(unittest.TestCase):
    """The measurement the module is built on."""

    ROUTED = ("p", "B p", "Z p", "leaf B", "leaf Z")

    def test_a_rerouted_edge_is_not_a_deletion(self):
        ours = build(self.ROUTED)
        theirs = build(self.ROUTED)
        theirs.put("Z", ["B"])          # prunes p->Z and B->leaf
        diff = compare(ours, theirs)
        self.assertEqual(diff.added, [("Z", "B")])
        self.assertEqual(diff.removed, [], "a re-routed edge was called a loss")
        self.assertEqual(len(diff.entailed_removed), 0)
        self.assertEqual(len(diff.entailed_added), 1)

    def test_a_real_loss_is_reported(self):
        ours = build(("p", "B p", "leaf B"))
        theirs = build(("p", "B p", "leaf p"))
        diff = compare(ours, theirs)
        self.assertEqual(diff.removed, [("leaf", "B")])
        self.assertEqual(diff.added, [])
        self.assertEqual(diff.entailed_removed, {("leaf", "B")})

    def test_an_item_only_one_side_has_carries_its_parents(self):
        ours = build(TRAVEL)
        theirs = build(TRAVEL)
        theirs.put("Ryokan-Kyoto", ["Ryokan"])
        ours.remove("BA")
        diff = compare(ours, theirs)
        self.assertEqual(diff.only_theirs, ["BA", "Ryokan-Kyoto"])
        self.assertEqual(diff.parents_theirs("Ryokan-Kyoto"), ["Ryokan"])
        # ...and its edges are not listed again as claim lines
        self.assertNotIn(("Ryokan-Kyoto", "Ryokan"), diff.added)

    def test_the_cascade_is_counted_not_listed(self):
        # One edge, thirteen claims: the reason the listing is edge-grain.
        # (Thirteen and not fourteen because the scope excludes the root:
        # "under `*`" is under nothing in particular.)
        rows = ["Top"] + [f"L{i} {'Top' if i == 0 else f'L{i - 1}'}"
                          for i in range(12)]
        ours = build(rows)
        theirs = build(rows)
        theirs.put("newleaf", ["L11"])
        diff = compare(ours, theirs)
        self.assertEqual(diff.only_theirs, ["newleaf"])
        self.assertEqual(diff.added, [])            # one line, not fourteen
        self.assertEqual(len(diff.entailed_added), 13)

    def test_the_entailment_is_computed_only_when_asked(self):
        diff = compare(build(TRAVEL), build(TRAVEL))
        self.assertIsNone(diff._entailed)
        diff.entailed_added
        self.assertIsNotNone(diff._entailed)


class TestScope(unittest.TestCase):
    def test_a_query_cuts_both_sides(self):
        ours = build(TRAVEL)
        theirs = build(TRAVEL)
        theirs.remove("BA")                       # outside Japan
        theirs.put("Ryokan-Kyoto", ["Ryokan"])
        unscoped = compare(ours, theirs)
        self.assertIn("BA", unscoped.only_ours)
        scoped = compare(ours, theirs, [["Travel", "Japan"]])
        self.assertEqual(scoped.only_ours, [])
        self.assertEqual(scoped.only_theirs, ["Ryokan-Kyoto"])

    def test_the_scope_is_the_contexted_excerpt_of_both_sides(self):
        ours = build(TRAVEL)
        scope = scope_of(ours, build(TRAVEL), [["Travel", "Japan"]])
        self.assertEqual(scope, ours.excerpt_names([["Travel", "Japan"]],
                                                   context=True))
        self.assertNotIn("BA", scope)

    def test_a_contexted_excerpt_is_an_exact_subview(self):
        # The pair that makes review possible: without --context the cut cannot
        # even be scoped by the query it came from, since the terms are missing.
        ours = build(TRAVEL)
        cut = ours.excerpt([["Travel", "Japan"]], context=True)
        self.assertFalse(compare(ours, cut, [["Travel", "Japan"]]))
        plain = ours.excerpt([["Travel", "Japan"]])
        self.assertTrue(compare(ours, plain, [["Travel", "Japan"]]))


class TestAdditions(unittest.TestCase):
    """The additive half of a patch IS a merge — the property, not the claim."""

    def _theirs(self):
        theirs = build(TRAVEL)
        theirs.put("Ryokan-Kyoto", ["Ryokan"])
        theirs.put("Onsen", ["Ryokan-Kyoto"])
        theirs.put("JAL-cheap", ["Ryokan"])       # a new claim, both sides have it
        theirs.remove("BA")                        # a removal, which cannot travel
        return theirs

    def test_merging_the_fragment_reaches_the_same_root(self):
        ours, theirs = build(TRAVEL), self._theirs()
        fragment = compare(ours, theirs).additions()

        via_fragment = build(TRAVEL)
        via_fragment.merge(fragment)
        via_whole = build(TRAVEL)
        via_whole.merge(theirs)
        self.assertEqual(root_of(via_fragment), root_of(via_whole))

    def test_it_is_idempotent(self):
        ours = build(TRAVEL)
        fragment = compare(ours, self._theirs()).additions()
        ours.merge(fragment)
        once = root_of(ours)
        ours.merge(fragment)
        self.assertEqual(root_of(ours), once)

    def test_it_carries_only_what_changed(self):
        fragment = compare(build(TRAVEL), self._theirs()).additions()
        self.assertEqual(set(fragment.nodes) - {fragment.root.name},
                         {"Ryokan-Kyoto", "Onsen", "Ryokan", "JAL-cheap"})

    def test_removals_are_not_in_it(self):
        ours, theirs = build(TRAVEL), self._theirs()
        diff = compare(ours, theirs)
        self.assertEqual(diff.only_ours, ["BA"])
        ours.merge(diff.additions())
        self.assertIn("BA", ours.nodes)       # merge only ever adds
        self.assertNotIn("BA", diff.additions().nodes)

    def test_an_empty_comparison_yields_an_empty_fragment(self):
        fragment = compare(build(TRAVEL), build(TRAVEL)).additions()
        self.assertEqual(set(fragment.nodes), {fragment.root.name})


class TestAnyDagShape(unittest.TestCase):
    """Duck-typed: whatever answers the query API can be compared."""

    def test_a_published_root_can_be_compared_lazily(self):
        blobs = MemoryBytesStore()
        published = EagerOntoDAG(RecordStore(blobs))
        build(TRAVEL, published)
        root = published.commit()

        theirs = build(TRAVEL)
        theirs.put("Ryokan-Kyoto", ["Ryokan"])
        reader = LazyOntoDAG(RecordStore.at(root, blobs))
        diff = compare(reader, theirs, [["Travel", "Japan"]])
        self.assertEqual(diff.only_theirs, ["Ryokan-Kyoto"])
        self.assertEqual(diff.only_ours, [])

    def test_it_never_mutates_either_side(self):
        ours, theirs = build(TRAVEL), build(TRAVEL)
        theirs.put("Ryokan-Kyoto", ["Ryokan"])
        before = (root_of(ours), root_of(theirs))
        diff = compare(ours, theirs)
        diff.additions()
        diff.entailed_added
        self.assertEqual((root_of(ours), root_of(theirs)), before)


class TestHelpers(unittest.TestCase):
    def test_parents_of_excludes_the_root(self):
        dag = build(TRAVEL)
        self.assertEqual(parents_of(dag, "Travel"), [])
        self.assertEqual(parents_of(dag, "JAL"), ["Flight", "Japan"])

    def test_entailed_claims_uses_the_combined_order(self):
        # A typed value is below a coarser one with no edge saying so.
        from ontodag.prelude import apply as apply_prelude
        dag = OntoDAG()
        apply_prelude(dag)
        dag.put("crate", ["weight(3kg)"])
        dag.put("shelf", ["weight(..5kg)"])
        claims = entailed_claims(dag, {"crate", "weight(3kg)", "weight(..5kg)"})
        self.assertIn(("weight(3kg)", "weight(..5kg)"), claims)
        self.assertIn(("crate", "weight(..5kg)"), claims)


if __name__ == "__main__":
    unittest.main()
