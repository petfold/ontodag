"""Experiment: delta-maintained `descendant_count` vs. recompute-by-enumeration.

Question under test
-------------------
`OntoDAG._update_descendant_counts` refreshes counts by recomputing
`len(get_descendants(X))` for *every* affected ancestor X. Because the root is
an ancestor of everything, the root's cone is the whole graph — so every write
enumerates the entire DAG. That cost is why `SwarmOntoDAG` hydrates eagerly and
why `LazyOntoDAG` refuses writes ("exact counts are properties of the whole
graph").

But *which* counts change is local: only the touched node's ancestors. A
non-overlapping cone (Chemistry, when you file a spaniel under Dog) cannot be
affected. So the answer is local while the method is global. Can counts be
maintained incrementally, touching only the region that actually changed?

Two pruned delta rules, both proved sound by a DAG argument:

  ADD p->c.  newly = {c} + cone(c) in the *before* state (an incoming edge
             cannot change c's own cone). Ascend from p over distinct
             ancestors; each X gains |newly \\ reach_before(X)|. If X gains
             nothing it already reached all of `newly`, and so does every
             ancestor of X (they reach X) -> prune the branch.
             Special case: if c is a brand-new item, nothing could reach it,
             so every distinct ancestor gains exactly |newly| with NO probes.

  DEL p->c.  candidates = {c} + cone(c) before removal. Apply the removal,
             then ascend from p: each X loses those candidates it can no
             longer reach at all. If X lost nothing, neither did its
             ancestors (paths from an ancestor down to X cannot use p->c,
             since X is above p in a DAG) -> prune.

Counts are cardinalities, not sets, so children's counts are never summed
(that double-counts overlap: Dog(2) + Pet(2) + 2 != Animal(4)). The stored
count is only ever used as the previous value to adjust.

What is measured
----------------
* Correctness: after *every* operation, both algorithms' counts are compared
  against a brute-force oracle (`len(get_descendants(X))` for all X).
* Cost: node expansions (one pop = one record fetch in a lazy remote setting).
  Baseline cost = descendant enumeration + affected-set walk. Delta cost =
  ancestor walk + reachability probes. Cycle checks (`_is_reachable`) are
  excluded: both algorithms pay them identically.

Run:  python experiments/delta_counts.py
"""

from __future__ import annotations

import random
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ontodag.dag import STATS, Item, OntoDAG  # noqa: E402


# --------------------------------------------------------------------------
# The delta algorithm
# --------------------------------------------------------------------------

class DeltaCountDAG(OntoDAG):
    """OntoDAG whose counts are maintained by pruned delta propagation.

    Keeps a *shadow* of the graph as of the last flush (children, parents and
    counts, keyed by name). The shadow is the "before" state every delta is
    computed against. In production that state needs no snapshot: it is the
    previously committed root, itself lazily queryable — so nothing here
    requires the whole graph to be resident.
    """

    def __init__(self):
        self._events: list[tuple[str, str, str]] = []
        self._adj: dict[str, set[str]] = {}
        self._radj: dict[str, set[str]] = {}
        self._shadow_counts: dict[str, int] = {}
        super().__init__()
        self._sync_new_names()

    # -- event capture ------------------------------------------------------

    def add_edge(self, from_node, to_node):
        existed = to_node in from_node.neighbors
        super().add_edge(from_node, to_node)
        if not existed and to_node in from_node.neighbors:
            self._events.append(("add", from_node.name, to_node.name))

    def remove_edge(self, from_node, to_node):
        super().remove_edge(from_node, to_node)
        self._events.append(("del", from_node.name, to_node.name))

    # -- flush scheduling (mirrors the base class's batching semantics) ------

    def _update_descendant_counts(self, parent):
        if self._deferred_dirty is not None:
            self._deferred_dirty.add(parent)
            return
        self._flush_delta()

    @contextmanager
    def _batched_count_updates(self):
        if self._deferred_dirty is not None:
            yield
            return
        self._deferred_dirty = set()
        try:
            yield
        finally:
            self._deferred_dirty = None
            self._flush_delta()

    # -- shadow helpers -----------------------------------------------------

    def _sync_new_names(self):
        for name in self.nodes:
            self._adj.setdefault(name, set())
            self._radj.setdefault(name, set())
            self._shadow_counts.setdefault(name, 0)

    def _ensure(self, name):
        self._adj.setdefault(name, set())
        self._radj.setdefault(name, set())
        self._shadow_counts.setdefault(name, 0)

    def _cone(self, name):
        """Descendants of `name` in the shadow state."""
        seen = set()
        frontier = [name]
        while frontier:
            STATS["delta"] += 1
            for child in self._adj.get(frontier.pop(), ()):
                if child not in seen:
                    seen.add(child)
                    frontier.append(child)
        return seen

    def _reaches(self, name, target):
        """Is `target` reachable from `name` in the shadow? Early-exit walk —
        cheap exactly when the answer is yes, which is when pruning fires."""
        seen = set()
        frontier = [name]
        while frontier:
            STATS["delta"] += 1
            for child in self._adj.get(frontier.pop(), ()):
                if child == target:
                    return True
                if child not in seen:
                    seen.add(child)
                    frontier.append(child)
        return False

    def _count_reachable(self, name, targets):
        """How many of `targets` are reachable from `name` in the shadow.

        Walks downward with an early exit as soon as all targets are found —
        the cheap direction when the answer is "already reachable", which is
        exactly when the pruning rule fires.
        """
        found = 0
        remaining = set(targets)
        seen = set()
        frontier = [name]
        while frontier and remaining:
            STATS["delta"] += 1
            for child in self._adj.get(frontier.pop(), ()):
                if child in remaining:
                    remaining.discard(child)
                    found += 1
                    if not remaining:
                        return found
                if child not in seen:
                    seen.add(child)
                    frontier.append(child)
        return found

    # -- the two delta rules ------------------------------------------------

    def _delta_add(self, p, c):
        brand_new = c not in self._adj
        self._ensure(p)
        self._ensure(c)
        cone_c = self._cone(c)             # one expansion when c is a leaf
        fresh = brand_new and not cone_c   # nothing could reach c or below it

        frontier = [p]
        seen = set()
        while frontier:
            x = frontier.pop()
            if x in seen:
                continue
            seen.add(x)
            STATS["delta"] += 1
            if fresh:
                gain = 1                   # no probe at all: c is brand new
            elif self._reaches(x, c):
                continue                   # already reaches c, hence all of cone(c)
            else:
                gain = 1 + len(cone_c) - self._count_reachable(x, cone_c)
            if gain == 0:
                continue                   # prune: ancestors gain nothing either
            self._shadow_counts[x] += gain
            frontier.extend(self._radj.get(x, ()))

        self._adj[p].add(c)
        self._radj[c].add(p)

    def _delta_remove(self, p, c):
        self._ensure(p)
        self._ensure(c)
        cone_c = self._cone(c)             # before the removal

        self._adj[p].discard(c)            # "still reachable?" is a post-state question
        self._radj[c].discard(p)

        frontier = [p]
        seen = set()
        while frontier:
            x = frontier.pop()
            if x in seen:
                continue
            seen.add(x)
            STATS["delta"] += 1
            if self._reaches(x, c):
                continue                   # still reaches c, hence all of cone(c)
            lost = 1 + len(cone_c) - self._count_reachable(x, cone_c)
            if lost == 0:
                continue                   # prune: ancestors lost nothing either
            self._shadow_counts[x] -= lost
            frontier.extend(self._radj.get(x, ()))

    def _flush_delta(self):
        for kind, p, c in self._events:
            if kind == "add":
                self._delta_add(p, c)
            else:
                self._delta_remove(p, c)
        self._events.clear()

        for gone in [n for n in self._adj if n not in self.nodes]:
            self._adj.pop(gone, None)
            self._radj.pop(gone, None)
            self._shadow_counts.pop(gone, None)
        self._sync_new_names()

        for name, node in self.nodes.items():
            node.descendant_count = self._shadow_counts[name]


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------

@contextmanager
def stats_frozen():
    """Run without polluting the counters (used for the oracle)."""
    saved = dict(STATS)
    try:
        yield
    finally:
        STATS.update(saved)


def oracle(dag):
    with stats_frozen():
        return {name: len(dag.get_descendants(node))
                for name, node in dag.nodes.items()}


def counts_of(dag):
    return {name: node.descendant_count for name, node in dag.nodes.items()}


def baseline_cost():
    return STATS["descendants"] + STATS["affected"]


def delta_cost():
    return STATS["delta"]


class Pair:
    """Runs identical operations on both DAGs, checking counts after each."""

    def __init__(self):
        self.base = OntoDAG()
        self.delta = DeltaCountDAG()
        self.failures = []
        self.ops = 0

    @staticmethod
    def _structure(dag):
        return {n: sorted(c.name for c in nd.neighbors)
                for n, nd in dag.nodes.items()}

    def _check(self, label):
        # Guard first: the two DAGs must remain structurally identical. A
        # divergence here is a harness bug (e.g. an operation that mutates one
        # DAG then raises), and would otherwise masquerade as a count error.
        if self._structure(self.base) != self._structure(self.delta):
            self.failures.append((label, "STRUCTURAL DIVERGENCE (harness bug)", {}))
            raise AssertionError(f"structures diverged at: {label}")
        truth = oracle(self.base)
        for name, dag in (("baseline", self.base), ("delta", self.delta)):
            got = counts_of(dag)
            if got != truth:
                wrong = {k: (got.get(k), truth.get(k))
                         for k in set(got) | set(truth) if got.get(k) != truth.get(k)}
                self.failures.append((label, name, wrong))

    def put(self, sub, supers):
        """Apply to both DAGs. Multi-super puts are decomposed into
        single-super puts: one put == one add_edge, which rejects a cycle
        *before* mutating, so either both DAGs change or neither does. A
        multi-super put can add edge 1 and then raise on edge 2, leaving the
        two DAGs in different states."""
        for sup in supers:
            raised = []
            for dag in (self.base, self.delta):
                try:
                    dag.put(Item(sub), [dag.nodes[sup]])
                    raised.append(None)
                except ValueError as e:
                    raised.append(str(e))
            assert (raised[0] is None) == (raised[1] is None), \
                f"asymmetric failure putting {sub} under {sup}: {raised}"
        self.ops += 1
        self._check(f"put {sub} under {supers}")

    def remove(self, name):
        for dag in (self.base, self.delta):
            dag.remove(name)
        self.ops += 1
        self._check(f"remove {name}")

    def names(self, exclude_root=True):
        out = [n for n in self.base.nodes]
        return [n for n in out if n != self.base.root.name] if exclude_root else out


def measure(fn, *args):
    """(baseline expansions, delta expansions) for one phase."""
    b0, d0 = baseline_cost(), delta_cost()
    fn(*args)
    return baseline_cost() - b0, delta_cost() - d0


def scenario_grow(pair, n, rng, width=3):
    """Append n brand-new items under existing supers — the dominant case."""
    for i in range(n):
        pool = pair.names() or [pair.base.root.name]
        supers = rng.sample(pool, min(len(pool), rng.randint(1, width)))
        pair.put(f"n{i}", supers)


def scenario_taxonomy(pair, n, rng, branching=6, extra_parent_p=0.25):
    """Append items in a *taxonomy* shape: bounded depth, each new item under
    one (sometimes two) items from the previous level. Random DAGs give every
    node hundreds of ancestors, which is nothing like a category graph — the
    design docs note ancestor chains stay short even in huge graphs, and the
    ancestor set is exactly what the delta rule pays for."""
    levels = [[pair.base.root.name]]
    i = 0
    while i < n:
        prev = levels[-1]
        level = []
        for parent in prev:
            for _ in range(branching):
                if i >= n:
                    break
                supers = [parent]
                if len(prev) > 1 and rng.random() < extra_parent_p:
                    other = rng.choice([x for x in prev if x != parent])
                    supers.append(other)
                name = f"t{i}"
                pair.put(name, supers)
                level.append(name)
                i += 1
        if not level:
            break
        levels.append(level)


def scenario_crosslink(pair, n, rng):
    """Re-put existing items under additional existing supers."""
    for _ in range(n):
        pool = pair.names()
        if len(pool) < 4:
            return
        child = rng.choice(pool)
        supers = rng.sample(pool, 2)
        if child in supers:
            continue
        pair.put(child, supers)  # per-edge cycle refusals are symmetric


def scenario_remove(pair, n, rng):
    for _ in range(n):
        pool = pair.names()
        if not pool:
            return
        pair.remove(rng.choice(pool))


def report(title, rows, ops, failures):
    print(f"\n{title}")
    print("-" * len(title))
    print(f"{'phase':<22}{'ops':>6}{'baseline':>12}{'delta':>11}{'ratio':>8}"
          f"{'base/op':>10}{'delta/op':>10}")
    for phase, o, b, d in rows:
        ratio = f"{b / d:.1f}x" if d else "—"
        print(f"{phase:<22}{o:>6}{b:>12,}{d:>11,}{ratio:>8}"
              f"{b // max(o, 1):>10,}{d // max(o, 1):>10,}")
    tb = sum(r[2] for r in rows)
    td = sum(r[3] for r in rows)
    print(f"{'TOTAL':<22}{ops:>6}{tb:>12,}{td:>11,}"
          f"{(f'{tb / td:.1f}x' if td else '—'):>8}")
    print(f"correctness: {'OK — counts identical to oracle after every op' if not failures else f'{len(failures)} MISMATCHES'}")
    for f in failures[:5]:
        print(f"  {f}")


def run(size, seed=7, shape="random"):
    rng = random.Random(seed)
    pair = Pair()
    rows = []

    grow = scenario_grow if shape == "random" else scenario_taxonomy
    before = pair.ops
    b, d = measure(grow, pair, size, rng)
    rows.append((f"grow ({shape})", pair.ops - before, b, d))

    before = pair.ops
    b, d = measure(scenario_crosslink, pair, max(10, size // 10), rng)
    rows.append(("cross-link existing", pair.ops - before, b, d))

    before = pair.ops
    b, d = measure(scenario_remove, pair, max(10, size // 10), rng)
    rows.append(("remove", pair.ops - before, b, d))

    report(f"{shape} shape, ~{size} items (seed {seed})", rows, pair.ops, pair.failures)
    return pair.failures, rows


def fuzz(rounds=400, seed=11):
    """Randomised mix; correctness only."""
    rng = random.Random(seed)
    pair = Pair()
    for i in range(rounds):
        roll = rng.random()
        pool = pair.names()
        if roll < 0.6 or len(pool) < 4:
            pool2 = pair.names() or [pair.base.root.name]
            supers = rng.sample(pool2, min(len(pool2), rng.randint(1, 3)))
            pair.put(f"f{i}", supers)
        elif roll < 0.8:
            child = rng.choice(pool)
            supers = rng.sample(pool, 2)
            if child not in supers:
                pair.put(child, supers)
        else:
            pair.remove(rng.choice(pool))
    print(f"\nfuzz: {pair.ops} ops, "
          f"{'OK — no mismatches' if not pair.failures else f'{len(pair.failures)} MISMATCHES'}")
    for f in pair.failures[:5]:
        print(f"  {f}")
    return pair.failures


if __name__ == "__main__":
    all_failures = []
    for shape in ("taxonomy", "random"):
        for size in (200, 800, 2000):
            STATS.update({k: 0 for k in STATS})
            failures, _ = run(size, shape=shape)
            all_failures += failures
    all_failures += fuzz()
    print()
    sys.exit(1 if all_failures else 0)
