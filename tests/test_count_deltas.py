"""I5 under stress: descendant_count is maintained by *delta*, not recompute.

`_update_descendant_counts` used to re-derive every affected ancestor's count
with `len(get_descendants(X))`. Since the root is an ancestor of everything,
that enumerated the whole graph on every write. The counts are now maintained
incrementally (`_plan_add`/`_plan_remove`, plus the operation-level rules in
`OntoDAG.add_edge`/`remove`), which is dramatically cheaper but has far more
ways to be subtly wrong — so the oracle (brute-force recount of every node)
is asserted after *every single operation*, not just at the end.

The hand-written cases below are the ones that broke earlier versions of the
algorithm; the fuzz is what would catch the next mistake.
"""

import random
import unittest

from ontodag import Item, OntoDAG


def counts(dag):
    return {name: node.descendant_count for name, node in dag.nodes.items()}


def oracle(dag):
    return {name: len(dag.get_descendants(node))
            for name, node in dag.nodes.items()}


class CountAssertions(unittest.TestCase):
    def assertExact(self, dag, label=""):
        truth, got = oracle(dag), counts(dag)
        if truth != got:
            wrong = {k: (got.get(k), truth.get(k))
                     for k in set(truth) | set(got) if got.get(k) != truth.get(k)}
            self.fail(f"stale counts after {label}: (got, expected) = {wrong}")


class TestKnownTraps(CountAssertions):
    """Cases that each broke a draft of the delta rules."""

    def test_overlapping_cones_are_not_double_counted(self):
        """A node reachable by two paths is one descendant, not two: naive
        per-edge deltas summed to Animal(5) where the truth is 4."""
        dag = OntoDAG()
        dag.put(Item("Animal"), [])
        dag.put(Item("Dog"), [Item("Animal")])
        dag.put(Item("Pet"), [Item("Animal")])
        dag.put(Item("Spaniel"), [Item("Dog"), Item("Pet")])
        self.assertExact(dag, "diamond")
        dag.put(Item("Beagle"), [Item("Dog"), Item("Pet")])
        self.assertExact(dag, "second diamond leaf")
        self.assertEqual(dag.nodes["Animal"].descendant_count, 4)

    def test_transitive_reduction_during_add_is_count_neutral(self):
        """`_remove_unneeded_edges` runs *before* the new edge exists, so an
        ancestor momentarily stops reaching the child. Planning the delta
        after the reduction read that as a fresh gain and drifted upward."""
        dag = OntoDAG()
        dag.put(Item("A"), [])
        dag.put(Item("B"), [Item("A")])
        dag.put(Item("C"), [Item("A")])         # A -> C direct
        self.assertExact(dag, "before reduction")
        dag.put(Item("C"), [Item("B")])         # now A -> B -> C; A -> C is dropped
        self.assertExact(dag, "reduction triggered")

    def test_remove_contracts_and_loses_exactly_one_per_ancestor(self):
        """Contraction reconnects children to parents, so nothing below the
        removed node becomes unreachable."""
        dag = OntoDAG()
        dag.put(Item("A"), [])
        dag.put(Item("mid"), [Item("A")])
        dag.put(Item("leaf1"), [Item("mid")])
        dag.put(Item("leaf2"), [Item("mid")])
        before = dag.nodes["A"].descendant_count
        dag.remove("mid")
        self.assertExact(dag, "remove intermediate")
        self.assertEqual(dag.nodes["A"].descendant_count, before - 1)

    def test_remove_with_multiple_parents(self):
        dag = OntoDAG()
        for name in ("A", "B"):
            dag.put(Item(name), [])
        dag.put(Item("mid"), [Item("A"), Item("B")])
        dag.put(Item("leaf"), [Item("mid")])
        dag.remove("mid")
        self.assertExact(dag, "remove diamond middle")

    def test_cross_link_between_existing_subtrees(self):
        """Adding an edge between existing nodes: ancestors that could already
        reach the target gain nothing, ancestors that could not gain the whole
        newly-reachable subtree minus what they already had."""
        dag = OntoDAG()
        dag.put(Item("Animal"), [])
        dag.put(Item("Dog"), [Item("Animal")])
        dag.put(Item("Spaniel"), [Item("Dog")])
        dag.put(Item("Pet"), [])
        self.assertExact(dag, "setup")
        dag.put(Item("Dog"), [Item("Pet")])     # Pet gains Dog + Spaniel
        self.assertExact(dag, "cross-link")
        self.assertEqual(dag.nodes["Pet"].descendant_count, 2)

    def test_merge_keeps_counts_exact(self):
        left, right = OntoDAG(), OntoDAG()
        for dag in (left, right):
            dag.put(Item("Animal"), [])
        left.put(Item("Dog"), [Item("Animal")])
        right.put(Item("Cat"), [Item("Animal")])
        right.put(Item("Kitten"), [Item("Cat")])
        left.merge(right)
        self.assertExact(left, "merge")


class TestFuzz(CountAssertions):
    """Randomised operation sequences, oracle-checked after every step."""

    def _run(self, seed, rounds=120):
        rng = random.Random(seed)
        dag = OntoDAG()
        for i in range(rounds):
            live = [n for n in dag.nodes if n != dag.root.name]
            roll = rng.random()
            if roll < 0.6 or len(live) < 4:
                supers = rng.sample(live, min(len(live), rng.randint(1, 3)))
                dag.put(Item(f"n{i}"), [Item(s) for s in supers])
                self.assertExact(dag, f"put n{i} under {supers} (seed {seed})")
            elif roll < 0.85:
                child = rng.choice(live)
                # one super at a time: a multi-super put can add one edge and
                # then raise on a cycle for the next, which would leave the
                # assertion pointing at a half-applied operation
                sup = rng.choice(live)
                if sup == child:
                    continue
                try:
                    dag.put(Item(child), [Item(sup)])
                except ValueError:
                    continue                    # would create a cycle
                self.assertExact(dag, f"cross-link {child} under {sup} (seed {seed})")
            else:
                victim = rng.choice(live)
                dag.remove(victim)
                self.assertExact(dag, f"remove {victim} (seed {seed})")

    def test_fuzz_many_seeds(self):
        for seed in range(12):
            self._run(seed)


if __name__ == "__main__":
    unittest.main()
