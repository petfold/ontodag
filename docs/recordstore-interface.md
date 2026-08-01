# recordstore — interface reference

`recordstore` lives in its own repo, [github.com/petfold/recordstore](https://github.com/petfold/recordstore),
extracted from this repo in July 2026 with history preserved. OntoDAG depends on it
from PyPI in `pyproject.toml` (`recordstore>=0.13.1`, both in the base dependencies
and in the `swarm` extra).

**This is a manually-synced reference doc**, not generated and not a submodule: if the
required version changes, re-check this summary against the tagged source. Last synced
against **0.11.0** (2026-07-25) — two releases behind the current floor, so treat the
details below as accurate for what OntoDAG actually calls, but re-check against the
0.13.1 tag before relying on anything not exercised by our tests.

## What OntoDAG uses it for

`ontodag.EagerOntoDAG` persists one JSON record per DAG node through a `RecordStore`
(duck-typed — the adapter imports nothing from `recordstore`; the concrete store is
injected by the caller). The recordstore test suite lives in the recordstore repo
(since its `v0.1.1`); this repo keeps the consumer-side checks
(`tests/test_boundaries.py` B2, `tests/test_eager.py`).

## `RecordStore`

A staged, versioned key→record store over a content-addressed bytes store. Keys are
non-empty strings; values are any JSON-encodable object. Reads are read-your-writes;
returned records are deep copies (mutating them never mutates the store).

- `RecordStore(bytes_store, root=None, pointer=None)` — open a store over a `BytesStore`,
  optionally at an existing root or following a `Pointer`.
- `put(key, value)` / `get(key)` / `delete(key)` / `contains(key)` — staged operations;
  `get`/`delete` raise `KeyError` for missing keys.
- `keys(prefix="")` — sorted keys under a prefix, staged overlay included, yielded
  lazily (no result-set-sized buffer).
- `items(prefix="")` — sorted `(key, value)` pairs, staged overlay included, streamed in
  windows: value blobs are fetched a window at a time, so over a network store with
  `get_many` the reads parallelise while memory stays bounded to one window. This is the
  fast path for hydrating a whole store, and what `EagerOntoDAG._hydrate` uses.
- `commit(*, reconcile=False, resolver=None, retries=5) → root` — flush staged changes,
  return the new root reference, and update the pointer (if any). The pointer moves only
  after every blob write succeeds, so a reader sees all of a commit or none of it. Value
  blobs and trie levels are written in concurrent batches (roots stay byte-identical to
  serial commits). With `reconcile=True`, a pointer that moved past this commit's base
  root is three-way-merged and the commit retried until it lands, so concurrent writers
  converge.
- `merge(bytes_store, base, ours, theirs, resolver=None) → root` (static) — canonical
  three-way merge of two roots, O(divergence) via structural trie diff. Conflicts raise
  `MergeConflict` unless `resolver(key, base, ours, theirs)` settles them (sentinels
  `ABSENT`/`DELETE`); commutative when the resolver is symmetric. See
  `docs/SWARM_DESIGN.md` §5 for how OntoDAG plans to use this — a per-key resolver alone
  cannot uphold the graph invariants, so a graph-level renormalization pass is needed.
- `RecordStore.at(root, bytes_store)` — read-only snapshot of any committed root
  (`put`/`delete`/`commit` raise `TypeError`).
- `.root` — root of the last committed state.

## Canonicity guarantee

Storage is a persistent, canonically-encoded compacted radix trie: **equal content
produces equal root references**, regardless of the insertion/deletion history that
produced it. This is what makes committed states content-addressable, diffable, and
mergeable — and it is why `EagerOntoDAG` gets history-independent canonical roots
(verified by `tests/test_eager.py` here and the fuzz suite
`tests/test_recordstore_fuzz.py` in the recordstore repo).

`canonical_bytes(value)` — the canonical JSON encoding (sorted keys, minimal
separators, UTF-8) used for records; exported for anything that needs byte-identical
encodings.

## `BytesStore` backends

Protocol: `put(data: bytes) → ref`, `get(ref) → bytes` (raises `KeyError` if missing).

Optional bulk methods `get_many(refs)` / `put_many(datas)` are used by `items()` and
`commit()` when the backend provides them; both backends below do.

- `MemoryBytesStore()` — in-memory dict; the test double.
- `BeeBytesStore(api_url, postage_batch_id="auto", deferred_upload=True,
  max_concurrent_reads=16)` — a real Bee node
  over `POST/GET /bytes` (Bee's blob endpoint, not the raw `/chunks/{address}` single-chunk
  primitive — the name reflects that). Imports `requests` lazily (install extra:
  `recordstore[bee]`). Writes need a usable postage batch; against a real node always
  supply a purchased batch id (see CLAUDE.md "Bee integration status").

## `Pointer` backends

Protocol: `get() → ref | None`, `set(ref)` — a mutable name for the latest root.

- `MemoryPointer(root=None)` — in-memory; `compare_and_set(expected, new)` is an atomic
  in-process CAS.
- `FilePointer(path)` — atomic file-based pointer.
- `SwarmFeedPointer(api_url, topic, *, signer=None, owner=None, postage_batch_id=None,
  feed_ttl=15.0, ...)` — a real `Pointer` backed by an owner-signed Swarm feed. Signing
  via the `swarm-bee` package, behind a `recordstore[feeds]` extra, imported lazily (the
  core stays stdlib-only). Handles Bee's flaky feed lookups with a read-your-writes
  cache, a monotonic write-index floor, direct SOC probing for cold reads, and the
  `?after=N` index hint. `compare_and_set(expected, new)` enables cross-process
  reconcile — best-effort, not atomic (Swarm feeds have no index-claim primitive).
  **Adopted by OntoDAG 2026-07-31:** with a signer configured (`$BEE_SIGNER` /
  `bee_signer`, settable via `odag set`) the `odag` Swarm backend routes through
  `swarm_store()`, so the mutable root lives in a signed feed; the local
  `FilePointer` remains the keyless, non-publishable fallback.

## Version history relevant to OntoDAG

All releases since `v0.3.0` have been additive — no breaking API changes — which is why
OntoDAG's dependency is a floor (`>=0.13.1` in `pyproject.toml`) rather than an exact
pin.

- **v0.4.0/0.4.1** — the real `SwarmFeedPointer` (above), replacing a documented stub.
- **v0.5.0–v0.7.1** — concurrent bulk I/O: `items()`, `get_many`/`put_many`, lazily
  streamed `keys()`/`items()`, pooled HTTP connections in `BeeBytesStore`, and batched
  blob/trie writes in `commit()`.
- **v0.8.0–v0.10.0** — multi-writer primitives: three-way `merge`, `commit(reconcile=True)`,
  `compare_and_set` on both pointer backends.
- **v0.11.0–v0.14.0** — the 0.13/0.14 line adds stamp-health checks for `"auto"`
  batch selection (see its CHANGELOG); OntoDAG's floor is `>=0.13.1`.
- **v0.15.0** — public **`RecordStore.diff(other_root)`**: `(key, mine, theirs)` per
  differing key, `ABSENT` for a missing side, cost proportional to the difference
  (the structural trie diff `merge` used internally, now first-class). Requested by
  `MERKLE_NOTES.md`; OntoDAG does not consume it yet, so the floor is unchanged.
  The version this document was last synced against.

Earlier renames worth knowing when reading old notes or commits: `BeeChunkStore` →
`BeeBytesStore` (v0.2.0), then `ChunkStore` → `BytesStore`, `MemoryChunkStore` →
`MemoryBytesStore`, and the `RecordStore` parameter `chunks` → `bytes_store` (v0.3.0).
