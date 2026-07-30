"""Published cone summaries (ontodag.cones + LazyOntoDAG wiring).

Plan steps A-C of docs/CONE_SUMMARIES_PLAN.md, with the plan's own oracles:
per-node membership vs get_descendants, popcount == descendant_count (I5 as
oracle, on a dimension-free graph), canonical index roots, the untouched
asserted root, index-vs-no-index result equality, the fetch-budget drop
that is the whole point, and staleness falling back to the exact walk."""

import random
import unittest

from ontodag.cones import ConeIndex, build_index, summarized_names
from ontodag.eager import EagerOntoDAG
from ontodag.lazy import LazyOntoDAG
from recordstore import MemoryBytesStore, RecordStore


def publish(puts):
    blobs = MemoryBytesStore()
    dag = EagerOntoDAG(RecordStore(blobs))
    for name, supers in puts:
        dag.put(name, list(supers))
    return dag, dag.commit(), blobs


def broad_fixture(seed=7, tops=5, mids=40, leaves=400):
    """A scaled-down version of the plan's 3,221-record shape: every leaf
    under two mid categories, every mid under two tops."""
    rng = random.Random(seed)
    puts = [(f"t{i}", []) for i in range(tops)]
    for m in range(mids):
        puts.append((f"m{m}", rng.sample([f"t{i}" for i in range(tops)], 2)))
    for leaf in range(leaves):
        puts.append((f"x{leaf}",
                     rng.sample([f"m{m}" for m in range(mids)], 2)))
    return puts


class TestBuild(unittest.TestCase):
    def test_membership_matches_get_descendants_and_counts(self):
        dag, root, _ = publish(broad_fixture())
        index_store = RecordStore(MemoryBytesStore())
        build_index(dag, index_store, root, threshold=50)
        for name in summarized_names(dag, threshold=50):
            members = index_store.get("cone/" + name)
            self.assertEqual(members, sorted(
                item.name for item in dag.get_descendants(name)))
            # I5 as the oracle (dimension-free graph: combined == asserted).
            self.assertEqual(len(members),
                             dag.nodes[name].descendant_count)

    def test_selection_rule_is_the_documented_one(self):
        dag, root, _ = publish(broad_fixture())
        picked = summarized_names(dag, threshold=50)
        self.assertTrue(picked)
        for name, node in dag.nodes.items():
            self.assertEqual(name in picked,
                             name != "*" and node.descendant_count >= 50)

    def test_canonical_index_root_and_untouched_data_root(self):
        puts = broad_fixture()
        dag_a, root_a, _ = publish(puts)
        shuffled = list(puts)
        random.Random(1).shuffle(shuffled)
        # Shuffling put order can orphan supers; publish() creates missing
        # supers implicitly? No — keep it honest: reverse within levels.
        dag_b, root_b, _ = publish(
            puts[:5] + puts[5:45][::-1] + puts[45:][::-1])
        self.assertEqual(root_a, root_b)
        index_a = build_index(dag_a, RecordStore(MemoryBytesStore()), root_a)
        index_b = build_index(dag_b, RecordStore(MemoryBytesStore()), root_b)
        self.assertEqual(index_a, index_b)          # canonical index root
        self.assertEqual(dag_a.commit(), root_a)    # indexing moved nothing


class TestLazyReaderWithIndex(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dag, cls.root, cls.blobs = publish(broad_fixture())
        index_store = RecordStore(MemoryBytesStore())
        cls.index_root = build_index(cls.dag, index_store, cls.root,
                                     threshold=50)
        cls.index_blobs = index_store.blobs

    def _reader(self, **kwargs):
        return LazyOntoDAG(RecordStore.at(self.root, self.blobs), **kwargs)

    def _index(self, data_root=None):
        return ConeIndex(RecordStore.at(self.index_root, self.index_blobs),
                         data_root if data_root is not None else self.root)

    def test_results_identical_with_and_without_index(self):
        for terms in [{"t1", "t2"}, {"t0", "m5"}, {"m3"}, {"t0", "t3", "t4"}]:
            plain = {i.name for i in self._reader().get(terms)}
            indexed = {i.name for i in
                       self._reader(cone_index=self._index()).get(terms)}
            self.assertEqual(plain, indexed, terms)

    def test_fetch_floor_removed(self):
        # The whole point: the narrowest broad cone no longer needs
        # enumerating. Without the index this query costs hundreds of
        # record fetches; with it, single digits plus a couple of index
        # reads.
        plain = self._reader()
        plain.get({"t1", "t2"})
        cone_index = self._index()
        fast = self._reader(cone_index=cone_index)
        fast.get({"t1", "t2"})
        self.assertGreater(plain.fetches, 100)
        self.assertLess(fast.fetches, 10,
                        f"index did not remove the floor: {fast.fetches}")
        self.assertLess(cone_index.fetches, 5)

    def test_stale_index_is_ignored_never_wrong(self):
        stale = self._index(data_root="not-the-root")
        reader = self._reader(cone_index=stale)
        result = {i.name for i in reader.get({"t1", "t2"})}
        self.assertEqual(result,
                         {i.name for i in self._reader().get({"t1", "t2"})})
        self.assertGreater(reader.fetches, 100)   # it walked (exact fallback)

    def test_registry_version_skew_is_ignored_never_wrong(self):
        # Summaries state COMBINED cones, so they pin the arithmetic that
        # produced them: a builder on a different dimensions registry
        # version must not be trusted — walk with our own arithmetic.
        from unittest import mock

        from ontodag import dimensions as dims
        with mock.patch.object(dims, "REGISTRY_VERSION", 999):
            skewed_store = RecordStore(MemoryBytesStore())
            skewed_root = build_index(self.dag, skewed_store, self.root,
                                      threshold=50)
        skewed = ConeIndex(RecordStore.at(skewed_root, skewed_store.blobs),
                           self.root)
        reader = self._reader(cone_index=skewed)
        result = {i.name for i in reader.get({"t1", "t2"})}
        self.assertEqual(result,
                         {i.name for i in self._reader().get({"t1", "t2"})})
        self.assertGreater(reader.fetches, 100)   # walked, exact fallback

    def test_partial_index_is_fine(self):
        # m-categories are below the threshold: misses fall through to the
        # walk, hits still serve the broad terms.
        reader = self._reader(cone_index=self._index())
        result = {i.name for i in reader.get({"t0", "m5"})}
        oracle = {i.name for i in
                  EagerOntoDAG(RecordStore.at(self.root, self.blobs))
                  .get({"t0", "m5"})}
        self.assertEqual(result, oracle)


if __name__ == "__main__":
    unittest.main()
