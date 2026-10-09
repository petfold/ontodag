"""Whole-store operations stay flat per record (review 2026-10-09 §7,
suggestion 5; built 2026-10-10).

Filing and querying have their own per-size tests (`TestFilingDoesNotScan`,
`TestAQueryCostsItsAnswer`); the operations over a whole store had none, and
recordstore's commit took over ten minutes at 11,900 records before anyone
noticed (quadratic: every insertion scanned the placeholders). Here each
operation runs on a store and on one ten times its size, and the time per
record may grow by at most `GROWTH`: a quadratic operation (ten times the
time per record) fails, and a linear one passes with room for a machine
whose time per record grows with the working set. GitHub's runners do: at
four times the size their hydrate grew 2.8 to 3.3 times per record where
this laptop's grew 1.3 (2026-10-10), and the four-to-one budget failed
there one run in two; ten-to-one at five separates the two cases.

- reading a native file the canonical mark does not vouch for (`_restore`,
  every spelling canonicalized, every edge reduced) and one it does
  (`_direct`, built as written);
- committing a store's records into a record store;
- hydrating an eager store from a committed root.

Sizes 1,000 against 10,000 records; `ONTODAG_SLOW_TESTS=1` runs 5,000
against 50,000.
"""

import os
import random
import time
import unittest

from recordstore import MemoryBytesStore, RecordStore

from ontodag import OntoDAG, native, prelude
from ontodag.eager import EagerOntoDAG

SLOW = bool(os.environ.get("ONTODAG_SLOW_TESTS"))
SMALL, LARGE = (5_000, 50_000) if SLOW else (1_000, 10_000)
GROWTH = 5        # allowed growth of the time per record, LARGE against SMALL


def store_text(n, seed=1):
    """A native store as a hand edit or an older release leaves it: the
    prelude, then `n` categories, most under one earlier category, some
    under two, one in ten under a mass in grams (spelled as no release
    stores it). No canonical mark, so loading it canonicalizes."""
    base = OntoDAG()
    prelude.apply(base)
    lines = [line for line in native.dumps(base).splitlines()
             if not line.startswith("#:canonical")]
    rng = random.Random(seed)
    lines.append("c0")
    for i in range(1, n):
        parents = [f"c{rng.randrange(i)}"]
        if i > 10 and rng.random() < 0.2:
            parents.append(f"c{rng.randrange(i)}")
        if rng.random() < 0.1:
            parents.append(f"'mass({i}g)'")
        lines.append(f"c{i} " + " ".join(parents))
    return "\n".join(lines) + "\n"


def best(fn, repeat=2):
    times, out = [], None
    for _ in range(repeat):
        start = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - start)
    return min(times), out


def records(dag):
    return {name: {"up": sorted(p.name for p in node.parents
                                if dag.nodes.get(p.name) is p),
                   "down": sorted(c.name for c in node.neighbors),
                   "count": node.descendant_count, "payload": None, "meta": {}}
            for name, node in dag.nodes.items()}


def commit_all(recs):
    blobs = MemoryBytesStore()
    store = RecordStore(blobs)
    for name, record in recs.items():
        store.put(name, record)
    return store.commit(), blobs


class TestWholeStoreCostIsFlat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {}
        for n in (SMALL, LARGE):
            text = store_text(n)
            t_restore, dag = best(lambda: native.loads(text), repeat=1)
            marked = native.dumps(dag)
            t_direct, _ = best(lambda: native.loads(marked))
            recs = records(dag)
            t_commit, (root, blobs) = best(lambda: commit_all(recs))
            t_hydrate, eager = best(
                lambda: EagerOntoDAG(RecordStore.at(root, blobs)))
            cls.cases[n] = {"restore": t_restore, "direct": t_direct,
                            "commit": t_commit, "hydrate": t_hydrate,
                            "nodes": len(dag.nodes), "hydrated": len(eager.nodes)}

    def assertFlat(self, op):
        small, large = self.cases[SMALL], self.cases[LARGE]
        per_small = small[op] / small["nodes"]
        per_large = large[op] / large["nodes"]
        self.assertLess(per_large, GROWTH * per_small,
                        f"{op}: {per_small * 1e6:.1f} us per record at "
                        f"{small['nodes']}, {per_large * 1e6:.1f} at {large['nodes']}")

    def test_the_stores_are_whole(self):
        for n, case in self.cases.items():
            self.assertGreater(case["nodes"], n)          # the prelude and the values too
            self.assertEqual(case["hydrated"], case["nodes"])

    def test_reading_an_unmarked_file(self):
        self.assertFlat("restore")

    def test_reading_a_marked_file(self):
        self.assertFlat("direct")

    def test_committing_the_records(self):
        self.assertFlat("commit")

    def test_hydrating_from_a_root(self):
        self.assertFlat("hydrate")


if __name__ == "__main__":
    unittest.main()
