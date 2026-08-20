#!/usr/bin/env python3
"""act-categories crypto spike (PACKS.md §14 item 3½): reproduce Bee's ACT
deterministic crypto in Python, pinned bit-for-bit against vectors generated
from Bee's own Go packages at v2.8.1 (`bee/actvectors_main/main.go`).

This retires the one real unknown in `docs/plans/act-categories/DESIGN.md`
Phase 1 (§5): the ECDH → Keccak → stream-cipher conventions where the Python
and Go implementations must agree exactly. It is a *spike* — throwaway proof
that the primitives line up — not the feature. Run it directly:

    python3 experiments/act_crypto_spike.py

Deps: coincurve (secp256k1), pycryptodome (Keccak). Both are in the `swarm`
extra's transitive set; this file imports them lazily and skips with a clear
message if absent, so it never breaks a bare checkout.

What it pins, from Bee's `pkg/accesscontrol` and `pkg/encryption`:

  * ECDH shared secret = the x-coordinate of grantee_priv * publisher_pub,
    as **raw big-endian bytes with leading zeros STRIPPED** — Go's
    `big.Int.Bytes()`. Vector 2 is chosen so that x is 31 bytes, which is
    exactly the trap the design doc flagged (§5, "byte ordering of the ECDH
    x-coordinate"): a fixed-32 encoding would diverge here and nowhere else.
  * getKeys(pub) = [ Keccak256(x || 0x00), Keccak256(x || 0x01) ] — the
    lookup key and the access-key-decryption key.
  * The stream cipher (encryption.go transform): per 32-byte segment,
    segmentKey = Keccak256(Keccak256(key || LE_uint32(counter))), then XOR;
    counter starts at 0 and increments per segment. Used to wrap the access
    key (getKeys[1]) and to encrypt a 64-byte reference (accessKey).
"""

import sys


def _need(mod, hint):
    try:
        return __import__(mod)
    except ImportError:
        print(f"SKIP: {mod} not installed ({hint})")
        sys.exit(0)


coincurve = _need("coincurve", "pip install coincurve")
_Crypto = _need("Crypto", "pip install pycryptodome")
from Crypto.Hash import keccak  # noqa: E402


def keccak256(data: bytes) -> bytes:
    return keccak.new(digest_bits=256, data=data).digest()


def shared_x(grantee_priv: bytes, publisher_pub: bytes) -> bytes:
    """ECDH x-coordinate as Go's big.Int.Bytes(): big-endian, no leading
    zeros. coincurve's ECDH hashes the point by default, so we do the raw
    scalar-mult ourselves and take the uncompressed X."""
    pub = coincurve.PublicKey(publisher_pub)
    point = pub.multiply(grantee_priv)                 # EC scalar mult
    uncompressed = point.format(compressed=False)      # 0x04 || X(32) || Y(32)
    x = uncompressed[1:33]
    return x.lstrip(b"\x00")                            # big.Int.Bytes()


def get_keys(grantee_priv: bytes, publisher_pub: bytes):
    x = shared_x(grantee_priv, publisher_pub)
    return keccak256(x + b"\x00"), keccak256(x + b"\x01")


def stream_transform(key: bytes, data: bytes, init_ctr: int = 0) -> bytes:
    """encryption.go: XOR each 32-byte segment with
    Keccak256(Keccak256(key || LE32(ctr))), ctr incrementing per segment."""
    out = bytearray()
    for seg in range(0, len(data), 32):
        chunk = data[seg:seg + 32]
        ctr = (seg // 32) + init_ctr
        ctr_hash = keccak256(key + ctr.to_bytes(4, "little"))
        segment_key = keccak256(ctr_hash)
        out += bytes(a ^ b for a, b in zip(chunk, segment_key))
    return bytes(out)


def priv_from_seed(seed: int) -> bytes:
    return seed.to_bytes(32, "big")


def pub_from_priv(priv: bytes) -> bytes:
    return coincurve.PublicKey.from_valid_secret(priv).format(compressed=True)


# Vectors emitted by bee/actvectors_main/main.go against Bee v2.8.1.
ACCESS_KEY = bytes.fromhex(
    "8abf1502f557f15026716030fb6384792583daf39608a3cd02ff2f47e9bc6e49")
REF = bytes.fromhex(
    "39a5ea87b141fe44aa609c3327ecd896c0e2122897f5f4bbacf74db1033c5559"
    "0000000000000000000000000000000000000000000000000000000000000001")

VECTORS = [
    dict(name="vector1", grantee=42, publisher=7,
         shared_x_len=32,
         publisher_pub="025cbdf0646e5db4eaa398f365f2ea7a0e3d419b7e033"
                       "0e39ce92bddedcac4f9bc",
         shared_x="b1d6ff90f1776329c097793d9116ce71cc3cf4ce06a9402b"
                  "2ae7f6cb96e73ce9",
         lookup_key="90520a9c134c04fbe88dcc47d5809b8f2122f723b9680cfc"
                    "05789a75f9ccfaf9",
         ak_decrypt_key="02a5e279ddd85943492047b8fd22077fb1c951e67f39f0"
                        "4d1913b73efcf3d83b",
         wrapped_ak="86c90a1dd419789ae328bfda1fe9ccf58328396f4c7964d4"
                    "4b6ff7bde29e8b09",
         encrypted_ref="0c846d288bc5c3a86c5c7095eced32af1b2d65e2675d03be"
                       "593440e473789bb59392b94a79376f1e5c10cd0c0f2a98e5"
                       "353bf22b3ea4fdac6677ee553dec192f"),
    dict(name="vector2 (short x)", grantee=177, publisher=100177,
         shared_x_len=31,
         publisher_pub="029acb593230e2a6ef975fff73554cce809a88ebd1d2a7"
                       "7d7f7fbf6eecba4943d2",
         shared_x="ca73f73ebfe84d4bf2d1b665445fdb431e54c9013698a09e"
                  "115ae38e779dd5",
         lookup_key="499869b38e436ca280bd7ddcb5ab2b6340c48bcf0b7c1c40"
                    "5a4363edefe45cb3",
         ak_decrypt_key="190a99ce393e6b01aea02efdf8e3897e523c74c7c9ad35"
                        "04b8619fc012557eb0",
         wrapped_ak="f248cba852b38e8f4cce943c651b59b99d412d424c6d0237"
                    "36465c63b69ed464",
         encrypted_ref="0c846d288bc5c3a86c5c7095eced32af1b2d65e2675d03be"
                       "593440e473789bb59392b94a79376f1e5c10cd0c0f2a98e5"
                       "353bf22b3ea4fdac6677ee553dec192f"),
]


def check(label, got, expected):
    ok = got == expected
    print(f"  [{'ok' if ok else 'FAIL'}] {label}")
    if not ok:
        print(f"        got      {got.hex() if isinstance(got, bytes) else got}")
        print(f"        expected {expected.hex() if isinstance(expected, bytes) else expected}")
    return ok


# Bee's own upstream-authored vector (encryption_test.go,
# TestEncryptDataLengthEqualsPadding): testKey over 4096 zero bytes,
# padding=4096, initCtr=0. The 4096-byte expected ciphertext is pinned here
# by its Keccak256 digest to keep this file readable; the full hex lives in
# bee/pkg/encryption/encryption_test.go.
UPSTREAM_KEY = bytes.fromhex(
    "8abf1502f557f15026716030fb6384792583daf39608a3cd02ff2f47e9bc6e49")
UPSTREAM_DIGEST = bytes.fromhex(
    "eab9772cbbd2b8dacaccb949a6539d856b707251894ce1642717b5912b7296fb")


def main():
    all_ok = True
    print("upstream vector (Bee's own encryption_test.go):")
    all_ok &= check("4096-byte zero-plaintext ciphertext digest",
                    keccak256(stream_transform(UPSTREAM_KEY, bytes(4096))),
                    UPSTREAM_DIGEST)
    print()
    for v in VECTORS:
        print(v["name"] + ":")
        gpriv = priv_from_seed(v["grantee"])
        ppriv = priv_from_seed(v["publisher"])
        ppub = pub_from_priv(ppriv)

        all_ok &= check("publisher pubkey (compressed)",
                        ppub, bytes.fromhex(v["publisher_pub"]))
        x = shared_x(gpriv, ppub)
        all_ok &= check(f"shared x is {v['shared_x_len']} bytes "
                        f"(big.Int.Bytes stripping)",
                        len(x), v["shared_x_len"])
        all_ok &= check("shared x bytes", x, bytes.fromhex(v["shared_x"]))

        lookup, ak_decrypt = get_keys(gpriv, ppub)
        all_ok &= check("lookup key = Keccak(x||0)",
                        lookup, bytes.fromhex(v["lookup_key"]))
        all_ok &= check("ak-decrypt key = Keccak(x||1)",
                        ak_decrypt, bytes.fromhex(v["ak_decrypt_key"]))

        wrapped = stream_transform(ak_decrypt, ACCESS_KEY)
        all_ok &= check("wrapped access key (stream cipher)",
                        wrapped, bytes.fromhex(v["wrapped_ak"]))
        # Unwrap round-trips (the cipher is its own inverse):
        all_ok &= check("unwrap round-trips to the access key",
                        stream_transform(ak_decrypt, wrapped), ACCESS_KEY)

        enc_ref = stream_transform(ACCESS_KEY, REF)
        all_ok &= check("encrypted reference (2 segments)",
                        enc_ref, bytes.fromhex(v["encrypted_ref"]))
        all_ok &= check("decrypt round-trips to the reference",
                        stream_transform(ACCESS_KEY, enc_ref), REF)
        print()

    print("SPIKE RESULT:",
          "all vectors match Bee v2.8.1 — the crypto conventions line up"
          if all_ok else "MISMATCH — a convention differs, see FAILs above")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
