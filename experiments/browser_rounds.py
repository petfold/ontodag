"""How many *sequential network round trips* does a lazy browser query need?

Fetch counts are the wrong number for a browser: fetches that can be issued
together cost one round trip, and only sequential dependencies cost more.
This measures rounds directly, by the miss-and-replay scheme:

    cache = {}                      # immutable blobs, content-addressed
    while True:
        try:    answer = query()    # pure sync, over the cache
        except Missing as m:        # a blob the cache does not have
            await fetch(m.refs)     # ONE round trip, however many refs
            continue

Every replay is free (in-memory work over immutable data); only the awaits
cost latency. So `rounds` is the number that decides whether this works in a
browser without JSPI or a cross-origin-isolated worker.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from recordstore import MemoryBytesStore, RecordStore
from ontodag.eager import EagerOntoDAG
from ontodag.lazy import LazyOntoDAG
from ontodag.cones import build_index, ConeIndex


class Missing(Exception):
    def __init__(self, refs, origin):
        self.refs = refs
        self.origin = origin


class ReplayStore:
    """A BytesStore that never blocks: it serves the cache or raises."""

    def __init__(self, origin, cache):
        self.origin = origin           # stands in for the Swarm node
        self.cache = cache
        self.wanted = set()

    def get(self, ref):
        if ref in self.cache:
            return self.cache[ref]
        self.wanted.add(ref)
        raise Missing({ref}, self.origin)

    def put(self, data):               # read-only client
        raise NotImplementedError


class BatchedLazy(LazyOntoDAG):
    """LazyOntoDAG with level-order traversal: expand the whole frontier at
    once, so one round trip serves a level instead of a node.

    This models the change `lazy.py` would need — `_expand_many` already
    exists as the seam and nothing calls it. Misses across a level are
    collected and raised together, which is what lets the replay loop fetch
    them in a single await.
    """

    def _expand_many(self, nodes):
        missing, done = set(), []
        for node in nodes:
            try:
                done.append(self._expand(node))
            except Missing as miss:
                missing |= miss.refs
                origin = miss.origin
        if missing:
            raise Missing(missing, origin)
        return done

    def get_descendants(self, node, computed=True):
        name = node if isinstance(node, str) else node.name
        start = self._stub(self._canonical_name(name))
        if computed and self._cone_cache is not None \
                and start.name in self._cone_cache:
            return set(self._cone_cache[start.name])
        if computed and self._cone_index is not None:
            members = self._cone_index.cone(start.name)
            if members is not None:
                cone = {self._stub(m) for m in members}
                self._cache_cone(start.name, cone)
                return cone
        descendants, seen, frontier = set(), {start}, [start]
        while frontier:
            level = self._expand_many(frontier)      # ONE round per level
            frontier = []
            for current in level:
                successors = list(current.neighbors)
                if computed:
                    successors.extend(self._computed_children(current))
                for child in successors:
                    descendants.add(child)
                    if child not in seen:
                        seen.add(child)
                        frontier.append(child)
        if computed:
            self._cache_cone(start.name, descendants)
        return descendants


def rounds_for(origin_blobs, root, run, index_pair=None, cls=LazyOntoDAG):
    """Run `run(dag)` under miss-and-replay; return (rounds, blobs fetched)."""
    cache, total, rounds = {}, 0, 0
    while True:
        store = ReplayStore(origin_blobs, cache)
        try:
            data = RecordStore.at(root, store)
            index = None
            if index_pair:
                index_root, index_blobs = index_pair
                index = ConeIndex(RecordStore.at(index_root,
                                                 ReplayStore(index_blobs, cache)),
                                  root)
            dag = cls(data, cone_index=index)
            run(dag)
            return rounds, total
        except Missing as miss:
            # one await, however many refs were wanted in this pass
            for ref in miss.refs:
                cache[ref] = miss.origin.get(ref)
                total += 1
            rounds += 1
            if rounds > 5000:
                raise RuntimeError("not converging")


def build(n_top, n_mid, n_leaf):
    blobs = MemoryBytesStore()
    store = RecordStore(blobs)
    dag = EagerOntoDAG(store)
    tops = [f"top{i}" for i in range(n_top)]
    for t in tops:
        dag.put(t, [])
    mids = []
    for i in range(n_mid):
        name = f"mid{i}"
        dag.put(name, [tops[i % n_top]])
        mids.append(name)
    for i in range(n_leaf):
        dag.put(f"leaf{i}", [mids[i % n_mid], mids[(i * 7 + 3) % n_mid]])
    return dag.commit(), blobs, dag


if __name__ == "__main__":
    root, blobs, eager_dag = build(20, 200, 3000)
    print(f"store: {len(eager_dag.nodes)} nodes\n")

    index_blobs = MemoryBytesStore()
    index_root = build_index(eager_dag, RecordStore(index_blobs), root,
                             threshold=64)

    print(f"  {'query':26} {'plain':>5} {'+index':>8} "
          f"{'+batching':>10} {'both':>9}")
    for label, query in (
        ("one specific term (leaf5)", ["mid5"]),
        ("two mid terms", ["mid5", "mid12"]),
        ("one broad term (top0)", ["top0"]),
        ("two broad terms", ["top0", "top1"]),
    ):
        r, _ = rounds_for(blobs, root, lambda d: d.get(query))
        ri, _ = rounds_for(blobs, root, lambda d: d.get(query),
                           index_pair=(index_root, index_blobs))
        b, _ = rounds_for(blobs, root, lambda d: d.get(query),
                          cls=BatchedLazy)
        bi, _ = rounds_for(blobs, root, lambda d: d.get(query),
                           index_pair=(index_root, index_blobs),
                           cls=BatchedLazy)
        print(f"  {label:26} {r:5} {ri:8} {b:10} {bi:9}")

    # Record-level view: LazyOntoDAG counts its own store.get calls, and
    # those are the batchable unit — a frontier of N names is N independent
    # key lookups that a get_many can issue together.
    print("\n  record-level (what batching would collapse rounds toward):")
    from recordstore import RecordStore as RS
    for label, query in (
        ("one specific term", ["mid5"]),
        ("two mid terms", ["mid5", "mid12"]),
        ("one broad term", ["top0"]),
        ("two broad terms", ["top0", "top1"]),
    ):
        plain = LazyOntoDAG(RS.at(root, blobs))
        plain.get(query)
        idx = ConeIndex(RS.at(index_root, index_blobs), root)
        withidx = LazyOntoDAG(RS.at(root, blobs), cone_index=idx)
        withidx.get(query)
        print(f"    {label:22} {plain.fetches:5} records"
              f"     with cone index: {withidx.fetches:4} records")

    # A session, not a cold query. A browser keeps its blob cache across
    # queries, and blobs are immutable, so the cost that matters is the
    # marginal one — what the *second* and later questions cost.
    print("\n  a session of six queries, one shared cache (both features):")
    cache = {}
    session = [["mid5"], ["top0"], ["mid5", "mid12"], ["top0", "top1"],
               ["mid7"], ["top3"]]
    for i, query in enumerate(session, 1):
        rounds = 0
        while True:
            store = ReplayStore(blobs, cache)
            try:
                idx = ConeIndex(RS.at(index_root,
                                      ReplayStore(index_blobs, cache)), root)
                dag = BatchedLazy(RS.at(root, store), cone_index=idx)
                dag.get(query)
                break
            except Missing as miss:
                for ref in miss.refs:
                    cache[ref] = miss.origin.get(ref)
                rounds += 1
        print(f"    query {i} {str(query):22} {rounds:3} rounds "
              f"(cache now {len(cache)} blobs)")
