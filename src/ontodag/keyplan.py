"""The key plan: what a store shares, enforced by keys, with no server.

docs/plans/SHARING_ON_SWARM.md §4. SHARING.md's rule, R sees x iff x is
below one of R's principals in the author's store, becomes something a
reader checks for itself. For each publication the author writes, into
any record store (a `RecordStore`, local or on Swarm):

    kp/meta          {"v", "author"}: the author's public key
    kp/g/<lookup>    a grantee entry per principal, Bee-ACT-shaped: the
                     principal node's key, found and unwrapped by ECDH
                     between author and reader (`act.act_keys`)
    kp/t/<u>/<v>     a token per edge of the combined order below the
                     principals, asserted edges and computed hops alike:
                     v's key wrapped under u's (`act.wrap`)
    kp/r/<id>        a record per shared node: its name, and its content's
                     data key, sealed under the node's key
    kp/c/<id>        content, sealed under its own data key

**What a reader gets.** A reader derives a node's key exactly when the node
is in its reach (`experiments/keyplan_spike.py` checks this on random
stores and edits). Records never name parents or children: the edges are
the tokens. So a reader sees exactly the edges between the nodes it
reaches, the faithful piece of the store of SHARING §2.1.

**Two keys per node** (§4.2):
- a random *derivation key*, which wraps the node's children's keys and its
  data keys, and is the key that rotates;
- per-version *data keys* for content, which never rotate.

So a rotation re-wraps 32 bytes and never re-encrypts content.

**Keyed node ids.** Ids are keyed with an author secret, so nobody can test
a guessed name against the published shape (§4.4).

**Revocation is lazy** (§4.3):
- A node someone lost gets a new key only before something new is wrapped
  under it: a new token out of it, or a changed record.
- The rotation then goes upward to a fixpoint, because rotating a node
  re-wraps its new key under its parents, which may be lost and stale too.
- The guarantee: a reader never derives a key minted after it last had
  that node in reach.
- It's forward-only, as on Swarm it must be: what a reader had, it keeps.

The author's private bookkeeping (every node key, the stale set, what was
last published) is `Publisher.state`, a JSON-serialisable dict. It belongs
in the author's own encrypted store, never beside the published one.

Module-level imports are stdlib only. secp256k1, Keccak and AES-SIV come
through the `act` extra (coincurve, pycryptodome).
"""

import base64
import hashlib
import hmac
import json
import os

from ontodag import sharing
from ontodag._extras import require
from ontodag.act import act_keys, public_key, stream_transform, unwrap, wrap

KP_VERSION = 2
KEY_LEN = 32

META_KEY = "kp/meta"
GRANT_PREFIX = "kp/g/"
TOKEN_PREFIX = "kp/t/"
RECORD_PREFIX = "kp/r/"
CONTENT_PREFIX = "kp/c/"

EVERYONE = "everyone"

_ID_DOMAIN = b"ontodag-keyplan-node-v2\0"
_CONTENT_DOMAIN = b"ontodag-keyplan-content-v2\0"
_BOX_DOMAIN = b"ontodag-keyplan-box-v2"
_EVERYONE_DOMAIN = b"ontodag-keyplan-everyone-v2"


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #

def everyone_key() -> bytes:
    """The private key of the reserved principal `everyone`, known to all:
    whatever is shared with `everyone` is public, and stays public."""
    return hashlib.sha256(_EVERYONE_DOMAIN).digest()


def keyed_id(secret: bytes, name: str) -> str:
    """A node's id: HMAC-SHA256 of its name under the author's secret, so
    ids can't be computed from guessed names (unlike `act.node_id`)."""
    return hmac.new(secret, _ID_DOMAIN + name.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:32]


def _aes():
    require("Crypto", "act", "the key plan")
    from Crypto.Cipher import AES
    return AES


def _box_key(k: bytes) -> bytes:
    return (hashlib.sha256(_BOX_DOMAIN + b"|enc|" + k).digest()
            + hashlib.sha256(_BOX_DOMAIN + b"|mac|" + k).digest())


def seal(k: bytes, header: str, data: bytes) -> str:
    """AES-SIV under a key derived from `k`, bound to `header` (the record's
    place), deterministic: equal inputs seal to equal bytes, so republishing
    an unchanged record changes no root (G1)."""
    aes = _aes()
    cipher = aes.new(_box_key(k), aes.MODE_SIV)
    cipher.update(header.encode("utf-8"))
    ciphertext, tag = cipher.encrypt_and_digest(data)
    return base64.b64encode(tag + ciphertext).decode("ascii")


def unseal(k: bytes, header: str, box: str) -> bytes:
    """The inverse of `seal`; `ValueError` if the key or header is wrong."""
    raw = base64.b64decode(box)
    aes = _aes()
    cipher = aes.new(_box_key(k), aes.MODE_SIV)
    cipher.update(header.encode("utf-8"))
    return cipher.decrypt_and_verify(raw[16:], raw[:16])


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


# --------------------------------------------------------------------------- #
# The plan: a pure function of (store, principals)
# --------------------------------------------------------------------------- #

def children(dag, name):
    """A node's children in the combined order: asserted edges, and the
    computed hops between present typed values (SHARING §2.2)."""
    node = dag.nodes[name]
    out = {c.name for c in node.neighbors}
    out.update(c.name for c in dag._computed_children(node))
    return out


def plan(dag, principals, reach=None):
    """The token plan: every edge (u, c) of the combined order where u is a
    principal, or in some principal's reach, and c is a child of u.

    It is a pure function of the store and the principals (SHARING Q4).
    The key values are not, since revocation needs fresh keys. `reach`
    may pass each principal's reach, already computed."""
    edges = set()
    for p in principals:
        if p not in dag.nodes:
            continue
        cone = reach[p] if reach is not None else sharing.reach(dag, [p])
        for u in {p} | set(cone):
            for c in children(dag, u):
                edges.add((u, c))
    return frozenset(edges)


# --------------------------------------------------------------------------- #
# The author's side
# --------------------------------------------------------------------------- #

class Published:
    """What one `publish` did: `root`, `rotated` (names), `stale` (lost
    nodes still awaiting rotation), `written` and `deleted` (record
    counts), `shared` (nodes someone can read)."""

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def __repr__(self):
        return "Published(" + ", ".join(
            f"{k}={v!r}" for k, v in self.__dict__.items()) + ")"


class Publisher:
    """Keep a record store equal to the key plan of a store.

    `store` receives the public material: a `RecordStore`, or anything with
    `put/get/delete/keys` (and optionally `commit`). `author_key` is the
    author's 32-byte secp256k1 secret, the sharing identity whose public
    half readers hold. `state` resumes from an earlier `Publisher.state`.
    `rng` is injectable for tests.
    """

    def __init__(self, store, author_key, state=None, rng=None):
        self.store = store
        self._author_key = author_key
        self._rng = rng or os.urandom
        st = state or {}
        if st and st.get("v") != KP_VERSION:
            raise ValueError(f"key plan state version {st.get('v')!r}, "
                             f"this is {KP_VERSION}")
        self._id_secret = (bytes.fromhex(st["id_secret"]) if st
                           else self._rng(KEY_LEN))
        self._keys = {n: bytes.fromhex(k) for n, k in st.get("keys", {}).items()}
        self._epoch = dict(st.get("epochs", {}))
        self._stale = set(st.get("stale", ()))
        self._plan = {tuple(e) for e in st.get("plan", ())}
        self._reach = {p: set(ns) for p, ns in st.get("reach", {}).items()}
        self._principals = {p: bytes.fromhex(k)
                            for p, k in st.get("principals", {}).items()}
        self._records = dict(st.get("records", {}))
        self._data = {n: dict(d) for n, d in st.get("data", {}).items()}
        self._meta = bool(st.get("meta"))

    # -- bookkeeping ---------------------------------------------------------
    @property
    def state(self) -> dict:
        """The private state, JSON-serialisable. It holds every node key:
        keep it encrypted, in the author's own store."""
        return {
            "v": KP_VERSION,
            "id_secret": self._id_secret.hex(),
            "keys": {n: k.hex() for n, k in sorted(self._keys.items())},
            "epochs": dict(sorted(self._epoch.items())),
            "stale": sorted(self._stale),
            "plan": sorted([u, v] for u, v in self._plan),
            "reach": {p: sorted(ns) for p, ns in sorted(self._reach.items())},
            "principals": {p: k.hex() for p, k in sorted(self._principals.items())},
            "records": dict(sorted(self._records.items())),
            "data": dict(sorted(self._data.items())),
            "meta": self._meta,
        }

    @property
    def stale(self) -> frozenset:
        """Nodes someone lost that still have the key they had."""
        return frozenset(self._stale)

    def node_id(self, name: str) -> str:
        return keyed_id(self._id_secret, name)

    def _content_id(self, name: str, digest: str) -> str:
        return hmac.new(self._id_secret,
                        _CONTENT_DOMAIN + name.encode("utf-8") + b"\0" + digest.encode(),
                        hashlib.sha256).hexdigest()[:32]

    # -- publishing ------------------------------------------------------------
    def publish(self, dag, principals, content=None, eager=False, message=None):
        """Bring the store up to date with `dag`.

        `principals` maps each principal's name in `dag` to that reader's
        33-byte public key; names absent from `dag` are ignored. `content`
        maps names to bytes (a post's text, a file) and is sealed under a
        data key per version. `eager=True` rotates every stale node now,
        a "rotate now" for urgent removals. Returns a `Published`.
        """
        content = content or {}
        present = {p: bytes(k) for p, k in principals.items() if p in dag.nodes}
        reach = {p: set(sharing.reach(dag, [p])) for p in present}

        # what someone lost: whatever fell out of a reach, and everything a
        # removed or re-keyed principal reached, its own node included
        lost = set()
        for p, before in self._reach.items():
            if p not in present or present[p] != self._principals.get(p):
                lost |= before | {p}
            else:
                lost |= before - reach[p]
        self._stale |= lost
        self._stale &= set(dag.nodes)

        new_plan = set(plan(dag, present, reach))
        shared = set(present).union(*reach.values())

        # the records as they would be published now, and which changed
        data = {}
        for n in shared:
            blob = content.get(n)
            if blob is None:
                continue
            digest = hashlib.sha256(blob).hexdigest()
            old = self._data.get(n)
            key = (old["key"] if old and old["digest"] == digest
                   else self._rng(KEY_LEN).hex())
            data[n] = {"digest": digest, "key": key, "size": len(blob),
                       "id": self._content_id(n, digest)}
        records = {n: self._record(n, data.get(n)) for n in shared}
        digests = {n: hashlib.sha256(_canonical(r)).hexdigest()
                   for n, r in records.items()}
        changed = {n for n in shared if digests[n] != self._records.get(n)}

        # which stale nodes rotate first: any that would wrap something new,
        # upward to a fixpoint
        due = (self._stale & changed) | (set(self._stale) if eager else set())
        while True:
            minting = ((new_plan - self._plan)
                       | {(u, v) for (u, v) in new_plan if v in due})
            more = {u for (u, v) in minting if u in self._stale} - due
            if not more:
                break
            due |= more
        for n in sorted(due):
            self._keys[n] = self._rng(KEY_LEN)
            self._epoch[n] = self._epoch.get(n, 0) + 1
        self._stale -= due
        fresh = set()
        for n in sorted(shared):
            if n not in self._keys:
                self._keys[n] = self._rng(KEY_LEN)
                self._epoch.setdefault(n, 0)
                fresh.add(n)
        renewed = due | fresh

        written = deleted = 0
        st = self.store
        ids = {n: self.node_id(n) for n in shared | {n for e in self._plan for n in e}}

        if not self._meta:
            st.put(META_KEY, {"v": KP_VERSION,
                              "author": public_key(self._author_key).hex()})
            self._meta = True
            written += 1

        # tokens
        for u, v in sorted(new_plan):
            if (u, v) in self._plan and u not in renewed and v not in renewed:
                continue
            st.put(f"{TOKEN_PREFIX}{ids[u]}/{ids[v]}", {
                "v": KP_VERSION,
                "token": wrap(self._keys[u], ids[v], self._keys[v]).hex(),
                "epoch": self._epoch[v]})
            written += 1
        for u, v in sorted(self._plan - new_plan):
            st.delete(f"{TOKEN_PREFIX}{ids[u]}/{ids[v]}")
            deleted += 1

        # content, one sealed record per version
        for n, d in sorted(data.items()):
            old = self._data.get(n)
            if old and old["id"] == d["id"]:
                continue
            st.put(CONTENT_PREFIX + d["id"], {
                "v": KP_VERSION,
                "box": seal(bytes.fromhex(d["key"]), d["id"], content[n])})
            written += 1
        for n, old in sorted(self._data.items()):
            if n not in data or data[n]["id"] != old["id"]:
                st.delete(CONTENT_PREFIX + old["id"])
                deleted += 1

        # records
        for n in sorted(shared):
            if n not in changed and n not in renewed:
                continue
            header = f"{ids[n]}|{self._epoch[n]}"
            st.put(RECORD_PREFIX + ids[n], {
                "v": KP_VERSION, "epoch": self._epoch[n],
                "box": seal(self._keys[n], header, _canonical(records[n]))})
            written += 1
        for n in sorted(set(self._records) - shared):
            st.delete(RECORD_PREFIX + self.node_id(n))
            deleted += 1

        # grantee entries
        for p, pub in sorted(present.items()):
            if self._principals.get(p) == pub and p not in renewed:
                continue
            lookup, wrap_key = act_keys(self._author_key, pub)
            st.put(GRANT_PREFIX + lookup.hex(), {
                "v": KP_VERSION, "node": ids[p], "epoch": self._epoch[p],
                "key": stream_transform(wrap_key, self._keys[p]).hex()})
            written += 1
        for p, pub in sorted(self._principals.items()):
            if present.get(p) != pub:
                lookup, _ = act_keys(self._author_key, pub)
                st.delete(GRANT_PREFIX + lookup.hex())
                deleted += 1

        self._plan = new_plan
        self._reach = reach
        self._principals = present
        self._records = digests
        self._data = data
        root = st.commit(message=message) if hasattr(st, "commit") else None
        return Published(root=root, rotated=sorted(due), stale=len(self._stale),
                         written=written, deleted=deleted, shared=len(shared))

    def _record(self, name, data):
        record = {"name": name}
        if data:
            record["content"] = {"id": data["id"], "key": data["key"],
                                 "size": data["size"]}
        return record


# --------------------------------------------------------------------------- #
# The reader's side
# --------------------------------------------------------------------------- #

class Received:
    """What one author shares with one reader, as that reader derived it:
    `principal` (the reader's own node in the author's store), `names`, and
    `edges` as (parent, child) pairs, all inside the reader's reach."""

    def __init__(self, store, principal, names, edges, contents):
        self._store = store
        self.principal = principal
        self.names = frozenset(names)
        self.edges = frozenset(edges)
        self._contents = contents          # name -> {"id", "key", "size"}

    def __len__(self):
        return len(self.names)

    def __contains__(self, name):
        return name in self.names

    def children(self, name):
        return sorted(c for p, c in self.edges if p == name)

    def parents(self, name):
        return sorted(p for p, c in self.edges if c == name)

    def content(self, name):
        """The content filed with `name`, or None if it has none."""
        c = self._contents.get(name)
        if c is None:
            return None
        record = self._store.get(CONTENT_PREFIX + c["id"])
        return unseal(bytes.fromhex(c["key"]), c["id"], record["box"])


class Reader:
    """Hold a personal key and read what one author shares with it.

    `store` is the author's published record store, or a read-only
    snapshot of it (`RecordStore.at(root, blobs)`); `author_public_key` is
    known out of band (a contact card), not taken from the store.
    """

    def __init__(self, store, reader_key, author_public_key):
        self.store = store
        self._key = reader_key
        self._author = author_public_key

    @classmethod
    def public(cls, store, author_public_key):
        """A reader holding `everyone`'s key: what the author made public."""
        return cls(store, everyone_key(), author_public_key)

    def _entry(self):
        lookup, wrap_key = act_keys(self._key, self._author)
        try:
            entry = self.store.get(GRANT_PREFIX + lookup.hex())
        except KeyError:
            return None, None
        return entry["node"], stream_transform(wrap_key, bytes.fromhex(entry["key"]))

    def walk(self):
        """(top id, {id: key}, {(parent id, child id)}): the tokens walked
        level by level, listing each held node's own tokens only, so a walk
        costs the reader's reach, never the author's whole graph."""
        top, key = self._entry()
        if top is None:
            return None, {}, set()
        keys, edges, frontier = {top: key}, set(), [top]
        while frontier:
            nxt = []
            for u in frontier:
                prefix = f"{TOKEN_PREFIX}{u}/"
                for k in self.store.keys(prefix):
                    v = k[len(prefix):]
                    edges.add((u, v))
                    if v in keys:
                        continue
                    token = bytes.fromhex(self.store.get(k)["token"])
                    keys[v] = unwrap(keys[u], v, token)
                    nxt.append(v)
            frontier = nxt
        return top, keys, edges

    def receive(self) -> Received:
        """Everything shared with this reader, decrypted."""
        top, keys, edges = self.walk()
        if top is None:
            return Received(self.store, None, (), (), {})
        names, contents = {}, {}
        for i, k in keys.items():
            record = self.store.get(RECORD_PREFIX + i)
            plain = json.loads(unseal(k, f"{i}|{record['epoch']}", record["box"]))
            names[i] = plain["name"]
            if "content" in plain:
                contents[plain["name"]] = plain["content"]
        return Received(self.store, names[top], names.values(),
                        {(names[u], names[v]) for u, v in edges}, contents)
