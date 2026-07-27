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
non-overlapping cone cannot be affected. So the answer is local while the
method is global. Can counts be maintained incrementally?

## Three algorithms compared

**baseline** — today's code: recompute `len(get_descendants(X))` for every
affected ancestor.

**edge-delta** — replay the operation's *edge events*, applying two pruned
rules. ADD p→c: ascend from p; if X already reaches c it also reaches
everything below c, so it gains nothing — and so does every ancestor of X
→ prune. Otherwise X gains `1 + |cone(c) \ reach(X)|`; a brand-new c means
every ancestor gains exactly 1 with no probes. DEL p→c: mirror, using
"can X still reach c?".

**op-delta** — exploit what each *operation* means instead of replaying its
edges:

1. **Redundancy removals cost nothing.** `_remove_unneeded_edges` deletes an
   edge only because its target is already reachable another way — that is
   what transitive reduction *is* — so no count changes.
2. **`remove(n)` costs one subtraction per ancestor.** Contraction reconnects
   n's children to n's parents, so nothing below n becomes unreachable: every
   ancestor of n loses exactly `n` itself. No probes, no cone walks.
3. **Genuine new edges** use the ADD rule above.

## Result 1 — correctness: exact counts do NOT need the whole graph

All three algorithms were compared against a brute-force oracle
(`len(get_descendants(X))` for every X) **after every single operation**,
across 6 configurations (taxonomy and random shapes × ~200/800/2000 items)
plus a randomised fuzz of adds, cross-links and removes — roughly 7,600
operations. **Zero mismatches** for both delta variants.

So `LazyOntoDAG`'s premise is a *cost* claim, not a correctness claim:
exactness survives partial residency. A DAG-wide invariant is maintainable
from local information.

## Result 2 — cost: op-delta wins everywhere, removes spectacularly

Cost unit: node expansions (one pop ≈ one record fetch in a lazy remote
setting), per operation. Cycle checks are excluded — all three pay them
identically.

Taxonomy shape (bounded depth, ~6 children per node):

| items | phase | base/op | edge-δ/op | op-δ/op | op-δ vs base |
|------:|-------|--------:|----------:|--------:|-------------:|
| 200 | grow | 192 | 26 | 26 | **7.2× cheaper** |
| 200 | cross-link | 645 | 492 | 399 | 1.6× |
| 200 | remove | 347 | 676 | **5** | **62×** |
| 800 | grow | 909 | 128 | 128 | **7.1×** |
| 800 | cross-link | 4,247 | 2,989 | 2,748 | 1.5× |
| 800 | remove | 2,015 | 8,062 | **8** | **231×** |
| 2000 | grow | 2,222 | 248 | 248 | **8.9×** |
| 2000 | cross-link | 21,207 | 12,823 | 11,005 | 1.9× |
| 2000 | remove | 16,946 | 67,612 | **26** | **642×** |
| 2000 | *all phases* | 5,031 | 6,910 | 1,126 | **4.5×** |

Random-DAG shape (pathologically dense ancestor sets; a stress case, not a
realistic model) at 2000 items: grow 5.3×, cross-link 1.8×, remove **927×**,
overall 4.2× cheaper than baseline.

Two things to read out of the table:

* **Scaling.** Baseline per-op cost grows linearly with graph size
  (192 → 909 → 2,222 for grow; 347 → 2,015 → 16,946 for remove), exactly as
  "enumerate the whole graph per write" predicts. op-delta's remove cost is
  near-constant (5 → 8 → 26 — it is just the ancestor-set size), so the gap
  *widens without limit* as the ontology grows.
* **Removal flipped from worst to best.** Edge-delta made removes 3–5×
  *worse* than baseline; op-delta makes them 62–927× *better*. The 5× loss
  was never a property of delta maintenance — it came from decomposing a
  structured operation into unstructured edge events, which destroys the
  information that makes it cheap.

## Result 3 — cross-links are the remaining weak spot

Adding an edge between two *existing* nodes genuinely changes reachability in
ways no operation-level shortcut captures, so it still pays the probes:
only 1.5–1.9× better than baseline, and it dominates op-delta's mixed-workload
total. This is precisely where the cached cone summaries (succinct bitmaps)
sketched in `docs/DATABASE_DIRECTION.md` would pay off — turning
"can X reach n?" into a bit test:
`gain = popcount(cone_c & ~reach(X))`.

## Two bugs worth remembering

**Redundancy removals are count-neutral per *operation*, not per *edge*.**
`_remove_unneeded_edges` runs *before* the new edge is added, so mid-operation
an ancestor really does lose reachability, which the new edge then restores.
Applying those removals to the shadow immediately corrupted the ADD rule's
"before" state: an ancestor that reached `c` only through a just-removed
redundant edge looked like it was newly gaining `c`, and counts drifted
upward. Fix: queue count-neutral structural changes and land them only after
every count delta has been computed.

**A harness trap that masqueraded as an algorithm bug.** A multi-super `put`
can add edge 1 and then raise on a cycle for edge 2, mutating one DAG but not
its twin. The first run reported hundreds of "count mismatches" that were
purely this divergence. The harness now decomposes puts into single-super
(atomic) puts and asserts structural equality across all three DAGs after
every operation — without that guard, a harness bug is indistinguishable from
an algorithm bug.

## Verdict

- Lazy, partially-resident writes are **not blocked by correctness**. The
  exact-count invariant is maintainable locally, verified empirically.
- **Appends and removals are both cheap** under op-delta, and the advantage
  grows with graph size — appends 7–9×, removals 62–927×.
- **Cross-links remain the expensive case** (still ~1.7× better than today).
  Cone-summary bitmaps are the next lever if that matters.
- A lazy writer is therefore viable now for append-and-remove workloads,
  which is what a growing shared ontology mostly does.

## Caveats

- Cost is node expansions, not wall clock or round trips; a real lazy reader
  would batch fetches, changing constants but not scaling.
- The delta classes keep an in-process shadow of the previous state. That is
  not cheating on residency — in production the previous state is the
  previously committed root, itself lazily queryable — but this experiment
  does not prove the fetch pattern against a real store.
- The random-shape generator produces far denser ancestor sets than any real
  taxonomy; treat those rows as a stress bound, not a forecast.
- `experiments/` and the `STATS` counters added to `src/ontodag/dag.py` are
  scaffolding. **The instrumentation is not for merge as-is.**
