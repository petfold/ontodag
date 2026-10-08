"""The performance probes behind docs/plans/REVIEW_2026-10.md §6.

Run from the repository root: ``python3 experiments/review_2026_10_perf.py
[probe ...]``. With no argument every probe runs (about two minutes; the
native-load and CLI rows dominate). Probes: startup, union, persistence,
filing, relations, graph.

Numbers are wall-clock times on whatever machine runs this; the review's
were taken on an i7-3612QM laptop with 8 GB. The persistence probe's commit
row needs recordstore 0.22.2 or later: 0.22.1 commits a store this size in
more than ten minutes.
"""
import os
import random
import subprocess
import sys
import tempfile
import time
import tracemalloc

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, SRC)

from ontodag import native, packs, prelude  # noqa: E402
from ontodag.dag import OntoDAG  # noqa: E402

DOMAINS = ["physics", "mathematics", "chemistry", "biology", "medicine", "ai",
           "economics", "computing", "geography", "space"]


def timed(label, fn, repeat=1):
    best = out = None
    for _ in range(repeat):
        t = time.perf_counter()
        out = fn()
        dt = time.perf_counter() - t
        best = dt if best is None else min(best, dt)
    print(f"{label:58} {best * 1000:9.1f} ms")
    return out


def _env():
    env = dict(os.environ)
    env["ONTODAG_HOME"] = tempfile.mkdtemp(prefix="od-perf-")
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _odag(*args, env):
    return subprocess.run([sys.executable, "-m", "ontodag", *args], env=env,
                          check=True, capture_output=True)


def union():
    """Core plus all ten domain packs, merged one by one."""
    dag = OntoDAG()
    prelude.apply(dag)
    for name in ["core", *DOMAINS]:
        dag.merge(packs.adoption_dag(dag, name))
    return dag


def probe_startup():
    env = _env()
    timed("python -c 'import ontodag'", lambda: subprocess.run(
        [sys.executable, "-c", "import ontodag"], env=env, check=True), repeat=5)
    timed("odag help (CLI start-up)", lambda: _odag("help", env=env), repeat=5)


def probe_union():
    env = _env()
    dag = timed("build core + 10 domain packs (merge each)", union)
    # Memory from a second, traced build: tracing slows allocation about
    # fourfold, so the build above is timed untraced.
    tracemalloc.start()
    union()
    current, _peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    n = len(dag.nodes)
    edges = sum(len(x.neighbors) for x in dag.nodes.values())
    print(f"{'  nodes / edges / traced memory':58} {n} / {edges} / "
          f"{current / 1e6:.1f} MB ({current / n / 1e3:.1f} KB per node)")
    path = os.path.join(env["ONTODAG_HOME"], "union.od")
    timed("native save", lambda: native.save(dag, path))
    loaded = timed("native load (in process)", lambda: native.load(path))
    assert len(loaded.nodes) == n
    timed("odag -f union.od count (whole CLI call)",
          lambda: _odag("-f", path, "count", env=env))
    for q in (["artifact", "device"], ["organism"], ["disease", "infection"],
              ["planet"], []):
        timed(f"get {q}", lambda q=q: dag.get(q), repeat=3)
    timed("is_below('aspirin', 'substance')",
          lambda: dag.is_below("aspirin", "substance"), repeat=3)
    timed("put a new item under 3 categories", lambda: dag.put(
        f"item-{time.perf_counter_ns()}", ["artifact", "device", "tool"]), repeat=3)
    return dag


def probe_persistence(dag=None):
    from recordstore import MemoryBytesStore, RecordStore

    from ontodag.eager import EagerOntoDAG
    from ontodag.lazy import LazyOntoDAG
    dag = dag or union()
    blobs = MemoryBytesStore()
    eager = EagerOntoDAG(RecordStore(blobs))
    timed("EagerOntoDAG: merge the union", lambda: eager.merge(dag))
    root = timed("EagerOntoDAG: commit (memory)", eager.commit)
    timed("EagerOntoDAG: hydrate the committed root",
          lambda: EagerOntoDAG(RecordStore.at(root, blobs)))

    def lazy_query():
        reader = LazyOntoDAG(RecordStore.at(root, blobs))
        reader.get(["planet"])
        return reader.fetches
    fetches = timed("LazyOntoDAG: a fresh reader answers get planet", lazy_query)
    print(f"{'  record fetches':58} {fetches}")


def probe_filing():
    d = OntoDAG()
    d.put("bulk", [])
    for k in range(20000):
        d.put(f"item{k}", ["bulk"])
    times = []
    for k in range(5):
        d.put(f"cat{k}", [])
        t = time.perf_counter()
        d.put("bulk", [f"cat{k}"])
        times.append(time.perf_counter() - t)
    print(f"{'file a 20,000-item category under a new parent (best of 5)':58} "
          f"{min(times) * 1000:9.1f} ms")


def probe_relations():
    for n in (200, 800, 3200):
        rng = random.Random(2)
        d = OntoDAG()
        prelude.apply(d)
        people = [f"p{i}" for i in range(n)]
        places = [f"pl{i}" for i in range(n)]
        d.put("person", [])
        d.put("place", [])
        for p in people:
            d.put(p, ["person"])
        for i, pl in enumerate(places):
            d.put(pl, ["place"] if i == 0 else [f"in({places[rng.randrange(i)]})"])
        times = []
        for k in range(600):
            shape = rng.random()
            if shape < 0.4:
                sup = [f"shared-with({rng.choice(people)})"]
            elif shape < 0.8:
                sup = [f"in({rng.choice(places)})"]
            else:
                sup = [f"shared-with({' '.join(rng.sample(people, 2))})"]
            t = time.perf_counter()
            d.put(f"doc{k}", sup)
            times.append(time.perf_counter() - t)
        print(f"{f'relation-kind filing, {n} people and places':58} "
              f"{sum(times[-300:]) / 300 * 1000:9.2f} ms per put")


def probe_graph():
    for n in (400, 1600, 6400):
        rng = random.Random(1)
        d = OntoDAG()
        prelude.apply(d)
        d.put("graph-dimension", ["dimension"])
        d.put("transport", ["graph-dimension"])
        cats = [f"c{i}" for i in range(40)]
        for c in cats:
            d.put(c, [])
        for k in range(n):
            a, b = rng.sample(cats, 2)
            shape = rng.random()
            term = (f"transport({a} mass(..{rng.randint(1, 60)}kg))" if shape < 0.5 else
                    f"transport({a} {b})" if shape < 0.8 else
                    f"transport(mass({rng.randint(1, 60)}kg..{rng.randint(61, 90)}kg))")
            d.put(f"offer{k}", [term, f"c{rng.randrange(40)}"])
        timed(f"compound graph-kind query over {n} offers",
              lambda: d.get(["transport(c0 mass(..30kg))"], items_only=True))


PROBES = {"startup": probe_startup, "union": probe_union,
          "persistence": probe_persistence, "filing": probe_filing,
          "relations": probe_relations, "graph": probe_graph}


def main(argv):
    chosen = argv or list(PROBES)
    unknown = [a for a in chosen if a not in PROBES]
    if unknown:
        raise SystemExit(f"unknown probe(s) {unknown}; choose from {list(PROBES)}")
    dag = None
    for name in chosen:
        print(f"== {name}")
        if name == "persistence":
            probe_persistence(dag)
        elif name == "union":
            dag = probe_union()
        else:
            PROBES[name]()


if __name__ == "__main__":
    main(sys.argv[1:])
