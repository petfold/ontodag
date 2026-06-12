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
