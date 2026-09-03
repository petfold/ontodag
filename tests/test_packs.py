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

GOLDEN_ROOTS = {  # pack v1 fingerprints: everyone merging these converges
    "core":  # v1, 2026-09-02 — the upper ontology (docs/CORE.md)
        "fc49774d178269c7d9ecf48a8012901ceac2b055a33127d38c1fe7cca63c7f26",
    "crypto-core":
        "4d501a439e109269252300d2777145be6ef736bbe5468b7812f016acb730d566",
    "crypto-majors":
        "649b00504f6f4346a0da2cb7a422ec7b5d9caf9c91bd11c37ee09ef7a819b5a5",
    "stablecoins":  # v1 finalized pre-release with LUSD (2026-08-01)
        "71aa064725388fc8a5b0fbefa8b5053a4afdda415d23f78ef7a677d280465ff5",
    "fiat-iso4217":
        "f1a2226ca3f4bbb90437d7331bbb5aa8758673a8f8350eec8c5b3d57c7b5ba7b",
    "physics":  # v1, 2026-09-03 — a domain pack over core (ontodag-core packs/physics)
        "b148bf5de9b8229210301bd60f6af4defa37fe50f37c3d997bf998185785a072",
    "mathematics":  # v1, 2026-09-03 — a domain pack over core (ontodag-core packs/mathematics)
        "adc892dcae95012ed9a5daa942c02034c4175bf569954fc2464bd597a749ce93",
    "chemistry":  # v1, 2026-09-03 — a domain pack over core (ontodag-core packs/chemistry)
        "206db41a1bc59f9b88cfa4f25363541ebe4e8352cb545a439797390db04318d1",
    "biology":  # v1, 2026-09-03 — a domain pack over core (ontodag-core packs/biology)
        "8e4413582c6a7a68a19d69fa1a77830b7eb37abd4d5ea54384e188c8efe423b0",
    "medicine":  # v1, 2026-09-03 — a domain pack over core (ontodag-core packs/medicine)
        "380ca8349d3519c3a9fb9892cc717b0f2691c86343dea7f0570bfbabd60afea9",
    "ai":  # v1, 2026-09-03 — a domain pack over core (ontodag-core packs/ai)
        "b86e048286de64a0fc9fb0a047f5766b782aed44ec2689d647b68e2bec6fda36",
    "economics":  # v1, 2026-09-03 — a domain pack over core (ontodag-core packs/economics)
        "abb74252b52016b6f652515b52ca750750002f0376bbb83f3a432e945a3cc2c2",
    "computing":  # v1, 2026-09-03 — a domain pack over core (ontodag-core packs/computing)
        "7c3d6a5e7e7130a3e1561857dc1546fd9d90e1da6732a6bbea668b1cf73e895f",
    "geography":  # v1, 2026-09-03 — a domain pack over core (ontodag-core packs/geography)
        "4b1a14b9ac5664cd06022ab431a8a6ddb5efae17fb6a0b00e9f915ac4354355e",
    "space":  # v1, 2026-09-03 — a domain pack over core (ontodag-core packs/space)
        "fbd2756c069d6b7283aaa0f8c1c2dd5d229aae68d519708c6fca6be6d131c2aa",
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
        "0238dc860933e8d4e737ad155a6e597191f42fef2f16accb0680dbf33b8e8006",
    "crypto-core":
        "bbd0a930d7888aae3ea65c3ce794e793b5362f4e1837f816567889c75c22ea14",
    "crypto-majors":
        "83337936b794a85f23869661b4b4b3984b03a351d1eb043acd93a64d294fadf6",
    "stablecoins":
        "5bcad36bf97c08af3affdbd73ef56a3bd357441ac0ce4633e4b37d6d5bbd08d1",
    "fiat-iso4217":
        "36a9e1e2fdce1f87b273a50938f30cf931a0880b2bba8ab1a3dea1fe0309dd7b",
    "physics":
        "d294774d44350c60a916b30acbb939731c4f8b6ee9a373d9c138ceec9dc2e7bb",
    "mathematics":
        "2c29f3729965c0e3c7cbb78899ffbd58f3e1b955179c067700a4b18651291d2f",
    "chemistry":
        "28f0649fe5ce870db1dd70df939cc43753d385d10839a0b9c2b0d7ca05f8e60b",
    "biology":
        "8ac757ebb13eafc03225ec5a3ec84aa96ac5a46f75b13b901a9469f0d654f26c",
    "medicine":
        "201e0b8e1ce1d0d3de39bbb7f99838af23026a21d6fbd525b7c10f60d49a256a",
    "ai":
        "3658d68c342429cee3d896c28baa5b54449ba1c4dded4df4a0390706e2cdcfe0",
    "economics":
        "b07549b34e1b885d05ab3f90bc284f6ccb8fb000bbe4483e2f39e441689884d9",
    "computing":
        "99684265b443dc1e4bd0ce2ea182064d340bb1719e196495da4968d25dcc44fb",
    "geography":
        "3b5c2d5c9ca87551318ce03b53842d867768d9e23e1d78e3da1b8cf8a6c6eb40",
    "space":
        "b6379f5c713db7ecbcfe0b1d269d2767823c2e28fbdb0d0df2ef103df626ac8b",
}


UNION_ROOT = (  # core + all ten domain packs, any order (ontodag-core tools/integrate.py, UPPER.md §8.1)
    "759ebb5a5613cb9d309cbd5665f07e9227c4aad22d3214d12116ccabc334881a")

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
        self.assertEqual(len(dag.nodes) - 1, 9793)
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
        self.assertEqual(describe("geography"), "1008 categories")             # borrowed names not counted
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
            self.assertIn("core v4 (2929 categories)", out.getvalue())
            self.assertIn("declarations)", out.getvalue())   # unit packs
