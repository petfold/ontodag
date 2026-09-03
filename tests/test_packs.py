"""Graph-declared units and the shipped packs (UNITS.md §7, registry 3.2).

What must hold: declarations are ordinary graph nodes, so vocabulary is
DATA — packs adopt by idempotent merge with pinned fingerprints, values
parse and render through declared spellings, canonical names of declared
families anchor at the family name, the vocabulary TRAVELS WITH THE STORE
(a fresh reader of the store parses its values with nothing installed),
conflicts and unresolvable definitions refuse loudly, and certificates
keep verifying over stores that carry declarations.
"""

import os
import tempfile
import unittest

from recordstore import MemoryBytesStore, RecordStore

import ontodag
from ontodag import surface
from ontodag.dimensions import UNIT_DECLARATION
from ontodag.packs import PACKS, apply, pack_dag

GOLDEN_ROOTS = {  # pack fingerprints: everyone merging these converges (a domain pack's root is core + pack, so it moves when core does)
    "core":  # v5, 2026-09-03 — the upper ontology (docs/CORE.md)
        "d612c934b069afac9da113ce65b3d3eff1fe94803b566901880dfb050046aa28",
    "crypto-core":
        "4d501a439e109269252300d2777145be6ef736bbe5468b7812f016acb730d566",
    "crypto-majors":
        "649b00504f6f4346a0da2cb7a422ec7b5d9caf9c91bd11c37ee09ef7a819b5a5",
    "stablecoins":  # v1 finalized pre-release with LUSD (2026-08-01)
        "71aa064725388fc8a5b0fbefa8b5053a4afdda415d23f78ef7a677d280465ff5",
    "fiat-iso4217":
        "f1a2226ca3f4bbb90437d7331bbb5aa8758673a8f8350eec8c5b3d57c7b5ba7b",
    "physics":  # v2, 2026-09-03 — a domain pack over core (ontodag-core packs/physics)
        "0c31c48181f11ba7cde173007a50458fddde390ebf320b9c160e6843a309147d",
    "mathematics":  # v1 over core v5, 2026-09-03 — a domain pack over core (ontodag-core packs/mathematics)
        "d7f02ae74299324ec5297ff0623bfcbc24d9578dcd35fa414dbe4a6e013b4dde",
    "chemistry":  # v1 over core v5, 2026-09-03 — a domain pack over core (ontodag-core packs/chemistry)
        "b59eedf86a25daa0446b4fc3f07f37014f4f8188d956e2853bf78f8c80f58403",
    "biology":  # v1 over core v5, 2026-09-03 — a domain pack over core (ontodag-core packs/biology)
        "9e6c4bb1f1269d3fc236f05153209e8809b0871fee5129bb4acbd887fca87e38",
    "medicine":  # v3, 2026-09-03 — a domain pack over core (ontodag-core packs/medicine)
        "16eb760186f77dfe0a87321efb6103fc11f9c0a837e34b5a66ec15b55418b188",
    "ai":  # v3, 2026-09-03 — a domain pack over core (ontodag-core packs/ai)
        "ab6d06f9e4b46921d62fc08efcaf30076972ea81d58722cfe89891d1ee31dd1a",
    "economics":  # v3, 2026-09-03 — a domain pack over core (ontodag-core packs/economics)
        "f7be077de11928ba88059a3d6a0b5e8d9c6e8f5b793dd77f29d8fec04b0e4610",
    "computing":  # v2, 2026-09-03 — a domain pack over core (ontodag-core packs/computing)
        "930cf132042c7750ee52465378c7fad49ae07d95941114cf654185df6876d591",
    "geography":  # v3, 2026-09-03 — a domain pack over core (ontodag-core packs/geography)
        "5044a0658400765339a74c9b27130123882456d68acebd97426fdc0825079286",
    "space":  # v2, 2026-09-03 — a domain pack over core (ontodag-core packs/space)
        "0af13b42bea190b305ed4b68e5127eb7d1ef0b19b820e28a0849f6c6f96400b4",
}


def priced_dag(*packs):
    dag = ontodag.OntoDAG()
    dag.put("dimension", [])
    dag.put("linear-dimension", ["dimension"])
    dag.put("price", ["linear-dimension"])
    for name in packs:
        apply(dag, name)
    return dag


class TestPacks(unittest.TestCase):
    def test_golden_roots_pin_every_pack(self):
        for name, golden in GOLDEN_ROOTS.items():
            dag = ontodag.EagerOntoDAG(RecordStore(MemoryBytesStore()))
            apply(dag, name)
            self.assertEqual(dag.commit(), golden, name)

    def test_adoption_is_idempotent(self):
        dag = ontodag.EagerOntoDAG(RecordStore(MemoryBytesStore()))
        apply(dag, "stablecoins")
        first = dag.commit()
        apply(dag, "stablecoins")
        self.assertEqual(dag.commit(), first)

    def test_unknown_pack_teaches(self):
        with self.assertRaises(ValueError) as ctx:
            pack_dag("nope")
        self.assertIn("available", str(ctx.exception))

    def test_fiat_and_stablecoins_each_their_own_lattice(self):
        dag = priced_dag("fiat-iso4217", "stablecoins")
        dag.put("book", ["price(0.99USD)"])
        self.assertIn("price(99/100USD)", dag.nodes)   # anchor = family
        self.assertTrue(dag.is_below("book", "price(..1USD)"))
        self.assertTrue(dag.is_below("price(99.5HUF)", "price(..100HUF)"))
        # A peg is a promise, not arithmetic: USD vs USDC refuses.
        with self.assertRaises(ValueError):
            dag.is_below("price(1USDC)", "price(..1USD)")

    def test_crypto_denominations_and_rendering(self):
        dag = priced_dag("crypto-majors")
        dag.put("fee", ["price(5000lamport)"])
        self.assertIn("price(1/200000SOL)", dag.nodes)  # canonical anchor
        self.assertTrue(dag.is_below("fee", "price(..1SOL)"))
        # the renderer may use declared vocabulary (policy picks,
        # vocabulary defines):
        self.assertEqual(surface.render("price(1/200000SOL)", dag),
                         "price(5000lamport)")
        with self.assertRaises(ValueError):
            dag.is_below("price(1XRP)", "price(..1SOL)")

    def test_crypto_core_denominations_and_bridges(self):
        dag = priced_dag("crypto-core")
        self.assertTrue(dag.is_below("price(1sat)",
                                     "price(..1/100000000BTC)"))
        self.assertEqual(
            dag._canonical_name("price(21Gwei)"),
            "price(21/1000000000ETH)")
        dag.put("stamp", ["price(9999PLUR)"])
        self.assertTrue(dag.is_below("stamp", "price(..1xBZZ)"))
        # bridges are promises, not identities (Peter's principle, kept):
        with self.assertRaises(ValueError):
            dag.is_below("price(1xBZZ)", "price(..1BZZ)")
        with self.assertRaises(ValueError):
            dag.is_below("price(1xDAI)", "price(..1DAI)")
        # ... and exchange rates never share a lattice
        with self.assertRaises(ValueError):
            dag.is_below("price(1BTC)", "price(..15ETH)")

    def test_vocabulary_travels_with_the_store(self):
        blobs = MemoryBytesStore()
        writer = ontodag.EagerOntoDAG(RecordStore(blobs))
        writer.put("dimension", [])
        writer.put("linear-dimension", ["dimension"])
        writer.put("price", ["linear-dimension"])
        apply(writer, "crypto-majors")
        writer.put("fee", ["price(5000lamport)"])
        root = writer.commit()
        # A fresh reader with NOTHING but the store: the declarations are
        # in the graph, so its own values parse and query.
        reader = ontodag.EagerOntoDAG(RecordStore(blobs, root=root))
        self.assertTrue(reader.is_below("fee", "price(..1SOL)"))
        self.assertIn("fee",
                      {i.name for i in reader.get(["price(..1SOL)"])})


class TestDeclarations(unittest.TestCase):
    def test_chained_declarations_resolve(self):
        dag = ontodag.OntoDAG()
        dag.put("dimension", [])
        dag.put("linear-dimension", ["dimension"])
        dag.put("beer", ["linear-dimension"])
        dag.put(UNIT_DECLARATION, [])
        dag.put("unit(firkin=9igal)", [UNIT_DECLARATION])
        dag.put("unit(kilderkin=2firkin)", [UNIT_DECLARATION])
        dag.put("delivery", ["beer(1kilderkin)"])
        self.assertTrue(dag.is_below("delivery", "beer(..100igal)"))

    def test_pack_defined_spelling_teaches_the_pack(self):
        # A unit that exists one merge away names its pack and the exact
        # command — never the generic error (Peter, 2026-08-01).
        dag = priced_dag()
        for term, pack in [("price(5USD)", "fiat-iso4217"),
                           ("price(1BTC)", "crypto-core"),
                           ("price(2000sat)", "crypto-core"),
                           ("price(1DOGE)", "crypto-majors"),
                           ("price(9USDC)", "stablecoins")]:
            with self.assertRaises(ValueError) as ctx:
                dag.put("x", [term])
            self.assertIn(f"odag pack {pack}", str(ctx.exception), term)
        # a declaration whose *base* is pack-defined teaches the same way
        from ontodag.dimensions import resolve_declarations
        with self.assertRaises(ValueError) as ctx:
            resolve_declarations({"unit(cent=1/100USD)"})
        self.assertIn("odag pack fiat-iso4217", str(ctx.exception))

    def test_unknown_spelling_teaches_the_declaration(self):
        dag = ontodag.OntoDAG()
        dag.put("dimension", [])
        dag.put("linear-dimension", ["dimension"])
        dag.put("beer", ["linear-dimension"])
        with self.assertRaises(ValueError) as ctx:
            dag.put("delivery", ["beer(1firkin)"])
        self.assertIn("unit(", str(ctx.exception))   # names its own fix

    def test_conflicts_and_unresolvables_refuse_loudly(self):
        dag = ontodag.OntoDAG()
        dag.put("dimension", [])
        dag.put("linear-dimension", ["dimension"])
        dag.put("w", ["linear-dimension"])
        dag.put(UNIT_DECLARATION, [])
        dag.put("unit(blob=2kg)", [UNIT_DECLARATION])
        dag.put("unit(blob=3kg)", [UNIT_DECLARATION])   # a second meaning
        with self.assertRaises(ValueError) as ctx:
            dag.put("x", ["w(1blob)"])
        self.assertIn("conflicting", str(ctx.exception))
        # redefining a built-in refuses too
        dag2 = ontodag.OntoDAG()
        dag2.put("dimension", [])
        dag2.put("linear-dimension", ["dimension"])
        dag2.put("w", ["linear-dimension"])
        dag2.put(UNIT_DECLARATION, [])
        dag2.put("unit(kg=2g)", [UNIT_DECLARATION])
        with self.assertRaises(ValueError):
            dag2.put("x", ["w(1kg)"])
        # unresolvable base names its fix
        dag3 = ontodag.OntoDAG()
        dag3.put("dimension", [])
        dag3.put("linear-dimension", ["dimension"])
        dag3.put("w", ["linear-dimension"])
        dag3.put(UNIT_DECLARATION, [])
        dag3.put("unit(keg=2vat)", [UNIT_DECLARATION])
        with self.assertRaises(ValueError) as ctx:
            dag3.put("x", ["w(1keg)"])
        self.assertIn("unresolvable", str(ctx.exception))

    def test_cache_follows_puts_and_removes(self):
        dag = ontodag.OntoDAG()
        dag.put("dimension", [])
        dag.put("linear-dimension", ["dimension"])
        dag.put("w", ["linear-dimension"])
        with self.assertRaises(ValueError):
            dag.put("x", ["w(1blob)"])
        dag.put(UNIT_DECLARATION, [])
        dag.put("unit(blob=2kg)", [UNIT_DECLARATION])
        dag.put("x", ["w(1blob)"])                     # picked up, no hooks
        self.assertIn("w(2kg)", dag.nodes)
        dag.remove("unit(blob=2kg)")
        with self.assertRaises(ValueError):
            dag.put("y", ["w(3blob)"])                 # and dropped again

    def test_certificates_survive_declared_vocabulary(self):
        from ontodag.certificates import prove_below, verify_below
        dag = ontodag.EagerOntoDAG(RecordStore(MemoryBytesStore()))
        dag.put("dimension", [])
        dag.put("linear-dimension", ["dimension"])
        dag.put("price", ["linear-dimension"])
        apply(dag, "crypto-majors")
        dag.put("fee", ["price(5000lamport)"])
        root = dag.commit()
        certificate = prove_below(dag, "fee", "price(..1SOL)")
        self.assertTrue(verify_below(certificate, root))
        negative = prove_below(dag, "fee", "price(..1000lamport)")
        self.assertFalse(verify_below(negative, root))


if __name__ == "__main__":
    unittest.main()


SWARM_GOLDEN_ROOTS = {  # the same packs under Swarm (BMT) addressing —
    # the fingerprints real Swarm publication must reproduce (PACKS.md §14
    # item 1). Computable offline: BMT is a hash, not a network.
    "core":
        "419f0169eefa6e0893a85988d0ace4a4572fc0704031e218d80c36840fed3053",
    "crypto-core":
        "bbd0a930d7888aae3ea65c3ce794e793b5362f4e1837f816567889c75c22ea14",
    "crypto-majors":
        "83337936b794a85f23869661b4b4b3984b03a351d1eb043acd93a64d294fadf6",
    "stablecoins":
        "5bcad36bf97c08af3affdbd73ef56a3bd357441ac0ce4633e4b37d6d5bbd08d1",
    "fiat-iso4217":
        "36a9e1e2fdce1f87b273a50938f30cf931a0880b2bba8ab1a3dea1fe0309dd7b",
    "physics":
        "b479c12ef39f4d720cdc3c6dad4104e61e6991ba05535e40a7c309bb742bcec9",
    "mathematics":
        "810ba1d2b3f8df070e92e6585ff58655fcbaa4b47ce685739b5426277ca2e99d",
    "chemistry":
        "50e1662ca4a39d395b55546cb269370637f863363f9d8e4c4d15e5de56f45307",
    "biology":
        "52116988bbfde1c1ba1624816773115aba9691584cbb3f9193a361e48f236a15",
    "medicine":
        "5d7775fbe17f82ba9326944d00976b18d34356d380fa8e557509cf4b3979fd8d",
    "ai":
        "2f186ae26059e17ffa2ad80ec4bae6e38cc2af2da55df1c7f5b50ec5d7a80ea1",
    "economics":
        "cd820c2090cc45999b59ae6c1ce589c5a9fb72f3c243961f03b72c372a2f41d4",
    "computing":
        "8b3e6267c1ef3688ceef5c3a503f471594e1d360720ce8da23352a305068df7c",
    "geography":
        "f1bcc3ccb9a0d47c9a5a88806054feea7502c0fb6e2338bb6d9c3784a509bb22",
    "space":
        "503159e77982f7933780bd33e34aed299ecf8daa4f67491625d452d39f46655e",
}


UNION_ROOT = (  # core + all ten domain packs, any order (ontodag-core tools/integrate.py, UPPER.md §8.1)
    "1d67a67033859582e63faba79538f1e81ab8260e241e36e2cdd18d544f3f0482")

DOMAIN_PACKS = ["physics", "mathematics", "chemistry", "biology", "medicine", "ai",
                "economics", "computing", "geography", "space"]
SLOW_DOMAIN_PACKS = set(DOMAIN_PACKS) - {"space"}   # the smallest one runs always; see the two gated loops


class TestPublishedPackStores(unittest.TestCase):
    """PACKS.md §13.8 / §14 item 1: publishing a shipped pack IS adopting it
    into a fresh store, so early (code-shipped) and late (published)
    adopters converge byte-identically — the published root must equal the
    golden root, per addressing scheme."""

    def test_cli_rs_store_adoption_reproduces_the_golden_roots(self):
        # Through the real CLI path (`odag -f rs:PATH pack NAME`), not the
        # library: the published store is whatever the tool actually writes.
        import io as _io
        import ontodag.__main__ as cli
        for name, golden in GOLDEN_ROOTS.items():
            if name in SLOW_DOMAIN_PACKS and not os.environ.get("ONTODAG_SLOW_TESTS"):
                continue    # a full on-disk adoption per domain pack is minutes of blob writes;
                            # `space` stands in for the path, ONTODAG_SLOW_TESTS=1 runs them all
            with tempfile.TemporaryDirectory() as home:
                os.environ["ONTODAG_HOME"] = home
                path = os.path.join(home, "pack")
                session = cli.Session(f"rs:{path}")
                code = cli.dispatch(["pack", name], session,
                                    out=_io.StringIO(), err=_io.StringIO())
                self.assertEqual(code, 0, name)
                store = session.backend.open_store()
                self.assertEqual(store.root, golden, name)

    def test_swarm_addressing_reproduces_its_own_golden_roots(self):
        # BMT refs give a different (but equally canonical) root; pinning it
        # here means a live Swarm publication is verifiable in advance.
        from recordstore import DirBytesStore
        # The BMT dependency surfaces at first HASH, not at construction —
        # probe with a real put, or a bare environment (CI) fails instead
        # of skipping. Found by the publish workflow's suite gate.
        with tempfile.TemporaryDirectory() as probe:
            try:
                DirBytesStore(probe, addressing="swarm").put(b"probe")
            except Exception as exc:                # extra not installed
                self.skipTest(f"swarm addressing unavailable: {exc}")
        for name, golden in SWARM_GOLDEN_ROOTS.items():
            if name in SLOW_DOMAIN_PACKS and not os.environ.get("ONTODAG_SLOW_TESTS"):
                continue    # BMT-hashing ~4,000 records per pack; `space` stands in, ONTODAG_SLOW_TESTS=1 runs all
            with tempfile.TemporaryDirectory() as d:
                blobs = DirBytesStore(d, addressing="swarm")
                dag = ontodag.EagerOntoDAG(RecordStore(blobs))
                apply(dag, name)
                self.assertEqual(dag.commit(), golden, name)


class TestDomainPacks(unittest.TestCase):
    """The ten domain packs of 0.21.0: each presumes core, each adopts alone
    (a sibling's name it leans on sits at top level until the sibling comes),
    and all ten with core converge on ONE root in any order — the integration
    build ontodag-core runs, reproduced here from the shipped modules."""

    def test_union_of_core_and_every_pack_has_one_root(self):
        if not os.environ.get("ONTODAG_SLOW_TESTS"):
            self.skipTest("~3 min: ten merges into a 9,000-node store; ONTODAG_SLOW_TESTS=1 runs it "
                          "(ontodag-core's tools/integrate.py is the other witness to this root)")
        dag = ontodag.EagerOntoDAG(RecordStore(MemoryBytesStore()))
        apply(dag, "core")
        for name in DOMAIN_PACKS:
            apply(dag, name)
        self.assertEqual(dag.commit(), UNION_ROOT)
        self.assertEqual(len(dag.nodes) - 1, 9777)
        # cross-pack claims resolve in the union
        self.assertTrue(dag.is_below("shapefile", "file-format"))          # geography -> computing
        self.assertTrue(dag.is_below("merkle-dag", "directed-acyclic-graph"))  # computing -> mathematics
        self.assertTrue(dag.is_below("celestial-coordinate-system", "coordinate-system"))  # space -> geography
        # and nothing but core's roots and the prelude's kind node sits at the top
        tops = {x.name for x in dag.nodes["*"].neighbors}
        self.assertEqual(tops, {"agent", "attribute", "cognition", "dimension", "event", "field-of-study",
                                "information", "physical-object", "place", "possession", "substance"})

    def test_a_pack_alone_leaves_a_borrowed_name_at_top_level_until_its_sibling_comes(self):
        from ontodag.packs import pack_dag, describe, packs_declaring_node
        dag = pack_dag("geography")
        self.assertIn("file-format", {x.name for x in dag.nodes["*"].neighbors})   # computing's, borrowed
        self.assertTrue(dag.is_below("shapefile", "file-format"))
        apply(dag, "computing")
        self.assertNotIn("file-format", {x.name for x in dag.nodes["*"].neighbors})  # filed under information
        self.assertEqual(describe("geography"), "1001 categories")             # borrowed names not counted
        self.assertEqual(packs_declaring_node("file-format"), ["computing"])   # and never hinted as geography's
        self.assertEqual(packs_declaring_node("mount-everest"), ["geography"])


class TestCorePack(unittest.TestCase):
    """docs/CORE.md: the upper ontology as a pack — closure, size discipline,
    the motivating paths, no unit declarations, composition with the
    prelude, and the missing-parent hint that starts firing for real
    categories the day a pack ships them."""

    def setUp(self):
        from ontodag.core_ontology import CORE
        self.core = CORE
        self.names = [name for name, _ in CORE]

    def test_closed_no_duplicates_and_small(self):
        self.assertEqual(len(self.names), len(set(self.names)), "duplicate")
        parents = {p for _, ps in self.core for p in ps}
        from ontodag.prelude import prelude_dag
        outside = parents - set(self.names)
        self.assertFalse(outside - set(prelude_dag().nodes), "parent outside the pack and the prelude")
        # EVOLUTION.md §3: admission is a one-way door, so the top stays
        # small. Coverage is a domain pack's job.
        self.assertGreater(len(self.names), 2000)      # v2: consensus over the reference ontologies
        self.assertLess(len(self.names), 5000)
        self.assertTrue(all(n == n.lower() and " " not in n
                            for n in self.names), "names: lowercase-hyphenated")

    def test_the_motivating_paths(self):
        dag = pack_dag("core")
        self.assertTrue(dag.is_below("plane-ticket", "transport-ticket"))
        self.assertTrue(dag.is_below("plane-ticket", "document"))
        self.assertTrue(dag.is_below("man", "human"))
        self.assertTrue(dag.is_below("human", "person"))      # two parents
        self.assertTrue(dag.is_below("human", "mammal"))
        self.assertTrue(dag.is_below("email", "information"))
        # an email from a man is an email from a human: the query works
        dag.put("mail-from-bob.eml", ["email", "man"])
        self.assertEqual({x.name for x in dag.get(["email", "human"])},
                         {"mail-from-bob.eml"})
        # taxonomy without teeth: a wrong filing is not refused (documented)
        dag.put("odd.xlsx", ["spreadsheet", "mammal"])

    def test_carries_no_unit_declarations(self):
        from ontodag.packs import is_unit_pack
        self.assertFalse(is_unit_pack("core"))
        self.assertNotIn(UNIT_DECLARATION, pack_dag("core").nodes)
        for other in PACKS:
            if other not in ("core", "prelude") and other not in DOMAIN_PACKS:
                self.assertTrue(is_unit_pack(other), other)
        for other in DOMAIN_PACKS:                 # categories over core, never units
            self.assertFalse(is_unit_pack(other), other)
            self.assertNotIn(UNIT_DECLARATION, pack_dag(other).nodes)

    def test_composes_with_the_prelude_and_is_idempotent(self):
        from ontodag.prelude import apply as prelude
        dag = ontodag.EagerOntoDAG(RecordStore(MemoryBytesStore()))
        prelude(dag)
        apply(dag, "core")
        first = dag.commit()
        apply(dag, "core")
        prelude(dag)
        self.assertEqual(dag.commit(), first)
        # and a typed value files under a core category with no conflict
        dag.put("parcel", ["container", "weight(..5kg)"])
        self.assertTrue(dag.is_below("parcel", "artifact"))

    def test_missing_parent_hint_names_the_pack(self):
        from ontodag.packs import packs_declaring_node
        self.assertEqual(packs_declaring_node("invoice"), ["core"])
        self.assertEqual(packs_declaring_node("BTC"), [])
        import io as _io
        import ontodag.__main__ as cli
        with tempfile.TemporaryDirectory() as home:
            os.environ["ONTODAG_HOME"] = home
            session = cli.Session(os.path.join(home, "s.od"))
            err = _io.StringIO()
            code = cli.dispatch(["put", "report.pdf", "invoice"], session,
                                out=_io.StringIO(), err=err)
            self.assertEqual(code, 1)
            self.assertIn("odag pack core", err.getvalue())

    def test_show_prints_claims_and_listing_says_categories(self):
        import io as _io
        import ontodag.__main__ as cli
        with tempfile.TemporaryDirectory() as home:
            os.environ["ONTODAG_HOME"] = home
            session = cli.Session(os.path.join(home, "s.od"))
            out = _io.StringIO()
            cli.dispatch(["pack", "core", "--show"], session, out=out,
                         err=_io.StringIO())
            self.assertIn("plane-ticket ⊑ transport-ticket", out.getvalue())
            self.assertIn("human ⊑ mammal, person", out.getvalue())
            out = _io.StringIO()
            cli.dispatch(["pack"], session, out=out, err=_io.StringIO())
            self.assertIn("core v5 (2930 categories)", out.getvalue())
            self.assertIn("declarations)", out.getvalue())   # unit packs
