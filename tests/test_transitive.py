"""The transitive kind: `in` (docs/DIMENSIONS.md §16, docs/plans/ROLES.md).

A head declared under `transitive-dimension` names a relation that chains:
`in(tokyo) ⊑ in(japan)` once `tokyo ⊑ in(japan)`, because whatever is in
Tokyo is in Japan. Its parameters are graph constraints, as for the graph
kind. Unlike the graph kind, two terms of one head on one item stay
separate (a photo can be in Tokyo and in Paris), and the relation is
strict: nothing is in itself, so an edge that would put a thing inside
itself is refused.

`Oracle` recomputes the combined order from the asserted edges alone, as
the least fixpoint of four rules: reflexive, transitive, the asserted
edges, and `R(x) ⊑ R(y)` when `x ⊑ y` or `x ⊑ R(y)`. It shares nothing
with the traversals, containment code and memo under test.
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


def declare(dag=None):
    dag = dag if dag is not None else OntoDAG()
    prelude.apply(dag)
    dag.put("transitive-dimension", ["dimension"])
    dag.put("in", ["transitive-dimension"])
    return dag


GEOGRAPHY = (("place", []), ("city", ["place"]), ("asia", ["place"]),
             ("japan", ["place", "in(asia)"]),
             ("kanto", ["place", "in(japan)"]),
             ("tokyo", ["city", "in(kanto)"]),
             ("photo", ["in(tokyo)"]),
             ("acme", []), ("sales", ["in(acme)"]),
             ("alice", ["in(sales)"]), ("bob", ["in(acme)"]))


def geography(dag=None):
    """Tokyo in Kanto in Japan in Asia, a photo in Tokyo; Alice in sales
    in Acme, Bob directly in Acme."""
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
        # transitivity gives in(in(Z)) ⊑ in(Z) only: Bob works for Acme
        # directly, in no department, so he is in Acme but in nothing
        # that is in Acme
        below = self.dag.is_below
        self.assertTrue(below("in(in(acme))", "in(acme)"))
        self.assertFalse(below("in(acme)", "in(in(acme))"))
        self.assertTrue(below("alice", "in(in(acme))"))
        self.assertFalse(below("bob", "in(in(acme))"))
        self.assertTrue(below("bob", "in(acme)"))
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
        self.assertEqual(names(get(["in(acme)", "in(in(acme))"],
                                   items_only=True)), {"alice"})


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
        self.dag.put("flight", ["in(tokyo)", "in(acme)"])
        self.assertEqual(parents(self.dag, "flight"), {"in(tokyo)", "in(acme)"})

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
        with self.assertRaisesRegex(ValueError, "no single term"):
            self.dag.meet("in(tokyo)", "in(acme)")
        self.assertTrue(self.dag.overlaps("in(tokyo)", "in(acme)"))


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


# ---- the oracle -----------------------------------------------------------

class Oracle:
    """The combined order over plain names and `in(name)` terms, from the
    asserted (child, parent) pairs alone."""

    def __init__(self, nodes, edges):
        self.nodes = list(nodes)
        terms = [f"in({n})" for n in self.nodes]
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
                    pair = (f"in({x})", f"in({y})")
                    if pair not in below and ((x, y) in below
                                              or (x, f"in({y})") in below):
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
        tries.append((child, f"in({parent})" if rnd.random() < 0.6 else parent))
    return nodes, tries


def build(nodes, edges, dag=None):
    dag = declare(dag)
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
                         ("bob", "in(in(acme))"), ("alice", "in(in(acme))"),
                         ("photo", "japan")):
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
                                   ("alice", "in(in(acme))", True),
                                   ("bob", "in(in(acme))", False),
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
