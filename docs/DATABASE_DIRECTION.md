# OntoDAG as a Database: Direction, Gaps, and the Purity Principle

Status: analysis + agreed strategy, 2026-07-25.
Origin: a swarmlite working session (see `docs/ecosystem-strategy-qa.md`
in the swarmlite repo for the verbatim exchange). Written to stand
alone: a future session in this repo should be able to start from this
file plus `HOW_IT_WORKS.md`.

**Scope: this is a longer-term goals document, not a task list.** It
records where OntoDAG-as-a-database is heading and — just as importantly
— which conventional database features are deliberately *not* being
built yet, together with the tripwire that would signal each one has
become necessary. Nothing here is scheduled by virtue of being written
down; the "Pure now" items are the ones considered ready to start, and
even those are sequenced against the near-term engineering queue in
`ROADMAP.md`. The day-to-day task list is in `CLAUDE.md`. Expect this
file to outlive several of those.

## The governing principle (Peter, verbatim)

> "My strategy was to keep it as pure and simple as possible to see how
> far we can go with the simplest approach. Only add non-ontodag pure
> features when we hit a wall. An example is geo information: don't
> integrate a geo engine if we can do it in the spirit of ontodag."

This is not an aesthetic preference. OntoDAG's two invariants —
**canonical form** (same knowledge ⇒ byte-identical graph ⇒ same
content-addressed root) and **mergeability** (commutative, idempotent
merge = multi-writer convergence without consensus) — are load-bearing,
and nearly every conventional "database feature" threatens one of them:
history-dependent indexes break canonical roots; tombstones complicate
idempotent merge; imported relation machinery dilutes the
one-primitive query model that keeps the planner provable. Purity is
what the guarantees are made of. Every proposal below is sorted by
whether it preserves the invariants untouched.

## Update 2026-08-01: the criterion behind the walls, and what changed

The strategy discussion recorded in `SURFACE_LAYER.md` Part II produced
`CONTRACT.md` (what a higher layer or agent may assume) and settled the
"how far toward knowledge representation?" question. Four consequences for
this document:

1. **The walls now have a general criterion**, not just instances
   (`CONTRACT.md` §5): a feature is admissible in the shared store only if
   it is (a) **monotone** — merge-as-union survives — *and* (b) **cheaply,
   semantically canonicalizable** — "equal knowledge ⇒ equal root" stays
   decidable and cheap rather than degrading to "equal syntax ⇒ equal
   root". Both are necessary; together they are still **not sufficient** —
   the tripwire discipline below decides what is *warranted* (computed
   values pass both axes and still wait). Per-wall notes below name which
   axis each wall protects.
2. **The as-of clause** (`CONTRACT.md` §4) is the sanctioned path around
   the non-monotone walls: negation, aggregation, closed-world readings and
   absence claims are well-defined when **pinned to a root** — immutable,
   replayable answers via the existing snapshot machinery
   (`RecordStore.at(root)` + `LazyOntoDAG`). The walls guard the living,
   merging store; they were never about snapshot questions.
3. **Agents are the tripwire instrument.** With agents-first agreed
   (`ROADMAP.md` "Direction"), the read-only MCP surface will log what
   agents try to express and can't — walls stop waiting on anecdote and
   start accumulating evidence. Expect the constraints and relations
   tripwires to be probed far sooner than human usage would have.
4. **Verification is now a stated offering** (`CONTRACT.md` §7): what holds
   today by construction (semantic content addressing *is* a commitment
   scheme; agreement is a hash comparison), what is committed (trie
   inclusion/absence proofs, `is_below` certificates), and what is walled
   (ZK, below).

## Why ask the database question at all

Context from the swarmlite side: SQL-on-Swarm (swarmlite) is the
*adoption* play — read-only SQL over published SQLite snapshots, meeting
existing skills where they are. But it is single-publisher by
construction. OntoDAG already has, natively, the two properties no SQL
facade can ever offer on decentralized storage:

- **Semantic content addressing**: identical knowledge has an identical
  address, regardless of construction history. Deduplication of
  *meaning*. Neither PostgreSQL nor Datomic has this.
- **Convergent multi-writer** without a server or chain: the CRDT merge.

So "OntoDAG as a proper database" is not competing with swarmlite; it
would sit above it as the native collaborative layer, publishing
materialized SQL views (`site.db` via swarmlite's publisher) downward
for conventional readers. The functional-database comparison (Datomic:
database-as-immutable-value, accumulate-only facts) is instructive —
on Swarm "the database as a value" becomes literal, the value *is* the
root — and OntoDAG is closer to that model than to relational, with
the taxonomy backbone as its differentiator.

## What OntoDAG already has, in database terms

- A canonical storage form with unique fingerprints (§2, §6 of
  HOW_IT_WORKS) — snapshot identity, cheap diffing, structural sharing.
- A query planner with *exact* statistics (`descendant_count` is a
  precomputed `COUNT(*)` per category), provably result-preserving
  rewrites, adaptive walk-vs-probe execution (§4).
- CRDT merge (§5, §7 invariants I3/I7).
- Versioned persistence with snapshots-forever on content-addressed
  storage via recordstore (§6), Swarm-ready today.

That is: identity, planning, concurrency-by-merge, and durability.
What separates this from "a proper database" is the list below.

## Pure now — no model change, no wall

These preserve both invariants untouched and are recommended as the
next work, in order:

1. ~~**Lazy remote reader.**~~ **DONE** — `LazyOntoDAG` (`src/ontodag/lazy.py`)
   already does this; it landed the same day this document was drafted, which
   the draft did not know. Its own follow-up (cone summaries for broad-term
   queries) landed 2026-07-31 — `src/ontodag/cones.py`, sorted-name-list
   summaries in a separate derived store, manifest-pinned to the data root
   and the dimensions registry version, wired into `LazyOntoDAG` as a cache
   with an exact fallback (two broad terms: 375 → 3 record fetches on the
   test fixture). Canonical form untouched by construction: indexing never
   writes to the asserted store. **Also done: count maintenance.** The delta
   rules described in `experiments/RESULTS.md` are now in `dag.py` — exact
   counts no longer require the whole graph, removing one of the three stated
   reasons `LazyOntoDAG` refuses writes. **The other two fell 2026-07-31:**
   `SparseOntoDAG` is the partially-resident *writer* (change detection by
   resident-set diff; reduction proven local once the downward reachability
   probes flipped upward), so read-only-ness is now a per-class contract
   choice, not a limitation of the model. Historical text follows.

   `EagerOntoDAG` currently loads every record
   into RAM at startup; that caps scale and forbids browser use. The
   swarmlite lesson applies directly: fetch item records on demand
   during walks (recordstore's trie already supports lazy per-key gets
   and `get_many` batching), cache cone summaries for hot categories
   (succinct bitmaps stored as ordinary content-addressed blobs,
   derived deterministically so canonical roots are unaffected), follow
   a feed pointer for "latest". Target: a browser queries a published
   million-item OntoDAG at tens of fetches per query. Pure engineering;
   zero semantics; makes everything else demonstrable on Swarm.
2. **Dimension lattices — values in the spirit of OntoDAG.** Time, geo,
   and numeric *ranges* need no value engine: generate category chains
   (century → decade → year → month → day; geo quad-tree cells; numeric
   interval halvings) and classify items under the finest cell. Then
   "photos of dogs from last summer near Balaton" is one cone
   intersection — the existing primitive, the existing planner. The
   lattice *generator* is tooling, not model. This is the worked
   example of the governing principle: the ontodag-spirit geo engine.
   **Update 2026-07-30: superseded as semantics** by parametric
   dimension lattices (`docs/DIMENSIONS.md`) — the arithmetic wall's
   tripwire fired (see below), and the linear/prefix/product kinds
   answer these queries *exactly* rather than by quantization; the
   Balaton query becomes a computed cone intersection with no
   quantization error. Generated chains survive only as an optional
   derived index for hot dimensions.
3. ~~**Union in `get()`.**~~ **Done (2026-07-31):** `OntoDAG.get_any` —
   query-side DNF, exactly as scoped: no stored state, canonical form
   untouched, and the one planner extension (drop a disjunct whose
   canonicalized term set strictly contains another's — it can only
   return a subset) is result-preserving like every planner step.
   Surfaced as `or` in the CLI and `|` in the REST query parameter.
4. **Proof surfaces** (added 2026-08-01 — pure by the same test: derived
   entirely from committed content, canonical form untouched). recordstore
   `prove`/`verify` — Merkle inclusion proofs plus **absence** proofs,
   which the trie supports precisely because its encoding is canonical (a
   key has exactly one possible location); then `is_below` certificates in
   both polarities on top (witness path; upward-closed ancestor cone).
   Details and the agent-facing rationale: `CONTRACT.md` §7 Tier 2.
5. **The read-only agent surface (MCP)** (added 2026-08-01) — pure
   engineering over the existing operations: tool-shaped queries citing
   roots, as-of via `RecordStore.at()`, the discoverability record, and
   logging of what agents fail to express (the tripwire instrument).

## The walls — documented tripwires, not features

Per the principle, these are *not* to be built now. Each is recorded
with the tripwire that signals the wall has actually been hit, so a
future session recognizes the moment instead of pre-building:

- **Exact arithmetic / equality on continuous values.** Dimension
  lattices quantize; they cannot compute. Tripwire: a real query that
  needs computation rather than classification (e.g. `price × quantity`
  comparisons, joins on computed values). The escape hatch, when hit:
  typed attribute payloads on item records plus deterministic ordered
  indexes — derived purely from content so roots stay canonical.
  **Tripwire fired 2026-07-30**: loopmarket's product/service matching
  needs arbitrary query-time thresholds (a courier's `weight(..5kg)`)
  that no pre-generated quantization contains. The hatch is being
  implemented in a name-native variant — parametric items,
  `docs/DIMENSIONS.md` — chosen over attribute payloads so that
  constraint terms remain categories and matching remains one cone
  intersection (one query model, one planner, one merge story) instead
  of a second payload-filter mechanism beside subsumption; the
  "deterministic ordered indexes" half of the recorded hatch survives
  verbatim as derived per-dimension sorted indexes. Values are integers
  in per-family base units (the bank/crypto move — exactness by
  construction). Note the wall itself only *moved*, precisely as far as
  the tripwire evidence reaches: comparisons of a value against a
  constraint *within one dimension*. Cross-dimension computation
  (`price × quantity`, joins on computed values) remains behind the
  wall, tripwire unchanged.
- **Arbitrary relations (roles).** "Alice *authored* Doc1" is not
  subsumption. Tripwire: users mass-reifying relation nodes
  ("authored-by-Alice" categories multiplying per entity). The escape
  hatch: a datom layer (entity, relation, target) stored beside the
  DAG in recordstore, with the DAG supplying what EAV systems lack — a
  taxonomy of entities *and of relations* (`authored` is-under
  `contributed-to`). That combination would be genuinely novel; it is
  also the research-grade step, not to be taken casually.
  **Refinement 2026-08-01:** which axis this wall protects is now known,
  and it is not the obvious one. The EL-shaped extension is *monotone*
  (adding axioms only adds entailments), so merge would survive; what
  breaks is axis (b) — subsumption stops being computable from names and
  local structure, and canonicalizing an axiom set up to logical
  equivalence means canonicalizing its entailment closure. Until that
  research is done, "equal knowledge ⇒ equal root" silently degrades to
  "equal syntax ⇒ equal root" — the guarantee agents actually cite. That
  is what "research-grade" concretely means here. Tripwire unchanged, but
  now observable: agent traffic through the MCP surface is where
  mass-reification pressure will first show.
- **Negation.** "Under A but not under B" requires a closed-world
  decision and prices the complement of a cone. Tripwire: repeated user
  need for exclusion queries that pre-filtering can't express.
  **Amendment 2026-08-01:** the wall guards the *living, merging* store —
  there the answer set can shrink under merge, which axis (a) forbids.
  Against a **pinned root** the same question is deterministic, immutable
  and replayable, and is sanctioned by `CONTRACT.md`'s as-of clause; the
  higher layer gets its negation there, the shared store never stores one.
- **Aggregation beyond COUNT.** `descendant_count` already gives the
  most-used aggregate for free. SUM/AVG/GROUP BY require values first
  (see arithmetic wall). Tripwire follows from that one.
  **Amendment 2026-08-01:** same as-of resolution as negation — a
  root-pinned aggregate is an honest, replayable fact (and parametric
  values now exist to aggregate over); anything *stored* or asked of the
  living store stays behind the wall.
- **Deletion under multi-writer merge.** Merge is union; a removal can
  be resurrected by an old copy. Options when hit: tombstones (costs
  idempotence care) or a declared grow-only stance. Tripwire: the first
  real collaborative deployment where remove matters.
- **Constraints (disjointness first).** "Nothing is both Cat and Dog"
  buys consistency checking and planner pruning (refuse
  empty-by-axiom intersections before walking). Tripwire: garbage
  queries or polluted merges that a disjointness check would have
  refused.
  **Refinement 2026-08-01 — the shape is resolved in advance, only the
  timing waits.** `SURFACE_LAYER.md` §11's criterion (claims merge,
  policy doesn't) splits this wall cleanly: the disjointness *assertion*
  is a claim about the world — monotone, trivially canonical (ordinary
  edges under a vocabulary node) — and may merge; *enforcement* is local
  policy — a checker that warns or refuses at put time, never a merge
  precondition. Merge stays total, and a violation arriving via merge is
  visible, queryable structure: `get(Cat, Dog)` being non-empty **is**
  the consistency check — the one query primitive doing one more job.
  Expect agents writing at volume to fire this tripwire first.
  **A second consumer approached the same day:** collateral netting in the
  factbond design (generalized negRisk — its graph layer) nets against
  *exclusions*, i.e. mutually exclusive claims, which in OntoDAG terms are
  exactly these disjointness claims (implications it gets from `is_below`,
  already built). Two independent consumers converging on one wall is the
  evidence shape this document's tripwires wait for; see factbond's
  `docs/INTEGRATION.md` §6.
- **Query-argument subsumption** (`is_below` taking conjunctions on
  either side; considered and parked 2026-07-31). The generalization is
  fully worked out and turns out to *be* loopmarket's `satisfies`: with
  same-head parametric conjuncts pre-intersected (dimension meets are
  exact), "(A₁∧A₂) fits within (B₁∧B₂)" is ∀ sup-conjunct ∃ sub-conjunct
  — sound, and complete w.r.t. everything the graph asserts, since
  asserted meets are unknowable (§10) while dimension meets are
  computable. Not built because it has one consumer, which already
  exists as three lines on the right side of the boundary. Tripwire:
  a caller holding machine-built description *sets* the satisfies-loop
  can't serve — realistically, parametric terms entering offer concepts,
  which is when the dimension-meet pre-intersection stops being
  consumerless. Two commitments for whoever builds it: the semantics is
  **intensional only** — extension containment (`get(A) ⊆ cone(B)`)
  makes the answer depend on today's population and can flip under a
  collaborator's merge, breaking the monotone/CRDT-stable answers
  property that admitted OR and excludes NOT — and sup-side
  *disjunction* is only ∃-sound (a term can fit a union of intervals
  while fitting neither part), so it stays out unless someone needs
  exactly that and accepts union-of-intervals arithmetic.
- **Rules / derived facts in the shared store** (added 2026-08-01, from
  `SURFACE_LAYER.md` §13's table). Derived content entering the shared
  store unmarked would be absorbed into the canonical form — the root
  would fingerprint conclusions as if they were ground truth, and
  re-running a different rule set would fork stores that agree on every
  assertion. Local derived closures need no wall at all (the cone-index
  pattern: derived, local, regenerable, never merged). The hatch for
  *shared* derived content: ordinary claims marked `derived` in the
  provenance store with their basis pinned (`PROVENANCE.md` §4), plus
  endorsement to promote them. Tripwire: mdl-fca output or agent-derived
  structure that people actually want to share rather than recompute.
- **Weights, probabilities, confidence** (added 2026-08-01). Fails axis
  (b) outright — a weight in the name or record breaks exactness, hence
  canonical roots; and it fails merge too (whose number wins?). The
  hatch: confidence is a property of a *speech act*, not of knowledge —
  it lives on assertion/endorsement records in the provenance store
  (`PROVENANCE.md` §6), or outside the system. Tripwire: a consumer whose
  need provably cannot be expressed as claims-plus-endorsement.
- **Zero-knowledge proofs over private ontologies** (added 2026-08-01;
  the Tier-3 item of `CONTRACT.md` §7). Prove "my catalogue contains
  something under `weight(..5kg) ∧ location(EU)`" without revealing the
  catalogue. Heavy research (SNARK circuits over trie walks), so walled —
  but record the positioning for when it fires: deterministic canonical
  encoding, a single query primitive, and no floats anywhere (integers in
  base units) make OntoDAG unusually circuit-friendly. Tripwire: a real
  privacy-demanding counterparty, loopmarket-shaped. Contrast on-chain
  *anchoring* of roots, which is not a wall: 32 bytes in a contract,
  keccak-native BMT addressing, waits only on a consumer.
- **A Merkle-ized semantic DAG — per-node cone commitments** (added
  2026-08-01, from Peter's question after the `is_below` certificates
  landed; extends `MERKLE_NOTES.md`). Hash-linking the semantic graph
  itself (node id = hash of name + child hashes) would buy three real
  things the current stack lacks: **path-sized, order-free positive
  subsumption proofs** (a hash-link path is a self-verifying witness — no
  dependency closure, no re-execution), **per-category cone commitments**
  (agree about a whole subontology by comparing one hash; adopt a
  published vocabulary as byte-identical subtrees), and **on-chain
  verifiable subsumption** — the one proof shape a contract can check,
  where re-execution certificates cannot run. It can never be the *base
  representation*: names are identity and a Merkle address changes
  whenever anything below the node changes (so it is an index *over* the
  named graph, never the graph); hash links point one way, so negative
  answers keep needing the ancestor-cone machinery regardless; and the
  computed order corresponds to no edges at all, so hash paths cover only
  the asserted fragment — declarations and arithmetic re-execution stay.
  The admissible form is the third instance of the
  derived-local-regenerable pattern (cone summaries, `SEMANTIC_CODES.md`):
  a per-node cone-commitment index in its own store, manifest-pinned,
  deterministic from the canonical form — the asserted root untouched by
  construction. Kin: the POT track in recordstore's ROADMAP (the
  storage-side cousin, with the Solidity verifier). Tripwire: someone
  needs a ⊑ claim verified **on-chain** (factbond dispute settlement,
  loopmarket P2 settlement), or certificate volume makes cone-sized
  proofs measurably painful. Until then, the 2026-08-01 certificates
  answer every off-chain need, and building this is pre-building.

## Merkle structures: see `MERKLE_NOTES.md`

Whether to use hash trees to find "which parts changed" is answered
separately in `docs/MERKLE_NOTES.md`. Short version: not for counts (a hash
answers equality, not arithmetic or membership, and a writer already knows
where its own change is), but **yes** for change detection — which is now the
principal blocker to lazy writes, and for which recordstore already has the
machinery behind a private method.

## Relationship to the rest of the family

- **recordstore** stays the shared value/persistence layer (it was
  extracted from here; the canonical-roots contract is joint property).
  The `prove`/`verify` pair (Pure now, item 4) belongs in that repo: it
  is a property of the canonical trie, not of OntoDAG.
- **swarmlite** is the SQL adoption surface; an OntoDAG can
  *materialize* views into `site.db` and publish them with swarmlite's
  publisher (pure downstream artifact, no coupling).
- **ontodag-fs** already shows the query surface insight: paths are
  queries. The lazy reader (Pure now, item 1) is what would let the
  same surface run against a published store without downloading it.
- **factbond** (github.com/petfold/factbond, created 2026-08-01, design
  stage) — bonded assertions + information insurance on factual claims:
  the *economic* trust leg above proofs and provenance. OntoDAG's roles in
  it: the **claim layer** (canonical, root-pinned claim identity; a root as
  a batched claim disputed per-record by inclusion proof), the
  **assertion-layer substrate** (its record shapes are `PROVENANCE.md` §3
  plus money — see `PROVENANCE.md` §7), and the candidate **tractable
  implication fragment** for its netting layer (`is_below` = implication;
  disjointness claims = exclusion — the wall note above). Composition is
  strictly one-directional: factbond consumes `CONTRACT.md`; nothing here
  imports it.

## Suggested first session in this repo

Start with the lazy remote reader: it is swarmlite-shaped work with
known patterns (LRU caches, batched fetches, read-budget tests against
an in-memory store — see swarmlite's test conventions for the
"assert correctness AND the number of fetches" style), it requires no
model decisions, and it turns the Swarm story from "works today" into
"demonstrable at scale from a browser."
