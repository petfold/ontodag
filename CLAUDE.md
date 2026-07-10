# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

OntoDAG is a DAG-based associative memory and category manager. Items are placed into the DAG under supercategories; querying with a set of categories returns the intersection of their descendants. The root node `*` is the implicit ancestor of all top-level items.

Conceptually OntoDAG is a **subsumption-only ontology**: a multi-parent category lattice kept in transitively reduced form, with one query primitive — the intersection of descendant cones ("everything below *all* of these categories"). It sits deliberately between flat tags/folders (no multi-parent subsumption) and full OWL/description-logic stacks (properties, axioms, reasoning). Its distinguishing property is that the **transitive reduction of a DAG is unique**, which gives the structure a canonical form. That canonical form is what later makes it content-addressable, diffable, and mergeable — see "Planned Swarm integration" below. Keeping the invariants exact is therefore not cosmetic: they are the precondition for the persistence and multi-writer story.

## Branch history note

The `recordstore` branch was rebased onto `origin/main` (July 2026), so it now sits on top of the package restructuring (PR #5) and the earlier PRs (merge-based workflow, DOT/LaTeX export, car-market demo, Manchester-syntax OWL). The pre-rebase state — which still had the old flat layout (`dag.py`, `ontodag.py`, `loader.py` at the repo root) — is preserved on the local branch `recordstore-pre-rebase`. The legacy standalone `ontodag.py` implementation and its tests (`testontodag.py`, `testitem_ontodag.py`) were superseded by the package and no longer exist on this branch. The remote `origin/recordstore` predates the rebase, so the first push needs `--force-with-lease`.

## Running tests

Tests use `pytest` from the repo root; `conftest.py` puts `src/` on the import path, so no `PYTHONPATH` fiddling is needed. Note that `testdag.py`/`testitem.py`/`testowl.py` do **not** match pytest's default `test_*.py` discovery pattern — running `pytest tests/` silently skips them, so name them explicitly:

```bash
python3 -m pytest tests/testdag.py tests/testitem.py -v    # core DAG logic
python3 -m pytest tests/test_invariants.py -v              # structural invariant tests (all 12 must pass)
python3 -m pytest tests/test_boundaries.py -v              # dependency-boundary tests (must always pass)
```

Expected failures in the local environment (missing optional deps, not regressions): `graphviz` and `dot2tex` are not installed, so the three `testdag.py` tests that render (`test_visualize`, `test_descendant_count_after_put`, `test_generate_dot_source_to_tex`) fail; `owlready2` is not installed, so `tests/testowl.py` fails at collection.

All 12 invariant tests pass as of July 2026 (fixes I1–I4, I6 landed; see "Known bugs" below for what remains). The helpers in `tests/test_invariants.py` (`reach`, `edge_set`) compute reachability independently of the traversal code under test, so they remain a valid oracle while `dag.py` is being changed.

## Architecture

The project is a `src/`-layout package (`pyproject.toml`, `pip install -e .` or run from the repo root via `conftest.py`'s path insert). Two top-level packages, with a strictly one-directional (future) dependency ontodag → recordstore:

### `src/ontodag/` — the core data structure
- `dag.py`:
  - `Item`: graph node with `name`, `neighbors` (set of child `Item`s), `descendant_count`
  - `DAG`: base directed graph — `add_node`, `add_edge`, `remove_edge`, `get_descendants`, `get_ancestors`, `topological_sort`, `intersection_dag`; descendant counts are recalculated from scratch on each structural change
  - `OntoDAG(DAG)`: extends DAG with `put(item, super_categories)`, `get(super_categories)`, `remove(item)`, `merge`, `copy_subdag`, `prune_to_common_descendants` and a root node `*`; `put` accepts an optional `optimized=True` flag that prunes redundant supercategory links before inserting; overrides `add_edge` to call `_remove_unneeded_edges`
  - `OntoDAGVisualizer`: Graphviz-backed renderer; lazy-imports `graphviz` so it doesn't break non-visualization code
- `owl.py`: OWL import/export via `owlready2`, including Manchester syntax; reached lazily through `ontodag.OWLOntology` (module `__getattr__` in `__init__.py`), so importing the core never touches `owlready2`
- `__main__.py`: CLI (`python3 -m ontodag` or the `ontodag` script) for import/export/query on OWL files

### `src/recordstore/` — generic versioned record store (see "Swarm integration" below)

### `web/`
Flask REST API + UI wrapping `OntoDAG`, including the car-market demo (`/market`).

## Web app

```bash
cd web && python3 app.py   # starts Flask dev server on localhost:5000 (needs flask, graphviz, owlready2, dot2tex)
```

REST endpoints: `POST /dag` (reset), `GET/POST/DELETE /dag/node`, `GET /dag/query?cat=A,B`, image renders (`/dag/image`, `/dag/query/image`), import (`/dag/import`, `/dag/query/import`), and exports in OWL/Manchester/DOT/LaTeX (`/dag/export`, `/dag/export/{omn,dot,tex}`, same under `/dag/query/`).

## Key invariants (from `tests/test_invariants.py`)

The invariant test file documents seven properties the data structure should uphold:
- **I1 Acyclicity** — `add_edge` must reject cycles
- **I2 Transitive reduction** — no redundant edges (if A→B→C exists, A→C must not)
- **I3 Order independence** — `put(X, [A, B])` and `put(X, [B, A])` must produce identical graphs
- **I4 No aliasing** — derived DAGs (intersection, copy) must not share `Item` objects with sources
- **I5 Counter consistency** — `descendant_count` must always equal the true reachable count
- **I6 Iterative traversal** — `get_descendants`/`get_ancestors` must not use recursion (Python recursion limit)
- **I7 Merge algebra** — `merge` must be commutative and idempotent (CRDT property)

## Dependency boundaries (from `tests/test_boundaries.py` — must always pass)

- **B1 The core stays Swarm-free.** The `ontodag` package must remain importable and fully functional with no Swarm, no `recordstore`, no network, and no optional dependency installed (`owlready2`, `graphviz`, `dot2tex`, `flask`). The Swarm layer is an optional persistence backend layered *on top of* the data structure — never a requirement of it. When the `SwarmOntoDAG` adapter lands, it must be reachable only via explicit import (and eventually an `[swarm]` extra in `pyproject.toml`), keeping plain `import ontodag` clean.
- **B2 `recordstore` never depends on OntoDAG** and keeps its module-level imports stdlib-only (third-party imports like `requests` in `BeeChunkStore` stay lazy inside methods). This is the boundary that keeps a later extraction to its own repo cheap — see `SWARM_DESIGN.md` §2.

## Known bugs and fix status

Fixed (July 2026), one commit per invariant:

1. ~~**No cycle check in `add_edge`.**~~ **Fixed (I1)** — `DAG.add_edge` raises `ValueError` when the edge would create a cycle, via the iterative early-exit `DAG._is_reachable`; `OntoDAG.add_edge` performs the check before `_remove_unneeded_edges` so a rejected edge never mutates the graph.
2. ~~**Transitive reduction incomplete and order-dependent.**~~ **Fixed (I2, I3)** — `OntoDAG.add_edge` skips any edge whose target is already reachable, then prunes ancestor edges as before. Note: `testdag.test_descendant_count_after_remove` had asserted the old non-reduced contraction result and was updated to the reduced expectation.
3. ~~**`intersection_dag` aliases live nodes.**~~ **Fixed (I4)** — builds fresh `Item`s via a name→copy mapping, mirroring `copy_subdag`; `is` name comparisons replaced with `==`.
4. ~~**Recursive traversals overflow on deep graphs.**~~ **Fixed (I6)** — `get_descendants`, `get_ancestors`, and `_get_affected_nodes` use explicit frontier stacks.

5. ~~**Quadratic structure maintenance.**~~ **Fixed (July 2026)** — `Item` has a `parents` set maintained symmetrically with `neighbors` via `_EdgeSet` (a set subclass that syncs the reverse direction even under direct `neighbors` mutation); `get_ancestors`, `_get_affected_nodes` and `remove` walk `parents` instead of scanning the graph; descendant-count refreshes are batched per public operation (`_batched_count_updates`) instead of per edge. `parents` is the in-memory form of the record schema's `up` list, so the in-memory and persisted shapes now match.

Still open:

6. **`topological_sort` is still recursive** (used by `merge` and optimized `put`), so those can still hit the recursion limit on graphs deeper than ~1000 levels; not covered by I6's tests. Convert to iterative post-order when touched next.

### Secondary cleanups (not blocking the invariant suite)
- ~~**`__init__.py` forces an `owlready2` dependency.**~~ **Done** — `src/ontodag/__init__.py` now exposes `OWLOntology` via a lazy module `__getattr__`, enforced by `tests/test_boundaries.py`. Still open: `pyproject.toml` lists `graphviz` and `owlready2` as hard dependencies; move them to optional dependency groups (like the existing `[web]` extra).
- **API takes `Item` objects but re-resolves by name.** `put`/`get` accept `Item`s then immediately do `self.nodes[x.name]`. Accept plain strings at the public boundary and keep `Item` construction internal (see "Identity" below).
- **Nondeterministic iteration.** `topological_sort`, `merge`, and any serialization iterate Python `set`s, so output order varies across runs. Sort by name at every iteration point — required for a canonical, content-addressable encoding later.
- **`print()` in `prune_to_common_descendants`** should be `logging`.

## Identity: strings vs pointers (design decision)

Keep both, at different layers:
- **Inside one DAG instance:** edges (`neighbors`, and the new `parents`) stay as object references — O(1) hops, natural for a live graph.
- **At every boundary** — public API, serialization, and anything crossing *between* DAG instances — identity is the **name string**. `Item.__eq__`/`__hash__` already compare names only, so names are the true identity; pointer identity must never escape a single `DAG` object. Letting pointer identity leak across instances is exactly what caused the `intersection_dag` aliasing bug (#3).
- Do **not** convert in-memory `neighbors` to sets of strings — that just adds a dict lookup per hop for no benefit.

## Instance vs class distinction

The graph currently mixes classes and instances as undifferentiated `Item`s (a stored photo and the category `vehicle` are both nodes). The OWL export already assumes every node is a class. Make this explicit — e.g. a `kind` field, or the convention that payload-bearing nodes are instances — before it gets frozen into a persisted encoding.

## Swarm integration — status and where things live

The medium-term goal (see repo roadmap: "DAG-only graph database for Ethereum Swarm" and "plugin to store the DAG in a decentralized way") is to persist OntoDAG on Ethereum Swarm, a content-addressed immutable chunk store.

**Full design rationale is in `docs/SWARM_DESIGN.md` — read it before touching `src/recordstore/` or starting the OntoDAG-Swarm adapter.** It covers: why a generic `recordstore` layer exists at all rather than calling Swarm directly, and the decision (deliberately deferred, with split criteria) on moving `recordstore` to its own repo (§2), the node record schema for the eventual adapter (§3), why storage is one-record-per-chunk for now and when that should change (§4), the planned multi-writer/CRDT merge mechanism (§5), the performance model and the four caching layers involved (§6), what's tested vs. not (§7), and the recommended sequencing of remaining work (§8). This file (`CLAUDE.md`) has the day-to-day task list; `SWARM_DESIGN.md` has the "why."

### What already exists (`src/recordstore/`)

A versioned key→record store over a content-addressed chunk store — the generic substrate `OntoDAG`-on-Swarm will sit on. Implemented and tested:
- `RecordStore`: staged put/get/delete, `commit() → root`, `RecordStore.at(root)` read-only snapshots, sorted prefix iteration (`keys(prefix)`).
- A persistent, canonically-encoded compacted radix trie (own implementation, not mantaray — see `SWARM_DESIGN.md` §2 for why compatibility with mantaray was deferred rather than required).
- `ChunkStore` backends: `MemoryChunkStore` (test double) and `BeeChunkStore` (real Bee node over `/bytes`).
- `Pointer` backends: `MemoryPointer`, `FilePointer`. `SwarmFeedPointer` is a documented stub — real feed writes need client-side SOC signing (secp256k1), deliberately deferred; see `SWARM_DESIGN.md` §5.

Tests: `tests/test_recordstore.py` (15 unit tests — canonical roots, snapshot isolation, structural sharing, no-aliasing, `FilePointer` persistence/atomicity), `tests/test_recordstore_fuzz.py` (model-based fuzz test against a dict oracle, 12 seeded runs × 400 ops, checks the canonical-root property under arbitrary put/delete histories), `tests/test_recordstore_bee.py` (integration test against a live Bee node — skips automatically unless `BEE_API` is set):

```bash
python3 -m pytest tests/test_recordstore.py tests/test_recordstore_fuzz.py -v   # no external deps

# integration test against a live node:
BEE_API=http://<node>:1633 [BEE_BATCH=<batchID>] python3 -m pytest tests/test_recordstore_bee.py -v
```

**Bee integration status (run July 2026 — read the label carefully).** All 4 tests passed, plus an ad-hoc `SwarmOntoDAG`-over-`BeeChunkStore` roundtrip, against **`bee dev` v2.7.1** — the last release shipping dev mode. What this validated: the client↔node **HTTP contract only** (`/bytes` upload/download with real BMT references, `/stamps`, Bee's splitter on oversized records). What it deliberately does NOT validate: anything network-level. Bee v2.8.0 was a breaking network upgrade (handshake 15.0.0, hive 2.0.0), so 2.7.x nodes cannot join today's Swarm at all, and 2.8+ removed dev mode without a lightweight local replacement (the community bee-factory rig is dead since 2022). Real-network validation — push-sync/retrieval across nodes, postage validity and expiry, GC/pinning behavior — requires running these same tests with `BEE_API`/`BEE_BATCH` pointed at your own funded Bee ≥2.8.1 light node; that remains open. Re-run the dev-mode check only if `BeeChunkStore`'s encoding changes; don't mistake it for network validation.

### `SwarmOntoDAG` adapter (`src/ontodag/swarm_adapter.py`) — DONE (July 2026)

An `OntoDAG` subclass persisted through a `RecordStore`, per `SWARM_DESIGN.md` §3/§6: one record per node keyed by name (`up`/`down` sorted, `count`, `kind`, `payload`, `meta`); full hydration into memory on construction; all mutation semantics inherited from `OntoDAG`; `commit()` diffs against the last-synced records and stages only changed nodes. The store is duck-typed — the module imports nothing from `recordstore` (B2), and `ontodag.SwarmOntoDAG` is exposed via the lazy `__getattr__` so `import ontodag` stays clean (B1). `put` accepts optional `kind`/`payload`/`meta` (records default to `kind: "class"` — see "Instance vs class distinction").

Tests: `tests/test_swarm_adapter.py` (13 tests against `MemoryChunkStore`): roundtrip + rehydrated queries, history/put-order-independent canonical roots, idempotent commit, incremental staging, invariants after rehydration, merge convergence to identical roots from either side (the §5 CRDT precondition in persisted form), extras roundtrip, persisted removal.

### What does not exist yet

- A committed Bee-backed `SwarmOntoDAG` integration test (an ad-hoc roundtrip passed against `bee dev` 2.7.1 in July 2026, but only as a one-off script; follow the `tests/test_recordstore_bee.py` pattern if making it permanent, same `BEE_API` gate and the same dev-mode caveat above).
- Real-network validation of `BeeChunkStore` (see "Bee integration status" above — needs a funded Bee ≥2.8.1 node).
- The GSOC-based CRDT merge (`SWARM_DESIGN.md` §5).
- The real `SwarmFeedPointer` (needs a signing dependency decision — flag this to the user rather than picking a crypto library unilaterally).
- Leaf-packing / B-tree-style chunk layout (`SWARM_DESIGN.md` §4) — do not implement pre-emptively; it needs real usage data first.
- Async/batched `get_many()` chunk fetches (`SWARM_DESIGN.md` §6) — only relevant once partial loading exists; full hydration reads every record once anyway.

## Previous tasks — DONE (July 2026)

1. **`dag.py` invariant fixes** — all 12 tests in `tests/test_invariants.py` pass; one focused commit per invariant (I1, I2+I3, I4, I6), plus item 5 (reverse adjacency + batched counts). Remaining `dag.py` work: item 6 under "Known bugs".
2. **`SwarmOntoDAG` adapter** — see above.

## Current task: none assigned

Next candidates, in the order `SWARM_DESIGN.md` §8 suggests: real-network validation against a funded Bee ≥2.8.1 node (the dev-mode API-contract check is done — see "Bee integration status"), then the GSOC-based merge (§5) / feed pointer — the latter needs a signing-library decision from the user first.

## Working across sessions

This is a multi-session project. At the start of each session:
1. Run the full test suite (`testdag.py`, `testitem.py`, `test_invariants.py`, `test_boundaries.py`, `test_swarm_adapter.py`, `test_recordstore.py`, `test_recordstore_fuzz.py` — the first two must be named explicitly, see "Running tests") to confirm the starting state matches what this file claims.
2. Check which of the two current-task sections above is still open, and update this file's "Definition of done" / "What does not exist yet" sections as work completes — this file should always reflect actual repo state, not a stale plan.
3. Prefer small, focused commits over large multi-concern ones; each should be reviewable against one invariant or one design-doc section.
