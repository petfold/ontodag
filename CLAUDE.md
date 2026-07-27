# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

OntoDAG is a DAG-based associative memory and category manager. Items are placed into the DAG under supercategories; querying with a set of categories returns the intersection of their descendants. The root node `*` is the implicit ancestor of all top-level items.

Conceptually OntoDAG is a **subsumption-only ontology**: a multi-parent category lattice kept in transitively reduced form, with one query primitive — the intersection of descendant cones ("everything below *all* of these categories"). It sits deliberately between flat tags/folders (no multi-parent subsumption) and full OWL/description-logic stacks (properties, axioms, reasoning). Its distinguishing property is that the **transitive reduction of a DAG is unique**, which gives the structure a canonical form. That canonical form is what later makes it content-addressable, diffable, and mergeable — see "Planned Swarm integration" below. Keeping the invariants exact is therefore not cosmetic: they are the precondition for the persistence and multi-writer story.

## Branch history note

The `recordstore` branch was rebased onto `origin/main` (July 2026), so it now sits on top of the package restructuring (PR #5) and the earlier PRs (merge-based workflow, DOT/LaTeX export, car-market demo, Manchester-syntax OWL). The pre-rebase state — which still had the old flat layout (`dag.py`, `ontodag.py`, `loader.py` at the repo root) — is preserved on the local branch `recordstore-pre-rebase`. The legacy standalone `ontodag.py` implementation and its tests (`testontodag.py`, `testitem_ontodag.py`) were superseded by the package and no longer exist on this branch. The rebased branch was force-pushed to `origin/recordstore` on 2026-07-12, so local and remote now agree; normal pushes work from here on.

## Running tests

Tests use `pytest` from the repo root; `conftest.py` puts `src/` on the import path, so no `PYTHONPATH` fiddling is needed. Note that `testdag.py`/`testitem.py`/`testowl.py` do **not** match pytest's default `test_*.py` discovery pattern — running `pytest tests/` silently skips them, so name them explicitly:

```bash
python3 -m pytest tests/testdag.py tests/testitem.py -v    # core DAG logic
python3 -m pytest tests/test_invariants.py -v              # structural invariant tests (all 12 must pass)
python3 -m pytest tests/test_boundaries.py -v              # dependency-boundary tests (must always pass)
python3 -m pytest tests/test_cli.py -v                     # `odag` CLI (backends, set, swarm wiring via in-memory store)
python3 -m pytest tests/test_lazy.py -v              # LazyOntoDAG: eager-oracle correctness + fetch budgets

# Live-node CLI Swarm test — skips unless BEE_API *and* BEE_BATCH are set
# (always pass a real BEE_BATCH so nothing auto-buys; see "Bee integration status"):
BEE_API=http://<node>:1633 BEE_BATCH=<batchID> python3 -m pytest tests/test_swarm_bee.py -v
```

All optional deps are now installed locally (`graphviz` and `dot2tex` since early July 2026; `owlready2` since 2026-07-21), so there are no expected failures left: `tests/testowl.py` collects and passes (7 tests), and the full suite (the files above plus `testowl.py` and `test_lazy.py`) is 107/107 green. Note the 2026-07-21 fix in `owl.py`: `ontology.save()` is called with the path *positional* because upstream `owlready2` names the parameter `file` while the `ontopy` fork names it `filename` — the old `filename=` keyword crashed `.owl` export under upstream owlready2 (silently swallowed into `**kargs`, falling back to the empty `onto_path`).

All 12 invariant tests pass as of July 2026 (fixes I1–I4, I6 landed; see "Known bugs" below for what remains). The helpers in `tests/test_invariants.py` (`reach`, `edge_set`) compute reachability independently of the traversal code under test, so they remain a valid oracle while `dag.py` is being changed.

## Architecture

The project is a `src/`-layout package (`pyproject.toml`, `pip install -e .` or run from the repo root via `conftest.py`'s path insert). One top-level package (`ontodag`), plus the external `recordstore` dependency (see below) with a strictly one-directional dependency ontodag → recordstore:

### `src/ontodag/` — the core data structure
- `dag.py`:
  - `Item`: graph node with `name`, `neighbors` (set of child `Item`s), `descendant_count`
  - `DAG`: base directed graph — `add_node`, `add_edge`, `remove_edge`, `get_descendants`, `get_ancestors`, `topological_sort`, `intersection_dag`; descendant counts are recalculated from scratch on each structural change
  - `OntoDAG(DAG)`: extends DAG with `put(item, super_categories)`, `get(super_categories)`, `remove(item)`, `merge`, `copy_subdag`, `prune_to_common_descendants` and a root node `*`; `put` accepts an optional `optimized=True` flag that prunes redundant supercategory links before inserting; overrides `add_edge` to call `_remove_unneeded_edges`
  - `OntoDAGVisualizer`: Graphviz-backed renderer; lazy-imports `graphviz` so it doesn't break non-visualization code
- `owl.py`: OWL import/export via `owlready2`, including Manchester syntax; reached lazily through `ontodag.OWLOntology` (module `__getattr__` in `__init__.py`), so importing the core never touches `owlready2`
- `__main__.py`: the `odag` CLI (`python3 -m ontodag` or the `odag` script) — a Unix-style command: silent on success, errors to stderr with non-zero exit, results one-per-line to stdout. Persists to a default native-text store at `~/.ontodag/store.od` (override with `-f PATH`, `$ONTODAG_STORE`, or `set store PATH` written to `~/.ontodag/config`; home dir override `$ONTODAG_HOME`). `odag put cat` / `odag get cat` need no file argument. No command → reads commands from stdin (pipe/batch) or an interactive `>` prompt on a tty. Paths ending in `.owl`/`.omn` use OWL/Manchester (owlready2 imported lazily, so the native path stays dependency-free); `import`/`export`/`merge` convert between them. Commands: put/get/remove/show/list/merge/import/export/visualize/set/help.
  - **Storage backends** (`FileBackend`/`SwarmBackend`, `_make_backend`): a store spec is either a filesystem path or a `swarm:NAME` URI. `set store swarm:NAME` persists the spec verbatim to config so every later invocation uses Swarm — content via `BeeBytesStore`, the mutable latest-root via a local `FilePointer` at `~/.ontodag/NAME.root` (no signing key, so this does *not* need the pin bump or `SwarmFeedPointer`). Bee config from `$BEE_API`/`$BEE_BATCH` or `bee_api`/`bee_batch` in config. `recordstore` + `eager` are imported lazily only on the Swarm path, so `import ontodag` and the native path stay dependency-free (B1 verified). The Swarm path also needs `requests` (recordstore's `BeeBytesStore.__init__` imports it) — declared as the `swarm` extra in `pyproject.toml` (`pip install -e ".[swarm]"`); a missing dep is caught in `SwarmBackend._record_store` and re-raised as a friendly `odag: ... install the swarm extra` message rather than a raw `ModuleNotFoundError`. Wiring is duck-typed via `SwarmBackend(name, store_factory=...)`; `tests/test_cli.py` exercises the full load→put→commit→reload cycle through `dispatch()` against an in-memory `RecordStore`, so the CLI is validated without a Bee node (the HTTP path is covered by recordstore's live-node suite). Follow-up: swap `FilePointer` for `SwarmFeedPointer` (available since recordstore v0.4.0, now installed), giving a fully on-Swarm mutable root — roadmap item 2 below.

### `recordstore` — generic versioned record store (external, see "Swarm integration" below)

Extracted to its own repo **github.com/petfold/recordstore** (July 2026, `git subtree split`, history preserved) and depended on from PyPI in `pyproject.toml` as `recordstore>=0.11` (a floor, not an exact pin: every release since v0.3.0 has been additive). Its test suite (`test_recordstore.py`, `test_recordstore_fuzz.py`, `test_recordstore_bee.py`, plus the ported stdlib-only boundary check) lives in that repo as of `v0.1.1`; this repo keeps only its consumer-side checks (`test_boundaries.py` B2, `test_eager.py`). Public-API summary (manually synced): `docs/recordstore-interface.md`.

`BeeChunkStore` was renamed to **`BeeBytesStore`** in `v0.2.0` (2026-07-19) — the class wraps Bee's `/bytes` (blob-level) endpoint, not the raw `/chunks/{address}` single-chunk primitive, and the old name implied the latter. Then in **`v0.3.0`** (2026-07-20) the abstraction itself was renamed `ChunkStore` → **`BytesStore`** and `MemoryChunkStore` → **`MemoryBytesStore`** for the same reason (a recordstore storage unit is a `put(bytes) → ref` blob, not a Swarm chunk), and the `RecordStore` store parameter `chunks` → `bytes_store`. The pin above was bumped for both; no OntoDAG source code referenced the old names — only docs and `tests/test_eager.py`, updated in the same pass.

**Version state (2026-07-25): the requirement is `recordstore>=0.11` and 0.11.0 is installed locally.** (Before this, the declared floor was already `>=0.11` while the environment still had 0.10.0 — i.e. the install did not satisfy `pyproject.toml`; fixed by upgrading the user-site install. Note PEP 668 marks this Python as externally managed, so installing needs `pip install --user --break-system-packages`.) The releases since v0.3.0 relevant to OntoDAG: a **real `SwarmFeedPointer`** (v0.4.0/0.4.1 — signed Swarm feeds via the `swarm-bee` package behind a `recordstore[feeds]` extra; this *is* the signing-library decision this repo's roadmap was waiting on, made upstream), **concurrent bulk I/O** (v0.5.0–v0.7.1 — `RecordStore.items()`, `BytesStore.get_many`/`put_many`, pooled HTTP sessions, bulk trie writes in `commit()`), and **multi-writer machinery** (v0.8.0–v0.10.0 — canonical three-way `RecordStore.merge` with a `resolver` hook and `MergeConflict`/`ABSENT`/`DELETE`, auto-reconciling `commit(reconcile=True)`, best-effort `SwarmFeedPointer.compare_and_set` for cross-process reconcile). Adoption items are in "What does not exist yet" below; the new API surface is summarized in `docs/recordstore-interface.md`.

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

- **B1 The core stays Swarm-free.** The `ontodag` package must remain importable and fully functional with no Swarm, no `recordstore`, no network, and no optional dependency installed (`owlready2`, `graphviz`, `dot2tex`, `flask`). The Swarm layer is an optional persistence backend layered *on top of* the data structure — never a requirement of it. When the `EagerOntoDAG` adapter lands, it must be reachable only via explicit import (and eventually an `[swarm]` extra in `pyproject.toml`), keeping plain `import ontodag` clean.
- **B2 `recordstore` never depends on OntoDAG** and keeps its module-level imports stdlib-only (third-party imports like `requests` in `BeeBytesStore` stay lazy inside methods). This boundary made the July 2026 extraction to `github.com/petfold/recordstore` cheap — see `SWARM_DESIGN.md` §2; the checks now run against the installed package.

## Known bugs and fix status

Fixed (July 2026), one commit per invariant:

1. ~~**No cycle check in `add_edge`.**~~ **Fixed (I1)** — `DAG.add_edge` raises `ValueError` when the edge would create a cycle, via the iterative early-exit `DAG._is_reachable`; `OntoDAG.add_edge` performs the check before `_remove_unneeded_edges` so a rejected edge never mutates the graph.
2. ~~**Transitive reduction incomplete and order-dependent.**~~ **Fixed (I2, I3)** — `OntoDAG.add_edge` skips any edge whose target is already reachable, then prunes ancestor edges as before. Note: `testdag.test_descendant_count_after_remove` had asserted the old non-reduced contraction result and was updated to the reduced expectation.
3. ~~**`intersection_dag` aliases live nodes.**~~ **Fixed (I4)** — builds fresh `Item`s via a name→copy mapping, mirroring `copy_subdag`; `is` name comparisons replaced with `==`.
4. ~~**Recursive traversals overflow on deep graphs.**~~ **Fixed (I6)** — `get_descendants`, `get_ancestors`, and `_get_affected_nodes` use explicit frontier stacks.

5. ~~**Quadratic structure maintenance.**~~ **Fixed (July 2026)** — `Item` has a `parents` set maintained symmetrically with `neighbors` via `_EdgeSet` (a set subclass that syncs the reverse direction even under direct `neighbors` mutation); `get_ancestors`, `_get_affected_nodes` and `remove` walk `parents` instead of scanning the graph; descendant-count refreshes are batched per public operation (`_batched_count_updates`) instead of per edge. `parents` is the in-memory form of the record schema's `up` list, so the in-memory and persisted shapes now match.

6. ~~**`topological_sort` is still recursive.**~~ **Fixed (July 2026)** — iterative post-order DFS with an explicit `(node, iterator)` path stack, completing I6; covered by `test_topological_sort_is_iterative` (1500-deep chain) and an ordering test in `test_invariants.py`.

No known open bugs in `dag.py`; remaining items are the secondary cleanups below.

### Secondary cleanups (not blocking the invariant suite)
- ~~**`__init__.py` forces an `owlready2` dependency.**~~ **Done** — `src/ontodag/__init__.py` now exposes `OWLOntology` via a lazy module `__getattr__`, enforced by `tests/test_boundaries.py`. Still open: `pyproject.toml` lists `graphviz` and `owlready2` as hard dependencies; move them to optional dependency groups (like the existing `[web]` extra).
- ~~**API takes `Item` objects but re-resolves by name.**~~ **Done (2026-07-21)** — the public boundary accepts plain strings everywhere an `Item` was required: `put` (subcategory + supers), `get` terms, `remove`, `get_descendants`/`get_ancestors`, and the `EagerOntoDAG` overrides (via `_name_of` in `dag.py`); `Item` arguments remain accepted and are resolved by name (earlier partial fix: `get_descendants`/`get_ancestors` re-resolve instead of traversing the caller's object). `remove` now also resolves fresh `Item("x")` arguments to the instance's node — previously a fresh Item passed the existence check but had empty `parents`, so removal would orphan children and leave dangling edges (latent footgun, now tested in `TestStringAPI`). The user-facing docs (`docs/USER_GUIDE.md`) use the string API throughout.
- **Nondeterministic iteration.** `topological_sort`, `merge`, and any serialization iterate Python `set`s, so output order varies across runs. Sort by name at every iteration point — required for a canonical, content-addressable encoding later.
- **`print()` in `prune_to_common_descendants`** should be `logging`.

## Identity: strings vs pointers (design decision)

Keep both, at different layers:
- **Inside one DAG instance:** edges (`neighbors`, and the new `parents`) stay as object references — O(1) hops, natural for a live graph.
- **At every boundary** — public API, serialization, and anything crossing *between* DAG instances — identity is the **name string**. `Item.__eq__`/`__hash__` already compare names only, so names are the true identity; pointer identity must never escape a single `DAG` object. Letting pointer identity leak across instances is exactly what caused the `intersection_dag` aliasing bug (#3).
- Do **not** convert in-memory `neighbors` to sets of strings — that just adds a dict lookup per hop for no benefit.

## Swarm integration — status and where things live

The medium-term goal (see `docs/ROADMAP.md`, which absorbed the old README checklist on 2026-07-25 — the "DAG-only graph database for Ethereum Swarm" and "plugin to store the DAG decentrally" items) is to persist OntoDAG on Ethereum Swarm, a content-addressed immutable chunk store.

**Full design rationale is in `docs/SWARM_DESIGN.md` — read it before touching `recordstore` or the OntoDAG-Swarm adapter.** It covers: why a generic `recordstore` layer exists at all rather than calling Swarm directly, and the move of `recordstore` to its own repo (§2 — executed July 2026, see the update note there), the node record schema for the eventual adapter (§3), why storage is one-record-per-chunk for now and when that should change (§4), the planned multi-writer/CRDT merge mechanism (§5), the performance model and the four caching layers involved (§6), what's tested vs. not (§7), and the recommended sequencing of remaining work (§8). This file (`CLAUDE.md`) has the day-to-day task list; `SWARM_DESIGN.md` has the "why."

### What already exists (the `recordstore` package — external repo, `>=0.11` from PyPI)

A versioned key→record store over a content-addressed chunk store — the generic substrate `OntoDAG`-on-Swarm will sit on. Implemented and tested:
- `RecordStore`: staged put/get/delete, `commit() → root`, `RecordStore.at(root)` read-only snapshots, sorted prefix iteration (`keys(prefix)`).
- A persistent, canonically-encoded compacted radix trie (own implementation, not mantaray — see `SWARM_DESIGN.md` §2 for why compatibility with mantaray was deferred rather than required).
- `BytesStore` backends: `MemoryBytesStore` (test double) and `BeeBytesStore` (real Bee node over `/bytes`).
- `Pointer` backends: `MemoryPointer`, `FilePointer`. `SwarmFeedPointer` is a documented stub — real feed writes need client-side SOC signing (secp256k1), deliberately deferred; see `SWARM_DESIGN.md` §5.

Tests (in the recordstore repo since `v0.1.1`, run them from a checkout of that repo): `tests/test_recordstore.py` (15 unit tests — canonical roots, snapshot isolation, structural sharing, no-aliasing, `FilePointer` persistence/atomicity), `tests/test_recordstore_fuzz.py` (model-based fuzz test against a dict oracle, 12 seeded runs × 400 ops, checks the canonical-root property under arbitrary put/delete histories), `tests/test_recordstore_bee.py` (integration test against a live Bee node — skips automatically unless `BEE_API` is set):

```bash
# from a checkout of github.com/petfold/recordstore:
python3 -m pytest tests/ -v   # no external deps; Bee tests skip without BEE_API

# integration test against a live node:
BEE_API=http://<node>:1633 [BEE_BATCH=<batchID>] python3 -m pytest tests/test_recordstore_bee.py -v
```

**Bee integration status (July 2026).** Two runs, different evidence levels:

1. **`bee dev` v2.7.1** (last release shipping dev mode — 2.8.0 removed it and broke protocol compatibility with 2.7.x, and the community bee-factory rig is dead since 2022): all 4 tests passed, plus an ad-hoc `EagerOntoDAG`-over-`BeeBytesStore` roundtrip. Validates the client↔node HTTP contract only; an isolated API fake, not network evidence. Re-run only if `BeeBytesStore`'s encoding changes.
2. **Real node, 2026-07-11:** all 4 tests passed against a live **bee v2.8.1 light node on Gnosis mainnet** (Swarm Desktop's node, `localhost:1633`) using a **real purchased postage batch** (depth 17, immutable, ~2-day TTL). Validates the current bee version, real on-chain stamps, and real BMT refs. Two things learned: mainnet rejects batches below ~1 day of validity at the current storage price, so the test's auto-buy default (`/stamps/100000000/20`) fails on a real node — **always set `BEE_BATCH` against a real node** (also avoids surprise spending); and batch purchase → usable took ~65s on-chain.

3. **Real node, 2026-07-19:** all 4 tests passed again, this time run from the extracted recordstore repo (post-`v0.1.1` move), against Swarm Desktop's bee v2.8.1 light node on Gnosis mainnet with a fresh purchased batch (depth 17, immutable, ~2-day TTL, ≈0.03 xBZZ). Operational notes: the node needed ~8.5 min after launch before `/chainstate`/`/wallet` responded (peers connect much sooner — wait for chainstate, not peers), and batch purchase → usable took ~70s, matching the July observation.

Also done 2026-07-19, same node/batch: **retrievability** — `GET /stewardship/{root}` returned `isRetrievable: true` (push-sync out of the light node works); and the **adapter smoke against the real node** — `EagerOntoDAG` over `BeeBytesStore` roundtrip (commit → rehydrate in a fresh instance → query → idempotent re-commit), with two independent runs producing the identical root on real BMT refs. That run also surfaced a real API quirk, since fixed: `get_descendants`/`get_ancestors` traversed the caller's `Item` object rather than re-resolving by name, so querying a *rehydrated* DAG with fresh `Item("x")` objects silently returned the empty set. Both now resolve `self.nodes[node.name]` first (regression tests: `TestQueriesWithFreshItems` in `test_invariants.py`, `test_query_after_rehydrate_with_fresh_items` in `test_eager.py`).

4. **Real node, 2026-07-21 — the `odag` CLI Swarm backend end-to-end.** Validated the `swarm:NAME` CLI backend (not just the adapter) against Swarm Desktop's bee v2.8.1 light node on Gnosis mainnet with a fresh purchased batch (depth 17, immutable, amount 2.4e9 → TTL ~2.06 days, ≈0.03 xBZZ; purchase → usable ~90s / 12 polls). All via the installed `od…`→`odag` command over `BeeBytesStore`+`FilePointer`: (a) build a 5-node DAG with `odag put` (each a commit, ~2.5s for all five), query hydrates from Swarm correctly; (b) **clean-environment rehydration** — a fresh `$ONTODAG_HOME` seeded with *only* the root ref in `pets.root` (no other local state) queried correctly, proving the records live on Swarm, retrievable by ref; (c) **canonical root** — rebuilding the same graph under a different store name *and* a different insertion order produced the byte-identical root `21728cd9…` (S2 history-independence, on real BMT refs); (d) `GET /stewardship/{root}` → `isRetrievable: true`; (e) idempotent commit (re-`put` of an existing edge left the root unchanged) and persisted removal (`remove` changed the root and dropped the node from subsequent queries). Confirms the CLI's lazy `requests`/BeeBytesStore path and the `set store swarm:…` config flow work against a real node. Now captured permanently as the `BEE_API`-gated **`tests/test_swarm_bee.py`** (skips unless `BEE_API` *and* `BEE_BATCH` are set; mirrors `test_recordstore_bee.py`), so this run is reproducible rather than one-off.

Still open at the network level: postage expiry behavior and GC/pinning.

### `LazyOntoDAG` on-demand reader (`src/ontodag/lazy.py`) — DONE (2026-07-25)

Read-only `OntoDAG` subclass that fetches records *as a query walks them*, so querying a published store costs the query rather than the store. Works because the §3 record schema carries `up`, `down` and `count` per node — exactly the planner's inputs. Nodes exist as **stubs** (name only, registered in `self.nodes` so `dag.py`'s `self.nodes.get(x.name) is x` identity checks hold) and are **expanded** (record fetched, count/meta set, children and parents added as stubs) on first traversal; `self.nodes` is a `_LazyNodes` dict whose `get` loads-and-expands, because the planner reads `descendant_count` off resolved terms and an unexpanded stub reports 0 (silently disabling cone ordering and term-dropping — correct results, no laziness). The three traversals the query path uses (`get_descendants`, `_has_ancestors`, `get_ancestors`) are overridden to expand as they walk; the inherited ones would walk a half-built graph. Cones are memoized by name (immutable snapshot, so no invalidation), bounded by `max_cached_cones`. `store.get` calls are counted in `.fetches`.

**Read-only by construction** (`put`/`remove`/`merge`/`add_edge`/`add_node`/`commit` raise `TypeError`): whole-graph invariants and `commit()`'s diff against a complete `_synced` set are undefined for a fragment. `load_all()` materializes everything when an inherited whole-graph operation (`topological_sort`, `intersection_dag`, visualization) is needed. Duck-typed like the adapter — imports nothing from `recordstore` (new B1 case in `test_boundaries.py`), exposed as `ontodag.LazyOntoDAG` via the lazy `__getattr__`.

Measured cost (3,221 records: 20 top / 200 mid / 3,000 leaves, two parents each): specific term 42 fetches, two mid terms (empty result) 82, broad+specific 81, two broad terms 1,071. The last one is the open case → roadmap item 1 (cone summaries).

Tests: `tests/test_lazy.py` (11 tests) — every 1/2/3-term query on the vehicles fixture and 200 random queries on a 40-node random DAG against an eager `EagerOntoDAG` oracle, plus **fetch budgets** (a query near the bottom of a 237-record chain reads <20 records; repeat queries add zero fetches; cache disabled/bounded), unknown terms, `Item`-vs-string arguments, refused mutations, and `load_all()`.

### `EagerOntoDAG` adapter (`src/ontodag/eager.py`) — DONE (July 2026)

An `OntoDAG` subclass persisted through a `RecordStore`, per `SWARM_DESIGN.md` §3/§6: one record per node keyed by name (`up`/`down` sorted, `count`, `payload`, `meta`); full hydration into memory on construction, batched through `RecordStore.items()` when the store offers it and falling back to `keys()`+`get` when it does not (`_all_records`, 2026-07-25); all mutation semantics inherited from `OntoDAG`; `commit()` diffs against the last-synced records and stages only changed nodes. The store is duck-typed — the module imports nothing from `recordstore` (B2), and `ontodag.EagerOntoDAG` is exposed via the lazy `__getattr__` so `import ontodag` stays clean (B1). `put` accepts optional `payload`/`meta` (nodes are undifferentiated `Item`s — there is deliberately no class/instance distinction).

Tests: `tests/test_eager.py` (19 tests against `MemoryBytesStore`): roundtrip + rehydrated queries, history/put-order-independent canonical roots, idempotent commit, incremental staging, invariants after rehydration, merge convergence to identical roots from either side (the §5 CRDT precondition in persisted form), extras roundtrip, persisted removal, and batched-vs-serial hydration (`TestBatchedHydration`: `items()` used when present with zero per-node `get`s, correct fallback when absent, and both paths producing identical edges/counts/`_synced`).

### What does not exist yet

- **`SwarmFeedPointer` adoption.** The pointer itself is DONE upstream (v0.4.0/0.4.1, `recordstore[feeds]` extra, `swarm-bee` signing — the signing decision is no longer blocking). Remaining OntoDAG-side work: use it as the mutable "latest ontology root" for a published `EagerOntoDAG`, plus a `BEE_API`-gated integration test.
- **Multi-writer sync for `EagerOntoDAG`** (`SWARM_DESIGN.md` §5 — updated 2026-07-20). The substrate now exists upstream: `RecordStore.merge` (three-way, O(divergence)), `commit(reconcile=True, resolver=...)`, and feed `compare_and_set`. OntoDAG's remaining job is the merge *rule*: a per-key record resolver alone cannot uphold the graph invariants (transitive reduction and counts are properties of the whole graph, not one record), so divergent same-node edits need a graph-level renormalization pass — hydrate both roots, `OntoDAG.merge` (the I7 semantics), recompute, recommit. The GSOC channel is now an *optional real-time op feed on top of* this state-based reconcile, not the prerequisite mechanism.
- A committed Bee-backed `EagerOntoDAG` integration test (an ad-hoc roundtrip passed against `bee dev` 2.7.1 in July 2026, but only as a one-off script; follow the pattern of `test_recordstore_bee.py` — now in the recordstore repo — if making it permanent, same `BEE_API` gate and the same dev-mode caveat above).
- Network-level behavior still unvalidated: postage expiry and GC/pinning (real-node runs on 2026-07-11 and 2026-07-19 covered upload, retrievability, and the adapter smoke — see "Bee integration status").
- Leaf-packing / B-tree-style chunk layout (`SWARM_DESIGN.md` §4) — do not implement pre-emptively; it needs real usage data first.
- Node provenance (`asserted`/`derived` origin, `derived_from`, `endorsed`) and the mdl-fca learned-DAG integration / retrieval-aware MDL direction (`SWARM_DESIGN.md` §8) — roadmap only, no schema field or code yet; it's the flag that will later drive eviction (§6) and shared-vs-personal sync (§5).
- The semantic-code cone index (`docs/SEMANTIC_CODES.md`, referenced from `SWARM_DESIGN.md` §8) — ancestor-set bitvector codes + per-category cone bitmaps, making `get()` a bitwise AND and enabling an index-only query path over Swarm without full hydration. **Design note only, explicitly gated** (see its §8: hot `get()` workload, RAM-exceeding graph, or thin-client queries); names remain the identity — codes are a derived, regenerable index like `descendant_count`. Its §9 records the declared goal (2026-07-20): a **workload-optimal materialization** between the bare asserted DAG and the full cone-bitmap lattice — materialized derived meets selected by input + retrieval statistics (view-selection / retrieval-aware-MDL / adaptive-indexing framing); the materialization layer is derived, local, per-writer, and never merged — only the asserted DAG syncs. Historical companion notes: `docs/PHILOSOPHICAL_LANGUAGES.md`.

## Previous tasks — DONE (July 2026)

1. **`dag.py` invariant fixes** — all 12 tests in `tests/test_invariants.py` pass; one focused commit per invariant (I1, I2+I3, I4, I6), plus item 5 (reverse adjacency + batched counts). Remaining `dag.py` work: item 6 under "Known bugs".
2. **`EagerOntoDAG` adapter** — see above.

## Current task: none assigned

Done 2026-07-25 (were items 1–2 of this list): the recordstore requirement is `>=0.11` with 0.11.0 installed and `docs/recordstore-interface.md` re-synced against it; `EagerOntoDAG._hydrate` now batches through `RecordStore.items()`.

The broader roadmap (delivered / queued / parked / research horizon, for a general
audience) is `docs/ROADMAP.md`; this list is the working queue.

Next candidates, in order (updated 2026-07-25 — see "What does not exist yet" for details):
1. **Published cone summaries** — the remaining half of `docs/DATABASE_DIRECTION.md` "Pure now" item 1. `LazyOntoDAG` (below) still walks a cone when the narrowest query term is broad (measured: 1,071 fetches for a two-broad-term query on a 3,221-record store, vs 42 for a specific one). Per-category succinct bitmaps stored as ordinary content-addressed blobs, derived deterministically so canonical roots are unaffected; this is step (1) of `SEMANTIC_CODES.md` §8 arriving via a measured need. Keep them *derived*: regenerable, never merged, never part of the record schema.
2. **Adopt `SwarmFeedPointer`** as the published-root pointer (also for the CLI's `swarm:NAME` backend, replacing the local `FilePointer`) plus a `BEE_API`-gated adapter test — no longer blocked on a signing decision (made upstream: `swarm-bee` under `recordstore[feeds]`).
3. **Multi-writer merge rule** over upstream `merge`/`commit(reconcile=True)` (§5) — the OntoDAG-semantic resolver + graph-level renormalization; GSOC is now optional on top.

Optional, pull-forward-anytime (agreed 2026-07-20): **in-memory cone bitmaps behind `get()`** — step (1) of `docs/SEMANTIC_CODES.md` §8's sequencing, exempted from that note's parking because it is bounded, in-memory-only, dependency-free (Python ints), schema-invisible, and oracle-tested by I5 (`popcount == descendant_count`). Do it if/when queries are measurably hot (web UI); it neither advances nor blocks items 1–3. The **`get()` query planner** — **DONE (2026-07-21), including the adaptive walk-vs-probe step**: `OntoDAG.get` resolves/dedups terms by name, drops query terms that are ancestors of other terms (upward `_has_ancestors` walk from the smaller-count term, so planning scales with the query, never the graph; `descendant_count` as the cheap necessary condition), orders cones smallest-count-first, then executes adaptively — before each remaining term it picks walk (traverse the cone, intersect) or probe (upward walk per surviving candidate settling all remaining terms at once) from the now-known running-result size, with early exit on empty. All steps are result-preserving; `_PROBE_COST_ESTIMATE` only steers operator choice (time, never correctness). Tests: `tests/testdag.py::TestQueryPlanner` — brute-force oracle over all 1/2/3-term fixture queries, forced-probe/forced-walk modes, a 60-node seeded-random DAG under all modes, and the meet-substitution guard (a node named "AB" under A and B is NOT the meet of A and B — `put(X, [A, B])` creates a *sibling* of AB — so do not "optimize" `get` through such nodes; see `SEMANTIC_CODES.md` §10).

## Working across sessions

This is a multi-session project. At the start of each session:
1. Run the full test suite (`testdag.py`, `testitem.py`, `test_invariants.py`, `test_boundaries.py`, `test_eager.py`, `test_cli.py` — the first two must be named explicitly, see "Running tests"; the recordstore tests live in the recordstore repo since its `v0.1.1`) to confirm the starting state matches what this file claims.
2. Check which of the two current-task sections above is still open, and update this file's "Definition of done" / "What does not exist yet" sections as work completes — this file should always reflect actual repo state, not a stale plan.
3. Prefer small, focused commits over large multi-concern ones; each should be reviewable against one invariant or one design-doc section.
