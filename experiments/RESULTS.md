# Delta-maintained counts vs. recompute-by-enumeration — results

Branch: `experiment/delta-counts`. Run: `python experiments/delta_counts.py`.
Date: 2026-07-25.

## The question

`_update_descendant_counts` refreshes `descendant_count` by recomputing
`len(get_descendants(X))` for every affected ancestor X. The root is an
ancestor of everything, so its cone is the whole graph: **every write
enumerates the entire DAG.** That cost is the stated reason `SwarmOntoDAG`
hydrates eagerly and `LazyOntoDAG` refuses writes ("exact counts are
properties of the whole graph").

But *which* counts change is local — only the touched node's ancestors; a
non-overlapping cone cannot be affected. So: can counts be maintained
incrementally, touching only the region that actually changed?

## The two rules tested

**ADD p→c.** Ascend from `p` over distinct ancestors. If X already reaches
`c`, it also reaches everything below `c`, so X gains nothing — and every
ancestor of X reaches X, hence also gains nothing → **prune the branch**.
Otherwise X gains `1 + |cone(c) \ reach(X)|`. If `c` is brand new, nothing
could reach it: every distinct ancestor gains exactly 1, **with no probes**.

**DEL p→c.** Apply the removal, then ascend from `p`. If X can still reach
`c` it still reaches all of `cone(c)` → prune. Otherwise X loses
`1 + |cone(c) \ reach_after(X)|`.

Counts are cardinalities, never summed across children (that double-counts
overlap: `Dog(2) + Pet(2) + 2 ≠ Animal(4)`); the stored count is only ever
the previous value to adjust.

## Result 1 — correctness: exact counts do NOT need the whole graph

Both algorithms were compared against a brute-force oracle
(`len(get_descendants(X))` for every X) **after every single operation**,
across 6 configurations (taxonomy and random shapes × ~200/800/2000 items),
plus a randomised fuzz of adds, cross-links and removes — roughly 7,000
operations in total.

**Zero mismatches.** The pruned delta rules are exact.

So `LazyOntoDAG`'s premise is a *cost* claim, not a correctness claim:
exactness survives partial residency. A DAG-wide invariant is maintainable
from local information.

## Result 2 — cost: appends win big and improve with scale; removes lose

Cost unit: node expansions (one pop = one record fetch in a lazy remote
setting). Cycle checks are excluded — both algorithms pay them identically.

Taxonomy shape (bounded depth, ~6 children per node — a realistic ontology):

| items | phase | base/op | delta/op | ratio |
|------:|-------|--------:|---------:|------:|
| 200 | grow (new items) | 192 | 29 | **6.6× cheaper** |
| 800 | grow | 909 | 119 | **7.6× cheaper** |
| 2000 | grow | 2,222 | 261 | **8.5× cheaper** |
| 2000 | cross-link existing | 21,207 | 12,870 | 1.6× cheaper |
| 2000 | remove | 16,946 | 68,368 | **5× worse** |

Random-DAG shape (pathologically large ancestor sets; included as a stress
case, not as a realistic model):

| items | phase | base/op | delta/op | ratio |
|------:|-------|--------:|---------:|------:|
| 2000 | grow | 44,289 | 8,749 | 5.1× cheaper |
| 2000 | cross-link | 189,686 | 129,151 | 1.5× cheaper |
| 2000 | remove | 172,953 | 627,900 | 3.6× worse |

The scaling is the point: **baseline per-op cost grows linearly with graph
size** (192 → 909 → 2,222 as items go 200 → 800 → 2000), exactly as
"enumerate the whole graph per write" predicts, while the delta ratio
*improves* with size (6.6× → 7.6× → 8.5×). Extrapolated to a large shared
ontology, the gap keeps widening.

## Result 3 — why removes lose, and what would fix them

Two causes, both structural rather than fatal:

1. **The baseline amortizes; the per-event delta does not.** `remove()`
   explodes into many edge events (every parent edge, every child edge, then
   the contraction edges). The base class defers to one recompute for the
   whole batch via `_batched_count_updates`; the delta pays a separate ascent
   with probes *per event*. Batching the delta — computing one net effect per
   flush instead of per edge — is the obvious next iteration.
2. **Negative reachability cannot early-exit.** "Can X still reach c?" is
   cheap when the answer is yes (stop at first hit) and worst-case a full
   cone walk when the answer is no — and after a removal, "no" is the common
   case. Cached cone summaries (the succinct-bitmap idea in
   `docs/DATABASE_DIRECTION.md`) would turn this into a bit test:
   `lost = popcount(cone_c & ~reach_after(X))`.

Note also that transitive reduction makes *adds* pay some of this: since
`OntoDAG.add_edge` calls `_remove_unneeded_edges`, an add can generate
removal events internally — which is why delta's grow cost isn't flat.

## Verdict

- Lazy, partially-resident writes are **not blocked by correctness**. The
  exact-count invariant is maintainable locally, proven empirically.
- For **append-mostly** workloads — what a growing shared ontology actually
  is — the delta rule is already a clear win that widens with scale.
- **Removal needs the batched formulation** before a lazy writer should ship;
  as formulated per-event it is several times worse than today's code.
- A pragmatic split follows: a lazy writer could maintain counts by delta on
  appends and fall back to publish-time recomputation after removals.

## Caveats on this experiment

- Cost is counted in node expansions, not wall clock or round trips; a real
  lazy reader would batch fetches, which changes constants but not scaling.
- The delta implementation keeps an in-process shadow of the previous state.
  That is *not* cheating on residency: in production the previous state is
  the previously committed root, itself lazily queryable — but the experiment
  does not prove the fetch pattern against a real store.
- `experiments/` and the `STATS` counters added to `src/ontodag/dag.py` are
  experiment scaffolding. **The instrumentation is not for merge as-is.**
- One harness trap worth remembering: a multi-super `put` can add one edge
  and then raise on a cycle for the next, mutating one DAG but not its twin.
  The harness now decomposes puts into single-super (atomic) puts and asserts
  structural equality after every operation. Before that guard, the resulting
  divergence masqueraded convincingly as a count bug.
