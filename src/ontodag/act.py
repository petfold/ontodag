"""Category-based access control: the key graph (act-categories Phase 1).

`docs/plans/act-categories/DESIGN.md` §2, client side, no Bee involved:

    Every category node v has an independent random symmetric key K_v.
    For every edge u -> v along which access should flow, a public
    rekeying token T(u -> v) = Enc(K_u, K_v) is published.
    A reader can decrypt a document iff a directed token path exists
    from their personal leaf to the document's key.

Two halves, opposite directions (§2.2): people keys flow *upward*
(alice -> eng-dept -> company: more specific = fewer members), document
keys flow *downward* (reports -> financial-reports -> doc-42: a grant on
a category opens everything inside it), and a **bridge** is one token
from a people node to a document category. Audience is expressed ONLY by
where bridges come from; document categories encode topic, never
audience — the design trap §2.2 names.

What is Bee-compatible here, bit for bit (pinned against vectors from Bee
v2.8.1's own Go packages — `experiments/act_crypto_spike.py`, retired
into `tests/test_act.py`): the **grantee entry**. A person's way in is
exactly an ACT entry: `lookup = Keccak(ECDH_x || 0)`, wrap key =
`Keccak(ECDH_x || 1)`, value = Bee's stream cipher over the leaf key. So
a person holds one secp256k1 key, the same kind `bee_signer` is, and the
org publishes one 32-byte entry per person — never touching a document.

What is ours: the **tokens**. Bee has no notion of category-to-category
rekeying. A token is the same stream cipher under a per-edge key
`Keccak(K_u || domain || id(v))` — per edge, because the cipher is a
keystream XOR and one keystream over two children's keys would leak
their XOR (a two-time pad); the derivation is deterministic so two key
managers holding the same keys publish identical tokens, which is what
lets the token store have a canonical root like everything else.

**Trust model (§6):** whoever mints the keys — the key manager holding a
`KeyGraph` — can read everything. That is ACT's publisher-centric model
lifted from individuals to categories, not a regression. **Revocation is
forward-only:** rotating a node re-mints its tokens; content already
fetched under the old keys stays readable by whoever had them, and on
Swarm stays fetchable forever. Old epochs remain resolvable from old
roots (`RecordStore.at(root, store.blobs)`), the ACT-history mechanism in
recordstore terms.

**The seam into encrypted stores:** `store_key_for(K_v)` is a 64-byte
AES-SIV key for `ontodag.encstore.EncryptedBytesStore`, so a private
overlay's blobs take their key from the audience's node in this graph —
"a private overlay" and "a document category with an audience bridge"
become one mechanism (DESIGN.md §1, 2026-08-20).

Module-level imports are stdlib only; coincurve (secp256k1) and
pycryptodome (Keccak) are reached lazily through the `act` extra. The
store is duck-typed: anything with `put/get/delete/keys(prefix)/commit`
(a `recordstore.RecordStore`, or a `RecordStore.at(root, blobs)` snapshot
for readers).
"""

import hashlib
import os

from ontodag._extras import require

ACT_VERSION = 1
KEY_LEN = 32

_ID_DOMAIN = b"ontodag-act-node-v1\0"
_TOKEN_DOMAIN = b"|ontodag-act-token-v1|"
_AUDIENCE_DOMAIN = b"ontodag-act-audience-v1|"
_STORE_KEY_DOMAIN = b"ontodag-act-store-key-v1"

META_KEY = "act/meta"
TOKEN_PREFIX = "act/t/"
GRANT_PREFIX = "act/g/"


class AccessDenied(LookupError):
    """No token path from this reader's key to the requested node."""


# --------------------------------------------------------------------------- #
# Primitives — Bee's conventions, exactly (pkg/accesscontrol, pkg/encryption)
# --------------------------------------------------------------------------- #

def _coincurve():
    return require("coincurve", "act", "category-based access control")


def keccak256(data: bytes) -> bytes:
    require("Crypto", "act", "category-based access control")
    from Crypto.Hash import keccak
    return keccak.new(digest_bits=256, data=data).digest()


def public_key(private_key: bytes) -> bytes:
    """Compressed secp256k1 public key (33 bytes) for a 32-byte secret."""
    cc = _coincurve()
    return cc.PublicKey.from_valid_secret(private_key).format(compressed=True)


def shared_x(private_key: bytes, other_public: bytes) -> bytes:
    """ECDH x-coordinate as Go's `big.Int.Bytes()`: big-endian, leading
    zeros STRIPPED (so it is occasionally 31 bytes — the trap the spike's
    second vector exists for)."""
    cc = _coincurve()
    point = cc.PublicKey(other_public).multiply(private_key)
    return point.format(compressed=False)[1:33].lstrip(b"\x00")


def act_keys(private_key: bytes, other_public: bytes):
    """Bee's `getKeys`: (lookup key, access-key-decryption key)."""
    x = shared_x(private_key, other_public)
    return keccak256(x + b"\x00"), keccak256(x + b"\x01")


def stream_transform(key: bytes, data: bytes) -> bytes:
    """Bee's `encryption.go` transform: XOR each 32-byte segment with
    Keccak(Keccak(key || LE32(counter))). Its own inverse."""
    out = bytearray()
    for seg in range(0, len(data), 32):
        counter = (seg // 32).to_bytes(4, "little")
        segment_key = keccak256(keccak256(key + counter))
        out += bytes(a ^ b for a, b in zip(data[seg:seg + 32], segment_key))
    return bytes(out)


# --------------------------------------------------------------------------- #
# Ours: identifiers, tokens, audiences, the store-key seam
# --------------------------------------------------------------------------- #

def node_id(name: str) -> str:
    """Opaque 32-hex identifier for a category name. The token store shows
    shape and degree (DESIGN.md §6 names that leakage), not names; a reader
    who knows a name computes its id, a stranger reading the store sees
    only hashes. Stdlib sha256 — no crypto extra needed to *address*."""
    return hashlib.sha256(_ID_DOMAIN + name.encode("utf-8")).hexdigest()[:32]


def token_key(k_u: bytes, v_id: str) -> bytes:
    return keccak256(k_u + _TOKEN_DOMAIN + v_id.encode("ascii"))


def wrap(k_u: bytes, v_id: str, k_v: bytes) -> bytes:
    """T(u -> v) = Enc(K_u, K_v), under a per-edge key (see module doc)."""
    return stream_transform(token_key(k_u, v_id), k_v)


def unwrap(k_u: bytes, v_id: str, token: bytes) -> bytes:
    return stream_transform(token_key(k_u, v_id), token)


def audience_key(keys_by_name: dict) -> bytes:
    """AND audiences (DESIGN.md §2.5): a key only someone holding EVERY
    listed category key can derive. Concatenation in sorted-name order —
    canonical, or two writers mint divergent intersection keys."""
    if not keys_by_name:
        raise ValueError("an audience needs at least one category")
    material = b"".join(keys_by_name[name] for name in sorted(keys_by_name))
    return keccak256(_AUDIENCE_DOMAIN + material)


def store_key_for(k: bytes) -> bytes:
    """The 64-byte AES-SIV key `EncryptedBytesStore` takes, derived from a
    node (or audience) key: the encstore seam."""
    return (hashlib.sha256(_STORE_KEY_DOMAIN + b"|enc|" + k).digest()
            + hashlib.sha256(_STORE_KEY_DOMAIN + b"|mac|" + k).digest())


def _token_record_key(u_id: str, v_id: str) -> str:
    return f"{TOKEN_PREFIX}{u_id}/{v_id}"


# --------------------------------------------------------------------------- #
# The key manager's side
# --------------------------------------------------------------------------- #

class KeyGraph:
    """Mint category keys, publish tokens and grantee entries.

    `store` is where the public material goes (tokens, grantee entries,
    the org public key). The private material — every K_v and the org's
    secp256k1 secret — stays in this object; `export_keys()`/`keys=`
    round-trip it for the key manager's own safekeeping. `rng` is
    injectable so tests can show that two managers with equal keys
    publish byte-identical stores.
    """

    def __init__(self, store, org_private_key=None, keys=None, rng=None):
        self._store = store
        self._rng = rng or os.urandom
        self._org_priv = org_private_key or self._rng(KEY_LEN)
        self._keys = dict(keys or {})          # name -> K_v (32 bytes)
        self._epoch = {name: 0 for name in self._keys}   # name -> int
        self._store.put(META_KEY, {"v": ACT_VERSION,
                                   "org_pub": public_key(self._org_priv).hex()})

    # -- keys ---------------------------------------------------------------
    @property
    def org_public_key(self) -> bytes:
        return public_key(self._org_priv)

    def ensure(self, name: str) -> bytes:
        """The node's key, minting a fresh random one on first sight."""
        if name not in self._keys:
            self._keys[name] = self._rng(KEY_LEN)
        self._epoch.setdefault(name, 0)
        return self._keys[name]

    def key(self, name: str) -> bytes:
        return self._keys[name]

    def export_keys(self) -> dict:
        return dict(self._keys)

    # -- tokens (edges access flows along) ----------------------------------
    def link(self, u: str, v: str) -> None:
        """Publish T(u -> v): holders of K_u can now derive K_v."""
        k_u, k_v = self.ensure(u), self.ensure(v)
        u_id, v_id = node_id(u), node_id(v)
        self._store.put(_token_record_key(u_id, v_id), {
            "v": ACT_VERSION, "from": u_id, "to": v_id,
            "token": wrap(k_u, v_id, k_v).hex(),
            "epoch": self._epoch.get(v, 0)})

    def unlink(self, u: str, v: str) -> None:
        self._store.delete(_token_record_key(node_id(u), node_id(v)))

    def links(self):
        """Every published (u_id, v_id) edge."""
        for key in self._store.keys(TOKEN_PREFIX):
            u_id, v_id = key[len(TOKEN_PREFIX):].split("/")
            yield u_id, v_id

    # -- grantee entries (a person's way in; Bee-ACT-shaped) ----------------
    def grant(self, person: str, person_public_key: bytes) -> None:
        """`Enc(ECDH(org, person_pk), K_person)` at Bee's lookup key: one
        entry, touches no document (DESIGN.md §2.6 "hire")."""
        leaf = self.ensure(person)
        lookup, wrap_key = act_keys(self._org_priv, person_public_key)
        self._store.put(GRANT_PREFIX + lookup.hex(), {
            "v": ACT_VERSION, "leaf": node_id(person),
            "wrapped": stream_transform(wrap_key, leaf).hex(),
            "epoch": self._epoch.get(person, 0)})

    def revoke(self, person: str, person_public_key: bytes) -> list:
        """Delete the entry, then rotate the person's leaf and every
        *category* they could reach (nodes with outgoing tokens), so every
        token minted from now on is useless to the keys they walked away
        with. Document leaves are NOT rotated: their content is already
        encrypted under the key the person may have fetched, and rotating
        it would lock out the remaining readers without hiding anything
        (forward-only revocation, module doc / DESIGN.md §6). Returns the
        rotated names, so the caller can re-`grant` anyone whose entry sat
        on a rotated leaf."""
        lookup, _ = act_keys(self._org_priv, person_public_key)
        self._store.delete(GRANT_PREFIX + lookup.hex())
        has_out = {u_id for u_id, _v in self.links()}
        rotated = [person] + [n for n in self._reachable_from(person)
                              if node_id(n) in has_out]
        for name in rotated:
            self.rotate(name)
        return rotated

    def rotate(self, name: str) -> None:
        """New K_name; re-mint the tokens into and out of it and the
        grantee entries onto it, so everyone *still* entitled keeps a path
        (an epoch event, DESIGN.md §2.7)."""
        old_id = node_id(name)
        self._keys[name] = self._rng(KEY_LEN)
        self._epoch[name] = self._epoch.get(name, 0) + 1
        by_id = {node_id(n): n for n in self._keys}
        for u_id, v_id in list(self.links()):
            if old_id in (u_id, v_id):
                self.link(by_id[u_id], by_id[v_id])
        for key in list(self._store.keys(GRANT_PREFIX)):
            record = self._store.get(key)
            if record["leaf"] == old_id:
                # cannot re-wrap without the person's public key; the
                # entry's wrap key is ECDH-derived and not stored. So the
                # entry is dropped: re-`grant` the people who should stay.
                self._store.delete(key)

    def _reachable_from(self, name: str) -> list:
        by_id = {node_id(n): n for n in self._keys}
        out = {}
        for u_id, v_id in self.links():
            out.setdefault(u_id, []).append(v_id)
        seen, frontier = set(), [node_id(name)]
        while frontier:
            cur = frontier.pop()
            for nxt in out.get(cur, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        return sorted(by_id[i] for i in seen if i in by_id)

    # -- alignment with a knowledge DAG (the "aligned twin", DESIGN.md §9) --
    def align(self, dag, people=None, documents=None, bridges=()) -> dict:
        """Mint tokens along an OntoDAG's asserted edges: the cone under
        `people` upward (child -> parent), the cone under `documents`
        downward (parent -> child), plus explicit `bridges` — pairs
        (people_node, document_node). Idempotent: equal keys give equal
        tokens. Returns counts."""
        n_people = n_docs = 0
        if people is not None:
            for child, parent in _cone_edges(dag, people):
                self.link(child, parent)
                n_people += 1
        if documents is not None:
            for child, parent in _cone_edges(dag, documents):
                self.link(parent, child)
                n_docs += 1
        for who, what in bridges:
            self.link(who, what)
        return {"people": n_people, "documents": n_docs,
                "bridges": len(tuple(bridges))}

    def commit(self, **kwargs) -> str:
        return self._store.commit(**kwargs)


def _cone_edges(dag, root_name):
    """(child, parent) asserted edges inside the cone under `root_name`,
    root included. Asserted only — computed dimension order is not an
    access path anyone published a token for."""
    root = dag.nodes[root_name]
    seen, frontier, edges = {root.name}, [root], []
    while frontier:
        node = frontier.pop()
        for child in sorted(node.neighbors, key=lambda c: c.name):
            edges.append((child.name, node.name))
            if child.name not in seen:
                seen.add(child.name)
                frontier.append(child)
    return edges


# --------------------------------------------------------------------------- #
# The reader's side
# --------------------------------------------------------------------------- #

class Resolver:
    """Hold a personal key, walk the tokens, answer "can I read X?".

    Works over any store snapshot — `RecordStore.at(old_root, blobs)`
    resolves an old epoch. Every unwrap is memoized; the walk is a plain BFS over the
    published edges, so a walk costs the reachable part of the key graph,
    never the store."""

    def __init__(self, store, private_key: bytes):
        self._store = store
        self._priv = private_key
        self._keys = None            # id -> key, filled by _walk

    def _walk(self):
        if self._keys is not None:
            return self._keys
        meta = self._store.get(META_KEY)
        org_pub = bytes.fromhex(meta["org_pub"])
        lookup, wrap_key = act_keys(self._priv, org_pub)
        try:
            entry = self._store.get(GRANT_PREFIX + lookup.hex())
        except KeyError:
            self._keys = {}
            return self._keys
        keys = {entry["leaf"]: stream_transform(wrap_key,
                                                bytes.fromhex(entry["wrapped"]))}
        out = {}
        for key in self._store.keys(TOKEN_PREFIX):
            u_id, v_id = key[len(TOKEN_PREFIX):].split("/")
            out.setdefault(u_id, []).append((v_id, key))
        frontier = list(keys)
        while frontier:
            u_id = frontier.pop()
            for v_id, key in out.get(u_id, ()):
                if v_id in keys:
                    continue
                token = bytes.fromhex(self._store.get(key)["token"])
                keys[v_id] = unwrap(keys[u_id], v_id, token)
                frontier.append(v_id)
        self._keys = keys
        return keys

    def reachable_ids(self) -> set:
        return set(self._walk())

    def can_read(self, name: str) -> bool:
        return node_id(name) in self._walk()

    def key_for(self, name: str) -> bytes:
        try:
            return self._walk()[node_id(name)]
        except KeyError:
            raise AccessDenied(f"no token path to {name!r}") from None

    def audience_key(self, names) -> bytes:
        """The AND-audience key, if this reader holds every part."""
        return audience_key({n: self.key_for(n) for n in names})
