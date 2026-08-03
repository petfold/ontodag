# Semantic codes: a binary index for OntoDAG (design note)

Status: **design note, parked 2026-07-20 — one §8 gate has since opened.** The
thin-client gate (fetch count over a published store) opened with measured numbers
(a two-broad-term lazy query cost 1,071 fetches; see `CONE_SUMMARIES_PLAN.md`), and
its step landed 2026-07-31 as **published cone summaries** (`src/ontodag/cones.py`):
per-category membership records in a *separate* derived store — but as **sorted name
lists, not this note's bitmaps**, because bitmaps are positional and a thin client
would need the whole name↔position dictionary to read one answer. §8's sequencing
assumed the hot-CPU gate would open first; it was the fetch gate, so its steps
(2)+(3) arrived before (1). The bitmap/code lattice of this note remains parked
behind the remaining gates; the manifest's format field is the seam it would land
through. Everything else stands: do not extend this note until another gate opens,
and the one cheap action allowed meanwhile — the web-API query counter §9
waits on — was taken 2026-08-01: `GET /dag/stats/queries` reports a per-
category-set counter (per disjunct, process-local, deliberately trivial).
§9's adaptive admission policy now has its data source whenever a gate
opens. Referenced from `SWARM_DESIGN.md` §8.
Companion historical notes (Wilkins, Leibniz, Borges — where this idea comes from and
how its ancestors failed): `PHILOSOPHICAL_LANGUAGES.md`.

## 1. The question, and the decision this note records

Three candidate identities for a concept were considered over the project's history:

1. **Pointers** (Python object references) — rejected early; pointer identity must
   never escape a single DAG instance (the `intersection_dag` aliasing bug was exactly
   this leaking). Pointers remain the *intra-instance* edge representation only.
2. **Words** (arbitrary name strings) — the current decision, and it stands: names are
   identity at every boundary (public API, serialization, cross-instance references).
3. **Codes** (artificial names constructed to reflect meaning — tree-like path codes,
   or binary vectors) — the third option this note examines.

**Decision: codes do not replace names; they join `descendant_count` as a *derived,
recomputable index*.** Identity stays arbitrary and stable; meaning-bearing structure
is computed from the graph, stored beside it, and regenerated when stale. Two reasons,
each with three centuries of supporting evidence (`PHILOSOPHICAL_LANGUAGES.md`):

- *Tree-like (prefix/path) codes cannot represent a DAG.* A prefix code embeds a tree
  order — a child shares a prefix with exactly one parent. A node with two parents
  cannot share a prefix with both unless they share it with each other; no linear key
  space embeds a partial order with genuine multi-parents. This kills the Wilkins/Dewey
  variant outright for OntoDAG; only set/bitvector codes respect the structure.
- *Meaning-bearing identity is unstable by construction.* If the name encodes the
  intent, refining a concept (adding one parent) renames it, cascading through every
  edge and external reference. Arbitrary names are stable names (the surrogate-key
  argument). Codes must therefore live where staleness is cheap: in a derived index.

## 2. The code: ancestor sets, and why FCA "maps directly"

Define, for every node `x`:

```
code(x) = { names of ancestors of x } ∪ { x }        # reflexive ancestor set
```

Read as a binary vector over the category alphabet, this code has the properties the
"neural binary representation" intuition wants:

- **Subsumption is containment:** `A ⊑ B  ⟺  code(A) ⊆ code(B)` (B is below A iff B
  carries all of A's bits). Leibniz's prime-product encoding — subsumption as
  divisibility — is this same lattice in multiplicative notation.
- **The core query is a superset test:** the descendant cone of A is
  `{x : A ∈ code(x)}`, and `get({A, B})` — the intersection of cones — is
  `{x : {A, B} ⊆ code(x)}`. The one query primitive OntoDAG has is a bit test.
- **It is the FCA intent.** When categories are (or are learned as) attributes, a
  concept's intent bitvector and its ancestor set are the same object — this is the
  precise sense in which "FCA maps binary codes directly to DAGs." The inverse
  direction (codes → DAG) is also exact: the containment order on the codes, taken to
  its covering relation, is the transitive reduction — which is **unique**, so:

  > The family `{code(x)}` is a **lossless, canonical alternative encoding of the
  > entire OntoDAG.** DAG → codes (reflexive-transitive closure) and codes → DAG
  > (covering relation of containment) are mutually inverse.

**On canonicality** (the "not sure about canonical" concern): as a *set of names*,
`code(x)` is canonical outright — no ordering enters. Non-canonicality appears only
when the set is materialized as a *bitvector*, which requires an enumeration
`π: names → bit positions`. §5 chooses π; §7 explains why π being derived (not
allocated) dissolves the multi-writer ID-assignment problem.

## 3. The index: cone bitmaps (the transpose)

The reflexive reachability relation is one boolean matrix `R[A, x]` ("A reaches x").
The codes are its columns; the **cone bitmaps are its rows**:

```
cone(A) = bitmap over nodes, bit x set  ⟺  x is a (reflexive) descendant of A
```

Rows are what the query workload wants:

- `get({A, B, ...})`  =  `cone(A) AND cone(B) AND ...`  — machine-word-parallel
  intersection (this is posting-list intersection, the search-engine primitive).
- `descendant_count(A)` = `popcount(cone(A))` — the existing counts are the
  cardinalities of these bitmaps, so **maintenance piggybacks on machinery that
  already exists**: the ancestor set that `_get_affected_nodes` computes for count
  updates is exactly the set of bitmaps a `put`/`remove` must touch, batched per
  public operation as counts already are.
- In-memory representation can be dependency-free: a Python arbitrary-precision `int`
  per category (100k nodes ≈ 12.5 KB/int; `&` runs in C). `pyroaring` is an optional
  upgrade, not a requirement.

This replaces the Python-set intersection in `get()` — previously identified as the
most expensive operation, bounded by the smallest cone — with a few microseconds of
bitwise AND even for large cones.

## 4. What this does to the Swarm story: query without hydration

`SWARM_DESIGN.md` §6 commits to hydrate-once/RAM-first because Swarm cannot answer a
query, only serve records. The cone index creates the first viable exception — an
**index-only query path** for graphs too large (or clients too thin) to hydrate:

```
fetch dictionary record(s)   (name ↔ bit-position map)        ~1 chunk fetch
fetch cone(A), cone(B), ...  (k records, k = |query|)          k fetches
AND locally                                                    ~0
fetch the result nodes' records only                           |result| fetches
```

Total: `O(k + |result|)` chunk fetches, independent of graph size — versus full
hydration's `O(n)`. Cone bitmaps also pack densely and are read together, which makes
the index (not the node records) the **first natural customer for the leaf-packing
machinery deferred in §4 of `SWARM_DESIGN.md`** — it was deferred for lack of usage
data; the index has a known, uniform access pattern from day one.

## 5. Locality, or: "relevance proximity in a tree, but the DAG is not a tree"

The objection is correct in its strong form and escapable in its practical form.

**The impossibility (strong form).** "Relevance proximity" via key order means: one
linear order on nodes such that every cone is a contiguous range. That is exactly what
Wilkins/Dewey path codes give — *for a tree*. For a genuine partial order it cannot
exist: a linear order is a tree order, and prefix/range containment can only express
tree containment. No cleverness rescues a single lexicographic key space. (This is
also why alphabetical `items(prefix)` can never prefetch a cone.)

**The escape (practical form): measure how far the DAG is from a tree, and pay only
for that.** Choose a canonical spanning tree `T` inside the DAG — each node designates
one **primary parent** (deterministic rule, e.g. the parent with the largest ancestor
set, ties broken by name; the rule is a tuning knob, the determinism is not). Number
nodes by DFS pre-order of `T`, children visited in name order. Then:

- Every `T`-subtree is a contiguous interval (the tree case, recovered).
- Every cone is closed under `T`-descendants (a T-child is a DAG-child), so
  **`cone(A)` is a disjoint union of `T`-subtree intervals**, one per "entry point":

  > `#runs(cone A) = #{ x ∈ cone(A) : x = A, or primary-parent(x) ∉ cone(A) }`

  A run break occurs *exactly* at nodes that enter the cone only through a
  **secondary** parent. Corollary: if the DAG *is* a tree, every cone is exactly one
  interval — Wilkins recovered. Each secondary parenthood adds at most a bounded
  number of extra runs to the cones above it.

So under this numbering, cone bitmaps are run-length-compressible into short interval
lists, storage degrades **linearly with the DAG's deviation from treeness** (the count
of secondary placements) rather than catastrophically, and interval-list intersection
is fast and cache-friendly. The DAG-ness is not a wall; it is a metered surcharge.
(Prior art for both halves: Aït-Kaci et al. 1989 — bitvector lattice encodings for
constant-time subsumption; Agrawal, Borgida & Jagadish 1989 — interval labeling for
transitive-closure compression. The synthesis — canonical spanning-tree numbering to
make the *bitmaps* interval-like — is just the two stapled together.)

**What locality does *not* need to do:** prefetch-by-proximity. The index makes
"fetch the relevant neighborhood" an explicit operation (fetch the cone) rather than a
hoped-for side effect of key adjacency. Proximity-as-adjacency was only ever a proxy
for co-cone membership, and the index serves co-cone membership directly.

## 6. Beyond cones (speculative, thinner ice)

- **Graded relevance.** `|code(x) ∩ code(y)| / |code(x) ∪ code(y)|` (Jaccard on
  ancestor sets) is a principled similarity between any two nodes — usable for ranking
  query results or suggesting placements. Cheap given the index.
- **Probabilistic bucketing.** MinHash sketches of codes as key *prefixes* would give
  LSH-style clustering — semantically similar nodes sharing key buckets with high
  probability. This partially dodges the §5 impossibility by being approximate.
  Unclear it earns its complexity; recorded, not proposed.
- **Continuous cousins.** Order embeddings and hyperbolic embeddings are the learned,
  approximate versions of these codes (subsumption as coordinate dominance / radial
  position). Relevant if mdl-fca ever wants a differentiable relaxation; see
  `PHILOSOPHICAL_LANGUAGES.md` "Modern descendants."

## 7. Consistency, provenance, multi-writer

- **The index is `derived`** in exactly the §8 (`SWARM_DESIGN.md`) provenance sense:
  a pure function of the committed graph, regenerable, losable without data loss.
  Persist it (if at all) as separate records under a reserved key prefix, or as a
  separate root committed alongside — never interleaved with asserted node records.
- **No bit-allocation CRDT is needed.** The multi-writer worry — two writers
  concurrently assigning bit 4017 — dissolves because the enumeration π is *derived,
  not allocated*: it is recomputed deterministically from the merged graph (like
  transitive reduction itself), so writers never need to agree on it in advance.
- **The open trade-off is numbering stability vs. structural sharing.** The canonical
  DFS numbering of §5 changes globally on insertion (best compression, but a
  renumbered index shares no chunks with its predecessor — poor fit for recordstore's
  structural sharing). Options, undecided:
  1. *Stable insertion-order IDs* — bitmaps stay valid across commits, structural
     sharing works, compression is worse (runs fragment over time).
  2. *Canonical DFS numbering, index treated as a per-root cache* — regenerate on
     publish; never diffed, so sharing loss is irrelevant. Simplest honest option.
  3. *Two-level:* stable IDs plus a small per-root permutation used only for
     run-encoding. Most machinery; only worth it if (1) and (2) both measurably fail.

## 8. When to build (gates), and what first

**Do not build yet.** In-memory Python sets are fine below ~10⁵ nodes, and the whole
project ethos (`SWARM_DESIGN.md` §4) is that layout optimizations wait for usage data.
Gates — any one suffices to open the work:

- a real graph or query workload where `get()` intersection is measurably hot
  (e.g. the web API serving repeated queries), or
- a graph that no longer comfortably hydrates into RAM, or
- a thin-client use case (query a published ontology without downloading it) —
  this is the gate the index uniquely serves (§4).

Sequencing when a gate opens: (1) in-memory cone bitmaps behind `get()` — pure
speedup, no schema change, invariant I5 doubles as its test oracle
(`popcount == descendant_count`); (2) canonical enumeration + persisted index records;
(3) the index-only query path; (4) only then, leaf-packing tuned for index records.

## 9. The goal: a workload-optimal materialization (declared 2026-07-20)

This section records the direction the preceding sections build toward — the
project-level goal for the retrieval side, stated as an optimization problem.

**The lattice is a memo table.** A concept is a memoized query: its cone is a
precomputed intersection. Full FCA memoizes every closed intersection (every
conjunctive query becomes a lookup; exponential space); the bare asserted DAG
memoizes nothing beyond what was asserted (every query pays its residual
intersection at query time); mdl-fca is a principled *cache-admission policy*
(reify a concept iff its description-length saving pays for it). "OntoDAG" and
"full cone-bitmap index over the complete lattice" are therefore not two data
structures to choose between but the two endpoints of one family:

```
family member = asserted DAG G
              + M: a set of materialized derived meets (reified intersections,
                   unnamed — content-named — concepts)
              + per-cone storage mode: bitmap | interval list | virtual
                   (virtual = recompute from parents' cones on demand)
              + numbering π (§5)
```

**The objective.** Given input statistics (item/code distribution: cone sizes,
overlaps, update rates) and retrieval statistics (query workload Q: which
conjunctions, how often, exact vs top-k):

```
minimize   E_q~Q [ retrieval_cost(q; M, modes, π) ]
         + λ_space · storage_cost(M)            # on Swarm: postage rent, literally
         + λ_maint · update_cost(M)             # hot-write regions resist materialization
```

`retrieval_cost(q)` = cost of intersecting the residual gap below the lowest
materialized bounds of q's terms — the denser M is near q, the closer the query
is to a pure lookup.

**This is a known problem, three times over:**

1. **View-materialization selection on a lattice** — Harinarayan, Rajaraman &
   Ullman, "Implementing Data Cubes Efficiently" (SIGMOD 1996): same picture
   with cuboids for concepts; greedy selection by frequency-weighted benefit is
   near-optimal (submodularity). The needed selectivity statistics are already
   maintained: `descendant_count` is the estimator.
2. **Retrieval-aware MDL** (`SWARM_DESIGN.md` §8) — the same objective seen
   from the learner side; the λ·retrieval_freq·storage_cost term *is* the
   space term above. The learner optimizing input statistics and the index
   optimizing retrieval statistics are one optimizer with two terms.
3. **Adaptive indexing / database cracking** (Idreos et al., CIDR 2007) — the
   online algorithm: every query that performs a residual intersection has just
   computed a candidate meet; admit it to M when expected reuse covers its
   cost, evict when cold. The structure converges to workload-optimality
   per-region without offline planning.

**Architectural consequences (already implied by decisions on record):**

- The materialization layer M is `derived` in the provenance sense —
  regenerable, evictable, never merged. **Only G syncs between writers; M is
  local and personal**, shaped by each device's own query log. Two users share
  an ontology and hold different accelerations of it. On Swarm, eviction has a
  native mechanism: let a derived cone's postage lapse.
- **Semantics must not leak into the optimizer.** G remains the sole ground
  truth (write/merge/retraction side, per the closure-non-compositionality
  argument); the optimizer may change what a query costs, never what it means.
- Graded (top-k overlap) retrieval rides the same structure: overlap with a
  fixed query is monotone along DAG edges (code(x) ⊇ code(A) for x ⊑ A), so
  the DAG doubles as an exact branch-and-bound search tree for
  nearest-by-overlap queries; generic approximate-NN machinery is needed only
  if codes ever become continuous/noisy.

**What is concrete today vs. deliberately open.** Concrete: the objective, the
decision variables (M + storage modes + π), and a v0 online policy needing no
offline planning — keep counts `f(S)` of queried category-sets; when a query
computes a residual intersection, materialize its meet iff
`f(S) × cost_saved > λ_space × |result cone| + λ_maint × update_rate`; evict by
the same inequality run backwards. Open, because the inputs are empirical and
do not exist yet: the cost-model constants (chunk fetch ≈ ms vs. word op ≈ ns —
backend-dependent), and the query log itself (the web API is the natural place
to start collecting one). Designing the admission thresholds before that data
exists would repeat the mistake §4 of `SWARM_DESIGN.md` explicitly avoids.

Gates from §8 apply unchanged; when they open, the sequencing there stands,
with this section as the destination it points toward.

## 10. Resolved questions (2026-07-20, closing the design thread)

- **"Internal activation" as the retrieval algorithm.** Spreading activation
  with a threshold unifies both retrieval modes on the closed form: each query
  category activates its cone, items accumulate counts; threshold = |query| is
  exact intersection, threshold < |query| is graded overlap retrieval (the
  2003-poster problem). The classic non-transitivity objection to spreading
  activation does not apply — cones are transitively correct by construction.
  No fifth cost layer exists beyond §9's four (closure precomputation,
  representation, planning, memoized meets); exact conjunctive retrieval has
  matching lower bounds, so "best" is workload-relative — hence §9's objective
  rather than a single structure.
- **Proper (complete) FCA is not needed.** What must be preserved is
  per-concept closedness and the DAG invariants, not lattice completeness.
  Under the memoization view (§9), incompleteness is a feature: absent meets
  are the intersections that didn't pay. mdl-fca (MDL selection) is the
  principled version of iceberg-lattice partiality.
- **Materialized meets impose a write-path invariant (soundness condition for
  §9, found 2026-07-20).** A node AB with parents {A, B} does *not* satisfy
  `cone(AB) = cone(A) ∩ cone(B)` in current OntoDAG: `put(X, [A, B])` creates a
  *sibling* of AB (`_remove_unneeded_edges` prunes redundant ancestors, never
  reroutes through descendants), so substituting AB for {A, B} in a query plan
  silently loses results. §9's admission policy is therefore incomplete without
  one of: (a) **canonical placement** — once a meet is materialized, every
  later put whose supers subsume its parent set must route through it; or
  (b) treating materialized meets as unverified cache with explicit
  invalidation. Sound without either: using AB only to *prune* (candidates
  below AB pass the A- and B-membership tests for free), never to generate
  candidates. Independent of all this, `get()` admits a small sound planner
  today: drop query terms that are ancestors of other terms, order cones by
  `descendant_count` ascending, intersect incrementally with early exit, and
  choose walk-vs-probe (walk smallest cone, test candidates by upward
  `parents` walk) from the counts. **Implemented 2026-07-21, including
  walk-vs-probe**: see `OntoDAG.get` in `src/ontodag/dag.py`. Design points
  that emerged: (a) *plan order in advance, choose operators during
  retrieval* — term order rests on exact maintained statistics
  (`descendant_count`), but intermediate result sizes are unknowable up
  front (cone overlap is not a per-term statistic), so the walk-vs-probe
  choice is made between steps, O(1) each, from the now-known running-result
  size; one upward walk per candidate settles *all* remaining terms.
  (b) *Planner work must scale with the query, never the graph* — the
  subsumption test walks upward from the smaller-count term
  (`_has_ancestors`, bounded by its shallow ancestor cone), not downward
  from the larger. (c) The probe/walk crossover uses a deliberately
  high constant (`_PROBE_COST_ESTIMATE`) standing in for the unmaintained
  ancestor-cone size; both operators are exact, so the estimate steers time,
  never correctness — made executable by the forced-probe/forced-walk oracle
  tests in `tests/testdag.py::TestQueryPlanner`, which also guard the
  meet-substitution trap above.
- **Change-locality resolves by layer.** Asserted DAG: local (one edge + its
  ancestor set). Bitmap index: semi-local (exactly the affected ancestors'
  cones — the count-update set). FCA/learning: global, *and that is
  acceptable* — learning is a periodic batch step whose output is `derived`
  and regenerable, so staleness costs compression quality, never correctness.
  Incremental MDL-FCA is a research problem the layering lets us not need.

## References

- H. Aït-Kaci, R. Boyer, P. Lincoln, R. Nasr, "Efficient Implementation of Lattice
  Operations," ACM TOPLAS 11(1), 1989 — bitvector encodings of partial orders.
- R. Agrawal, A. Borgida, H. V. Jagadish, "Efficient Management of Transitive
  Relationships in Large Data and Knowledge Bases," SIGMOD 1989 — interval labeling.
- B. Ganter, R. Wille, *Formal Concept Analysis*, 1999 — intents, concept lattices.
- Roaring bitmaps (Lemire et al.) — the practical compressed-bitmap workhorse.
- mdl-fca (github.com/petfold/mdl-fca) — the learner that makes codes *meaningful*
  (short codes for concepts that pay for themselves), see `SWARM_DESIGN.md` §8.
- P. Földiák, "Sparse neural representation for semantic indexing," ESCOP 2003 —
  concepts as sets of active features, inheritance as subset structure, set-algebra
  queries, overlap-based retrieval; the code-primary position this note builds on.
  https://drive.google.com/file/d/0BzC4pqiFnDxcNnpFTm9qYWpqejg/view?usp=sharing
  (local copy: `docs/escopill2.pdf`, untracked).
- `PHILOSOPHICAL_LANGUAGES.md` — why the ancestors of this idea failed, and which
  failure modes this note is built to avoid.
