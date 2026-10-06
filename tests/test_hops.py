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
                       ("reversed-dimension", "for"),
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
            return f"weight({rnd.randint(1, 9)}kg)"
        if shape < 0.7:
            lo = rnd.randint(1, 6)
            return f"weight({lo}kg..{lo + rnd.randint(1, 4)}kg)"
        return f"geo({rnd.choice(['u2', 'u2e', 'u2e4', 'u2e5', 'u3'])})"

    def term():
        shape = rnd.random()
        a, b = rnd.sample(names, 2)
        if shape < 0.2:
            return f"in({a})"
        if shape < 0.35:
            return f"about({a})"
        if shape < 0.5:
            return f"for({a})"
        if shape < 0.65:
            return f"transport({a})"
        if shape < 0.8:
            return f"transport({a} {b})"
        return f"transport({a} weight(..{rnd.randint(2, 9)}kg))"

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
            dag.put(f"item{i}", [f"in(city{i - i % 2})", f"weight({i + 1}g)",
                                 f"transport(small-item weight(..{1 + i % 9}kg))"])
            dag.put(f"doc{i}", [f"for(person{i - i % 2})", f"about(city{i - i % 2})"])
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


if __name__ == "__main__":
    unittest.main()
