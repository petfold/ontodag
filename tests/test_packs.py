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

GOLDEN_ROOTS = {  # pack fingerprints: everyone merging these converges (a domain pack's root is core + pack, so it moves when core does;
    # all moved 2026-10-22 when derived terms lost their records)
    "core":  # v12, 2026-10-07 — the upper ontology (docs/CORE.md): v11 + step 7, prelude v4
        "7bc21466a8f9df5492884dde530f8c53cd541f50e4b25b42f4f0481a84b2e091",
    "crypto-core":
        "4d501a439e109269252300d2777145be6ef736bbe5468b7812f016acb730d566",
    "crypto-majors":
        "649b00504f6f4346a0da2cb7a422ec7b5d9caf9c91bd11c37ee09ef7a819b5a5",
    "stablecoins":  # v1 finalized pre-release with LUSD (2026-08-01)
        "71aa064725388fc8a5b0fbefa8b5053a4afdda415d23f78ef7a677d280465ff5",
    "fiat-iso4217":
        "f1a2226ca3f4bbb90437d7331bbb5aa8758673a8f8350eec8c5b3d57c7b5ba7b",
    "physics":  # v5 over core v12, 2026-10-07 (ontodag-core packs/physics)
        "b24999a62b8aa2b385268035527cb26e7c5431bd25ba0dda099d983afb020879",
    "mathematics":  # v3 over core v12, 2026-10-07 (ontodag-core packs/mathematics)
        "7b05a2f1977337074ca1393f0f9bb6d0abc3b861660433d24e94f1588ef292a2",
    "chemistry":  # v3 over core v12, 2026-10-07 (ontodag-core packs/chemistry)
        "69fb8e4d26ec2b05a607c373779decc6c39f0be16c966268d37c76c90a46bdfd",
    "biology":  # v3 over core v12, 2026-10-07 (ontodag-core packs/biology)
        "716962388eef38cca2888456ee388046f33231e6cdb11f7f4cc24bd4703a3b79",
    "medicine":  # v6 over core v12, 2026-10-07 (ontodag-core packs/medicine)
        "2e65ffd28337b494687f1b243167f2bba515b9852fd302fccca6d4c016f5b0ac",
    "ai":  # v5 over core v12, 2026-10-07 (ontodag-core packs/ai)
        "d42c82107c31eba1d0e6622352fedd630a1cf476409d5c2e496aff0d4dd70579",
    "economics":  # v7 over core v12, 2026-10-07 (ontodag-core packs/economics)
        "e5ca8bdb319e8121d62b42e6f28f2fbd5fd093ae2f2c206a69709d514af72185",
    "computing":  # v5 over core v12, 2026-10-07 (ontodag-core packs/computing)
        "a5318ebf237a744fa32f0020994bc1fb5786d4b48f6a216beaeee063fc149073",
    "geography":  # v6 over core v12, 2026-10-07 (ontodag-core packs/geography)
        "3f566922fdc31a17b69c8d23b747cc48332ee7d6498d38b91b3a24304ba7afbe",
    "space":  # v5 over core v12, 2026-10-07 (ontodag-core packs/space)
        "ba35f7ca6a479125da079525a4617404093150fd7c1609a2110d5d062f8a457e",
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
        "ee32b3bae0c76bcf95f0fa0973aa70ed5a8c57d3f87326d2687a9f66b22d2ae5",
    "crypto-core":
        "bbd0a930d7888aae3ea65c3ce794e793b5362f4e1837f816567889c75c22ea14",
    "crypto-majors":
        "83337936b794a85f23869661b4b4b3984b03a351d1eb043acd93a64d294fadf6",
    "stablecoins":
        "5bcad36bf97c08af3affdbd73ef56a3bd357441ac0ce4633e4b37d6d5bbd08d1",
    "fiat-iso4217":
        "36a9e1e2fdce1f87b273a50938f30cf931a0880b2bba8ab1a3dea1fe0309dd7b",
    "physics":
        "2d642b5ea8d38cec1fadd9b789ba84507005caf99fec2874aeb850db1e038517",
    "mathematics":
        "4d43578c16273500600dd48f89f6062d9a824fd7cc59dfe2716b8501e4f083ae",
    "chemistry":
        "38e2c898c24135df3a9abddb1d09c5ce04cd57a0ce9c6489cdbf5d08a447ad41",
    "biology":
        "718e84d510661d33affc61a711d8a1f462901faa31216510fec477b4f24a580d",
    "medicine":
        "2406646b92f2f54852d933adbe35544f549cfb543ec694e62e537e0f72336ba8",
    "ai":
        "5e58f29467fa76f5409e0c70ae0965ce81058ca97c6d20e8de4022c56e78fbce",
    "economics":  # v6, 2026-09-19
        "7cb150b1d6f347ec6d35d2da8318474bb57cea73d8f48cc37812783656971cbc",
    "computing":
        "ca8b01d710a1d89db5d56ca2772fce365c58f06ae9af32f740b7730da652079a",
    "geography":
        "03a37d39ceefa5d47a2f37ea683040a86b9379d58719e23de03c1f578d2ac181",
    "space":
        "67f6be2688e5fb7ca85a463c3d2929dad2b177bb3edb6bb910e8fa110598cff3",
}


UNION_ROOT = (  # core + all ten domain packs, any order (ontodag-core tools/integrate.py, UPPER.md §8.1)
    "3d09e626b7fe1cecfe82e2263b6230fd62780c93e098b2ac6199398d6d4e3e61")

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
            self.skipTest("~6 min alone (measured 2026-09-12, core v9): ten merges into an 11,900-node store; ONTODAG_SLOW_TESTS=1 runs it "
                          "(ontodag-core's tools/integrate.py is the other witness to this root)")
        dag = ontodag.EagerOntoDAG(RecordStore(MemoryBytesStore()))
        apply(dag, "core")
        for name in DOMAIN_PACKS:
            apply(dag, name)
        self.assertEqual(dag.commit(), UNION_ROOT)
        self.assertEqual(len(dag.nodes) - 1, 11642)   # core v14, prelude 5 (2026-10-25)
        # cross-pack claims resolve in the union
        self.assertTrue(dag.is_below("temporal-knowledge-graph", "knowledge-base"))  # ai -> computing
        self.assertTrue(dag.is_below("merkle-dag", "directed-acyclic-graph"))  # computing -> mathematics
        self.assertTrue(dag.is_below("celestial-coordinate-system", "coordinate-system"))  # space -> geography
        self.assertTrue(dag.is_below("pork-butcher", "merchant"))   # economics carries occupations' butcher
        # and nothing but core's roots, the prelude's kind node and the
        # mathematics pack's own branch sits at the top
        tops = {x.name for x in dag.nodes["*"].neighbors}
        self.assertEqual(tops, {"agent", "amount", "attribute", "cognition", "dimension", "event",
                                "field-of-study", "group", "information", "mathematical-object", "part",
                                "physical-object", "place", "possession", "relation", "substance"})

    def test_a_pack_alone_leaves_a_borrowed_name_at_top_level_until_its_sibling_comes(self):
        from ontodag.packs import pack_dag, describe, packs_declaring_node
        dag = pack_dag("space")
        self.assertIn("coordinate-system", {x.name for x in dag.nodes["*"].neighbors})   # geography's, borrowed
        self.assertTrue(dag.is_below("celestial-coordinate-system", "coordinate-system"))
        apply(dag, "geography")
        self.assertNotIn("coordinate-system", {x.name for x in dag.nodes["*"].neighbors})  # filed
        self.assertEqual(describe("space"), "340 categories")                  # borrowed names not counted
        self.assertEqual(packs_declaring_node("coordinate-system"), ["geography"])  # and never hinted as space's
        self.assertEqual(packs_declaring_node("milky-way"), ["space"])

    def test_a_packs_own_top_level_name_is_its_own_not_borrowed(self):
        # mathematical-object is the mathematics pack's own branch (ontodag-core,
        # 2026-10-16): siblings borrow it, and it already sits where its owner puts it
        from ontodag.packs import _DOMAIN, pack_entries, packs_declaring_node, unplaced_borrowings, uses
        self.assertIn(("mathematical-object", ()), pack_entries("mathematics"))   # as core writes its branches
        self.assertNotIn("mathematical-object", _DOMAIN["mathematics"].BORROWED)
        self.assertEqual(packs_declaring_node("mathematical-object"), ["mathematics"])
        self.assertEqual(uses("geography"), ("mathematics",))
        dag = ontodag.OntoDAG()
        apply(dag, "geography")
        self.assertEqual(unplaced_borrowings(dag, "geography"), {})          # nothing to file


class TestSoftDependencies(unittest.TestCase):
    """A sibling pack is a soft dependency: `uses` names the packs whose
    names a pack borrows, and `unplaced_borrowings` the ones still unfiled
    in a store, which `odag pack` and the REST route offer, never adopt."""

    def test_uses_names_the_siblings_a_pack_borrows_from(self):
        from ontodag.packs import uses
        self.assertIn("computing", uses("ai"))              # knowledge-graph, search-algorithm, ...
        self.assertEqual(uses("chemistry"), ())              # core alone
        self.assertEqual(uses("core"), ())                   # not a domain pack

    def test_unplaced_borrowings_empty_once_the_sibling_is_adopted(self):
        from ontodag.packs import unplaced_borrowings
        dag = ontodag.OntoDAG()
        apply(dag, "ai")
        self.assertIn("knowledge-graph", unplaced_borrowings(dag, "ai").get("computing", []))
        apply(dag, "computing")
        self.assertNotIn("computing", unplaced_borrowings(dag, "ai"))


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
        from ontodag import dimensions as dims
        from ontodag.prelude import prelude_dag
        known = set(self.names) | set(prelude_dag().nodes)
        parents = set()
        for _, ps in self.core:
            for p in ps:
                pin = dims.kind_node(p)
                split = dims.split_term(p)
                if pin is not None:                       # a family pin: its kind
                    parents.add(pin[0])
                elif split is not None and split[0] in known:
                    parents |= {split[0], *dims.constraints(split[1])}   # in(egg): in, egg
                else:
                    parents.add(p)
        self.assertFalse(parents - known, "parent outside the pack and the prelude")
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
        dag.put("parcel", ["container", "mass(..5kg)"])
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
            self.assertIn("core v14 (4753 categories)", out.getvalue())
            self.assertIn("declarations)", out.getvalue())   # unit packs
