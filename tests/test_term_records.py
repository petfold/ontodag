"""Record stores keep no record of a derived term (2026-10-22, Peter: a
geography store holds thousands of `in()` terms, and they are not
knowledge). A term whose only parent is its anchor (`in(alps)` under `in`,
`mass(5kg)` under `mass`) is named in the `up` of the records filed
under it,
and its anchor's record counts such terms (`"terms": n`) instead of
listing them. The properties that matter:

  T1  An eager commit writes no record for a derived term; a term with
      something more to say (metadata, a payload) keeps its record, and so
      does a family pin (`linear-dimension(mass)`), which is schema.
  T2  Hydration puts every derived term back: the same graph, counts and
      canonical text as the writer had.
  T3  A lazy reader stays lazy on plain names and goes whole on a term,
      answering as the eager store does.
  T4  A sparse writer and an eager writer applying the same operations
      reach the same root; peers syncing terms converge.
  T5  An answer about a term certifies as a whole-store certificate
      (version 2) that verifies, and refuses a tampered store; a
      plain-name answer keeps its per-key certificate (version 1).
"""

import unittest

from ontodag import native, prelude
from ontodag.eager import EagerOntoDAG
from ontodag.lazy import LazyOntoDAG, SparseOntoDAG
from recordstore import MemoryBytesStore, RecordStore

FILINGS = [
    ("place", []), ("japan", ["place"]), ("kyoto", ["japan"]),
    ("tokyo", ["japan"]), ("hotel", []),
    ("ryokan", ["hotel", "in(kyoto)"]), ("capsule", ["hotel", "in(tokyo)"]),
    ("parcel", ["mass(5kg)"]), ("crate", ["mass(20kg)"]),
    ("photo", ["about(japan)"]),
    ("animal", []), ("dog", ["animal"]), ("cat", ["animal"]),
]


def build(filings=FILINGS, blobs=None):
    blobs = blobs if blobs is not None else MemoryBytesStore()
    dag = EagerOntoDAG(RecordStore(blobs))
    prelude.apply(dag)
    for name, parents in filings:
        dag.put(name, parents)
    return dag, dag.commit(), blobs


def shape(dag):
    return {name: (sorted(p.name for p in node.parents
                          if dag.nodes.get(p.name) is p),
                   node.descendant_count, dict(node.metadata))
            for name, node in dag.nodes.items()}


class TestEagerRecords(unittest.TestCase):

    def test_no_record_for_a_derived_term(self):
        dag, root, blobs = build()
        keys = set(RecordStore.at(root, blobs).keys())
        for term in ("in(kyoto)", "in(tokyo)", "mass(5kg)", "about(japan)"):
            self.assertIn(term, dag.nodes)
            self.assertNotIn(term, keys)
        self.assertIn("linear-dimension(mass)", keys)
        snapshot = RecordStore.at(root, blobs)
        self.assertEqual(snapshot.get("in")["terms"], 2)
        self.assertNotIn("in(kyoto)", snapshot.get("in")["down"])
        self.assertEqual(snapshot.get("ryokan")["up"], ["hotel", "in(kyoto)"])
        self.assertNotIn("terms", snapshot.get("animal"))   # plain records as before

    def test_a_term_with_more_to_say_keeps_its_record(self):
        dag, _, blobs = build()
        dag.nodes["in(kyoto)"].metadata["note"] = "the old capital"
        dag._payloads["mass(5kg)"] = "ab" * 32
        root = dag.commit()
        keys = set(RecordStore.at(root, blobs).keys())
        self.assertTrue({"in(kyoto)", "mass(5kg)"} <= keys)
        self.assertNotIn("in(tokyo)", keys)
        self.assertEqual(shape(EagerOntoDAG(RecordStore.at(root, blobs))), shape(dag))

    def test_hydration_derives_the_terms(self):
        dag, root, blobs = build()
        again = EagerOntoDAG(RecordStore.at(root, blobs))
        self.assertEqual(shape(again), shape(dag))
        self.assertEqual(native.dumps(again), native.dumps(dag))
        writer = EagerOntoDAG(RecordStore(blobs, root=root))
        self.assertEqual(writer.commit(), root)             # nothing to write

    def test_a_removed_filing_takes_its_term_along(self):
        dag, _, blobs = build()
        dag.remove("capsule")
        root = dag.commit()
        again = EagerOntoDAG(RecordStore.at(root, blobs))
        self.assertNotIn("in(tokyo)", again.nodes)
        self.assertEqual(RecordStore.at(root, blobs).get("in")["terms"], 1)


class TestLazyReader(unittest.TestCase):

    def test_plain_names_stay_lazy(self):
        dag, root, blobs = build()
        lazy = LazyOntoDAG(RecordStore.at(root, blobs))
        self.assertEqual({i.name for i in lazy.get(["animal"])}, {"dog", "cat"})
        self.assertFalse(lazy._whole)
        self.assertLess(lazy.fetches, 10)

    def test_a_term_makes_it_whole_and_answers_as_the_store(self):
        dag, root, blobs = build()
        for query in (["in(japan)"], ["in(kyoto)"], ["hotel", "in(japan)"],
                      ["mass(..10kg)"], ["about(japan)"], ["dimension"]):
            lazy = LazyOntoDAG(RecordStore.at(root, blobs))
            self.assertEqual({i.name for i in lazy.get(query)},
                             {i.name for i in dag.get(query)}, query)
            self.assertTrue(lazy._whole, query)
        lazy = LazyOntoDAG(RecordStore.at(root, blobs))
        self.assertTrue(lazy.is_below("ryokan", "in(japan)"))
        self.assertFalse(lazy.is_below("capsule", "in(kyoto)"))

    def test_load_all_holds_the_whole_graph(self):
        dag, root, blobs = build()
        lazy = LazyOntoDAG(RecordStore.at(root, blobs))
        lazy.load_all()
        lazy._go_whole()
        self.assertEqual(native.dumps(lazy), native.dumps(dag))


class TestWriters(unittest.TestCase):

    def test_sparse_and_eager_reach_one_root(self):
        _, base, blobs = build()
        sparse = SparseOntoDAG(RecordStore(blobs, root=base))
        eager = EagerOntoDAG(RecordStore(blobs, root=base))
        for writer in (sparse, eager):
            writer.put("hostel", ["hotel", "in(kyoto)"])
            writer.put("kennel", ["animal"])
            writer.put("sack", ["mass(5kg)"])
            writer.remove("crate")
        self.assertEqual(sparse.commit(), eager.commit())

    def test_a_plain_write_stays_sparse(self):
        _, base, blobs = build()
        sparse = SparseOntoDAG(RecordStore(blobs, root=base))
        sparse.put("kennel", ["animal"])
        self.assertFalse(sparse._whole)
        eager = EagerOntoDAG(RecordStore(blobs, root=base))
        eager.put("kennel", ["animal"])
        self.assertEqual(sparse.commit(), eager.commit())

    def test_peers_with_terms_converge(self):
        _, base, blobs = build()
        alice = EagerOntoDAG(RecordStore(blobs, root=base))
        bob = EagerOntoDAG(RecordStore(blobs, root=base))
        alice.put("osaka", ["japan"])
        alice.put("inn", ["hotel", "in(osaka)"])
        bob.put("lodge", ["hotel", "in(kyoto)"])
        bob.put("bag", ["mass(5kg)"])
        root_a, root_b = alice.commit(), bob.commit()
        merged_a, merged_b = alice.sync(root_b), bob.sync(root_a)
        self.assertEqual(merged_a, merged_b)
        union = EagerOntoDAG(RecordStore.at(merged_a, blobs))
        self.assertTrue(union.is_below("inn", "in(japan)"))
        self.assertTrue(union.is_below("lodge", "in(kyoto)"))
        self.assertNotIn("in(osaka)", set(RecordStore.at(merged_a, blobs).keys()))


class TestCertificates(unittest.TestCase):

    def test_a_plain_answer_keeps_per_key_proofs(self):
        from ontodag.certificates import prove_below, verify_below
        dag, root, _ = build()
        cert = prove_below(dag, "dog", "animal")
        self.assertEqual(cert["version"], 1)
        self.assertTrue(verify_below(cert, root))

    def test_a_term_answer_carries_the_store(self):
        from ontodag.certificates import (CertificateError, prove_below,
                                          verify_below)
        dag, root, _ = build()
        for sub, sup, expected in (("ryokan", "in(japan)", True),
                                   ("capsule", "in(kyoto)", False),
                                   ("parcel", "mass(..10kg)", True)):
            cert = prove_below(dag, sub, sup)
            self.assertEqual(cert["version"], 2)
            self.assertIs(verify_below(cert, root), expected)
        forged = dict(cert, store=dict(cert["store"], values=cert["store"]["values"][1:]))
        with self.assertRaises(CertificateError):
            verify_below(forged, root)
        with self.assertRaises(CertificateError):
            verify_below(dict(cert, result=not cert["result"]), root)


if __name__ == "__main__":
    unittest.main()
