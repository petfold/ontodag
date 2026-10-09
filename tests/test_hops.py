"""Computed hops found without scanning stars (ROLES.md §9 step 4a).

A resident graph finds the terms above or below a term from the term's own
parameter (`OntoDAG._hops`): interval values through a sorted index, prefix
values by their prefixes, and the kinds the graph orders by walking near
their constraints. The scan of the head's star that this replaced is still
there, for lazy readers and as the fallback, and it is the reference:

* `TestAgreesWithTheScan` runs the same random operations on a graph that
  finds hops by name and on one forced to scan (`_resident = False`), over
  every kind together (conjunctions, value constraints and virtual query
  terms included), and requires the same stored form and the same answers.
* `TestFilingDoesNotScan` pins the point of the work: filing an item never
  walks a star, however many terms its head has.
* `TestTermsInsideAreAllOfThem` pins what a walk relies on to leave a term
  unasked (`OntoDAG._walk_children`), and `TestAQueryCostsItsAnswer` what
  that, and the planner's sizing of such terms, buys (REVIEW §8 item 13).
"""

import random
import unittest

from ontodag import prelude
from ontodag.dag import OntoDAG


def edge_set(dag):
    return {(parent.name, child.name)
            for parent in dag.nodes.values() for child in parent.neighbors}


def declare(resident):
    dag = OntoDAG()
    dag._resident = resident
    prelude.apply(dag)
    for kind, head in (("transitive-dimension", "in"),
                       ("enclosing-dimension", "about"),
                       ("reversed-dimension", "shared-with"),
                       ("graph-dimension", "transport")):
        dag.put(kind, ["dimension"])
        dag.put(head, [kind])
    return dag


def random_operations(seed, size=9, steps=40):
    rnd = random.Random(seed)
    names = [f"n{i}" for i in range(size)]

    def value():
        shape = rnd.random()
        if shape < 0.4:
            return f"mass({rnd.randint(1, 9)}kg)"
        if shape < 0.7:
            lo = rnd.randint(1, 6)
            return f"mass({lo}kg..{lo + rnd.randint(1, 4)}kg)"
        return f"geo({rnd.choice(['u2', 'u2e', 'u2e4', 'u2e5', 'u3'])})"

    def term():
        shape = rnd.random()
        a, b = rnd.sample(names, 2)
        if shape < 0.2:
            return f"in({a})"
        if shape < 0.35:
            return f"about({a})"
        if shape < 0.5:
            return f"shared-with({a})"
        if shape < 0.65:
            return f"transport({a})"
        if shape < 0.8:
            return f"transport({a} {b})"
        return f"transport({a} mass(..{rnd.randint(2, 9)}kg))"

    ops = []
    for _ in range(steps):
        child = rnd.choice(names + [f"item{rnd.randint(0, 9)}"])
        shape = rnd.random()
        parent = (rnd.choice(names) if shape < 0.3 else value() if shape < 0.5
                  else term())
        ops.append((child, parent))
    queries = [[term()] for _ in range(8)] + [[value()] for _ in range(4)] + \
        [[term(), term()] for _ in range(4)]
    return names, ops, queries


def play(resident, names, ops):
    dag = declare(resident)
    for name in names:
        dag.put(name, [])
    for child, parent in ops:
        try:
            dag.put(child, [parent])
        except ValueError:
            pass
    return dag


class TestAgreesWithTheScan(unittest.TestCase):
    def test_random_worlds(self):
        for seed in range(30):
            names, ops, queries = random_operations(seed)
            by_name, by_scan = play(True, names, ops), play(False, names, ops)
            self.assertEqual(edge_set(by_name), edge_set(by_scan), seed)
            present = sorted(n for n in by_scan.nodes if n != "*")
            for query in queries:
                try:
                    expected = {n.name for n in by_scan.get(query)}
                except ValueError:
                    continue
                self.assertEqual({n.name for n in by_name.get(query)},
                                 expected, (seed, query))
            rnd = random.Random(seed)
            for _ in range(60):
                a, b = rnd.choice(present), rnd.choice(present)
                self.assertEqual(by_name.is_below(a, b), by_scan.is_below(a, b),
                                 (seed, a, b))
            for query in queries:
                for name in rnd.sample(present, 5):
                    try:
                        expected = by_scan.is_below(name, query[0])
                    except ValueError:
                        continue
                    self.assertEqual(by_name.is_below(name, query[0]), expected,
                                     (seed, name, query[0]))



def graph_operations(seed, size=7, steps=40):
    """The graph kind's shapes the first worlds never made: a value as the
    only constraint (`transport(mass(..5kg))`, a value that is no node),
    and a graph-kind term nested in another (`option(transport(n2))`)."""
    rnd = random.Random(seed)
    names = [f"n{i}" for i in range(size)]

    def mass():
        return f"mass(..{rnd.randint(2, 9)}kg)"

    def term():
        shape = rnd.random()
        a, b = rnd.sample(names, 2)
        if shape < 0.25:
            return f"transport({a})"
        if shape < 0.45:
            return f"transport({mass()})"
        if shape < 0.6:
            return f"transport({a} {mass()})"
        if shape < 0.75:
            return f"transport({a} {b})"
        if shape < 0.9:
            return f"option(transport({a}))"
        return f"option({a} transport({b} {mass()}))"

    ops = []
    for _ in range(steps):
        shape = rnd.random()
        if shape < 0.3:
            a, b = sorted(rnd.sample(range(size), 2))
            ops.append((names[a], names[b]))      # acyclic: lower under higher
        elif shape < 0.4:
            ops.append((rnd.choice(names), f"mass({rnd.randint(1, 9)}kg)"))
        else:
            ops.append((f"job{rnd.randint(0, 9)}", term()))
    queries = [[term()] for _ in range(10)] + [[term(), term()] for _ in range(4)]
    return names, ops, queries


def play_graph(resident, names, ops):
    dag = OntoDAG()
    dag._resident = resident
    prelude.apply(dag)
    dag.put("graph-dimension", ["dimension"])
    dag.put("transport", ["graph-dimension"])
    dag.put("option", ["graph-dimension"])
    for name in names:
        dag.put(name, [])
    for child, parent in ops:
        try:
            dag.put(child, [parent])
        except ValueError:
            pass
    return dag


class TestGraphKindAgreesWithTheScan(unittest.TestCase):
    """Until 2026-10-08 a resident graph's hops missed two shapes, so
    `get(["transport(mass(..8kg))"])` answered nothing for what was
    filed under `transport(mass(..5kg))`, while `is_below` (and a lazy
    reader, which scans) said yes; and the terms above `transport(piano)`
    left out `transport(option(b))` when piano ⊑ option(a)."""

    def test_a_value_named_only_inside_a_term(self):
        for resident in (True, False):
            dag = play_graph(resident, ["goods"], [
                ("x", "transport(mass(..5kg))"),
                ("y", "transport(goods mass(..5kg))")])
            self.assertEqual({n.name for n in dag.get(
                ["transport(mass(..8kg))"], items_only=True)}, {"x", "y"}, resident)

    def test_a_term_nested_in_a_term(self):
        for resident in (True, False):
            dag = play_graph(resident, ["b"], [
                ("a", "b"), ("piano", "option(a)"),
                ("j1", "transport(piano)"), ("j2", "transport(option(b))")])
            self.assertEqual([p.name for p in dag._computed_parents(
                dag.nodes["transport(piano)"])], ["transport(option(b))"], resident)

    def test_random_worlds(self):
        for seed in range(30):
            names, ops, queries = graph_operations(seed)
            by_name, by_scan = play_graph(True, names, ops), play_graph(False, names, ops)
            self.assertEqual(edge_set(by_name), edge_set(by_scan), seed)
            for query in queries:
                try:
                    expected = {n.name for n in by_scan.get(query)}
                except ValueError:
                    continue
                self.assertEqual({n.name for n in by_name.get(query)},
                                 expected, (seed, query))
            for node in list(by_scan.nodes.values()):
                if node.name.startswith(("transport(", "option(")):
                    for direction in ("_computed_parents", "_computed_children"):
                        closure = lambda dag, step: {
                            m.name for m in dag.get_ancestors(dag.nodes[node.name])
                        } if step == "_computed_parents" else {
                            m.name for m in dag.get_descendants(dag.nodes[node.name])}
                        self.assertEqual(closure(by_name, direction),
                                         closure(by_scan, direction),
                                         (seed, node.name, direction))


class TestACompoundQueryWalksItsNarrowPart(unittest.TestCase):
    """A compound graph-kind query is the conjunction of its parts (§15).
    One part is often broad: every offer accepting things up to some mass.
    The planner walks the narrow part and probes the broad one per
    candidate, rather than finding every term inside the broad one (which
    nest, each range inside the next) to intersect with a small answer."""

    def test_the_broad_part_is_probed(self):
        rnd = random.Random(1)
        dag = play_graph(True, [f"c{i}" for i in range(30)], [])
        for k in range(600):
            a = f"c{rnd.randrange(30)}"
            dag.put(f"offer{k}", [f"transport({a} mass(..{rnd.randint(1, 60)}kg))"])
        walked = []
        original = OntoDAG._walk_cone

        def walk(self, cone):
            walked.append(cone.name)
            return original(self, cone)
        OntoDAG._walk_cone = walk
        try:
            got = dag.get(["transport(c0 mass(..30kg))"], items_only=True)
        finally:
            OntoDAG._walk_cone = original
        self.assertEqual(walked, ["transport(c0)"])
        expected = {f"offer{k}" for k in range(600)
                    if dag.is_below(f"offer{k}", "transport(c0 mass(..30kg))")}
        self.assertEqual({i.name for i in got}, expected)
        self.assertTrue(expected)

def role_operations(seed, places=7, steps=40):
    """Places in cells, regions above cells, and offers under `from(...)`
    in both spellings: a place (`from(p3)`) and a literal cell
    (`from(u2e4)`). `from` is a role of `geo` (DIMENSIONS.md §14)."""
    rnd = random.Random(seed)
    cells = ["u2", "u2e", "u2e4", "u2e4x", "u2e5", "u2e5y", "u3", "u3b"]
    names = [f"p{i}" for i in range(places)] + ["r0", "r1"]
    ops = []
    for _ in range(steps):
        shape = rnd.random()
        if shape < 0.3:
            ops.append((rnd.choice(names[:places]), f"geo({rnd.choice(cells)})"))
        elif shape < 0.4:
            ops.append((f"geo({rnd.choice(cells)})", rnd.choice(["r0", "r1"])))
        elif shape < 0.5:
            ops.append((rnd.choice(names[:places]), rnd.choice(names)))
        elif shape < 0.8:
            ops.append((f"offer{rnd.randint(0, 9)}", f"from({rnd.choice(names)})"))
        else:
            ops.append((f"offer{rnd.randint(0, 9)}", f"from({rnd.choice(cells)})"))
    queries = [[f"from({rnd.choice(names + cells)})"] for _ in range(10)]
    return names, ops, queries


def play_roles(resident, names, ops):
    dag = OntoDAG()
    dag._resident = resident
    prelude.apply(dag)
    dag.put("from", ["geo"])
    for name in names:
        dag.put(name, [])
    for child, parent in ops:
        try:
            dag.put(child, [parent])
        except ValueError:
            pass
    return dag


class TestRolesAgreeWithTheScan(unittest.TestCase):
    def test_random_worlds(self):
        for seed in range(30):
            names, ops, queries = role_operations(seed)
            by_name = play_roles(True, names, ops)
            by_scan = play_roles(False, names, ops)
            self.assertEqual(edge_set(by_name), edge_set(by_scan), seed)
            for query in queries:
                try:
                    expected = {n.name for n in by_scan.get(query)}
                except ValueError:
                    continue
                self.assertEqual({n.name for n in by_name.get(query)},
                                 expected, (seed, query))
            present = sorted(n for n in by_scan.nodes if n != "*")
            rnd = random.Random(seed)
            for _ in range(60):
                a, b = rnd.choice(present), rnd.choice(present)
                self.assertEqual(by_name.is_below(a, b), by_scan.is_below(a, b),
                                 (seed, a, b))


class TestFilingDoesNotScan(unittest.TestCase):
    """Filing an item touches what it is filed under, not every term of
    that term's head: the members a star yields during a put do not grow
    with the store."""

    @staticmethod
    def count_star(dag):
        counter = {"members": 0}
        original = dag._star

        def counting(head):
            for member in original(head):
                counter["members"] += 1
                yield member
        dag._star = counting
        return counter

    def filing_cost(self, n):
        dag = declare(True)
        dag.put("country", [])
        dag.put("staff", [])
        dag.put("small-item", [])

        def step(i):
            if i % 2 == 0:
                dag.put(f"city{i}", ["in(country)"])
                dag.put(f"person{i}", ["staff"])
            dag.put(f"item{i}", [f"in(city{i - i % 2})", f"mass({i + 1}g)",
                                 f"transport(small-item mass(..{1 + i % 9}kg))"])
            dag.put(f"doc{i}", [f"shared-with(person{i - i % 2})", f"about(city{i - i % 2})"])
        for i in range(n):
            step(i)
        counter = self.count_star(dag)
        for i in range(n, n + 20):
            step(i)
        return counter["members"]

    def test_filing_cost_does_not_grow(self):
        small, large = self.filing_cost(50), self.filing_cost(400)
        # A new value checks one sibling's value space; nothing else scans.
        self.assertLessEqual(large, small)
        self.assertLess(large, 100)


class TestAVirtualConeIsOneWalk(unittest.TestCase):
    """A virtual query term's cone is walked once, whatever its values'
    nesting. A walk per contained value re-walked every value nested
    inside it (quadratic in the nesting); since 2026-10-09 the values,
    being every value inside the term, are not asked for theirs at all."""

    def test_no_value_is_asked_for_the_values_inside_it(self):
        dag = OntoDAG()
        prelude.apply(dag)
        n = 60
        for k in range(n):           # nested ranges, each with a crate
            dag.put(f"crate{k}", [f"mass({k + 1}kg..{2 * n - k}kg)"])
        counter = {"calls": 0}
        original = dag._terms_inside

        def counting(*args, **kwargs):
            counter["calls"] += 1
            return original(*args, **kwargs)
        dag._terms_inside = counting
        found = dag.get(["mass(..10000kg)"])
        self.assertEqual(len(found), 2 * n)
        self.assertEqual(counter["calls"], 1)      # the query term's own


def counting(dag, method):
    """Count the calls `dag` makes to one of its methods."""
    counter = {"calls": 0}
    original = getattr(dag, method)

    def counted(*args, **kwargs):
        counter["calls"] += 1
        return original(*args, **kwargs)
    setattr(dag, method, counted)
    return counter


def play_narrower(resident, names, ops):
    dag = declare(resident)
    dag.put("inside", ["in"])            # narrower relations (§20)
    dag.put("mentions", ["about"])
    for name in names:
        dag.put(name, [])
    for child, parent in ops:
        try:
            dag.put(child, [parent])
        except ValueError:
            pass
    return dag


def narrower_operations(seed, size=8, steps=40):
    rnd = random.Random(seed)
    names = [f"n{i}" for i in range(size)]
    heads = ["in", "inside", "about", "mentions", "shared-with"]
    ops = []
    for _ in range(steps):
        a, b = rnd.sample(names, 2)
        shape = rnd.random()
        if shape < 0.25:
            ops.append((a, b))
        elif shape < 0.85:
            ops.append((a, f"{rnd.choice(heads)}({b})"))
        else:
            ops.append((f"doc{rnd.randint(0, 9)}", f"{rnd.choice(heads)}({b})"))
    return names, ops, []


class TestTermsInsideAreAllOfThem(unittest.TestCase):
    """A walk below a term leaves the terms of its head further down
    unasked when the term's hops listed every one of them inside it
    (`OntoDAG._walk_children`, 2026-10-09). That holds for the hops of
    every kind but the transitive one, whose hops leave the terms inside
    a term inside it to that term; the scan, which lists them all, is the
    reference. A head's anchor edges list every term of it by schema."""

    def check(self, by_name, by_scan, label):
        for name in sorted(by_scan.nodes):
            parsed = by_scan._parse_parametric(name)
            if parsed is None or name not in by_name.nodes:
                continue
            head, kind, canonical = parsed
            try:
                listed, complete = by_name._terms_inside(
                    canonical, head, kind, by_name.nodes[name])
                every, scanned = by_scan._terms_inside(
                    canonical, head, kind, by_scan.nodes[name])
            except ValueError:
                continue
            self.assertTrue(scanned)
            listed = {n.name for n in listed}
            every = {n.name for n in every}
            if complete:
                self.assertEqual(listed, every, (label, name))
            else:
                self.assertEqual(kind, "transitive-dimension", (label, name))
                self.assertLessEqual(listed, every, (label, name))

    def test_every_kind(self):
        for seed in range(10):
            for operations, play_with in ((random_operations, play),
                                          (graph_operations, play_graph),
                                          (role_operations, play_roles),
                                          (narrower_operations, play_narrower)):
                names, ops, _queries = operations(seed)
                self.check(play_with(True, names, ops),
                           play_with(False, names, ops),
                           (operations.__name__, seed))


class TestAQueryCostsItsAnswer(unittest.TestCase):
    """REVIEW §8 item 13 (2026-10-09): a query's work follows its answer,
    not the store around it. Counted, not timed; each case cost what its
    name says before the fix, measured in the decision record (REVIEW
    §4)."""

    @staticmethod
    def places(n, docs, seed=7):
        """A random tree of places, each in an earlier one, and documents
        about random places, three of them also reviews."""
        rnd = random.Random(seed)
        dag = declare(True)
        for name in ("place", "document", "review"):
            dag.put(name, [])
        dag.put("p0", ["place"])
        for i in range(1, n):
            dag.put(f"p{i}", ["place", f"in(p{rnd.randrange(i)})"])
        for j in range(docs):
            parents = ["document", f"about(p{rnd.randrange(n)})"]
            dag.put(f"doc{j}", parents + (["review"] if j < 3 else []))
        return dag

    def answer(self, dag, terms):
        """The answer by `is_below`, which climbs, for comparison."""
        return {n for n in dag.nodes if n != "*" and n not in terms
                and all(dag.is_below(n, t) for t in terms)}

    def test_nested_terms_are_checked_once_each(self):
        # n places each inside the last, a document about each: every
        # about-term was checked against every one above it, n²/2 checks
        # for 2n answers.
        dag = declare(True)
        dag.put("place", [])
        n = 80
        dag.put("level0", ["place"])
        for i in range(1, n):
            dag.put(f"level{i}", ["place", f"in(level{i - 1})"])
        for i in range(n):
            dag.put(f"doc{i}", [f"about(level{i})"])
        dag._memo = None
        checks = counting(dag, "_graph_contains_uncached")
        found = {m.name for m in dag.get(["about(level0)"])}
        self.assertEqual(len(found), 2 * n - 1)
        self.assertEqual(found, self.answer(dag, ["about(level0)"]))
        self.assertLess(checks["calls"], 3 * n)

    def test_places_nothing_is_about_cost_nothing(self):
        # Every village in France was walked to learn that checking the
        # store's few about-terms was cheaper.
        def walked(villages):
            dag = declare(True)
            for name, supers in (("place", []), ("france", ["place"]),
                                 ("lyon", ["place", "in(france)"]),
                                 ("guide", ["about(lyon)"]),
                                 ("atlas", ["about(france)"])):
                dag.put(name, supers)
            for i in range(villages):
                dag.put(f"village{i}", ["place", "in(lyon)"])
            dag._memo = None
            steps = counting(dag, "_walk_children")
            found = {m.name for m in dag.get(["about(france)"])}
            self.assertEqual(found, {"guide", "atlas", "about(lyon)"})
            return steps["calls"]
        self.assertLessEqual(walked(2000), walked(200))

    def test_a_broad_term_beside_a_small_category_is_probed(self):
        dag = self.places(400, 300)
        for stored in (False, True):
            if stored:       # its count, 1, used to make it look smallest
                dag.put("overview", ["document", "about(p0)"])
            dag._memo = None
            checks = counting(dag, "_graph_contains_uncached")
            found = {m.name for m in dag.get(["about(p0)", "review"])}
            self.assertEqual(found, {"doc0", "doc1", "doc2"}, stored)
            self.assertLess(checks["calls"], 40, stored)
            del dag._graph_contains_uncached

    def test_a_small_term_beside_a_broad_category_is_walked(self):
        dag = self.places(400, 300)
        leaf = next(f"p{i}" for i in range(399, 0, -1)
                    if f"about(p{i})" in dag.nodes
                    and not dag.get([f"in(p{i})"]))
        dag._memo = None
        probes = counting(dag, "_probe_cones")
        found = {m.name for m in dag.get([f"about({leaf})", "document"])}
        self.assertEqual(found, self.answer(dag, [f"about({leaf})", "document"]))
        self.assertLessEqual(probes["calls"], len(found))

    def test_a_value_range_beside_a_small_category_is_probed(self):
        rnd = random.Random(5)
        dag = declare(True)
        for name in ("parcel", "fragile", "want"):
            dag.put(name, [])
        for i in range(1000):
            dag.put(f"parcel{i}", ["parcel", f"mass({rnd.randint(1, 10000)}g)"]
                    + (["fragile"] if i % 250 == 0 else []))
        dag.put("want1", ["want", "mass(..5kg)"])      # stored, count 1
        dag._memo = None
        steps = counting(dag, "_walk_children")
        found = {m.name for m in dag.get(["mass(..5kg)", "fragile"])}
        self.assertEqual(found, self.answer(dag, ["mass(..5kg)", "fragile"]))
        self.assertLess(steps["calls"], 40)

    def test_a_head_holds_every_term_of_it(self):
        # `get about`, and the empty query, asked every about-term for the
        # about-terms inside it, though the head's anchors list them all.
        dag = self.places(300, 200)
        for terms in (["about"], []):
            dag._memo = None
            asked = counting(dag, "_terms_inside")
            found = dag.get(terms)
            self.assertEqual(asked["calls"], 0, terms)
            self.assertTrue(found, terms)
            del dag._terms_inside


if __name__ == "__main__":
    unittest.main()



class TestALoadedStoreAnswersAsItDidLive(unittest.TestCase):
    """Found by CONTRACT.md G7's fixture (2026-10-07): a value index was
    kept up to date when a value node was created, not when its anchor
    edge arrived, and a load creates every node before filing any. A head
    whose index was built mid-load then missed its values: `get geo(u2e)`
    answered nothing after a load, while `is_below` (which needs no index)
    still answered true. The oracle is the scan, which uses no index."""

    def test_the_g7_fixture_loaded_agrees_with_the_scan(self):
        import os
        from ontodag import native
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "fixtures", "g7.od")
        indexed, scanned = native.load(path), native.load(path)
        scanned._resident = False
        for query in (["geo(u2e)"], ["geo(u2ed)"], ["from(u2e)"], ["time(2026)"],
                      ["mass(..5kg)"], ["count(2..)"], ["size(25x35x45cm)"],
                      ["in(japan)"], ["in(louvre)"], ["about(japan)"],
                      ["shared-with(alice)"], ["transport(small-item)"]):
            self.assertEqual({n.name for n in indexed.get(query)},
                             {n.name for n in scanned.get(query)}, query)
