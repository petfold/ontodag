"""The provenance store: attribution without breaking the root.

Implements the agreed design of docs/PROVENANCE.md (reviewed 2026-08-01):
a store of **signed speech acts about claims**, kept strictly beside the
knowledge store — never inside it, or identical knowledge asserted by
different authors would stop producing identical roots (`CONTRACT.md` G1).

The shapes, exactly as agreed:

* **Subjects are claims, not edges** (§3): the ordered pair of canonical
  names ``sub ⊑ sup`` — stable under the core's own transitive reduction,
  where a stored edge is not. Node existence is ``X ⊑ *``; key↔name links
  are ``speaks-for`` subjects. (The ``payload(name, content-hash)`` form is
  the flagged residual — deliberately not implemented until it is worked.)
  This module treats names as opaque strings: **callers canonicalize**
  (the write surface does it through the DAG), so the store stays
  graph-independent.
* **Records** carry ``v`` and a namespaced ``ext`` map from day one
  (factbond's ``bondRef``/``confidence`` ride there later); four types —
  assertion (with ``origin: asserted|derived`` and optional
  ``derived_from``), endorsement, retraction (a speech act, never a
  deletion), and binding (self-signed key↔name, endorsable by others —
  web-of-trust, kept out of the knowledge graph where "speaks-for" would
  be a walled relation).
* **Keys are** ``s/<subject-hash>/<record-hash>`` — content-addressed set
  semantics (the same record staged twice is one record), subject-prefix
  lookup via the store's sorted ``keys(prefix)``, and **union merge** with
  no resolver at all: equal keys imply equal bytes by construction, so
  two provenance stores merge conflict-free and land on the same root
  from either direction.
* **Timestamps are part of the signed claim** — "K says it was Tuesday" —
  never load-bearing; re-asserting the same claim later is deliberately a
  *new* record (audit information).
* **Signing** is a duck-typed seam (``.address`` + ``.sign(bytes) → hex``):
  `KeySigner` provides real secp256k1/keccak signing through the same
  ``bee`` package the Swarm feed pointer uses (lazy import, optional —
  the `swarm` extra's chain), and ``verify_record`` checks any record
  against its ``author`` address. Tests may inject any signer; what the
  network should trust is the real one.

Module-level imports stay core-only (B1; recordstore and bee load lazily
inside functions — checked in tests/test_boundaries.py).

Deployment shape (agreed, §3): per-writer stores folded by explicit
choice — publish your provenance root beside your knowledge root as a
pair, merge only the stores you trust; spam control is admission by
reference, not quotas. The write surface (the MCP write path) is the
layer that couples knowledge writes to assertion records and `remove` to
retraction; this module only provides the records and the store.
"""

import hashlib

RECORD_VERSION = 1
RECORD_TYPES = ("assertion", "endorsement", "retraction", "binding")
_PREFIX = "s/"


def _canonical_bytes(obj) -> bytes:
    from recordstore import canonical_bytes
    return canonical_bytes(obj)


# --------------------------------------------------------------------------- #
# Subjects (claim-grain — canonical names in, opaque here)
# --------------------------------------------------------------------------- #

def below_subject(sub: str, sup: str) -> dict:
    """The claim ``sub ⊑ sup``, in canonical names."""
    return {"claim": "below", "sub": sub, "sup": sup}


def exists_subject(name: str) -> dict:
    """Node existence is the claim ``name ⊑ *``."""
    return below_subject(name, "*")


def binding_subject(key: str, name: str) -> dict:
    """The claim that `key` speaks for `name` (a relation — walled out of
    the knowledge graph, so it lives here as a speech act)."""
    return {"claim": "speaks-for", "key": key, "name": name}


def subject_hash(subject: dict) -> str:
    return hashlib.sha256(_canonical_bytes(subject)).hexdigest()


def operation_group(op: str, item: str, supers, basis) -> str:
    """The deterministic hash linking the several claims of one intentional
    act (`put(X, [A, B])`): same operation against the same basis, same
    group — whoever performs it."""
    return hashlib.sha256(_canonical_bytes(
        {"op": op, "item": item, "supers": sorted(supers),
         "basis": basis})).hexdigest()


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #

def record_payload_bytes(record: dict) -> bytes:
    """What the author signs: the record minus its signature."""
    return _canonical_bytes({k: v for k, v in record.items() if k != "sig"})


def record_id(record: dict) -> str:
    """Content address of the *signed* record: the same claim signed by two
    keys is two records; the identical record twice is one."""
    return hashlib.sha256(_canonical_bytes(record)).hexdigest()


def record_key(record: dict) -> str:
    return f"{_PREFIX}{subject_hash(record['subject'])}/{record_id(record)}"


class KeySigner:
    """Real signing: secp256k1 private key, eth-style address — the same
    key format the Swarm feed pointer uses (`bee_signer`), imported lazily
    so the core stays dependency-free."""

    def __init__(self, private_key_hex: str):
        from bee.swarm.keys import PrivateKey
        self._key = PrivateKey.from_hex(private_key_hex)
        self.address = str(self._key.public_key().address())

    def sign(self, data: bytes) -> str:
        return str(self._key.sign(data).to_hex())


def verify_record(record: dict) -> bool:
    """True iff the record's signature was made by ``record['author']``
    over the record's payload bytes. False for tampering or a wrong
    author; raises only on a malformed envelope."""
    from bee.swarm.keys import EthAddress, Signature, verify_signature
    try:
        signature = Signature.from_hex(record["sig"])
        author = EthAddress.from_hex(record["author"])
    except Exception:
        return False
    return bool(verify_signature(signature, record_payload_bytes(record),
                                 author))


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #

class ProvenanceStore:
    """Signed speech acts over a duck-typed RecordStore of its own — one
    per writer. `commit()` yields the provenance root that travels beside
    the knowledge root as a pair; `union(other_root)` folds a chosen
    peer's records in (conflict-free by construction)."""

    def __init__(self, record_store, signer=None):
        self._store = record_store
        self._signer = signer
        self._staged = 0

    @property
    def root(self):
        return self._store.root

    @property
    def author(self):
        return self._signer.address if self._signer else None

    # -- writing ----------------------------------------------------------- #

    def _add(self, record_type: str, subject: dict, basis, time=None,
             ext=None, **fields) -> dict:
        if self._signer is None:
            raise ValueError(
                "this provenance store has no signer — records are signed "
                "speech acts; construct with signer=KeySigner(<hex key>) "
                "(or any object with .address and .sign(bytes))")
        record = {"v": RECORD_VERSION, "type": record_type,
                  "subject": subject, "author": self._signer.address,
                  "basis": basis}
        if time is not None:
            record["time"] = time      # part of the signed claim, unverified
        record["ext"] = ext or {}
        record.update({k: v for k, v in fields.items() if v is not None})
        record["sig"] = self._signer.sign(record_payload_bytes(record))
        self._store.put(record_key(record), record)
        self._staged += 1
        return record

    def assert_claim(self, subject: dict, basis, origin: str = "asserted",
                     derived_from=None, time=None, group=None, ext=None):
        if origin not in ("asserted", "derived"):
            raise ValueError(f"origin must be asserted|derived, "
                             f"not {origin!r}")
        return self._add("assertion", subject, basis, time=time, ext=ext,
                         origin=origin, derived_from=derived_from,
                         group=group)

    def endorse(self, subject: dict, basis, time=None, ext=None):
        return self._add("endorsement", subject, basis, time=time, ext=ext)

    def retract(self, subject: dict, basis, time=None, ext=None):
        """"This key no longer stands behind this claim" — a speech act;
        the knowledge-level grow-only stance is untouched."""
        return self._add("retraction", subject, basis, time=time, ext=ext)

    def bind(self, name: str, basis, time=None, ext=None):
        """The self-signed key↔name link, endorsable by others."""
        return self._add("binding",
                         binding_subject(self.author, name), basis,
                         time=time, ext=ext)

    def commit(self):
        root = self._store.commit()
        self._staged = 0
        return root

    # -- reading ----------------------------------------------------------- #

    def records(self, subject: dict = None):
        """All records (sorted by key), or those about one subject."""
        prefix = _PREFIX if subject is None \
            else f"{_PREFIX}{subject_hash(subject)}/"
        for _key, record in self._store.items(prefix):
            yield record

    # -- merging (per-writer stores, folded by explicit choice) ------------- #

    def union(self, other_root):
        """Fold a chosen peer's provenance root in. Conflict-free by
        construction (a key is the hash of its record, so equal keys imply
        equal bytes) and direction-independent: both writers land on the
        byte-identical root. Requires a clean store — commit first."""
        if self._staged:
            raise ValueError("union with staged records — commit() first")
        if other_root is None or other_root == self.root:
            return self.root
        from recordstore import RecordStore
        if self.root is None:
            merged = other_root
        else:
            merged = RecordStore.merge(self._store.blobs, None,
                                       self.root, other_root)
        self._store = RecordStore(self._store.blobs, root=merged)
        return merged
