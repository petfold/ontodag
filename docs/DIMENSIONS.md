# Dimension Lattices: Parametric Items with a Computed Order

Status: design agreed 2026-07-30 (three-session discussion, Peter + Claude);
**steps 1–5 and 7 of §12 implemented and released the same day (v0.4.0)** —
`src/ontodag/dimensions.py`, the `dag.py` integration, the `LazyOntoDAG`
path, `get_overlapping`, the web REST pass-through, user docs; CLI validated
end-to-end on the native store. Step 6 (per-dimension sorted derived index)
was built on 2026-10-07, when profiling asked (§19). This document is the design record;
implementation sequencing is at the end. Read `DATABASE_DIRECTION.md` first
for where this sits in the wall/tripwire discipline — this design is the
fired escape hatch of the "exact arithmetic" wall, recorded there.

**Note on the examples (2026-10-07).** The sections below were written when
the prelude's mass head was `weight` and a head took its unit family from its
first value. Since prelude v4 (0.30) the head is `mass`, pinned with `mass ⊑
linear-dimension(mass)`, and there is no `weight` head (weight is a force;
§21). The examples keep `weight` as written; read it as a head a store
declares itself, or as `mass`.

## 1. What and why

OntoDAG's order has so far been entirely asserted: `JAL < Flight` exists
because someone put an edge there. Nothing in the graph knows that a 3 kg
parcel satisfies a courier's 5 kg limit — `5` in a name is an opaque
string. Marketplace matching (the loopmarket sister project — offers
described as OntoDAG-concept conjunctions, matched by *fits-within*)
needs constraints at arbitrary, query-time thresholds: max weight, min
quantity, time windows, service regions. No pre-generated quantization
contains an arbitrary threshold; this is computation, not classification
— the tripwire of `DATABASE_DIRECTION.md`'s "exact arithmetic" wall,
fired 2026-07-30 by loopmarket.

The design adds **parametric items**: names of the form `head(param)` —
`weight(3000g)`, `weight(..5000g)`, `time(2026-08-10T00:00:00Z..
2026-08-20T23:59:59Z)`, `geo(u2ed)`, `size(390x230x190mm)` — whose order
relative to each other is *computed* from the name rather than stored as
edges.

## 2. Semantics: one order, and it is the one we already had

A parametric item **denotes a set of values**: `weight(3000g)` denotes
{3000 g}; `weight(..5000g)` denotes (0, 5000] g. The computed order is
**containment of denotations** — and that is not a second kind of order:
the DAG's asserted order was always extension inclusion (`JAL < Flight`
= every dog is an animal). `A < B` reads "A is a solution to query B."

Consequences worth stating explicitly, because they are easy to get
wrong:

- `weight(3000g) < weight(..5000g)` — every 3 kg thing is a ≤5 kg thing.
  The courier match.
- `weight(1200g) < weight(1000g..)` — the "at least 1 kg of flour"
  match; no special ≥ rule, containment covers both directions.
- `weight(3000g)` and `weight(5000g)` are **incomparable**. The value
  order 3 < 5 is machinery *inside* the containment test, never a DAG
  edge: a 3 kg parcel is not a special case of a 5 kg parcel, and
  `get(weight(5000g))` must not return 3 kg items.
- Min/max are not primitives: they are half-bounded intervals
  (`..5000g`, `1000g..`) under one constructor per dimension; a point is
  a degenerate interval.

The division of labor: **subsumption and unordered sets live in the
graph** (multi-parent `put` gives the feature set), **binding lives in
the name** (`height(30mm)` vs `weight(5000g)` — the term is the pair;
a flat set {height, weight, 30, 5000} could not bind value to
dimension), **arithmetic lives in a fixed interpreter** (§3).

Why the arithmetic cannot live in edges — four independent obstructions,
recorded so nobody re-attempts a "pure DAG" encoding:

1. Dense orders have an empty covering relation — no transitive
   reduction of the full order exists, so it can never be materialized
   even in principle.
2. Materializing the present slice is insertion-unstable: adding a value
   between two others rewrites neighbor records — non-local churn and a
   merge-conflict magnet.
3. Read-only clients (`LazyOntoDAG`, a browser on a published graph)
   cannot create threshold nodes at query time; a *virtual* query term
   evaluated by an oracle needs no write access.
4. Merging two writers' materialized chains cannot be renormalized
   without the arithmetic anyway (nothing in the merged edges says
   4 < 4.2) — multi-writer convergence forces the oracle to exist.

Constituency encodings (a `(5 kg)` node with child nodes `5` and `kg`)
are also out: argument edges have no subsumption reading — they are
*roles*, a documented wall. The one edge in that sketch that is genuine
subsumption ("every 5000 g-weighing thing is a weighted thing") is kept:
it is the anchor edge of §5.

## 3. Declarations: edges, not meta; a registry, not callables

Nothing about dimensions goes in the record `meta` field. The rule that
keeps modeling canonicity (same knowledge, one representation, same
root): **anything that changes what a query returns must be an edge or a
name; meta is annotation no query traverses.**

- **Kind by ancestry.** A dimension head is an ordinary node placed
  under a registry-known kind node: `weight → linear-dimension →
  dimension → *`, `geo → prefix-dimension → dimension`, `size →
  dominance-dimension → dimension`. The registry recognizes these
  reserved names the same way the codebase already recognizes `*`.
  "Is `weight` a dimension?" is answered by graph traversal; a published
  DAG is self-describing. Kind lookup walks asserted ancestors
  (so `integer → number → linear-dimension` inherits); inheriting two
  *different* kinds is an error.
- **The registry is fixed, versioned, in-core interpreter code** —
  stdlib only (B1 intact), never per-graph code, never a callable
  attached to data. Two writers must compute the identical relation from
  the identical bytes; that determinism is as load-bearing as transitive
  reduction itself, because the computed relation participates in
  reduction (§5) and therefore in the canonical root.
- **Determinism doctrine — exact arithmetic only.** Only kinds whose
  comparisons are exact and platform-independent (integers, strings,
  products of these) may ever enter the canonical order. Transcendental
  math is permanently excluded: geohash *cells* are DAG-side (string
  prefixes), haversine *discs* stay application-side refinement
  (loopmarket's `check_match` is the exact truth by its own design
  requirement — the DAG only supplies recall-safe candidates).
- Units are read from the value suffix via a global registry table and
  normalized to the family's base unit; a head's values must share one
  unit family (checked at `put`). Product arity is inferred from values
  and checked for consistency. Nothing is configured per node.

## 4. Values are exact

Measured quantities are **reduced rationals of the SI coherent anchor**:
`weight(3kg)`, `weight(1/2000kg)`, `length(10/33m)`. No floats anywhere,
so comparisons are exact and platform-independent, and there is no base
unit to choose — which also means no future base migration exists as a
class of problem. `docs/UNITS.md` is the authority: the full unit table
(~30 families, every spelling exact), the registry version and its
compatibility rule, affine temperatures, graph-declared units and packs.

> **History, for anyone reading old stores or old notes:** the original
> 2026-07-30 decision was *integers in a per-family base unit* (mass in
> `mg`, length in `mm` — the cents/wei move), and canonical names looked
> like `weight(3000000mg)`. Registry v3 (2026-08-01, `UNITS.md` D9)
> reversed it: rationals are equally exact, need no base, and cannot
> round at sub-base precision. Old spellings remain valid *input*, and
> `ontodag.migrate` replays a pre-v3 store into the current form. The
> examples below use the current canonical form.

- Input in any accepted unit of the family is scaled exactly, and the
  canonical name is the reduced rational: `weight(3000g)` → `weight(3kg)`,
  `weight(500g)` → `weight(1/2kg)`. Nothing is ever rounded.
- Timestamps are the one non-numeric linear value space: fixed-format
  ISO-8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`), where lexicographic order *is*
  chronological order — comparison is exact string comparison. Boundary
  sugar: a bare date expands deterministically (range start →
  `T00:00:00Z`, range end → `T23:59:59Z`).

## 5. Storage shape

- **Computed order is never materialized.** Stored structure = asserted
  edges only, exactly today's record schema (`up`/`down`/`count`/
  `payload`/`meta` — unchanged).
- **Anchor edges are schema, not assertions.** Every parametric node
  carries exactly one asserted edge to its head node (`weight(3kg)
  → weight`), exempt from transitive-reduction pruning. The star under
  the head is the dimension's existence-and-enumeration index (it is
  what virtual queries and `LazyOntoDAG` walk); the computed relation
  supplies all finer order. Anchoring anywhere else (e.g. narrowest
  present container) reintroduces insertion churn.
- **Reduction modulo the computed relation.** `add_edge`'s cycle check
  and `_remove_unneeded_edges` consult *combined* reachability (asserted
  edges ∪ computed pairs among present same-dimension nodes — finite,
  deterministic). So asserting `parcel7 → weight(3kg)` prunes an
  earlier `parcel7 → weight(..5kg)` as redundant; without this,
  assertion history would leak into roots. The canonical stored form —
  asserted edges reduced modulo computed order, anchors exempt — remains
  unique because the computed relation is a pure function of present
  names.
- Asserted edges **between two same-dimension parametric nodes are
  rejected** (`ValueError`): within a dimension, order is computed,
  full stop.
- **Persisted counts stay asserted-cone-only** (records remain a pure
  function of asserted structure); combined cones are computed at query
  time. Counts steer planner time, never correctness — existing
  doctrine.
- **`remove` contracts along combined covers**: children of a removed
  parametric node reattach to the narrowest *present* nodes above it in
  the combined order, restoring exactly what pruning removed (the
  closure-preserving contract `remove` has today, extended).
  Value nodes left with only their anchor are kept — that a value was
  observed is knowledge; GC stays explicit.
- Merge: asserted parts merge as today (anchor adds are the usual
  union-of-down-lists). Kind-assignment edges merge as ordinary edges; a
  head under two kinds is detectable in-graph and is an error surfaced
  at interpretation time. Post-merge renormalization (already planned
  for multi-writer, §5 of SWARM_DESIGN) also removes semantically
  redundant cross edges that union reintroduces.

## 6. The kinds

| kind node             | denotations                          | contains / intersect                    | covers |
|-----------------------|--------------------------------------|-----------------------------------------|--------|
| `linear-dimension`    | intervals over integers-with-unit or ISO-UTC timestamps; points degenerate; open ends | two comparisons each | weight, quantity-vs-capacity, prices, time windows |
| `prefix-dimension`    | identifier subtrees                  | string prefix test                       | geohash cells; generated hierarchies |
| `dominance-dimension` | boxes (componentwise intervals), components canonically sorted descending | componentwise | parcels/luggage ("fits in"), `size(390x230x190mm)` |
| `calendar-dimension`  | the same interval denotations as linear over the time family, but every literal is a calendar period: `2026` the year, `2026-08` the month, `2026-08-15` the day, a timestamp the instant | identical to linear (shared code path) | dates on documents, "last summer", "everything from 2026" |
| `count-dimension`     | whole numbers ≥ 1 of discrete things; ranges with floor 1 | interval containment | multiplicities (§ UNITS.md 11) |
| `graph-dimension`  | a conjunction of constraints on the graph — category names and terms of other dimensions (`transport(small-item weight(..8kg))`), sorted, deduplicated, a redundant one dropped; stored as one term per constraint (§15) | **by the graph**, not the name: every outer constraint is above some inner one; meet = union, reduced (§15) | what an operator accepts (loopmarket's courier), any "things such that" argument |

**`calendar-dimension` (added 2026-08-01, `REGISTRY_VERSION` 2).** A separate
kind for one reason, and it is a grammar collision rather than a semantic
difference: in a linear dimension a bare integer is a dimensionless *count*
(`number(5)`), so `time(2026)` there can only mean the number 2026, which then
refuses to compare with any date and reports a baffling unit-family error.
Parsing is deliberately context-free on the name — the year reading must not
depend on what else the graph happens to contain, or the same term would
canonicalize differently for two replicas and §3's determinism doctrine would
fall. The declared kind is the one piece of context a term already carries
(`contains(outer, inner, kind)` has always taken it), so that is where the
calendar grammar belongs.

It is *linear over the time family* in every other respect: same interval
denotations, same containment and meet code, same `linear:time` space tag, same
canonical rendering. A dimension declared `time → linear-dimension` can be
re-declared `time → calendar-dimension` without one stored value or canonical
name changing — the only difference is which literals the parameter grammar
admits. Reduced precision denoting the whole period is not new either: the
linear grammar already read a bare date as the whole day, and this extends the
same rule up to months and years.

Deferred, with reasons: **periodic sets as a computed kind**
— largely obsoleted by §9: "Saturdays" is a generated node over
day-interval terms, with definitional hierarchy replacing
recurrence-rule inclusion; a computed kind would only answer
beyond-horizon membership, so its tripwire has receded. (Calendar *periods*,
above, are ordinary intervals and needed none of that machinery.) **Geo discs** — never
(determinism doctrine, §3); they remain loopmarket's exact refinement.
**Cross-dimension computation** (`price × quantity`) — still behind its
wall; dimensions compare a value to a constraint within one dimension,
never compute new values.

## 7. Grammar

Canonical form is the identity string; the grammar exists to make
rendering deterministic, not to be a language.

```
term   := head "(" param ")"
param  := value | range | tuple
range  := [value] ".." [value]        -- at least one end; inclusive (v1)
tuple  := value ("x" value)+          -- dominance kinds; canonical order sorted descending
value  := integer unit | iso-utc-timestamp | prefix-string
          | calendar-period            -- calendar kinds: YYYY | YYYY-MM | YYYY-MM-DD | iso-utc-timestamp
```

Canonical form: no whitespace (except between the constraints of a
category term, §15); integers without leading zeros or `+`;
base unit suffix; full-precision timestamps. Inclusive bounds only in
v1 (exclusivity doubles canonical-form cases for near-zero matching
benefit on exact values; revisit on real need).

**Parse trigger:** a name `head(...)` is parametric only when `head`
resolves to a present node descending from `dimension`. Every other
name remains an opaque atom — full backward compatibility; nothing
changes for existing graphs. Declare the dimension before putting
values (error otherwise). `(` `)` `..` `x` are reserved in new names
going forward. The grammar is defined recursively (terms as parameters):
the flat kinds refuse a nested parameter as before (`weight(x(y))` under a
declared `weight` stays an opaque atom), and the graph kind (§15) is
the one whose parameter holds terms — `split_term` accepts balanced
parentheses inside a parameter since registry 4.2. CLI note: parentheses
need shell quoting, and a category term with several constraints holds a
space, so it needs quoting as one token.

**Nesting is bounded (2026-10-09, review question 7, decided with Peter):**
a new term nests at most `MAX_NESTING` = 32 levels (`in(paris)` is one,
`transport(mass(..5kg))` two). Reading a term recurses once per level and
Python stops at about 600, so a deeper name ended in a RecursionError — a
traceback from `odag`, an `odag-mcp` that exited, a 500 from the web app —
after seconds of work for a long name. `check_nesting` refuses it with a
teaching error in one pass, before anything recursive reads it (in
`_parse_parametric` and `_graph_parts`, the two ways in); a name already in
a store is never read again, so no stored name is affected. Real names use
two levels. The alternative, an iterative parser, was declined: it would
rewrite the most intricate code for names nobody writes, and a deep name
would still cost seconds.

Boundary sugar (CLI/web, never the identity): friendly units
(`3000g` → `3kg`), bare dates, bare numbers → `number(...)`,
user-defined aliases like `max_weight(x) := weight(..x)` — all
normalized before names are formed.

## 8. Queries

- **Present nodes only.** Parametric nodes exist only when used;
  queries quantify over what is present. "All integers" can never be an
  answer.
- **Virtual terms.** `get(weight(..5kg))` needs no such node to
  exist: its cone = the head's present instances (the anchor star's
  `down` list) filtered by containment, unioned with their asserted
  cones. Cost ∝ matching used values; log-time with a per-dimension
  sorted index — **derived, regenerable, never merged**, like every
  other index in this stack. `LazyOntoDAG` gets the same via the head
  record's `down` — bounded fetches, no writes.
- **Planner integration.** Same-dimension query terms: one inside the
  other keeps the finer; provably disjoint ones short-circuit to the
  empty result; incomparable ones stay separate cones the planner
  intersects. (Until 0.26.1 they were met into one virtual term — not
  result-preserving: the meet's cone holds the present values inside it,
  and an item filed under both terms was below neither. `put` now files
  such an item under the meet, §9, and the planner no longer substitutes.)
- `get` returns matching parametric nodes as well as items below them
  (consistent with today's whole-cone results; items-only is a
  presentation flag).
- **The Boolean face**: `is_below(sub, sup)` (v0.7.0) accepts virtual
  parametric terms on either side — a same-head pair decides from the
  names alone, a virtual bound is met by a streaming upward climb
  (early exit on the walk, not just the scan), a virtual subject
  relates through its present containers.
- **Overlap is not a cone and never will be** — overlap is not
  transitive, so no partial order generates it. Guaranteed satisfaction
  (offer ⊆ constraint) is the v1 order. A separate query op
  (`get_overlapping(term)`: per-dimension `intersect` over present
  values, query-only, no stored state) is the **first follow-up**,
  because loopmarket's time/geo gates are overlap-shaped ("a delivery
  instant exists", "a handover point exists"). Until it lands,
  bucket-decomposition + loopmarket's exact re-check remains
  recall-safe. A match report can then be three-valued: guaranteed /
  possible / impossible.
- **Operators along a dimension** (filed 2026-09-07 by loopmarket, not
  yet an issue). loopmarket's cleared object is now a *circulation* with
  composed legs: one want satisfied by several gives together — a
  toothbrush on a forecourt plus a courier's carriage satisfies "toothbrush
  at the hotel reception by 00:35" (`loopmarket/docs/plans/P2-loop-selection.md`
  §10–11). The composition is an operator on a dimension's coordinate:
  transport shifts *place* (cell a → cell b over a time window), storage
  shifts *time*, exchange shifts *denomination*. The question for ontodag:
  can such an operator be a catalogue term with computed ordering like a
  dimension value — `transport(u2ed→u2ef, 00:15..00:35)` — so that
  `brush@u2ed ⊗ transport(u2ed→u2ef) ⊑ brush@u2ef` is decided by the
  planner, with the intermediate coordinate of a multi-hop chain left as a
  free variable the solver binds? Until then loopmarket composes in its
  own `check_composition` over exact dimension values, and clearing
  re-verifies it (U3), so this is a pruning ask like overlap, not a
  correctness one.
- **Overlap terms in the planner — built and WITHDRAWN 2026-09-12** (issue
  #14, filed 2026-09-07 by loopmarket). `get(terms, overlapping=[...])`
  shipped in the afternoon: each overlap term one more cone in the plan,
  anchors = the star values overlapping it, walk = `get_overlapping`'s,
  probe = an asserted climb into the anchor set. The same night it was
  first revised (overlap terms as per-candidate constraints, an item
  stating nothing under the head passing unvisited — Peter: *what is
  unconstrained is not visited; the other constraints give the result*)
  and then removed altogether, when Peter asked the question the design
  had skipped: *why is overlap relevant at all? ontodag is based on
  intersection.* The answer: it was relevant only under a reading of
  loopmarket's offers the author of loopmarket does not hold. A want is
  the wider cone and a give the narrower one — the toothbrush wanted
  within five metres of the reception desk within thirty minutes is a
  narrow want, and the give that fits within it matches — so a want's
  place and time are query terms like its categories, and the gives in
  the answer are `get(want.terms)`: containment, term by term, one plan.
  "A handover point exists" (two flexible sides, a non-empty meet) was
  the modelling error, not a missing operator. What stays: `items_only`
  (the second ask of #14, a presentation flag made real: no parametric
  values, nothing with something filed under it); `get_overlapping` and
  `overlaps`/`meet` (#16) as a consumer's *candidate* question and the
  pairwise arithmetic of two terms — neither is a query mode of `get`.
  The CLI flag `--overlapping`, REST `overlapping=` and the MCP `query`
  argument are gone (the REST and MCP surfaces answer a request for them
  with a pointer to `terms`).
- **Role heads and node parameters** (issue #15, shipped 2026-09-12):
  a head declared under another head is a *role* of that dimension and
  may take the base dimension's *nodes* as parameters — `from(my_home)`,
  `where(ljubljana)`. The order is then the graph's own order in the
  base dimension, and it follows the catalogue. §14 is the record.

## 9. Regions and generated sets (agreed 2026-07-30)

**Canonical placement (0.26.2).** An item sits in the *intersection* of
its parents, and within one dimension that intersection has a name — so
`put(x, ["weight(1kg..3kg)", "weight(2kg..5kg)"])` files `x` under
`weight(2kg..3kg)`, in one call or across two (`reclassify` folds with
the parents the item keeps). One denotation, one stored form, and every
query path — a two-term `get`, a `get` on the meet, `is_below` against a
bound only the meet is inside — finds the item where it is. Every value
named in the put is still materialized (a value once named stays), so
stored form does not depend on the order of puts. The graph kind is the
exception since 2026-10-08: its meet is a compound term whose spelling
follows the graph, so its terms are filed as their parts instead (§15). Role terms naming nodes
have no nameable meet and keep their several parents; a provably empty
meet is the disjoint-parents refusal below. A legacy or edge-built store
may still hold an item under two values of one head; the planner
intersects the two cones and `is_below` consults the meet of the item's
same-head ancestors, so it is found there too — the gap found while
building §15. This is the "canonical placement" SEMANTIC_CODES.md §10
names as the soundness condition for materialized meets, holding for
dimension values (whose meets are computed, never asserted).

Set-valued concepts whose members are expressible as parametric terms
need **no new kind**: they are ordinary asserted nodes over generated
children. The recurrence rule / boundary polygon is a *generator* —
tooling, not model.

- **Geo regions, any shape.** A region (administrative area, delivery
  zone, shoreline) is an ordinary node with its interior cells asserted
  as children (`put(geo(u2e), [balaton-region])`). Arbitrary
  boundaries, holes, disconnected regions and freely overlapping
  regions come for free — the shape lives in *which cells were
  asserted* — and adaptive precision is native: one region can hold a
  coarse interior cell and fine boundary cells simultaneously, since
  prefix containment computes across precisions. Administrative
  hierarchies are definitional, not geometric (`balaton-shore →
  hungary → eu`: plain edges). **Coverage queries are ancestor
  queries**: from an item's cell, the combined order climbs computed
  prefix hops, then asserted edges, into every region containing it —
  `get_ancestors` is the primitive. Soundness: interior cells go under
  the region (guaranteed match); boundary-crossing cells belong to the
  "possible" layer (`get_overlapping` / index hints), with exact
  geometry as application-side refinement — loopmarket's "cells are
  hints" doctrine.
- **Periodic and ad-hoc time sets.** "Saturdays" is the same mechanism
  in the time dimension: a node whose children are day-long interval
  terms (`time(2026-08-15)` sugar), asserted by a generator.
  Definitional hierarchy is free (`saturdays → weekend-days`),
  sidestepping recurrence-rule inclusion decidability entirely. Unlike
  geo, time cells are *exact* — no boundary layer. The caveat is the
  **horizon**: a periodic set is infinite, so the generator asserts
  cells over a bounded horizon (for loopmarket, offer validity windows
  bound it). Extension is append-only, O(1) churn per day,
  merge-friendly; but queries beyond the asserted horizon miss — the
  only residue the deferred calendar kind would ever compute, so its
  tripwire recedes far. Consequently **time needs no prefix kind**:
  buckets are interval terms of the linear kind. The pattern
  generalizes: shifts, holiday lists, price bands — any finite or
  generated union of parametric terms.
- **The union-vs-intersection footgun, and its guard.** `put(X, [A,
  B])` means X ⊆ A ∩ B. A union-shaped extent (a service region,
  opening times) must therefore be a region *node above* its cells —
  never an item multi-parented under all its cells, which asserts the
  (often empty) intersection. Because disjointness is computable
  within a dimension (`intersect()` empty), the boundary catches the
  mistake: **`put` under provably disjoint same-dimension parametric
  terms raises**. A cheap, exact lint; part of the v1 boundary checks.
- **Exact polygons — doctrine-permitted, deferred.** Unlike discs
  (distance needs trigonometry — excluded forever), polygon
  *containment* over integer coordinates reduces to
  sign-of-determinant orientation predicates: exact, deterministic,
  admissible under §3. Deferred anyway: it needs a real canonical name
  form (vertex order, starting vertex, collinearity) and genuine
  computational geometry, while cell-unions + refinement cover the
  known use cases. Its own tripwire: a real query where
  cell-granularity candidates plus exact recheck measurably fail on
  recall or cost. The prefix kind is cell-scheme-agnostic — geohash
  today, S2 tokens later (already on loopmarket's P1 radar), no design
  change.

## 10. loopmarket integration map

- `check_match` stays the exact, self-contained truth (its stated design
  requirement); OntoDAG supplies recall-safe candidate generation.
- loopmarket P1's "spacetime buckets as generated OntoDAG nodes" is
  subsumed: time windows become exact linear-interval terms (no
  quantization error), geohash cells become a `prefix-dimension`
  (containment computed from the name; only used cells materialize).
  The chain/bucket generators survive only as optional derived indexes.
- loopmarket's candidate generation should be **one planned query**, not
  three intersected client-side (§8, issue #14, 2026-09-07): meaning
  (containment), service time (overlap) and — once cell/region terms are
  in the shared catalogue — place, in one adaptive plan, so whichever
  dimension is selective prunes first. Its `DimensionIndex.candidates`
  collapses to one `get(..., overlapping=[...])` call when that lands.
- Offers pin ontology roots; since the registry's semantics participates
  in reduction, the **registry version must be pinned alongside the
  root** (a module-level `REGISTRY_VERSION`; where it rides in
  loopmarket's offer encoding is loopmarket's decision). Open question:
  whether a graph should also self-declare it (e.g. a reserved record
  key) — decide before multi-writer dimensions ship.

## 11. Invariant audit (summary)

- I1: computed relation is a strict partial order given canonical
  normalization (equal denotations ⇒ equal names ⇒ same node); combined
  cycle check in `add_edge`.
- I2/I3: reduction modulo the computed relation, unique because the
  relation is a pure function of present names; order-independence holds
  for the same reason.
- I4: unchanged (names remain the only cross-instance identity).
- I5: persisted counts asserted-only; combined counts on demand.
- I6: traversals gain computed hops but stay iterative.
- I7: merge as today + declaration-conflict surfacing + post-merge
  renormalization.
- B1: registry is stdlib-only core; `import ontodag` stays clean.
- S2 (history-independence): protected by reduction-modulo-computed and
  by integer canonicalization at the boundary.

## 12. Implementation sequencing (one reviewable commit each)

1. ~~Grammar + registry + canonicalizer (`src/ontodag/dimensions.py`)~~
   **DONE** (`80f18df`) — parse/normalize/render, unit table,
   `contains`/`intersect` for the three kinds; brute-force denotation
   oracles. One design refinement the oracle forced: integer families
   admit no negatives, so an unbounded lower end IS 0 and normalizes to
   one canonical form (`number(..0)` ≡ `number(0)`,
   `number(0..5)` ≡ `number(..5)`).
2. ~~Combined reachability in `dag.py`~~ **DONE** (`590a402`) — kind
   lookup by ancestry, boundary canonicalization everywhere, anchor
   auto-creation (schema edges, never pruned), combined-order cycle
   check and reduction, same-dimension edge rejection, disjoint-parents
   guard, per-head value-space consistency. Note on counts: pruning now
   runs with *live* counts after the add — an edge redundant only via
   computed hops genuinely changes asserted reachability, so its
   removal must (and does) decrement the asserted-only counts, while
   asserted-redundant prunes remain count-neutral automatically.
3. ~~`remove` contraction along combined covers~~ **DONE** (`d78639d`).
4. ~~Virtual query terms + planner pre-intersection~~ **DONE**
   (`72e7d31`) — queries with parametric terms take a straightforward
   smallest-cone-first path (virtual cones from the anchor star, then
   one upward probe for the ordinary terms); dimension-free queries
   keep the existing adaptive planner bit-for-bit.
5. ~~`LazyOntoDAG` virtual-term path~~ **DONE** (`06b4df8`) — the kind
   lookup expands as it climbs (records carry `up`); traversal overrides
   follow computed hops; cones cached only in the combined order; a
   courier query reads <20 records while a 40-leaf unrelated subtree
   stays untouched.
6. ~~Per-dimension sorted derived index (only if profiling asks)~~ **DONE
   2026-10-07** (§19): profiling asked, and the answer was quadratic bulk
   loads in every kind. In memory, per head, built from the star on first
   use and kept by `add_node` and `_forget`; never stored or merged.
7. ~~`get_overlapping` (first follow-up, after v1 ships)~~ **DONE**
   (`ff9b72a`) — the possibly-satisfies query op of §8, virtual terms
   welcome, inherited unchanged by Eager and Lazy. The web REST layer
   also passes names through now (`put`/`get` resolve and validate),
   so dimensions work over HTTP (`tests/test_web.py`).

Tests mirror `test_invariants.py` style: an independent denotation
oracle, all-pairs computed-order checks on fixtures, history-
independence of roots with parametric puts in shuffled orders, boundary
error cases (sub-base precision, mixed unit families, undeclared heads,
same-dimension edges), and a loopmarket-shaped candidate-generation
fixture (courier + flour + time window + geohash).

## 13. Future kinds — parked, with tripwires (recorded 2026-08-01)

The four shipped kinds are not the boundary of what the admissibility
criterion allows. The criterion never mentions topology; it asks only
that **containment of named regions be a partial order decidable by
exact arithmetic from the names alone**. Candidates that pass, parked
until a consumer trips the wire:

- **Cyclic (`cyclic-dimension`)** — values are *arcs* on a circle:
  `weekday(Fri..Mon)` wrapping through Sunday, hour-of-day, angle mod
  360 (the linear `angle` family puts 359° maximally far from 1°; a
  cyclic kind would make them neighbors). Arc containment is
  transitive and exact. Design wrinkles: canonical form is
  `(start, extent)` rather than `lo..hi` (a wrapping arc has no
  lo ≤ hi), and the full circle must collapse to one name. Likeliest
  consumer: opening hours / recurring schedules — and midnight-crossing
  hours are the motivating case: linear `5..3` refuses today ("empty
  range"), correctly, because on a line nothing sits between 5 and 3
  going up; on a circle `hours(22..06)` and `weekday(Thu..Tue)` are the
  wrap arcs, which is exactly what `(start, extent)` makes canonical
  and one mod-subtraction decides. Refined (Peter, same day): make it
  ONE general modular kind, not per-case types — a head declares its
  period the way a unit family declares its anchor (weekday = 7,
  hour-of-day = 86400 s, month = 12, angle = 360), and named positions
  (`Thu`, `Aug`) are spellings for rational positions, so the whole
  unit-declaration/pack machinery transfers unchanged. Time zones:
  a fixed offset is a *rotation* of the circle, and rotations map arcs
  to arcs exactly — boundary-crossing shifts cost nothing because the
  circle has no boundary — so fixed offsets are core arithmetic and
  may ride in canonical names. **Political zones (tzdata, DST) are a
  wall**: not computable from names, mutably and politically amended,
  and one named zone is different rotations at different times of the
  year — two readers with different tables would disagree about stored
  knowledge, breaking determinism and merge. They belong at
  elaboration ("Vienna time" snaps to concrete offsets on input), or
  wait for a pinned-table mechanism à la REGISTRY_VERSION if stored
  political zones ever find a real consumer. Narrowed further (Peter,
  same day: "leave it to the surface layer, core deals only in UTC"):
  (a) the time→cycle projection can ALSO be surface — file the event
  under both `time(…)` and `weekday(Sat)` at put time (materialized,
  asserted, merge-safe; cost: projections not anticipated at filing
  time can't be queried retroactively); (b) FINITE cycles need no kind
  at all — `weekday(Fri..Mon)` is a plain category with four asserted
  children, shippable as a vocabulary pack today. The cyclic kind's
  tripwire therefore narrows to *continuous* periodic ranges as query
  terms (opening hours `22:00..06:00`, angles mod 360), where
  containment must be computed, not enumerated.
- **Periodic projections of time** — "all Saturdays" is not a
  dimension but a periodic predicate over the time line: an infinite
  union of intervals whose containment against any interval is still
  decidable from names (reduce endpoints mod the period, exact).
  More machinery than cyclic; same tripwire.
- **Spherical caps (real geo discs)** — currently dodged by geohash
  (prefix topology draped over the sphere). The square root is NOT
  the wall: comparisons of squared distances eliminate it — planar
  Euclidean discs are admissible *today*
  (`disc₁ ⊆ disc₂ ⇔ r₁ ≤ r₂ ∧ dist² ≤ (r₂−r₁)²`, exact over
  rationals; Peter's observation, 2026-08-01). The real wall is
  **trig**: lat/lon are angles, and sin/cos are transcendental. But
  that is a representation choice — store positions as rational
  points *on* the sphere (dense, Pythagorean-style parametrization),
  and chordal-squared arithmetic makes cap containment a comparison
  among degree-2 algebraic numbers: decidable exactly by squaring
  with sign case-analysis. The lossy lat/lon → rational-point snap
  happens at elaboration, where lossiness is allowed (the surface
  layer's job, like `2026` → a timestamp range). Needs a worked
  design: canonical point encoding, the case analysis, and whether
  loopmarket's application-side discs migrate. **But note the shortcut
  that covers the actual use case (Peter, same day): "within 10 km of
  here" needs no sphere at all — project to a shared local tangent
  plane at elaboration and store rational planar coordinates; planar
  squared-distance discs are already admissible, and the projection
  error at service-offer scales is of order (d/R)² — centimeters. The
  one requirement is a shared frame (two discs compare exactly only in
  the same projection), which makes the frame choice part of the
  vocabulary, like a unit. A *per-pair* halfway-point tangent plane
  roughly halves the distortion but is an application-side trick only:
  frame-per-comparison means containment stops being a function of the
  stored names in one shared system (and the frame itself needs trig at
  query time) — fine for loopmarket's matcher, out of bounds for a
  stored kind. Full spherical caps then matter only for
  continent-scale regions — nobody's tripwire.**
- **Toroids, Möbius strips, Klein bottles** — no obstruction in
  principle: a partial order of regions neither knows nor cares
  about orientability or genus. The blocker would only ever be
  agreeing a canonical region-naming scheme with exact containment
  arithmetic. Recorded for completeness; no consumer is expected.

- **Identifier (`identifier-dimension`)** — *filed 2026-09-25 with a
  consumer, the first of this list to trip its wire*: values compared
  by **equality only**, no order, no meet except equality. loopmarket's
  `item(h)` names a content-addressed genesis record for a unique item
  (a VIN's hash, a tagger's signed fingerprint) and a want must take
  that item and no other. It passes the criterion trivially (the
  discrete order is a partial order decidable from the names). Why a
  kind and not a node per item: only a declared head lets `is_below`
  decide a same-head pair from the names alone with no node present
  (virtual comparison), and a node per item would move every pinned
  root daily; why not the prefix kind: `startswith` makes the shorter
  value the wider region, so `item(ab)` would cover every item whose
  hash starts `ab` — a want served by an item nobody inspected. Shape,
  about twenty lines: `contains` is `==`, `intersect` is `a if a == b
  else None`, the prefix kind's grammar (a fixed width is *not* asked
  for: no kind has per-head declaration parameters, and under equality
  a short or malformed value matches only itself, so fail-closed comes
  free and rejecting such values is the consumer's lint), space tag
  `identifier`, a `KINDS` entry, **registry 4.4** (a minor, as the
  graph kind's 4.2 was: additive, no canonical name changes; 4.3 went to
  the transitive kind, §16), the kind
  node **outside the prelude** and declared by the consumer's seed (§13's
  own rule for the graph kind, so no pack root moves). Role heads carry
  the variants: `item → identifier-dimension`, `lot → item`, `sample →
  item`, each with its own star and no cross-head comparison (§14).
  Interim: the prefix kind with the consumer refusing non-full-length
  values — forward-compatible, since the prefix kind's canonical form is
  the validated string itself and a later re-declaration of the head
  changes no stored name (the linear → calendar precedent, §4). Filed by
  `loopmarket/docs/plans/items-and-ownership.md` and the cross-repository
  plan `credentials-cover-and-options.md` (D5, D7), 2026-09-25.

None of these are scheduled. The rule stands: kinds are added when a
real workload arrives (the loopmarket precedent), never speculatively.
The identifier kind is the first whose workload has arrived; the
ordinal kind's tripwire (`EVOLUTION.md` §3) has a second vertical as of
the same date, with cumulative naming as the consumers' interim.

## 14. Role heads: parameters that name nodes (issue #15, 2026-09-12)

**The problem.** A role head is a head declared under another head so
that it inherits the value space and the kind: `put("from", ["geo"])`,
`put("when", ["time"])`. Values work at once — `from(u2e4x) ⊑ from(u2e4)`
computes. But places are *nodes*, not values: `my_home` sits under
`geo(u2e4x)`, `ljubljana` sits above `geo(u2e4)` and `geo(u2e5)`. Before
this, `from(ljubljana)` parsed as the literal cell `ljubljana` — a
parameter that *is* a node was silently read as a value that happened to
spell the same, and a region has no single value a consumer could
substitute (loopmarket's `_value_of` workaround covered places only).

**What a role is.** `_dimension_of(head)` walks the declaration chain
upward and returns `(kind, base)`, where the *base* is the head directly
under the kind node. A head whose base is another head is a role of that
dimension. Two consequences of the same walk: **values are leaves of the
declaration walk** — a node filed under `geo(u2e4x)` is not thereby a
head, whatever its name looks like (`shop(1)` under a cell stays an
opaque atom, where before it parsed as a prefix term); and a role with
two bases is refused like a head with two kinds.

**Parameters.** Only role heads look a parameter up — a base head's
parameters are values by definition, however a category happens to be
named, which is loopmarket's guard ("a place called `u2e` must not become
the cell `u2e`") answered structurally. For a role head:

- a parameter naming a **present node in the base dimension** — below its
  head (a place under a cell, a floor under a building, an offer under a
  role value), or above one of its values (a region) — denotes that node;
- a parameter naming a present node **outside** the dimension is refused
  (`ValueError`), never guessed;
- any other parameter is a value of the base's kind, as before.

**Canonical form is the name as spelled.** `from(my_home)` is stored as
`from(my_home)`; the node's position may move with the catalogue, which
is the point (a place whose cell is refined changes no stored name).
There is no value to canonicalize to: a floor has no cell of its own and a
region has no single cell.

**The order.** `R(x) ⊑ R(y)` iff `x ⊑ y` in the base dimension — values
spelled as terms of the base head (`from(my_home) ⊑ from(u2e4)` iff
`my_home ⊑ geo(u2e4)`), nodes as themselves. So a place is below the
cells above it and below every region containing those cells; a region
is above the cells it covers and everything finer; two floors of one
building are siblings although they share a cell. One combined order,
everywhere: `is_below`, `get` (virtual and present role terms alike),
reduction, `remove`'s contraction, the lazy reader, certificates.
Two rules that fall out of monotonicity (CONTRACT G2):

- **A region's covering is a lower bound only.** Its cells are what it is
  *known* to cover; `from(ljubljana) ⊑ from(u2)` is False until someone
  files the region under `geo(u2)`. Reading the covering as an upper
  bound would let a later cell flip a True answer to False.
- **Same-head role terms never pre-intersect as meets.** No single term
  names `from(my_home) ∩ from(u2e5)`; when one contains the other the
  planner keeps the finer, otherwise both stay separate cones. The
  disjoint-parents guard likewise refuses provably disjoint *values*
  only — the graph cannot prove two named places apart (the disjointness
  wall), so a place and a cell it is not known to lie in are accepted.

**Overlap.** `get_overlapping` and `overlaps` (#16) decide value pairs by
arithmetic; nodes are individuated by the graph: two named things
overlap when one is below the other, or when what one is known to
**cover** (the values below it) meets what the other lies within or
covers. Deliberately excluded is upper × upper — two distinct places
under one cell are two places, not one — so a ground-floor courier and a
fourth-floor want never match, while a give to the whole building serves
the fourth floor (the floor is below the building). This is Peter's
third-coordinate case (issue #15's comment): a floor is a sub-place node,
`my_home_4th ⊑ my_home ⊑ geo(u24mc)`, and "floors 1–4" is a region node
above four floors — the same device as a region above cells, no metric
invented. A by-product fixed on the way: `get_overlapping` used to walk
*computed* hops below an overlapping anchor and so returned items under a
finer value that provably does not overlap (`weight(0.9kg)` under
`weight(0.8kg..1.5kg)` against `weight(1kg..)`); it now walks asserted
edges below each anchor, finer values being anchors in their own right.
Completeness for possibility (G6) is kept; the walk stopped inventing it.

**Stored form stays canonical (I3, I7).** The order of role terms follows
the catalogue, so filing a place or growing a region can make an asserted
edge redundant *after the fact*: `ride ⊑ from(ljubljana)` and
`ride ⊑ from(u2e6)` are both kept while `u2e6` is outside the region;
adding the cell makes the first redundant, and no rectangle around the
new edge sees it (the computed hop is a wormhole between the role's star
and the base dimension). `add_edge` therefore ends with
`_reduce_roles_touching`: every node whose position the edge changed —
`to` and what is below it gained ancestors, `from` and what is above it
gained descendants — is checked for role terms naming it, and each such
term's computed hops are re-reduced through the same rectangle. Tested
against direct filing in both natural shapes (a region grows; a place's
cell is refined), as byte-identical eager roots across orders, as merge
commutativity, and as sparse-writer = eager-writer roots. Cost: nothing
when the graph declares no role; otherwise `|touched| × |roles|` name
lookups per edge.

**Interpretation depends on the catalogue, so three guards keep it
stable.** A role-named node cannot be `remove`d or cone-deleted while the
term stands (the term would turn into a literal spelling the same, or
stop parsing at all — remove the term first); `reclassify` refuses to
move it out of its dimension; and `put` refuses to *create* a category
whose name a role term already carries as a literal unless the new
category lands inside the dimension — inside, the literal becomes the
node and the reduction pass follows (a store where `from(my_home)` was
filed before the place existed heals itself when the place is filed).
Replays (`merge`, `sync`) add nodes before edges, so inside them a not-
yet-placed node is read as an isolated node rather than refused; the
final state is the peer's, which was valid. Interpretation can loop
without the graph cycling (deciding whether `offer` is in the dimension
walks through the role star that contains `from(offer)`), so the lookup
is re-entrancy-guarded and reads a re-entered parameter as a literal.

The move and create guards apply to roles of a value dimension only. A
head that the graph orders (§15–§18), declared under another head
(`courier ⊑ transport`), names nodes by constraint, as its base does, so
moving a node one of its terms names is as free as under the base. Until
2026-10-07 the guards took such terms for roles and refused both.

**Removal is guarded for every term (decided with Peter, 2026-10-09).** A
category may not stop existing while any term names it — a role's, the graph
kind's, a relation's — because the term would be left naming nothing: after
`remove paris`, the Louvre (`in(paris)`) silently stopped being in France,
and a share naming a removed contact came back by itself when the contact
was added again. `remove` and `remove --cone` refuse, naming the terms and
what is filed under each, unless the terms go too: named in the same
command, or all of them with `--with-terms` (`with_terms=True`). A term that
goes is contracted as `remove` contracts any category: what was under it
moves to **the terms just above it**, made by replacing the removed category
with each of its own parents (`in(paris)` → `in(city)`, `in(france)`; under
the relations that follow containment a parent `in(Z)` gives `Z`; a
compound keeps its other constraints, `in(museum-district paris)` →
`in(city museum-district)`, `in(france)`), each candidate kept only where
the order puts it above the term, and the lowest of those. The same rule
holds for a term removed on its own. A **share never widens**:
`shared-with(person)` is *below* `shared-with(alice)` in the reversed order,
so no candidate survives and a share naming a removed person or group goes
to the bare head, which reaches nobody. The other way out is `rename OLD
NEW`, for a name that was the mistake: everything under the category, its
placement and every term naming it follow (`in(pairs)` → `in(paris)`), and
an existing NEW absorbs OLD. Both are local, like every removal: a peer that
still has the category brings it back when merged. Stores written before
this can hold terms naming nothing; they load, and nothing is inside what no
longer exists. Tests: `tests/test_removal_terms.py`, and the three-writer
differential in `tests/test_crosskind.py`.

**The dimension itself is not a parameter (issue #17, 2026-09-12).** The
base head is a node of its own dimension, so #15's rule would let a role
name it — `from(geo)`, `when(time)` — and read it as the whole space.
loopmarket asked for exactly that, to file a give silent on `from` under
"from anywhere" so an overlap term could reach it. Built for an hour, then
undone on Peter's rule: *when something is unconstrained it should not be
visited at all; the other constraints give the result* — and *the overlap
of everything with A is just A*, so a term for the whole space is never
more than a redundant edge beside anything finer. The answer is in §8: an
overlap term constrains only candidates that state a value of its head,
so an item that says nothing under `from` IS from anywhere, with no edge
at all. `from(geo)` is therefore refused, with the reason ("`geo` is the
dimension itself, not a value or a place in it — an item that is from
anywhere states no from(...) at all"). A base head's own parameters stay
values (`geo(geo)` is the literal prefix `geo`): only roles look names up.

**Cost (issue #18, 2026-09-12).** `_dimension_of` — the declaration walk
from a head to its kind — is asked once per star member on every
containment or overlap decision, and role stars make those decisions
graph walks; on a names-heavy graph that was tens of thousands of walks
per query. It is now cached per DAG and dropped exactly when `_heads` is
(an edge from a kind node or a head to a plain node; a node ceasing to
exist), so filing items and values never clears it. Absent names are not
cached and an ambiguous declaration raises uncached.

**Deferred, recorded here.** Peter's refinement in the issue — a
*covering as a value*, `where(u24m+u24q)`, a set of cells with no node
and therefore no name — is not built: it is a grammar change to the
prefix kind (canonical form = sorted minimal set), and region nodes
answer the named case today. It fires if anonymity of regions becomes
the tripwire. Performance: a role star's containment checks are graph
walks rather than string arithmetic, which made a large role star slow to
query until its hops were found by name (§19, 2026-10-07).

## 15. The graph kind: constraints on the graph itself (issue #19, 2026-09-13)

**The case.** loopmarket's courier offers `transport(small-item
weight(..8kg))`; a wanter writes `transport(bicycle weight(5kg))`. The
argument of `transport` is not a value of some arithmetic space — it is a
set of *constraints on the graph*: categories a thing must be under and
terms of other dimensions it must satisfy. Whether the wanter's argument
fits the courier's is a question the graph already answers (`bicycle ⊑
small-item`, `weight(5kg) ⊑ weight(..8kg)`); what was missing was a term
grammar that lets a head take such an argument, and the ordering of two
such terms. Which side must be inside is the consumer's rule (loopmarket
reads the argument as what an operator *accepts*, so its want is inside
its give); ontodag only orders.

**Declaration.** A head under the kind node `graph-dimension`:
`odag put graph-dimension dimension`, then `odag put transport
graph-dimension`. The kind is deliberately **not in the prelude**:
adding a node to the prelude moves its golden root and, through `core`,
the root of every pack and every published pack store — a cost the
everyday dimensions justified and a kind only operator vocabularies use
does not. A store that needs it declares it, like any other seed line. Roles work as for every kind — a head under
`transport` is a role of it with its own star; role parameters are never
looked up as nodes here, because every constraint *is* a node or a term.

**Grammar.** `H(c1 c2 ...)`: constraints separated by whitespace at
parenthesis depth 0, so a nested term stays whole. Each constraint must be
a present category (kind nodes excluded) or a term of a declared
dimension, else the term fails closed (`transport(unicorn)` raises).
Canonical form: each constraint canonical (`weight(8000g)` →
`weight(8kg)`), deduplicated, sorted; at least one constraint. A
**redundant** constraint — one that another constraint of the same term
already implies (`transport(bicycle small-item)` with `bicycle ⊑
small-item`) — is **dropped**: the term is spelled `transport(bicycle)`,
since one denotation gets one canonical name (I1: distinct canonical
names are never mutually contained, which keeps the computed order
acyclic). Until 2026-10-08 it was refused instead, for the reason a
whole-dimension parameter is refused (§14, #17); but the graph decides
redundancy, so refusing made whether a write was accepted depend on the
order facts arrived in. Since compound terms are no longer stored (below),
a spelling that follows the graph harms nothing. Replays (merge, sync) run
lenient, like role parameters naming not-yet-placed nodes.

**Order.** `H(X…) ⊑ H(A…)` iff every constraint `A` is above (or is) some
constraint `X` — a thing meeting all of `X…` meets all of `A…`. Fewer
constraints is the wider term; `H(A B) ⊑ H(A)`. Constraints compare by
`is_below` either way (nodes, terms, a node against a term). Terms of
distinct heads are incomparable, as with every kind. The meet of two
same-head terms is the union of their constraints, reduced — never empty,
since categories carry no disjointness (two same-head parents on one item
are admitted and fold to their union; `overlaps` is always true).
`H(A B)` ≡ `H(A) H(B)`: as a query, two cones with the same intersection;
as an item, either spelling files it under the parts (below).

**Stored as parts (2026-10-08).** A graph-kind head relates an item to
ONE thing: a job under `transport(piano)` and `transport(heavy-item)`
moves one thing that is a piano and heavy, which is how loopmarket reads
its terms. So a term with several constraints is never stored: filing
under `transport(heavy-item piano)` files under `transport(heavy-item)` and
`transport(piano)`, and a constraint that is itself a graph-kind term
splits too (`H(G(a b))` is `H(G(a))` and `H(G(b))`). Every part a write
names is materialized, whether or not the graph already relates the parts,
and reduction keeps only the finer ones: at once, or when a later fact
makes one part imply another (re-reduction, §16's mechanism, now covers
the graph kind's heads). Queries answer a compound as the conjunction of
its parts, in `get`, `is_below` and everything built on them.

Why: a compound's canonical spelling follows the graph, while a stored
name never changes. Until this date the parts were folded into one stored
compound (canonical placement, §9), and the same knowledge got two stored
forms. A removal job tagged "piano" and "heavy item" was stored under
`transport(piano)` in a store that knew pianos are heavy, and under
`transport(heavy-item piano)` in one that learned it a day later: roots
`0b24367f…` and `55b70437…`, a third (`cd01999c…`) for their merge, and
two names for one class in the second store. Now all three are
`0b24367f…`. Peter chose this on 2026-10-08 over renaming stored
compounds as the graph grows (names are identity across stores, merges,
provenance and paths) and over reading two terms as two things (that is
the relation kinds' reading, and not loopmarket's). Stores written before
keep their compound nodes: they load verbatim and answer the same
questions, and `ontodag.migrate` replays them into parts. The relation
kinds keep compounds whole, since an item can relate to several things at
once, so a compound there is not its parts; their stored spelling is kept
current instead (§16). A claim about a compound (the agent surface) is
recorded per part too, since a part's spelling never follows the graph.
`tests/test_graph_kind.py` (`TestStoredFormIsOrderFree`,
`TestAgainstTheMeaning`: 25 random worlds, four orders each and a merge,
one root, every answer checked against the one-thing reading).

Answering a compound as its parts needed two planner changes, measured
before they were made. A part is often broad (`transport(mass(..30kg))`
beside `transport(c0)`), and its cone runs through every term inside its
values, each range inside the next, so its asserted count is no guide to
its size: a graph-kind part's planner size is now at least its narrowest
category constraint's count, or the store's size when it names only
values, and a part not yet stored is computed only if walked. So the
narrow part is walked and the broad one probed per candidate. And the
step that drops a query term below another now climbs asserted edges
only; it had climbed the computed order through every containing range
(same-head terms are compared by containment the step before, and a drop
missed costs a cone, never an answer). Offers filed under one category
and one mass range each: 1.8, 11 and 37 ms for `get transport(c0
mass(..30kg))` at 400, 1,600 and 6,400 offers (0.9, 62 and 554 ms
before, with answers missed in the shapes §19 records); filing stays flat
at about 1.2 ms per put (0.8 ms before; an item now has an edge per
constraint).

**The name.** Every node is a category and every typed value narrows a
query, so neither "category" nor "constraint" says what is special here.
What a kind names is *how a head's values are ordered*: linear by
intervals, prefix by string prefix, dominance componentwise, calendar by
periods, count by whole numbers — five orderings computed from the two
names alone. This kind is the one whose values are ordered by the graph
itself, hence `graph-dimension`.

**What it is not.** No defined classes: `transport(small-item
weight(..8kg))` is not a category a bicycle is *under*; it is a term that
*contains* `transport(bicycle weight(5kg))`. And no cross-dimension
computation: a constraint is checked one dimension at a time.

Registry **4.2** (additive: a kind, no canonical name of an existing kind
changes); prelude unchanged (v3); `dimensions.constraints(param)` splits
a parameter for consumers; `split_term` accepts balanced nesting.

## 16. The transitive kind: relations that chain (2026-10-06)

**The case.** "Below" means one thing, inclusion between classes of
items (docs/plans/ROLES.md), so a relation to an entity is filed as a
term rather than as an edge to the entity: `tokyo ⊑ in(japan)`, never
`tokyo ⊑ japan` (Tokyo is a city; Japan is not one). For `in` the order
between terms must chain: once Tokyo is in Japan, whatever is in Tokyo
is in Japan. The graph kind orders `in(tokyo) ⊑ in(japan)` only when
`tokyo ⊑ japan`, which is the very edge the one meaning forbids.

**Scope: places and parts.** These chain together soundly: an engine in
a car in a garage is in the garage. Membership is not `in` (decided
2026-10-06, ROLES.md §5), because chained with location it gives wrong
answers: with Alice `in(sales)` and the sales department
`in(ljubljana-office)`, Alice is located in the Ljubljana office, though
she may work from home. People go under kinds instead,
`alice ⊑ sales-employee ⊑ employee`, and the department (an entity, with
a location) is a different name from its staff (a kind, with members).
The code cannot enforce this, since it cannot tell a person from a
place; it is a modeling rule, for the docs and the surface layer to
teach.

**Declaration.** A head under the kind node `transitive-dimension`:
`odag put transitive-dimension dimension`, then `odag put in
transitive-dimension`. Like the graph kind's, the kind node is not in
the prelude yet; ROLES.md §9 step 3.7 moves the standard heads in once,
together with the pack audit, so golden roots move once.

**Grammar.** The graph kind's: a conjunction of constraints (present
categories or terms of declared dimensions), canonical when sorted and
deduplicated, with a redundant constraint dropped (§15).

**The stored spelling stays current (2026-10-08).** A relation term with
several constraints means ONE thing meeting all of them:
`shared-with(manager sales-employee)` is for the people who are both,
`in(church landmark)` places a thing in a church that is a landmark. So,
unlike the graph kind's, it is stored whole: as two terms it would say
two things, and for an audience it would widen who may see. Its spelling
follows the graph all the same. Shared with `shared-with(employee
sales-employee)` before the org chart said sales employees are employees,
a plan used to keep that name: a second name for
`shared-with(sales-employee)`'s audience (I1), under a root
(`a1201572…`) other than a store's that knew the chart first
(`dbec98f1…`), which refused the spelling as redundant. Now a write drops
the redundant constraint, and when a fact makes one of a stored term's
constraints redundant, what is filed under the term is re-filed under its
current spelling and the old name is dropped (`_respell_stored`, run from
re-reduction, and after a merge or a sync for the compounds either side
brought): both stores are `dbec98f1…`, and so is their merge either way
round. A term naming a re-filed one (`in(in(church landmark))`) follows
it. Peter chose this on 2026-10-08 over keeping relation compounds out of
stored form (which loses "the people who are both") and over leaving the
gap. The price is that a stored name can change, though only from a
redundant spelling to its current one, never to another class: whatever
refers to the node by name sees it move (an ontodag-fs directory, the
node's key in a key plan, replaced on the next publish), and a
provenance claim recorded under the old spelling is not found under the
new one. The old spelling still answers queries.
`tests/test_transitive.py` (`TestTheStoredSpellingStaysCurrent`,
`TestRelationSpellingAgainstOrders`: 30 random worlds of `in`, `about`
and `shared-with` compounds in four orders and a merge, one root, no two
names for one class).

**Order.** `R(X…) ⊑ R(A…)` iff every A is above (or is) some X — the
graph kind's rule — **or some x in X is itself below `R(A…)`**. The
second disjunct is transitivity: `tokyo ⊑ in(japan)` gives
`in(tokyo) ⊑ in(japan)`. It gives `R(R(Z)) ⊑ R(Z)`, never the converse,
which would need everything in Z to be inside something else in Z. On
whole numbers, 4 is less than 5 without being less than anything that
is less than 5; in a store, the Louvre's pyramid filed directly in the
Louvre, in no wing, is in `in(louvre)` but not in `in(in(louvre))`,
while the Mona Lisa in the Denon wing is in both.

**Strict, with a guard.** Nothing is R of itself. A reflexive R would
make `in(in(japan))` and `in(japan)` name one class, and the core gives
each class one name (I1). With x in y and y in x, `in(x)` and `in(y)`
would contain each other, the same violation. `put`, `reclassify` and
`add_edge` refuse any edge after which some x is below R(x). The check
covers the child and everything below it, asking whether the parent is
already below R(that thing); the rest of such a path needs no new edge,
or the cycle check would have refused it. Every way two terms of one
head could contain each other passes through such an x (for a
conjunction, x below R(X) with x in X puts x below R(x), since
R(X) ⊑ R(x)), so one check covers them all. It is asked before anything
is materialized, so a refusal leaves no new vocabulary behind.

**Merges stay total.** Replays (merge, sync) skip the guard, as they
skip role-parameter refusals, because a merge must not refuse: two
stores that are each consistent can union to x in y in x. The merged
store keeps both asserted edges as data. Reduction never prunes on a
cycle (`_prune_rectangle` returns when the pair lies on one), because
every witness path there could run through the edge it would prune;
before that check, such a merge orphaned a node.

**No folding, no meets.** An item can stand in R to several things at
once: Zermatt is in Switzerland and in the Alps, and neither contains
the other. So canonical placement (§9) never folds a transitive head's
terms into one combined term, `meet` names an intersection only when one
term contains the other (and raises otherwise), and `is_below` has no
meet fallback for these heads. The internal intersection still returns
the union of constraints, but only as a witness below both terms, for
overlap; with no disjointness, overlap is always possible.

**Re-reduction.** A transitive term moves when any of its constraints
moves, and a term naming a moved term moves with it (`in(in(japan))`
follows `in(japan)`). So `_reduce_roles_touching` re-reduces those
terms' computed hops after every edge: §14's mechanism, extended. A
photo filed under `in(tokyo)` and `in(japan)` before Tokyo was placed in
Japan ends up under `in(tokyo)` alone, as if the fact had come first.

**Memo.** The transitive rule asks `is_below` from inside containment,
which scans a head's terms and asks containment again; without memory
the cost grew exponentially (seconds on fifteen nodes). Answers that are
pure functions of the graph's shape (`is_below`, graph-ordered
containment, the canonical spelling of graph-ordered terms) are now
memoized against a version counter that `add_node`, `add_edge`,
`remove_edge` and `_forget` bump. Lazy expansion does not bump it: it
reveals an immutable snapshot, so a memoized answer stays true.

**Iterative containment** (2026-10-07). The transitive rule asked
`is_below(x, R(A…))` of each constraint x, which walks x's ancestors and
asks the rule again of each container: a stack frame per level of
containment, so a chain of two hundred places ran out of stack (I6).
`_within` answers the same question with a worklist over containers, and
memoizes every container it settles: a miss settles everything explored,
since each container's search lies inside the one just exhausted, and a
hit settles the path to it. A scan over a head's terms therefore stays
linear. The enclosing rule uses it too. A chain of 3,000 places answers
in 0.15 s (`TestDeepChains`).

**Tests.** `tests/test_transitive.py`. An oracle recomputes the order
from the asserted edges alone, as the least fixpoint of four rules
(§17 and §18 later added one each, for `about` and `shared-with`)
(reflexive, transitive, asserted, the lift), and checks on 40 random
worlds every `is_below` answer between names and `in(name)` terms,
every refusal, and the reduced stored form. Order independence and
merge commutativity run on 25 more; the contradictory merge, Eager roots
across orders, the lazy reader, the sparse writer and certificates have
tests of their own.

Registry **4.3** (additive: a kind; no canonical name of an existing
kind changes). Prelude unchanged (v3).

**A limitation of the graph kind, found while building this, fixed on
2026-10-08** (§15: compound terms are stored as their parts, and the
graph kind's heads are re-reduced). Its folding (§9) made stored form
depend on filing order when constraints became related later: `courier`
filed under `transport(bicycle)` and `transport(small-item)` stored
`transport(bicycle small-item)` if filed before `bicycle ⊑ small-item`,
and `transport(bicycle)` if after. And for a relation that is not
single-valued, the fold changed the meaning: `about(mars)` and
`about(earth)` stored `about(earth mars)`, about one thing that is both,
which is why ROLES.md §9 step 3.3 gave `about` the transitive kind's
treatment instead. A second gap, found while building §18: graph-kind
terms were not re-reduced when a constraint moved. `courier-x` under
`transport(small-item)` and under `bike-courier ⊑ transport(bicycle)` kept
both edges if `bicycle ⊑ small-item` came afterwards, and only the second
if it came first. Both waited for one decision, since fixing either
changes graph-kind stored form.

## 17. The enclosing kind: relations that follow `in` (2026-10-06)

**The case.** `about`, `from` and `to` relate an item to an entity, but
unlike `in` they do not chain: a note about a note about Mars is not
thereby about Mars. What they do is carry the entity's containment up. A
photo about Tokyo is about Japan once Tokyo is in Japan, and a flight
from Tokyo is a flight from Japan. The kind is named for what it
follows: whatever encloses the argument. (It was `relation-dimension`
before release; every head names a relation, so that name did not say
which.)

**Declaration.** A head under the kind node `enclosing-dimension`: `odag
put enclosing-dimension dimension`, then `odag put about
enclosing-dimension` (and `from`, `to` the same way). Not in the prelude
yet (ROLES.md §9 step 3.7).

**Order.** `R(X…) ⊑ R(A…)` iff every A is above (or is) some X — the
graph kind's rule — **or some x in X is itself below `in(A…)`**. The
second disjunct follows the reserved transitive head `in`
(`CONTAINMENT_HEAD`) when a store declares it, and only that head: a note
about Alice is not about her ancestors, however `descended-from` is
declared. Without `in` declared, the order is the graph kind's (without
its folding).

**No guard needed.** Two enclosing terms could only contain each other if
something were inside itself: with x below `in(y)` and y below `in(x)`,
x is below `in(x)`. `in`'s own guard (§16) refuses that.

**No folding, no meets.** A photo can be about Mars and about Earth, so
enclosing terms are multi-valued exactly like transitive ones (§16).

**What adding this kind found in the shared machinery** — all three
found by the oracle in `tests/test_transitive.py`, and the first two
affected the transitive kind of §16 too:

- *Re-reduction missed terms below a moved term.* With n3 under
  `in(n4)`, filing n4 under n1 moves `in(n4)` inside `in(n1)`, so n3 is
  in n1 and `about(n3)` moves inside `about(n1)`. The fixpoint now adds
  the descendants of each moved term to the moved set.
- *Re-reduction skipped terms the new edge itself touched.* `about(n3)`
  sat above n1, so it was already in the starting set and was never
  checked on its own, though its constraint had moved. Being touched by
  the edge and having a constraint move are now tracked separately.
- *A provisional answer was memoized as final.* The enclosing rule asks
  containment across heads, and deciding where a term sits can ask
  about the very node whose ancestors are being walked. The re-entrancy
  guard answers that inner question "no" to break the loop; the outer
  question still finds its answer through other branches, but the inner
  "no" was being cached, and a later query read it (a wrong `is_below`
  answer that depended on what had been asked before). Answers computed
  while a guard tripped are no longer memoized (`_trip`,
  `_memo_put_unless_tripped`). That alone made queries slow again, so
  `is_below` now searches only paths that can matter: a bound that is a
  term is tested by containment against the subject's same-head
  ancestors directly (containment is transitive), and a term's computed
  hops are walked only if some term of its head is filed under
  something other than the head (`_escapes`, `_lean`); otherwise those
  hops lead only to more terms of that head, then the head, the kind,
  `dimension` and the root.

**Tests.** `TestRelations` (nine), and `about` facts in the oracle's
random worlds. A one-off run of the oracle checks on 300 larger worlds
found no disagreement in refusals, answers, stored form, order or merge.

**`geo` and `in` stay apart for now** (decided 2026-10-06, ROLES.md §8).
loopmarket's model (§14) is consistent with the one meaning when read as
location classes: `geo(u2e4)` is the things located in that cell, a
place under a cell is located there, and a region above cells is the
class of things located in the region. What it must not do is also file
a region as an entity (`ljubljana ⊑ city`). The two meet by assertion:
filing a cell under a named place, `geo(u2e4) ⊑ in(ljubljana)`, puts
whatever is located in the cell, at any precision, `in(ljubljana)`, and
Ljubljana stays a city. The reverse is not derived: something
`in(ljubljana)` is not thereby in any cell. The target, once a consumer
needs named places and cells in one query, is a rule that lets `in`
follow cells. That rule became sound only when membership left `in`
(§16): a member of a department is nowhere on the map.

## 18. The reversed kind: audiences (2026-10-06)

**The case.** `shared-with` relates an item to the people it is meant for, and
access runs against membership: what is shared with a group is shared with each member.
So the order of `shared-with` terms runs against the graph. Once Alice is a sales
employee, `shared-with(sales-employee) ⊑ shared-with(alice)`, and whatever Alice may see
is the one cone below `shared-with(alice)` (ROLES.md §6–§7). Every earlier kind
orders its terms the way their arguments are ordered; this one reverses
it.

**Declaration.** A head under the kind node `reversed-dimension`: `odag
put reversed-dimension dimension`, then `odag put shared-with
reversed-dimension`. Prelude v4 will declare it (ROLES.md §8 item 15).
The name is `shared-with` (ROLES.md §8 item 18; it was `for` while
unreleased, a word too often used for purpose); no code refers to it.

**Order.** `R(X…) ⊑ R(A…)` iff every X is above (or is) some A: the graph
kind's rule with the two sides swapped. A parameter names a class of
people as a conjunction, so `shared-with(manager sales-employee)` is for the
people who are both, and `shared-with(sales-employee) ⊑ shared-with(manager
sales-employee)`: what is for every sales employee is for the sales
managers. A redundant constraint is dropped, as for the graph kind,
since it is the parameter's class that counts, whichever way the order
runs; a stored one is re-filed under its current spelling (§16).

**Kinds only, never `in`.** Membership is said by kinds (§16, "Scope"),
and the reversed rule follows the plain order alone. Following `in` would
turn a location fact into an access grant: whoever filed Alice as living
in Tokyo would give her whatever is `shared-with(japan)`.

**No folding, no meets.** A budget can be for sales and for finance, and
the union of two audiences has no single name; the conjunction
`shared-with(finance-employee sales-employee)` names the people in both, which is
a wider class of items, not the meet. So reversed terms are multi-valued
like transitive and enclosing ones: never folded, and met only by
containment (`meet(shared-with(acme-employee), shared-with(sales-employee))` is
`shared-with(acme-employee)`).

**No guard of its own.** Two `shared-with` terms contain each other only if their
parameters do, which takes a cycle the ordinary check refuses, or a
redundant constraint, which the spelling drops (§16).

**Terms of every kind the graph orders go only under their head**
(graph, transitive, enclosing, reversed). Filing `shared-with(board)` under `secret`
would say that everything for the board is secret: a rule, not a fact
about an item. The contract keeps rules out (CONTRACT.md §5.1), and the
random worlds showed why. With such edges the containment of terms
depends on rules anywhere in the store, and the recursive evaluation went
exponential: with them, 19 of 60 worlds using `in` and `about` hit a put
slower than three seconds, 43 of 60 using `shared-with`, and 38 of 60 using the
graph kind (§15, released in 0.26.0); without them the slowest put took
12 ms. `put`, `reclassify` and `add_edge` refuse such a term under
anything but its head, before anything is materialized; merges and syncs
stay lenient. Peter's ruling the same day: "We expect very large graphs,
so exponential is out of the question." The relation kinds are
unreleased, so for them no stored name is affected; for the graph kind
this withdraws something 0.26.0 accepted, which loopmarket never used
(its suite passes unchanged). Values of the arithmetic kinds still go
under plain names (a region above cells, §14), and so do role terms,
whose random worlds stayed fast either way.

**A stored term parses as itself.** Every parse of a graph-ordered term
used to re-check its constraints for redundancy, including a stored
term's. Two harms followed. Once a folded term's constraints became
related (`transport(bicycle fragile)`, then `bicycle ⊑ fragile`), every
query touching it raised, since 0.26.0. And walks parse each node they
pass, so the checks ran inside walks and recursed into more walks: this,
not the order itself, made 2 of 60 random graph-kind worlds without any
escape exponential too. A present name is now taken as it was stored,
as `_canonical_graph_term` had always promised.

**A loop no pre-check can see.** The cycle check in `add_edge` runs
before the edge exists, so it sees only the computed hops already there,
and an edge can create a new one. With `transport(vehicle)` under a plain
`rush` that is below `transport(bicycle)`, filing `bicycle` under
`vehicle` adds `transport(bicycle) ⊑ transport(vehicle)`, and three
names denote one class (I1). That was possible for the graph kind since
0.26.0 and for role terms since 0.25.0, whenever a term is filed outside
its head. For the graph kind that filing is now refused (above). Role
terms may still be filed so, so `add_edge` checks, after placing the
edge, whether a term whose constraints it moved lies on a loop; if one
does, it removes the edge and refuses, and nothing moves. The check runs
only for heads with a term filed outside the head (`_escapes`: role
heads, and data that arrived by merge), kept as a per-DAG cache that
edges update. It deliberately does not run for a head that is merely
filed under an ordinary node, as loopmarket files `transport` under
`operator`. There it would mistake the graph kind's folding issue (a
stored conjunction that became redundant contains its reduced twin both
ways, above) for a loop, and refuse ordinary facts.

**Cost, measured here and fixed the next day (§19).** Filing cost grew
with the number of terms of each head an edge touches, for every
dimension kind, released ones included, because every computed hop was
found by scanning the head's star. Per put, with 200, 400 and 800 terms: `weight` values
31, 73 and 156 ms (the same in 0.28.0), `in` places 28, 64 and 132, and
`shared-with` people 8, 18 and 39, while a plain DAG stays at 0.1 ms. Bulk loads
are therefore quadratic. Declaring a relation kind doubles the cost on a
store with many values, since re-reduction computes a full cone on every
edge, and that will matter once the prelude declares `in` and `shared-with`
(ROLES.md §9 step 3.7). The fix, output-sensitive hops, is proposed as
its own step before the release (ROLES.md §9).

**Tests.** In `tests/test_transitive.py`: `TestAudience` (nine), and
`TestCertificatesAcrossProcesses`, which verifies certificates for `in`,
`about` and `shared-with` under three hash seeds, since the reversed rule walks
up from the bound's argument as no earlier kind does. The oracle there
gained the reversed rule, `shared-with` facts, and terms filed under plain names
(expected refused) in its random worlds; a one-off run on 300 larger
worlds found no disagreement in refusals, answers, stored form, order or
merge. The loop: `TestNoLoopThroughAComputedLink` (graph kind) and
`TestNoLoopThroughARoleLink` (role heads).

Registry still **4.3**: this cycle's kinds land together, and this one is
additive. Prelude unchanged (v3).

## 19. Computed hops without scans (2026-10-07)

**The case.** A computed hop, one term of a head inside another, used to
be found by scanning the head's whole star and testing containment
against each term. Walks pass through terms on every put (redundancy,
cycles, pruning, re-reduction), so filing cost grew with the number of
terms per head and bulk loads were quadratic in every kind, released ones
included: with 800 distinct `weight` values, 156 ms per put in 0.28.0.
Peter's requirement (2026-10-06): "We expect very large graphs, so
exponential is out of the question." This is ROLES.md §9 step 4a, and it
closes §12 step 6.

**Hops from the term's own parameter.** On a resident graph (`OntoDAG`,
`EagerOntoDAG`):

- **Interval values** (linear, calendar, count) go through a per-head
  index sorted by lower bound. The values a value contains are a range;
  the values containing it are found among the wide ones alone, since a
  point contains only itself.
- **Prefix values**: the containing ones are the value's own prefixes,
  looked up by name, and the contained ones are a range of a sorted
  index.
- **Graph-ordered terms**: candidates come from walking near the term's
  constraints (their ancestors for the terms above a covariant term,
  their descendants for those below, the other way round for `shared-with`; what
  is filed in a transitive term; the containers of an enclosing term's
  argument). They are looked up in an argument index (constraint → the
  terms naming it) that `add_node` and `_forget` keep. Each candidate is
  then checked with `_contains`, so a candidate too many costs a check,
  never a wrong hop. When the walk would be larger than the star, the
  star is scanned instead.
- **Role terms**: the base dimension is walked from the parameter and
  both spellings are looked up (`from(my_home)`, `from(u2e4)`), the
  literal ones also by prefix, through a sorted index of the role's
  literal parameters.

Hops are complete under closure rather than at every step: a walk that
follows them reaches every term above or below, which is all any caller
does.

**Writes ask questions instead of enumerating.**

- Anchoring a freshly used term under its head makes nothing redundant,
  moves nothing and closes no loop (any path through it existed already,
  containment being transitive), so it costs only its count deltas.
- `add_edge`'s redundancy and cycle checks are `is_below` questions.
- Pruning iterates the lower end's parents with `is_below` tests rather
  than enumerating the upper end's whole ancestry.
- The strictness guard walks the parent's containers once, and not at
  all for a new place.
- Re-reduction looks up, in the argument index, the terms naming what
  the edge put under something new, and follows the terms it finds to a
  fixpoint (`_moved_terms`).

**Found and fixed on the way.** `is_below`'s meet fallback (a subject
under several values of one head) computed the subject's full bounds,
walking every combined ancestor of every head and recursing through the
same fallback. A nine-node graph-kind world with self-referential
conjunctions took 4 s (30 s before this work); it now takes the meet of
the values its own walk met, in 0.02 s. And the first version of the
strictness guard's fast path let `x ⊑ in(x)` past the check that runs
before anything is materialized, so a refusal left `in(x)` behind. The
stress run caught it, after the commit had been pushed, and the oracle
now asserts that a refusal leaves nodes and edges untouched.

**Measured.**

| shape | 200 terms | 800 terms | 3,200 terms |
|---|---|---|---|
| `weight` values, per put (0.28.0: 31, 156 ms, …) | 0.8 ms | 0.8 ms | 0.9 ms |
| `in` places, per put | 0.6 ms | 0.6 ms | 0.6 ms |
| `shared-with` people, per put | 0.3 ms | 0.3 ms | 0.3 ms |

loopmarket-shaped offers (graph-kind terms with value constraints, a
role over geo, dates) file in 1.8 ms from 300 to 2,400 offers. A chain of
places filed top-down costs 0.22 ms per put at depths 100 to 1,600 (the
day before, 136 ms at 1,600; before that, a RecursionError). Queries
whose answers stay small cost the same at 400 and 6,400 items, and
`get from(ljubljana)` grows with its answer: 8, 34 and 115 ms for 75, 300
and 1,200 (before, 100 s at 6,400). Merging two stores costs 0.28 ms per
merged node at every size.

**Found and fixed later (2026-10-08).** Two shapes the name-directed
hops missed, so on a resident graph `get` could answer less than
`is_below` (and less than a lazy reader, which scans). A value named only
inside a term is not a node, so no walk met it: with things filed under
`transport(mass(..5kg))`, `get transport(mass(..8kg))` answered nothing. The
values that present terms name as constraints now have an index per head,
like a star's, consulted wherever a walk meets a value. And a graph-kind
term nesting a graph-ordered term (`transport(option(b))` above
`transport(piano)` when piano ⊑ option(a) ⊑ option(b)) is reached by no
hop; a head with such a term scans, as does any head whose terms name a
value no index covers. Re-reduction follows nested constraints that are
not nodes too. Neither showed in the random worlds, which never made a
value-only constraint or a nested graph-kind term;
`TestGraphKindAgreesWithTheScan` now makes both.

**What still scans, deliberately.**

- A lazy reader and the sparse writer, which pay a fetch for every name
  they look up, and whose stars are what they would fetch anyway.
- The dominance kind.
- An edge that moves a whole region or group, which pays for what it
  moves: moving Japan into Asia moves everything in Japan. That cost is
  proportional to the region, not to the store.

**Tests.** `tests/test_hops.py` runs the name-directed hops against the
scan they replace on random worlds over every kind (conjunctions, value
constraints, virtual query terms; roles with places, regions and both
spellings), requiring the same stored form and the same answers, and it
pins that filing never walks a star, whatever the store's size. One-off
runs of 200 larger worlds of each found no disagreement. The 300-world
oracle of `tests/test_transitive.py` found none either. The live Bee
tests passed on bee 2.8.2, and loopmarket's suite passes against this
tree (297 passed).

## 20. Narrower relations (2026-10-07)

**Status.** ROLES.md §9 step 5. Built overnight on a branch in the form
below, which was a proposal, since the declaration form was an open
question (ROLES.md §8). Peter chose it the next morning, and it landed
with contract 0.3 (CONTRACT.md §5.1).

**The case.** A departure is a narrower kind of "from": a flight
departing from Heathrow is from Heathrow, so `get from(lhr)` should find
it. Without a declaration, `departure` and `from` are two unrelated
relations, and stores that name the same thing at different precision
never meet. Narrower relations make free naming safe: one person's
`departure` and another's `departs`, both declared narrower than `from`,
meet at `from(lhr)` (ROLES.md §4).

**Declaration: a head of a relation kind filed under another head of
the same kind.** `odag put departure from`, with `from` under
`enclosing-dimension`. For the kinds over nodes this is the only reading
the edge can have. A role takes its base's values (§14), but a relation's
argument is any node already, so "uses that space" adds nothing. And
`departure(lhr) ⊑ departure ⊑ from` already reads correctly at the head
level: whatever has a departure has a from. Value roles (`max-load`
under `weight`, `posted` under `time`) keep the role reading. So does
the graph kind, whose conjunctions fold (§15): `R(x)` with `S(y)` and
`R(x)` with `S(x y)` would denote one class and be stored two ways, so
a narrower graph-kind head waits for the folding question (§16, "Known
issue"). The alternatives considered were a declaration node (`narrower(
departure from)` under a registry node, the unit-declaration pattern)
and a marker kind node beside the edge. Both say the same thing as the
edge, and both leave the head-level reading to be computed.

**Order.** For heads R under S (directly or through a chain of heads),
`R(x) ⊑ S(y)` exactly when `S(x) ⊑ S(y)`, since `R(x) ⊑ S(x)` and
nothing else relates the two heads. A broader term is never inside a
narrower one: something from Heathrow need not depart from it. Each head
keeps its kind's rule. A transitive narrower relation chains through its
own terms and those narrower than it. `x ⊑ inside(y)` puts x `in(y)`;
`x ⊑ in(y)` does not put it `inside(y)`. And since the enclosing kind
follows `in`, it follows `in`'s narrower relations too.

**Terms that were never filed.** In one head, the terms a chain passes
through always exist, since something is filed under each. With a
narrower relation they need not. From `x ⊑ inside(z)` and `z ⊑
inside(y)`, x is in y through `in(z)`, which nobody filed. `is_below`
was right from the start, because its containment walk goes through
places, not terms (`_within`). The hops were not: they are complete
under closure only if the intermediate terms exist. Upward, a missing
broader term is looked past, to what its argument is below or inside.
Downward, what is filed in each narrower term found is chased to a
fixpoint, except where the broader term exists and its own hops cover
it. Both are worklists, so deep chains stay iterative (I6). The
scan-differential test (`TestAgreesWithTheScan`) found this; the oracle
had not, at its smaller world size.

**Declaring late.** Filing `departure` under `from` after terms of both
were filed changes the order of terms already stored. An item under
`departure(lhr)` and `from(lhr)` now carries a redundant edge that
filing in the other order would never have stored. So the declaration
re-reduces the terms of the heads it makes narrower, at a cost
proportional to them: 390 µs per item, linear from 400 to 6,400 items.
For a transitive relation, the declaration can also put something inside
itself. `x ⊑ inside(y)` and `y ⊑ in(x)` were consistent while `inside`
was a relation of its own, and give `x ⊑ in(x)` once it is narrower than
`in`. `put`'s guard looks only at the parent's containers, so it cannot
see this. Any such loop passes through a term of the newly narrower
head, so their arguments are checked after the edge is placed. On a
refusal the edge is removed and whatever pruning dropped is put back
(the old kind edge, typically). The check runs after pruning because
until then the head belongs to two dimensions at once. Merges and syncs
stay lenient.

**Candidates and meets.** Categories carry no disjointness, so a term
and a narrower one always overlap. `get_overlapping(about(lhr))` lists
what is under a narrower term, as G6 requires (it is complete for
possibility). `meet` names the finer term when one contains the other,
and raises otherwise, as for one head.

**Measured.** Filing stays flat: `inside`, `editor` and `topic` terms
cost 0.3–0.4 ms per put at 200, 800 and 3,200 terms, as `in` and `shared-with`
do. A chain of 3,200 places, each filed only `inside` the last (so no
`in` term exists), answers `get in(p0)` with 6,400 results in about a
second. Building that found a quadratic in the planner's walk of a
virtual term, now fixed on main as well (CHANGELOG, "A query over a
virtual value no longer re-walks nested values").

**Tests.** `tests/test_narrower.py`. An independent fixpoint oracle over
seven heads in three kinds, with `subtopic ⊑ topic ⊑ about` as a chain:
answers, refusals (refused puts leave nothing behind), stored form, and
`get` for every term. Also filing order, merge, declaring late versus
early, the refusal of a declaration that puts something inside itself,
the scan differential, the lazy reader, the sparse writer, and
certificates verified under three hash seeds. One-off runs of 500 larger
oracle worlds and 150 scan-differential worlds found no disagreement
after the two fixes above.

## 21. Family pins: a head states its unit family (2026-10-07)

Until now a linear or count head took its unit family from its first value:
a store whose first `weight` was `weight(10N)` held force under it and
refused `weight(3kg)`. Nothing in the store said which family a head meant,
so two stores could choose differently, and merging them crashed (below).

**The rule** (ROLES.md §8 item 21). A head is *pinned* by filing it under a
family-narrowed kind node:

```
mass ⊑ linear-dimension(mass) ⊑ linear-dimension
```

- A family node is recognized by its name alone, as the kind nodes are:
  `KIND(FAMILY)` for the kinds whose values carry a family (linear, count).
  Filing under one that is missing creates it under its kind, as a value
  is created under its head.
- A pinned head takes only values of its family. A new value or a query
  term of another family is refused, naming both families; a stored value
  parses as stored.
- Pinning a head that already holds values of another family is refused.
- A role inherits its base's pin.
- The family must be one the store knows: built in, or declared with
  `unit-family(NAME)`. Two pins on one head (after a merge) and a pin
  naming no family are refused when the head is used, never by the merge.
- An unpinned head keeps the first-value rule.

**Why in the kind.** Stating a family is subsumption: a head that holds
mass is a linear head of a narrower sort. So `get linear-dimension(mass)`
lists the heads that hold mass, and a store adopts a pin by merge: in a
store that said `mass ⊑ linear-dimension`, the new edge makes the old one
redundant and reduction prunes it. A declaration node beside the head
(`family(mass=mass)`, the unit-declaration pattern) was the alternative;
it would have needed parsing to answer the same question.

**Merge stays total across families.** Found while deciding this: merging a
store whose unpinned head held newtons into one whose head held kilograms
raised `unit families differ` inside `merge`, breaking I7 (released bug).
During a merge, values of different families now count as not containing
each other, which is true of their denotations, so the merge completes and
is the same in either order. Comparing them afterwards is refused, so the
disagreement is reported at first use, as conflicting kinds are.

Tests: `TestFamilyPins` and `TestMergeStaysTotalAcrossFamilies` in
`tests/test_dimensions_dag.py`.
