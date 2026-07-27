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

Last updated 2026-07-25.

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
  section for why) and does not yet use published cone summaries, so a query
  whose narrowest term is a broad category still costs that cone.

## Next up (concrete, queued)

1. **Cone summaries for broad queries.** The on-demand reader (above) still
   enumerates a cone when a query's narrowest term is broad. A small
   deterministically-derived summary per popular category — fetched instead of
   walked — is what turns that into a handful of fetches, and it is the first
   step of the bitmap-index work below, pulled forward by an actual need rather
   than speculation. Being *derived*, it never touches the canonical form.
2. **Writing back from a partially-loaded graph.** `LazyOntoDAG` is read-only on
   purpose: the exactness rules (minimal links, exact counts) are properties of
   the whole graph, and change-detection diffs a complete set of records, so
   neither is defined when only a fragment is resident. Making edits possible
   without full residence means deciding which invariants can be checked locally
   — a real design question, not a port.
3. **A published "latest version" pointer.** Swarm *feeds* give a stable address
   that always resolves to your newest root — the missing piece for subscribing
   to someone's ontology. The signing machinery landed upstream; OntoDAG needs to
   adopt it and add an integration test.
4. **Multi-writer collaboration.** The storage layer can now three-way-merge
   diverged versions and auto-reconcile concurrent commits. OntoDAG's remaining
   job is the merge *rule*: when two people edit the same item, reconcile at the
   graph level using the order-independent merge of §5 (whose properties were
   built for exactly this), then recommit. Goal: several writers, one shared
   ontology, no server.

## Then: more capability, still no model change

The remaining "pure now" items of `DATABASE_DIRECTION.md` — they preserve the
canonical form and the merge properties untouched:

- **Dimension lattices** — time, geo and numeric *ranges* handled in the spirit of
  OntoDAG rather than by bolting on a value engine: generate category chains
  (century → decade → year → month → day, geo quad-tree cells, interval halvings)
  and classify items under the finest cell, so "photos of dogs from last summer
  near Balaton" stays one cone intersection. This is what the original roadmap's
  "predicated (parametric) items" and "space and time calculation" become; the
  same trick covers hierarchical value types (image → png) and is where a way to
  declare a partial ordering over values, and to retrieve items in that order,
  would belong.
- **Union in `get()`.** Query-side set union over cone intersections; stored state
  and canonical form untouched.

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
- **Namespaces.** Reconciling different people's naming — spelling, language, and
  the same word used for different things — so DAGs built independently can be
  merged without name collisions.
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
