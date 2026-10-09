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
  indexed, so re-reduction missed them);
* dropping every derived cache at random points changes no answer, no
  refusal and no root;
* with removals and moves among the writes, an eager store, the same with
  its caches dropped, and the sparse writer agree on every outcome and on
  the root.
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


# Derived state the core rebuilds from the graph when it is absent: the
# argument, value, constraint and shape indexes, the memo, and the heads,
# dimension, relation and escape caches.
CACHES = ("_args", "_nested_keys", "_compound_terms", "_values",
          "_constraint_values", "_unit_cache", "_shapes", "_nested_cache",
          "_nested_version", "_memo", "_memo_version", "_heads_cache",
          "_escape_cache", "_dim_cache", "_rel_cache")


def drop_caches(dag):
    for name in CACHES:
        if name in vars(dag):
            delattr(dag, name)


def answer(dag, op):
    kind, arg = op
    try:
        if kind == "get":
            return frozenset(i.name for i in dag.get(arg))
        if kind == "below":
            return dag.is_below(*arg)
        return frozenset(i.name for i in dag.get_overlapping(arg))
    except (ValueError, KeyError) as exc:
        return type(exc).__name__


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

    def test_dropping_every_cache_changes_no_answer(self):
        """Two stores take the same writes with the same queries between
        them; one has every derived cache dropped at random points. A cache
        that a write failed to keep current shows as a different answer,
        refusal or root. (Checked 2026-10-09: with the argument index never
        fed, 12 of 20 worlds differ.)"""
        for seed in range(30):
            cats, places, writes, queries = world(seed)
            rng = random.Random(seed * 7 + 1)
            dags = [declare(EagerOntoDAG(RecordStore(MemoryBytesStore())))
                    for _ in range(2)]
            for dag in dags:
                for c in cats:
                    dag.put(c, [])
                for p in places:
                    dag.put(p, ["geo(u)"])
            order = list(writes)
            rng.shuffle(order)
            for name, supers in order:
                names = sorted(n for n in dags[0].nodes if n != "*")
                ops = [("get", rng.choice(queries)) for _ in range(2)]
                ops += [("below", (rng.choice(names), rng.choice(names)))
                        for _ in range(3)]
                ops.append(("overlap", rng.choice(queries)[0]))
                if rng.random() < 0.4:
                    drop_caches(dags[1])
                for op in ops:
                    self.assertEqual(answer(dags[1], op), answer(dags[0], op),
                                     (seed, op))
                outcomes = []
                for dag in dags:
                    try:
                        dag.put(name, supers)
                        outcomes.append(None)
                    except ValueError as exc:
                        outcomes.append(str(exc))
                self.assertEqual(outcomes[1], outcomes[0], (seed, name, supers))
            self.assertEqual(dags[1].commit(), dags[0].commit(), seed)

    def test_removals_and_moves_agree_across_writers(self):
        """Writes mixed with `remove`, `reclassify` and `remove_cone`, applied
        to an eager store, an eager store whose caches are dropped at random
        points, and the sparse writer, from one committed base. Worlds 150 to
        189 include the four that found a released bug on 2026-10-09:
        removing a category an `about` compound named made later writes
        raise in the eager store, while the sparse writer, never loading the
        term, accepted them."""
        for seed in range(150, 190):
            cats, places, writes, _ = world(seed)
            rng = random.Random(seed * 31 + 5)
            blobs = MemoryBytesStore()
            base = declare(EagerOntoDAG(RecordStore(blobs)))
            for c in cats:
                base.put(c, [])
            for p in places:
                base.put(p, ["geo(u)"])
            root = base.commit()
            writers = [EagerOntoDAG(RecordStore(blobs, root=root)),
                       EagerOntoDAG(RecordStore(blobs, root=root)),
                       SparseOntoDAG(RecordStore(blobs, root=root))]
            order = list(writes)
            rng.shuffle(order)
            items = [name for name, _ in order]
            pending, ops = list(order), []
            while pending:
                r = rng.random()
                if r < 0.7:
                    name, supers = pending.pop(0)
                    ops.append(("put", name, supers))
                elif r < 0.8:
                    ops.append(("remove", rng.choice(items + cats[1:])))
                elif r < 0.92:
                    ops.append(("move", rng.choice(items), rng.choice(
                        cats + [f"in({rng.choice(places)})",
                                f"about({rng.choice(cats)})",
                                f"transport({rng.choice(cats)})"])))
                else:
                    ops.append(("cone", rng.choice(cats[1:])))
            for op in ops:
                if rng.random() < 0.4:
                    drop_caches(writers[1])
                outcomes = []
                for dag in writers:
                    if op[0] != "put" and op[1] not in dag.nodes:
                        outcomes.append("absent")
                        continue
                    try:
                        if op[0] == "put":
                            dag.put(op[1], op[2])
                        elif op[0] == "remove":
                            dag.remove(op[1])
                        elif op[0] == "move":
                            dag.reclassify([op[1]], to=[op[2]])
                        else:
                            dag.remove_cone([op[1]])
                        outcomes.append("ok")
                    except (ValueError, KeyError) as exc:
                        outcomes.append(type(exc).__name__)
                self.assertEqual(len(set(outcomes)), 1, (seed, op, outcomes))
            self.assertEqual(len({dag.commit() for dag in writers}), 1, seed)

    def test_removing_with_terms_agrees_across_writers(self):
        """Removals that take the terms naming what goes (`with_terms`) and
        renames, mixed with writes, over every kind at once: the three
        writers agree on every outcome and on the root."""
        for seed in range(40):
            cats, places, writes, _ = world(seed)
            rng = random.Random(seed * 17 + 3)
            blobs = MemoryBytesStore()
            base = declare(EagerOntoDAG(RecordStore(blobs)))
            for c in cats:
                base.put(c, [])
            for p in places:
                base.put(p, ["geo(u)"])
            root = base.commit()
            writers = [EagerOntoDAG(RecordStore(blobs, root=root)),
                       EagerOntoDAG(RecordStore(blobs, root=root)),
                       SparseOntoDAG(RecordStore(blobs, root=root))]
            order = list(writes)
            rng.shuffle(order)
            items = [name for name, _ in order]
            ops = []
            for name, supers in order:
                ops.append(("put", name, supers))
                r = rng.random()
                if r < 0.25:
                    ops.append(("remove", rng.choice(cats[1:] + places + items)))
                elif r < 0.35:
                    ops.append(("cone", rng.choice(cats[1:])))
                elif r < 0.45:
                    ops.append(("rename", rng.choice(cats[1:] + places),
                                f"n{len(ops)}"))
            for op in ops:
                if rng.random() < 0.4:
                    drop_caches(writers[1])
                outcomes = []
                for dag in writers:
                    if op[0] != "put" and op[1] not in dag.nodes:
                        outcomes.append("absent")
                        continue
                    try:
                        if op[0] == "put":
                            dag.put(op[1], op[2])
                        elif op[0] == "remove":
                            dag.remove(op[1], with_terms=True)
                        elif op[0] == "cone":
                            dag.remove_cone([op[1]], with_terms=True)
                        else:
                            dag.rename(op[1], op[2])
                        outcomes.append("ok")
                    except (ValueError, KeyError) as exc:
                        outcomes.append(type(exc).__name__)
                self.assertEqual(len(set(outcomes)), 1, (seed, op, outcomes))
            self.assertEqual(len({dag.commit() for dag in writers}), 1, seed)


if __name__ == "__main__":
    unittest.main()
