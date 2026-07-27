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
   queries) is roadmap item 1. **Also done: count maintenance.** The delta
   rules described in `experiments/RESULTS.md` are now in `dag.py` — exact
   counts no longer require the whole graph, removing one of the three stated
   reasons `LazyOntoDAG` refuses writes. Historical text follows.

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
3. **Union in `get()`.** Query-side set union over cone intersections
   (disjunctive normal form). Touches no stored state; canonical form
   untouched; planner extension is straightforward.

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
- **Arbitrary relations (roles).** "Alice *authored* Doc1" is not
  subsumption. Tripwire: users mass-reifying relation nodes
  ("authored-by-Alice" categories multiplying per entity). The escape
  hatch: a datom layer (entity, relation, target) stored beside the
  DAG in recordstore, with the DAG supplying what EAV systems lack — a
  taxonomy of entities *and of relations* (`authored` is-under
  `contributed-to`). That combination would be genuinely novel; it is
  also the research-grade step, not to be taken casually.
- **Negation.** "Under A but not under B" requires a closed-world
  decision and prices the complement of a cone. Tripwire: repeated user
  need for exclusion queries that pre-filtering can't express.
- **Aggregation beyond COUNT.** `descendant_count` already gives the
  most-used aggregate for free. SUM/AVG/GROUP BY require values first
  (see arithmetic wall). Tripwire follows from that one.
- **Deletion under multi-writer merge.** Merge is union; a removal can
  be resurrected by an old copy. Options when hit: tombstones (costs
  idempotence care) or a declared grow-only stance. Tripwire: the first
  real collaborative deployment where remove matters.
- **Constraints (disjointness first).** "Nothing is both Cat and Dog"
  buys consistency checking and planner pruning (refuse
  empty-by-axiom intersections before walking). Tripwire: garbage
  queries or polluted merges that a disjointness check would have
  refused.

## Relationship to the rest of the family

- **recordstore** stays the shared value/persistence layer (it was
  extracted from here; the canonical-roots contract is joint property).
- **swarmlite** is the SQL adoption surface; an OntoDAG can
  *materialize* views into `site.db` and publish them with swarmlite's
  publisher (pure downstream artifact, no coupling).
- **ontodag-fs** already shows the query surface insight: paths are
  queries. The lazy reader (Pure now, item 1) is what would let the
  same surface run against a published store without downloading it.

## Suggested first session in this repo

Start with the lazy remote reader: it is swarmlite-shaped work with
known patterns (LRU caches, batched fetches, read-budget tests against
an in-memory store — see swarmlite's test conventions for the
"assert correctness AND the number of fetches" style), it requires no
model decisions, and it turns the Swarm story from "works today" into
"demonstrable at scale from a browser."
