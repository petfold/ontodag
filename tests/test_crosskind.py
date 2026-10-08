"""Every kind at once (review, 2026-10-09).

Each kind has its own order-independence oracle (test_dimensions_dag,
test_roles, test_graph_kind, test_transitive, test_narrower), but the kinds
share one reduction, one re-reduction and one set of hop indexes, and no
test mixed them. Here random worlds use linear, prefix, calendar and count
values, a role of `geo` taking places and cells, graph-kind compounds,
`in`/`about`/`shared-with` with compounds, and a narrower relation, in one
store:

* every order of the same writes, and a merge of two orders, gives one root
  (G1, I7);
* a lazy reader over the committed root, which scans stars where the
  resident store uses its hop indexes, answers every query the same;
* the sparse writer, writing the same over the same base, commits the same
  root as the eager one (until 2026-10-09 it did not once an earlier put
  had built its argument index: the terms it created later were never
  indexed, so re-reduction missed them).
"""

import random
import unittest

from recordstore import MemoryBytesStore, RecordStore

from ontodag import prelude
from ontodag.eager import EagerOntoDAG
from ontodag.lazy import LazyOntoDAG, SparseOntoDAG

CELLS = ["u2", "u2e", "u2e4", "u2e5", "u3"]


def declare(dag):
    prelude.apply(dag)              # mass, geo, time, count, in, about, shared-with
    dag.put("graph-dimension", ["dimension"])
    dag.put("transport", ["graph-dimension"])
    dag.put("from", ["geo"])        # a role of geo: places and cells
    dag.put("located-at", ["in"])   # a narrower relation
    return dag


def world(seed):
    rng = random.Random(seed)
    cats = [f"c{i}" for i in range(6)]
    places = [f"p{i}" for i in range(5)]
    writes = []
    for i in range(1, 6):
        if rng.random() < 0.6:
            writes.append((cats[i], [cats[rng.randrange(i)]]))       # acyclic
    for i in range(1, 5):
        if rng.random() < 0.6:
            writes.append((places[i], [f"in({places[rng.randrange(i)]})"]))
    for p in places:
        if rng.random() < 0.5:
            writes.append((p, [f"geo({rng.choice(CELLS)})"]))

    def term():
        r = rng.random()
        a, b = rng.sample(cats, 2)
        pa = rng.choice(places)
        if r < 0.1:
            return f"mass({rng.randint(1, 9)}kg)"
        if r < 0.18:
            lo = rng.randint(1, 6)
            return f"mass({lo}kg..{lo + rng.randint(1, 4)}kg)"
        if r < 0.25:
            return f"geo({rng.choice(CELLS)})"
        if r < 0.3:
            return f"time(2026-0{rng.randint(1, 9)})"
        if r < 0.34:
            return f"count({rng.randint(1, 5)})"
        if r < 0.42:
            return f"from({rng.choice(places + CELLS)})"
        if r < 0.52:
            return f"transport({a})" if rng.random() < 0.5 else f"transport({a} {b})"
        if r < 0.62:
            return f"in({pa})" if rng.random() < 0.6 else f"in({pa} {a})"
        if r < 0.7:
            return f"located-at({pa})"
        if r < 0.8:
            return f"about({a})" if rng.random() < 0.6 else f"about({a} {b})"
        if r < 0.9:
            return f"shared-with({a})" if rng.random() < 0.6 else f"shared-with({a} {b})"
        return rng.choice(cats)

    for k in range(10):
        writes.append((f"x{k}", [term() for _ in range(rng.choice((1, 2, 3)))]))
    queries = [[term()] for _ in range(8)] + [[term(), term()] for _ in range(4)]
    return cats, places, writes, queries


def build(cats, places, writes, order, blobs=None):
    dag = declare(EagerOntoDAG(RecordStore(
        blobs if blobs is not None else MemoryBytesStore())))
    for c in cats:
        dag.put(c, [])
    for p in places:
        dag.put(p, ["geo(u)"])      # a place is in geo before a role names it
    shuffled = list(writes)
    random.Random(order).shuffle(shuffled)
    refused = []
    for name, supers in shuffled:
        try:
            dag.put(name, supers)
        except ValueError:          # e.g. provably disjoint masses: in every order
            refused.append((name, tuple(supers)))
    return dag, sorted(refused)


class TestEveryKindAtOnce(unittest.TestCase):
    def test_every_order_and_merge_gives_one_root(self):
        for seed in range(40):
            cats, places, writes, _ = world(seed)
            built = [build(cats, places, writes, order) for order in range(4)]
            self.assertEqual(len({tuple(r) for _, r in built}), 1, seed)
            roots = {dag.commit() for dag, _ in built}
            merged = EagerOntoDAG(RecordStore(MemoryBytesStore()))
            merged.merge(built[1][0])
            merged.merge(built[2][0])
            roots.add(merged.commit())
            self.assertEqual(len(roots), 1, seed)

    def test_a_lazy_reader_answers_the_same(self):
        for seed in range(40):
            cats, places, writes, queries = world(seed)
            blobs = MemoryBytesStore()
            eager, _ = build(cats, places, writes, 0, blobs)
            root = eager.commit()
            lazy = LazyOntoDAG(RecordStore.at(root, blobs))
            for query in queries:
                try:
                    expected = {i.name for i in eager.get(query)}
                except ValueError:
                    continue
                self.assertEqual({i.name for i in lazy.get(query)}, expected,
                                 (seed, query))
            rng = random.Random(seed)
            names = sorted(n for n in eager.nodes if n != "*")
            for _ in range(40):
                a, b = rng.choice(names), rng.choice(names)
                self.assertEqual(lazy.is_below(a, b), eager.is_below(a, b),
                                 (seed, a, b))


    def test_the_sparse_writer_commits_the_same_root(self):
        for seed in range(25):
            cats, places, writes, _ = world(seed)
            blobs = MemoryBytesStore()
            base = declare(EagerOntoDAG(RecordStore(blobs)))
            for c in cats:
                base.put(c, [])
            for p in places:
                base.put(p, ["geo(u)"])
            root = base.commit()
            roots = set()
            order = list(writes)
            random.Random(seed).shuffle(order)    # facts after the items too
            for writer in (EagerOntoDAG(RecordStore(blobs, root=root)),
                           SparseOntoDAG(RecordStore(blobs, root=root))):
                writer.put("warm-up", [cats[0]])   # builds the indexes first
                for name, supers in order:
                    try:
                        writer.put(name, supers)
                    except ValueError:
                        pass
                roots.add(writer.commit())
            self.assertEqual(len(roots), 1, seed)

if __name__ == "__main__":
    unittest.main()
