# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

OntoDAG is a DAG-based associative memory and category manager. Items are placed into the DAG under supercategories; querying with a set of categories returns the intersection of their descendants. The root node `*` is the implicit ancestor of all top-level items.

Conceptually OntoDAG is a **subsumption-only ontology**: a multi-parent category lattice kept in transitively reduced form, with one query primitive — the intersection of descendant cones ("everything below *all* of these categories"). It sits deliberately between flat tags/folders (no multi-parent subsumption) and full OWL/description-logic stacks (properties, axioms, reasoning). Its distinguishing property is that the **transitive reduction of a DAG is unique**, which gives the structure a canonical form. That canonical form is what later makes it content-addressable, diffable, and mergeable — see "Planned Swarm integration" below. Keeping the invariants exact is therefore not cosmetic: they are the precondition for the persistence and multi-writer story.

## Running tests

Tests use `pytest` from the repo root. The `graphviz` Python package is not installed in the local environment, so tests that call `OntoDAGVisualizer.visualize()` will fail:

```bash
python3 -m pytest tests/testdag.py tests/testitem.py -v   # core DAG logic
python3 -m pytest tests/test_invariants.py -v              # structural invariant tests (several intentionally fail — see below)
```

The invariant tests in `tests/test_invariants.py` are deliberately written to fail against the current implementation — each failing test is a bug reproduction. Do not treat these failures as regressions. The goal of the current work is to make all of them pass without breaking the existing suite. The helpers in that file (`reach`, `edge_set`) compute reachability independently of the traversal code under test, so they remain a valid oracle even while `dag.py` is being changed.

## Architecture

There are **two separate implementations**; `dag.py` is the active one:

### `dag.py` — active implementation
- `Item`: graph node with `name`, `neighbors` (set of child `Item`s), `descendant_count`
- `DAG`: base directed graph — `add_node`, `add_edge`, `remove_edge`, `get_descendants`, `get_ancestors`, `topological_sort`; descendant counts are recalculated from scratch on each structural change
- `OntoDAG(DAG)`: extends DAG with `put(item, super_categories)`, `get(super_categories)`, `remove(item)` and a root node `*`; `put` accepts an optional `optimized=True` flag that prunes redundant supercategory links before inserting
- `OntoDAGVisualizer`: Graphviz-backed renderer; lazy-imports `graphviz` so it doesn't break non-visualization code

### `ontodag.py` — older, standalone implementation
- String-based API: `put(name, ["supercat1", ...])`, `get({"cat1", "cat2"})`, `remove(name)`
- Items carry a `counter` (descendant count) and a `subcategories` set
- `VisualizerOntoDAG` subclass adds `visualize()`
- Still used by `tests/testontodag.py` and `tests/testitem_ontodag.py`; these tests fail without `graphviz` because `ontodag.py` imports it at module level

### Supporting modules
- `owl.py`: OWL import/export via `owlready2`; `OWLOntology.import_dag()` and `export_dag()` translate between OWL class hierarchies and a `dag.py` `OntoDAG`
- `loader.py`: CSV-based loading into the `ontodag.py` API
- `web/app.py`: Flask REST API wrapping the `dag.py` `OntoDAG`; runs with `python3 web/app.py`

## Web app

```bash
cd web && python3 app.py   # starts Flask dev server on localhost:5000
```

REST endpoints: `POST /dag` (reset), `GET/POST/DELETE /dag/node`, `GET /dag/query?cat=A,B`, `GET /dag/image`, `POST /dag/import`, `GET /dag/export`.

## Key invariants (from `tests/test_invariants.py`)

The invariant test file documents seven properties the data structure should uphold:
- **I1 Acyclicity** — `add_edge` must reject cycles
- **I2 Transitive reduction** — no redundant edges (if A→B→C exists, A→C must not)
- **I3 Order independence** — `put(X, [A, B])` and `put(X, [B, A])` must produce identical graphs
- **I4 No aliasing** — derived DAGs (intersection, copy) must not share `Item` objects with sources
- **I5 Counter consistency** — `descendant_count` must always equal the true reachable count
- **I6 Iterative traversal** — `get_descendants`/`get_ancestors` must not use recursion (Python recursion limit)
- **I7 Merge algebra** — `merge` must be commutative and idempotent (CRDT property)

## Known bugs and recommended fix order

Line numbers refer to `src/ontodag/dag.py` and may drift as edits land; locate by method name if so. Fix in this order — earlier fixes are preconditions for later tests behaving sensibly.

1. **No cycle check in `add_edge` (DAG.add_edge, ~line 35).** Edge insertion never checks reachability, so `put` can create cycles (e.g. `put(A, [])`, `put(B, [A])`, then `put(A, [B])`). Fix: in `add_edge(u, v)`, reject (raise `ValueError`) if `u` is reachable from `v`. Catches I1.

2. **Transitive reduction is incomplete and order-dependent (`OntoDAG._remove_unneeded_edges` ~line 198, `OntoDAG.add_edge` ~line 154).** `_remove_unneeded_edges` only prunes edges from ancestors of the new parent to the child; it never checks whether the *new* edge `u→v` is itself redundant. With `root→A→B→X`, `put(X, [A])` wrongly adds `A→X`; and `put(X, [B, A])` vs `put(X, [A, B])` give different graphs. Fix: before adding `u→v`, skip if `v` is already reachable from `u`; then prune ancestor edges as now. Catches I2, I3.

3. **`intersection_dag` aliases live nodes (`DAG.intersection_dag` ~line 114).** It inserts the *original* `Item` objects from both source DAGs into the result (unlike `copy_subdag`, which maps to fresh copies), so mutating the intersection mutates the sources. Also uses `is` for name comparison (`node.name is intersecting_dag.root.name`) which only works via CPython string interning — use `==`. Fix: build fresh `Item`s with a name→new-Item mapping, mirroring `copy_subdag`. Catches I4.

4. **Recursive traversals overflow on deep graphs (`DAG.get_descendants` ~line 81, `DAG.get_ancestors` ~line 93).** Both recurse once per level and raise `RecursionError` beyond ~1000 levels. Convert to explicit-stack/queue iteration. Catches I6.

5. **Quadratic structure maintenance (root cause: no reverse adjacency).** `Item` stores children but not parents, so `get_ancestors` and `_get_affected_nodes` scan every node in the graph, and `_update_descendant_counts` (~line 61) fully recomputes descendant sets for the changed node and all ancestors on every edge change. Add a `parents` set maintained symmetrically with `neighbors`. This is also the in-memory form of the `up`-list the Swarm record needs (see below), so doing it now aligns both models. For counts: "number of distinct descendants" is not decomposable over a DAG (cones overlap), so prefer marking counts dirty and recomputing lazily via a memoized topological pass rather than per-edge full recomputation. Improves I5 performance; I5 correctness is already testable.

### Secondary cleanups (not blocking the invariant suite)
- **`__init__.py` forces an `owlready2` dependency.** `src/ontodag/__init__.py` imports `owl.py` unconditionally, so the core DAG cannot be used without `owlready2` installed. Make the `owl` import lazy/optional.
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

**Full design rationale is in `docs/SWARM_DESIGN.md` — read it before touching `src/recordstore/` or starting the OntoDAG-Swarm adapter.** It covers: why a generic `recordstore` layer exists at all rather than calling Swarm directly (§2), the node record schema for the eventual adapter (§3), why storage is one-record-per-chunk for now and when that should change (§4), the planned multi-writer/CRDT merge mechanism (§5), the performance model and the four caching layers involved (§6), what's tested vs. not (§7), and the recommended sequencing of remaining work (§8). This file (`CLAUDE.md`) has the day-to-day task list; `SWARM_DESIGN.md` has the "why."

### What already exists (`src/recordstore/`)

A versioned key→record store over a content-addressed chunk store — the generic substrate `OntoDAG`-on-Swarm will sit on. Implemented and tested:
- `RecordStore`: staged put/get/delete, `commit() → root`, `RecordStore.at(root)` read-only snapshots, sorted prefix iteration (`keys(prefix)`).
- A persistent, canonically-encoded compacted radix trie (own implementation, not mantaray — see `SWARM_DESIGN.md` §2 for why compatibility with mantaray was deferred rather than required).
- `ChunkStore` backends: `MemoryChunkStore` (test double) and `BeeChunkStore` (real Bee node over `/bytes`).
- `Pointer` backends: `MemoryPointer`, `FilePointer`. `SwarmFeedPointer` is a documented stub — real feed writes need client-side SOC signing (secp256k1), deliberately deferred; see `SWARM_DESIGN.md` §5.

Tests: `tests/test_recordstore.py` (11 unit tests — canonical roots, snapshot isolation, structural sharing, no-aliasing), `tests/test_recordstore_fuzz.py` (model-based fuzz test against a dict oracle, 12 seeded runs × 400 ops, checks the canonical-root property under arbitrary put/delete histories), `tests/test_recordstore_bee.py` (integration test against a live Bee node — **skips automatically unless `BEE_API` is set; run it once before extending `BeeChunkStore` further**):

```bash
python3 -m pytest tests/test_recordstore.py tests/test_recordstore_fuzz.py -v   # no external deps

# integration test against a real node (do this once before further BeeChunkStore work):
bee dev --api-addr=127.0.0.1:1633
BEE_API=http://127.0.0.1:1633 python3 -m pytest tests/test_recordstore_bee.py -v
```

### What does not exist yet

- `SwarmOntoDAG` adapter (implements `dag.py`'s `put`/`get`/`remove`/`merge` against `RecordStore`, using the schema in `SWARM_DESIGN.md` §3). **Do not start this until the `dag.py` invariant fixes below are merged** — the adapter should inherit correct, canonical semantics rather than freeze today's bugs into a content-addressed encoding.
- The GSOC-based CRDT merge (`SWARM_DESIGN.md` §5).
- The real `SwarmFeedPointer` (needs a signing dependency decision — flag this to the user rather than picking a crypto library unilaterally).
- Leaf-packing / B-tree-style chunk layout (`SWARM_DESIGN.md` §4) — do not implement pre-emptively; it needs real usage data first.

## Definition of done (current task: `dag.py` invariant fixes)

- All tests in `tests/test_invariants.py` pass (12 tests).
- The existing `tests/testdag.py` and `tests/testitem.py` still pass.
- No new hard dependency is introduced for the core DAG (the `owlready2`/`graphviz` imports stay optional/lazy).
- Each fix is a focused commit referencing the invariant (I1–I7) it satisfies.

## Next task after that: the `SwarmOntoDAG` adapter

Once the invariant fixes above are merged: implement `src/ontodag/swarm_adapter.py` (or similar) per `SWARM_DESIGN.md` §3 and §8. It should depend on `src/recordstore` (already built) and the fixed `src/ontodag/dag.py`. Write it test-first against `MemoryChunkStore` (fast, no external dependency); a Bee-backed integration test is a separate, later addition, following the pattern in `tests/test_recordstore_bee.py`.

## Working across sessions

This is a multi-session project. At the start of each session:
1. Run the full test suite (`testdag.py`, `testitem.py`, `test_invariants.py`, `test_recordstore.py`, `test_recordstore_fuzz.py`) to confirm the starting state matches what this file claims.
2. Check which of the two current-task sections above is still open, and update this file's "Definition of done" / "What does not exist yet" sections as work completes — this file should always reflect actual repo state, not a stale plan.
3. Prefer small, focused commits over large multi-concern ones; each should be reviewable against one invariant or one design-doc section.
