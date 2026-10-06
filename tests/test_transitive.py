"""The transitive kind, `in`, and the enclosing kind, `about`
(docs/DIMENSIONS.md §16 and §17, docs/plans/ROLES.md).

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

`Oracle` recomputes the combined order from the asserted edges alone, as
the least fixpoint of five rules: reflexive, transitive, the asserted
edges, `in(x) ⊑ in(y)` when `x ⊑ y` or `x ⊑ in(y)`, and `about(x) ⊑
about(y)` when `x ⊑ y` or `x ⊑ in(y)`. It shares nothing with the
traversals, containment code and memo under test.
"""

import random
import unittest

from recordstore import MemoryBytesStore, RecordStore

from ontodag import prelude
from ontodag.dag import OntoDAG
from ontodag.eager import EagerOntoDAG
from ontodag.lazy import LazyOntoDAG, SparseOntoDAG


def names(items):
    return {item.name for item in items}


def edge_set(dag):
    return {(parent.name, child.name)
            for parent in dag.nodes.values() for child in parent.neighbors}


def parents(dag, name):
    return {parent.name for parent in dag.nodes[name].parents}


def declare(dag=None, about=False):
    dag = dag if dag is not None else OntoDAG()
    prelude.apply(dag)
    dag.put("transitive-dimension", ["dimension"])
    dag.put("in", ["transitive-dimension"])
    if about:
        dag.put("enclosing-dimension", ["dimension"])
        dag.put("about", ["enclosing-dimension"])
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


# ---- the oracle -----------------------------------------------------------

class Oracle:
    """The combined order over plain names and `in(name)` terms, from the
    asserted (child, parent) pairs alone."""

    def __init__(self, nodes, edges):
        self.nodes = list(nodes)
        terms = [f"{r}({n})" for r in ("in", "about") for n in self.nodes]
        universe = set(self.nodes) | set(terms) | {p for _c, p in edges}
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


def random_world(seed, size=8, attempts=16):
    rnd = random.Random(seed)
    nodes = [f"n{i}" for i in range(size)]
    tries = []
    for _ in range(attempts):
        child, parent = rnd.choice(nodes), rnd.choice(nodes)
        shape = rnd.random()
        tries.append((child, f"in({parent})" if shape < 0.45
                      else f"about({parent})" if shape < 0.65 else parent))
    return nodes, tries


def build(nodes, edges, dag=None):
    dag = declare(dag, about=True)
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
                expect_refusal = Oracle(nodes, candidate).bad()
                try:
                    dag.put(child, [parent])
                    refused = False
                except ValueError:
                    refused = True
                self.assertEqual(refused, expect_refusal, (seed, child, parent))
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
            if child != parent and not Oracle(
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


if __name__ == "__main__":
    unittest.main()
