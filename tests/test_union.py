"""Union in get(): get_any — DNF over conjunctive queries.

Query-side only (DATABASE_DIRECTION "Pure now" item 3): no stored state,
canonical form untouched. Oracle discipline as everywhere: results compared
against naive per-disjunct intersections over independently-computed
reachability, on a fixture and on a seeded random DAG."""

import itertools
import random
import unittest

from ontodag.dag import OntoDAG
from ontodag.eager import EagerOntoDAG
from ontodag.lazy import LazyOntoDAG
from recordstore import MemoryBytesStore, RecordStore


def reach(node):
    seen, stack = set(), [node]
    while stack:
        for child in stack.pop().neighbors:
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def naive_get_any(dag, queries):
    """The oracle: union of naive cone intersections."""
    result = set()
    for query in queries:
        cones = [reach(dag.nodes[t]) if t in dag.nodes else set()
                 for t in query]
        result |= set.intersection(*cones) if cones else set()
    return {n.name for n in result}


def zoo():
    dag = OntoDAG()
    for name, supers in [
        ("animal", []), ("pet", []), ("machine", []),
        ("dog", ["animal", "pet"]), ("cat", ["animal", "pet"]),
        ("wolf", ["animal"]), ("aibo", ["machine", "pet"]),
        ("spaniel", ["dog"]), ("drone", ["machine"]),
    ]:
        dag.put(name, supers)
    return dag


class TestGetAny(unittest.TestCase):
    def test_readme_case(self):
        dag = zoo()
        result = {i.name for i in dag.get_any([{"animal", "pet"}, {"machine"}])}
        self.assertEqual(result,
                         {"dog", "cat", "spaniel", "aibo", "drone"})

    def test_oracle_over_fixture_combinations(self):
        dag = zoo()
        names = [n for n in dag.nodes if n != "*"]
        singles = [{a} for a in names]
        pairs = [set(p) for p in itertools.combinations(names, 2)]
        rng = random.Random(3)
        for _ in range(120):
            queries = rng.sample(singles + pairs, rng.randint(1, 3))
            self.assertEqual(
                {i.name for i in dag.get_any(queries)},
                naive_get_any(dag, [sorted(q) for q in queries]),
                queries)

    def test_oracle_on_random_dag(self):
        rng = random.Random(11)
        dag = OntoDAG()
        names = [f"n{i}" for i in range(40)]
        for i, name in enumerate(names):
            supers = rng.sample(names[:i], min(i, rng.randint(0, 2)))
            dag.put(name, supers)
        for _ in range(80):
            queries = [set(rng.sample(names, rng.randint(1, 2)))
                       for _ in range(rng.randint(1, 3))]
            self.assertEqual(
                {i.name for i in dag.get_any(queries)},
                naive_get_any(dag, queries))

    def test_superset_disjuncts_are_skipped_correctly(self):
        dag = zoo()
        # {animal, pet} ⊃ {animal}: the narrower disjunct adds nothing.
        self.assertEqual(dag.get_any([{"animal"}, {"animal", "pet"}]),
                         dag.get({"animal"}))

    def test_duplicate_disjuncts_are_one(self):
        dag = zoo()
        self.assertEqual(dag.get_any([{"pet"}, {"pet"}]), dag.get({"pet"}))

    def test_unknown_term_empties_only_its_branch(self):
        dag = zoo()
        result = {i.name for i in dag.get_any([{"no-such"}, {"machine"}])}
        self.assertEqual(result, {"aibo", "drone"})

    def test_empty_queries_raise(self):
        dag = zoo()
        with self.assertRaises(TypeError):
            dag.get_any([])
        with self.assertRaises(TypeError):
            dag.get_any([set()])

    def test_dimensions_outside_a_range(self):
        dag = OntoDAG()
        dag.put("dimension", [])
        dag.put("linear-dimension", ["dimension"])
        dag.put("weight", ["linear-dimension"])
        dag.put("light", ["weight(1kg)"])
        dag.put("mid", ["weight(3kg)"])
        dag.put("heavy", ["weight(9kg)"])
        # The classic union need: OUTSIDE an interval — under 2 kg OR over
        # 5 kg — inexpressible as one conjunctive query.
        result = {i.name
                  for i in dag.get_any([{"weight(..2kg)"}, {"weight(5kg..)"}])}
        self.assertIn("light", result)
        self.assertIn("heavy", result)
        self.assertNotIn("mid", result)

    def test_inherited_by_the_lazy_reader(self):
        blobs = MemoryBytesStore()
        eager = EagerOntoDAG(RecordStore(blobs))
        for name, supers in [("a", []), ("b", []), ("x", ["a"]),
                             ("y", ["b"])]:
            eager.put(name, supers)
        root = eager.commit()
        reader = LazyOntoDAG(RecordStore.at(root, blobs))
        self.assertEqual({i.name for i in reader.get_any([{"a"}, {"b"}])},
                         {"x", "y"})


if __name__ == "__main__":
    unittest.main()
