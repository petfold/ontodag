"""LazyOntoDAG — on-demand reading of a published OntoDAG.

Two things are asserted throughout, in the style DATABASE_DIRECTION.md asks
for: **the answer is right** (an eagerly-hydrated EagerOntoDAG over the same
root is the oracle) **and the number of fetches is small** — a lazy reader that
quietly loads everything is correct and useless, so correctness alone would not
catch the regression that matters.
"""

import random
import unittest

from ontodag.dag import Item
from ontodag.lazy import LazyOntoDAG
from ontodag.eager import EagerOntoDAG
from recordstore import MemoryBytesStore, RecordStore


VEHICLES = [
    ("vehicle", []), ("electric", []),
    ("car", ["vehicle"]), ("bike", ["vehicle"]),
    ("ev", ["car", "electric"]), ("ebike", ["bike", "electric"]),
]


def publish(puts):
    """Build a graph eagerly, commit it, and return (root, blobs)."""
    blobs = MemoryBytesStore()
    dag = EagerOntoDAG(RecordStore(blobs))
    for name, supers in puts:
        dag.put(name, list(supers))
    return dag.commit(), blobs


def eager(root, blobs):
    return EagerOntoDAG(RecordStore.at(root, blobs))


def lazy(root, blobs, **kwargs):
    return LazyOntoDAG(RecordStore.at(root, blobs), **kwargs)


def names(items):
    return {item.name for item in items}


def deep_chain(length, width=3):
    """A long chain with a few leaves hanging off each link.

    Querying near the bottom must not walk the chain above it — that is the
    case where "load everything" is catastrophic and laziness obvious.
    """
    puts = [("c0", [])]
    for i in range(1, length):
        puts.append((f"c{i}", [f"c{i - 1}"]))
        for j in range(width):
            puts.append((f"leaf{i}_{j}", [f"c{i}"]))
    return puts


class TestAnswersMatchEagerReader(unittest.TestCase):
    def setUp(self):
        self.root, self.blobs = publish(VEHICLES)
        self.oracle = eager(self.root, self.blobs)

    def test_every_one_two_and_three_term_query(self):
        terms = sorted(n for n in self.oracle.nodes if n != "*")
        reader = lazy(self.root, self.blobs)
        checked = 0
        for i, a in enumerate(terms):
            for b in terms[i:]:
                for c in terms:
                    query = [a, b, c]
                    self.assertEqual(names(self.oracle.get(query)),
                                     names(reader.get(query)),
                                     f"query {query}")
                    checked += 1
        self.assertGreater(checked, 100)

    def test_unknown_term_is_empty_not_an_error(self):
        reader = lazy(self.root, self.blobs)
        self.assertEqual(set(), reader.get(["nosuchthing"]))
        self.assertEqual(set(), reader.get(["car", "nosuchthing"]))
        # ... and the miss is remembered rather than re-fetched
        before = reader.fetches
        reader.get(["nosuchthing"])
        self.assertEqual(before, reader.fetches)

    def test_empty_query_is_everything_and_costs_everything(self):
        # Correct, and honestly expensive: the empty query is the root's
        # whole cone, so a lazy reader must fetch the store to answer it.
        # That is the one query for which laziness buys nothing — worth
        # knowing before wiring `get([])` into a thin client's hot path.
        reader = lazy(self.root, self.blobs)
        self.assertEqual(names(self.oracle.get([])), names(reader.get([])))
        self.assertGreaterEqual(reader.fetches, len(self.oracle.nodes) - 1)

    def test_descendants_and_ancestors_by_name_or_item(self):
        reader = lazy(self.root, self.blobs)
        self.assertEqual({"car", "bike", "ev", "ebike"},
                         names(reader.get_descendants("vehicle")))
        self.assertEqual({"car", "bike", "ev", "ebike"},
                         names(reader.get_descendants(Item("vehicle"))))
        self.assertEqual({"car", "vehicle", "electric", "*"},
                         names(reader.get_ancestors("ev")))
        self.assertEqual(set(), reader.get_descendants("nosuchthing"))
        with self.assertRaises(ValueError):
            reader.get_ancestors("nosuchthing")

    def test_counts_come_from_the_records(self):
        reader = lazy(self.root, self.blobs)
        reader.get(["vehicle"])
        for name, node in reader.nodes.items():
            if name in reader._expanded:
                self.assertEqual(self.oracle.nodes[name].descendant_count,
                                 node.descendant_count, name)


class TestFetchBudget(unittest.TestCase):
    def test_query_near_a_leaf_does_not_read_the_whole_store(self):
        puts = deep_chain(60)                      # 60 + 59*3 = 237 records
        root, blobs = publish(puts)
        total = len(list(RecordStore.at(root, blobs).keys()))
        self.assertGreater(total, 200)

        reader = lazy(root, blobs)
        result = reader.get(["c58"])
        self.assertEqual(names(eager(root, blobs).get(["c58"])), names(result))
        # the cone of c58 is c59 + 6 leaves; the 58 links above it and their
        # leaves are irrelevant and must stay unfetched
        self.assertLess(reader.fetches, 20)
        self.assertLess(reader.fetches, total // 10)

    def test_intersection_stops_at_the_smallest_cone(self):
        # 'electric' has a small cone, 'vehicle' a large one; the planner
        # starts small, and the leaves under 'vehicle' are never visited.
        puts = list(VEHICLES) + [(f"car{i}", ["car"]) for i in range(50)]
        root, blobs = publish(puts)
        reader = lazy(root, blobs)
        self.assertEqual({"ev", "ebike"},
                         names(reader.get(["vehicle", "electric"])))
        self.assertLess(reader.fetches, 12)

    def test_repeated_queries_are_free_when_cones_are_cached(self):
        root, blobs = publish(deep_chain(30))
        reader = lazy(root, blobs)
        reader.get(["c20", "c25"])
        settled = reader.fetches
        for _ in range(5):
            reader.get(["c20", "c25"])
        self.assertEqual(settled, reader.fetches)

    def test_cache_can_be_disabled_and_is_bounded(self):
        root, blobs = publish(VEHICLES)
        uncached = lazy(root, blobs, cache_cones=False)
        uncached.get(["vehicle"])
        first = uncached.fetches
        uncached.get(["vehicle"])
        self.assertEqual(first, uncached.fetches,   # records still cached
                         "records should be cached even without cone caching")
        self.assertIsNone(uncached._cone_cache)

        bounded = lazy(root, blobs, max_cached_cones=2)
        for name in ("vehicle", "electric", "car", "bike"):
            bounded.get_descendants(name)
        self.assertLessEqual(len(bounded._cone_cache), 2)


class TestRandomizedAgainstEager(unittest.TestCase):
    def test_random_dag_all_queries_match(self):
        rng = random.Random(20260725)
        puts = []
        for i in range(40):
            supers = rng.sample([f"n{j}" for j in range(i)],
                                min(i, rng.randint(0, 2)))
            puts.append((f"n{i}", supers))
        root, blobs = publish(puts)
        oracle, reader = eager(root, blobs), lazy(root, blobs)

        pool = [f"n{i}" for i in range(40)]
        for _ in range(200):
            query = rng.sample(pool, rng.randint(1, 3))
            self.assertEqual(names(oracle.get(query)), names(reader.get(query)),
                             f"query {query}")
        # a fresh reader answering one query still beats full hydration
        single = lazy(root, blobs)
        single.get(rng.sample(pool, 2))
        self.assertLess(single.fetches, len(pool))


class TestReadOnly(unittest.TestCase):
    def setUp(self):
        self.root, self.blobs = publish(VEHICLES)
        self.reader = lazy(self.root, self.blobs)

    def test_mutations_are_refused(self):
        for call in (
            lambda: self.reader.put("truck", ["vehicle"]),
            lambda: self.reader.remove("car"),
            lambda: self.reader.merge(eager(self.root, self.blobs)),
            lambda: self.reader.commit(),
            lambda: self.reader.add_node(Item("truck")),
        ):
            with self.assertRaises(TypeError):
                call()

    def test_load_all_gives_the_whole_graph_for_dag_operations(self):
        oracle = eager(self.root, self.blobs)
        self.reader.load_all()
        self.assertEqual(set(oracle.nodes), set(self.reader.nodes))
        self.assertEqual(
            {(p.name, c.name) for p in oracle.nodes.values()
             for c in p.neighbors},
            {(p.name, c.name) for p in self.reader.nodes.values()
             for c in p.neighbors},
        )
        order = [n.name for n in self.reader.topological_sort()]
        self.assertLess(order.index("vehicle"), order.index("ev"))


class TestLazyDimensions(unittest.TestCase):
    """DIMENSIONS.md §12 step 5: virtual-term queries over a published
    store, eager reader as the oracle, fetch budget asserted (a lazy reader
    that quietly loads everything is correct and useless)."""

    @classmethod
    def setUpClass(cls):
        puts = [
            ("dimension", []), ("linear-dimension", ["dimension"]),
            ("weight", ["linear-dimension"]),
            ("parcel", ["weight(3kg)"]),
            ("flour-bag", ["weight(1.2kg)"]),
            ("heavy-parcel", ["weight(9kg)"]),
            ("variable-offer", ["weight(0.8kg..1.5kg)"]),
            ("unrelated", []),
        ] + [(f"unrelated-{i}", ["unrelated"]) for i in range(40)]
        cls.root, cls.blobs = publish(puts)
        cls.total_records = 40 + 12   # leaves + the rest incl. root/values

    def test_virtual_queries_match_eager(self):
        oracle = eager(self.root, self.blobs)
        reader = lazy(self.root, self.blobs)
        for term in ["weight(..5kg)", "weight(1kg..)",
                     "weight(2kg..8kg)", "weight(3kg)"]:
            self.assertEqual(
                {i.name for i in oracle.get([term])},
                {i.name for i in reader.get([term])},
                term)

    def test_get_overlapping_matches_eager(self):
        oracle = eager(self.root, self.blobs)
        reader = lazy(self.root, self.blobs)
        expected = {i.name for i in oracle.get_overlapping("weight(1kg..)")}
        self.assertIn("variable-offer", expected)   # the possibly-satisfies
        self.assertEqual(
            expected,
            {i.name for i in reader.get_overlapping("weight(1kg..)")})

    def test_fetch_budget_ignores_unrelated_subtree(self):
        reader = lazy(self.root, self.blobs)
        reader.get(["weight(..5kg)"])
        # The query walks the kind chain, the star and the matching cones —
        # never the 40-leaf unrelated subtree.
        self.assertLess(reader.fetches, 20,
                        f"lazy dimension query fetched {reader.fetches}")

    def test_dimension_free_query_costs_no_dimension_fetches(self):
        reader = lazy(self.root, self.blobs)
        reader.get(["unrelated"])
        # Plain names never trigger head lookups: budget stays the cone.
        self.assertLess(reader.fetches, 45)

    def test_still_read_only(self):
        reader = lazy(self.root, self.blobs)
        with self.assertRaises(TypeError):
            reader.put("x", ["weight(1kg)"])


if __name__ == "__main__":
    unittest.main()


class _BatchingRecords:
    """A record store that reads many records at once (`get_many`), counting
    round trips: each `get` or `get_many` call is one."""

    def __init__(self, store):
        self.store = store
        self.calls = 0

    def get(self, key):
        self.calls += 1
        return self.store.get(key)

    def get_many(self, keys):
        self.calls += 1
        found = {}
        for key in keys:
            try:
                found[key] = self.store.get(key)
            except KeyError:
                pass
        return found


def wide_tree(levels=4, fanout=6):
    """`levels` levels below one top, `fanout` children per node, plus a
    second parent for every leaf so cones overlap."""
    puts = [("top", []), ("other", [])]
    level = ["top"]
    for depth in range(1, levels + 1):
        nxt = []
        for parent in level:
            for i in range(fanout):
                name = f"{parent}.{i}"
                supers = [parent] if depth < levels else [parent, "other"]
                puts.append((name, supers))
                nxt.append(name)
        level = nxt
    return puts


class TestPrefetch(unittest.TestCase):
    """`prefetch=True` reads a walk's waiting frontier in one batch when the
    store can: the same answers, a round trip per level instead of per node
    (BROWSER.md §4b)."""

    def setUp(self):
        self.root, self.blobs = publish(wide_tree())   # 1 + 6 + 36 + 216 + 1296 nodes

    def reader(self, prefetch):
        records = _BatchingRecords(RecordStore.at(self.root, self.blobs))
        return LazyOntoDAG(records, prefetch=prefetch), records

    def test_same_answers(self):
        plain, _ = self.reader(False)
        batched, _ = self.reader(True)
        oracle = eager(self.root, self.blobs)
        for query in (["top"], ["top.3"], ["top.1.2", "other"], ["other"], ["top.5.5.5"]):
            self.assertEqual(names(plain.get(query)), names(oracle.get(query)), query)
            self.assertEqual(names(batched.get(query)), names(oracle.get(query)), query)
        self.assertEqual(names(batched.get_ancestors("top.0.1.2.3")),
                         names(oracle.get_ancestors("top.0.1.2.3")))
        self.assertTrue(batched.is_below("top.4.4.4.4", "top"))

    def test_a_broad_cone_costs_rounds_per_level_not_per_node(self):
        batched, records = self.reader(True)
        cone = batched.get_descendants("top.2")        # 6 + 36 + 216 nodes
        self.assertEqual(len(cone), 258)
        self.assertLessEqual(records.calls, 20)
        # switched off: one round trip per record read
        plain, plain_records = self.reader(False)
        plain.get_descendants("top.2")
        self.assertGreater(plain_records.calls, 250)
        self.assertEqual(plain.fetches, plain_records.calls)

    def test_without_get_many_it_reads_one_by_one(self):
        store = RecordStore.at(self.root, self.blobs)
        if hasattr(store, "get_many"):
            self.skipTest("this recordstore reads many records at once")
        reader = LazyOntoDAG(store, prefetch=True)
        reader.get_descendants("top.2")
        self.assertEqual(reader.rounds, reader.fetches)
