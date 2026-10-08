"""The graph kind (registry 4.2, issue #19): a head under
`graph-dimension` takes as its parameter a conjunction of constraints on
the graph itself — category names and terms of other dimensions — and the
graph orders such terms: `H(X ...) ⊑ H(A ...)` iff every A is above some X.

loopmarket's consumer case: a courier's `transport(mass(..8kg) small-item)`
is what the courier accepts, and the wanter's `transport(bicycle mass(5kg))`
fits within it. Which side must be inside is the consumer's rule; ontodag
only orders."""

import random
import unittest

from ontodag import prelude
from ontodag.dag import OntoDAG
from ontodag.eager import EagerOntoDAG
from ontodag.surface import elaborate, render
from recordstore import MemoryBytesStore, RecordStore


def city():
    dag = OntoDAG()
    prelude.apply(dag)
    dag.put("graph-dimension", ["dimension"])    # not in the prelude: a seed line
    dag.put("transport", ["graph-dimension"])
    dag.put("goods", [])
    dag.put("small-item", ["goods"])
    dag.put("bicycle", ["small-item"])
    dag.put("racing-bicycle", ["bicycle"])
    dag.put("piano", ["goods"])
    return dag


class TestGrammar(unittest.TestCase):
    def test_constraints_are_sorted_deduplicated_and_each_canonical(self):
        dag = city()
        self.assertEqual(dag._canonical_name("transport(mass(..8000g) small-item)"),
                         "transport(mass(..8kg) small-item)")
        self.assertEqual(dag._canonical_name("transport(bicycle bicycle)"),
                         "transport(bicycle)")
        self.assertEqual(elaborate("transport(small-item mass(..8kg))", dag),
                         "transport(mass(..8kg) small-item)")
        self.assertEqual(render("transport(mass(..8kg) small-item)", dag),
                         "transport(mass(..8kg) small-item)")

    def test_unknown_constraints_fail_closed_and_redundant_ones_are_dropped(self):
        dag = city()
        with self.assertRaisesRegex(ValueError, "unicorn"):
            dag.is_below("transport(unicorn)", "transport(goods)")
        # A redundant constraint says nothing the finer one does not, so the
        # spelling drops it (until 2026-10-08 it was refused, which made a
        # write's acceptance depend on whether the graph already related
        # the two): one class, one name.
        self.assertEqual(dag._canonical_name("transport(bicycle small-item)"),
                         "transport(bicycle)")
        self.assertEqual(dag._canonical_name("transport(mass(5kg) mass(..8kg))"),
                         "transport(mass(5kg))")
        dag.put("x", ["transport(bicycle small-item)"])
        self.assertEqual({p.name for p in dag.nodes["x"].parents},
                         {"transport(bicycle)"})
        self.assertIn("transport(small-item)", dag.nodes)   # named, so materialized
        # a kind node is not a constraint; an empty argument is not a term
        with self.assertRaises(ValueError):
            dag.is_below("transport(linear-dimension)", "transport(goods)")
        self.assertFalse(dag.is_below("transport()", "transport(goods)"))

    def test_the_flat_kinds_still_read_a_nested_parameter_as_opaque(self):
        dag = city()
        dag.put("mass(x(y))", [])                  # an opaque atom, as before
        self.assertIsNone(dag._parse_parametric("mass(x(y))"))
        self.assertTrue(dag.is_below("mass(x(y))", "mass(x(y))"))


class TestOrder(unittest.TestCase):
    def test_every_outer_constraint_above_some_inner_one(self):
        dag = city()
        below = dag.is_below
        self.assertTrue(below("transport(bicycle)", "transport(goods)"))
        self.assertTrue(below("transport(racing-bicycle)", "transport(bicycle)"))
        self.assertFalse(below("transport(goods)", "transport(bicycle)"))
        self.assertFalse(below("transport(piano)", "transport(bicycle)"))
        # a nested term is ordered by its own dimension
        self.assertTrue(below("transport(bicycle mass(5kg))",
                              "transport(mass(..8kg) small-item)"))
        self.assertFalse(below("transport(bicycle mass(12kg))",
                               "transport(mass(..8kg) small-item)"))
        # a constraint the inner term does not answer is not met
        self.assertFalse(below("transport(bicycle)", "transport(mass(..8kg) small-item)"))
        # fewer constraints is the wider term
        self.assertTrue(below("transport(mass(..8kg) small-item)", "transport(small-item)"))
        self.assertTrue(below("transport(bicycle)", "transport(bicycle)"))
        # roles keep their own star, as with every kind
        dag.put("bicycle-courier", ["transport"])
        self.assertTrue(below("bicycle-courier(racing-bicycle)", "bicycle-courier(bicycle)"))
        self.assertFalse(below("bicycle-courier(bicycle)", "transport(goods)"))

    def test_a_conjunction_is_the_same_as_its_constraints_as_separate_terms(self):
        """`H(A B)` ≡ `H(A) H(B)`: an item under the conjunction is found
        whichever way the question is spelled, the two separate query terms
        are two cones whose intersection is the same answer, and an item put
        under the two separate terms is filed under their meet (canonical
        placement, DIMENSIONS.md §9)."""
        dag = city()
        dag.put("courier-1", ["transport(mass(..8kg) small-item)"])
        dag.put("courier-3", ["transport(piano)"])
        names = lambda items: {i.name for i in items}
        for query in (["transport(mass(..8kg) small-item)"],
                      ["transport(small-item)", "transport(mass(..8kg))"],
                      ["transport(goods mass(..10kg))"]):
            self.assertEqual(names(dag.get(query, items_only=True)), {"courier-1"}, query)
        self.assertEqual(names(dag.get(["transport(goods)"], items_only=True)),
                         {"courier-1", "courier-3"})
        self.assertEqual(names(dag.get(["transport(bicycle)"], items_only=True)), set())
        self.assertEqual(dag.meet("transport(small-item)", "transport(mass(..8kg))"),
                         "transport(mass(..8kg) small-item)")
        self.assertEqual(dag.meet("transport(bicycle)", "transport(small-item)"),
                         "transport(bicycle)")
        self.assertTrue(dag.overlaps("transport(bicycle)", "transport(piano)"))
        # `H(A B)` ≡ `H(A) H(B)` as an ITEM too: either spelling files the
        # item under the parts, and no compound term is ever a node (§15)
        dag.put("courier-2", ["transport(small-item)", "transport(mass(..8kg))"])
        parts = {"transport(mass(..8kg))", "transport(small-item)"}
        for courier in ("courier-1", "courier-2"):
            self.assertEqual({p.name for p in dag.nodes[courier].parents}, parts)
        self.assertNotIn("transport(mass(..8kg) small-item)", dag.nodes)
        self.assertEqual(names(dag.get(["transport(mass(..8kg) small-item)"], items_only=True)),
                         {"courier-1", "courier-2"})

    def test_the_order_follows_the_graph(self):
        """A constraint names a node, so the term moves with it (the #15
        reading): when `piano` becomes a small item, the piano courier's
        term slides under the small-item one."""
        dag = city()
        dag.put("c", ["transport(piano)"])
        self.assertFalse(dag.is_below("c", "transport(small-item)"))
        dag.put("piano", ["small-item"])
        self.assertTrue(dag.is_below("c", "transport(small-item)"))
        self.assertEqual({i.name for i in dag.get(["transport(small-item)"], items_only=True)},
                         {"c"})


class TestATermGoesOnlyUnderItsHead(unittest.TestCase):
    """A graph-kind term filed under anything but its head states a rule
    (`transport(vehicle)` under `rush`: everything transported as a
    vehicle is a rush job), which CONTRACT.md §5.1 keeps out. Random
    worlds with such edges went exponential (38 of 60 hit a put slower
    than three seconds), and with them an edge could close a loop through
    a computed link it creates (DIMENSIONS.md §18). Refused since
    2026-10-06; before, it was accepted."""

    def test_the_rule_is_refused_and_leaves_nothing(self):
        dag = city()
        dag.put("vehicle", ["goods"])
        dag.put("rush", [])
        before = {(p.name, c.name) for p in dag.nodes.values() for c in p.neighbors}
        with self.assertRaisesRegex(ValueError, "would state a rule"):
            dag.put("transport(vehicle)", ["rush"])
        after = {(p.name, c.name) for p in dag.nodes.values() for c in p.neighbors}
        self.assertEqual(before, after)
        self.assertNotIn("transport(vehicle)", dag.nodes)

    def test_the_finer_part_stays_when_the_constraints_meet(self):
        # Until 2026-10-08 the two terms folded into a stored
        # transport(bicycle fragile), which became a second name for
        # transport(bicycle) once bicycles were fragile.
        dag = city()
        dag.put("fragile", ["goods"])
        dag.put("courier", ["transport(bicycle)", "transport(fragile)"])
        self.assertEqual({p.name for p in dag.nodes["courier"].parents},
                         {"transport(bicycle)", "transport(fragile)"})
        dag.put("bicycle", ["fragile"])          # now fragile is redundant
        self.assertEqual({p.name for p in dag.nodes["courier"].parents},
                         {"transport(bicycle)"})
        self.assertTrue(dag.is_below("courier", "transport(goods)"))
        self.assertTrue(dag.is_below("courier", "transport(bicycle fragile)"))
        self.assertIn("courier", {n.name for n in dag.get(["transport(goods)"])})
        self.assertFalse(dag.is_below("courier", "goods"))


class TestPersistence(unittest.TestCase):
    def test_terms_with_spaces_round_trip_through_a_store_and_a_merge(self):
        store = RecordStore(MemoryBytesStore())
        dag = EagerOntoDAG(store)
        prelude.apply(dag)
        dag.put("graph-dimension", ["dimension"])
        dag.put("transport", ["graph-dimension"])
        dag.put("goods", []); dag.put("small-item", ["goods"]); dag.put("bicycle", ["small-item"])
        dag.put("courier", ["transport(mass(..8kg) small-item)"])
        root = dag.commit()
        again = EagerOntoDAG(RecordStore.at(root, store.blobs))
        self.assertIn("transport(mass(..8kg))", again.nodes)
        self.assertIn("transport(small-item)", again.nodes)
        self.assertTrue(again.is_below("transport(bicycle mass(5kg))",
                                       "transport(mass(..8kg) small-item)"))
        self.assertTrue(again.is_below("courier", "transport(goods)"))
        # a fresh DAG merging it lands the same name, edges before nodes or after
        fresh = EagerOntoDAG(RecordStore(MemoryBytesStore()))
        fresh.merge(again)
        self.assertEqual(fresh.commit(), root)
        self.assertTrue(fresh.is_below("courier", "transport(goods)"))



def removals():
    """A removal firm's catalogue: what a job moves, and two job tags."""
    dag = EagerOntoDAG(RecordStore(MemoryBytesStore()))
    prelude.apply(dag)
    dag.put("graph-dimension", ["dimension"])
    dag.put("transport", ["graph-dimension"])
    for name, supers in (("goods", []), ("heavy-item", ["goods"]),
                         ("piano", ["goods"])):
        dag.put(name, supers)
    return dag


def parents(dag, name):
    return {p.name for p in dag.nodes[name].parents}


def graph_terms(dag, head="transport"):
    return [n for n in dag.nodes if n.startswith(head + "(")]


class TestStoredFormIsOrderFree(unittest.TestCase):
    """A graph-kind term with several constraints is stored as its parts
    (DIMENSIONS.md §15, 2026-10-08). Until then a job tagged "piano" and
    "heavy item" was folded into a stored `transport(heavy-item piano)`,
    so a store that learned "pianos are heavy" after the job was posted
    kept a second name for `transport(piano)`'s class and a different
    root from a store that knew it first; and nothing re-reduced the
    graph kind's terms when one of their constraints moved."""

    def test_the_piano_job_converges(self):
        early = removals()
        early.put("piano", ["heavy-item"])
        early.put("job-17", ["transport(piano)", "transport(heavy-item)"])
        late = removals()
        late.put("job-17", ["transport(piano)", "transport(heavy-item)"])
        late.put("piano", ["heavy-item"])
        self.assertEqual(parents(early, "job-17"), {"transport(piano)"})
        self.assertEqual(parents(late, "job-17"), {"transport(piano)"})
        root = early.commit()
        self.assertEqual(late.commit(), root)
        merged = EagerOntoDAG(RecordStore(MemoryBytesStore()))
        merged.merge(late)
        merged.merge(early)
        self.assertEqual(merged.commit(), root)

    def test_a_job_type_keeps_no_redundant_tag(self):
        def typed():
            dag = removals()
            dag.put("piano-move", ["transport(piano)"])
            return dag
        early, late = typed(), typed()
        early.put("piano", ["heavy-item"])
        early.put("job-19", ["piano-move", "transport(heavy-item)"])
        late.put("job-19", ["piano-move", "transport(heavy-item)"])
        late.put("piano", ["heavy-item"])
        self.assertEqual(parents(late, "job-19"), {"piano-move"})
        self.assertEqual(late.commit(), early.commit())

    def test_the_two_tag_spelling_works_in_every_order(self):
        for fact_first in (True, False):
            dag = removals()
            if fact_first:
                dag.put("piano", ["heavy-item"])
            dag.put("job-18", ["transport(heavy-item piano)"])
            if not fact_first:
                dag.put("piano", ["heavy-item"])
            self.assertEqual(parents(dag, "job-18"), {"transport(piano)"})
            self.assertEqual(sorted(graph_terms(dag)),
                             ["transport(heavy-item)", "transport(piano)"])
            self.assertTrue(dag.is_below("job-18", "transport(heavy-item piano)"))
            self.assertEqual({i.name for i in dag.get(
                ["transport(heavy-item piano)"], items_only=True)}, {"job-18"})

    def test_a_term_put_as_an_item_is_its_parts(self):
        dag = removals()
        dag.put("transport(heavy-item piano)", [])
        self.assertEqual(sorted(graph_terms(dag)),
                         ["transport(heavy-item)", "transport(piano)"])

    def test_a_nested_compound_splits_too(self):
        dag = removals()
        dag.put("option", ["graph-dimension"])
        dag.put("job", ["option(transport(heavy-item piano))"])
        self.assertEqual(parents(dag, "job"), {"option(transport(heavy-item))",
                                               "option(transport(piano))"})
        dag.put("piano", ["heavy-item"])
        self.assertEqual(parents(dag, "job"), {"option(transport(piano))"})
        self.assertTrue(dag.is_below("job", "option(transport(heavy-item piano))"))

    def test_reclassify_takes_and_retracts_compounds(self):
        dag = removals()
        dag.put("crate", ["goods"])
        dag.put("job", ["transport(crate)"])
        dag.reclassify(["job"], to=["transport(heavy-item piano)"],
                       from_=["transport(crate)"])
        self.assertEqual(parents(dag, "job"),
                         {"transport(heavy-item)", "transport(piano)"})
        dag.reclassify(["job"], to=["transport(crate)"],
                       from_=["transport(heavy-item piano)"])
        self.assertEqual(parents(dag, "job"), {"transport(crate)"})

    def test_a_store_written_before_reads_the_same_and_migrates(self):
        # A store from before 2026-10-08 holds the folded compound as a
        # node. It loads verbatim and answers the same questions; the
        # migration replay files it as its parts.
        from ontodag import migrate, native
        old = native.loads(native.dumps(removals()) +
                           "'transport(heavy-item piano)' transport\n"
                           "job-17 'transport(heavy-item piano)'\n")
        self.assertIn("transport(heavy-item piano)", old.nodes)
        for query in ("transport(piano)", "transport(heavy-item)",
                      "transport(heavy-item piano)"):
            self.assertTrue(old.is_below("job-17", query), query)
            self.assertEqual({i.name for i in old.get([query], items_only=True)},
                             {"job-17"}, query)
        entries = {name: sorted(p.name for p in node.parents
                                if p.name != old.root.name)
                   for name, node in old.nodes.items() if name != old.root.name}
        fresh = migrate._replay(entries)
        self.assertNotIn("transport(heavy-item piano)", fresh.nodes)
        self.assertEqual(parents(fresh, "job-17"),
                         {"transport(heavy-item)", "transport(piano)"})

    def test_readers_writers_and_certificates(self):
        from ontodag.certificates import prove_below, verify_below
        from ontodag.lazy import LazyOntoDAG, SparseOntoDAG
        blobs = MemoryBytesStore()
        eager = EagerOntoDAG(RecordStore(blobs))
        for name, supers in (("goods", []), ("heavy-item", ["goods"]),
                             ("piano", ["goods"])):
            eager.put(name, supers)
        prelude.apply(eager)
        eager.put("graph-dimension", ["dimension"])
        eager.put("transport", ["graph-dimension"])
        base = eager.commit()
        eager.put("job-17", ["transport(heavy-item piano)"])
        root = eager.commit()
        sparse = SparseOntoDAG(RecordStore(blobs, root=base))
        sparse.put("job-17", ["transport(heavy-item piano)"])
        self.assertEqual(sparse.commit(), root)
        reader = LazyOntoDAG(RecordStore.at(root, blobs))
        self.assertEqual({i.name for i in reader.get(
            ["transport(heavy-item piano)"], items_only=True)}, {"job-17"})
        for sup, expected in (("transport(heavy-item piano)", True),
                              ("transport(goods)", True),
                              ("transport(heavy-item crate)", False)):
            if sup.endswith("crate)"):
                eager.put("crate", ["goods"])
                root = eager.commit()
            self.assertEqual(eager.is_below("job-17", sup), expected, sup)
            cert = prove_below(eager, "job-17", sup)
            self.assertEqual(verify_below(cert, root), expected, sup)


class TestAgainstTheMeaning(unittest.TestCase):
    """Random worlds against what a graph-kind term means: an item under
    `transport(...)` terms moves ONE thing meeting every constraint named
    on it or on its types, so it is below `transport(A...)` exactly when
    each A is above one of those constraints. Every order of the same
    writes, and every merge of two orders, must give one root, and no two
    present terms may name one class (I1)."""

    def world(self, seed):
        rng = random.Random(seed)
        cats = [f"c{i}" for i in range(7)]
        edges = [(cats[i], cats[j]) for i in range(7) for j in range(i + 1, 7)
                 if rng.random() < 0.25]

        def term():
            picked = rng.sample(cats, rng.choice((1, 1, 2, 3)))
            return f"transport({' '.join(picked)})"

        types = {f"type{k}": [term()] for k in range(2)}
        jobs = {f"job{k}": rng.sample([term(), term(), "type0", "type1"],
                                      rng.choice((1, 2)))
                for k in range(6)}
        queries = [term() for _ in range(10)]
        return cats, edges, types, jobs, queries

    def build(self, world, order_seed):
        cats, edges, types, jobs, _ = world
        dag = removals()
        for c in cats:
            dag.put(c, [])
        for name, supers in types.items():
            dag.put(name, supers)
        writes = [("edge", e) for e in edges] + [("job", j) for j in jobs.items()]
        random.Random(order_seed).shuffle(writes)
        for kind, (a, b) in writes:
            dag.put(a, [b] if kind == "edge" else b)
        return dag

    def meaning(self, world):
        cats, edges, types, jobs, queries = world
        up = {c: {c} for c in cats}
        changed = True
        while changed:
            changed = False
            for a, b in edges:
                for c in cats:
                    if a in up[c] and not up[b] <= up[c]:
                        up[c] |= up[b]
                        changed = True
        constraints = lambda t: t[len("transport("):-1].split()
        filler = {}
        for job, supers in jobs.items():
            terms = [t for s in supers for t in (types.get(s) or [s])]
            filler[job] = {c for t in terms for c in constraints(t)}

        def below(job, query):
            return all(any(a in up[f] for f in filler[job])
                       for a in constraints(query))
        return below

    def test_every_order_gives_one_root_and_the_meaning(self):
        for seed in range(25):
            world = self.world(seed)
            below = self.meaning(world)
            roots = set()
            dags = [self.build(world, order) for order in range(4)]
            for dag in dags:
                roots.add(dag.commit())
                for job in world[3]:
                    for query in world[4]:
                        self.assertEqual(dag.is_below(job, query),
                                         below(job, query), (seed, job, query))
                for query in world[4]:
                    expected = {j for j in world[3] if below(j, query)}
                    got = {i.name for i in dag.get([query])} & set(world[3])
                    self.assertEqual(got, expected, (seed, query))
                terms = graph_terms(dag)
                self.assertTrue(all(" " not in t for t in terms), seed)
                for a in terms:
                    for b in terms:
                        if a != b:
                            self.assertFalse(dag.is_below(a, b) and dag.is_below(b, a),
                                             (seed, a, b))
            merged = EagerOntoDAG(RecordStore(MemoryBytesStore()))
            merged.merge(dags[1])
            merged.merge(dags[2])
            roots.add(merged.commit())
            self.assertEqual(len(roots), 1, seed)


if __name__ == "__main__":
    unittest.main()
