# recordstore — interface reference

`recordstore` lives in its own repo, [github.com/petfold/recordstore](https://github.com/petfold/recordstore),
extracted from this repo in July 2026 with history preserved. OntoDAG pins it in
`pyproject.toml` (`recordstore @ git+https://github.com/petfold/recordstore.git@v0.3.0`).

**This is a manually-synced reference doc**, not generated and not a submodule: if the
pinned version changes, re-check this summary against the tagged source.

## What OntoDAG uses it for

`ontodag.SwarmOntoDAG` persists one JSON record per DAG node through a `RecordStore`
(duck-typed — the adapter imports nothing from `recordstore`; the concrete store is
injected by the caller). The recordstore test suite lives in the recordstore repo
(since its `v0.1.1`); this repo keeps the consumer-side checks
(`tests/test_boundaries.py` B2, `tests/test_swarm_adapter.py`).

## `RecordStore`

A staged, versioned key→record store over a content-addressed bytes store. Keys are
non-empty strings; values are any JSON-encodable object. Reads are read-your-writes;
returned records are deep copies (mutating them never mutates the store).

- `RecordStore(bytes_store, root=None, pointer=None)` — open a store over a `BytesStore`,
  optionally at an existing root or following a `Pointer`.
- `put(key, value)` / `get(key)` / `delete(key)` / `contains(key)` — staged operations;
  `get`/`delete` raise `KeyError` for missing keys.
- `keys(prefix="")` — sorted iteration over keys under a prefix, staged overlay included.
- `commit() → root` — flush staged changes, return the new root reference, and update
  the pointer (if any). The pointer moves only after every blob write succeeds, so a
  reader sees all of a commit or none of it.
- `RecordStore.at(root, bytes_store)` — read-only snapshot of any committed root
  (`put`/`delete`/`commit` raise `TypeError`).
- `.root` — root of the last committed state.

## Canonicity guarantee

Storage is a persistent, canonically-encoded compacted radix trie: **equal content
produces equal root references**, regardless of the insertion/deletion history that
produced it. This is what makes committed states content-addressable, diffable, and
mergeable — and it is why `SwarmOntoDAG` gets history-independent canonical roots
(verified by `tests/test_swarm_adapter.py` here and the fuzz suite
`tests/test_recordstore_fuzz.py` in the recordstore repo).

`canonical_bytes(value)` — the canonical JSON encoding (sorted keys, minimal
separators, UTF-8) used for records; exported for anything that needs byte-identical
encodings.

## `BytesStore` backends

Protocol: `put(data: bytes) → ref`, `get(ref) → bytes` (raises `KeyError` if missing).

- `MemoryBytesStore()` — in-memory dict; the test double.
- `BeeBytesStore(api_url, postage_batch_id, deferred_upload=True)` — a real Bee node
  over `POST/GET /bytes` (Bee's blob endpoint, not the raw `/chunks/{address}` single-chunk
  primitive — the name reflects that). Imports `requests` lazily (install extra:
  `recordstore[bee]`). Writes need a usable postage batch; against a real node always
  supply a purchased batch id (see CLAUDE.md "Bee integration status").

## `Pointer` backends

Protocol: `get() → ref | None`, `set(ref)` — a mutable name for the latest root.

- `MemoryPointer(root=None)` — in-memory.
- `FilePointer(path)` — atomic file-based pointer.
- `SwarmFeedPointer` — documented stub *at the pinned v0.3.0*; a real implementation
  landed upstream in v0.4.0 (see below).

## Upstream since the pin (v0.4.0 – v0.10.0, all released 2026-07-20)

Not yet available at the pinned v0.3.0 — bump the pin to use these (all additive, no
breaking changes since v0.3.0; the pin bump is on the roadmap in `CLAUDE.md`). Re-sync
this whole document when the pin moves.

- **`SwarmFeedPointer(bee_api, topic, signer=..., owner=...)`** (v0.4.0/0.4.1) — a real
  `Pointer` backed by an owner-signed Swarm feed. Signing via the `swarm-bee` package,
  behind a `recordstore[feeds]` extra, imported lazily (core stays stdlib-only). Handles
  Bee's flaky feed lookups with a read-your-writes cache, a monotonic write-index floor,
  direct SOC probing for cold reads, and the `?after=N` index hint.
  `compare_and_set(expected, new)` (v0.10.0) enables cross-process reconcile —
  best-effort, not atomic (Swarm feeds have no index-claim primitive).
- **Concurrent bulk I/O** (v0.5.0–v0.7.1): `RecordStore.items(prefix="")` — sorted
  `(key, value)` pairs with value blobs fetched concurrently in bounded windows (the
  fast way to hydrate a whole store); optional `BytesStore.get_many(refs)` /
  `put_many(datas)`; `keys()`/`items()` stream lazily in sorted order; `BeeBytesStore`
  pools HTTP connections; `commit()` writes value blobs and trie levels in concurrent
  batches (roots byte-identical to serial commits).
- **Multi-writer primitives** (v0.8.0–v0.10.0):
  `RecordStore.merge(bytes_store, base, ours, theirs, resolver=None)` — canonical
  three-way merge of two roots, O(divergence) via structural trie diff; conflicts raise
  `MergeConflict` unless a `resolver(key, base, ours, theirs)` settles them (sentinels
  `ABSENT`/`DELETE`); commutative when the resolver is symmetric.
  `commit(reconcile=True, resolver=None, retries=5)` — if the pointer moved past this
  commit's base root, merge and retry until it lands, so concurrent writers converge.
  `MemoryPointer.compare_and_set` — atomic in-process CAS.
  See `docs/SWARM_DESIGN.md` §5 (2026-07-20 update) for how OntoDAG plans to use these.
