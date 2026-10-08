"""The transitive kind, `in`; the enclosing kind, `about`; and the
reversed kind, `for` (docs/DIMENSIONS.md §16–§18, docs/plans/ROLES.md).

An enclosing-kind head follows containment instead of chaining: a photo
about Tokyo is about Japan once Tokyo is in Japan. It too keeps several
terms of one head separate, and needs no guard of its own.

A head declared under `transitive-dimension` names a relation that chains:
`in(tokyo) ⊑ in(japan)` once `tokyo ⊑ in(japan)`, because whatever is in
Tokyo is in Japan. Its parameters are graph constraints, as for the graph
kind. Unlike the graph kind, two terms of one head on one item stay
separate (Zermatt is in Switzerland and in the Alps), and the relation is
strict: nothing is in itself, so an edge that would put a thing inside
itself is refused.

A reversed-kind head orders its terms against the graph: what is for a
group is for each member, so `shared-with(group) ⊑ shared-with(member)`. It follows
kinds only, never `in`.

`Oracle` recomputes the combined order from the asserted edges alone, as
the least fixpoint of six rules: reflexive, transitive, the asserted
edges, `in(x) ⊑ in(y)` when `x ⊑ y` or `x ⊑ in(y)`, `about(x) ⊑
about(y)` when `x ⊑ y` or `x ⊑ in(y)`, and `shared-with(y) ⊑ shared-with(x)` when
`x ⊑ y`. It shares nothing with the traversals, containment code and memo
under test. Its random worlds also file terms under plain names (a term
"escaping" its head), the one shape in which an edge can close a loop
through a computed link it creates itself.
"""

import random
import unittest

from recordstore import MemoryBytesStore, RecordStore

from ontodag import prelude
from ontodag.dag import DAG, Item, OntoDAG
from ontodag.eager import EagerOntoDAG
from ontodag.lazy import LazyOntoDAG, SparseOntoDAG


def names(items):
    return {item.name for item in items}


def edge_set(dag):
    return {(parent.name, child.name)
            for parent in dag.nodes.values() for child in parent.neighbors}


def parents(dag, name):
    return {parent.name for parent in dag.nodes[name].parents}


def declare(dag=None, about=False, audience=False):
    dag = dag if dag is not None else OntoDAG()
    prelude.apply(dag)
    dag.put("transitive-dimension", ["dimension"])
    dag.put("in", ["transitive-dimension"])
    if about:
        dag.put("enclosing-dimension", ["dimension"])
        dag.put("about", ["enclosing-dimension"])
    if audience:
        dag.put("reversed-dimension", ["dimension"])
        dag.put("shared-with", ["reversed-dimension"])
    return dag


GEOGRAPHY = (("place", []), ("city", ["place"]), ("asia", ["place"]),
             ("japan", ["place", "in(asia)"]),
             ("kanto", ["place", "in(japan)"]),
             ("tokyo", ["city", "in(kanto)"]),
             ("photo", ["in(tokyo)"]),
             ("louvre", ["place"]), ("denon-wing", ["in(louvre)"]),
             ("mona-lisa", ["in(denon-wing)"]),
             ("louvre-pyramid", ["in(louvre)"]),
             ("switzerland", ["place"]), ("alps", ["place"]),
             ("zermatt", ["place", "in(switzerland)", "in(alps)"]))


def geography(dag=None):
    """Tokyo in Kanto in Japan in Asia, a photo in Tokyo; the Mona Lisa in
    the Louvre's Denon wing, the Louvre's pyramid in it directly, in no
    wing; Zermatt in Switzerland and in the Alps. Places and parts only:
    membership goes under kinds (ROLES.md §5)."""
    dag = declare(dag)
    for name, supers in GEOGRAPHY:
        dag.put(name, supers)
    return dag


class TestTheOrder(unittest.TestCase):
    def setUp(self):
        self.dag = geography()

    def test_whatever_is_in_tokyo_is_in_japan(self):
        below = self.dag.is_below
        for place in ("tokyo", "kanto", "japan", "asia"):
            self.assertTrue(below("photo", f"in({place})"), place)
        self.assertTrue(below("in(tokyo)", "in(japan)"))
        self.assertFalse(below("in(japan)", "in(tokyo)"))
        # the photo is in Japan; it is not a Japan
        self.assertFalse(below("photo", "japan"))

    def test_in_in_is_the_smaller_class(self):
        # transitivity gives in(in(Z)) ⊑ in(Z) only: the pyramid stands in
        # the Louvre directly, in no wing, so it is in the Louvre but in
        # nothing that is in the Louvre
        below = self.dag.is_below
        self.assertTrue(below("in(in(louvre))", "in(louvre)"))
        self.assertFalse(below("in(louvre)", "in(in(louvre))"))
        self.assertTrue(below("mona-lisa", "in(in(louvre))"))
        self.assertFalse(below("louvre-pyramid", "in(in(louvre))"))
        self.assertTrue(below("louvre-pyramid", "in(louvre)"))
        self.assertTrue(below("tokyo", "in(in(japan))"))      # through Kanto
        self.assertFalse(below("kanto", "in(in(japan))"))     # directly in Japan

    def test_the_kinds_carry_over(self):
        self.dag.put("railway-station", ["place"])
        self.dag.put("kyoto-station", ["railway-station"])
        self.dag.put("ticket-office", ["in(kyoto-station)"])
        self.assertTrue(self.dag.is_below("in(kyoto-station)",
                                          "in(railway-station)"))
        self.assertTrue(self.dag.is_below("ticket-office",
                                          "in(railway-station)"))

    def test_queries(self):
        get = self.dag.get
        self.assertEqual(names(get(["city", "in(japan)"])), {"tokyo"})
        # the terms in(tokyo) and in(kanto) are in the cone too; items_only
        # leaves the things (nothing is filed directly under a place here)
        self.assertEqual(names(get(["in(japan)"], items_only=True)),
                         {"photo", "tokyo", "kanto"})
        self.assertEqual(names(get(["in(louvre)", "in(in(louvre))"],
                                   items_only=True)), {"mona-lisa"})


class TestStrictness(unittest.TestCase):
    def test_nothing_is_in_itself(self):
        dag = geography()
        for name, supers in (("japan", ["in(japan)"]),     # directly
                             ("asia", ["in(tokyo)"]),      # round the chain
                             ("japan", ["in(photo)"]),
                             ("kanto", ["tokyo"])):        # a plain edge closing it
            before = edge_set(dag)
            with self.assertRaisesRegex(ValueError, "inside itself"):
                dag.put(name, supers)
            self.assertEqual(edge_set(dag), before, (name, supers))

    def test_a_new_place_is_not_in_itself_either(self):
        # Nothing is below `lone` and no term names it, which lets the guard
        # skip its walk; `lone ⊑ in(lone)` must still be refused before
        # `in(lone)` is created, or the refusal leaves the term behind.
        dag = declare()
        dag.put("lone", [])
        before = (set(dag.nodes), edge_set(dag))
        with self.assertRaisesRegex(ValueError, "inside itself"):
            dag.put("lone", ["in(lone)"])
        self.assertEqual((set(dag.nodes), edge_set(dag)), before)

    def test_a_merge_stays_total_and_keeps_the_data(self):
        # Each store is consistent; their union puts x and y inside each
        # other. A merge must not refuse, and must not orphan anything.
        a = declare()
        for name in ("x", "y", "thing"):
            a.put(name, [])
        b = a.deepcopy()
        a.put("x", ["in(y)"])
        a.put("thing", ["in(x)"])
        b.put("y", ["in(x)"])
        ab, ba = a.deepcopy(), b.deepcopy()
        ab.merge(b)
        ba.merge(a)
        self.assertEqual(edge_set(ab), edge_set(ba))
        self.assertEqual(parents(ab, "x"), {"in(y)"})
        self.assertEqual(parents(ab, "y"), {"in(x)"})
        self.assertEqual([n for n, node in ab.nodes.items()
                          if n != "*" and not node.parents], [])
        self.assertTrue(ab.is_below("thing", "in(y)"))


class TestPlacement(unittest.TestCase):
    def setUp(self):
        self.dag = geography()

    def test_separate_places_stay_separate(self):
        self.assertEqual(parents(self.dag, "zermatt"),
                         {"place", "in(switzerland)", "in(alps)"})

    def test_the_finer_place_wins(self):
        self.dag.put("trip", ["in(tokyo)", "in(japan)"])
        self.assertEqual(parents(self.dag, "trip"), {"in(tokyo)"})

    def test_a_late_fact_reduces_what_was_filed_before_it(self):
        def build(fact_first):
            dag = declare()
            for name in ("japan", "tokyo"):
                dag.put(name, [])
            if fact_first:
                dag.put("tokyo", ["in(japan)"])
            dag.put("photo", ["in(tokyo)", "in(japan)"])
            if not fact_first:
                dag.put("tokyo", ["in(japan)"])
            return dag
        early, late = build(True), build(False)
        self.assertEqual(parents(late, "photo"), {"in(tokyo)"})
        self.assertEqual(edge_set(early), edge_set(late))

    def test_meet_and_overlap(self):
        self.assertEqual(self.dag.meet("in(tokyo)", "in(japan)"), "in(tokyo)")
        # Zermatt is in both, and neither contains the other: no single
        # term names what is in Switzerland and in the Alps
        with self.assertRaisesRegex(ValueError, "no single term"):
            self.dag.meet("in(switzerland)", "in(alps)")
        self.assertTrue(self.dag.overlaps("in(switzerland)", "in(alps)"))


class TestMemo(unittest.TestCase):
    def test_answers_follow_every_change(self):
        dag = declare()
        for name in ("asia", "japan", "photo"):
            dag.put(name, [])
        dag.put("photo", ["in(japan)"])
        self.assertFalse(dag.is_below("photo", "in(asia)"))
        dag.put("japan", ["in(asia)"])
        self.assertTrue(dag.is_below("photo", "in(asia)"))
        dag.reclassify(["japan"], to=(), from_=["in(asia)"])
        self.assertFalse(dag.is_below("photo", "in(asia)"))


def subjects(dag=None):
    """The geography, plus `about` and a few things to be about."""
    dag = geography(dag)
    dag.put("enclosing-dimension", ["dimension"])
    dag.put("about", ["enclosing-dimension"])
    for name, supers in (("celestial-body", []), ("planet", ["celestial-body"]),
                         ("mars", ["planet"]), ("earth", ["planet"]),
                         ("photograph", []),
                         ("shibuya-photo", ["photograph", "about(tokyo)"]),
                         ("earthrise", ["photograph", "about(mars)",
                                        "about(earth)"])):
        dag.put(name, supers)
    return dag


class TestRelations(unittest.TestCase):
    """The enclosing kind: `about` follows `in` (DIMENSIONS.md §17)."""

    def setUp(self):
        self.dag = subjects()

    def test_aboutness_follows_containment(self):
        below = self.dag.is_below
        self.assertTrue(below("shibuya-photo", "about(japan)"))
        self.assertTrue(below("shibuya-photo", "about(asia)"))
        self.assertTrue(below("about(tokyo)", "about(japan)"))
        self.assertFalse(below("about(japan)", "about(tokyo)"))

    def test_the_kinds_carry_over(self):
        self.assertTrue(self.dag.is_below("shibuya-photo", "about(city)"))
        self.assertTrue(self.dag.is_below("earthrise", "about(planet)"))

    def test_about_is_neither_in_nor_the_thing(self):
        below = self.dag.is_below
        self.assertFalse(below("shibuya-photo", "in(japan)"))
        self.assertFalse(below("shibuya-photo", "japan"))
        self.assertFalse(below("earthrise", "planet"))

    def test_several_subjects_stay_separate(self):
        self.assertEqual(parents(self.dag, "earthrise"),
                         {"photograph", "about(mars)", "about(earth)"})

    def test_the_finer_subject_wins(self):
        self.dag.put("guidebook", ["about(tokyo)", "about(japan)"])
        self.assertEqual(parents(self.dag, "guidebook"), {"about(tokyo)"})

    def test_queries(self):
        self.assertEqual(names(self.dag.get(["photograph", "about(planet)"])),
                         {"earthrise"})
        self.assertEqual(names(self.dag.get(["photograph", "about(japan)"])),
                         {"shibuya-photo"})

    def test_meet(self):
        self.assertEqual(self.dag.meet("about(tokyo)", "about(japan)"),
                         "about(tokyo)")
        with self.assertRaisesRegex(ValueError, "no single term"):
            self.dag.meet("about(mars)", "about(earth)")

    def test_without_in_it_follows_the_order_only(self):
        dag = OntoDAG()
        prelude.apply(dag)
        dag.put("enclosing-dimension", ["dimension"])
        dag.put("about", ["enclosing-dimension"])
        for name, supers in (("planet", []), ("mars", ["planet"]),
                             ("note", ["about(mars)"])):
            dag.put(name, supers)
        self.assertTrue(dag.is_below("note", "about(planet)"))

    def test_stores_readers_and_certificates(self):
        from ontodag.certificates import prove_below, verify_below
        blobs = MemoryBytesStore()
        eager = subjects(EagerOntoDAG(RecordStore(blobs)))
        root = eager.commit()
        reader = LazyOntoDAG(RecordStore.at(root, blobs))
        for sub, sup, expected in (("shibuya-photo", "about(asia)", True),
                                   ("earthrise", "about(planet)", True),
                                   ("shibuya-photo", "in(japan)", False)):
            self.assertEqual(reader.is_below(sub, sup), expected, (sub, sup))
            cert = prove_below(eager, sub, sup)
            self.assertEqual(verify_below(cert, root), expected, (sub, sup))


ORG = (("person", []), ("employee", ["person"]),
       ("acme-employee", ["employee"]),
       ("sales-employee", ["acme-employee"]),
       ("finance-employee", ["acme-employee"]), ("manager", ["person"]),
       ("alice", ["sales-employee"]), ("bob", ["finance-employee"]),
       ("dave", ["sales-employee", "manager"]),
       ("q3-plan", ["shared-with(sales-employee)"]),
       ("handbook", ["shared-with(acme-employee)"]),
       ("payslip", ["shared-with(alice)"]),
       ("budget", ["shared-with(sales-employee)", "shared-with(finance-employee)"]),
       ("targets", ["shared-with(manager sales-employee)"]))


def org(dag=None):
    """Acme's people, ordered by kinds (never by `in`), and documents filed
    for audiences."""
    dag = declare(dag, audience=True)
    for name, supers in ORG:
        dag.put(name, supers)
    return dag


class TestARemovedConstraint(unittest.TestCase):
    """A category may be removed while a stored relation term names it
    (graph-ordered terms guard nothing, DIMENSIONS.md §14). The term then
    names something that no longer exists, and nothing is inside that.
    Until 2026-10-09 an `about` compound naming the removed category made
    every query and write that walked it raise (the `in(c1 c4)` it derives
    no longer parsed), while the sparse writer, which never loaded the
    term, accepted the same writes."""

    def check(self, remove):
        dag = declare(about=True)
        for name in ("c0", "c1", "c4"):
            dag.put(name, [])
        dag.put("x0", ["about(c1 c4)"])
        dag.put("x1", ["about(c1)"])
        remove(dag)
        dag.put("c1", ["c0"])                 # walks the term: raised
        self.assertEqual(names(dag.get(["about(c1)"])) & {"x0", "x1"},
                         {"x0", "x1"})
        self.assertEqual(names(dag.get(["about(c0)"])) & {"x0", "x1"},
                         {"x0", "x1"})
        self.assertTrue(dag.is_below("x0", "about(c0)"))

    def test_after_contraction(self):
        self.check(lambda dag: dag.remove("c4"))

    def test_after_cone_removal(self):
        self.check(lambda dag: dag.remove_cone(["c4"]))

    def test_a_term_beside_one_naming_the_removed_category(self):
        # The containment check derives `in(c3 c5)` from `about(c5 c3)`
        # when it compares the two terms: the second path that raised.
        dag = declare(about=True)
        for name in ("c0", "c1", "c3", "c5"):
            dag.put(name, [])
        dag.put("x1", ["about(c1 c5)"])
        dag.put("x3", ["about(c5 c3)"])
        dag.remove_cone(["c5"])
        dag.reclassify(["c1"], to=["c0"])
        dag.put("c3", ["c1"])
        self.assertTrue(dag.is_below("x3", "about(c0)"))
        self.assertTrue(dag.is_below("x1", "about(c0)"))


class TestAudience(unittest.TestCase):
    """The reversed kind: `for` (DIMENSIONS.md §18)."""

    def setUp(self):
        self.dag = org()

    def test_what_is_for_a_group_is_for_each_member(self):
        below = self.dag.is_below
        self.assertTrue(below("shared-with(sales-employee)", "shared-with(alice)"))
        self.assertTrue(below("shared-with(acme-employee)", "shared-with(sales-employee)"))
        self.assertFalse(below("shared-with(alice)", "shared-with(sales-employee)"))
        self.assertTrue(below("handbook", "shared-with(bob)"))
        self.assertFalse(below("q3-plan", "shared-with(bob)"))
        # the plan is for Alice; it is not Alice
        self.assertFalse(below("q3-plan", "alice"))

    def test_what_someone_may_see_is_one_cone(self):
        def sees(who):
            return names(self.dag.get([f"shared-with({who})"], items_only=True))
        self.assertEqual(sees("alice"), {"q3-plan", "handbook", "payslip", "budget"})
        self.assertEqual(sees("bob"), {"handbook", "budget"})
        self.assertEqual(sees("dave"), {"q3-plan", "handbook", "budget", "targets"})

    def test_kinds_only_never_in(self):
        dag = declare(audience=True)
        for name, supers in (("japan", []), ("tokyo", ["in(japan)"]),
                             ("alice", ["in(tokyo)"]), ("notice", ["shared-with(japan)"])):
            dag.put(name, supers)
        # Alice lives in Tokyo, in Japan: a notice for Japan is not for her,
        # or filing where she lives would grant her access
        self.assertFalse(dag.is_below("shared-with(japan)", "shared-with(alice)"))
        self.assertFalse(dag.is_below("notice", "shared-with(alice)"))

    def test_a_conjunction_is_the_people_in_both(self):
        below = self.dag.is_below
        self.assertTrue(below("targets", "shared-with(dave)"))
        self.assertFalse(below("targets", "shared-with(alice)"))
        # what is for every sales employee is for the sales managers
        self.assertTrue(below("shared-with(sales-employee)", "shared-with(manager sales-employee)"))

    def test_several_audiences_stay_separate(self):
        self.assertEqual(parents(self.dag, "budget"),
                         {"shared-with(finance-employee)", "shared-with(sales-employee)"})
        self.assertEqual(self.dag.meet("shared-with(acme-employee)", "shared-with(sales-employee)"),
                         "shared-with(acme-employee)")
        with self.assertRaisesRegex(ValueError, "no single term"):
            self.dag.meet("shared-with(sales-employee)", "shared-with(finance-employee)")

    def test_the_wider_audience_wins(self):
        self.dag.put("memo", ["shared-with(acme-employee)", "shared-with(sales-employee)"])
        self.assertEqual(parents(self.dag, "memo"), {"shared-with(acme-employee)"})

    def test_a_late_membership_reduces_what_was_filed_before_it(self):
        def build_(late):
            dag = declare(audience=True)
            for name in ("finance-employee", "carol"):
                dag.put(name, [])
            if not late:
                dag.put("carol", ["finance-employee"])
            dag.put("note", ["shared-with(carol)", "shared-with(finance-employee)"])
            if late:
                dag.put("carol", ["finance-employee"])
            return dag
        early, late = build_(False), build_(True)
        self.assertEqual(parents(late, "note"), {"shared-with(finance-employee)"})
        self.assertEqual(edge_set(early), edge_set(late))

    def test_a_rule_is_refused_and_leaves_nothing(self):
        dag = declare(about=True, audience=True)
        for name in ("board", "secret", "japan", "japanese"):
            dag.put(name, [])
        for term, parent in (("shared-with(board)", "secret"), ("in(japan)", "japanese"),
                             ("about(japan)", "japanese")):
            before = edge_set(dag)
            with self.assertRaisesRegex(ValueError, "would state a rule"):
                dag.put(term, [parent])
            self.assertEqual(edge_set(dag), before)
            self.assertNotIn(term, dag.nodes)
        dag.put("minutes", ["shared-with(board)"])          # the term itself is fine
        with self.assertRaisesRegex(ValueError, "would state a rule"):
            dag.put("shared-with(board)", ["secret"])

    def test_stores_readers_certificates_and_the_sparse_writer(self):
        from ontodag.certificates import prove_below, verify_below

        def root(order):
            dag = declare(EagerOntoDAG(RecordStore(MemoryBytesStore())),
                          audience=True)
            for name, supers in order:
                dag.put(name, supers)
            return dag.commit()
        create = [(name, []) for name, _ in ORG]
        facts = [(name, [sup]) for name, supers in ORG for sup in supers]
        rnd = random.Random(3)
        roots = set()
        for _ in range(3):
            rnd.shuffle(facts)
            roots.add(root(create + facts))
        self.assertEqual(len(roots), 1)

        blobs = MemoryBytesStore()
        eager = org(EagerOntoDAG(RecordStore(blobs)))
        stored = eager.commit()
        self.assertIn(stored, roots)
        reader = LazyOntoDAG(RecordStore.at(stored, blobs))
        for sub, sup, expected in (("q3-plan", "shared-with(alice)", True),
                                   ("q3-plan", "shared-with(bob)", False),
                                   ("targets", "shared-with(dave)", True),
                                   ("shared-with(acme-employee)", "shared-with(alice)", True)):
            self.assertEqual(reader.is_below(sub, sup), expected, (sub, sup))
            cert = prove_below(eager, sub, sup)
            self.assertEqual(verify_below(cert, stored), expected, (sub, sup))
        self.assertEqual(names(reader.get(["shared-with(alice)"], items_only=True)),
                         {"q3-plan", "handbook", "payslip", "budget"})

        blobs = MemoryBytesStore()
        base = declare(EagerOntoDAG(RecordStore(blobs)), audience=True).commit()
        eager = EagerOntoDAG(RecordStore(blobs, root=base))
        sparse = SparseOntoDAG(RecordStore(blobs, root=base))
        for name, supers in ORG:
            eager.put(name, supers)
            sparse.put(name, supers)
        self.assertEqual(eager.commit(), sparse.commit())


class TestDeepChains(unittest.TestCase):
    """Containment must not cost a stack frame per level (I6). Asking
    whether a photo in p0 is in p3000 walks 3,000 containers; when the
    transitive rule recursed through is_below, 200 levels ran out of stack.
    Everything is built directly, edge by edge, so the test measures the
    question and not the cost of filing (which still grows with the
    number of terms per head: DIMENSIONS.md §18)."""

    @staticmethod
    def chain(dag, depth, head, name):
        # p0 ⊑ head(p1) ⊑ … : each term anchored under its head, each place
        # under the next place's term — already reduced, so no put needed
        head_node = dag.nodes[head]
        top = Item(f"{name}{depth}")
        dag.add_node(top)
        DAG.add_edge(dag, dag.root, top)
        for i in range(depth - 1, -1, -1):
            place, term = Item(f"{name}{i}"), Item(f"{head}({name}{i + 1})")
            dag.add_node(place)
            dag.add_node(term)
            DAG.add_edge(dag, head_node, term)
            DAG.add_edge(dag, term, place)

    @staticmethod
    def hang(dag, name, term):
        """`name` filed under `term`, the term anchored under its head."""
        item, node = Item(name), dag.nodes.get(term) or Item(term)
        if term not in dag.nodes:
            dag.add_node(node)
            DAG.add_edge(dag, dag.nodes[term.split("(")[0]], node)
        dag.add_node(item)
        DAG.add_edge(dag, node, item)

    def test_three_thousand_levels(self):
        dag = declare(about=True, audience=True)
        self.chain(dag, 3000, "in", "p")
        self.hang(dag, "photo", "in(p0)")
        self.hang(dag, "note", "about(p0)")
        self.assertTrue(dag.is_below("photo", "in(p3000)"))
        self.assertTrue(dag.is_below("note", "about(p3000)"))
        self.assertFalse(dag.is_below("photo", "about(p3000)"))
        # nested groups, each under the next: what is for the top group is
        # for the bottom one (500 deep: the reversed rule walks plain
        # ancestors and never recursed; deeper only costs setup time, each
        # edge raising every ancestor's count)
        top = Item("g500")
        dag.add_node(top)
        DAG.add_edge(dag, dag.root, top)
        for i in range(499, -1, -1):
            group = Item(f"g{i}")
            dag.add_node(group)
            DAG.add_edge(dag, dag.nodes[f"g{i + 1}"], group)
        self.hang(dag, "doc", "shared-with(g500)")
        self.assertTrue(dag.is_below("doc", "shared-with(g0)"))
        self.assertFalse(dag.is_below("doc", "shared-with(p0)"))


class TestCertificatesAcrossProcesses(unittest.TestCase):
    """A verifier in another process iterates sets in another order, so its
    walk may take another path; the certificate must cover every path. The
    reversed rule walks up from the BOUND's argument (`alice` in
    `shared-with(alice)`), which no earlier kind does."""

    def test_verifies_under_other_hash_seeds(self):
        import json, os, subprocess, sys, tempfile
        from ontodag.certificates import prove_below
        blobs = MemoryBytesStore()
        dag = org(subjects(EagerOntoDAG(RecordStore(blobs))))
        root = dag.commit()
        cases = [("shibuya-photo", "about(asia)", True),
                 ("mona-lisa", "in(in(louvre))", True),
                 ("louvre-pyramid", "in(in(louvre))", False),
                 ("q3-plan", "shared-with(alice)", True),
                 ("q3-plan", "shared-with(bob)", False),
                 ("targets", "shared-with(dave)", True)]
        jobs = [{"cert": prove_below(dag, sub, sup), "expected": expected}
                for sub, sup, expected in cases]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"root": root, "jobs": jobs}, fh)
            path = fh.name
        self.addCleanup(os.unlink, path)
        code = ("import json\n"
                "from ontodag.certificates import verify_below\n"
                f"data = json.load(open({path!r}))\n"
                "for job in data['jobs']:\n"
                "    assert verify_below(job['cert'], data['root']) == job['expected'], job['cert']['sub']\n")
        src = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "src")
        for seed in ("0", "1", "42"):
            env = dict(os.environ, PYTHONPATH=src, PYTHONHASHSEED=seed)
            proc = subprocess.run([sys.executable, "-c", code], env=env,
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, f"seed={seed}:\n{proc.stderr}")


# ---- the oracle -----------------------------------------------------------

class Oracle:
    """The combined order over plain names and `in`/`about`/`for` terms of
    them, from the asserted (child, parent) pairs alone."""

    def __init__(self, nodes, edges):
        self.nodes = list(nodes)
        terms = [f"{r}({n})" for r in ("in", "about", "shared-with") for n in self.nodes]
        universe = set(self.nodes) | set(terms) | {p for _c, p in edges} \
            | {c for c, _p in edges}
        below = {(a, a) for a in universe} | set(edges)
        while True:
            up = {}
            for a, b in below:
                up.setdefault(a, set()).add(b)
            new = {(a, c) for a, bs in up.items() for b in bs
                   for c in up.get(b, ()) if (a, c) not in below}
            for x in self.nodes:
                for y in self.nodes:
                    lifts = (x, y) in below or (x, f"in({y})") in below
                    for r in ("in", "about"):
                        pair = (f"{r}({x})", f"{r}({y})")
                        if lifts and pair not in below:
                            new.add(pair)
                    # reversed: what is for all of y is for x, a part of it
                    pair = (f"shared-with({y})", f"shared-with({x})")
                    if (x, y) in below and pair not in below:
                        new.add(pair)
            if not new:
                break
            below |= new
        self.below = below
        self.universe = sorted(universe)

    def bad(self):
        """A cycle, or something inside itself."""
        return any(a != b and (b, a) in self.below for a, b in self.below) \
            or any((x, f"in({x})") in self.below for x in self.nodes)

    def stored_parents(self, child, asserted):
        """The reduced form: the asserted parents not above another one."""
        ps = {p for c, p in asserted if c == child}
        return {p for p in ps
                if not any(q != p and (q, p) in self.below for q in ps)} or {"*"}


def escapes(child, parent):
    """A relation term filed under anything but its head: a rule, which
    `put` refuses (CONTRACT.md §5.1)."""
    return "(" in child


def random_world(seed, size=8, attempts=16):
    rnd = random.Random(seed)
    nodes = [f"n{i}" for i in range(size)]
    tries = []
    for _ in range(attempts):
        child, parent = rnd.choice(nodes), rnd.choice(nodes)
        shape = rnd.random()
        if shape < 0.12:
            # a term filed under a plain name: "whatever is for n1 is n2"
            head = rnd.choice(("in", "about", "shared-with"))
            tries.append((f"{head}({child})", parent))
            continue
        tries.append((child, f"in({parent})" if shape < 0.45
                      else f"about({parent})" if shape < 0.6
                      else f"shared-with({parent})" if shape < 0.75 else parent))
    return nodes, tries


def build(nodes, edges, dag=None):
    dag = declare(dag, about=True, audience=True)
    for n in nodes:
        dag.put(n, [])
    for child, parent in edges:
        dag.put(child, [parent])
    return dag


class TestAgainstTheOracle(unittest.TestCase):
    def test_answers_refusals_and_stored_form(self):
        refusals = 0
        for seed in range(40):
            nodes, tries = random_world(seed)
            dag = build(nodes, [])
            asserted = set()
            for child, parent in tries:
                if child == parent:
                    continue
                candidate = asserted | {(child, parent)}
                expect_refusal = escapes(child, parent) \
                    or Oracle(nodes, candidate).bad()
                before = (set(dag.nodes), edge_set(dag))
                try:
                    dag.put(child, [parent])
                    refused = False
                except ValueError:
                    refused = True
                self.assertEqual(refused, expect_refusal, (seed, child, parent))
                if refused:     # a refusal leaves nothing behind, not even a term
                    self.assertEqual((set(dag.nodes), edge_set(dag)), before,
                                     (seed, child, parent))
                if refused:
                    refusals += 1
                else:
                    asserted = candidate
            oracle = Oracle(nodes, asserted)
            for a in oracle.universe:
                for b in oracle.universe:
                    self.assertEqual(dag.is_below(a, b), (a, b) in oracle.below,
                                     (seed, a, b))
            for n in nodes:
                self.assertEqual(parents(dag, n),
                                 oracle.stored_parents(n, asserted), (seed, n))
        self.assertGreater(refusals, 10)        # the guard was exercised

    def _accepted(self, seed):
        nodes, tries = random_world(seed)
        asserted = []
        for child, parent in tries:
            if child != parent and not escapes(child, parent) and not Oracle(
                    nodes, set(asserted) | {(child, parent)}).bad():
                asserted.append((child, parent))
        return nodes, asserted

    def test_order_does_not_matter(self):
        for seed in range(25):
            nodes, asserted = self._accepted(seed)
            reference = edge_set(build(nodes, asserted))
            rnd = random.Random(seed)
            for _ in range(3):
                shuffled = asserted[:]
                rnd.shuffle(shuffled)
                self.assertEqual(edge_set(build(nodes, shuffled)), reference, seed)

    def test_merge_commutes_and_equals_the_union(self):
        for seed in range(25):
            nodes, asserted = self._accepted(seed)
            rnd = random.Random(seed)
            left = [e for e in asserted if rnd.random() < 0.5]
            right = [e for e in asserted if e not in left]
            a, b = build(nodes, left), build(nodes, right)
            ab, ba = a.deepcopy(), b.deepcopy()
            ab.merge(b)
            ba.merge(a)
            self.assertEqual(edge_set(ab), edge_set(ba), seed)
            self.assertEqual(edge_set(ab), edge_set(build(nodes, asserted)), seed)


class TestStoresAndReaders(unittest.TestCase):
    def test_roots_agree_across_orders(self):
        def root(order):
            blobs = MemoryBytesStore()
            dag = declare(EagerOntoDAG(RecordStore(blobs)))
            for name, supers in order:
                dag.put(name, supers)
            return dag.commit()
        # every name first (a term names only present categories), then
        # the facts, one per put, in shuffled orders
        facts = [(name, [sup]) for name, supers in GEOGRAPHY for sup in supers]
        facts += [("trip", ["in(tokyo)"]), ("trip", ["in(japan)"])]
        create = [(name, []) for name, _ in GEOGRAPHY] + [("trip", [])]
        rnd = random.Random(1)
        roots = set()
        for _ in range(3):
            shuffled = facts[:]
            rnd.shuffle(shuffled)
            roots.add(root(create + shuffled))
        self.assertEqual(len(roots), 1)

    def test_a_lazy_reader_answers_like_the_writer(self):
        blobs = MemoryBytesStore()
        eager = geography(EagerOntoDAG(RecordStore(blobs)))
        root = eager.commit()
        reader = LazyOntoDAG(RecordStore.at(root, blobs))
        for sub, sup in (("photo", "in(asia)"), ("in(tokyo)", "in(japan)"),
                         ("louvre-pyramid", "in(in(louvre))"),
                         ("mona-lisa", "in(in(louvre))"),
                         ("zermatt", "in(alps)"), ("photo", "japan")):
            self.assertEqual(reader.is_below(sub, sup), eager.is_below(sub, sup),
                             (sub, sup))
        self.assertEqual(names(reader.get(["city", "in(japan)"])), {"tokyo"})

    def test_certificates_prove_both_answers(self):
        from ontodag.certificates import prove_below, verify_below
        blobs = MemoryBytesStore()
        eager = geography(EagerOntoDAG(RecordStore(blobs)))
        root = eager.commit()
        for sub, sup, expected in (("photo", "in(asia)", True),
                                   ("in(tokyo)", "in(japan)", True),
                                   ("mona-lisa", "in(in(louvre))", True),
                                   ("louvre-pyramid", "in(in(louvre))", False),
                                   ("photo", "japan", False)):
            cert = prove_below(eager, sub, sup)
            self.assertEqual(verify_below(cert, root), expected, (sub, sup))

    def test_the_sparse_writer_matches_the_eager_one(self):
        blobs = MemoryBytesStore()
        base = declare(EagerOntoDAG(RecordStore(blobs))).commit()
        eager = EagerOntoDAG(RecordStore(blobs, root=base))
        sparse = SparseOntoDAG(RecordStore(blobs, root=base))
        for name, supers in GEOGRAPHY:
            eager.put(name, supers)
            sparse.put(name, supers)
        self.assertEqual(eager.commit(), sparse.commit())



class TestTheStoredSpellingStaysCurrent(unittest.TestCase):
    """A relation term with several constraints means ONE thing meeting all
    of them (`shared-with(manager sales-employee)` is for the people who
    are both), so unlike the graph kind's it is stored as written. Its
    spelling follows the graph, though: once a fact makes a constraint
    redundant, the stored term is re-filed under its current spelling
    (Peter's option 1, 2026-10-08; DIMENSIONS.md §16). Until then a plan
    shared with `shared-with(employee sales-employee)` before the org chart
    said sales employees are employees kept that name, a second name for
    `shared-with(sales-employee)`, under a different root from a store that
    knew it first, which refused the spelling."""

    def org(self):
        dag = declare(EagerOntoDAG(RecordStore(MemoryBytesStore())),
                      about=True, audience=True)
        for name, supers in (("person", []), ("employee", ["person"]),
                             ("sales-employee", ["person"]),
                             ("alice", ["sales-employee"])):
            dag.put(name, supers)
        return dag

    def test_the_audience_converges(self):
        early, late = self.org(), self.org()
        early.put("sales-employee", ["employee"])
        early.put("plan", ["shared-with(employee sales-employee)"])
        late.put("plan", ["shared-with(employee sales-employee)"])
        late.put("sales-employee", ["employee"])
        for dag in (early, late):
            self.assertEqual(parents(dag, "plan"), {"shared-with(sales-employee)"})
            self.assertNotIn("shared-with(employee sales-employee)", dag.nodes)
            self.assertTrue(dag.is_below("plan", "shared-with(alice)"))
            self.assertTrue(dag.is_below(
                "plan", "shared-with(employee sales-employee)"))
        root = early.commit()
        self.assertEqual(late.commit(), root)
        for first, second in ((early, late), (late, early)):
            merged = EagerOntoDAG(RecordStore(MemoryBytesStore()))
            merged.merge(first)
            merged.merge(second)
            self.assertEqual(merged.commit(), root)

    def test_a_peers_old_spelling_is_re_filed_on_merge(self):
        # The peer filed before it knew; this store knew first. Neither
        # replays an edge that relates the constraints: the merge itself
        # has to notice the old spelling.
        peer, ours = self.org(), self.org()
        peer.put("plan", ["shared-with(employee sales-employee)"])
        ours.put("sales-employee", ["employee"])
        ours.merge(peer)
        self.assertEqual(parents(ours, "plan"), {"shared-with(sales-employee)"})
        self.assertNotIn("shared-with(employee sales-employee)", ours.nodes)
        known = self.org()
        known.put("sales-employee", ["employee"])
        known.put("plan", ["shared-with(sales-employee)"])
        self.assertEqual(ours.commit(), known.commit())

    def test_a_sync_re_files_too(self):
        blobs = MemoryBytesStore()
        a = declare(EagerOntoDAG(RecordStore(blobs)), audience=True)
        for name, supers in (("person", []), ("employee", ["person"]),
                             ("sales-employee", ["person"]),
                             ("alice", ["sales-employee"])):
            a.put(name, supers)
        base_root = a.commit()
        b = EagerOntoDAG(RecordStore(blobs, root=base_root))
        a.put("plan", ["shared-with(employee sales-employee)"])
        a_root = a.commit()
        b.put("sales-employee", ["employee"])
        b.commit()
        b.sync(a_root)
        self.assertEqual(parents(b, "plan"), {"shared-with(sales-employee)"})
        self.assertNotIn("shared-with(employee sales-employee)", b.nodes)

    def test_a_fact_from_a_peer_re_files_our_term_on_merge(self):
        # The other direction: this store holds the compound, the peer
        # brings the fact. The fact's edge is replayed while the merge is
        # lenient, so the re-filing waits for the end of the merge.
        ours, peer = self.org(), self.org()
        ours.put("plan", ["shared-with(employee sales-employee)"])
        peer.put("sales-employee", ["employee"])
        ours.merge(peer)
        self.assertEqual(parents(ours, "plan"), {"shared-with(sales-employee)"})
        self.assertNotIn("shared-with(employee sales-employee)", ours.nodes)
        known = self.org()
        known.put("sales-employee", ["employee"])
        known.put("plan", ["shared-with(sales-employee)"])
        self.assertEqual(ours.commit(), known.commit())

    def test_a_fact_from_a_peer_re_files_our_term_on_sync(self):
        blobs = MemoryBytesStore()
        a = declare(EagerOntoDAG(RecordStore(blobs)), audience=True)
        for name, supers in (("person", []), ("employee", ["person"]),
                             ("sales-employee", ["person"])):
            a.put(name, supers)
        base = a.commit()
        b = EagerOntoDAG(RecordStore(blobs, root=base))
        a.put("plan", ["shared-with(employee sales-employee)"])
        a.commit()
        b.put("sales-employee", ["employee"])
        b_root = b.commit()
        a.sync(b_root)
        self.assertEqual(parents(a, "plan"), {"shared-with(sales-employee)"})
        self.assertNotIn("shared-with(employee sales-employee)", a.nodes)

    def test_a_term_naming_a_re_filed_one_follows_it(self):
        dag = declare(about=True)
        for name, supers in (("place", []), ("church", ["place"]),
                             ("landmark", ["place"])):
            dag.put(name, supers)
        dag.put("map", ["in(in(church landmark))"])
        dag.put("church", ["landmark"])
        self.assertEqual(parents(dag, "map"), {"in(in(church))"})
        self.assertNotIn("in(in(church landmark))", dag.nodes)

    def test_places_topics_and_nesting(self):
        dag = declare(about=True)
        for name, supers in (("place", []), ("church", ["place"]),
                             ("landmark", ["place"]), ("animal", []),
                             ("dog", ["animal"]), ("poodle", ["animal"])):
            dag.put(name, supers)
        dag.put("photo", ["in(church landmark)"])
        dag.put("note", ["about(dog poodle)"])
        dag.put("map", ["in(in(church landmark))"])
        dag.put("church", ["landmark"])
        dag.put("poodle", ["dog"])
        self.assertEqual(parents(dag, "photo"), {"in(church)"})
        self.assertEqual(parents(dag, "note"), {"about(poodle)"})
        self.assertEqual(parents(dag, "map"), {"in(in(church))"})
        for stale in ("in(church landmark)", "about(dog poodle)",
                      "in(in(church landmark))"):
            self.assertNotIn(stale, dag.nodes)
            self.assertEqual(dag._canonical_name(stale),
                             stale.replace("church landmark", "church")
                             .replace("dog poodle", "poodle"))

    def test_into_a_term_that_already_holds_things(self):
        dag = self.org()
        dag.put("handbook", ["shared-with(sales-employee)"])
        dag.put("plan", ["shared-with(employee sales-employee)"])
        dag.put("sales-employee", ["employee"])
        self.assertEqual({i.name for i in dag.get(
            ["shared-with(sales-employee)"], items_only=True)},
            {"handbook", "plan"})
        self.assertEqual([n for n in dag.nodes if n.startswith("shared-with(")],
                         ["shared-with(sales-employee)"])

    def test_the_sparse_writer_lands_on_the_same_root(self):
        blobs = MemoryBytesStore()
        eager = self.org()
        base = declare(EagerOntoDAG(RecordStore(blobs)), about=True,
                       audience=True)
        for name, supers in (("person", []), ("employee", ["person"]),
                             ("sales-employee", ["person"]),
                             ("alice", ["sales-employee"])):
            base.put(name, supers)
        root = base.commit()
        sparse = SparseOntoDAG(RecordStore(blobs, root=root))
        for dag in (sparse, eager):
            dag.put("plan", ["shared-with(employee sales-employee)"])
            dag.put("sales-employee", ["employee"])
        self.assertEqual(sparse.commit(), eager.commit())


class TestRelationSpellingAgainstOrders(unittest.TestCase):
    """Random worlds: items under relation terms with one or two
    constraints, and category edges that relate constraints, written in
    every order and merged. One root, and no two stored terms of one head
    naming one class (I1)."""

    def world(self, seed):
        rng = random.Random(seed)
        cats = [f"c{i}" for i in range(6)]
        edges = [(cats[i], cats[j]) for i in range(6) for j in range(i + 1, 6)
                 if rng.random() < 0.3]

        def term():
            head = rng.choice(["in", "about", "shared-with"])
            return f"{head}({' '.join(rng.sample(cats, rng.choice((1, 2, 2))))})"

        items = {f"x{k}": [term() for _ in range(rng.choice((1, 2)))]
                 for k in range(6)}
        return cats, edges, items

    def build(self, world, order):
        cats, edges, items = world
        dag = declare(EagerOntoDAG(RecordStore(MemoryBytesStore())),
                      about=True, audience=True)
        for c in cats:
            dag.put(c, [])
        writes = [("edge", e) for e in edges] + [("item", i) for i in items.items()]
        random.Random(order).shuffle(writes)
        for kind, (a, b) in writes:
            dag.put(a, [b] if kind == "edge" else b)
        return dag

    def test_every_order_and_merge_gives_one_root(self):
        for seed in range(30):
            world = self.world(seed)
            dags = [self.build(world, order) for order in range(4)]
            roots = {dag.commit() for dag in dags}
            merged = EagerOntoDAG(RecordStore(MemoryBytesStore()))
            merged.merge(dags[1])
            merged.merge(dags[3])
            roots.add(merged.commit())
            self.assertEqual(len(roots), 1, seed)
            dag = dags[0]
            for head in ("in", "about", "shared-with"):
                terms = [n for n in dag.nodes if n.startswith(head + "(")]
                for a in terms:
                    for b in terms:
                        if a != b:
                            self.assertFalse(
                                dag.is_below(a, b) and dag.is_below(b, a),
                                (seed, a, b))

if __name__ == "__main__":
    unittest.main()
