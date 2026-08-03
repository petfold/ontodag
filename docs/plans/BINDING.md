# Binding: Roles, Bundles, Multiplicity, and the Depth Question

Status: **discussion draft, 2026-08-03 (prompted by Peter's sequence of
probes: the London→Rome ticket → the two-leg journey → the bouquet with
2 red and 3 white roses and a blue tulip). Nothing here is decided; §9
collects the open questions.** This document exists to be argued with,
and to gate any grammar extension: the standing decision (CONTRACT.md,
agreed at 0.1) is that **the core gains no further expressiveness**, so
everything in §4–§6 is a *proposed scoped amendment*, brought to the
contract table — not grammar work to be started. It is also the evidence
file for the parked "EL/relations canonicalization" research item in
`DATABASE_DIRECTION.md`: two genuine consumers have now shown up (§2,
§5), which is what that item's tripwire was waiting for.

## 1. The scope rule for flat roles (what already works, and why)

The London→Rome worked example needs no new machinery:

```
odag get transport 'from(EU-UK-London)' 'to(EU-IT-Rome)' 'duration(..10h)'
```

Three coordinates as three supercategories *is* the product lattice, and
plain intersection answers it — flights, trains and buses alike, since
anything filed below `transport` is in the cone whatever its mode.
`duration(..10h)` is a virtual query term; computed containment puts
every stored `duration(X)` with X ≤ 10h below it at query time, no
edges. `from`/`to` are roles spelled as distinguishable category heads —
and if declared as **prefix-kind** dimension heads over geo-style paths,
`from(EU-UK-London) ⊑ from(EU-UK)` is computed too, so the role
hierarchies come free rather than needing a duplicated geo tree.

The nested spelling `transport(from(London), to(Rome), duration(..10h))`
is surface sugar over that conjunction. The v1 grammar deliberately
rejects it (`split_term`: no nested parens, one head one parameter); if
the spelling is ever wanted, it is an `elaborate()` job — expand to the
conjunction before the core, never store the nested name.

This works **not by luck but by a scope rule**, which should be
documented wherever the worked example lands:

> **Flat roles are sound for one filler per role per item.** Beyond
> that, composition is a query-layer join, not a bigger name.

## 2. Where it breaks: the grouping problem

The two-leg journey — transport from A to B, then walk from B to C — is
exactly where flattening fails, and the failure is precise: **an item's
supercategories are a set, so the pairing of role fillers is lost.**
A journey filed under `{from(A), to(B), from(B), to(C)}` is
indistinguishable from a journey `{from(A), to(C)}` with a middle leg
`{from(B), to(B)}`. The fillers survive; the *grouping* does not.

This is the classic role-grouping problem for flat feature sets — the
reason description logics have relational structure at all — and it is
the already-recorded **arbitrary-relations wall**
(`DATABASE_DIRECTION.md`, "Arbitrary relations (roles)", with its
tripwire: users mass-reifying relation nodes). Nothing in this document
retracts that wall. What the rest of the document examines is a strip of
territory *in front of* it that the two-axis criterion (monotone +
computable from names and local structure) turns out to admit.

## 3. What stays inside the current model (no amendment needed)

- **Legs are the items; journeys are joins.** The multi-leg search is
  `get(transport, from(A), to(x))` composed with
  `get(walk, from(x), to(C))` on the shared endpoint — a query-layer
  join. The core deliberately has no variables; the join lives in the
  consumer. This pattern already carries real weight: **loopmarket's
  entire job is finding chains and cycles of compatible offers** over
  OntoDAG queries. A route planner is the same shape (a path instead of
  a loop).
- **A stored itinerary is still an honest item.** The composite journey
  legitimately is-a `transport`, `from(A)`, `to(C)`,
  `duration(11h30min)` — all true of the whole, all queryable. The leg
  *sequence* goes in `payload`, because "consists of leg 1 then leg 2"
  is parthood, not subsumption. The cost is real and must be named: you
  cannot lattice-query "itineraries whose second leg is a walk".
  (The composite's `from`/`to`/summed duration are *derived* from the
  legs — the parked computed-values item's second consumer appearance.)
- **The workaround not to recommend**: positional role heads
  (`leg1-from(...)`, `leg2-from(...)`). Tolerable for a fixed small
  schema (outbound/return), degenerate for arbitrary chains — it is
  precisely the mass-reification tripwire pattern.

## 4. The proposed strip: ground bundles (binding one level down)

The admissibility criterion never mentions nesting. A **ground** nested
term — `leg(from(EU-UK-London), to(EU-IT-Rome))` — is still one name.
Its containment order is componentwise: drop unmentioned coordinates,
contain the mentioned ones, each coordinate decided by machinery that
already exists (prefix containment for the paths, linear order for
values, the graph's order for plain category coordinates — see the fork
in §6). Its canonical form is "sort bound roles by head name,
recursively" — the same move that already makes `put(X,[A,B])` and
`put(X,[B,A])` converge (I3). Subsumption of ground description trees is
homomorphism-shaped and polynomial.

And one level of bundling is precisely what fixes §2: the journey sits
under `leg(from(A), to(B))` **and** `leg(from(B), to(C))` — two distinct
names, each carrying its own internal binding, coexisting in one set
with nothing mixed up. "Journeys with some leg departing the UK" is the
virtual term `leg(from(EU-UK))`. Set semantics of supers gives the
existential reading ("has *some* leg such that…") for free.

**Depth is not the wall.** There is no cliff at 3 or at 7: a ground term
of any depth is one name, canonicalized by recursive sorting, compared
by homomorphism, monotone throughout. What grows with depth is *cost* —
name length, proof size, human legibility — not kind. (Practical smell:
depth beyond 2–3 usually means encoding things that want to be separate
items joined at query time.) The wall is crossed by **variables,
coreference, and axioms** — never by nesting deeper:

- **Coreference/variables** — storing "leg 2 starts *where leg 1 ends*"
  as a constraint, rather than both happening to be ground `B`, is a
  shared variable, i.e. a join; it stays in the query layer forever.
- **Sequence and multiplicity of same-name supers** — supers are a set:
  leg order is lost, a duplicated identical leg collapses. Ordering
  stays in payload; multiplicity has its own answer (§5).
- **Axioms** — per the 2026-08-01 EL refinement: ground nested *terms*
  keep subsumption name-computable; a nested *axiom set* would need its
  entailment closure canonicalized. Ground values yes, schematic
  statements no.

## 5. Multiplicity: the bouquet

"2 red roses, 3 white roses, 1 blue tulip" is the multiset probe — the
thing plain set-of-supers loses. The standard move applies: **a multiset
is a set of (kind, count) pairs**, and counts already exist in the
registry (the dimensionless count family; a `count` head is one
declaration away). The bouquet binds a count into each bundle:

```
put bouquet-17 [bouquet,
                part(red-rose, count(2)),
                part(white-rose, count(3)),
                part(blue-tulip, count(1))]
```

with `red-rose` an *ordinary DAG node* under both `rose` and `red` — the
color does not nest, because multi-parent subsumption is what OntoDAG
already does best. Containment is coordinate-wise: the kind coordinate
by the graph's combined order (`red-rose ⊑ rose ⊑ flower`), the count
coordinate by the linear order (`count(3) ⊑ count(2..)`), plus
drop-unmentioned-coordinates. Queries that fall out, all virtual, no
writes:

- "at least 2 roses of some kind" — `part(rose, count(2..))` ✓
- "contains a tulip" — `part(tulip)` ✓
- "at least 3 white flowers" — `part(white-flower, count(3..))` ✓

Three limits, each landing on an already-named wall rather than a new
one:

1. **Cross-line totals.** "At least 4 roses *in total*" is 2+3 summed
   across bundles — aggregation, explicitly behind the wall
   (cross-dimension computation, `DATABASE_DIRECTION.md`). Per-line
   thresholds are computed; totals belong to a higher layer at a pinned
   root. The representation is *sound but incomplete* for totals, and
   must say so.
2. **Exactness.** "Exactly 2 red roses and nothing else" is
   closed-world. The store's reading is monotone — "contains at least
   these" — and the exact-composition question is the as-of clause's
   job: enumerate the bundle lines at a pinned root.
3. **The parthood residue survives in miniature.** If a merge unions
   `part(red-rose, count(2))` and `part(red-rose, count(3))` onto one
   item, the result is ambiguous between "same grouping, conflicting
   claims" and "two separate bunches, five total". The bundle move
   *contains* parthood ambiguity in one line; it does not abolish it.
   Known residue, same status as remove-loses-to-readd.

## 6. The design fork: where does a coordinate's order come from?

The kind coordinate in `part(red-rose, count(2))` can be ordered two
ways, and the choice constrains everything downstream:

- **From names** (prefix paths — the geo move): bundle containment stays
  a pure function of two names, which is what certificates and the
  current dimension machinery assume. But prefix paths encode *trees*,
  and `red-rose` under both `rose` and `red` is exactly the multi-parent
  case a single path cannot spell. The DAG's defining feature breaks the
  name-only version.
- **From the graph** (delegate to `is_below`'s combined order, which
  already unifies asserted edges and computed dimension order): matches
  the lattice, handles multi-parent, is the same computation the core
  already performs and proves — but bundle subsumption becomes a
  function of names *plus the pinned root*. Heavier: a bundle comparison
  triggers graph walks, and certificates must carry the kind
  coordinate's ancestor fragment (the `certificates.py` closure
  machinery is the template).

The bouquet forces the graph-resolved choice if bundles ever land; this
fork should be taken eyes-open, not discovered mid-implementation. It is
the largest single line item in the cost column (§7).

## 7. Costs, and the partial compile-down

If the amendment were accepted, the engineering bill: product
denotations, recursive canonical ordering (with I3's guarantee restated
for arguments: `leg(from(x),to(y))` and `leg(to(y),from(x))` must
collapse to one name), renderer and `elaborate` support, the
homomorphism-shaped containment check, pack/declaration interaction for
bundle heads, and the certificate closure of §6. None of it is research;
all of it is real work multiplied across every surface that touches
names.

There is also a **cheaper partial compile-down needing no core change**,
worth knowing as the baseline any amendment must beat: the surface layer
mints role-composed heads — `leg-from`, `leg-to` as prefix-kind
dimensions — and files each *leg item* under `leg-from(EU-UK-London)`
and `leg-to(EU-IT-Rome)`, journeys below their legs. Cones being
transitive, "some leg from the UK" already works, computed geo
generality included. Its residue is the same-bundle conjunction at
intermediate generality ("some leg from the UK *to Italy*", the same
leg): intersecting the two cones cannot guarantee same-leg — that is the
meet-substitution guard (`SEMANTIC_CODES.md` §10) — so that query needs
either the leg items themselves as results (arguably the right answer:
query legs, join into journeys) or true nested parsing in the core.

## 8. The map in one box

| territory | status | where it lives |
|---|---|---|
| one filler per role per item (London→Rome) | works today | conjunction of supers; docs-only worked example |
| nested spelling of the above | surface sugar | `elaborate()`; never stored |
| role hierarchies (`from(UK)` ⊒ `from(London)`) | works today | prefix-kind heads; needs the geo vocabulary (PACKS.md) |
| multi-instance grouping (two legs) | breaks flat sets | ground bundles (§4) — proposed amendment |
| multiplicity (the bouquet) | breaks flat sets | bundles + bound counts (§5) — same amendment |
| depth 3 / depth 7 ground terms | admissible in principle | same amendment; cost grows, kind does not |
| cross-bundle totals | out — aggregation wall | higher layer at a pinned root |
| exactness / "nothing else" | out — closed world | as-of clause |
| coreference, variables, leg order, axioms | out — the real walls | query-layer joins; payload; never the core |
| parts and relations in general | out (accepted) | relations wall unchanged; datom-layer escape hatch |

## 9. Open questions (the sheet)

1. **Does the amendment get proposed at all?** Two consumers exist
   (two-leg grouping, bouquet multiplicity) — is that enough tripwire
   evidence, or do we wait for demand from real stores / MCP traffic?
   The compile-down (§7) is the null hypothesis to beat.
2. **The §6 fork**: name-computed vs graph-resolved coordinate order.
   The bouquet forces graph-resolved; is the certificate cost
   acceptable, and does `verify_below`'s fragment-store design extend
   cleanly to bundle coordinates?
3. **Depth policy**: admit any ground depth (the criterion's answer) or
   cap at 2 as product discipline (the smell's answer)? A cap is policy,
   not semantics — where would it live?
4. **Bundle heads and packs**: is `leg`/`part` vocabulary a pack
   (`unit-declaration`-style bundle-head declarations that travel with
   the data), and does PACKS.md's collision analysis carry over
   unchanged?
5. ~~**The count head**~~ **DONE (2026-08-03): registry 4.1 + prelude
   v3** — `count-dimension` kind (whole numbers ≥ 1, teaching refusals
   for zero/fractions/units), `count` head in the prelude, golden root
   re-pinned; design record UNITS.md §11. Note what this does and does
   not unlock: the *count coordinate* of the §5 lines exists now
   (single-count items work: `bq ⊑ bouquet, red-rose, count(12)`), but
   the `part(...)` bundles remain this document's unbuilt proposal —
   and the flat spelling cannot substitute, since three counts on one
   item are refused as provably disjoint (the §2 grouping problem in
   miniature: without a bundle, nothing says which kind each count
   belongs to). The mixed bouquet today is the legs pattern: one item
   per part-line, joined at query time. History of the decision, kept
   because the reasoning generalizes: the
   bare-number family admits all rationals and suffixes are globally
   owned, so natural-number semantics needs a `count-dimension` *kind*
   (per-head constraints don't exist; per-family can't split count from
   ratios) — and the kind edge is permanent, so the choice must be made
   at declaration time. Proposed semantics: value must be an integer
   ≥ 1 after scaling; `count(0)` refused with a teaching error (a zero
   multiplicity is an absence claim — negation, which the open-world
   store cannot mean); no `amount` head (continuous stuff has
   dimensional heads; a second bare-number head would be a G1 synonym
   hazard). See `EVOLUTION.md` §3 (decoupling: the kind can later gain
   an `integer-valued-dimension` parent additively) and its §8.8 for
   whether this proceeds now or waits on the math-pack scope.
6. **Merged-duplicate ambiguity** (§5 limit 3): document as residue, or
   add a convention (one line per maximal kind per writer) knowing
   conventions are unenforceable under merge?
7. **Contract wording**: if accepted, the amendment clause — ground
   role-bundles, no variables, no axioms, coordinate order delegated to
   the combined order at a pinned root — and which guarantee (G-number)
   it lands under.
8. **The worked example now**: the User Guide's London→Rome section
   should state the §1 scope rule and the legs-plus-join pattern; does
   it also *mention* bundles as the identified extension point, or stay
   silent until this document settles?
