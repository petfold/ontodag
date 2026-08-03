# OntoDAG roadmap

Delivered work first, then near-term, mid-term, and research horizon. Written for
a broad audience — the mechanisms behind the terms used here are explained in
[HOW_IT_WORKS.md](../HOW_IT_WORKS.md), whose section numbers (§2 canonical form, §4
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
([CONTRACT.md](../CONTRACT.md)), verifiable answers, and provenance-gated agent
writes ([PROVENANCE.md](../PROVENANCE.md)) — while keeping a decent human
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
5. **The higher-layer contract** — [CONTRACT.md](../CONTRACT.md), drafted and
   **reviewed & agreed the same day (2026-08-01, contract version 0.1)**:
   the operations and guarantees a higher layer or agent may rely on
   (G1–G6, including `get_overlapping`'s candidate semantics), the
   monotonicity-under-merge clause with its remove caveat, the
   as-of/root-pinning rule for non-monotone questions, the admissibility
   criterion behind the walls, the verifiability tiers, and the certificate
   policy. The conformance test suite asserting the guarantees through the
   public API only landed the same day (`tests/test_contract.py`, 15 tests
   covering G1–G6, the as-of clause, and the version constant).
6. **Provenance design** — [PROVENANCE.md](../PROVENANCE.md), drafted and
   **reviewed & agreed the same day (2026-08-01)**: attribution in a
   parallel provenance store (never in the knowledge record, so agreement-
   by-fingerprint survives); **subjects are claims, not edges** (stable
   under the core's own reduction); signed assertion / endorsement /
   retraction / key-binding records with a version and extensions map from
   day one; per-writer stores folded by explicit choice, so spam control is
   admission-by-reference. **Gates all agent writes** — the design gate is
   now open; implementation is Phase 2. Promoted from the research horizon
   by the agents-first decision.
7. ~~**Readable rendering + `odag canon`.**~~ **Done (2026-08-01).** On a
   terminal, `odag` now prints `time(2026)` and `weight(3kg)`; pipes, files
   and `-o` always get the exact canonical bytes, so `odag get ... | odag`
   round-trips by default (`--render`/`--raw`/`ONTODAG_SURFACE` override;
   flag > env > terminal test). `odag canon TERM` shows the exact stored
   form of any spelling — the inspectable mapping — and bare `canon` prints
   the surface and registry versions. The renderer (`ontodag.surface`) is a
   pure function of the canonical name and the declared kind, emits only
   spellings the vocabulary already accepts, and is pinned by a fuzz test of
   the round-trip law `elaborate(render(t)) == t` — the promised one-way
   direction only. Serves humans and agents at once: the canonical echo is
   the confirm mechanism for both.
8. ~~**Read-only agent surface (MCP) + a discoverability record.**~~
   **Done (2026-08-01).** `odag-mcp` serves any odag store over MCP's stdio
   transport (stdlib-only, no SDK dependency): six tools — `about` (the
   what-is-this-store record, computed on demand, never stored), `query`
   (conjunctions and unions), `is_below`, `overlapping`, `describe`,
   `canon` — with every answer citing the root it is true of, the contract
   version, and the extensible annotations slot; canonical terms echoed
   back so an agent sees what was stored, friendly spellings supplied
   *beside* names, `as_of` for snapshot queries, and even local file
   stores answering with their semantic fingerprint (equal knowledge,
   equal root). Failed calls are logged from day one — the tripwire
   instrument the walls wait for. Design note: `docs/AGENT_SURFACE.md`.
   Writes stay absent until the provenance layer exists.
9. ~~**Verifiable answers.**~~ **Done (2026-08-01).** recordstore v0.16.0
   ships `prove`/`verify_proof` — Merkle inclusion *and absence* proofs
   from the canonically-encoded trie (absence is provable precisely because
   the encoding is canonical: one root, one possible location per key), and
   `ontodag.certificates` composes them into `is_below` certificates in
   both polarities: the prover bundles an authenticated proof of every
   record the answer depends on (an order-invariant closure, so any
   verifier's walk is covered), and the verifier **re-runs the real
   `is_below`** over those proof-verified records — semantics single-
   sourced, a wrong answer impossible to validate, a coverage gap failing
   loudly. Live on the agent surface as `certify: true`: "trust the store"
   is now "verify against 32 bytes", for humans, agents, and — when the
   time comes — factbond's mechanical dispute rung.
10. **Agent writes** — the provenance store **and the write path shipped
    (2026-08-01)**: attribution lives in a per-writer store beside the
    knowledge (never inside it, so identical knowledge keeps identical
    fingerprints whoever asserted it); subjects are *claims*, stable under
    the core's own canonicalization; records are signed speech acts —
    assertion, endorsement, retraction, key-binding — that merge
    conflict-free between writers. `odag-mcp --write` mechanizes the safe
    flow: **propose** (see exactly what would be stored, and whether it
    already holds) → **confirm** (refused if the store moved meanwhile),
    with signed assertion records beside every change and removals
    emitting retractions — the audit trail has no silent disappearances.
    **And the review workflow (same day — this item is complete):**
    `endorse`/`retract` sign a reader's stance on any claim without
    touching knowledge, and `review` — available read-only — shows a
    claim's full audit trail with every signature verified, each author's
    standing, and an acceptance verdict under the reader's own trust
    list. What lands in a store is never what a reader must accept:
    claims merge, acceptance is policy.
11. **The human track:** ~~a standard prelude~~ + ~~the quick start~~ —
    **done (2026-08-01).** `odag prelude` adopts the everyday dimension
    declarations (weight, length, duration, time, geo, size) in one
    idempotent merge — never a silent default: adoption is explicit,
    versioned, and *is* a specific fingerprint (prelude v1's canonical
    root is pinned by a golden test), which is also the shape of the
    upper-ontology answer: publish optional vocabularies, don't bake one
    in. The User Guide opens with a two-minute Quick Start — install,
    file travel documents under overlapping categories and a typed date,
    ask, check — every output executed for real. Two of the `issues.txt`
    wishes landed after it (2026-08-02): the **empty query is now the
    universe** rather than an error — `odag get`, `odag list` and `odag
    get '*'` are one question, with a new `odag count` and a
    terminal-only display cap so a full store can't flood a screen — and
    **settings were unified**: all six (store, limit, render, bee_api,
    bee_batch, bee_signer) now take a flag, an environment variable, a
    config entry and `set`, resolved by one precedence rule, with the
    surface and settings matrices written into the guide. The **web app
    was then verified end to end** (same day) and turned out to be
    broken by the dimensions release: canonical names were used as DOT
    node identifiers, and DOT reads `:` as a port separator, so any store
    holding a typed date could not be drawn at all — `odag visualize`,
    `/dag/image` and the DOT/LaTeX exports were dead. Fixed (names in
    labels, synthetic identifiers), along with two smaller ones: the REST
    API needed a browser to have loaded the page first, and the UI did
    not URL-encode query terms. Clicking through it in a real browser then
    found three more that HTTP checks had missed, because the endpoints
    answered 200 with wrong content: the query picture ignored parametric
    terms entirely (so it could draw a graph that contradicted the result
    list beside it), it had no union, and the car-market demo failed in any
    session that had used the main page. Rendering endpoints now have
    tests, which they never had — the reason the first bug survived a
    release — and the picture ones assert the drawn graph against the
    query's own answer rather than against a status code.
    Remaining wishes (upper ontologies, computed values) stay on the
    list, not on this item; the wasm/Pyodide one became the next item.

12. **OntoDAG in a browser, on Swarm.** Two things landed on 2026-08-02
    that turn this from an aspiration into a queued task. The base install
    became pure Python — measured: 2 packages, 896 KB, no compiled code —
    so `micropip.install("ontodag")` is possible, where before it failed
    outright because `owlready2` ships sdist-only and micropip cannot build
    sdists. And `ontodag.browser` now implements the four methods
    `recordstore` actually needs (`BytesStore.put/get`, `Pointer.get/set`)
    over a JavaScript bridge, so no fork or special build is required.

    The structural constraint worth knowing: **`ontodag[swarm]` can never
    run in a browser.** It brings 25 further packages including `coincurve`
    and `pycryptodome` — compiled crypto. The browser reaches Swarm through
    JavaScript, permanently, which is why the adapter is a JS bridge rather
    than a port of `BeeBytesStore`.

    Downloading the store is not an option — a shared ontology on Swarm is
    far too large — so the browser must fetch only the fragment each query
    touches. The cost of that is now **measured** rather than guessed
    (`experiments/browser_rounds.py`, 3,221-node store, counting sequential
    round trips because that is the only number a browser feels): a session
    costs ~12 round trips for the first query and **4–5 for each one
    after**, about 250 ms per query at 50 ms latency, against a store that
    was never downloaded.

    Three things get it there. The **cone index is mandatory**, not an
    optimisation — broad queries go from 305 round trips to 10, because a
    published summary answers them instead of walking the cone. **Frontier
    batching** is the one real code change needed: `lazy.py` has the seam
    (`_expand_many`) and nothing calls it, so each node currently costs its
    own round trip; expanding level-order takes specific queries from 47 to
    8. And **miss-and-replay** — blobs are immutable, so a query can be
    replayed for free until its cache is complete — removes any need for
    JSPI or a cross-origin-isolated worker.

    Full implementation record, including what a first page should
    demonstrate and in what order, in [BROWSER.md](BROWSER.md). Blocked on
    two questions about the in-browser Swarm node (what it exposes to page
    JavaScript, and whether it can sign feeds) and on releasing the
    pure-Python base install — the wheel currently on PyPI still carries
    the old hard dependencies, so a demo must serve its own wheel until
    then. **Nothing here has run in a browser yet**; the adapters are
    unit-tested against a fake bridge, including the property that matters
    most — that a JS-backed store computes the byte-identical canonical
    root to an on-disk one, which is what makes a browser a peer and not a
    silo.

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

- **Local-time dates: elaboration default with explicit zone override**
  (queued 2026-08-01; position in `SURFACE_LAYER.md` §5). A bare date is
  zone-relative reality — "2026-08-01" is a different set of instants in
  Vienna than in Tokyo — and today the core resolves it as the UTC day by
  fiat. Implement the surface-layer policy: elaboration interprets bare
  dates/times in the user's local zone by default, with an explicit-zone
  spelling to override; the zone dies at input (IANA tzdata via stdlib
  `zoneinfo`, consulted once, only the resolved UTC interval is stored),
  so canonical arithmetic and merge never see it. Cross-zone query
  mismatch is inherent and stays served by `get_overlapping`.
- **Cyclic (modular) dimension kind — narrowed** (queued 2026-08-01;
  design sketch in `DIMENSIONS.md` §13). One general kind for circles:
  values are arcs with `(start, extent)` canonical form (so
  `hours(22:00..06:00)` wraps through midnight legally), per-head period
  declared as vocabulary, named positions as spellings, fixed-offset
  zones as exact rotations. Narrowed by the UTC-only-core discussion:
  finite cycles (weekdays, months) need NO kind — they are vocabulary
  packs plus surface-side materialized parents, buildable today — so the
  kind is only for *continuous* periodic ranges as query terms (opening
  hours, angles mod 360). Tripwire: a real consumer filing continuous
  periodic ranges; political/DST zones stay walled at elaboration.

## Under discussion (no decision yet)

- **Packs — published ontologies as an ecosystem** (`PACKS.md`, draft
  2026-08-01). What shipped for units is an instance of a general role:
  a published ontology adopted by merge — and the general role raises
  the questions the unit case dodged: name collisions between strangers'
  packs (the Namespaces problem, arriving with urgency), spoofing and
  trust (adopt-by-fingerprint, signed feeds, endorsement of pack roots,
  diff-before-merge), whether packs form a DAG (yes — and adoption is
  order-free because merges commute), where packs live and how they are
  discovered. Third-party pack distribution is frozen until this is
  discussed.

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
  moved to the queue ([PROVENANCE.md](../PROVENANCE.md)) because agent writes
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
