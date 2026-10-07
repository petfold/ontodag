"""Narrower relations (docs/DIMENSIONS.md §20, docs/plans/ROLES.md §4).

A head of a relation kind (transitive, enclosing, reversed) filed under
another head of the same kind names a narrower relation: with `departure`
under `from`, every `departure(x)` is a `from(x)`, so a flight departing
from Heathrow is found by `get from(lhr)`. `departure(x) ⊑ from(y)` holds
exactly when `from(x) ⊑ from(y)`; a broader term is never inside a
narrower one.

`Oracle` recomputes the combined order from the asserted edges alone, as
the least fixpoint of the rules of `tests/test_transitive.py` for seven
heads, plus one more: `R(x) ⊑ S(x)` for each declared narrower pair. A
transitive head chains through its own terms and the narrower ones
(`x ⊑ inside(y)` puts x `in(y)`, but `x ⊑ in(y)` does not put it
`inside(y)`). It shares nothing with the code under test.
"""

import random
import unittest

from recordstore import MemoryBytesStore, RecordStore

from ontodag import prelude
from ontodag.dag import OntoDAG
from ontodag.eager import EagerOntoDAG
from ontodag.lazy import LazyOntoDAG, SparseOntoDAG

# head -> (kind, the head it is declared under: its kind node or a broader head)
HEADS = {
    "in": ("transitive", None), "inside": ("transitive", "in"),
    "about": ("enclosing", None), "topic": ("enclosing", "about"),
    "subtopic": ("enclosing", "topic"),
    "shared-with": ("reversed", None), "editor": ("reversed", "shared-with"),
}
KIND_NODE = {"transitive": "transitive-dimension",
             "enclosing": "enclosing-dimension",
             "reversed": "reversed-dimension"}


def edge_set(dag):
    return {(parent.name, child.name)
            for parent in dag.nodes.values() for child in parent.neighbors}


def parents(dag, name):
    return {parent.name for parent in dag.nodes[name].parents}


def declare(dag=None, narrower=True):
    """The seven heads; with `narrower=False` each is declared under its
    kind node instead, as a relation of its own."""
    dag = dag if dag is not None else OntoDAG()
    prelude.apply(dag)
    for kind_node in KIND_NODE.values():
        dag.put(kind_node, ["dimension"])
    for head, (kind, broader) in HEADS.items():
        dag.put(head, [broader if broader and narrower else KIND_NODE[kind]])
    return dag


def declare_narrower(dag, order=None):
    pairs = [(head, broader) for head, (_k, broader) in HEADS.items() if broader]
    for head, broader in (order or pairs):
        dag.put(head, [broader])


class Oracle:
    def __init__(self, nodes, edges):
        self.nodes = list(nodes)
        terms = [f"{h}({n})" for h in HEADS for n in self.nodes]
        universe = set(self.nodes) | set(terms) | {p for _c, p in edges} \
            | {c for c, _p in edges}
        below = {(a, a) for a in universe} | set(edges)
        below |= {(f"{h}({n})", f"{b}({n})") for h, (_k, b) in HEADS.items()
                  if b for n in self.nodes}
        while True:
            up = {}
            for a, b in below:
                up.setdefault(a, set()).add(b)
            new = {(a, c) for a, bs in up.items() for b in bs
                   for c in up.get(b, ()) if (a, c) not in below}
            for x in self.nodes:
                for y in self.nodes:
                    for h, (kind, _b) in HEADS.items():
                        if kind == "reversed":
                            pair = (f"{h}({y})", f"{h}({x})")
                            lifts = (x, y) in below
                        else:
                            via = h if kind == "transitive" else "in"
                            pair = (f"{h}({x})", f"{h}({y})")
                            lifts = (x, y) in below or (x, f"{via}({y})") in below
                        if lifts and pair not in below:
                            new.add(pair)
            if not new:
                break
            below |= new
        self.below = below
        self.universe = sorted(universe)

    def bad(self):
        return any(a != b and (b, a) in self.below for a, b in self.below) \
            or any((x, f"{h}({x})") in self.below for x in self.nodes
                   for h, (kind, _b) in HEADS.items() if kind == "transitive")

    def stored_parents(self, child, asserted):
        ps = {p for c, p in asserted if c == child}
        return {p for p in ps
                if not any(q != p and (q, p) in self.below for q in ps)} or {"*"}


def random_world(seed, size=7, attempts=16):
    rnd = random.Random(seed)
    nodes = [f"n{i}" for i in range(size)]
    heads = sorted(HEADS)
    tries = []
    for _ in range(attempts):
        child, parent = rnd.choice(nodes), rnd.choice(nodes)
        shape = rnd.random()
        if shape < 0.08:
            tries.append((f"{rnd.choice(heads)}({child})", parent))  # a rule: refused
        elif shape < 0.75:
            tries.append((child, f"{rnd.choice(heads)}({parent})"))
        else:
            tries.append((child, parent))
    return nodes, tries


def build(nodes, edges, dag=None, narrower=True):
    dag = declare(dag, narrower=narrower)
    for n in nodes:
        dag.put(n, [])
    for child, parent in edges:
        dag.put(child, [parent])
    return dag


def accepted(seed):
    nodes, tries = random_world(seed)
    asserted = []
    for child, parent in tries:
        if child != parent and "(" not in child and not Oracle(
                nodes, set(asserted) | {(child, parent)}).bad():
            asserted.append((child, parent))
    return nodes, asserted


class TestTheOrder(unittest.TestCase):
    def setUp(self):
        self.dag = declare()
        for name, supers in (("place", []), ("lhr", ["place"]),
                             ("gate-b12", ["place", "in(lhr)"]),
                             ("flight-ba1", ["topic(gate-b12)"]),
                             ("brochure", ["about(lhr)"]),
                             ("car", []), ("engine", ["inside(car)"]),
                             ("garage", []),
                             ("employee", []), ("alice", ["employee"]),
                             ("minutes", ["editor(employee)"])):
            self.dag.put(name, supers)

    def test_a_narrower_term_is_inside_the_broader_one(self):
        dag = self.dag
        self.assertTrue(dag.is_below("topic(gate-b12)", "about(gate-b12)"))
        self.assertTrue(dag.is_below("topic(gate-b12)", "about(lhr)"))
        self.assertFalse(dag.is_below("about(gate-b12)", "topic(gate-b12)"))
        self.assertTrue(dag.is_below("inside(car)", "in(car)"))
        self.assertFalse(dag.is_below("in(car)", "inside(car)"))
        self.assertTrue(dag.is_below("editor(employee)", "shared-with(alice)"))
        self.assertFalse(dag.is_below("shared-with(employee)", "editor(alice)"))

    def test_queries_find_the_narrower_terms(self):
        dag = self.dag
        get = lambda *terms: {n.name for n in dag.get(list(terms))}
        self.assertIn("flight-ba1", get("about(lhr)"))
        self.assertNotIn("brochure", get("topic(lhr)"))
        self.assertIn("engine", get("in(car)"))
        self.assertIn("minutes", get("shared-with(alice)"))
        self.assertIn("minutes", get("editor(alice)"))
        # A virtual broader term, never filed, finds them too.
        self.assertIn("flight-ba1", get("about(place)") | get("about(lhr)"))

    def test_the_broader_edge_is_redundant(self):
        dag = self.dag
        dag.put("leaflet", ["topic(gate-b12)", "about(lhr)"])
        self.assertEqual(parents(dag, "leaflet"), {"topic(gate-b12)"})

    def test_a_transitive_narrower_relation_chains_through_its_own_terms(self):
        dag = self.dag
        dag.put("piston", ["inside(engine)"])
        self.assertTrue(dag.is_below("piston", "inside(car)"))
        self.assertTrue(dag.is_below("piston", "in(car)"))
        dag.put("car", ["in(garage)"])
        self.assertTrue(dag.is_below("piston", "in(garage)"))
        self.assertFalse(dag.is_below("piston", "inside(garage)"))

    def test_meet_overlaps_and_candidates(self):
        dag = self.dag
        self.assertEqual(dag.meet("topic(gate-b12)", "about(lhr)"),
                         "topic(gate-b12)")
        self.assertEqual(dag.meet("about(lhr)", "topic(gate-b12)"),
                         "topic(gate-b12)")
        with self.assertRaises(ValueError):      # no single term names it
            dag.meet("topic(lhr)", "about(gate-b12)")
        self.assertTrue(dag.overlaps("topic(gate-b12)", "about(lhr)"))
        self.assertTrue(dag.overlaps("flight-ba1", "about(place)"))
        with self.assertRaises(ValueError):      # unrelated heads
            dag.overlaps("about(lhr)", "in(lhr)")
        # Complete for possibility (G6): a narrower term's items are there.
        candidates = {n.name for n in dag.get_overlapping("about(lhr)")}
        self.assertTrue({"flight-ba1", "brochure"} <= candidates)
        self.assertTrue({n.name for n in dag.get(["about(lhr)"])} <= candidates)

    def test_a_narrower_container_moves_the_broader_terms(self):
        # Found by a larger oracle run: n7 inside n5 puts in(n7) inside
        # in(n5), and an edge filed before that must be re-reduced.
        dag = declare()
        for name, supers in (("n5", []), ("n7", []), ("n1", ["in(n7)"]),
                             ("n6", ["in(n5)", "n1"]),
                             ("n7", ["inside(n5)"])):
            dag.put(name, supers)
        self.assertTrue(dag.is_below("in(n7)", "in(n5)"))
        self.assertEqual(parents(dag, "n6"), {"n1"})

    def test_strictness_holds_through_a_narrower_relation(self):
        dag = self.dag
        with self.assertRaises(ValueError):
            dag.put("car", ["in(engine)"])
        before = edge_set(dag)
        with self.assertRaises(ValueError):
            dag.put("car", ["inside(engine)"])
        self.assertEqual(edge_set(dag), before)


class TestDeclarations(unittest.TestCase):
    def test_declaring_late_stores_what_declaring_first_stores(self):
        for seed in range(25):
            nodes, asserted = accepted(seed)
            reference = edge_set(build(nodes, asserted))
            pairs = [(h, b) for h, (_k, b) in HEADS.items() if b]
            for order in (pairs, list(reversed(pairs))):
                late = build(nodes, asserted, narrower=False)
                declare_narrower(late, order)
                self.assertEqual(edge_set(late), reference, (seed, order))

    def test_a_declaration_that_puts_something_inside_itself_is_refused(self):
        dag = declare(narrower=False)
        for name, supers in (("x", []), ("y", []), ("x", ["inside(y)"]),
                             ("y", ["in(x)"])):
            dag.put(name, supers)
        before = edge_set(dag)
        with self.assertRaises(ValueError) as caught:
            dag.put("inside", ["in"])
        self.assertIn("strict", str(caught.exception))
        self.assertEqual(edge_set(dag), before)
        self.assertFalse(dag.is_below("inside(y)", "in(y)"))

    def test_value_roles_keep_their_meaning(self):
        dag = OntoDAG()
        prelude.apply(dag)
        dag.put("max-load", ["mass"])
        dag.put("truck", ["max-load(3000kg)"])
        self.assertFalse(dag.is_below("truck", "mass(3000kg)"))
        self.assertTrue(dag.is_below("truck", "max-load(..5000kg)"))


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
                expect_refusal = "(" in child or Oracle(nodes, candidate).bad()
                before = (set(dag.nodes), edge_set(dag))
                try:
                    dag.put(child, [parent])
                    refused = False
                except ValueError:
                    refused = True
                self.assertEqual(refused, expect_refusal, (seed, child, parent))
                if refused:
                    self.assertEqual((set(dag.nodes), edge_set(dag)), before,
                                     (seed, child, parent))
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
            for h in HEADS:
                for n in nodes:
                    term = f"{h}({n})"
                    expected = {c for c in nodes if (c, term) in oracle.below}
                    got = {m.name for m in dag.get([term])} & set(nodes)
                    self.assertEqual(got, expected, (seed, term))
        self.assertGreater(refusals, 10)

    def test_order_does_not_matter(self):
        for seed in range(25):
            nodes, asserted = accepted(seed)
            reference = edge_set(build(nodes, asserted))
            rnd = random.Random(seed)
            for _ in range(3):
                shuffled = asserted[:]
                rnd.shuffle(shuffled)
                self.assertEqual(edge_set(build(nodes, shuffled)), reference, seed)

    def test_merge_commutes_and_equals_the_union(self):
        for seed in range(25):
            nodes, asserted = accepted(seed)
            rnd = random.Random(seed)
            left = [e for e in asserted if rnd.random() < 0.5]
            right = [e for e in asserted if e not in left]
            a, b = build(nodes, left), build(nodes, right)
            ab, ba = a.deepcopy(), b.deepcopy()
            ab.merge(b)
            ba.merge(a)
            self.assertEqual(edge_set(ab), edge_set(ba), seed)
            self.assertEqual(edge_set(ab), edge_set(build(nodes, asserted)), seed)


class TestAgreesWithTheScan(unittest.TestCase):
    """Name-directed hops (DIMENSIONS.md §19) against the scan they
    replace, on worlds big enough for chains of narrower terms whose
    broader terms were never filed: `x ⊑ inside(z)`, `z ⊑ inside(y)`
    puts x in y through `in(z)`, which may not exist."""

    def test_random_worlds(self):
        for seed in range(30):
            nodes, tries = random_world(seed, size=9, attempts=26)
            dags = []
            for resident in (True, False):
                dag = OntoDAG()
                dag._resident = resident
                declare(dag)
                for n in nodes:
                    dag.put(n, [])
                for child, parent in tries:
                    if child != parent:
                        try:
                            dag.put(child, [parent])
                        except ValueError:
                            pass
                dags.append(dag)
            by_name, by_scan = dags
            self.assertEqual(edge_set(by_name), edge_set(by_scan), seed)
            for h in HEADS:
                for n in nodes:
                    query = [f"{h}({n})"]
                    self.assertEqual({m.name for m in by_name.get(query)},
                                     {m.name for m in by_scan.get(query)},
                                     (seed, query))


class TestStoresAndReaders(unittest.TestCase):
    def store_of(self, nodes, asserted):
        store = RecordStore(MemoryBytesStore())
        build(nodes, asserted, dag=EagerOntoDAG(store)).commit()
        return store

    def test_roots_agree_across_orders(self):
        nodes, asserted = accepted(3)
        roots = set()
        rnd = random.Random(3)
        for _ in range(3):
            shuffled = asserted[:]
            rnd.shuffle(shuffled)
            roots.add(self.store_of(nodes, shuffled).root)
        self.assertEqual(len(roots), 1)

    def test_a_lazy_reader_answers_like_the_writer(self):
        for seed in range(6):
            nodes, asserted = accepted(seed)
            store = self.store_of(nodes, asserted)
            oracle = Oracle(nodes, asserted)
            lazy = LazyOntoDAG(RecordStore.at(store.root, store.blobs))
            for h in HEADS:
                for n in nodes:
                    term = f"{h}({n})"
                    expected = {c for c in nodes if (c, term) in oracle.below}
                    got = {m.name for m in lazy.get([term])} & set(nodes)
                    self.assertEqual(got, expected, (seed, term))

    def test_the_sparse_writer_matches_the_eager_one(self):
        for seed in range(6):
            nodes, asserted = accepted(seed)
            half = len(asserted) // 2
            store = self.store_of(nodes, asserted[:half])
            sparse = SparseOntoDAG(RecordStore(store.blobs, root=store.root))
            for child, parent in asserted[half:]:
                sparse.put(child, [parent])
            sparse.commit()
            self.assertEqual(sparse.store.root,
                             self.store_of(nodes, asserted).root, seed)

    def test_certificates_prove_both_answers(self):
        from ontodag.certificates import prove_below, verify_below
        nodes, asserted = accepted(5)
        store = self.store_of(nodes, asserted)
        oracle = Oracle(nodes, asserted)
        rnd = random.Random(5)
        for _ in range(40):
            a = rnd.choice(nodes)
            b = f"{rnd.choice(sorted(HEADS))}({rnd.choice(nodes)})"
            cert = prove_below(RecordStore.at(store.root, store.blobs), a, b)
            self.assertEqual(verify_below(cert, store.root),
                             (a, b) in oracle.below, (a, b))


class TestCertificatesAcrossProcesses(unittest.TestCase):
    """A verifier in another process iterates sets in another order, so its
    walk may take another path; the certificate must cover every path,
    including the broader head's terms a narrower term is compared with."""

    def test_verifies_under_other_hash_seeds(self):
        import json, os, subprocess, sys, tempfile
        from ontodag.certificates import prove_below
        blobs = MemoryBytesStore()
        dag = declare(EagerOntoDAG(RecordStore(blobs)))
        for name, supers in (("place", []), ("lhr", ["place"]),
                             ("gate-b12", ["place", "in(lhr)"]),
                             ("flight-ba1", ["topic(gate-b12)"]),
                             ("car", []), ("garage", []),
                             ("car", ["inside(garage)"]),
                             ("engine", ["inside(car)"]),
                             ("employee", []), ("alice", ["employee"]),
                             ("minutes", ["editor(employee)"])):
            dag.put(name, supers)
        root = dag.commit()
        cases = [("flight-ba1", "about(lhr)", True),
                 ("flight-ba1", "subtopic(lhr)", False),
                 ("topic(gate-b12)", "about(place)", True),
                 ("engine", "in(garage)", True),
                 ("engine", "inside(garage)", True),
                 ("minutes", "shared-with(alice)", True),
                 ("minutes", "editor(alice)", True),
                 ("shared-with(employee)", "editor(alice)", False)]
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
                "    assert verify_below(job['cert'], data['root']) == "
                "job['expected'], (job['cert']['sub'], job['cert']['sup'])\n")
        src = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "src")
        for seed in ("0", "1", "42"):
            env = dict(os.environ, PYTHONPATH=src, PYTHONHASHSEED=seed)
            proc = subprocess.run([sys.executable, "-c", code], env=env,
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, f"seed={seed}:\n{proc.stderr}")


if __name__ == "__main__":
    unittest.main()
