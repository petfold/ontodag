"""Invariant tests for OntoDAG.

These tests encode the structural invariants the data structure promises:

  I1  Acyclicity            - no edge insertion may create a cycle
  I2  Transitive reduction  - no edge u->v may coexist with a longer u~>v path
  I3  Order independence    - results must not depend on argument or insertion order
  I4  No aliasing           - derived DAGs must not share mutable Item objects
  I5  Counter consistency   - descendant_count always equals the true count
  I6  Scalability           - traversals must not hit Python's recursion limit
  I7  Merge algebra         - merge is commutative and idempotent (CRDT property)

Several of these tests FAIL against the current implementation by design:
each failure is a reproduction of a concrete bug, to be fixed afterwards.

Helpers below compute reachability independently (iterative BFS over the raw
neighbor sets), so they do not depend on the traversal code under test.
"""

import unittest

from ontodag.dag import DAG, OntoDAG, Item


# ----------------------------------------------------------------------------
# Independent helpers (deliberately NOT using DAG.get_descendants/get_ancestors)
# ----------------------------------------------------------------------------

def reach(node):
    """All nodes strictly reachable from `node`, via iterative BFS."""
    seen = set()
    frontier = list(node.neighbors)
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        frontier.extend(current.neighbors)
    return seen


def edge_set(dag):
    """Canonical, hashable representation of the DAG's edges."""
    return frozenset(
        (parent.name, child.name)
        for parent in dag.nodes.values()
        for child in parent.neighbors
    )


def assert_acyclic(testcase, dag):
    for node in dag.nodes.values():
        testcase.assertNotIn(
            node, reach(node),
            f"Cycle detected through node {node.name!r}",
        )


def assert_transitively_reduced(testcase, dag):
    """For every edge u->v there must be no other path from u to v."""
    for u in dag.nodes.values():
        for v in u.neighbors:
            for w in u.neighbors:
                if w is v:
                    continue
                testcase.assertNotIn(
                    v, reach(w) | {w},
                    f"Edge {u.name!r}->{v.name!r} is redundant: "
                    f"also reachable via {u.name!r}->{w.name!r}~>...",
                )


def assert_counts_consistent(testcase, dag):
    for node in dag.nodes.values():
        testcase.assertEqual(
            len(reach(node)), node.descendant_count,
            f"descendant_count of {node.name!r} is stale",
        )


def build(puts):
    """Build an OntoDAG from a list of (name, [super names]) put operations."""
    dag = OntoDAG()
    for name, supers in puts:
        dag.put(Item(name), [Item(s) for s in supers])
    return dag


# ----------------------------------------------------------------------------
# I1 - Acyclicity
# ----------------------------------------------------------------------------

class TestAcyclicity(unittest.TestCase):
    def test_put_rejects_cycle(self):
        """Re-putting an ancestor under its own descendant must be rejected.

        BUG (current code): add_edge performs no reachability check, so
        put(A, [B]) with B below A silently creates the cycle A->B->A.
        """
        dag = build([("A", []), ("B", ["A"])])
        with self.assertRaises(ValueError):
            dag.put(Item("A"), [Item("B")])
        assert_acyclic(self, dag)

    def test_add_edge_rejects_self_ancestor(self):
        dag = build([("A", []), ("B", ["A"]), ("C", ["B"])])
        with self.assertRaises(ValueError):
            dag.add_edge(dag.nodes["C"], dag.nodes["A"])
        assert_acyclic(self, dag)


# ----------------------------------------------------------------------------
# I2 + I3 - Transitive reduction, independent of argument order
# ----------------------------------------------------------------------------

class TestTransitiveReduction(unittest.TestCase):
    def test_reput_under_ancestor_stays_reduced(self):
        """With root->A->B->X in place, put(X, [A]) must not add edge A->X.

        BUG (current code): _remove_unneeded_edges only prunes edges from
        ancestors of the new parent; it never checks whether the new edge
        itself is redundant, so A->X is added alongside A->B->X.
        """
        dag = build([("A", []), ("B", ["A"]), ("X", ["B"])])
        dag.put(Item("X"), [Item("A")])
        assert_transitively_reduced(self, dag)
        self.assertNotIn(dag.nodes["X"], dag.nodes["A"].neighbors)

    def test_put_super_order_does_not_matter(self):
        """put(X, [A, B]) and put(X, [B, A]) must produce identical graphs.

        BUG (current code): with B below A, the order [B, A] leaves the
        redundant edge A->X in place while [A, B] correctly prunes it.
        """
        base = [("A", []), ("B", ["A"])]
        dag_ab = build(base + [("X", ["A", "B"])])
        dag_ba = build(base + [("X", ["B", "A"])])
        self.assertEqual(edge_set(dag_ab), edge_set(dag_ba))
        assert_transitively_reduced(self, dag_ab)
        assert_transitively_reduced(self, dag_ba)

    def test_new_edge_prunes_the_edges_it_bypasses(self):
        """Adding p->Z must prune the pre-existing p->B once Z reaches B.

        BUG (pre-fix, 2026-08-04): _remove_unneeded_edges pruned only
        upward/same-child — edges from ancestors of the new parent INTO the
        new child. An existing edge whose redundancy witness runs THROUGH
        the new edge (p->Z->B) was kept, so the stored form was not the
        transitive reduction, and which form you got depended on insertion
        order — the shape behind the order-dependent multi-writer merge.
        """
        dag = build([("p", []), ("Z", []), ("B", ["p", "Z"])])
        dag.put(Item("Z"), [Item("p")])
        assert_transitively_reduced(self, dag)
        self.assertNotIn(dag.nodes["B"], dag.nodes["p"].neighbors)
        assert_counts_consistent(self, dag)

    def test_bypassed_grandparent_edge_is_pruned_too(self):
        """The downward prune must cover every ancestor of the new parent:
        with g->p and g->B in place, adding p->Z (where Z->B exists) makes
        g->B redundant via g->p->Z->B."""
        dag = build([("g", []), ("p", ["g"]), ("Z", []), ("B", ["g", "Z"])])
        dag.put(Item("Z"), [Item("p")])
        assert_transitively_reduced(self, dag)
        self.assertNotIn(dag.nodes["B"], dag.nodes["g"].neighbors)
        assert_counts_consistent(self, dag)

    def test_remove_preserves_reduction(self):
        """Contracting a node (reconnect supers to subs) must stay reduced."""
        dag = build([
            ("A", []), ("B", ["A"]), ("M", ["A", "B"]),
            ("S1", ["M"]), ("S2", ["M", "B"]),
        ])
        dag.remove(dag.nodes["M"])
        assert_acyclic(self, dag)
        assert_transitively_reduced(self, dag)
        assert_counts_consistent(self, dag)


# ----------------------------------------------------------------------------
# I4 - No aliasing between a DAG and DAGs derived from it
# ----------------------------------------------------------------------------

class TestNoAliasing(unittest.TestCase):
    def test_intersection_dag_is_independent_copy(self):
        """Mutating the intersection DAG must not mutate the source DAGs.

        BUG (current code): intersection_dag inserts the *original* Item
        objects of the source DAG into the result (unlike copy_subdag,
        which maps to fresh copies), so edits to the result write through
        to the source.
        """
        dag1 = build([("A", []), ("B", ["A"]), ("C", ["A"])])
        dag2 = build([("A", []), ("B", ["A"]), ("D", ["A"])])

        before = edge_set(dag1)
        inter = dag1.intersection_dag(dag2)

        # Mutate the derived DAG only.
        if "B" in inter.nodes and "A" in inter.nodes:
            inter.nodes["A"].neighbors.discard(inter.nodes["B"])

        self.assertEqual(
            before, edge_set(dag1),
            "intersection_dag aliases Item objects of the source DAG",
        )

    def test_intersection_nodes_are_fresh_objects(self):
        dag1 = build([("A", []), ("B", ["A"])])
        dag2 = build([("A", []), ("B", ["A"])])
        inter = dag1.intersection_dag(dag2)
        for name, node in inter.nodes.items():
            if name == inter.root.name:
                continue
            self.assertIsNot(
                node, dag1.nodes.get(name),
                f"Node {name!r} in intersection is the same object as in dag1",
            )


# ----------------------------------------------------------------------------
# I5 - descendant_count consistency through put/remove sequences
# ----------------------------------------------------------------------------

class TestCounters(unittest.TestCase):
    def test_counts_after_mixed_operations(self):
        dag = build([
            ("A", []), ("B", []), ("AB", ["A", "B"]),
            ("C", ["A"]), ("X", ["AB", "C"]),
        ])
        assert_counts_consistent(self, dag)
        dag.remove(dag.nodes["AB"])
        assert_counts_consistent(self, dag)
        dag.put(Item("Y"), [Item("C")])
        assert_counts_consistent(self, dag)


# ----------------------------------------------------------------------------
# I6 - traversals must survive deep graphs (no RecursionError)
# ----------------------------------------------------------------------------

class TestDeepGraphs(unittest.TestCase):
    DEPTH = 1500  # comfortably above CPython's default recursion limit

    def _make_chain(self):
        """Build a deep chain directly (bypassing put, which is too slow
        for setup at this size) - this isolates the traversal code."""
        dag = DAG()
        prev = Item("n0")
        dag.add_node(prev)
        for i in range(1, self.DEPTH):
            node = Item(f"n{i}")
            dag.add_node(node)
            prev.neighbors.add(node)
            prev = node
        return dag

    def test_get_descendants_is_iterative(self):
        """BUG (current code): get_descendants recurses once per level and
        raises RecursionError beyond ~1000 levels."""
        dag = self._make_chain()
        descendants = dag.get_descendants(dag.nodes["n0"])
        self.assertEqual(len(descendants), self.DEPTH - 1)

    def test_get_ancestors_is_iterative(self):
        """BUG (current code): _get_ancestors_helper recurses per level."""
        dag = self._make_chain()
        ancestors = dag.get_ancestors(dag.nodes[f"n{self.DEPTH - 1}"])
        self.assertEqual(len(ancestors), self.DEPTH - 1)

    def test_topological_sort_is_iterative(self):
        dag = self._make_chain()
        order = dag.topological_sort()
        self.assertEqual(len(order), self.DEPTH)
        self.assertEqual(order[0].name, "n0")
        self.assertEqual(order[-1].name, f"n{self.DEPTH - 1}")

    def test_topological_sort_parents_precede_children(self):
        dag = build([
            ("A", []), ("B", []), ("AB", ["A", "B"]),
            ("C", ["A"]), ("X", ["AB", "C"]),
        ])
        position = {node.name: i for i, node in enumerate(dag.topological_sort())}
        self.assertEqual(len(position), len(dag.nodes))
        for node in dag.nodes.values():
            for child in node.neighbors:
                self.assertLess(position[node.name], position[child.name],
                                f"{node.name} must come before {child.name}")


class TestTopologicalSortIsDeterministic(unittest.TestCase):
    """Equal content must give the equal order, whatever the build history.

    `neighbors` is a set, so an unsorted walk picks a different (still valid)
    topological order per process -- string hashing is randomized. Consumers
    that order their *output* by this function (`odag show`, the OWL and
    Manchester exports) were therefore undiffable across runs for identical
    content, which contradicts the canonical-form story the rest of the
    design rests on. Names are the identity at every boundary, so name order
    is the canonical choice.
    """

    HISTORIES = [
        [("Animal", []), ("Machine", []), ("Pet", []),
         ("Dog", ["Animal", "Pet"]), ("Cat", ["Animal", "Pet"]),
         ("Aibo", ["Machine", "Pet"])],
        # Same content, different insertion order and different parent order.
        [("Machine", []), ("Pet", []), ("Animal", []),
         ("Aibo", ["Pet", "Machine"]), ("Cat", ["Pet", "Animal"]),
         ("Dog", ["Pet", "Animal"])],
    ]

    def test_same_content_same_order(self):
        orders = [[n.name for n in build(h).topological_sort()]
                  for h in self.HISTORIES]
        self.assertEqual(orders[0], orders[1])

    def test_order_is_stable_across_repeated_calls(self):
        dag = build(self.HISTORIES[0])
        first = [n.name for n in dag.topological_sort()]
        for _ in range(5):
            self.assertEqual([n.name for n in dag.topological_sort()], first)

    def test_root_first_and_names_ascending_within_the_order(self):
        order = [n.name for n in build(self.HISTORIES[0]).topological_sort()]
        self.assertEqual(order[0], "*")
        # Ties (nodes at the same depth) resolve alphabetically, which is what
        # makes `odag show` read sensibly rather than merely reproducibly.
        self.assertEqual(order, ["*", "Animal", "Machine", "Pet",
                                 "Aibo", "Cat", "Dog"])


# ----------------------------------------------------------------------------
# Name-identity at the public boundary: traversals must resolve the caller's
# Item by name, not walk the caller's object (whose edges may be empty).
# ----------------------------------------------------------------------------

class TestQueriesWithFreshItems(unittest.TestCase):
    def _dag(self):
        return build([
            ("vehicle", []), ("electric", []),
            ("car", ["vehicle"]), ("ev", ["car", "electric"]),
        ])

    def test_get_with_fresh_items_matches_live_nodes(self):
        dag = self._dag()
        live = dag.get([dag.nodes["vehicle"], dag.nodes["electric"]])
        fresh = dag.get([Item("vehicle"), Item("electric")])
        self.assertEqual({i.name for i in fresh}, {i.name for i in live})
        self.assertEqual({i.name for i in fresh}, {"ev"})

    def test_get_descendants_with_fresh_item(self):
        dag = self._dag()
        names = {i.name for i in dag.get_descendants(Item("vehicle"))}
        self.assertEqual(names, {"car", "ev"})

    def test_get_ancestors_with_fresh_item(self):
        dag = self._dag()
        names = {i.name for i in dag.get_ancestors(Item("ev"), {dag.root})}
        self.assertEqual(names, {"car", "vehicle", "electric"})


# ----------------------------------------------------------------------------
# I7 - merge algebra (the property the multi-writer / CRDT story rests on)
# ----------------------------------------------------------------------------

class TestMergeAlgebra(unittest.TestCase):
    def _dag_one(self):
        return build([
            ("vehicle", []), ("electric", []),
            ("car", ["vehicle"]), ("ev", ["car", "electric"]),
        ])

    def _dag_two(self):
        return build([
            ("vehicle", []), ("bike", ["vehicle"]),
            ("electric", []), ("ebike", ["bike", "electric"]),
        ])

    def test_merge_commutative(self):
        left = self._dag_one()
        left.merge(self._dag_two())
        right = self._dag_two()
        right.merge(self._dag_one())
        self.assertEqual(edge_set(left), edge_set(right))
        assert_transitively_reduced(self, left)
        assert_acyclic(self, left)

    def test_merge_idempotent(self):
        dag = self._dag_one()
        before = edge_set(dag)
        dag.merge(self._dag_one())
        self.assertEqual(before, edge_set(dag))


if __name__ == "__main__":
    unittest.main()


# ----------------------------------------------------------------------------
# Cone removal — the *other* removal, held to every invariant above
# ----------------------------------------------------------------------------

class TestConeRemoval(unittest.TestCase):
    """`remove_cone` deletes; `remove` contracts. Both must leave the graph
    exactly as sound as they found it.

    The survival rule is the part that could be wrong in a multi-parent DAG, so
    it is checked against an independent oracle: a cone member must be deleted
    iff the root can no longer reach it once the targets are gone.
    """

    def _travel(self):
        return build([
            ("Travel", []), ("Japan", []),
            ("Flight", ["Travel"]), ("Hotel", ["Travel"]),
            ("JAL", ["Flight", "Japan"]), ("JAL-cheap", ["JAL"]),
            ("Ryokan", ["Hotel", "Japan"]), ("Onsen", ["Japan"]),
            ("BA", ["Flight"]),
        ])

    def _random(self, seed, n=30):
        import random
        rnd = random.Random(seed)
        dag = OntoDAG()
        names = [f"n{i}" for i in range(n)]
        for index, name in enumerate(names):
            pool = names[:index]
            dag.put(name, rnd.sample(pool,
                                     min(len(pool), rnd.choice([0, 1, 1, 2, 3]))))
        return dag, names

    def _reachable_avoiding(self, dag, banned):
        """Independent oracle: what the root still sees with `banned` gone."""
        seen, frontier = set(), [dag.root]
        while frontier:
            node = frontier.pop()
            for child in node.neighbors:
                if child.name in banned or child.name in seen:
                    continue
                seen.add(child.name)
                frontier.append(child)
        return seen

    def test_multi_parent_members_survive(self):
        dag = self._travel()
        cone, deleted = dag.cone_removal_plan(["Japan"])
        self.assertEqual(cone, {"Japan", "JAL", "JAL-cheap", "Ryokan", "Onsen"})
        self.assertEqual(deleted, {"Japan", "Onsen"})
        self.assertEqual(dag.remove_cone(["Japan"]), {"Japan", "Onsen"})
        self.assertEqual(set(dag.nodes) - {"*"},
                         {"Travel", "Flight", "Hotel", "JAL", "JAL-cheap",
                          "Ryokan", "BA"})

    def test_survivors_are_detached_never_contracted(self):
        # Contraction would file JAL under Japan's parents — a claim nobody
        # made. Here Japan's parent is Asia, so the mistake would be visible.
        dag = build([
            ("Asia", []), ("Japan", ["Asia"]), ("Travel", []),
            ("Flight", ["Travel"]), ("JAL", ["Flight", "Japan"]),
        ])
        dag.remove_cone(["Japan"])
        self.assertEqual({p.name for p in dag.nodes["JAL"].parents
                          if dag.nodes.get(p.name) is p}, {"Flight"})
        self.assertNotIn("Asia", {p.name for p in dag.nodes["JAL"].parents})

    def test_the_whole_cone_can_go(self):
        dag = build([("A", []), ("B", ["A"]), ("C", ["B"]), ("D", [])])
        self.assertEqual(dag.remove_cone(["A"]), {"A", "B", "C"})
        self.assertEqual(set(dag.nodes) - {"*"}, {"D"})

    def test_several_targets_at_once(self):
        # X survives Japan alone (it is also a Flight) but not Japan+Flight.
        dag = self._travel()
        self.assertEqual(dag.remove_cone(["Japan", "Flight"]),
                         {"Japan", "Flight", "Onsen", "JAL", "JAL-cheap", "BA"})
        self.assertEqual(set(dag.nodes) - {"*"},
                         {"Travel", "Hotel", "Ryokan"})

    def test_invariants_hold_over_random_deletions(self):
        import random
        for seed in range(25):
            dag, names = self._random(seed)
            targets = [n for n in random.Random(seed + 100).sample(
                names, random.Random(seed).choice([1, 2, 3])) if n in dag.nodes]
            cone, deleted = dag.cone_removal_plan(targets)

            survivors = self._reachable_avoiding(dag, set(targets))
            self.assertEqual(deleted, {n for n in cone if n not in survivors},
                             f"seed {seed}: survival rule disagrees with the "
                             f"reachability oracle")

            self.assertEqual(dag.remove_cone(targets), deleted)
            assert_acyclic(self, dag)
            assert_transitively_reduced(self, dag)
            assert_counts_consistent(self, dag)          # I5
            for name, node in dag.nodes.items():
                for parent in node.parents:
                    self.assertIs(dag.nodes.get(parent.name), parent,
                                  f"seed {seed}: {name} kept a dangling parent")
                    self.assertIn(node, parent.neighbors)
                for child in node.neighbors:
                    self.assertIs(dag.nodes.get(child.name), child)
                    self.assertIn(node, child.parents)

    def test_a_deleted_name_can_be_used_again(self):
        # The trap a naive implementation falls into: Item equality is by name,
        # so a stale parent reference left behind by a sloppy delete SHADOWS the
        # re-added node — the graph then reads correct downward, wrong upward.
        dag = self._travel()
        dag.remove_cone(["Japan"])
        dag.put("Japan", [])
        dag.put("JAL", ["Japan"])
        self.assertEqual({p.name for p in dag.nodes["JAL"].parents
                          if dag.nodes.get(p.name) is p}, {"Flight", "Japan"})
        assert_counts_consistent(self, dag)

    def test_the_root_and_unknown_names_are_refused_before_anything_moves(self):
        dag = self._travel()
        before = edge_set(dag)
        for bad in (["*"], ["Japan", "nope"], ["nope"]):
            with self.assertRaises(ValueError):
                dag.remove_cone(bad)
            self.assertEqual(edge_set(dag), before)
            with self.assertRaises(ValueError):
                dag.cone_removal_plan(bad)

    def test_the_plan_changes_nothing(self):
        dag = self._travel()
        before = edge_set(dag)
        dag.cone_removal_plan(["Japan", "Flight"])
        self.assertEqual(edge_set(dag), before)

    def test_asserted_only_so_a_typed_value_sweeps_nothing_extra(self):
        # The computed order is derived from names; deleting by it would take
        # every finer value ever filed, which no stored edge asserted.
        from ontodag.prelude import apply as apply_prelude
        dag = OntoDAG()
        apply_prelude(dag)
        dag.put("crate", ["weight(3kg)"])
        dag.put("pallet", ["weight(..5kg)"])
        cone, deleted = dag.cone_removal_plan(["weight(..5kg)"])
        self.assertEqual(cone, {"weight(..5kg)", "pallet"})
        self.assertNotIn("crate", deleted)
        self.assertNotIn("weight(3kg)", deleted)
        dag.remove_cone(["weight(..5kg)"])
        self.assertIn("crate", dag.nodes)
        assert_counts_consistent(self, dag)


class TestReclassify(unittest.TestCase):
    """`reclassify` is the retracting counterpart of `put` — the operation a
    lifecycle needs (`active` -> `archive`).

    What it must never do: leave the graph half-moved on a refusal, orphan
    anything, or produce a placement `put` itself would refuse.
    """

    def _projects(self):
        return build([
            ("active", []), ("archive", []),
            ("A", ["active"]), ("B", ["active"]),
            ("C", ["A", "B"]), ("a-only", ["A"]), ("b-only", ["B"]),
        ])

    def _parents(self, dag, name):
        return {p.name for p in dag.nodes[name].parents
                if dag.nodes.get(p.name) is p}

    def test_the_subtree_travels_with_it(self):
        dag = self._projects()
        self.assertEqual(dag.reclassify(["A"], to=["archive"], from_=["active"]),
                         {("active", "A")})
        self.assertEqual({i.name for i in dag.get(["archive"])},
                         {"A", "C", "a-only"})
        self.assertEqual({i.name for i in dag.get(["active"])},
                         {"B", "C", "b-only"})

    def test_a_shared_child_ends_up_in_both_states(self):
        # Not a bug: C really is part of an archived project and a live one.
        # Subsumption inherits; exclusive status cannot.
        dag = self._projects()
        dag.reclassify(["A"], to=["archive"], from_=["active"])
        self.assertEqual({i.name for i in dag.get(["active", "archive"])}, {"C"})
        assert_counts_consistent(self, dag)
        assert_transitively_reduced(self, dag)

    def test_to_alone_replaces_every_classification(self):
        dag = self._projects()
        dag.reclassify(["C"], to=["archive"])
        self.assertEqual(self._parents(dag, "C"), {"archive"})

    def test_from_alone_unfiles_and_never_orphans(self):
        dag = self._projects()
        dag.reclassify(["A"], from_=["active"])
        self.assertEqual(self._parents(dag, "A"), {"*"})
        self.assertIn("A", {i.name for i in dag.get([])})    # still visible
        assert_counts_consistent(self, dag)

    def test_moving_to_a_finer_category_under_the_same_parent(self):
        # Adding the new parent makes the old edge redundant, so reduction
        # prunes it before the retraction gets there. That must count as done.
        dag = build([("active", []), ("recent", ["active"]), ("X", ["active"])])
        dag.reclassify(["X"], to=["recent"], from_=["active"])
        self.assertEqual(self._parents(dag, "X"), {"recent"})
        self.assertTrue(dag.is_below("X", "active"))         # still, by entailment
        assert_transitively_reduced(self, dag)

    def test_invariants_hold_and_nothing_moves_on_a_refusal(self):
        cases = [
            (["A"], ["B"], None),                      # would create a cycle
            (["A"], ["nowhere"], None),                # unknown destination
            (["nope"], ["archive"], None),             # unknown item
            (["*"], ["archive"], None),                # the root
            (["C"], ["archive"], ["active"]),          # not a direct parent
            (["A"], ["archive"], ["nowhere"]),         # unknown source
        ]
        dag = build([("active", []), ("archive", []), ("A", ["active"]),
                     ("B", ["A"]), ("C", ["A"])])
        before = edge_set(dag)
        for items, to, from_ in cases:
            with self.assertRaises(ValueError, msg=f"{items} -> {to}"):
                dag.reclassify(items, to=to, from_=from_)
            self.assertEqual(edge_set(dag), before, f"{items} -> {to} mutated")
        assert_counts_consistent(self, dag)

    def test_the_inherited_case_says_what_to_do_instead(self):
        dag = self._projects()
        with self.assertRaises(ValueError) as caught:
            dag.reclassify(["C"], to=["archive"], from_=["active"])
        self.assertIn("not filed directly under active", str(caught.exception))
        self.assertIn("A, B", str(caught.exception))

    def test_a_placement_put_refuses_is_not_reachable_by_moving(self):
        from ontodag.prelude import apply as apply_prelude
        dag = OntoDAG()
        apply_prelude(dag)
        dag.put("shelf", [])
        dag.put("crate", ["weight(3kg)", "shelf"])
        with self.assertRaises(ValueError) as caught:
            dag.reclassify(["crate"], to=["weight(10kg)"], from_=["shelf"])
        self.assertIn("provably disjoint", str(caught.exception))
        # ...and the refusal left no new vocabulary behind
        self.assertNotIn("weight(10kg)", dag.nodes)
        # replacing the value instead is fine, and materializes it
        dag.reclassify(["crate"], to=["weight(10kg)"])
        self.assertEqual(self._parents(dag, "crate"), {"weight(10kg)"})
        assert_counts_consistent(self, dag)

    def test_counts_and_reduction_survive_random_moves(self):
        import random
        for seed in range(15):
            rnd = random.Random(seed)
            dag = OntoDAG()
            names = [f"n{i}" for i in range(20)]
            for index, name in enumerate(names):
                pool = names[:index]
                dag.put(name, rnd.sample(pool, min(len(pool),
                                                   rnd.choice([0, 1, 2]))))
            for _ in range(6):
                item, destination = rnd.sample(names, 2)
                try:
                    dag.reclassify([item], to=[destination])
                except ValueError:
                    continue                     # cycles are legitimately refused
                assert_acyclic(self, dag)
                assert_transitively_reduced(self, dag)
                assert_counts_consistent(self, dag)
                for name in dag.nodes:
                    self.assertTrue(
                        name == dag.root.name or self._parents(dag, name),
                        f"seed {seed}: {name} was orphaned")
