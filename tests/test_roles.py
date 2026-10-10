"""Role heads over a base dimension (docs/DIMENSIONS.md §14, issue #15).

A head declared under another head — `from` under `geo`, `when` under
`time` — is a ROLE of that dimension: it shares the kind and the value
space, and its parameters may be values of the base (`from(geo(u2e4x))`) or
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


def written_before_4_4(dag, lines):
    """`dag` with `lines` added as a store written before registry 4.4
    holds them: a role of geo's cell as a bare word (`from(u2e4x)`), which
    a new write is refused since review question 14 and a store keeps
    reading as the cell. Loaded from text with no canonical mark."""
    from ontodag import native
    text = "\n".join(line for line in native.dumps(dag).splitlines()
                     if not line.startswith("#:canonical"))
    return native.loads(text + "\n" + "\n".join(lines) + "\n")


def with_offers(dag):
    dag.put("offer", ["from(my_home)"])       # a place as the parameter
    dag.put("offer2", ["from(geo(u2e5))"])         # a value, as before
    dag.put("ride", ["from(ljubljana)"])      # a region as the parameter
    return dag


class TestRoleParameters(unittest.TestCase):
    def test_the_issue_scenario(self):
        d = make_dag()
        self.assertEqual(d._dimension_of("from"), ("prefix-dimension", "geo"))
        self.assertEqual(d._dimension_of("geo"), ("prefix-dimension", "geo"))
        self.assertTrue(d.is_below("from(ljubljana)", "from(ljubljana)"))
        # The line the issue reports as False: my_home sits under u2e4x.
        self.assertTrue(d.is_below("from(my_home)", "from(geo(u2e4))"))
        self.assertTrue(d.is_below("from(my_home)", "from(ljubljana)"))
        self.assertFalse(d.is_below("from(ljubljana)", "from(my_home)"))
        # A region covers its cells: any cell in it (or finer) is below it.
        self.assertTrue(d.is_below("from(geo(u2e4))", "from(ljubljana)"))
        self.assertTrue(d.is_below("from(geo(u2e4x))", "from(ljubljana)"))
        self.assertTrue(d.is_below("from(geo(u2e5))", "from(ljubljana)"))
        self.assertFalse(d.is_below("from(geo(u2e6))", "from(ljubljana)"))

    def test_a_region_is_a_lower_bound_only(self):
        # Its cells are what it is KNOWN to cover; nothing asserts it lies
        # within u2 until someone files it there. Reading the covering as
        # an upper bound would let a later cell flip a True to False.
        d = make_dag()
        self.assertFalse(d.is_below("from(ljubljana)", "from(geo(u2))"))
        d.put("ljubljana", ["geo(u2)"])
        self.assertTrue(d.is_below("from(ljubljana)", "from(geo(u2))"))
        d.put("geo(u2e6)", ["ljubljana"])          # the region grows
        self.assertTrue(d.is_below("from(ljubljana)", "from(geo(u2))"))

    def test_a_present_node_outside_the_dimension_is_refused(self):
        d = make_dag()
        d.put("Flight", [])
        with self.assertRaises(ValueError):
            d.put("x", ["from(Flight)"])
        with self.assertRaises(ValueError):
            d.get(["from(Flight)"])
        with self.assertRaises(ValueError):
            d.is_below("from(Flight)", "from(geo(u2))")

    def test_a_literal_stays_a_literal_until_the_name_exists(self):
        # A store from before 4.4: zzz, a cell, nothing else.
        d = written_before_4_4(make_dag(), ["'from(zzz)' from", "y 'from(zzz)'"])
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
        self.assertTrue(d.is_below("want-4th", "from(geo(u2e4))"))
        # A give to the whole building serves the fourth floor by overlap;
        # a ground-floor-only courier does not.
        possible = names(d.get_overlapping("from(my_home_4th)"))
        self.assertIn("offer", possible)              # from(my_home)
        self.assertIn("want-4th", possible)
        self.assertNotIn("courier-ground", possible)

    def test_queries_with_role_terms(self):
        d = with_offers(make_dag())
        self.assertEqual(names(d.get(["from(geo(u2e4))"])) - {"from(my_home)"},
                         {"offer"})
        self.assertEqual(names(d.get(["from(ljubljana)"]))
                         - {"from(my_home)", "from(geo(u2e5))"},
                         {"offer", "offer2", "ride"})
        self.assertEqual(names(d.get(["from(my_home)"])), {"offer"})
        before = set(d.nodes)
        self.assertEqual(names(d.get(["from(geo(u2e4x))"])), {"from(my_home)",
                                                          "offer"})
        self.assertEqual(before, set(d.nodes))   # virtual: nothing created
        # Same-head role terms: the finer one wins when comparable ...
        self.assertEqual(d.get(["from(ljubljana)", "from(geo(u2e4))"]),
                         d.get(["from(geo(u2e4))"]))
        # ... and incomparable ones stay separate cones (no fake meet).
        self.assertEqual(names(d.get(["from(my_home)", "from(geo(u2e5))"])), set())

    def test_get_overlapping_with_role_terms(self):
        d = with_offers(make_dag())
        self.assertIn("offer", names(d.get_overlapping("from(geo(u2e4xz))")))
        self.assertIn("ride", names(d.get_overlapping("from(geo(u2e))")))
        self.assertNotIn("offer", names(d.get_overlapping("from(geo(u2f))")))
        self.assertNotIn("ride", names(d.get_overlapping("from(geo(u2f))")))
        self.assertIn("offer", names(d.get_overlapping("from(ljubljana)")))

    def test_disjointness_is_never_proven_for_named_places(self):
        # The guard refuses two provably disjoint VALUES; the graph cannot
        # prove two named things apart (the disjointness wall), so a place
        # and a cell it is not known to lie in are accepted.
        d = make_dag()
        d.put("z", ["from(my_home)", "from(geo(u2e5))"])
        with self.assertRaises(ValueError):
            d.put("w", ["from(geo(u2e4))", "from(geo(u2e5))"])

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
        late.put("ride", ["from(geo(u2e6))"])           # not in the region (yet)
        late.put("geo(u2e6)", ["ljubljana"])       # now it is
        direct = make_dag()
        direct.put("geo(u2e6)", ["ljubljana"])
        direct.put("ride", ["from(geo(u2e6))", "from(ljubljana)"])
        self.assertEqual(edge_set(late), edge_set(direct))
        self.assertNotIn(("from(ljubljana)", "ride"), edge_set(late))
        self.assertTrue(late.is_below("ride", "from(ljubljana)"))

    def test_refining_a_place_reduces_like_direct_filing(self):
        late = make_dag()
        late.put("cafe", ["geo(u2e)"])            # coarse at first
        late.put("o", ["from(cafe)"])
        late.put("o", ["from(geo(u2e4x))"])            # kept: cafe may be elsewhere
        late.put("cafe", ["geo(u2e4x)"])          # refined into that cell
        direct = make_dag()                       # geo(u2e), used no more, goes
        direct.put("cafe", ["geo(u2e4x)"])
        direct.put("o", ["from(geo(u2e4x))", "from(cafe)"])
        self.assertEqual(edge_set(late), edge_set(direct))
        self.assertNotIn(("from(geo(u2e4x))", "o"), edge_set(late))

    def test_roots_agree_across_orders(self):
        def build(order):
            blobs = MemoryBytesStore()
            dag = make_dag(EagerOntoDAG(RecordStore(blobs)))
            for name, supers in order:
                dag.put(name, supers)
            return dag.commit()
        a = build([("ride", ["from(ljubljana)"]), ("ride", ["from(geo(u2e6))"]),
                   ("geo(u2e6)", ["ljubljana"]),
                   ("cafe", ["geo(u2e)"]), ("o", ["from(cafe)"]),
                   ("o", ["from(geo(u2e4x))"]), ("cafe", ["geo(u2e4x)"])])
        b = build([("geo(u2e6)", ["ljubljana"]),
                   ("cafe", ["geo(u2e4x)"]),
                   ("o", ["from(geo(u2e4x))", "from(cafe)"]),
                   ("ride", ["from(geo(u2e6))", "from(ljubljana)"])])
        self.assertEqual(a, b)

    def test_merge_commutes(self):
        a = make_dag()
        a.put("ride", ["from(ljubljana)"])
        a.put("o", ["from(geo(u2e4x))"])
        b = make_dag()
        b.put("geo(u2e6)", ["ljubljana"])
        b.put("ride", ["from(geo(u2e6))"])
        b.put("cafe", ["geo(u2e4x)"])
        b.put("o", ["from(cafe)"])
        ab = a.deepcopy()
        ab.merge(b)
        ba = b.deepcopy()
        ba.merge(a)
        self.assertEqual(edge_set(ab), edge_set(ba))
        self.assertTrue(ab.is_below("o", "from(geo(u2e4x))"))
        self.assertTrue(ab.is_below("ride", "from(ljubljana)"))

    def test_sparse_writer_matches_eager(self):
        blobs = MemoryBytesStore()
        base = make_dag(EagerOntoDAG(RecordStore(blobs))).commit()
        steps = [("cafe", ["geo(u2e)"]), ("o", ["from(cafe)"]),
                 ("o", ["from(geo(u2e4x))"]), ("cafe", ["geo(u2e4x)"]),
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
        self.assertTrue(reader.is_below("offer", "from(geo(u2e4))"))
        self.assertFalse(reader.is_below("offer2", "from(geo(u2e4))"))
        self.assertEqual(names(reader.get(["from(ljubljana)"])),
                         names(eager.get(["from(ljubljana)"])))
        for sub, sup, expected in [("offer", "from(geo(u2e4))", True),
                                   ("from(my_home)", "from(ljubljana)", True),
                                   ("offer2", "from(geo(u2e4))", False),
                                   ("from(geo(u2e4x))", "from(ljubljana)", True)]:
            cert = prove_below(eager, sub, sup)
            self.assertEqual(verify_below(cert, root), expected, (sub, sup))


class TestOverlapsAndMeet(unittest.TestCase):
    """The Boolean overlap face (issue #16): `overlaps(a, b)` for any pair of
    terms or nodes, and `meet(a, b)` as one canonical term with store units."""

    def test_values_decide_by_arithmetic(self):
        d = make_dag()
        self.assertTrue(d.overlaps("geo(u2e)", "geo(u2e4x)"))
        self.assertFalse(d.overlaps("geo(u2e4)", "geo(u2e5)"))
        self.assertTrue(d.overlaps("from(geo(u2e))", "from(geo(u2e4x))"))   # both ways
        self.assertTrue(d.overlaps("from(geo(u2e4x))", "from(geo(u2e))"))
        d.put("when", ["time"])
        self.assertTrue(d.overlaps("when(2026-08)", "when(2026-08-15..2026-09-02)"))
        self.assertFalse(d.overlaps("when(2026-08)", "when(2026-09)"))

    def test_nodes_decide_by_the_graph(self):
        d = with_offers(make_dag())
        self.assertTrue(d.overlaps("from(ljubljana)", "from(geo(u2e))"))
        self.assertFalse(d.overlaps("from(ljubljana)", "from(geo(u2f))"))
        self.assertTrue(d.overlaps("from(my_home)", "from(geo(u2e4xz))"))  # possibly
        self.assertFalse(d.overlaps("from(my_home)", "from(geo(u2f))"))
        self.assertTrue(d.overlaps("from(my_home)", "from(ljubljana)"))
        # region ∩ region, both sides nodes — never consumer enumeration
        d.put("central", [])
        d.put("geo(u2e5)", ["central"])
        d.put("geo(u2e6)", ["central"])
        self.assertTrue(d.overlaps("ljubljana", "central"))
        self.assertTrue(d.overlaps("from(ljubljana)", "from(central)"))
        d.put("north", [])
        d.put("geo(u2f1)", ["north"])
        self.assertFalse(d.overlaps("ljubljana", "north"))
        # an item against a term, and two plain nodes
        self.assertTrue(d.overlaps("offer", "from(geo(u2e4))"))
        self.assertFalse(d.overlaps("offer", "from(geo(u2f))"))
        self.assertTrue(d.overlaps("ljubljana", "my_home"))

    def test_two_places_under_one_cell_are_two_places(self):
        d = with_offers(make_dag())
        d.put("shop", ["geo(u2e4x)"])
        self.assertFalse(d.overlaps("from(shop)", "from(my_home)"))
        self.assertFalse(d.overlaps("shop", "my_home"))
        d.put("my_home_4th", ["my_home"])
        self.assertTrue(d.overlaps("from(my_home_4th)", "from(my_home)"))

    def test_below_implies_overlaps(self):
        d = with_offers(make_dag())
        pairs = [("from(geo(u2e4x))", "from(geo(u2e4))"), ("from(my_home)", "from(geo(u2e))"),
                 ("from(geo(u2e5))", "from(ljubljana)"), ("offer", "from(ljubljana)"),
                 ("my_home", "geo(u2e4)")]
        for a, b in pairs:
            self.assertTrue(d.is_below(a, b) or d.is_below(b, a), (a, b))
            self.assertTrue(d.overlaps(a, b), (a, b))
            self.assertTrue(d.overlaps(b, a), (a, b))

    def test_errors_and_fail_closed(self):
        d = make_dag()
        with self.assertRaises(ValueError):
            d.overlaps("from(geo(u2e4))", "geo(u2e4)")          # different heads
        with self.assertRaises(ValueError):
            d.overlaps("mass(3kg)", "mass(nonsense)")  # malformed
        self.assertFalse(d.overlaps("nobody", "geo(u2e4)"))  # unknown: False

    def test_units_come_from_the_store(self):
        d = make_dag()
        d.put("unit-declaration", [])
        d.put("unit(stone=14lb)", ["unit-declaration"])
        d.put("load", ["mass"])                     # a role over a linear head
        self.assertTrue(d.overlaps("load(1stone..)", "load(..7kg)"))
        self.assertFalse(d.overlaps("load(1stone..)", "load(..6kg)"))
        self.assertEqual(d.meet("load(1stone..)", "load(..7kg)"),
                         "load(317514659/50000000kg..7kg)")

    def test_meet(self):
        d = with_offers(make_dag())
        self.assertEqual(d.meet("from(geo(u2e))", "from(geo(u2e4x))"), "from(geo(u2e4x))")
        self.assertIsNone(d.meet("from(geo(u2e4))", "from(geo(u2e5))"))
        self.assertEqual(d.meet("from(ljubljana)", "from(geo(u2e4x))"), "from(geo(u2e4x))")
        self.assertEqual(d.meet("from(my_home)", "from(ljubljana)"), "from(my_home)")
        self.assertIsNone(d.meet("from(my_home)", "from(geo(u2f))"))    # no overlap
        with self.assertRaises(ValueError):
            d.meet("from(ljubljana)", "from(geo(u2e))")   # overlap, but no one term
        with self.assertRaises(ValueError):
            d.meet("from(geo(u2e4))", "geo(u2e4)")
        with self.assertRaises(ValueError):
            d.meet("offer", "from(geo(u2e4))")
        self.assertEqual(d.meet("mass(1kg..5kg)", "mass(3kg..)"),
                         "mass(3kg..5kg)")


class TestTheDimensionItselfIsNoParameter(unittest.TestCase):
    """Issue #17, closed the other way round (Peter, 2026-09-12): there is
    no "from anywhere" term. `get` is containment — a want's place is a
    query term and the gives in the answer fit within it — and an item that
    says nothing about `from` simply has no `from` cone to be in. A term
    for the whole space, `from(geo)`, would only ever be redundant beside
    anything finer (the overlap of everything with A is A), so the
    dimension itself is refused as a role parameter, with the reason."""

    def test_refused_with_the_reason(self):
        d = make_dag()
        for call in (lambda: d.is_below("from(geo)", "from(geo(u2e))"),
                     lambda: d.overlaps("from(geo)", "from(geo(u2e))"),
                     lambda: d.put("anywhere", ["from(geo)"]),
                     lambda: d.get(["from(geo)"]),
                     lambda: d.get_overlapping("from(geo)")):
            with self.assertRaises(ValueError) as caught:
                call()
            self.assertIn("is the dimension itself", str(caught.exception))
            self.assertIn("states no from(...) at all", str(caught.exception))
        self.assertNotIn("anywhere", d.nodes)
        # a base head's own parameters stay values: geo(geo) is a literal
        self.assertIsNone(d._param_node("geo", "geo"))

    def test_place_is_a_query_term_like_any_other(self):
        """The want is the wider cone, the give the narrower: a give at a
        place fits within a want for the cell above it; a give that says
        nothing about `from` is in no `from` cone; a give elsewhere is out."""
        d = OntoDAG()
        prelude.apply(d)
        d.put("from", ["geo"]); d.put("cat", [])
        d.put("my_home", ["geo(u2e4x)"])
        d.put("silent", ["cat"])
        d.put("at_home", ["cat", "from(my_home)"])
        d.put("in_cell", ["cat", "from(geo(u2e4))"])
        d.put("elsewhere", ["cat", "from(geo(u2f))"])
        self.assertEqual(names(d.get(["cat", "from(geo(u2e))"], items_only=True)),
                         {"at_home", "in_cell"})
        self.assertEqual(names(d.get(["cat", "from(geo(u2e4x))"], items_only=True)),
                         {"at_home"})
        self.assertEqual(names(d.get(["cat"], items_only=True)),
                         {"silent", "at_home", "in_cell", "elsewhere"})
        self.assertEqual(names(d.get_overlapping("from(geo(u2e))")),
                         {"at_home", "in_cell", "from(my_home)", "from(geo(u2e4))"})


class TestNoLoopThroughARoleLink(unittest.TestCase):
    """The role-head version of the loop the graph kind could close
    (test_graph_kind.TestNoLoopThroughAComputedLink): `from(office)` filed
    under a name below `from(castle)`, then `castle` filed under `office`,
    which adds `from(castle) ⊑ from(office)`."""

    def test_the_edge_is_refused_and_nothing_moves(self):
        dag = make_dag()
        dag.put("castle", ["geo(u2e4y)"])
        dag.put("office", ["geo(u2e4z)"])
        dag.put("rush", [])
        dag.put("from(office)", ["rush"])
        dag.put("rush", ["from(castle)"])
        before = edge_set(dag)
        with self.assertRaisesRegex(ValueError, "cycle through"):
            dag.put("castle", ["office"])
        self.assertEqual(edge_set(dag), before)


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
        self.assertTrue(d.is_below("offer", "from(geo(u2e4))"))     # untouched
        d.reclassify(["my_home"], to=["geo(u2e5)"])
        self.assertTrue(d.is_below("offer", "from(geo(u2e5))"))
        self.assertFalse(d.is_below("offer", "from(geo(u2e4))"))


if __name__ == "__main__":
    unittest.main()


class TestHeadsTheGraphOrdersAreNoRoles(unittest.TestCase):
    """A head the graph orders, declared under another head, is not a role
    of a value dimension (§14): its terms name nodes by constraint, so they
    put no condition on where the nodes they name sit. Until 2026-10-07 the
    move guard took them for roles and refused. Removal is another matter
    since 2026-10-09: no term may be left naming nothing, whatever its kind
    (`_refuse_if_named`), so it is refused unless the terms go too."""

    def build(self, kind, base, head):
        dag = OntoDAG()
        prelude.apply(dag)
        dag.put(kind, ["dimension"])
        dag.put(base, [kind])
        dag.put(head, [base])
        dag.put("bicycle", [])
        dag.put("vehicle", [])
        dag.put("job", [f"{head}(bicycle)"])
        return dag

    def test_moving_a_named_node_is_free_and_removing_it_guarded(self):
        for kind, base, head in (("graph-dimension", "transport", "courier"),
                                 ("enclosing-dimension", "from", "departure")):
            with self.subTest(kind=kind):
                dag = self.build(kind, base, head)
                dag.reclassify(["bicycle"], to=["vehicle"])
                self.assertTrue(dag.is_below("bicycle", "vehicle"))
                with self.assertRaisesRegex(ValueError, "is named by"):
                    dag.remove("bicycle")
                dag.remove("bicycle", with_terms=True)
                self.assertNotIn("bicycle", dag.nodes)
                self.assertNotIn(f"{head}(bicycle)", dag.nodes)
                # The job follows to the term just above: bicycles are vehicles.
                self.assertEqual({p.name for p in dag.nodes["job"].parents},
                                 {f"{head}(vehicle)"})



class TestANameUsedTwoWaysAfterAMerge(unittest.TestCase):
    """Review question 13 (decided by Peter 2026-10-10, option A). Alice
    files a parcel under `from(nyc)` in a store with no category `nyc`, so
    `nyc` is a cell; Bob has a category `nyc` under `city`. Each store is
    valid and a single writer is refused either second write; a merge
    takes both. Until 2026-10-10 every read and write that met the term
    then raised. A category outside the role's dimension is no parameter,
    so the term reads as the value it was written as."""

    def fresh(self):
        d = OntoDAG()
        prelude.apply(d)
        d.put("from", ["geo"])
        return d

    def alice(self):
        """A store written before 4.4 (since review question 14 a new
        write is refused a bare word that is no place)."""
        return written_before_4_4(self.fresh(),
                                  ["'from(nyc)' from", "parcel 'from(nyc)'"])

    def merged(self):
        alice, bob = self.alice(), self.fresh()
        bob.put("city", [])
        bob.put("nyc", ["city"])
        m = self.fresh()
        m.merge(alice)
        m.merge(bob)
        return alice, m

    def test_the_merged_store_answers_as_alice_did(self):
        alice, m = self.merged()
        for probe in ("from(ny)", "from(n)", "from(nyc)"):
            self.assertEqual(m.is_below("parcel", probe),
                             alice.is_below("parcel", probe), probe)
        self.assertIn("parcel", names(m.get(["from(ny)"])))
        self.assertEqual(names(m.get(["city"])), {"nyc"})
        m.put("box", ["from(geo(nycz2))"])               # writes go on too
        self.assertTrue(m.is_below("box", "from(ny)"))
        self.assertTrue(m.is_below("box", "from(geo(ny))"))

    def test_a_single_writer_is_still_refused_both_ways(self):
        d = self.alice()
        d.put("city", [])
        with self.assertRaises(ValueError):
            d.put("nyc", ["city"])
        d = self.fresh()
        d.put("city", [])
        d.put("nyc", ["city"])
        with self.assertRaisesRegex(ValueError, "outside the 'geo' dimension"):
            d.put("parcel", ["from(nyc)"])
        d.put("parcel", [])
        with self.assertRaisesRegex(ValueError, "outside the 'geo' dimension"):
            d.reclassify(["parcel"], to=["from(nyc)"])

    def test_the_clash_is_listed_and_a_rename_ends_it(self):
        _, m = self.merged()
        self.assertEqual(m.name_clashes(), [("from(nyc)", "nyc")])
        m.rename("nyc", "new-york-city")
        self.assertEqual(m.name_clashes(), [])
        self.assertTrue(m.is_below("parcel", "from(ny)"))
        self.assertEqual(names(m.get(["city"])), {"new-york-city"})


class TestACellIsWrittenByItsName(unittest.TestCase):
    """Review question 14 (decided by Peter 2026-10-10). In a role of geo a
    bare word names a place filed in the dimension, and a cell is written
    by its own name, `from(geo(u2e4x))`; `geo(...)` takes geohashes only.
    Before, a role read any word it could not find as a cell, so
    `from(sydney)` filed a parcel in southern Turkey and a mistyped place
    landed somewhere else in silence. A store written before keeps reading
    as it did (G7), and `migrate` respells it."""

    def test_a_cell_by_its_own_name_orders_as_the_cell(self):
        d = with_offers(make_dag())
        self.assertIn("from(geo(u2e5))", d.nodes)
        self.assertEqual(d.canonical("from(geo(u2e5))"), "from(geo(u2e5))")
        self.assertTrue(d.is_below("offer2", "from(geo(u2e))"))
        self.assertTrue(d.is_below("offer2", "from(ljubljana)"))   # a region
        self.assertFalse(d.is_below("offer2", "from(geo(u2e4))"))
        self.assertEqual(d.meet("from(geo(u2e))", "from(geo(u2e5))"),
                         "from(geo(u2e5))")
        self.assertTrue(d.overlaps("from(ljubljana)", "from(geo(u2e5))"))
        d.put("van", ["from(geo(u2e7))"])
        self.assertNotIn("geo(u2e7)", d.nodes)     # the cell itself is not stored

    def test_a_bare_word_must_be_a_filed_place(self):
        d = make_dag()
        d.put("parcel", ["from(my_home)"])                  # a place: fine
        for word, hint in (("sydney", "from(geo(sydney))"),
                           ("ljubljna", None), ("u2e5", "from(geo(u2e5))")):
            with self.subTest(word=word):
                with self.assertRaisesRegex(ValueError, "no place filed") as raised:
                    d.put("x", [f"from({word})"])
                if hint:
                    self.assertIn(hint, str(raised.exception))
                with self.assertRaisesRegex(ValueError, "no place filed"):
                    d.reclassify(["parcel"], to=[f"from({word})"])
        self.assertNotIn("x", d.nodes)
        self.assertEqual(d.parents_of("parcel"), ["from(my_home)"])

    def test_a_geo_cell_is_a_geohash(self):
        d = make_dag()
        for name in ("geo(london)", "geo(U2E)", "from(geo(london))"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "geohash"):
                    d.put("x", [name])
        d.put("x", ["geo(u2e)"])
        d.put("y", ["from(geo(gcpvj))"])

    def test_a_query_reads_a_bare_word_as_before(self):
        """G7: an answer a query gave is not taken away; a bare word that
        names no place still reads as the cell when asked."""
        d = with_offers(make_dag())
        self.assertTrue(d.is_below("offer2", "from(u2e)"))
        self.assertEqual(names(d.get(["from(u2e)"])),
                         names(d.get(["from(geo(u2e))"])))

    def old_store(self):
        return written_before_4_4(make_dag(), [
            "'from(u2e5)' from", "offer2 'from(u2e5)'",
            "'from(london)' from", "pub 'from(london)'"])

    def test_a_store_from_before_reads_as_it_was_stored(self):
        d = self.old_store()
        self.assertEqual(d.old_cell_spellings(), ["from(london)", "from(u2e5)"])
        self.assertTrue(d.is_below("offer2", "from(geo(u2e))"))
        self.assertTrue(d.is_below("offer2", "from(u2e)"))
        self.assertTrue(d.is_below("offer2", "from(ljubljana)"))
        self.assertIn("offer2", names(d.get(["from(geo(u2e))"])))
        self.assertTrue(d.is_below("pub", "from(lon)"))       # as it always read

    def test_a_new_write_of_the_cell_respells_the_old_term(self):
        d = self.old_store()
        d.put("crate", ["from(geo(u2e5))"])
        self.assertNotIn("from(u2e5)", d.nodes)
        self.assertEqual(d.parents_of("offer2"), ["from(geo(u2e5))"])
        self.assertEqual(d.old_cell_spellings(), ["from(london)"])

    def test_a_merge_respells_in_either_direction(self):
        def new():
            n = make_dag()
            n.put("crate", ["from(geo(u2e5))"])
            return n
        a, b = self.old_store(), new()
        a.merge(new())
        b.merge(self.old_store())
        self.assertEqual(edge_set(a), edge_set(b))
        self.assertNotIn("from(u2e5)", a.nodes)
        self.assertEqual(a.old_cell_spellings(), ["from(london)"])

    def test_migrate_respells_every_stored_cell(self):
        import os
        import tempfile
        from ontodag import migrate, native
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "store.od")
            native.save(self.old_store(), path)
            migrate.migrate_native(path)
            d = native.load(path)
        self.assertEqual(d.parents_of("offer2"), ["from(geo(u2e5))"])
        # `london` is no geohash: no cell to name, so it reads as before
        self.assertEqual(d.old_cell_spellings(), ["from(london)"])
        self.assertTrue(d.is_below("pub", "from(lon)"))

    def test_time_roles_keep_their_values(self):
        d = make_dag()
        d.put("made", ["time"])
        d.put("chair", ["made(1850)"])
        self.assertTrue(d.is_below("chair", "made(1800..1900)"))

    def test_the_sparse_writer_refuses_and_respells_as_the_eager_one(self):
        blobs = MemoryBytesStore()
        old = self.old_store()
        seed = EagerOntoDAG(RecordStore(blobs))
        seed.merge(old)
        base = seed.commit()
        eager = EagerOntoDAG(RecordStore(blobs, root=base))
        sparse = SparseOntoDAG(RecordStore(blobs, root=base))
        for w in (eager, sparse):
            with self.assertRaisesRegex(ValueError, "no place filed"):
                w.put("x", ["from(u2e7)"])
            w.put("crate", ["from(geo(u2e5))"])
        self.assertEqual(eager.commit(), sparse.commit())
        self.assertNotIn("from(u2e5)", eager.nodes)
