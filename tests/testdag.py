import os
import unittest

from ontodag.dag import OntoDAG, OntoDAGVisualizer, Item


class TestOntoDAG(unittest.TestCase):
    def setUp(self):
        self.a = Item('A')
        self.b = Item('B')
        self.c = Item('C')
        self.d = Item('D')
        self.e = Item('E')
        self.f = Item('F')
        self.g = Item('G')
        self.ab = Item('AB')
        self.af = Item('AF')
        self.bc = Item('BC')
        self.cd = Item('CD')
        self.abc = Item('ABC')
        self.abf = Item('ABF')

        self.dag = OntoDAG()
        self.dag.put(self.a, [])
        self.dag.put(self.b, [])
        self.dag.put(self.c, [])
        self.dag.put(self.d, [])
        self.dag.put(self.f, [])
        self.dag.put(self.g, [])
        self.dag.put(self.af, [self.a, self.f])
        self.dag.put(self.ab, [self.a, self.b])
        self.dag.put(self.bc, [self.b, self.c])
        self.dag.put(self.abc, [self.ab, self.bc])
        self.dag.put(self.abf, [self.ab, self.af])
        self.dag.put(self.cd, [self.c, self.d])

    def test_common_subcategories(self):
        query_items = [self.b, self.c]
        common_subcategories = self.dag.get(query_items)
        self.assertEqual(['ABC', 'BC'], sorted([item.name for item in common_subcategories]))

    def test_ancestors_of_AF(self):
        ancestors = self.dag.get_ancestors(self.af, {self.dag.root})
        self.assertIsNotNone(ancestors)
        self.assertEqual(['A', 'F'], sorted([item.name for item in ancestors]))

    def test_descendant_count(self):
        descendants = self.dag.get_descendants(self.a)
        self.assertEqual(4, len(descendants))

    def test_descendant_count_after_put(self):
        self.dag.put(self.e, [self.ab, self.cd], optimized=True)
        descendants = self.dag.get_descendants(self.a)
        visualizer = OntoDAGVisualizer()
        visualizer.visualize(self.dag)
        self.assertEqual(5, len(descendants))

    def test_descendant_count_after_remove(self):
        ancestor_node = self.f
        descendants_before = self.dag.get_descendants(ancestor_node)
        self.assertEqual(2, len(descendants_before))
        self.assertEqual(['ABF', 'AF'], sorted([subcategory.name for subcategory in descendants_before]))

        self.dag.remove(self.af)

        descendants_after = self.dag.get_descendants(ancestor_node)
        self.assertEqual(1, len(descendants_after))
        self.assertEqual(['ABF'], [subcategory.name for subcategory in ancestor_node.neighbors])
        # A -> ABF must NOT be re-added by the contraction: ABF stays reachable
        # via A -> AB -> ABF, and the graph is kept transitively reduced (I2).
        self.assertEqual(['AB'], sorted([subcategory.name for subcategory in self.a.neighbors]))
        self.assertIn(self.abf, self.dag.get_descendants(self.a))

    def test_visualize(self):
        visualizer = OntoDAGVisualizer()
        visualizer.visualize(self.dag)
        self.assertTrue(os.path.isfile('ontodag_vis'))
        self.assertTrue(os.path.isfile('ontodag_vis.png'))
        os.remove('ontodag_vis')
        os.remove('ontodag_vis.png')

    def test_generate_dot_source_to_tex(self):
        from dot2tex import dot2tex
        visualizer = OntoDAGVisualizer()
        dot_source = visualizer.generate_dot_source(self.dag)
        self.assertIsNotNone(dot_source)
        tex_content = dot2tex(dot_source)
        self.assertIsNotNone(tex_content)

    def test_put_optimized(self):
        element_set_query = [self.ab, self.cd]
        self.dag.put(self.e, element_set_query, optimized=True)
        query_items = [self.abc, self.cd]
        common_subcategories = self.dag.get(query_items)
        self.assertEqual(['E'], [item.name for item in common_subcategories])


class TestStringAPI(unittest.TestCase):
    """Names are the identity at the public boundary: plain strings are
    accepted anywhere the API takes an Item, and both forms are
    interchangeable."""

    def setUp(self):
        self.dag = OntoDAG()
        self.dag.put("Animal", [])
        self.dag.put("Pet", [])
        self.dag.put("Dog", ["Animal", "Pet"])
        self.dag.put("Cat", ["Animal", "Pet"])
        self.dag.put("Spaniel", ["Dog"])

    def test_get_with_strings(self):
        names = sorted(item.name for item in self.dag.get(["Animal", "Pet"]))
        self.assertEqual(['Cat', 'Dog', 'Spaniel'], names)

    def test_strings_and_items_are_interchangeable(self):
        self.assertEqual(self.dag.get(["Animal", "Pet"]),
                         self.dag.get([Item("Animal"), Item("Pet")]))
        self.dag.put(Item("Terrier"), ["Dog"])
        self.dag.put("Beagle", [Item("Dog")])
        self.assertEqual({'Terrier', 'Beagle', 'Spaniel'},
                         {i.name for i in self.dag.get(["Dog"])})

    def test_put_unknown_string_parent_raises(self):
        with self.assertRaises(ValueError):
            self.dag.put("X", ["Nope"])

    def test_remove_by_name_reconnects_children(self):
        self.dag.remove("Dog")
        self.assertNotIn("Dog", self.dag.nodes)
        self.assertEqual({'Animal', 'Pet'},
                         {p.name for p in self.dag.nodes["Spaniel"].parents})

    def test_remove_with_fresh_item_resolves_by_name(self):
        # A fresh Item("Dog") has empty parents/neighbors; remove() must
        # resolve it to this instance's node — operating on the caller's
        # object would orphan Dog's children and leave dangling edges.
        self.dag.remove(Item("Dog"))
        self.assertNotIn("Dog", self.dag.nodes)
        self.assertEqual({'Animal', 'Pet'},
                         {p.name for p in self.dag.nodes["Spaniel"].parents})
        self.assertEqual({'Cat', 'Spaniel'},
                         {i.name for i in self.dag.get(["Animal", "Pet"])})

    def test_traversals_accept_strings(self):
        self.assertEqual({'Cat', 'Dog', 'Spaniel'},
                         {i.name for i in self.dag.get_descendants("Animal")})
        self.assertEqual(set(), self.dag.get_descendants("Nope"))
        self.assertEqual({'*', 'Animal', 'Dog', 'Pet'},
                         {i.name for i in self.dag.get_ancestors("Spaniel")})


class TestQueryPlanner(unittest.TestCase):
    """get() plans queries (term elimination, count-ordered traversal, early
    exit); every planning step must be result-preserving. These tests pin the
    results to a brute-force oracle and guard the known unsound "shortcut"
    (rewriting a query through a meet-named node — see docs/SEMANTIC_CODES.md
    §10)."""

    def setUp(self):
        # Same shape as TestOntoDAG's fixture: single letters are top-level
        # categories; a multi-letter name is a node under those categories
        # (e.g. AB sits under A and B) — but it is NOT thereby the meet of
        # its parents: siblings under the same parents may exist.
        self.items = {name: Item(name) for name in
                      ['A', 'B', 'C', 'D', 'F', 'G',
                       'AF', 'AB', 'BC', 'CD', 'ABC', 'ABF']}
        i = self.items
        self.dag = OntoDAG()
        for name in ['A', 'B', 'C', 'D', 'F', 'G']:
            self.dag.put(i[name], [])
        self.dag.put(i['AF'], [i['A'], i['F']])
        self.dag.put(i['AB'], [i['A'], i['B']])
        self.dag.put(i['BC'], [i['B'], i['C']])
        self.dag.put(i['ABC'], [i['AB'], i['BC']])
        self.dag.put(i['ABF'], [i['AB'], i['AF']])
        self.dag.put(i['CD'], [i['C'], i['D']])

    def _brute_force(self, query):
        # The pre-planner semantics of get(): fully materialize every cone,
        # intersect at the end. The oracle the planner must agree with.
        return set.intersection(
            *[self.dag.get_descendants(item) for item in query])

    def test_matches_brute_force_on_all_pairs_and_triples(self):
        from itertools import combinations
        items = list(self.items.values())
        for size in (1, 2, 3):
            for query in combinations(items, size):
                self.assertEqual(
                    self._brute_force(query), self.dag.get(list(query)),
                    f"planner diverged from brute force on {[q.name for q in query]}")

    def test_query_term_order_is_irrelevant(self):
        i = self.items
        self.assertEqual(self.dag.get([i['B'], i['C']]),
                         self.dag.get([i['C'], i['B']]))

    def test_subsumed_terms_are_dropped_without_changing_results(self):
        i = self.items
        # A is an ancestor of AB, so it cannot narrow the result.
        self.assertEqual(self.dag.get([i['AB']]),
                         self.dag.get([i['A'], i['AB']]))
        # Chain: A ⊐ AB ⊐ ABC — only ABC's cone matters.
        self.assertEqual(self.dag.get([i['ABC']]),
                         self.dag.get([i['A'], i['AB'], i['ABC']]))

    def test_meet_named_node_is_not_the_meet(self):
        # X is placed directly under A and B: a *sibling* of AB, invisible to
        # any plan that rewrites get([A, B]) as cone(AB). This test fails
        # loudly if such a rewrite is ever added without the canonical-
        # placement invariant (docs/SEMANTIC_CODES.md §10).
        i = self.items
        x = Item('X')
        self.dag.put(x, [i['A'], i['B']])
        result = {item.name for item in self.dag.get([i['A'], i['B']])}
        self.assertIn('X', result)
        self.assertEqual({'AB', 'ABC', 'ABF', 'X'}, result)

    def test_disjoint_cones_yield_empty_result(self):
        i = self.items
        # G is a leaf: its cone is empty, so any query containing it is empty
        # (and the planner's early exit must not change that).
        self.assertEqual(set(), self.dag.get([i['G'], i['A']]))
        self.assertEqual(set(), self.dag.get([i['D'], i['F']]))

    def test_duplicate_terms_are_deduplicated(self):
        i = self.items
        self.assertEqual(self.dag.get([i['B'], i['C']]),
                         self.dag.get([i['B'], i['C'], Item('B')]))

    def test_unknown_term_returns_empty_set(self):
        self.assertEqual(set(), self.dag.get([self.items['A'], Item('nope')]))

    def test_empty_query_is_everything(self):
        # The empty intersection is the universe: no constraints, so nothing
        # is excluded. Equivalently the root's cone — `get([])`, `get(["*"])`
        # and the CLI's `list` must all be the same question.
        everything = {name for name in self.dag.nodes
                      if name != self.dag.root.name}
        self.assertEqual(everything, {i.name for i in self.dag.get([])})
        self.assertEqual(self.dag.get([]), self.dag.get(["*"]))

    def test_adding_a_term_only_ever_narrows(self):
        # The property that forces the line above: if every term narrows,
        # then no terms at all must be the widest answer there is.
        everything = self.dag.get([])
        for name in self.dag.nodes:
            self.assertTrue(self.dag.get([name]) <= everything)

    # get() chooses adaptively between two exact operators (walk the next
    # cone vs probe the surviving candidates upward); _PROBE_COST_ESTIMATE
    # only steers that choice. Forcing it to each extreme must not change
    # any result — this is what "a bad estimate costs time, never
    # correctness" means, made executable.

    def _assert_matches_brute_force_everywhere(self):
        from itertools import combinations
        items = list(self.items.values())
        for size in (1, 2, 3):
            for query in combinations(items, size):
                self.assertEqual(
                    self._brute_force(query), self.dag.get(list(query)),
                    f"diverged on {[q.name for q in query]} with probe "
                    f"estimate {self.dag._PROBE_COST_ESTIMATE}")

    def test_forced_probe_matches_brute_force(self):
        self.dag._PROBE_COST_ESTIMATE = 0        # probe whenever possible
        self._assert_matches_brute_force_everywhere()

    def test_forced_walk_matches_brute_force(self):
        self.dag._PROBE_COST_ESTIMATE = 10 ** 9  # never probe
        self._assert_matches_brute_force_everywhere()

    def test_all_modes_agree_on_random_dag(self):
        # A larger, seeded (deterministic) DAG so the probe path sees
        # nontrivial ancestor cones, multi-parent diamonds, and skewed
        # cone sizes that the hand-built fixture is too small to produce.
        import random
        rng = random.Random(7)
        dag = OntoDAG()
        items = []
        for n in range(60):
            item = Item(f'N{n:02d}')
            parents = (rng.sample(items, rng.randint(1, min(3, len(items))))
                       if items else [])
            dag.put(item, parents)
            items.append(item)

        def brute_force(query):
            return set.intersection(
                *[dag.get_descendants(item) for item in query])

        queries = [rng.sample(items, rng.randint(2, 4)) for _ in range(40)]
        for estimate in (0, 16, 10 ** 9):
            dag._PROBE_COST_ESTIMATE = estimate
            for query in queries:
                self.assertEqual(
                    brute_force(query), dag.get(query),
                    f"diverged on {[q.name for q in query]} with probe "
                    f"estimate {estimate}")


class TestVisualizerRendersEveryName(unittest.TestCase):
    """Parametric canonical names contain characters DOT gives meaning to.

    A timestamp range like time(2026-...T00:00:00Z..) used as a DOT node
    *identifier* is split by the graphviz package's quoting at the `:` it
    reads as a port separator, and the render dies with a syntax error —
    which is exactly what happened to `odag visualize` and the web app's
    /dag/image once dimensions shipped. Names therefore live in labels and
    identifiers are synthetic. This is the regression guard."""

    def setUp(self):
        try:
            import graphviz  # noqa: F401
        except ImportError:
            self.skipTest("graphviz not installed")
        self.dag = OntoDAG()
        for name, parents in (("dimension", []),
                              ("calendar-dimension", ["dimension"]),
                              ("linear-dimension", ["dimension"]),
                              ("time", ["calendar-dimension"]),
                              ("weight", ["linear-dimension"])):
            self.dag.put(name, parents)
        self.dag.put("doc", ["time(2026-08-15)", "weight(3kg)"])

    def test_dot_source_carries_names_as_labels(self):
        source = OntoDAGVisualizer().generate_dot_source(self.dag)
        # The full canonical name survives, intact, inside a quoted label...
        self.assertIn(
            '"time(2026-08-15T00:00:00Z..2026-08-15T23:59:59Z): 1"', source)
        # ...and never appears as a bare identifier before an edge arrow.
        for line in source.splitlines():
            if "->" in line:
                self.assertNotIn("(", line, f"name used as an id: {line}")

    def test_the_image_actually_renders(self):
        # The end-to-end check: graphviz's `dot` has to accept the source.
        # Without this the bug is invisible — bad DOT is only a syntax error
        # once something parses it.
        try:
            image = OntoDAGVisualizer().generate_image(self.dag)
        except ImportError:
            self.skipTest("PIL not installed")
        self.assertGreater(image.size[0], 0)


if __name__ == '__main__':
    unittest.main()
