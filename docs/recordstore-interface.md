# recordstore — interface reference

`recordstore` lives in its own repo, [github.com/petfold/recordstore](https://github.com/petfold/recordstore),
extracted from this repo in July 2026 with history preserved. OntoDAG pins it in
`pyproject.toml` (`recordstore @ git+https://github.com/petfold/recordstore.git@v0.1.0`).

**This is a manually-synced reference doc**, not generated and not a submodule: if the
pinned version changes, re-check this summary against the tagged source.

## What OntoDAG uses it for

`ontodag.SwarmOntoDAG` persists one JSON record per DAG node through a `RecordStore`
(duck-typed — the adapter imports nothing from `recordstore`; the concrete store is
injected by the caller). The recordstore test suite also still lives here
(`tests/test_recordstore*.py`).

## `RecordStore`

A staged, versioned key→record store over a content-addressed chunk store. Keys are
non-empty strings; values are any JSON-encodable object. Reads are read-your-writes;
returned records are deep copies (mutating them never mutates the store).

- `RecordStore(chunks, root=None, pointer=None)` — open a store over a `ChunkStore`,
  optionally at an existing root or following a `Pointer`.
- `put(key, value)` / `get(key)` / `delete(key)` / `contains(key)` — staged operations;
  `get`/`delete` raise `KeyError` for missing keys.
- `keys(prefix="")` — sorted iteration over keys under a prefix, staged overlay included.
- `commit() → root` — flush staged changes, return the new root reference, and update
  the pointer (if any). The pointer moves only after every chunk write succeeds, so a
  reader sees all of a commit or none of it.
- `RecordStore.at(root, chunks)` — read-only snapshot of any committed root
  (`put`/`delete`/`commit` raise `TypeError`).
- `.root` — root of the last committed state.

## Canonicity guarantee

Storage is a persistent, canonically-encoded compacted radix trie: **equal content
produces equal root references**, regardless of the insertion/deletion history that
produced it. This is what makes committed states content-addressable, diffable, and
mergeable — and it is why `SwarmOntoDAG` gets history-independent canonical roots
(verified by `tests/test_swarm_adapter.py` and the fuzz suite
`tests/test_recordstore_fuzz.py`).

`canonical_bytes(value)` — the canonical JSON encoding (sorted keys, minimal
separators, UTF-8) used for records; exported for anything that needs byte-identical
encodings.

## `ChunkStore` backends

Protocol: `put(data: bytes) → ref`, `get(ref) → bytes` (raises `KeyError` if missing).

- `MemoryChunkStore()` — in-memory dict; the test double.
- `BeeChunkStore(api_url, postage_batch_id, deferred_upload=True)` — a real Bee node
  over `POST/GET /bytes`. Imports `requests` lazily (install extra: `recordstore[bee]`).
  Writes need a usable postage batch; against a real node always supply a purchased
  batch id (see CLAUDE.md "Bee integration status").

## `Pointer` backends

Protocol: `get() → ref | None`, `set(ref)` — a mutable name for the latest root.

- `MemoryPointer(root=None)` — in-memory.
- `FilePointer(path)` — atomic file-based pointer.
- `SwarmFeedPointer` — documented stub; real Swarm feed writes need client-side SOC
  signing (secp256k1), deliberately deferred (see `docs/SWARM_DESIGN.md` §5).
