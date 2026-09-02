"""Category-based access control (ontodag.act, act-categories Phase 1).

What must hold: the grantee entry is Bee's ACT entry bit for bit (vectors
generated from Bee v2.8.1's Go packages); a reader decrypts exactly what
a directed token path reaches (oracle: brute-force reachability over
random two-sided graphs); document categories carry topic not audience
(the §2.2 trap does not bite); tokens do not leak (no two-time pad);
revocation is forward-only and rotates categories not documents; equal
keys publish equal stores (canonical root); the audience key is
order-free; and the encstore seam encrypts for the audience only.

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

from recordstore import MemoryBytesStore, RecordStore

import ontodag


def _store():
    return RecordStore(MemoryBytesStore())


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

    def test_a_grantee_entry_is_an_act_entry(self):
        # What KeyGraph.grant publishes is exactly lookup -> Enc(wrap, K_leaf)
        from ontodag import act
        store = _store()
        graph = act.KeyGraph(store, org_private_key=_priv(7), rng=_seeded_rng(1))
        alice = _priv(42)
        graph.grant("alice", act.public_key(alice))
        lookup, wrap = act.act_keys(alice, act.public_key(_priv(7)))
        entry = store.get(act.GRANT_PREFIX + lookup.hex())
        self.assertEqual(act.stream_transform(wrap, bytes.fromhex(entry["wrapped"])),
                         graph.key("alice"))


def _org(seed=1):
    """The DESIGN.md §2.2 picture."""
    from ontodag import act
    store = _store()
    graph = act.KeyGraph(store, org_private_key=_priv(7), rng=_seeded_rng(seed))
    graph.link("alice", "eng-dept"); graph.link("eng-dept", "company")
    graph.link("bob", "sales-dept"); graph.link("sales-dept", "company")
    graph.link("eng-documents", "design-specs"); graph.link("design-specs", "doc-57")
    graph.link("eng-documents", "doc-42")
    graph.link("company-docs", "handbook")
    graph.link("eng-dept", "eng-documents")          # bridge
    graph.link("company", "company-docs")            # bridge
    graph.grant("alice", act.public_key(_priv(42)))
    graph.grant("bob", act.public_key(_priv(43)))
    return store, graph


@unittest.skipUnless(HAVE_ACT, "needs the act extra (coincurve, pycryptodome)")
class TestReachabilityIsAccess(unittest.TestCase):
    def test_the_design_picture(self):
        from ontodag import act
        store, graph = _org()
        alice = act.Resolver(store, _priv(42))
        bob = act.Resolver(store, _priv(43))
        for doc in ("doc-42", "doc-57", "handbook"):
            self.assertTrue(alice.can_read(doc), doc)
            self.assertEqual(alice.key_for(doc), graph.key(doc))
        self.assertTrue(bob.can_read("handbook"))
        self.assertFalse(bob.can_read("doc-42"))      # topic, not audience
        self.assertFalse(bob.can_read("eng-documents"))
        with self.assertRaises(act.AccessDenied):
            bob.key_for("doc-57")
        # nobody walks against the arrows: alice cannot derive sales
        self.assertFalse(alice.can_read("sales-dept"))
        self.assertFalse(alice.can_read("bob"))
        # a stranger holds nothing
        self.assertEqual(act.Resolver(store, _priv(99)).reachable_ids(), set())

    def test_the_audience_trap_is_a_modeling_rule_not_a_bug(self):
        # §2.2: if "departmental documents" were filed UNDER "company docs",
        # every company reader would get them. The construction does exactly
        # what the tokens say — the test pins that the rule is load-bearing.
        from ontodag import act
        store, graph = _org()
        graph.link("company-docs", "eng-documents")   # the mistake
        self.assertTrue(act.Resolver(store, _priv(43)).can_read("doc-42"))

    def test_random_graphs_against_a_reachability_oracle(self):
        from ontodag import act
        for seed in range(12):
            r = random.Random(seed)
            store = _store()
            graph = act.KeyGraph(store, org_private_key=_priv(7), rng=_seeded_rng(seed))
            names = [f"n{i}" for i in range(14)]
            edges = set()
            for _ in range(22):
                u, v = r.sample(names, 2)
                edges.add((u, v))
                graph.link(u, v)
            people = r.sample(names, 3)
            keys = {p: _priv(100 + i) for i, p in enumerate(people)}
            for p, k in keys.items():
                graph.grant(p, act.public_key(k))
            graph.commit()
            for p, k in keys.items():
                expected = set()
                frontier = [p]
                while frontier:
                    cur = frontier.pop()
                    for (u, v) in edges:
                        if u == cur and v not in expected:
                            expected.add(v); frontier.append(v)
                expected.add(p)
                resolver = act.Resolver(store, k)
                got = {n for n in names if resolver.can_read(n)}
                self.assertEqual(got, expected, (seed, p))
                for n in expected:
                    self.assertEqual(resolver.key_for(n), graph.key(n))

    def test_tokens_from_one_node_are_not_a_two_time_pad(self):
        from ontodag import act
        k_u, k_v1, k_v2 = _seeded_rng(5)(32), _seeded_rng(6)(32), _seeded_rng(7)(32)
        t1 = act.wrap(k_u, act.node_id("v1"), k_v1)
        t2 = act.wrap(k_u, act.node_id("v2"), k_v2)
        xor = bytes(a ^ b for a, b in zip(t1, t2))
        self.assertNotEqual(xor, bytes(a ^ b for a, b in zip(k_v1, k_v2)))


@unittest.skipUnless(HAVE_ACT, "needs the act extra (coincurve, pycryptodome)")
class TestRevocationAndEpochs(unittest.TestCase):
    def test_revoke_is_forward_only_and_spares_documents(self):
        from ontodag import act
        store, graph = _org()
        before = graph.commit()
        old_doc_key = graph.key("doc-42")
        rotated = graph.revoke("alice", act.public_key(_priv(42)))
        self.assertIn("eng-dept", rotated)
        self.assertIn("eng-documents", rotated)
        self.assertIn("alice", rotated)
        self.assertNotIn("doc-42", rotated)              # a document leaf
        self.assertEqual(graph.key("doc-42"), old_doc_key)
        after = graph.commit()
        # now: no entry, no path
        self.assertEqual(act.Resolver(store, _priv(42)).reachable_ids(), set())
        # the old epoch still resolves — what she fetched stays hers
        old = act.Resolver(RecordStore.at(before, store.blobs), _priv(42))
        self.assertTrue(old.can_read("doc-42"))
        # bob, unaffected, still reads company docs; a re-granted carol
        # under the rotated department reads the eng documents
        self.assertTrue(act.Resolver(store, _priv(43)).can_read("handbook"))
        graph.link("carol", "eng-dept")
        graph.grant("carol", act.public_key(_priv(44)))
        self.assertTrue(act.Resolver(store, _priv(44)).can_read("doc-57"))
        self.assertNotEqual(before, after)

    def test_rotate_drops_entries_on_the_rotated_leaf(self):
        from ontodag import act
        store, graph = _org()
        graph.rotate("alice")
        self.assertEqual(act.Resolver(store, _priv(42)).reachable_ids(), set())
        graph.grant("alice", act.public_key(_priv(42)))
        self.assertTrue(act.Resolver(store, _priv(42)).can_read("doc-42"))


@unittest.skipUnless(HAVE_ACT, "needs the act extra (coincurve, pycryptodome)")
class TestCanonicalAndComposition(unittest.TestCase):
    def test_equal_keys_publish_equal_stores(self):
        from ontodag import act
        s1, g1 = _org(seed=3)
        s2, g2 = _org(seed=3)
        self.assertEqual(g1.commit(), g2.commit())
        s3, g3 = _org(seed=4)
        self.assertNotEqual(g1.commit(), g3.commit())
        # a manager rebuilt from exported keys publishes the same tokens
        store = _store()
        rebuilt = act.KeyGraph(store, org_private_key=_priv(7),
                               keys=g1.export_keys())
        for u, v in [("alice", "eng-dept"), ("eng-dept", "company")]:
            rebuilt.link(u, v)
        for key in store.keys(act.TOKEN_PREFIX):
            self.assertEqual(store.get(key), s1.get(key))

    def test_audience_key_is_order_free(self):
        from ontodag import act
        a, b = _seeded_rng(1)(32), _seeded_rng(2)(32)
        self.assertEqual(act.audience_key({"A": a, "B": b}),
                         act.audience_key({"B": b, "A": a}))
        self.assertNotEqual(act.audience_key({"A": a, "B": b}),
                            act.audience_key({"A": b, "B": a}))
        with self.assertRaises(ValueError):
            act.audience_key({})

    def test_the_encstore_seam(self):
        # An overlay encrypted for eng-documents: alice reads it, bob cannot.
        from ontodag import act
        from ontodag.encstore import EncryptedBytesStore
        store, graph = _org()
        blobs = MemoryBytesStore()
        writer = EncryptedBytesStore(blobs, act.store_key_for(graph.key("eng-documents")))
        ref = writer.put(b"the design spec")
        alice = act.Resolver(store, _priv(42))
        reader = EncryptedBytesStore(blobs, act.store_key_for(alice.key_for("eng-documents")))
        self.assertEqual(reader.get(ref), b"the design spec")
        bob = act.Resolver(store, _priv(43))
        with self.assertRaises(act.AccessDenied):
            bob.key_for("eng-documents")
        # and the AND audience: eng AND company readers only
        both = alice.audience_key(["eng-documents", "company-docs"])
        self.assertEqual(both, act.audience_key({
            "eng-documents": graph.key("eng-documents"),
            "company-docs": graph.key("company-docs")}))

    def test_align_with_an_ontodag(self):
        # People cone upward, document cone downward, one bridge.
        from ontodag import act
        dag = ontodag.OntoDAG()
        dag.put("staff", []); dag.put("eng", ["staff"]); dag.put("alice", ["eng"])
        dag.put("bob", ["staff"])
        dag.put("docs", []); dag.put("specs", ["docs"]); dag.put("spec-1", ["specs"])
        dag.put("memo", ["docs"])
        store = _store()
        graph = act.KeyGraph(store, org_private_key=_priv(7), rng=_seeded_rng(9))
        counts = graph.align(dag, people="staff", documents="docs",
                             bridges=[("eng", "specs")])
        self.assertEqual(counts, {"people": 3, "documents": 3, "bridges": 1})
        graph.grant("alice", act.public_key(_priv(42)))
        graph.grant("bob", act.public_key(_priv(43)))
        alice, bob = act.Resolver(store, _priv(42)), act.Resolver(store, _priv(43))
        self.assertTrue(alice.can_read("spec-1"))
        self.assertTrue(alice.can_read("staff"))         # upward
        self.assertFalse(alice.can_read("memo"))         # no bridge to docs
        self.assertFalse(bob.can_read("spec-1"))         # bob is not in eng
        self.assertFalse(bob.can_read("eng"))            # never downward on people


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
        # addressing needs no crypto at all
        self.assertEqual(len(act.node_id("x")), 32)


if __name__ == "__main__":
    unittest.main()
