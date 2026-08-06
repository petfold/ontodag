# recordstore — interface reference

`recordstore` lives in its own repo, [github.com/petfold/recordstore](https://github.com/petfold/recordstore),
extracted from this repo in July 2026 with history preserved. OntoDAG depends on it
from PyPI in `pyproject.toml` (`recordstore>=0.20.0`, both in the base dependencies and
in the `swarm` extra, which asks for `recordstore[bee,feeds,stamps]`).

> **The authoritative reference now lives upstream.** Since recordstore
> 0.18.2 the repo ships its own
> [`docs/REFERENCE.md`](https://github.com/petfold/recordstore/blob/main/docs/REFERENCE.md)
> (local checkout: `../../recordstore/docs/REFERENCE.md`) — definition-first
> tables of every export, signature, error and extra, **pinned against the
> code by its `tests/test_reference.py`**, so unlike this file it cannot
> drift. For anything current — the local-first surface
> (`local_first_store`, pin/fetch, `squash_history`), `CachedBytesStore`,
> `RecordUnavailable` — go there. swarmfs (pulled in by the `swarm` extra's
> `[stamps]` path, and by `recordstore[local]`) has the same:
> [`docs/REFERENCE.md`](https://github.com/petfold/swarmfs/blob/main/docs/REFERENCE.md).

**This file's remaining role is the consumer-side view**: the subset OntoDAG
actually uses, with floor annotations. It is manually synced and no longer
chases the full upstream API. Last full signature-by-signature sync:
**0.15.0** (2026-08-01); anything requiring more than the 0.14.0-era floor
is marked **(needs ≥ x.y.z)** below.

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
- `commit(*, message=None, reconcile=False, resolver=None, retries=5) → root` — flush staged changes,
  return the new root reference, and update the pointer (if any). The pointer moves only
  after every blob write succeeds, so a reader sees all of a commit or none of it. Value
  blobs and trie levels are written in concurrent batches (roots stay byte-identical to
  serial commits). With `reconcile=True`, a pointer that moved past this commit's base
  root is three-way-merged and the commit retried until it lands, so concurrent writers
  converge.
- `history(limit=None) → [Version]` **(needs ≥ 0.20.0)** — the states this store has been
  in, newest first, as `Version(root, at, message, current)`. `[]` when the pointer keeps
  no timeline. Every entry is a whole state, so `RecordStore.at(v.root, blobs)` reopens any
  of them — which is why undo needs no diff replay.
- `undo()` / `redo() → root|None` **(needs ≥ 0.20.0)** — step the pointer back or forward
  along that line; `None` at either end, and the store is left where it was. A commit made
  after an undo abandons the redo tail. `checkout(root)` jumps to a state the timeline
  holds and refuses any other root; `status()` reports
  `{root, staged, readonly, history, position, undoable, redoable}`.
  `commit(message=…)` labels the state — in the timeline, **never** in the content, so
  equal content still commits to equal roots. This is what `odag history` / `status` /
  `undo` / `redo` / `-m` are made of.
- `merge(bytes_store, base, ours, theirs, resolver=None) → root` (static) — canonical
  three-way merge of two roots, O(divergence) via structural trie diff. Conflicts raise
  `MergeConflict` unless `resolver(key, base, ours, theirs)` settles them (sentinels
  `ABSENT`/`DELETE`); commutative when the resolver is symmetric. See
  `docs/SWARM_DESIGN.md` §5 for how OntoDAG plans to use this — a per-key resolver alone
  cannot uphold the graph invariants, so a graph-level renormalization pass is needed.
- `diff(other_root)` **(needs ≥ 0.15.0)** — yields `(key, mine, theirs)` for every key
  whose value differs between this store's committed root and `other_root`; a side
  lacking the key gets `ABSENT` (a stored value may legitimately be `None`). Cost is
  proportional to the *difference*, not the dataset — the same structural trie diff
  `merge` uses, pruning subtrees whose refs match, so equal roots read zero blobs.
  Compare two arbitrary roots with `RecordStore.at(a, blobs).diff(b)`. Requested by
  `docs/plans/MERKLE_NOTES.md`; **consumed since 2026-08-04** by the delta merge fold —
  `EagerOntoDAG.merge_delta` and `SparseOntoDAG.sync` diff the dag's own lineage
  against the peer's root so folding a peer costs the divergence, never the store.
  Caveat inherited by that path: staged, uncommitted changes belong to no root and to
  no diff (the fold handles its own dirty set separately for exactly this reason).
- `prove(key, addressing=None)` **(needs ≥ 0.16.0)** — a verifiable inclusion-or-absence
  proof for `key` against the *committed* root: a self-describing, JSON-ready dict
  (`{format: "recordstore-trie-proof", version: 1, addressing, root, key, present,
  nodes, value}`) carrying the raw trie-node blobs along the key's one possible path,
  plus the value blob when present. O(depth) small; refuses keys with staged changes
  (proofs are statements about committed roots); self-verified before being returned,
  so an addressing mismatch fails at prove time. `addressing` is auto-detected
  (`sha256`/`swarm`), with the keyword for duck-typed stores. Module-level
  **`verify_proof(proof, root)`** checks a proof with **no store access** — hash-chain
  recomputation over the carried bytes — returning the record or `ABSENT`, raising
  `ProofError` on any mismatch. Absence is provable because the encoding is canonical:
  one root, one possible location per key. This is the substrate for `CONTRACT.md` §7
  Tier 2 (`is_below` certificates compose these proofs), built for exactly that
  purpose 2026-08-01.
- `RecordStore.at(root, bytes_store)` — read-only snapshot of any committed root
  (`put`/`delete`/`commit` raise `TypeError`).
- `.root` — root of the last committed state.
- `.blobs` — the underlying `BytesStore`, so a caller holding one store can open another
  root over the same backend without having kept a separate reference.
  `EagerOntoDAG.merge_published` relies on exactly this:
  `RecordStore.at(other_root, self.store.blobs)`.

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
`commit()` when the backend provides them; all four backends below do.

- `MemoryBytesStore()` — in-memory dict; the test double.
- `DirBytesStore(path, addressing="sha256")` — durable blobs in a local directory, the
  file name being the reference. Fills the gap between the other two: `MemoryBytesStore`
  forgets everything on exit and `BeeBytesStore` needs a node and a batch, while
  `FilePointer` persists only the *root ref*, not the blobs. Atomic and idempotent
  writes; names fan out two hex chars deep so a large store stays listable.
- `FsspecBytesStore(url, addressing="sha256")` — the same contract over any fsspec
  filesystem (local, S3, GCS, Azure, HTTP, SFTP, `memory://`); needs `recordstore[fsspec]`.
  It **refuses `bzz://` explicitly**: fsspec is path-addressed while a Swarm reference is
  produced *by* the write, so pointing it at Swarm would store blobs under `<sha256>`
  paths and discard Swarm's own addressing — use `BeeBytesStore`/`swarm_store` for that.
- Both take `addressing=`: `"sha256"` (default — roots stay portable with
  `MemoryBytesStore`), `"swarm"` (name blobs by their Swarm reference, computed locally
  via `swarmfs.splitter`, making a directory an offline mirror of Swarm's address space;
  needs `recordstore[swarm-addressing]`), or any `bytes -> str` callable.
- `BeeBytesStore(api_url, postage_batch_id="auto", deferred_upload=True,
  max_concurrent_reads=16, min_batch_ttl=AUTO_MIN_BATCH_TTL)` — a real Bee node
  over `POST/GET /bytes` (Bee's blob endpoint, not the raw `/chunks/{address}` single-chunk
  primitive — the name reflects that). Imports `requests` lazily (install extra:
  `recordstore[bee]`). Writes need a usable postage batch; against a real node always
  supply a purchased batch id (see CLAUDE.md "Bee integration status").

### Postage batches: selection, never purchase

`postage_batch_id="auto"` (the default, and what `odag` uses unless `BEE_BATCH` /
`bee_batch` is set) resolves the batch at **construction time**, by asking the node for
its batch list via swarmfs's `StampManager` — so opening a store over Bee is a network
call, and a stopped node fails there rather than at first write. Selection picks the
usable batch with the longest remaining validity and **never buys one**: spending the
node wallet's xBZZ stays a deliberate caller action (swarmfs's `StampManager.plan`/`buy`
is the programmatic route).

- `AUTO_MIN_BATCH_TTL = 86400` — a day of remaining validity is required of an
  auto-selected batch; override per store with `min_batch_ttl=`. Versions before 0.14.0
  inherited swarmfs's 60-second floor, written for one-shot uploads: a batch with a
  minute left would be selected and everything written under it would stop being paid
  for a minute later. Getting this behaviour is part of why the floor is 0.14.0.
- `batch_status(api_url, batch_id, *, buckets=False)` and
  `BeeBytesStore.batch_status(*, buckets=False)` — read-only batch
  health, returning `(StampInfo, BucketStats | None)`; `buckets=True` fetches the node's
  exact per-bucket histogram (~2 MB) instead of the summary. Selection also warns on
  under a week of validity (an expired batch cannot be revived) and on a fullest bucket
  ≥ 80% full on an immutable batch (dilute, or chunks hashing there are refused despite
  free capacity elsewhere).
  *Import note:* only the **method** is reachable from the package root — neither
  `batch_status` nor `AUTO_MIN_BATCH_TTL` appears in `recordstore.__all__`, so the free
  function needs `from recordstore.recordstore import batch_status` (verified
  2026-08-01; an export oversight upstream rather than a deliberate boundary).

**Why the floor is 0.14.0 and the extra names three components.** The `auto` path imports
`swarmfs`, which recordstore declares as its `[stamps]` extra (`swarmfs>=0.4.0`) from
0.14.0 on. OntoDAG's `swarm` extra used to ask for `recordstore[bee,feeds]` only, so a
clean install had no `swarmfs` and the *default* batch setting failed at store-open with
an `ImportError` — invisible on a dev box that has swarmfs from a checkout. Fixed
2026-08-01 by asking for `recordstore[bee,feeds,stamps]>=0.14.0`. The floor had to move
with it: `stamps` does not exist below 0.14.0, and pip only *warns* about an
unknown extra, so naming it against an older floor would have installed nothing and
looked fine.

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

## `swarm_store()` — the whole store on Swarm, in one call

```python
swarm_store(topic, *, api_url="http://localhost:1633", stamp="auto",
            signer=None, owner=None, feed_ttl=15.0,
            deferred_upload=True, max_concurrent_reads=16) -> RecordStore
```

Blobs in a Bee node (`BeeBytesStore`) **and** the mutable latest-root in a Swarm feed
(`SwarmFeedPointer`), so a published store has a stable address instead of a root hash
passed around by hand. Pass `signer=` to publish your own store, `owner=` to follow
someone else's (read-only). The postage batch is resolved once by the blob store and
shared with the feed's SOC writes.

This is the single greppable answer to "where is Swarm specified?" — everything above
`RecordStore` stays backend-neutral. It is what `odag`'s `swarm:NAME` backend calls when
a signer is configured (`src/ontodag/__main__.py`, `SwarmBackend._record_store`); without
one, `odag` assembles `BeeBytesStore` + a local `FilePointer` itself, which is the wiring
`swarm_store` exists to replace — that combination leaves the head on local disk while
only the blobs go to Swarm, which is exactly the keyless mode's documented limitation.

## Version history relevant to OntoDAG

All releases since `v0.3.0` have been additive — no breaking API changes — which is why
OntoDAG's dependency is a floor (`>=0.20.0` in `pyproject.toml`, in the base dependencies
and the `swarm` extra alike) rather than an exact pin. One behavioural tightening rather
than a signature change: 0.14.0 made `"auto"` refuse batches with under a day of validity
left, so a batch that older versions would have selected can now be rejected.

- **v0.20.0** — (the floor since 2026-08-06) `history()`, `undo()`, `redo()`,
  `checkout()`, `status()`, `commit(message=…)` and a timeline-keeping `FilePointer`
  — the version-history surface `odag undo` is built on. Nothing existing changed
  except `commit()` gaining an optional keyword.
- **v0.4.0/0.4.1** — the real `SwarmFeedPointer` (above), replacing a documented stub.
- **v0.5.0–v0.7.1** — concurrent bulk I/O: `items()`, `get_many`/`put_many`, lazily
  streamed `keys()`/`items()`, pooled HTTP connections in `BeeBytesStore`, and batched
  blob/trie writes in `commit()`.
- **v0.8.0–v0.10.0** — multi-writer primitives: three-way `merge`, `commit(reconcile=True)`,
  `compare_and_set` on both pointer backends.
- **v0.11.0** — `postage_batch_id` defaults to `"auto"` (selection via swarmfs, never
  purchase).
- **v0.12.0** — `swarm_store()` (above). **v0.12.1** — metadata only (the PyPI page was
  blank: `readme` was never declared).
- **v0.13.0** — `DirBytesStore`, `FsspecBytesStore`, pluggable `addressing=`.
- **v0.13.1** — `RecordStore.blobs`, needed by `EagerOntoDAG.merge_published`.
  **v0.13.2** — metadata only (`requires-python>=3.11`, populated `[project.urls]`).
- **v0.14.0** — (the floor 2026-08-01, until the proofs moved it) Postage batch health: the one-day
  `AUTO_MIN_BATCH_TTL`, expiry and bucket-fullness warnings, `batch_status()`, and
  402-on-write messages that distinguish "overissued bucket, dilute and retry, nothing
  lost" from an expired batch. Adds the `[stamps]` extra (`swarmfs>=0.4.0`) — which is
  the reason the floor sits here rather than at 0.13.1 (see above).
- **v0.15.0** — public `RecordStore.diff(other_root)` (above).
- **v0.16.0** — **OntoDAG's current floor.** Verifiable inclusion/absence proofs:
  `RecordStore.prove(key)`, module-level `verify_proof(proof, root)`, `ProofError`,
  `PROOF_FORMAT` (above). Built at ontodag's request (`CONTRACT.md` §7 Tier 2) and
  consumed the same day by `ontodag.certificates` (`is_below` certificates — which is
  what moved the floor here). The version this document was last synced against
  (local checkout; installed 2026-08-01).

Renewal is deliberately absent throughout: recordstore reports batch health, the caller
decides whether to spend.

Earlier renames worth knowing when reading old notes or commits: `BeeChunkStore` →
`BeeBytesStore` (v0.2.0), then `ChunkStore` → `BytesStore`, `MemoryChunkStore` →
`MemoryBytesStore`, and the `RecordStore` parameter `chunks` → `bytes_store` (v0.3.0).
