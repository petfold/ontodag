"""The primitives of category-based access control, Bee-compatible.

`ontodag.keyplan` is the access-control API: what a store shares, as keys
(docs/plans/SHARING_ON_SWARM.md). This module keeps the primitives it is
built from. The hand-maintained key graph that lived here (`KeyGraph`,
`Resolver`, `align`; act-categories Phase 1, 0.19–0.29) was retired in
0.30: the key plan derives the same tokens from the store, and two ways to
grant access were one too many (ROLES.md §9).

What is Bee-compatible here, bit for bit (pinned against vectors from Bee
v2.8.1's own Go packages in `tests/test_act.py`): the **grantee entry**. A
person's way in is exactly an ACT entry: `lookup = Keccak(ECDH_x || 0)`,
wrap key = `Keccak(ECDH_x || 1)`, value = Bee's stream cipher over the
key it opens (`act_keys`, `stream_transform`). So a person holds one
secp256k1 key, the same kind `bee_signer` is.

What is ours: the **tokens**. Bee has no notion of node-to-node
rekeying. A token is a public check value of the child's key,
`check(K_v) = Keccak(domain || K_v)`, followed by the same stream cipher
over K_v under the key `Keccak(K_u || domain || id(v) || check(K_v))`
(`wrap`, `unwrap`). The cipher is a keystream XOR, so no keystream may
ever encrypt two different keys, or their XOR leaks (a two-time pad).
Binding the keystream to `id(v)` keeps two children apart; binding it to
the check keeps two keys of one child apart. That second binding is what
format 1 (ontodag 0.19–0.28) lacked: when v was rotated under a parent
that kept its key, the re-minted token reused the keystream, so anyone who
kept the old key read the new one off the public store (found
2026-10-05). `unwrap` verifies the check, so a wrong key fails instead of
yielding garbage. The derivation is deterministic, so equal keys publish
identical tokens, which lets a token store have a canonical root.

**The seam into encrypted stores:** `store_key_for(K)` is a 64-byte
AES-SIV key for `ontodag.encstore.EncryptedBytesStore`, derived from a
node key.

Module-level imports are stdlib only; coincurve (secp256k1) and
pycryptodome (Keccak) are reached lazily through the `act` extra. Where
coincurve can't install (Pyodide has no wheel for it), a pure-Python
secp256k1 stands in: slower and not constant-time, so coincurve is used
wherever it is present.
"""

import hashlib

from ontodag._extras import require

ACT_VERSION = 2
KEY_LEN = 32

_TOKEN_DOMAIN = b"|ontodag-act-token-v2|"
_CHECK_DOMAIN = b"ontodag-act-key-check-v2|"
_STORE_KEY_DOMAIN = b"ontodag-act-store-key-v1"


# --------------------------------------------------------------------------- #
# Primitives — Bee's conventions, exactly (pkg/accesscontrol, pkg/encryption)
# --------------------------------------------------------------------------- #

def _coincurve():
    return require("coincurve", "act", "category-based access control")


def keccak256(data: bytes) -> bytes:
    require("Crypto", "act", "category-based access control")
    from Crypto.Hash import keccak
    return keccak.new(digest_bits=256, data=data).digest()


def _secp256k1():
    """coincurve, or None where it can't be installed (Pyodide: it has no
    pure-Python wheel). Then the pure-Python curve below stands in."""
    try:
        return _coincurve()
    except ImportError:
        return None


def public_key(private_key: bytes) -> bytes:
    """Compressed secp256k1 public key (33 bytes) for a 32-byte secret."""
    cc = _secp256k1()
    if cc is None:
        return _py_public_key(private_key)
    return cc.PublicKey.from_valid_secret(private_key).format(compressed=True)


def shared_x(private_key: bytes, other_public: bytes) -> bytes:
    """ECDH x-coordinate as Go's `big.Int.Bytes()`: big-endian, leading
    zeros STRIPPED (so it is occasionally 31 bytes — the trap the spike's
    second vector exists for)."""
    cc = _secp256k1()
    if cc is None:
        return _py_shared_x(private_key, other_public)
    point = cc.PublicKey(other_public).multiply(private_key)
    return point.format(compressed=False)[1:33].lstrip(b"\x00")


# --------------------------------------------------------------------------- #
# secp256k1 in pure Python: the fallback for runtimes without coincurve
# (Pyodide, so a browser can walk a key graph). It is NOT constant-time:
# prefer coincurve wherever it installs. Pinned to coincurve by the tests.
# --------------------------------------------------------------------------- #

_P = 2 ** 256 - 2 ** 32 - 977
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
      0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _double(X, Y, Z):
    if Z == 0 or Y == 0:
        return (0, 1, 0)
    S = 4 * X * Y * Y % _P
    M = 3 * X * X % _P
    X3 = (M * M - 2 * S) % _P
    Y3 = (M * (S - X3) - 8 * pow(Y, 4, _P)) % _P
    return X3, Y3, 2 * Y * Z % _P


def _add(A, B):
    X1, Y1, Z1 = A
    X2, Y2, Z2 = B
    if Z1 == 0:
        return B
    if Z2 == 0:
        return A
    Z1Z1, Z2Z2 = Z1 * Z1 % _P, Z2 * Z2 % _P
    U1, U2 = X1 * Z2Z2 % _P, X2 * Z1Z1 % _P
    S1, S2 = Y1 * Z2 * Z2Z2 % _P, Y2 * Z1 * Z1Z1 % _P
    if U1 == U2:
        return _double(X1, Y1, Z1) if S1 == S2 else (0, 1, 0)
    H, R = (U2 - U1) % _P, (S2 - S1) % _P
    HH = H * H % _P
    HHH, V = H * HH % _P, U1 * HH % _P
    X3 = (R * R - HHH - 2 * V) % _P
    return X3, (R * (V - X3) - S1 * HHH) % _P, H * Z1 * Z2 % _P


def _multiply(k, point):
    if not 0 < k < _N:
        raise ValueError("not a valid secp256k1 secret")
    acc, base = (0, 1, 0), (point[0], point[1], 1)
    for bit in bin(k)[2:]:
        acc = _double(*acc)
        if bit == "1":
            acc = _add(acc, base)
    X, Y, Z = acc
    if Z == 0:
        raise ValueError("the product is the point at infinity")
    zi = pow(Z, -1, _P)
    return X * zi * zi % _P, Y * zi * zi * zi % _P


def _point(public: bytes):
    if len(public) == 65 and public[0] == 4:
        x, y = int.from_bytes(public[1:33], "big"), int.from_bytes(public[33:], "big")
    elif len(public) == 33 and public[0] in (2, 3):
        x = int.from_bytes(public[1:], "big")
        y = pow((pow(x, 3, _P) + 7) % _P, (_P + 1) // 4, _P)
        if (y & 1) != (public[0] & 1):
            y = _P - y
    else:
        raise ValueError("not a secp256k1 public key")
    if (y * y - pow(x, 3, _P) - 7) % _P:
        raise ValueError("not a point on secp256k1")
    return x, y


def _py_public_key(private_key: bytes) -> bytes:
    x, y = _multiply(int.from_bytes(private_key, "big"), _G)
    return bytes([2 + (y & 1)]) + x.to_bytes(32, "big")


def _py_shared_x(private_key: bytes, other_public: bytes) -> bytes:
    x, _y = _multiply(int.from_bytes(private_key, "big"), _point(other_public))
    return x.to_bytes(32, "big").lstrip(b"\x00")


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
# Ours: tokens, and the store-key seam
# --------------------------------------------------------------------------- #

def key_check(k: bytes) -> bytes:
    """A public check value for a node key: what a token's keystream is
    bound to, and what `unwrap` verifies against (see module doc)."""
    return keccak256(_CHECK_DOMAIN + k)


def token_key(k_u: bytes, v_id: str, check: bytes) -> bytes:
    return keccak256(k_u + _TOKEN_DOMAIN + v_id.encode("ascii") + check)


def wrap(k_u: bytes, v_id: str, k_v: bytes) -> bytes:
    """T(u -> v): the check of K_v (32 bytes), then K_v under a keystream
    bound to the edge and to that check (32 bytes)."""
    check = key_check(k_v)
    return check + stream_transform(token_key(k_u, v_id, check), k_v)


def unwrap(k_u: bytes, v_id: str, token: bytes) -> bytes:
    """K_v from T(u -> v). `ValueError` unless K_u is u's key and the token
    was minted for v."""
    check, body = token[:KEY_LEN], token[KEY_LEN:]
    k_v = stream_transform(token_key(k_u, v_id, check), body)
    if len(k_v) != KEY_LEN or key_check(k_v) != check:
        raise ValueError("this token does not open with that key")
    return k_v


def store_key_for(k: bytes) -> bytes:
    """The 64-byte AES-SIV key `EncryptedBytesStore` takes, derived from a
    node (or audience) key: the encstore seam."""
    return (hashlib.sha256(_STORE_KEY_DOMAIN + b"|enc|" + k).digest()
            + hashlib.sha256(_STORE_KEY_DOMAIN + b"|mac|" + k).digest())
