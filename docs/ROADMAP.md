# OntoDAG roadmap

Delivered work first, then near-term, mid-term, and research horizon. Written for
a broad audience — the mechanisms behind the terms used here are explained in
[HOW_IT_WORKS.md](HOW_IT_WORKS.md), whose section numbers (§2 canonical form, §4
query planning, §5 merge, §6 persistence) are referenced throughout.

Where the other documents fit: the **day-to-day task list** is in `CLAUDE.md`
(what a working session picks up); **longer-term goals** for OntoDAG as a database,
including which conventional database features are deliberately *not* being built
yet and what would signal that they are needed, are in `DATABASE_DIRECTION.md`;
the engineering rationale is in `SWARM_DESIGN.md` and `SEMANTIC_CODES.md`.

Last updated 2026-08-01.

## Direction (agreed 2026-08-01): agents first

OntoDAG's differentiators — knowledge that is **canonical** (equal knowledge,
equal fingerprint), **addressable** (citable by root), **verifiable** (answers
that can be checked, eventually with cryptographic certificates), and
**attributable** (who asserted what, against which state) — are exactly the
four properties an AI model's knowledge lacks, and exactly what agent
ecosystems are missing. The agreed priority is therefore the **agent-facing
surface**: a written contract of what a higher layer may assume
([CONTRACT.md](CONTRACT.md)), verifiable answers, and provenance-gated agent
writes ([PROVENANCE.md](PROVENANCE.md)) — while keeping a decent human
interface (the surface layer's readable rendering serves both audiences; its
canonical echo is the same mechanism as the agent-facing one).

The companion decision: the **core gains no further expressiveness** — no
relations, no negation, no rules, no weights. Richer reasoning belongs to a
higher layer that compiles down to cone intersections under the contract, and
non-monotone questions (negation, aggregation, closed-world) are asked
honestly by pinning them to a root — a snapshot question with an immutable,
replayable answer, which the existing snapshot machinery already supports.

## Delivered

- The core structure — `put`/`get`/`remove`/`merge`, minimal-link maintenance
  (§2), exact descendant counts, and the invariant suite that pins them (§7).
- Save/load, OWL and Manchester-syntax import/export, DOT/LaTeX export, Graphviz
  visualization, an extensive test suite, and a demo ontology to build on.
- The `odag` command line and the Flask web app / REST API, including the
  car-market demo.
- A query planner with exact statistics and provably result-preserving rewrites
  (§4) — this is what the old roadmap called "optimize retrieval by choosing
  subsets of query items".
- Content-addressed persistence: the generic `recordstore` layer (now its own
  package) and `EagerOntoDAG`, validated against a real Bee node on Gnosis
  mainnet — the "DAG-only graph database for Ethereum Swarm" line item, in its
  library form rather than as a Bee plugin.
- Fast loading from a published store (2026-07-25): hydration goes through
  recordstore's batched, concurrent bulk read instead of one fetch per item.
- **Reading without loading everything** (2026-07-25): `LazyOntoDAG` answers
  queries by fetching items as the query walks them, so a published ontology can
  be queried without downloading it. On a 3,200-item store a specific query
  touches a few dozen items. It is read-only by construction (see the next
  section for why). Since 2026-07-31 it can also consult **published cone
  summaries** (below), so broad queries no longer cost their cones.

## Next up (concrete, queued)

1. ~~**Cone summaries for broad queries.**~~ **Done (2026-07-31).** A small
   deterministically-derived summary per broad category (sorted name lists in
   a *separate* derived store, manifest-pinned to the data root and the
   dimensions registry version) is fetched instead of walked: a two-broad-term
   query dropped from hundreds of fetches to a handful on the test fixture.
   Being *derived*, it never touches the canonical form — indexing writes
   nothing to the asserted store, and a stale or version-skewed index is
   ignored, never silently wrong.
2. ~~**Writing back from a partially-loaded graph.**~~ **Done (2026-07-31):
   `SparseOntoDAG`** — LazyOntoDAG's residency with the full mutation
   semantics. The two open problems resolved as the analysis predicted:
   (a) *change detection* needs no Merkle diff at all — every mutation runs
   on resident nodes, whose as-loaded records the reader already caches, so
   `commit()` diffs the resident set against those baselines and stages only
   real changes; (b) *minimal links* proved local once the three remaining
   downward probes (redundancy, cycle, "already reaches child" in count
   planning) were flipped upward into ancestor-cone walks — the same
   direction rule the query planner always followed, and a speedup for the
   eager writer too. Oracle: byte-identical roots against an eager writer
   applying the same operations, including randomized sequences, removals
   with contraction, and dimension renormalization. Measured on a
   447-record store: a `put` costs **7 fetches** and its commit stages
   **7 records**; a `remove` 3 more and 5.
3. ~~**A published "latest version" pointer.**~~ **Done (2026-07-31).** With a
   signing key configured (`odag set bee_signer …` or `$BEE_SIGNER`) the store's
   latest root lives in an owner-signed Swarm feed — a stable address others can
   follow. Keyless stores keep the local-file pointer. Validated live 2026-08-01
   (Gnosis mainnet): the root of a store rebuilt in an empty environment came
   back purely via the feed.
4. ~~**Multi-writer collaboration.**~~ **Done (2026-07-31).** `EagerOntoDAG.sync`
   folds a peer's published root in at the graph level (the order-independent
   merge, re-reduced, then recommitted); writers syncing each other's roots land
   on the byte-identical root. Several writers, one shared ontology, no server —
   with the documented union semantics (removals lose to concurrent re-adds).
5. **The higher-layer contract** — [CONTRACT.md](CONTRACT.md), drafted and
   **reviewed & agreed the same day (2026-08-01, contract version 0.1)**:
   the operations and guarantees a higher layer or agent may rely on
   (G1–G6, including `get_overlapping`'s candidate semantics), the
   monotonicity-under-merge clause with its remove caveat, the
   as-of/root-pinning rule for non-monotone questions, the admissibility
   criterion behind the walls, the verifiability tiers, and the certificate
   policy. The conformance test suite asserting the guarantees through the
   public API only landed the same day (`tests/test_contract.py`, 15 tests
   covering G1–G6, the as-of clause, and the version constant).
6. **Provenance design** — [PROVENANCE.md](PROVENANCE.md), drafted and
   **reviewed & agreed the same day (2026-08-01)**: attribution in a
   parallel provenance store (never in the knowledge record, so agreement-
   by-fingerprint survives); **subjects are claims, not edges** (stable
   under the core's own reduction); signed assertion / endorsement /
   retraction / key-binding records with a version and extensions map from
   day one; per-writer stores folded by explicit choice, so spam control is
   admission-by-reference. **Gates all agent writes** — the design gate is
   now open; implementation is Phase 2. Promoted from the research horizon
   by the agents-first decision.
7. **Readable rendering + `odag canon`** — the surface layer's steps 1–2
   (`SURFACE_LAYER.md` §10; unblocked since the pipe-semantics decision):
   `time(2026)` instead of the canonical timestamp range on terminals,
   canonical bytes whenever output is piped, a round-trip fuzz test, and an
   inspectable elaboration command. Serves humans and agents at once — the
   canonical echo is the confirm mechanism for both.
8. **Read-only agent surface (MCP) + a discoverability record.** Tool-shaped
   `get`/`get_any`/`is_below`/`show`/`canon`, always citing roots, with as-of
   (query at a named root) included since the snapshot machinery exists; plus
   a small conventional "what is this store about" record an agent reads
   first. Doubles as the **tripwire instrument**: what agents try to express
   and can't is the usage evidence the walls in `DATABASE_DIRECTION.md` wait
   for, so refused/awkward patterns get logged from day one.
9. **Verifiable answers.** recordstore `prove`/`verify` — Merkle inclusion
   *and absence* proofs from the canonically-encoded trie (absence is provable
   precisely because the encoding is canonical); then `is_below` certificates
   in both polarities on top (witness path for true; an upward-closed,
   inclusion-proven ancestor cone for false). Upgrades "trust the store" to
   "verify against 32 bytes". recordstore half lives in that repo.
10. **Agent writes** — gated on item 6: the provenance store implementation,
    write-path tools (propose → canonical echo → confirm, idempotent puts),
    then endorsement/review workflows before any volume.
11. **The human track, in parallel:** a standard **prelude as a published
    ontology** (adopt common dimension declarations by merging a well-known
    root — also the answer to "which upper ontology?": publish optional
    vocabularies, don't bake one in), and the User Guide quick-start rework,
    which item 7 makes honest to write (examples can finally read
    `time(2026)`).

## Then: more capability, still no model change

The remaining "pure now" items of `DATABASE_DIRECTION.md` — they preserve the
canonical form and the merge properties untouched:

- ~~**Dimension lattices**~~ — *shipped in v0.4.0 (2026-07-30); see
  `docs/DIMENSIONS.md`.* Parametric items (`weight(..5kg)`, `time(a..b)`,
  `geo(u2ed)`) whose order relative to each other is computed from the name —
  containment of denoted value sets, the same extension-inclusion order the DAG
  always had — instead of generated category chains: the "exact arithmetic" wall's
  tripwire fired (loopmarket matching needs arbitrary query-time thresholds), so
  the earlier quantized-chain version is superseded as semantics and survives only
  as an optional derived index. Values are integers in per-family base units;
  kinds (linear, prefix, dominance) are declared by ordinary edges under
  registry-known nodes; queries like "photos of dogs from last summer near
  Balaton" become *exactly* computed cone intersections. This is what the original
  roadmap's "predicated (parametric) items" and "space and time calculation"
  become.
- ~~**Union in `get()`.**~~ **Done (2026-07-31):** `get_any` — DNF over
  conjunctive queries, on every residency (Eager/Lazy/Sparse), with the CLI's
  literal `or` and the REST API's `|`. Stored state and canonical form
  untouched, as promised: union is a question you ask, never a thing you
  store. Classic use with typed values: *outside a range*
  (`get_any([["weight(..2kg)"], ["weight(5kg..)"]])`).

## Under discussion (no decision yet)

- **A surface layer** — a layer between people and the exact core: forgiving
  input on the way in (a bare `2026` as the year, ISO weeks, eventually a
  locally-running LLM turning a sentence into terms) and readable output on
  the way out (`time(2026)` rather than
  `time(2026-01-01T00:00:00Z..2026-12-31T23:59:59Z)`, `weight(3kg)` rather than
  `weight(3000000mg)`). The core stays exactly as strict as it is now — the
  surface only ever proposes, and everything it proposes is validated and
  canonicalized before it is stored, which is also the condition that would
  make an LLM safe to plug in. Both layers stay reachable from every interface:
  a `--raw` switch on the command line, an opt-in module for Python callers.
  Discussion draft with open questions: `SURFACE_LAYER.md`. **Status
  2026-08-01:** its Part II questions now have outcomes — the agents-first
  direction above, `CONTRACT.md` (how far toward knowledge representation:
  the core stops here; a higher layer compiles down), and `PROVENANCE.md`
  (what agent writes require) — and the rendering work itself is queued
  (item 7 above). Still genuinely under discussion: declaration ergonomics,
  clock-dependent input, and multilingual naming (a proposed split — exact
  aliases in a shared-by-reference lexicon store, disputed near-synonyms as
  graph claims — is recorded in its §12, waiting on the Namespaces tripwire).

## Parked until real usage data exists

Not "someday" items — each is worked out in a design note and waits on a trigger:

- **Bitmap indexes for queries.** Each category's cone can be kept as a bitmap so
  that query intersection becomes a few machine-word AND operations, and — more
  interestingly — queries against a *published* ontology could be answered by
  fetching just a few small index records instead of the whole graph.
  `SEMANTIC_CODES.md` works this out in detail (including how an item's set of
  ancestors acts as a "semantic code" — a meaning-bearing binary address), along
  with the endgame: letting *usage statistics* decide which intermediate
  categories are worth materializing, somewhere between the bare graph and a
  fully precomputed index. Parked behind explicit triggers: a measurably hot
  query workload, a graph too big for RAM, or thin clients.
- **Chunk-level layout tuning** (packing many small records per storage chunk) —
  waiting on real record-size and access-pattern data.
- **Zero-knowledge proofs over private ontologies** — prove "my catalogue
  contains something under `weight(..5kg) ∧ location(EU)`" without revealing
  the catalogue. Parked behind a real privacy-demanding counterparty
  (loopmarket-shaped), but the positioning is unusually good when it fires:
  deterministic canonical encoding, one query primitive, and no floating
  point anywhere (values are integers in base units — what arithmetic
  circuits want). See `CONTRACT.md` §7. On-chain *anchoring* of roots, by
  contrast, is cheap (Swarm's BMT addressing is keccak-based, the EVM's
  native hash) and waits only on a consumer, not on research.

## Research horizon

- **Private parts of a shared graph.** Overlays: a public base DAG plus encrypted
  private sub-graphs, composable at load time via merge, with access managed by
  Swarm's built-in access control. A permissions structure (company → department →
  team) is itself a small DAG — a natural fit being explored.
- **Learned categories.** A companion project, `mdl-fca`, learns "good" category
  structures from raw data (which features co-occur across your items), using a
  compression principle: a category earns its existence only if it makes
  describing your data *shorter*. Its output has the same shape as OntoDAG, so
  learned structure can flow in — tagged with **provenance** (`asserted` = a human
  said so, irreplaceable; `derived` = a learner proposed it, regenerable), which
  in turn drives what must be stored durably versus what can be recomputed.
  *Note 2026-08-01: the provenance machinery itself is no longer horizon — it
  moved to the queue ([PROVENANCE.md](PROVENANCE.md)) because agent writes
  need it first; the learner integration stays here.*
- **Namespaces.** Reconciling different people's naming — spelling, language, and
  the same word used for different things — so DAGs built independently can be
  merged without name collisions. *A proposed shape is recorded in
  `SURFACE_LAYER.md` §12 (exact aliases in a lexicon store, disputed
  near-synonyms as graph claims); building it waits on the tripwire.*
- **Economic guarantees on claims — the factbond sister project**
  (github.com/petfold/factbond, created 2026-08-01, design stage: bonded
  assertions + information insurance for factual claims). The third trust
  leg after structural proofs and provenance: "someone will pay if this is
  wrong." OntoDAG's parts in it are worked out in factbond's
  `docs/INTEGRATION.md`: canonical root-pinned names as *claim identity*
  (and a root as a batched claim — bond millions of facts at once, dispute
  one record via an inclusion proof); the provenance store as its assertion
  layer minus money; certificates as the free bottom rung of dispute
  adjudication; and — the research bridge — OntoDAG as a tractable,
  monotone claim/implication fragment for knowledge-graph collateral
  netting (`is_below` as implication, disjointness claims as exclusion).
  loopmarket's P3 "guarantee fabric" (bonded stakes on catalogue edges,
  settlement-attached insurance) is the first structured consumer. Nothing
  in this repo depends on any of it.
- **Materialized intermediate categories.** Adding (and removing) intermediate
  nodes purely to speed up search, chosen by usage statistics; the derived,
  never-merged half of the bitmap-index endgame above.
- **Other implementations and surfaces.** A Go (or Rust) port with its own REST
  API; an adapter onto an existing graph database; a hosted web interface with
  user profiles. All from the original roadmap, none of them prerequisites for
  anything above — the Python core plus the Swarm layer is the reference
  implementation.
- **A Bee-side plugin.** Storing the DAG decentrally works today as a library
  against a node's HTTP API; running it *inside* Bee remains an open idea rather
  than a plan.
