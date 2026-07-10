"""recordstore: a versioned record store over a content-addressed chunk store.

This is the thin database kernel between Swarm (immutable chunks + a mutable
feed pointer) and an application that wants to think in records and versions.
It knows nothing about graphs, edges, or ontologies.

Model
-----
- A *record* is any JSON-compatible value, stored under a string key.
- All records live in a persistent (copy-on-write) compacted radix trie whose
  nodes are chunks; the trie's root reference identifies one immutable,
  self-consistent snapshot of the entire dataset.
- Mutations are staged in memory and flushed by `commit()`, which produces a
  single new root reference. Readers pin a root and see a frozen snapshot.
- Encodings are canonical (sorted keys, fixed separators), so equal content
  yields byte-equal chunks and therefore an equal root: same dataset =>
  same root reference, regardless of insertion order or history.

Layering
--------
  ChunkStore  : put(bytes) -> ref, get(ref) -> bytes      (Memory / Bee HTTP)
  Trie        : canonical persistent radix trie over the chunk store
  RecordStore : staging, commit, snapshots, prefix iteration
  Pointer     : mutable "latest root" (Memory / File; Swarm feed = follow-up)

Nothing above this layer should ever see a chunk or a trie node.
"""

from __future__ import annotations

import json
import hashlib
import os
from typing import Dict, Iterator, Optional, Protocol, Tuple

Ref = str  # hex-encoded chunk reference

_SCHEMA_VERSION = 1
_TOMBSTONE = object()


# ---------------------------------------------------------------------------
# Canonical encoding
# ---------------------------------------------------------------------------

def canonical_bytes(obj) -> bytes:
    """Deterministic byte encoding: equal values => equal bytes.

    Content addressing makes this a correctness requirement, not a style
    choice. Rejects NaN/Infinity (not canonical in JSON).
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def _encode_value(value) -> bytes:
    return canonical_bytes({"rsv": _SCHEMA_VERSION, "val": value})


def _decode_value(data: bytes):
    obj = json.loads(data.decode("utf-8"))
    if obj.get("rsv") != _SCHEMA_VERSION:
        raise ValueError(f"unsupported record schema version: {obj.get('rsv')!r}")
    return obj["val"]


# ---------------------------------------------------------------------------
# Chunk store backends
# ---------------------------------------------------------------------------

class ChunkStore(Protocol):
    def put(self, data: bytes) -> Ref: ...
    def get(self, ref: Ref) -> bytes: ...


class MemoryChunkStore:
    """In-memory content-addressed store; the test double for Swarm."""

    def __init__(self):
        self.chunks: Dict[Ref, bytes] = {}

    def put(self, data: bytes) -> Ref:
        ref = hashlib.sha256(data).hexdigest()
        self.chunks[ref] = data
        return ref

    def get(self, ref: Ref) -> bytes:
        try:
            return self.chunks[ref]
        except KeyError:
            raise KeyError(f"chunk not found: {ref}") from None

    def __len__(self):
        return len(self.chunks)


class BeeChunkStore:
    """Chunk store over a Bee node's HTTP API (POST/GET /bytes).

    Values larger than one 4 KB chunk are handled transparently: Bee's
    splitter turns any payload into a chunk tree and returns one reference.
    Requires a usable postage batch id for writes.
    """

    def __init__(self, api_url: str, postage_batch_id: str,
                 deferred_upload: bool = True):
        import requests  # lazy: only needed for the real backend
        self._requests = requests
        self.api_url = api_url.rstrip("/")
        self.batch = postage_batch_id
        self.deferred = deferred_upload

    def put(self, data: bytes) -> Ref:
        r = self._requests.post(
            f"{self.api_url}/bytes",
            data=data,
            headers={
                "Content-Type": "application/octet-stream",
                "Swarm-Postage-Batch-Id": self.batch,
                "Swarm-Deferred-Upload": "true" if self.deferred else "false",
            },
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["reference"]

    def get(self, ref: Ref) -> bytes:
        r = self._requests.get(f"{self.api_url}/bytes/{ref}", timeout=120)
        if r.status_code == 404:
            raise KeyError(f"chunk not found: {ref}")
        r.raise_for_status()
        return r.content


# ---------------------------------------------------------------------------
# Persistent compacted radix trie (canonical)
#
# Node wire format (canonical JSON):
#   {"tn": 1, "p": "<hex prefix>", "v": "<value ref>"|null, "c": {"<hex byte>": "<ref>", ...}}
#
# Canonical-form invariants (make the structure a pure function of content):
#   - a node with no value and no children does not exist (empty map => root None)
#   - a node with no value and exactly one child is merged into that child
# ---------------------------------------------------------------------------

class _Node:
    __slots__ = ("prefix", "value_ref", "children")

    def __init__(self, prefix: bytes, value_ref: Optional[Ref],
                 children: Dict[int, Ref]):
        self.prefix = prefix
        self.value_ref = value_ref
        self.children = children  # first-byte -> child node ref


class _Trie:
    def __init__(self, chunks: ChunkStore):
        self._chunks = chunks
        self._cache: Dict[Ref, _Node] = {}  # nodes are immutable => safe

    # -- node io -----------------------------------------------------------

    def _load(self, ref: Ref) -> _Node:
        node = self._cache.get(ref)
        if node is None:
            obj = json.loads(self._chunks.get(ref).decode("utf-8"))
            if obj.get("tn") != 1:
                raise ValueError("not a trie node or unsupported version")
            node = _Node(
                bytes.fromhex(obj["p"]),
                obj["v"],
                {int(k, 16): v for k, v in obj["c"].items()},
            )
            self._cache[ref] = node
        return node

    def _store(self, node: _Node) -> Ref:
        data = canonical_bytes({
            "tn": 1,
            "p": node.prefix.hex(),
            "v": node.value_ref,
            "c": {format(b, "02x"): r for b, r in sorted(node.children.items())},
        })
        ref = self._chunks.put(data)
        self._cache[ref] = node
        return ref

    # -- operations (functional: take a root ref, return a new root ref) ----

    def get(self, root: Optional[Ref], key: bytes) -> Optional[Ref]:
        while root is not None:
            node = self._load(root)
            if not key.startswith(node.prefix):
                return None
            key = key[len(node.prefix):]
            if key == b"":
                return node.value_ref
            root = node.children.get(key[0])
            key = key[1:]
        return None

    def insert(self, root: Optional[Ref], key: bytes, value_ref: Ref) -> Ref:
        if root is None:
            return self._store(_Node(key, value_ref, {}))
        node = self._load(root)
        common = os.path.commonprefix([node.prefix, key])

        if len(common) < len(node.prefix):
            # split: demote the existing node under the diverging byte
            demoted = _Node(node.prefix[len(common) + 1:], node.value_ref,
                            dict(node.children))
            children = {node.prefix[len(common)]: self._store(demoted)}
            rest = key[len(common):]
            if rest == b"":
                return self._store(_Node(common, value_ref, children))
            leaf = self._store(_Node(rest[1:], value_ref, {}))
            children[rest[0]] = leaf
            return self._store(_Node(common, None, children))

        rest = key[len(node.prefix):]
        if rest == b"":
            return self._store(_Node(node.prefix, value_ref, dict(node.children)))
        children = dict(node.children)
        child_ref = children.get(rest[0])
        if child_ref is None:
            children[rest[0]] = self._store(_Node(rest[1:], value_ref, {}))
        else:
            children[rest[0]] = self.insert(child_ref, rest[1:], value_ref)
        return self._store(_Node(node.prefix, node.value_ref, children))

    def delete(self, root: Optional[Ref], key: bytes) -> Optional[Ref]:
        if root is None:
            raise KeyError(key)
        node = self._load(root)
        if not key.startswith(node.prefix):
            raise KeyError(key)
        rest = key[len(node.prefix):]

        if rest == b"":
            if node.value_ref is None:
                raise KeyError(key)
            return self._canonicalize(node.prefix, None, dict(node.children))

        child_ref = node.children.get(rest[0])
        if child_ref is None:
            raise KeyError(key)
        new_child = self.delete(child_ref, rest[1:])
        children = dict(node.children)
        if new_child is None:
            del children[rest[0]]
        else:
            children[rest[0]] = new_child
        return self._canonicalize(node.prefix, node.value_ref, children)

    def _canonicalize(self, prefix: bytes, value_ref: Optional[Ref],
                      children: Dict[int, Ref]) -> Optional[Ref]:
        """Restore canonical-form invariants after a removal."""
        if value_ref is None and not children:
            return None
        if value_ref is None and len(children) == 1:
            (byte, child_ref), = children.items()
            child = self._load(child_ref)
            merged = _Node(prefix + bytes([byte]) + child.prefix,
                           child.value_ref, dict(child.children))
            return self._store(merged)
        return self._store(_Node(prefix, value_ref, children))

    def items(self, root: Optional[Ref],
              prefix: bytes = b"") -> Iterator[Tuple[bytes, Ref]]:
        """All (key, value_ref) with key under `prefix`, in sorted key order."""
        if root is None:
            return
        stack = [(root, b"")]
        out = []
        while stack:
            ref, acc = stack.pop()
            node = self._load(ref)
            full = acc + node.prefix
            # prune subtrees that cannot contain the prefix
            probe = min(len(full), len(prefix))
            if full[:probe] != prefix[:probe]:
                continue
            if node.value_ref is not None and full.startswith(prefix):
                out.append((full, node.value_ref))
            for byte, child in node.children.items():
                stack.append((child, full + bytes([byte])))
        yield from sorted(out)


# ---------------------------------------------------------------------------
# Pointers ("latest root")
# ---------------------------------------------------------------------------

class Pointer(Protocol):
    def get(self) -> Optional[Ref]: ...
    def set(self, root: Ref) -> None: ...


class MemoryPointer:
    def __init__(self, root: Optional[Ref] = None):
        self._root = root

    def get(self) -> Optional[Ref]:
        return self._root

    def set(self, root: Ref) -> None:
        self._root = root


class FilePointer:
    """Local-file pointer, useful during development."""

    def __init__(self, path: str):
        self.path = path

    def get(self) -> Optional[Ref]:
        try:
            with open(self.path) as f:
                content = f.read().strip()
                return content or None
        except FileNotFoundError:
            return None

    def set(self, root: Ref) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            f.write(root)
        os.replace(tmp, self.path)  # atomic on POSIX


class SwarmFeedPointer:
    """Placeholder for the Swarm feed backend.

    A feed update is a signed single-owner chunk: the update must be
    BMT-hashed and secp256k1-signed with the feed owner's key client-side,
    then posted to Bee's /soc/{owner}/{id} endpoint; lookups go through
    GET /feeds/{owner}/{topic}. Doing this properly needs an Ethereum
    signing dependency (e.g. eth-keys/coincurve), so it is deliberately
    out of scope for this stdlib-only first cut. The interface is the
    contract; swapping this in changes nothing above it.
    """

    def __init__(self, *_, **__):
        raise NotImplementedError(
            "Swarm feed pointer requires client-side SOC signing; "
            "see class docstring. Use FilePointer/MemoryPointer meanwhile."
        )


# ---------------------------------------------------------------------------
# RecordStore
# ---------------------------------------------------------------------------

class RecordStore:
    """Staged, versioned key->record store over a ChunkStore.

    Reads are read-your-writes (staged changes shadow the committed trie).
    `commit()` flushes staged changes and returns the new root reference;
    `RecordStore.at(root, chunks)` opens a read-only snapshot of any root.
    Returned records are deep copies: mutating them never mutates the store.
    """

    def __init__(self, chunks: ChunkStore, root: Optional[Ref] = None,
                 pointer: Optional[Pointer] = None, _readonly: bool = False):
        self._chunks = chunks
        self._trie = _Trie(chunks)
        self._root = pointer.get() if (pointer and root is None) else root
        self._pointer = pointer
        self._staged: Dict[str, object] = {}
        self._readonly = _readonly

    # -- snapshots -----------------------------------------------------------

    @classmethod
    def at(cls, root: Optional[Ref], chunks: ChunkStore) -> "RecordStore":
        return cls(chunks, root=root, _readonly=True)

    @property
    def root(self) -> Optional[Ref]:
        """Root of the last committed state (staged changes not included)."""
        return self._root

    # -- record operations -----------------------------------------------------

    @staticmethod
    def _check_key(key: str) -> bytes:
        if not isinstance(key, str) or key == "":
            raise ValueError("key must be a non-empty string")
        return key.encode("utf-8")

    def get(self, key: str):
        kb = self._check_key(key)
        if key in self._staged:
            staged = self._staged[key]
            if staged is _TOMBSTONE:
                raise KeyError(key)
            return json.loads(canonical_bytes(staged))  # deep copy
        vref = self._trie.get(self._root, kb)
        if vref is None:
            raise KeyError(key)
        return _decode_value(self._chunks.get(vref))

    def contains(self, key: str) -> bool:
        try:
            self.get(key)
            return True
        except KeyError:
            return False

    def put(self, key: str, value) -> None:
        if self._readonly:
            raise TypeError("read-only snapshot")
        self._check_key(key)
        canonical_bytes(value)  # fail fast on non-encodable values
        self._staged[key] = json.loads(canonical_bytes(value))  # detach

    def delete(self, key: str) -> None:
        if self._readonly:
            raise TypeError("read-only snapshot")
        kb = self._check_key(key)
        if key not in self._staged and self._trie.get(self._root, kb) is None:
            raise KeyError(key)
        self._staged[key] = _TOMBSTONE

    def keys(self, prefix: str = "") -> Iterator[str]:
        """Sorted keys under `prefix`, staged overlay included."""
        pb = prefix.encode("utf-8")
        committed = {
            k.decode("utf-8")
            for k, _ in self._trie.items(self._root, pb)
        }
        for key, staged in self._staged.items():
            if not key.startswith(prefix):
                continue
            if staged is _TOMBSTONE:
                committed.discard(key)
            else:
                committed.add(key)
        yield from sorted(committed)

    # -- commit ---------------------------------------------------------------

    def commit(self) -> Optional[Ref]:
        """Flush staged changes; return the new root and update the pointer.

        The root/pointer changes only after every chunk write has succeeded,
        so a reader following the pointer sees all of a commit or none of it.
        """
        if self._readonly:
            raise TypeError("read-only snapshot")
        root = self._root
        for key in sorted(self._staged):  # deterministic write order
            staged = self._staged[key]
            kb = key.encode("utf-8")
            if staged is _TOMBSTONE:
                try:
                    root = self._trie.delete(root, kb)
                except KeyError:
                    pass  # deleted a key that never existed in the trie
            else:
                vref = self._chunks.put(_encode_value(staged))
                root = self._trie.insert(root, kb, vref)
        self._staged.clear()
        self._root = root
        if self._pointer is not None and root is not None:
            self._pointer.set(root)
        return root
