"""The access-control primitives (ontodag.act).

What must hold: the grantee-entry derivation is Bee's ACT entry bit for
bit (vectors generated from Bee v2.8.1's Go packages), with coincurve and
with the pure-Python curve alike; a token opens only with its parent's key
and for its own child; tokens do not leak (no two-time pad, across
children or across a rotation); wrapping is deterministic; and the
encstore seam derives a store key per node key. What a reader sees, and
revocation, are the key plan's: tests/test_keyplan.py.

Gated on the `act` extra (coincurve + pycryptodome); skips otherwise.
"""

import random
import unittest

try:
    import coincurve  # noqa: F401
    from Crypto.Hash import keccak  # noqa: F401
    HAVE_ACT = True
except ImportError:
    HAVE_ACT = False

from recordstore import MemoryBytesStore


def _seeded_rng(seed):
    r = random.Random(seed)
    return lambda n: bytes(r.getrandbits(8) for _ in range(n))


def _priv(seed: int) -> bytes:
    return seed.to_bytes(32, "big")


@unittest.skipUnless(HAVE_ACT, "needs the act extra (coincurve, pycryptodome)")
class TestBeeCompatibility(unittest.TestCase):
    """The spike's vectors, now permanent: Bee's getKeys + stream cipher."""

    ACCESS_KEY = bytes.fromhex(
        "8abf1502f557f15026716030fb6384792583daf39608a3cd02ff2f47e9bc6e49")
    VECTORS = [
        dict(grantee=42, publisher=7, x_len=32,
             publisher_pub="025cbdf0646e5db4eaa398f365f2ea7a0e3d419b7e033"
                           "0e39ce92bddedcac4f9bc",
             lookup="90520a9c134c04fbe88dcc47d5809b8f2122f723b9680cfc"
                    "05789a75f9ccfaf9",
             wrap="02a5e279ddd85943492047b8fd22077fb1c951e67f39f0"
                  "4d1913b73efcf3d83b",
             wrapped_ak="86c90a1dd419789ae328bfda1fe9ccf58328396f4c7964d4"
                        "4b6ff7bde29e8b09"),
        # x has a leading zero byte: Go's big.Int.Bytes() strips it
        dict(grantee=177, publisher=100177, x_len=31,
             publisher_pub="029acb593230e2a6ef975fff73554cce809a88ebd1d2a7"
                           "7d7f7fbf6eecba4943d2",
             lookup="499869b38e436ca280bd7ddcb5ab2b6340c48bcf0b7c1c40"
                    "5a4363edefe45cb3",
             wrap="190a99ce393e6b01aea02efdf8e3897e523c74c7c9ad35"
                  "04b8619fc012557eb0",
             wrapped_ak="f248cba852b38e8f4cce943c651b59b99d412d424c6d0237"
                        "36465c63b69ed464"),
    ]
    # Bee's own encryption_test.go vector, by digest
    UPSTREAM_DIGEST = bytes.fromhex(
        "eab9772cbbd2b8dacaccb949a6539d856b707251894ce1642717b5912b7296fb")

    def test_vectors_from_bee_v2_8_1(self):
        from ontodag import act
        for v in self.VECTORS:
            gpriv, ppriv = _priv(v["grantee"]), _priv(v["publisher"])
            ppub = act.public_key(ppriv)
            self.assertEqual(ppub.hex(), v["publisher_pub"])
            self.assertEqual(len(act.shared_x(gpriv, ppub)), v["x_len"])
            lookup, wrap = act.act_keys(gpriv, ppub)
            self.assertEqual((lookup.hex(), wrap.hex()), (v["lookup"], v["wrap"]))
            wrapped = act.stream_transform(wrap, self.ACCESS_KEY)
            self.assertEqual(wrapped.hex(), v["wrapped_ak"])
            self.assertEqual(act.stream_transform(wrap, wrapped), self.ACCESS_KEY)
            # ECDH is symmetric: the grantee derives what the publisher wrapped
            self.assertEqual(act.act_keys(ppriv, act.public_key(gpriv)),
                             (lookup, wrap))
        self.assertEqual(
            act.keccak256(act.stream_transform(self.ACCESS_KEY, bytes(4096))),
            self.UPSTREAM_DIGEST)

    def test_the_pure_python_curve_meets_bees_vectors_too(self):
        # Where coincurve can't install (Pyodide), act falls back to a
        # pure-Python secp256k1; it must give the same bytes, the 31-byte
        # x-coordinate included
        from unittest import mock
        from ontodag import act
        with mock.patch.object(act, "_secp256k1", lambda: None):
            self.test_vectors_from_bee_v2_8_1()
        rnd = random.Random(5)
        for _ in range(50):
            a = rnd.getrandbits(255).to_bytes(32, "big")
            b = rnd.getrandbits(255).to_bytes(32, "big")
            self.assertEqual(act._py_public_key(a), act.public_key(a))
            self.assertEqual(act._py_shared_x(a, act.public_key(b)),
                             act.shared_x(a, act.public_key(b)))

    def test_the_pure_python_curve_refuses_what_coincurve_refuses(self):
        from ontodag import act
        with self.assertRaises(ValueError):
            act._py_public_key(bytes(32))                       # zero secret
        with self.assertRaises(ValueError):
            act._py_shared_x(_priv(1), b"\x02" + bytes(32))     # x = 0: off the curve
        with self.assertRaises(ValueError):
            act._py_shared_x(_priv(1), b"\x05" + bytes(32))     # not a key encoding


def _xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


@unittest.skipUnless(HAVE_ACT, "needs the act extra (coincurve, pycryptodome)")
class TestTokens(unittest.TestCase):
    """Format 2. Found 2026-10-05: a format-1 token was K_v XOR KS(K_u, v),
    so when v rotated under a parent that did not, the re-minted token
    reused the keystream and the two tokens XORed to K_v_old XOR K_v_new:
    anyone who kept the old key read the new one off the public store.
    The keyplan-level version of these checks, over real rotations, is in
    tests/test_keyplan.py (TestLazyRevocation)."""

    def test_a_token_opens_only_with_its_parents_key(self):
        from ontodag import act
        k_u, k_v, wrong = _seeded_rng(5)(32), _seeded_rng(6)(32), _seeded_rng(8)(32)
        token = act.wrap(k_u, "v", k_v)
        self.assertEqual(len(token), 2 * act.KEY_LEN)
        self.assertEqual(act.unwrap(k_u, "v", token), k_v)
        with self.assertRaises(ValueError):
            act.unwrap(wrong, "v", token)
        with self.assertRaises(ValueError):                 # filed under another child
            act.unwrap(k_u, "w", token)
        with self.assertRaises(ValueError):                 # truncated
            act.unwrap(k_u, "v", token[:-1])

    def test_wrap_is_deterministic(self):
        # equal keys publish equal tokens, so a token store has a canonical root
        from ontodag import act
        k_u, k_v = _seeded_rng(1)(32), _seeded_rng(2)(32)
        self.assertEqual(act.wrap(k_u, "v", k_v), act.wrap(k_u, "v", k_v))

    def test_a_rotation_reuses_no_keystream(self):
        # one parent key, one child id, the child's key rotated: the change
        # in the token must not be the change in the key
        from ontodag import act
        rnd = _seeded_rng(11)
        for _ in range(50):
            k_u, old, new = rnd(32), rnd(32), rnd(32)
            t_old, t_new = act.wrap(k_u, "v", old), act.wrap(k_u, "v", new)
            self.assertNotEqual(_xor(t_old[act.KEY_LEN:], t_new[act.KEY_LEN:]),
                                _xor(old, new))

    def test_two_children_share_no_keystream(self):
        from ontodag import act
        rnd = _seeded_rng(12)
        for _ in range(50):
            k_u, a, b = rnd(32), rnd(32), rnd(32)
            t_a, t_b = act.wrap(k_u, "a", a), act.wrap(k_u, "b", b)
            self.assertNotEqual(_xor(t_a[act.KEY_LEN:], t_b[act.KEY_LEN:]), _xor(a, b))


@unittest.skipUnless(HAVE_ACT, "needs the act extra (coincurve, pycryptodome)")
class TestTheEncstoreSeam(unittest.TestCase):
    def test_a_node_key_opens_its_store_and_no_other(self):
        from ontodag import act
        from ontodag.encstore import EncryptedBytesStore
        try:
            from Crypto.Cipher import AES  # noqa: F401
        except ImportError:
            self.skipTest("needs the crypto extra")
        k, other = _seeded_rng(3)(32), _seeded_rng(4)(32)
        self.assertEqual(len(act.store_key_for(k)), 64)
        self.assertNotEqual(act.store_key_for(k), act.store_key_for(other))
        blobs = MemoryBytesStore()
        ref = EncryptedBytesStore(blobs, act.store_key_for(k)).put(b"the design spec")
        self.assertEqual(EncryptedBytesStore(blobs, act.store_key_for(k)).get(ref),
                         b"the design spec")
        with self.assertRaises(Exception):
            EncryptedBytesStore(blobs, act.store_key_for(other)).get(ref)


class TestBoundary(unittest.TestCase):
    def test_module_imports_stay_stdlib(self):
        import sys
        for mod in ("coincurve", "Crypto"):
            sys.modules.pop(mod, None)
        import importlib
        import ontodag.act as act
        importlib.reload(act)
        self.assertNotIn("coincurve", sys.modules)
        self.assertNotIn("Crypto", sys.modules)
        # and the store-key seam needs no crypto at all
        self.assertEqual(len(act.store_key_for(bytes(32))), 64)


if __name__ == "__main__":
    unittest.main()
