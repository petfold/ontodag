# Evolution: How an Ontology Changes — the Top, Refinement, and Retraction

Status: **discussion draft, 2026-08-03 (the top-ontology and Rover
threads with Peter, same session as BINDING.md). Nothing here is
decided; §8 collects the open questions.** The file is named for its
real subject — how committed structure changes over time — of which the
top ontology (§3) is the highest-stakes instance, not the whole story
("it's not about the top really — retract the top", Peter, correctly).
The mechanical claims in §4–§6 were **executed against the current
code** during the session, not asserted from memory.

## 1. The change asymmetry (the criterion everything else follows from)

Two kinds of change exist, and the merge algebra treats them
oppositely:

- **Additions propagate and converge.** New nodes, new parents, finer
  distinctions inserted below coarse ones — all merge cleanly, in any
  order, from any writer, and every replica converges (I7).
- **Interventions do not propagate.** Removing or re-meaning something
  requires every writer to act, and an old peer merging back resurrects
  what one writer removed (the documented grow-only stance). In a
  decentralized ecosystem, corrections converge only by social
  coordination.

Compare the units precedent, which was the *easy* case and was still
painful: registry majors came with (a) a **migration oracle** (same
denotation, new spelling — a pure, idempotent, verifiable replay),
(b) **detectable conflicts** (declarations carry arithmetic that can
disagree loudly), and (c) a **consulted version pin**
(`REGISTRY_VERSION` gates cone indexes and certificates). Plain
subsumption structure has none of the three: repairing a conflated
category needs per-descendant judgment (no oracle), bare name edges
merge silently (no detection, PACKS.md §3), and nothing consults "which
top is this store on" (no pin).

The asymmetry reduces to one sentence: **vagueness is repairable by
addition; wrongness is not repairable at all.** A category that is
coarse-but-true can be refined forever (§4). A category that is false,
or one name carrying two meanings, can only be abandoned and routed
around.

## 2. Consequences for anything committed early

- **Prefer coarse-but-true over fine-but-risky.** `dog ⊑ animal` is
  safe forever; a speculative fine distinction is a liability.
- **Never repair; deprecate and refine.** Don't re-parent `process`
  when it turns out to conflate events with activities — leave it as
  the (true) coarse union, add `event` and `activity` below it, and
  deprecate filing directly under it. The would-be intervention becomes
  an addition.
- **Distinctions can't be retrofitted.** The mechanical retrofit of a
  late top is cheap (parent the orphan category heads; items inherit
  transitively — additive). What can't be backdated is the *prevention*:
  Mercury-planet and Mercury-element filed as one node, events conflated
  with their documents. Those repairs are splits — interventions,
  compounding with every item filed meanwhile. This is the rigorous
  form of "the top matters early."

## 3. The top ontology

**Why early:** §2's last point. Everything files under the top's
branches, so the top's value is mostly preventive, and prevention
doesn't backdate.

**Why small:** §1. Every top node is a permanent, ecosystem-wide,
effectively unretractable commitment — admission to the top is a
one-way door. The discipline that falls out inverts the Cyc instinct:
"get the top right early" does **not** mean "get the top big early."
The rule of thumb generalizes from UNITS.md §7: *if we could
conceivably be wrong about it, it's not top material.* That points at a
BFO-sized top (dozens of nodes, each individually defended) rather than
a Cyc-sized one (thousands), with the care spent on **selectivity, not
coverage**. Growth happens below the line, as packs, where being wrong
is survivable.

**Sources — read for their decisions, never imported:** the value of
Cyc's upper levels is the decades of care in the *distinctions*
(individual/collection, tangible/intangible, event/situation), which is
exactly what Wikidata never had — its P279 top is documented chaos
(instance/subclass muddles), fine as a quarry for *domain* packs,
useless as a skeleton. The systems that took the top seriously: **Cyc**
(the design record), **BFO** (ISO 21838, continuant/occurrent rigor,
~35 classes — the right *size*), **DOLCE** (explicitly cognitively
oriented — arguably the best philosophical fit for an "associative
memory"), **SUMO** (IEEE, has a worked Abstract/Quantity/Number branch —
the math skeleton). Method: survey their decisions, then hand-write the
small core with each admission argued. Cyc-care at OntoDAG scale.

**The limitation to state up front:** a large part of Cyc's top-level
discipline lived in *disjointness* — partitions that make wrong filings
contradictions. OntoDAG cannot state disjointness (the wall in
`DATABASE_DIRECTION.md`; factbond is its second consumer). An OntoDAG
top offers the branches but not the fences: its discipline arrives as
convention, diff-preview, and the review workflow, never refusal. Our
top will be Cyc's taxonomy without Cyc's teeth — the draft proposing it
must say so in its first paragraph. (One computable island inside that
wall exists; see §6.)

**Prelude-tier, not pack-tier.** The prelude is already a
non-optional-in-practice micro-top: the registry consults kind nodes by
name, so typed values effectively require it — yet adoption stayed
explicit, versioned, and golden-rooted, so "empty" keeps its canonical
root and adopters converge byte-identically. That is the template for
the top: socially default (the guide's step zero, one command),
technically explicit, one fingerprint per version. Whether it ships
*inside* the prelude or as a `core` pack the guide mandates is a
tiering question for PACKS.md §8 — and the top is now that discussion's
most consequential client.

**The math skeleton (and the patchy one we already have).** The kind
nodes *are* a micro-ontology of mathematics — `linear-dimension` is
"totally-ordered, rational-valued" in disguise, `dominance-dimension` a
product order, `prefix-dimension` a tree order — grown by demand, not
design (a proposed `count-dimension` would be the third accretion; see
BINDING.md §9.5). Deliberate growth means: number kinds
(`natural ⊑ integer ⊑ rational`), **registry reflection** (the kinds
classified by their value spaces —
`count-dimension ⊑ integer-valued-dimension ⊑ rational-valued-dimension`),
and, if wanted, the algebra classification lattice
(`abelian-group ⊑ group ⊑ monoid` — real content, subsumption-shaped,
imports losslessly). What a math ontology can never be here:
definitions, axioms, proofs — it will know *that* every group is a
monoid, never *why*, and the draft must set that expectation loudly or
it becomes an invitation to assume inference. Two honest notes: the
system already knows rationals *operationally* (exact arithmetic — its
strongest knowledge of anything); and a `real-number` node can exist
while no real *value* ever can (the registry's value space is exactly
the rationals). Math-basics is the best-case first upper pack: no
Mercury problem, stable on the timescale of centuries.

**Decoupling:** none of this blocks `count`. Shipping `count` under a
`count-dimension` kind now and filing that kind under
`integer-valued-dimension` when the reflection lands is an *addition* —
the sequence composes.

## 4. Refinement, verified: the safe operation

Executed against the current code (2026-08-03):

```python
store: animal → dog → Rover            # early, coarse, true
pack:  animal → canine → dog           # a pack refines by merge
store.merge(pack)
# edges now: animal→canine, canine→dog, dog→Rover
# the direct dog→animal edge was PRUNED by merge's re-reduction (I2/I7)

old_peer: animal → dog                 # still has the direct edge
store.merge(old_peer)
# edges unchanged — the pruned edge does NOT resurrect
```

Two facts, both load-bearing:

1. **A pack can insert `canine` between `dog` and `animal` by plain
   merge**, and every adopter converges on the identical reduced graph
   regardless of adoption order.
2. **Reduction-pruned edges are immune to resurrection.** A *removed*
   edge resurrects when an old peer merges back (grow-only); a
   *derivably redundant* edge is re-pruned deterministically by every
   merge, forever. This is the mechanical proof of §1: refinement is
   stable under merge; removal is not. Coarse-but-true early claims are
   genuinely safe.

Same mechanics one level down: `put(Rover, [spaniel])` where
`spaniel ⊑ dog` prunes the direct `dog→Rover` edge automatically. The
*claim* "Rover ⊑ dog" survives the pruned edge — still entailed, still
provable, its provenance record still resolves — which is exactly why
PROVENANCE.md made subjects claims, not edges.

A pack can only refine under names it knows: shared vocabulary is what
makes third-party refinement land in your graph — another quiet
argument for a small shared top (it is the vocabulary everyone else's
refinements arrive through).

## 5. Retraction is selective (the Rover problem)

"It turns out Rover is not exactly a spaniel" is not an edge deletion,
because when `Rover ⊑ spaniel` was asserted, everything else — dog,
long-haired-by-breed, floppy-eared-by-breed — was **entailed through
that one edge**, never separately stored. Retract it and every
entailment through it vanishes at once. Both mechanical options are
therefore wrong:

- **bare edge removal** loses everything, including `dog`;
- **contraction** (reattach to the parents) keeps everything —
  *including the failed criterion* (`hair-length(5cm..)`, the very
  reason Rover left).

Which ancestors survive is **evidence about Rover** — judgment, not
computation; the no-oracle problem of §1 recurring at item scale. A
correct retraction carries a *keep-list*.

**The ordering trap (found by execution, 2026-08-03):** re-asserting
`put(Rover, [dog])` *before* dropping the spaniel edge does nothing —
the edge is skipped as redundant while the spaniel path exists — and
the subsequent `remove_edge` leaves Rover with **no parents at all**:
not under `dog`, not under `*`, invisible to every query including the
universe query. All *supported* surfaces are safe (CLI/MCP `remove` is
node-level and contracts; nothing exposes `remove_edge`), but any
future per-claim retraction built naively on `remove_edge` would be
this trap with a friendlier name.

## 6. The computable why, and the `reclassify` operation

The reason for a retraction is more expressible than it first looks.
"His hair is not long enough to qualify" is not a negation — it is a
**positive measurement**: `Rover ⊑ hair-length(3cm)`. If the vocabulary
states its criteria as values (`spaniel ⊑ hair-length(5cm..)`), the
system can *prove* the incompatibility: the two denotations are
disjoint, computed exactly (verified: `is_below` false,
`get_overlapping` empty). **Within a dimension, OntoDAG has decidable
disjointness** — the one place something negation-shaped exists, a
computable island inside the disjointness wall that
`DATABASE_DIRECTION.md` does not currently note. The "why" of a
retraction can be *certifiable*.

So the right operation is **provenance-shaped, not graph-shaped** — the
graph part is trivial (drop one edge, add the survivors); the meaning
lives in one operation group (`operation_group` already exists):

> **`reclassify`** (proposed, write surface): in one group —
> a **retraction** record for `Rover ⊑ spaniel`; an **assertion**
> record for the motivating evidence (`Rover ⊑ hair-length(3cm)`), so
> every reviewer sees the retraction bundled with the measurement that
> caused it; re-assertions for the keep-list (`dog`, `floppy-eared`) —
> the survivors still believed on independent grounds. The keep-list is
> where judgment enters; the group is the "why" made auditable.

Its read-side companion, buildable today: a **disjoint-values lint** —
"item sits below two disjoint values of one head" is just `intersect`
returning empty. Report, never refuse (merge must not fail, and a
peer's contrary belief is legitimate speech).

Multi-writer stance, deliberate: you never delete the spaniel claim
from the world. A peer may still assert it; after a sync the grow-only
graph may show the edge again. What you own is your retraction record
plus the disjoint measurement; the review workflow's per-reader trust
policy turns that into "not a spaniel" for anyone who trusts your
evidence. Truth about Rover is a judgment over the record set — the
provenance design's stance, earning its keep.

## 7. The map in one box

| operation | merge behavior | status |
|---|---|---|
| add node / parent / finer category | converges, any order | safe today (I7) |
| pack inserts a layer (`canine`) | converges; redundant edge re-pruned, immune to resurrection | verified today (§4) |
| remove a node | contraction preserves coarser claims | safe today; resurrects from old peers |
| retract one claim, keep the rest | needs keep-list + evidence | **does not exist** — `reclassify`, §6 |
| repair a wrong top category | per-descendant judgment; social coordination | avoid by §2 discipline |
| state why (failed criterion) | disjoint dimension values, provable | computable today; lint not built |

## 8. Open questions (the sheet)

1. **TOP.md itself**: who drafts the ~dozens-node top, from which
   sources' decisions, and does it ship inside the prelude or as a
   mandated `core` pack? (The tiering half belongs to PACKS.md §8; the
   top is now its most consequential client.)
2. **A consulted top-version marker**: stores can be audited for which
   top subgraphs they contain (subgraph presence is computable), but
   nothing *consults* a declared top version the way the registry pin
   gates cone indexes. Build one?
3. **The math pack**: scope of v1 — number kinds only? registry
   reflection (`integer-valued-dimension`)? the algebra lattice? And
   does the reflection belong to the registry (shipped) or the pack
   (adopted)?
4. **`reclassify` design**: exact tool shape on the write surface;
   is the keep-list ever defaultable (e.g. "keep everything not
   provably disjoint with the evidence"), or always explicit judgment?
5. **The disjoint-values lint**: where does it live — `odag lint`, the
   `review` tool, an MCP annotation on answers? Does the computable
   island get recorded in `DATABASE_DIRECTION.md`'s disjointness wall
   (amending an agreed doc — Peter's call)?
6. **The `remove_edge` orphan footgun** (§5): should the primitive
   refuse to orphan (raise), reattach to `*`, or stay a documented
   low-level sharp edge?
7. **Deprecation as a first-class signal**: §2's discipline says
   "deprecate filing under the coarse node" — is deprecation a
   convention in docs, a provenance record type, or a node under a
   registry-known `deprecated` category?
8. ~~**Does BINDING.md's `count` decision proceed now** under
   `count-dimension` (the §3 decoupling says it can), or wait for the
   math-pack scope question 3?~~ **Proceeded (2026-08-03, Peter: "it's
   safe to add count even if we may want to add more maths above it").**
   Registry 4.1 + prelude v3: `count-dimension` (whole numbers ≥ 1;
   `count(0)` refused as an absence claim; fractions refused), the
   `count` head, golden root re-pinned. Design record: UNITS.md §11.
   The future `integer-valued-dimension` parent remains an addition.
