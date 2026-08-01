"""The provenance store (ontodag.provenance, PROVENANCE.md as agreed).

What must hold: subjects are claims (canonical-name pairs) and records are
signed speech acts keyed by content (`s/<subject-hash>/<record-hash>` — set
semantics, so the identical record twice is one record and re-assertion
with a new time is deliberately two); per-writer stores union conflict-free
and direction-independently; the knowledge store is never touched; real
signatures verify and tampering does not.
"""

import hashlib
import unittest

from recordstore import MemoryBytesStore, RecordStore

from ontodag.provenance import (ProvenanceStore, below_subject,
                                binding_subject, exists_subject,
                                operation_group, record_id, record_key,
                                subject_hash, verify_record)

try:
    from ontodag.provenance import KeySigner
    KeySigner("aa" * 32)
    HAVE_BEE = True
except ImportError:
    HAVE_BEE = False


class FakeSigner:
    """Duck-typed signer for logic tests; real signing is tested below."""

    def __init__(self, name):
        self.address = f"fake:{name}"

    def sign(self, data: bytes) -> str:
        return hashlib.sha256(self.address.encode() + data).hexdigest()


def store(name="alice", blobs=None):
    # NB: `blobs or ...` would be wrong — an empty MemoryBytesStore is falsy.
    blobs = MemoryBytesStore() if blobs is None else blobs
    return ProvenanceStore(RecordStore(blobs), signer=FakeSigner(name))


CLAIM = below_subject("cat", "pet")


class TestRecords(unittest.TestCase):
    def test_record_shape_and_key_layout(self):
        ps = store()
        record = ps.assert_claim(CLAIM, basis="root123", time="2026-08-01")
        self.assertEqual(record["v"], 1)
        self.assertEqual(record["type"], "assertion")
        self.assertEqual(record["subject"], CLAIM)
        self.assertEqual(record["author"], "fake:alice")
        self.assertEqual(record["basis"], "root123")
        self.assertEqual(record["origin"], "asserted")
        self.assertEqual(record["ext"], {})
        self.assertTrue(record["sig"])
        key = record_key(record)
        self.assertTrue(key.startswith(f"s/{subject_hash(CLAIM)}/"))
        self.assertTrue(key.endswith(record_id(record)))

    def test_content_addressed_set_semantics(self):
        ps = store()
        ps.assert_claim(CLAIM, basis="r1", time="2026-08-01")
        ps.assert_claim(CLAIM, basis="r1", time="2026-08-01")  # identical
        ps.commit()
        self.assertEqual(len(list(ps.records(CLAIM))), 1)
        # re-assertion later is deliberately a NEW record (audit info)
        ps.assert_claim(CLAIM, basis="r2", time="2026-08-02")
        ps.commit()
        self.assertEqual(len(list(ps.records(CLAIM))), 2)

    def test_subject_filtering_and_types(self):
        ps = store()
        other = exists_subject("dog")
        ps.assert_claim(CLAIM, basis="r1")
        ps.endorse(other, basis="r1")
        ps.retract(CLAIM, basis="r2")
        ps.bind("alice", basis="r1")
        ps.commit()
        about_claim = {r["type"] for r in ps.records(CLAIM)}
        self.assertEqual(about_claim, {"assertion", "retraction"})
        self.assertEqual(len(list(ps.records())), 4)
        binding = next(r for r in ps.records()
                       if r["type"] == "binding")
        self.assertEqual(binding["subject"],
                         binding_subject("fake:alice", "alice"))

    def test_derived_assertions_pin_their_regenerator(self):
        ps = store()
        record = ps.assert_claim(
            CLAIM, basis="r1", origin="derived",
            derived_from={"corpus_root": "c1", "learner_version": "mdl-1"})
        self.assertEqual(record["derived_from"]["learner_version"], "mdl-1")
        with self.assertRaises(ValueError):
            ps.assert_claim(CLAIM, basis="r1", origin="guessed")

    def test_extensions_ride_namespaced(self):
        ps = store()
        record = ps.assert_claim(CLAIM, basis="r1",
                                 ext={"factbond": {"confidence": 0.99}})
        self.assertEqual(record["ext"]["factbond"]["confidence"], 0.99)

    def test_signerless_store_reads_but_refuses_to_write(self):
        ps = ProvenanceStore(RecordStore(MemoryBytesStore()))
        with self.assertRaises(ValueError) as ctx:
            ps.assert_claim(CLAIM, basis="r1")
        self.assertIn("signer", str(ctx.exception))
        self.assertEqual(list(ps.records()), [])

    def test_operation_group_is_deterministic_and_order_free(self):
        a = operation_group("put", "x", ["A", "B"], "r1")
        b = operation_group("put", "x", ["B", "A"], "r1")
        self.assertEqual(a, b)
        self.assertNotEqual(a, operation_group("put", "x", ["A", "B"], "r2"))


class TestUnion(unittest.TestCase):
    def test_two_writers_union_conflict_free_and_direction_free(self):
        blobs = MemoryBytesStore()
        alice = store("alice", blobs)
        bob = store("bob", blobs)
        alice.assert_claim(CLAIM, basis="r1")
        bob.assert_claim(CLAIM, basis="r1")       # same claim, other author
        bob.endorse(exists_subject("dog"), basis="r1")
        root_a, root_b = alice.commit(), bob.commit()

        merged_ab = alice.union(root_b)
        fresh_b = ProvenanceStore(RecordStore(blobs, root=root_b),
                                  signer=FakeSigner("bob"))
        merged_ba = fresh_b.union(root_a)
        self.assertEqual(merged_ab, merged_ba)     # byte-identical roots
        self.assertEqual(alice.union(root_b), merged_ab)  # idempotent

        records = list(alice.records())
        self.assertEqual(len(records), 3)
        authors = {r["author"] for r in records}
        self.assertEqual(authors, {"fake:alice", "fake:bob"})

    def test_union_refuses_staged_records(self):
        blobs = MemoryBytesStore()
        alice, bob = store("alice", blobs), store("bob", blobs)
        bob.assert_claim(CLAIM, basis="r1")
        root_b = bob.commit()
        alice.assert_claim(CLAIM, basis="r1")      # staged, uncommitted
        with self.assertRaises(ValueError):
            alice.union(root_b)

    def test_union_from_empty_adopts(self):
        blobs = MemoryBytesStore()
        alice, bob = store("alice", blobs), store("bob", blobs)
        bob.assert_claim(CLAIM, basis="r1")
        root_b = bob.commit()
        self.assertEqual(alice.union(root_b), root_b)
        self.assertEqual(len(list(alice.records())), 1)


@unittest.skipUnless(HAVE_BEE, "real signing needs the bee package")
class TestRealSigning(unittest.TestCase):
    def test_sign_and_verify_roundtrip(self):
        ps = ProvenanceStore(RecordStore(MemoryBytesStore()),
                             signer=KeySigner("aa" * 32))
        record = ps.assert_claim(CLAIM, basis="r1", time="2026-08-01")
        self.assertTrue(verify_record(record))

    def test_tampering_fails_verification(self):
        ps = ProvenanceStore(RecordStore(MemoryBytesStore()),
                             signer=KeySigner("aa" * 32))
        record = ps.assert_claim(CLAIM, basis="r1")
        tampered = dict(record, basis="r2")
        self.assertFalse(verify_record(tampered))
        wrong_author = dict(record,
                            author=KeySigner("bb" * 32).address)
        self.assertFalse(verify_record(wrong_author))

    def test_fake_signatures_do_not_verify(self):
        record = store().assert_claim(CLAIM, basis="r1")
        self.assertFalse(verify_record(record))


if __name__ == "__main__":
    unittest.main()
