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

from ontodag.dag import STATS, Item, OntoDAG, _name_of  # noqa: E402

STATS.setdefault("opdelta", 0)


# --------------------------------------------------------------------------
# The delta algorithm
# --------------------------------------------------------------------------

class DeltaCountDAG(OntoDAG):
    _stats_key = "delta"

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
            STATS[self._stats_key] += 1
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
            STATS[self._stats_key] += 1
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
            STATS[self._stats_key] += 1
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
            STATS[self._stats_key] += 1
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
            STATS[self._stats_key] += 1
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
        deferred = getattr(self, "_deferred_shadow", None)
        if deferred:
            self._apply_deferred()

        self._write_back()

    def _write_back(self):
        for gone in [n for n in self._adj if n not in self.nodes]:
            self._adj.pop(gone, None)
            self._radj.pop(gone, None)
            self._shadow_counts.pop(gone, None)
        self._sync_new_names()
        for name, node in self.nodes.items():
            node.descendant_count = self._shadow_counts[name]


class OpDeltaDAG(DeltaCountDAG):
    """Counts maintained from what each *operation* means, not from its edges.

    Three rules, exploiting structure the edge-event log throws away:

    1. **Redundancy removals cost nothing.** `_remove_unneeded_edges` deletes
       an edge only because its target is already reachable another way — that
       is what transitive reduction *is* — so reachability, and therefore every
       count, is unchanged. Do the structural work, record no count change.
    2. **`remove(n)` costs one subtraction per ancestor.** Contraction
       reconnects n's children to n's parents, so nothing below n becomes
       unreachable: every ancestor of n loses exactly `n` itself. No probes,
       no cone walks — cost is |ancestors(n)|.
    3. **Genuine new edges** use the ADD rule inherited from `DeltaCountDAG`.
    """

    _stats_key = "opdelta"

    def __init__(self):
        self._suppress = False
        self._deferred_shadow = []
        super().__init__()

    # -- structural bookkeeping that must happen even when counts don't ------

    def _shadow_add(self, p, c):
        self._ensure(p)
        self._ensure(c)
        self._adj[p].add(c)
        self._radj[c].add(p)

    def _shadow_del(self, p, c):
        self._ensure(p)
        self._ensure(c)
        self._adj[p].discard(c)
        self._radj[c].discard(p)

    def _apply_deferred(self):
        """Land the count-neutral structural changes (redundancy removals,
        contraction edges) once every count delta has been computed against
        the untouched pre-operation shadow."""
        for kind, p, c in self._deferred_shadow:
            if kind == "add":
                self._shadow_add(p, c)
            else:
                self._shadow_del(p, c)
        self._deferred_shadow.clear()

    def _shadow_ancestors(self, name):
        """Distinct strict ancestors of `name` in the shadow."""
        seen = set()
        frontier = [name]
        while frontier:
            STATS[self._stats_key] += 1
            for parent in self._radj.get(frontier.pop(), ()):
                if parent not in seen:
                    seen.add(parent)
                    frontier.append(parent)
        return seen

    # -- rule 1: redundancy removals are count-neutral ----------------------

    def _remove_unneeded_edges(self, from_node, to_node):
        prev, self._suppress = self._suppress, True
        try:
            super()._remove_unneeded_edges(from_node, to_node)
        finally:
            self._suppress = prev

    # -- event capture, honouring suppression -------------------------------

    def add_edge(self, from_node, to_node):
        existed = to_node in from_node.neighbors
        OntoDAG.add_edge(self, from_node, to_node)
        if existed or to_node not in from_node.neighbors:
            return
        if self._suppress:
            self._deferred_shadow.append(("add", from_node.name, to_node.name))
        else:
            self._events.append(("add", from_node.name, to_node.name))

    def remove_edge(self, from_node, to_node):
        OntoDAG.remove_edge(self, from_node, to_node)
        if self._suppress:
            self._deferred_shadow.append(("del", from_node.name, to_node.name))
        else:
            self._events.append(("del", from_node.name, to_node.name))

    # -- rule 2: remove(n) == one subtraction per ancestor ------------------

    def remove(self, node_to_remove):
        name = _name_of(node_to_remove)
        if name not in self.nodes or name == self.root.name:
            return super().remove(node_to_remove)   # let the base class raise
        ancestors = self._shadow_ancestors(name)
        prev, self._suppress = self._suppress, True
        try:
            super().remove(node_to_remove)
        finally:
            self._suppress = prev
        for a in ancestors:
            self._shadow_counts[a] -= 1
        self._apply_deferred()
        self._write_back()


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


def opdelta_cost():
    return STATS["opdelta"]


class Pair:
    """Runs identical operations on both DAGs, checking counts after each."""

    def __init__(self):
        self.base = OntoDAG()
        self.delta = DeltaCountDAG()
        self.opdelta = OpDeltaDAG()
        self.failures = []
        self.ops = 0

    @property
    def dags(self):
        return (("baseline", self.base), ("edge-delta", self.delta),
                ("op-delta", self.opdelta))

    @staticmethod
    def _structure(dag):
        return {n: sorted(c.name for c in nd.neighbors)
                for n, nd in dag.nodes.items()}

    def _check(self, label):
        # Guard first: the two DAGs must remain structurally identical. A
        # divergence here is a harness bug (e.g. an operation that mutates one
        # DAG then raises), and would otherwise masquerade as a count error.
        shape = self._structure(self.base)
        for name, dag in self.dags[1:]:
            if self._structure(dag) != shape:
                self.failures.append((label, f"STRUCTURAL DIVERGENCE in {name}", {}))
                raise AssertionError(f"{name} structure diverged at: {label}")
        truth = oracle(self.base)
        for name, dag in self.dags:
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
            for _, dag in self.dags:
                try:
                    dag.put(Item(sub), [dag.nodes[sup]])
                    raised.append(None)
                except ValueError as e:
                    raised.append(str(e))
            assert len({r is None for r in raised}) == 1, \
                f"asymmetric failure putting {sub} under {sup}: {raised}"
        self.ops += 1
        self._check(f"put {sub} under {supers}")

    def remove(self, name):
        for _, dag in self.dags:
            dag.remove(name)
        self.ops += 1
        self._check(f"remove {name}")

    def names(self, exclude_root=True):
        out = [n for n in self.base.nodes]
        return [n for n in out if n != self.base.root.name] if exclude_root else out


def measure(fn, *args):
    """(baseline, edge-delta, op-delta) expansions for one phase."""
    b0, d0, o0 = baseline_cost(), delta_cost(), opdelta_cost()
    fn(*args)
    return (baseline_cost() - b0, delta_cost() - d0, opdelta_cost() - o0)


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
    print(f"{'phase':<20}{'ops':>5}{'base/op':>10}{'edge-δ/op':>11}"
          f"{'op-δ/op':>10}{'edge-δ':>9}{'op-δ':>9}")
    for phase, o, b, d, x in rows:
        n = max(o, 1)
        rd = f"{b / d:.1f}x" if d else "—"
        rx = f"{b / x:.1f}x" if x else "—"
        print(f"{phase:<20}{o:>5}{b // n:>10,}{d // n:>11,}{x // n:>10,}"
              f"{rd:>9}{rx:>9}")
    tb, td, tx = (sum(r[i] for r in rows) for i in (2, 3, 4))
    n = max(ops, 1)
    print(f"{'TOTAL':<20}{ops:>5}{tb // n:>10,}{td // n:>11,}{tx // n:>10,}"
          f"{(f'{tb / td:.1f}x' if td else '—'):>9}"
          f"{(f'{tb / tx:.1f}x' if tx else '—'):>9}")
    print(f"correctness: {'OK — counts identical to oracle after every op' if not failures else f'{len(failures)} MISMATCHES'}")
    for f in failures[:5]:
        print(f"  {f}")


def run(size, seed=7, shape="random"):
    rng = random.Random(seed)
    pair = Pair()
    rows = []

    grow = scenario_grow if shape == "random" else scenario_taxonomy
    before = pair.ops
    costs = measure(grow, pair, size, rng)
    rows.append((f"grow ({shape})", pair.ops - before, *costs))

    before = pair.ops
    costs = measure(scenario_crosslink, pair, max(10, size // 10), rng)
    rows.append(("cross-link existing", pair.ops - before, *costs))

    before = pair.ops
    costs = measure(scenario_remove, pair, max(10, size // 10), rng)
    rows.append(("remove", pair.ops - before, *costs))

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
