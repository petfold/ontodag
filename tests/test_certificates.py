"""is_below certificates (ontodag.certificates, CONTRACT.md §7 Tier 2).

What must hold: a certificate verifies with NO store access, against the
root alone; both polarities work, including virtual parametric terms that
exist as no node at all; verification equals the eager oracle over every
pair (the sweep); tampering in any component fails loudly; a verifier
under a *different hash seed* (different set-iteration order, hence a
possibly different walk) still verifies — the order-invariant dependency
closure is what pays for that; and a registry-version mismatch refuses
rather than misinterprets.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from recordstore import MemoryBytesStore, RecordStore

import ontodag
from ontodag.certificates import (CertificateError, prove_below,
                                  verify_below)
from ontodag.dimensions import REGISTRY_VERSION

REPO_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def fixture():
    dag = ontodag.EagerOntoDAG(RecordStore(MemoryBytesStore()))
    dag.put("dimension", [])
    dag.put("linear-dimension", ["dimension"])
    dag.put("calendar-dimension", ["dimension"])
    dag.put("weight", ["linear-dimension"])
    dag.put("time", ["calendar-dimension"])
    dag.put("pet", [])
    dag.put("robot", [])
    dag.put("cat", ["pet"])
    dag.put("dog", ["pet"])
    dag.put("puppy", ["dog"])
    dag.put("robodog", ["robot", "dog"])
    dag.put("parcel", ["weight(3kg)"])
    dag.put("light", ["weight(500g)"])
    dag.put("doc", ["time(2026-08)"])
    dag.commit()
    return dag


CASES = [
    # (sub, sup, expected) — a spread over every answer shape
    ("cat", "pet", True),                       # asserted witness
    ("puppy", "pet", True),                     # two asserted hops
    ("robodog", "robot", True),                 # multi-parent
    ("pet", "cat", False),                      # wrong direction
    ("cat", "robot", False),                    # unrelated
    ("weight(3kg)", "weight(..5kg)", True),     # virtual vs virtual
    ("weight(6kg)", "weight(..5kg)", False),    # virtual, false
    ("weight(3kg)", "weight(3000g)", True),     # spelling reflexivity
    ("parcel", "weight(..5kg)", True),          # item -> value -> bound
    ("parcel", "weight(..1kg)", False),         # bound not met
    ("light", "weight(..1kg)", True),           # 500g fits
    ("doc", "time(2026)", True),                # calendar containment
    ("doc", "time(2025)", False),
    ("nope", "pet", False),                     # unknown, fail-closed
    ("cat", "nope", False),
]


class TestCertificates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dag = fixture()
        cls.root = cls.dag.store.root

    def test_every_answer_shape_certifies_and_verifies(self):
        for sub, sup, expected in CASES:
            cert = prove_below(self.dag, sub, sup)
            self.assertEqual(cert["result"], expected, (sub, sup))
            self.assertEqual(verify_below(cert, self.root), expected,
                             (sub, sup))

    def test_verification_is_pure(self):
        cert = prove_below(self.dag, "puppy", "pet")
        wire = json.dumps(cert)      # travels as text
        # a verifier holding nothing but the envelope and the root:
        self.assertTrue(verify_below(json.loads(wire), self.root))

    def test_oracle_sweep_over_all_pairs(self):
        terms = ["pet", "cat", "puppy", "robot", "robodog", "parcel",
                 "weight(..5kg)", "weight(2kg..)", "time(2026)", "nope"]
        for sub in terms:
            for sup in terms:
                expected = self.dag.is_below(sub, sup)
                cert = prove_below(self.dag, sub, sup)
                self.assertEqual(verify_below(cert, self.root), expected,
                                 (sub, sup))

    def test_certificates_are_cone_sized(self):
        cert = prove_below(self.dag, "puppy", "pet")
        self.assertLess(len(cert["proofs"]), 12)

    def test_accepts_a_raw_record_store(self):
        cert = prove_below(self.dag.store, "cat", "pet")
        self.assertTrue(verify_below(cert, self.root))

    def test_verifies_under_a_different_hash_seed(self):
        # The reason the dependency closure exists: a verifier in another
        # process iterates sets in a different order, so its walk may take
        # a different path. The certificate must cover any of them.
        for sub, sup, expected in CASES:
            cert = prove_below(self.dag, sub, sup)
            with tempfile.NamedTemporaryFile("w", suffix=".json",
                                             delete=False) as fh:
                json.dump({"cert": cert, "root": self.root,
                           "expected": expected}, fh)
                path = fh.name
            self.addCleanup(os.unlink, path)
            code = (
                "import json, sys\n"
                "from ontodag.certificates import verify_below\n"
                f"job = json.load(open({path!r}))\n"
                "assert verify_below(job['cert'], job['root']) == "
                "job['expected']\n"
            )
            for seed in ("0", "1", "42"):
                env = dict(os.environ, PYTHONPATH=REPO_SRC,
                           PYTHONHASHSEED=seed)
                proc = subprocess.run([sys.executable, "-c", code],
                                      capture_output=True, text=True,
                                      env=env, timeout=60)
                self.assertEqual(proc.returncode, 0,
                                 f"{(sub, sup)} seed={seed}:\n{proc.stderr}")


class TestTampering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dag = fixture()
        cls.root = cls.dag.store.root
        cls.cert = prove_below(cls.dag, "puppy", "pet")

    def expect_error(self, cert, root=None, fragment=""):
        with self.assertRaises(CertificateError) as ctx:
            verify_below(cert, self.root if root is None else root)
        if fragment:
            self.assertIn(fragment, str(ctx.exception))

    def test_flipped_claim(self):
        self.expect_error(dict(self.cert, result=False),
                          fragment="contradicts")

    def test_wrong_root(self):
        self.expect_error(self.cert, root="00" * 32, fragment="about root")

    def test_registry_version_mismatch(self):
        self.expect_error(dict(self.cert, registry_version=999),
                          fragment="registry")

    def test_missing_record_proof_is_incomplete_never_wrong(self):
        # Drop the proof for a record the walk needs: verification must
        # fail as incomplete, not return an answer.
        needed = next(p for p in self.cert["proofs"]
                      if p["key"] == "puppy")
        pruned = [p for p in self.cert["proofs"] if p is not needed]
        self.expect_error(dict(self.cert, proofs=pruned),
                          fragment="does not cover")

    def test_tampered_record_proof(self):
        proofs = [dict(p) for p in self.cert["proofs"]]
        victim = next(p for p in proofs if p["present"])
        blob = bytearray(bytes.fromhex(victim["nodes"][0]))
        blob[0] ^= 0xFF
        victim["nodes"] = [bytes(blob).hex()] + victim["nodes"][1:]
        self.expect_error(dict(self.cert, proofs=proofs),
                          fragment="record proof failed")

    def test_foreign_format(self):
        self.expect_error(dict(self.cert, format="something-else"),
                          fragment="envelope")

    def test_substituted_claim_terms(self):
        # A certificate for one claim cannot answer another: either the
        # walk needs uncovered records, or the recomputed answer differs.
        with self.assertRaises(CertificateError):
            verify_below(dict(self.cert, sub="cat", sup="robot"),
                         self.root)


if __name__ == "__main__":
    unittest.main()
