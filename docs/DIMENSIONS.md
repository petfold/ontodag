# Dimension Lattices: Parametric Items with a Computed Order

Status: design agreed 2026-07-30 (three-session discussion, Peter + Claude);
**steps 1–5 and 7 of §12 implemented and released the same day (v0.4.0)** —
`src/ontodag/dimensions.py`, the `dag.py` integration, the `LazyOntoDAG`
path, `get_overlapping`, the web REST pass-through, user docs; CLI validated
end-to-end on the native store. Step 6 (per-dimension sorted derived index)
stays parked until profiling asks. This document is the design record;
implementation sequencing is at the end. Read `DATABASE_DIRECTION.md` first
for where this sits in the wall/tripwire discipline — this design is the
fired escape hatch of the "exact arithmetic" wall, recorded there.

## 1. What and why

OntoDAG's order has so far been entirely asserted: `Dog < Animal` exists
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
the DAG's asserted order was always extension inclusion (`Dog < Animal`
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

## 4. Values are integers

Decision 2026-07-30: measured quantities are **integers in a per-family
base unit** — the bank/crypto move (cents, wei). Tiny base units, large
> **Superseded 2026-08-01 (registry v3, `UNITS.md` D9):** values are now
> **reduced rationals of the SI coherent anchor** (`weight(3kg)`,
> `weight(1/2000kg)`, `length(10/33m)`) — the same exactness with no base
> to choose and no future base migration; the full SI + customary unit
> table and all decisions live in `docs/UNITS.md`. The §-references to
> integer base units below are kept as the historical record.
numbers; rendering in friendly units is the UI's job, the canonical name
keeps the integer.

- Input in any accepted unit of the family is scaled exactly to base:
  `weight(3kg)` → canonical `weight(3000000mg)`. If the scaled value is
  not an integer (`weight(0.0005g)` with base mg), the boundary raises —
  no silent rounding, ever.
- v1 unit families (registry content, amendable until code lands):
  mass base `mg` (mg, g, kg, t); length base `mm` (mm, cm, m, km);
  duration base `s` (s, min, h, d); dimensionless base `1` (bare
  integer, head decides meaning). Money/currencies: deferred —
  loopmarket prices in personal tokens, not modeled here.
- Timestamps are the one non-integer linear value space: fixed-format
  ISO-8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`), where lexicographic order *is*
  chronological order — comparison is exact string comparison. Boundary
  sugar: a bare date expands deterministically (range start →
  `T00:00:00Z`, range end → `T23:59:59Z`).

## 5. Storage shape

- **Computed order is never materialized.** Stored structure = asserted
  edges only, exactly today's record schema (`up`/`down`/`count`/
  `payload`/`meta` — unchanged).
- **Anchor edges are schema, not assertions.** Every parametric node
  carries exactly one asserted edge to its head node (`weight(3000000mg)
  → weight`), exempt from transitive-reduction pruning. The star under
  the head is the dimension's existence-and-enumeration index (it is
  what virtual queries and `LazyOntoDAG` walk); the computed relation
  supplies all finer order. Anchoring anywhere else (e.g. narrowest
  present container) reintroduces insertion churn.
- **Reduction modulo the computed relation.** `add_edge`'s cycle check
  and `_remove_unneeded_edges` consult *combined* reachability (asserted
  edges ∪ computed pairs among present same-dimension nodes — finite,
  deterministic). So asserting `parcel7 → weight(3000000mg)` prunes an
  earlier `parcel7 → weight(..5000000mg)` as redundant; without this,
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

Canonical form: no whitespace; integers without leading zeros or `+`;
base unit suffix; full-precision timestamps. Inclusive bounds only in
v1 (exclusivity doubles canonical-form cases for near-zero matching
benefit on exact values; revisit on real need).

**Parse trigger:** a name `head(...)` is parametric only when `head`
resolves to a present node descending from `dimension`. Every other
name remains an opaque atom — full backward compatibility; nothing
changes for existing graphs. Declare the dimension before putting
values (error otherwise). `(` `)` `..` `x` are reserved in new names
going forward. The grammar is defined recursively (terms as parameters)
though v1 kinds are flat. CLI note: parentheses need shell quoting.

Boundary sugar (CLI/web, never the identity): friendly units
(`3kg` → `3000000mg`), bare dates, bare numbers → `number(...)`,
user-defined aliases like `max_weight(x) := weight(..x)` — all
normalized before names are formed.

## 8. Queries

- **Present nodes only.** Parametric nodes exist only when used;
  queries quantify over what is present. "All integers" can never be an
  answer.
- **Virtual terms.** `get(weight(..5000000mg))` needs no such node to
  exist: its cone = the head's present instances (the anchor star's
  `down` list) filtered by containment, unioned with their asserted
  cones. Cost ∝ matching used values; log-time with a per-dimension
  sorted index — **derived, regenerable, never merged**, like every
  other index in this stack. `LazyOntoDAG` gets the same via the head
  record's `down` — bounded fetches, no writes.
- **Planner integration.** Same-dimension query terms pre-intersect
  exactly (within a dimension, meets are real and computable — the one
  place the SEMANTIC_CODES §10 meet-substitution guard does not apply);
  empty intersection short-circuits to the empty result.
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

## 9. Regions and generated sets (agreed 2026-07-30)

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
6. Per-dimension sorted derived index (only if profiling asks) — OPEN,
   deliberately: the tripwire is a measured hot dimension, not this
   sequencing.
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
  political zones ever find a real consumer.
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

None of these are scheduled. The rule stands: kinds are added when a
real workload arrives (the loopmarket precedent), never speculatively.
