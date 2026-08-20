"""Deterministic authenticated encryption for record-store blobs — the
single-audience encrypted store (PACKS.md §14 item 3, second half;
PROJECTIONS.md §11's overlay composition assumes it; the category key graph
of `docs/plans/act-categories/DESIGN.md` later supplies this module's key
from an audience node, which is the two mechanisms' unification seam).

The one design fact everything follows from: **encryption must be
deterministic**, because the store is content-addressed. A random nonce
would make the same record encrypt differently on your two devices, so the
same knowledge would produce different refs, different tries, different
roots — G1 broken *within one audience*. So this uses AES-SIV (RFC 5297)
with no nonce: same key + same plaintext = same ciphertext, which keeps
convergence and dedup exactly as content addressing gives them, at the
documented price that equality of records is visible to whoever holds the
ciphertext (they already see blob sizes and counts; this is the standard
convergent-encryption trade, acceptable inside one audience).

What is protected: every blob the record store writes — records AND trie
nodes — so names, structure and payloads are ciphertext at rest; the root
ref addresses ciphertext. What is not: blob sizes, blob count, access
patterns, and record-equality. Certificates (`prove`/`verify_proof`) do not
work across the audience boundary: a proof carries trie bytes, which are
ciphertext here — you cannot prove the contents of a secret to someone who
cannot read it, and that is a property, not a gap.

The key: `derive_key(secret)` turns the `store_key` setting (any string — a
passphrase or a hex key, the seam does not care where key material comes
from, per the SwarmID forward-compatibility rule) into the 64-byte
AES-SIV-512 key via two domain-separated SHA-256 halves. Derivation is
versioned in the domain strings; changing it is a store-format MAJOR.

Module-level imports are stdlib-only (B1 discipline): pycryptodome loads
lazily, through the `crypto` extra's teaching error.
"""

import hashlib
import json
import os

_VERSION = b"\x01"
_DOMAIN = b"ontodag-enc-store-v1"
MARKER = "encrypted"          # marker file name, beside blobs/ and root


def derive_key(secret):
    """The 64-byte AES-SIV-512 key for a `store_key` secret (any string)."""
    if not secret:
        raise ValueError("an encrypted store needs a non-empty store_key")
    raw = secret.encode("utf-8")
    return (hashlib.sha256(_DOMAIN + b"|enc|" + raw).digest()
            + hashlib.sha256(_DOMAIN + b"|mac|" + raw).digest())


def keycheck(key):
    """A short digest of the derived key, stored in the marker so a wrong
    key refuses at open time instead of surfacing as garbage records."""
    return hashlib.sha256(_DOMAIN + b"|check|" + key).hexdigest()[:32]


def _aes():
    from ontodag._extras import require
    require("Crypto", "crypto", "an encrypted store")
    from Crypto.Cipher import AES
    return AES


class EncryptedBytesStore:
    """A BytesStore wrapper: ciphertext through the inner store.

    Refs are the inner store's refs OF THE CIPHERTEXT — content addressing
    and structural sharing keep working, over encrypted bytes. Duck-typed
    like every store seam in this family; bulk methods are provided only
    when the inner store has them, so capability detection stays honest.
    """

    def __init__(self, inner, key):
        self._inner = inner
        self._key = key
        self._aes = _aes()                 # fail at construction, loudly
        # Mirror the inner store's bulk surface exactly: capability
        # detection elsewhere is hasattr-based, so the wrapper must not
        # advertise what its inner store cannot do.
        # The bulk contract (recordstore BytesStore): put_many(datas) ->
        # list of refs; get_many(refs) -> DICT of ref -> bytes.
        if hasattr(inner, "put_many"):
            self.put_many = lambda datas: inner.put_many(
                [self._encrypt(d) for d in datas])
        if hasattr(inner, "get_many"):
            self.get_many = lambda refs: {
                ref: self._decrypt(blob)
                for ref, blob in inner.get_many(refs).items()}

    def _encrypt(self, data):
        cipher = self._aes.new(self._key, self._aes.MODE_SIV)
        ciphertext, tag = cipher.encrypt_and_digest(data)
        return _VERSION + tag + ciphertext

    def _decrypt(self, blob):
        if not blob[:1] == _VERSION:
            raise ValueError("not an ontodag-encrypted blob (or a future "
                             "format this version cannot read)")
        cipher = self._aes.new(self._key, self._aes.MODE_SIV)
        return cipher.decrypt_and_verify(blob[17:], blob[1:17])

    def put(self, data):
        return self._inner.put(self._encrypt(data))

    def get(self, ref):
        return self._decrypt(self._inner.get(ref))


def read_marker(directory):
    """The store's encryption marker, or None for a plaintext store."""
    try:
        with open(os.path.join(directory, MARKER), encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, NotADirectoryError):
        # NotADirectoryError: `directory` is a plain .od FILE store — those
        # have no marker (and no encryption) by construction.
        return None


def write_marker(directory, key):
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, MARKER), "w", encoding="utf-8") as fh:
        json.dump({"format": "ontodag-encrypted-store", "version": 1,
                   "keycheck": keycheck(key)}, fh)
        fh.write("\n")


def check_key(marker, key, describe):
    """Refuse a wrong key at open time, in the store's own terms."""
    if marker.get("version") != 1:
        raise ValueError(
            f"{describe} uses encrypted-store format "
            f"v{marker.get('version')}, which this version cannot read")
    if marker.get("keycheck") != keycheck(key):
        raise ValueError(
            f"the configured store_key does not open {describe} "
            f"(wrong key — the store refuses rather than serving garbage)")
