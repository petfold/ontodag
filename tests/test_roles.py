"""Role heads over a base dimension (docs/DIMENSIONS.md §14, issue #15).

A head declared under another head — `from` under `geo`, `when` under
`time` — is a ROLE of that dimension: it shares the kind and the value
space, and its parameters may be values of the base (`from(u2e4x)`) or
NODES filed in the base dimension: a place under a cell, a region above
cells, a floor under a building. The order between role terms is then the
graph's own order in the base dimension. Nothing is stored beyond the name
as spelled, nothing is materialized, and the order follows the catalogue.

Oracle discipline as in tests/test_invariants.py: `edge_set` reads the raw
neighbor sets, independent of the traversals under test."""

import unittest

from ontodag import prelude, surface
from ontodag.dag import OntoDAG
from ontodag.eager import EagerOntoDAG
from ontodag.lazy import LazyOntoDAG, SparseOntoDAG
from recordstore import MemoryBytesStore, RecordStore


def names(items):
    return {item.name for item in items}


def edge_set(dag):
    return {(parent.name, child.name)
            for parent in dag.nodes.values() for child in parent.neighbors}


def make_dag(dag=None):
    """The issue's catalogue: a region above two cells, a place under a
    finer cell, and `from` declared as a role of `geo`."""
    dag = dag if dag is not None else OntoDAG()
    prelude.apply(dag)
    dag.put("ljubljana", [])
    dag.put("geo(u2e4)", ["ljubljana"])
    dag.put("geo(u2e5)", ["ljubljana"])
    dag.put("my_home", ["geo(u2e4x)"])
    dag.put("from", ["geo"])
    return dag


def with_offers(dag):
    dag.put("offer", ["from(my_home)"])       # a place as the parameter
    dag.put("offer2", ["from(u2e5)"])         # a value, as before
    dag.put("ride", ["from(ljubljana)"])      # a region as the parameter
    return dag


class TestRoleParameters(unittest.TestCase):
    def test_the_issue_scenario(self):
        d = make_dag()
        self.assertEqual(d._dimension_of("from"), ("prefix-dimension", "geo"))
        self.assertEqual(d._dimension_of("geo"), ("prefix-dimension", "geo"))
        self.assertTrue(d.is_below("from(ljubljana)", "from(ljubljana)"))
        # The line the issue reports as False: my_home sits under u2e4x.
        self.assertTrue(d.is_below("from(my_home)", "from(u2e4)"))
        self.assertTrue(d.is_below("from(my_home)", "from(ljubljana)"))
        self.assertFalse(d.is_below("from(ljubljana)", "from(my_home)"))
        # A region covers its cells: any cell in it (or finer) is below it.
        self.assertTrue(d.is_below("from(u2e4)", "from(ljubljana)"))
        self.assertTrue(d.is_below("from(u2e4x)", "from(ljubljana)"))
        self.assertTrue(d.is_below("from(u2e5)", "from(ljubljana)"))
        self.assertFalse(d.is_below("from(u2e6)", "from(ljubljana)"))

    def test_a_region_is_a_lower_bound_only(self):
        # Its cells are what it is KNOWN to cover; nothing asserts it lies
        # within u2 until someone files it there. Reading the covering as
        # an upper bound would let a later cell flip a True to False.
        d = make_dag()
        self.assertFalse(d.is_below("from(ljubljana)", "from(u2)"))
        d.put("ljubljana", ["geo(u2)"])
        self.assertTrue(d.is_below("from(ljubljana)", "from(u2)"))
        d.put("geo(u2e6)", ["ljubljana"])          # the region grows
        self.assertTrue(d.is_below("from(ljubljana)", "from(u2)"))

    def test_a_present_node_outside_the_dimension_is_refused(self):
        d = make_dag()
        d.put("Flight", [])
        with self.assertRaises(ValueError):
            d.put("x", ["from(Flight)"])
        with self.assertRaises(ValueError):
            d.get(["from(Flight)"])
        with self.assertRaises(ValueError):
            d.is_below("from(Flight)", "from(u2)")

    def test_a_literal_stays_a_literal_until_the_name_exists(self):
        d = make_dag()
        d.put("y", ["from(zzz)"])                  # zzz: a cell, nothing else
        self.assertTrue(d.is_below("from(zzz)", "from(zz)"))
        with self.assertRaises(ValueError):
            d.put("zzz", [])                       # would leave the dimension
        d.put("zzz", ["geo(zz)"])                  # a place named zzz: fine
        self.assertTrue(d.is_below("from(zzz)", "from(zz)"))
        self.assertTrue(d.is_below("y", "from(zz)"))

    def test_canonical_form_is_the_name_as_spelled(self):
        d = with_offers(make_dag())
        self.assertIn("from(my_home)", d.nodes)
        self.assertEqual(d._canonical_name("from(my_home)"), "from(my_home)")
        self.assertEqual(surface.elaborate("from(my_home)", d), "from(my_home)")

    def test_base_head_parameters_are_always_values(self):
        # loopmarket's footgun in reverse: a category that happens to be
        # called `u2e4` never becomes the cell — only ROLES look names up.
        d = make_dag()
        d.put("Flight", [])
        d.put("u2e4", ["Flight"])
        self.assertTrue(d.is_below("geo(u2e4x)", "geo(u2e4)"))
        self.assertFalse(d.is_below("u2e4", "geo(u2)"))

    def test_values_are_leaves_of_the_declaration_walk(self):
        # A place under a cell is not a dimension head, whatever its name.
        d = make_dag()
        d.put("shop(1)", ["geo(u2e4x)"])
        self.assertIsNone(d._parse_parametric("shop(1)"))
        self.assertEqual(d._dimension_of("my_home"), (None, None))
        self.assertEqual(names(d.get(["shop(1)"])), set())

    def test_a_role_over_a_calendar_dimension(self):
        d = make_dag()
        d.put("when", ["time"])
        d.put("summer-fair", ["time(2026-08)"])
        d.put("stall", ["when(summer-fair)"])
        self.assertTrue(d.is_below("stall", "when(2026)"))
        self.assertTrue(d.is_below("when(summer-fair)", "when(2026-08)"))
        self.assertFalse(d.is_below("stall", "when(2027)"))
        with self.assertRaises(ValueError):
            d.put("z", ["when(nonsense)"])          # neither node nor period

    def test_floors_are_sub_places(self):
        # Peter's third coordinate: a floor is a node under the building,
        # so containment computes end to end and siblings never match.
        d = with_offers(make_dag())
        d.put("my_home_4th", ["my_home"])
        d.put("my_home_ground", ["my_home"])
        d.put("courier-ground", ["from(my_home_ground)"])
        d.put("want-4th", ["from(my_home_4th)"])
        self.assertTrue(d.is_below("from(my_home_4th)", "from(my_home)"))
        self.assertFalse(d.is_below("from(my_home)", "from(my_home_4th)"))
        self.assertTrue(d.is_below("want-4th", "from(u2e4)"))
        # A give to the whole building serves the fourth floor by overlap;
        # a ground-floor-only courier does not.
        possible = names(d.get_overlapping("from(my_home_4th)"))
        self.assertIn("offer", possible)              # from(my_home)
        self.assertIn("want-4th", possible)
        self.assertNotIn("courier-ground", possible)

    def test_queries_with_role_terms(self):
        d = with_offers(make_dag())
        self.assertEqual(names(d.get(["from(u2e4)"])) - {"from(my_home)"},
                         {"offer"})
        self.assertEqual(names(d.get(["from(ljubljana)"]))
                         - {"from(my_home)", "from(u2e5)"},
                         {"offer", "offer2", "ride"})
        self.assertEqual(names(d.get(["from(my_home)"])), {"offer"})
        before = set(d.nodes)
        self.assertEqual(names(d.get(["from(u2e4x)"])), {"from(my_home)",
                                                          "offer"})
        self.assertEqual(before, set(d.nodes))   # virtual: nothing created
        # Same-head role terms: the finer one wins when comparable ...
        self.assertEqual(d.get(["from(ljubljana)", "from(u2e4)"]),
                         d.get(["from(u2e4)"]))
        # ... and incomparable ones stay separate cones (no fake meet).
        self.assertEqual(names(d.get(["from(my_home)", "from(u2e5)"])), set())

    def test_get_overlapping_with_role_terms(self):
        d = with_offers(make_dag())
        self.assertIn("offer", names(d.get_overlapping("from(u2e4xz)")))
        self.assertIn("ride", names(d.get_overlapping("from(u2e)")))
        self.assertNotIn("offer", names(d.get_overlapping("from(u2f)")))
        self.assertNotIn("ride", names(d.get_overlapping("from(u2f)")))
        self.assertIn("offer", names(d.get_overlapping("from(ljubljana)")))

    def test_disjointness_is_never_proven_for_named_places(self):
        # The guard refuses two provably disjoint VALUES; the graph cannot
        # prove two named things apart (the disjointness wall), so a place
        # and a cell it is not known to lie in are accepted.
        d = make_dag()
        d.put("z", ["from(my_home)", "from(u2e5)"])
        with self.assertRaises(ValueError):
            d.put("w", ["from(u2e4)", "from(u2e5)"])

    def test_render_is_total(self):
        d = with_offers(make_dag())
        d.put("when", ["time"])
        d.put("summer-fair", ["time(2026-08)"])
        d.put("stall", ["when(summer-fair)"])
        self.assertEqual(surface.render("from(my_home)", d), "from(my_home)")
        self.assertEqual(surface.render("when(summer-fair)", d),
                         "when(summer-fair)")
        self.assertEqual(surface.render("when(2026-08-01T00:00:00Z.."
                                        "2026-08-31T23:59:59Z)", d),
                         "when(2026-08)")

    def test_a_role_with_two_bases_is_refused(self):
        d = make_dag()
        d.put("alt", ["prefix-dimension"])
        d.put("twin", ["geo", "alt"])
        with self.assertRaises(ValueError):
            d.get(["twin(u2)"])


class TestStoredFormWithRoles(unittest.TestCase):
    """The order of role terms follows the catalogue, so filing a place or
    growing a region can make an asserted edge redundant after the fact.
    Stored form must not depend on which came first (I3), or merge would
    not converge (I7)."""

    def test_region_growth_reduces_like_direct_filing(self):
        late = make_dag()
        late.put("ride", ["from(ljubljana)"])
        late.put("ride", ["from(u2e6)"])           # not in the region (yet)
        late.put("geo(u2e6)", ["ljubljana"])       # now it is
        direct = make_dag()
        direct.put("geo(u2e6)", ["ljubljana"])
        direct.put("ride", ["from(u2e6)", "from(ljubljana)"])
        self.assertEqual(edge_set(late), edge_set(direct))
        self.assertNotIn(("from(ljubljana)", "ride"), edge_set(late))
        self.assertTrue(late.is_below("ride", "from(ljubljana)"))

    def test_refining_a_place_reduces_like_direct_filing(self):
        late = make_dag()
        late.put("cafe", ["geo(u2e)"])            # coarse at first
        late.put("o", ["from(cafe)"])
        late.put("o", ["from(u2e4x)"])            # kept: cafe may be elsewhere
        late.put("cafe", ["geo(u2e4x)"])          # refined into that cell
        direct = make_dag()
        direct.put("geo(u2e)", ["geo"])           # values, once used, stay
        direct.put("cafe", ["geo(u2e4x)"])
        direct.put("o", ["from(u2e4x)", "from(cafe)"])
        self.assertEqual(edge_set(late), edge_set(direct))
        self.assertNotIn(("from(u2e4x)", "o"), edge_set(late))

    def test_roots_agree_across_orders(self):
        def build(order):
            blobs = MemoryBytesStore()
            dag = make_dag(EagerOntoDAG(RecordStore(blobs)))
            for name, supers in order:
                dag.put(name, supers)
            return dag.commit()
        a = build([("ride", ["from(ljubljana)"]), ("ride", ["from(u2e6)"]),
                   ("geo(u2e6)", ["ljubljana"]),
                   ("cafe", ["geo(u2e)"]), ("o", ["from(cafe)"]),
                   ("o", ["from(u2e4x)"]), ("cafe", ["geo(u2e4x)"])])
        b = build([("geo(u2e6)", ["ljubljana"]), ("geo(u2e)", ["geo"]),
                   ("cafe", ["geo(u2e4x)"]),
                   ("o", ["from(u2e4x)", "from(cafe)"]),
                   ("ride", ["from(u2e6)", "from(ljubljana)"])])
        self.assertEqual(a, b)

    def test_merge_commutes(self):
        a = make_dag()
        a.put("ride", ["from(ljubljana)"])
        a.put("o", ["from(u2e4x)"])
        b = make_dag()
        b.put("geo(u2e6)", ["ljubljana"])
        b.put("ride", ["from(u2e6)"])
        b.put("cafe", ["geo(u2e4x)"])
        b.put("o", ["from(cafe)"])
        ab = a.deepcopy()
        ab.merge(b)
        ba = b.deepcopy()
        ba.merge(a)
        self.assertEqual(edge_set(ab), edge_set(ba))
        self.assertTrue(ab.is_below("o", "from(u2e4x)"))
        self.assertTrue(ab.is_below("ride", "from(ljubljana)"))

    def test_sparse_writer_matches_eager(self):
        blobs = MemoryBytesStore()
        base = make_dag(EagerOntoDAG(RecordStore(blobs))).commit()
        steps = [("cafe", ["geo(u2e)"]), ("o", ["from(cafe)"]),
                 ("o", ["from(u2e4x)"]), ("cafe", ["geo(u2e4x)"]),
                 ("ride", ["from(ljubljana)"]), ("geo(u2e6)", ["ljubljana"])]
        eager = EagerOntoDAG(RecordStore(blobs, root=base))
        sparse = SparseOntoDAG(RecordStore(blobs, root=base))
        for name, supers in steps:
            eager.put(name, supers)
            sparse.put(name, supers)
        self.assertEqual(eager.commit(), sparse.commit())

    def test_lazy_reader_answers_and_certifies(self):
        from ontodag.certificates import prove_below, verify_below
        blobs = MemoryBytesStore()
        eager = with_offers(make_dag(EagerOntoDAG(RecordStore(blobs))))
        root = eager.commit()
        reader = LazyOntoDAG(RecordStore.at(root, blobs))
        self.assertTrue(reader.is_below("offer", "from(u2e4)"))
        self.assertFalse(reader.is_below("offer2", "from(u2e4)"))
        self.assertEqual(names(reader.get(["from(ljubljana)"])),
                         names(eager.get(["from(ljubljana)"])))
        for sub, sup, expected in [("offer", "from(u2e4)", True),
                                   ("from(my_home)", "from(ljubljana)", True),
                                   ("offer2", "from(u2e4)", False),
                                   ("from(u2e4x)", "from(ljubljana)", True)]:
            cert = prove_below(eager, sub, sup)
            self.assertEqual(verify_below(cert, root), expected, (sub, sup))


class TestRoleGuards(unittest.TestCase):
    def test_remove_refuses_while_a_role_term_names_the_node(self):
        d = with_offers(make_dag())
        with self.assertRaises(ValueError):
            d.remove("my_home")
        d.remove("from(my_home)")
        d.remove("my_home")                        # free once the term is gone
        self.assertNotIn("my_home", d.nodes)

    def test_remove_cone_refuses_unless_the_term_goes_too(self):
        d = with_offers(make_dag())
        with self.assertRaises(ValueError):
            d.remove_cone(["my_home"])
        deleted = d.remove_cone(["my_home", "from(my_home)"])
        self.assertIn("my_home", deleted)
        self.assertIn("from(my_home)", deleted)

    def test_reclassify_keeps_the_node_in_its_dimension(self):
        d = with_offers(make_dag())
        d.put("Flight", [])
        with self.assertRaises(ValueError):
            d.reclassify(["my_home"], to=["Flight"])
        self.assertTrue(d.is_below("offer", "from(u2e4)"))     # untouched
        d.reclassify(["my_home"], to=["geo(u2e5)"])
        self.assertTrue(d.is_below("offer", "from(u2e5)"))
        self.assertFalse(d.is_below("offer", "from(u2e4)"))


if __name__ == "__main__":
    unittest.main()
