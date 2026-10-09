"""Conformance suite for docs/CONTRACT.md (contract version 0.4).

One named test class per guarantee G1-G7, plus the §4 as-of clause, the
§5.1 dimensions over nodes, and the version constant. Every test goes through the PUBLIC API only: the `ontodag`
package surface (plus recordstore's public surface where a guarantee is
about roots) — never submodule paths, never internals. This file is the
executable half of the contract: if a change breaks a test here, either the
change is wrong or CONTRACT.md needs a version bump (its §8, resolution 2).
"""

import unittest

import ontodag
from recordstore import MemoryBytesStore, RecordStore


def eager(blobs, base=None):
    return ontodag.EagerOntoDAG(RecordStore(blobs, root=base))


def names(items):
    return {i.name for i in items}


def declare_weight(dag):
    """The v1 kind registry plus one linear dimension (DIMENSIONS.md)."""
    dag.put("dimension", [])
    dag.put("linear-dimension", ["dimension"])
    dag.put("weight", ["linear-dimension"])
    return dag


class TestContractVersion(unittest.TestCase):
    def test_version_constant_matches_document(self):
        self.assertEqual(ontodag.CONTRACT_VERSION, "0.6")


class TestG1CanonicalRoot(unittest.TestCase):
    """Equal knowledge yields an equal root: history, insertion order and
    spelling of equal denotations do not affect it."""

    def test_put_order_does_not_affect_root(self):
        a = eager(MemoryBytesStore())
        a.put("pet", [])
        a.put("cat", ["pet"])
        a.put("dog", ["pet"])
        b = eager(MemoryBytesStore())  # separate blob store on purpose:
        b.put("pet", [])               # roots are content addresses
        b.put("dog", ["pet"])
        b.put("cat", ["pet"])
        self.assertEqual(a.commit(), b.commit())

    def test_redundant_parent_is_pruned_to_the_same_root(self):
        a = eager(MemoryBytesStore())
        a.put("animal", [])
        a.put("pet", ["animal"])
        a.put("cat", ["pet"])
        b = eager(MemoryBytesStore())
        b.put("animal", [])
        b.put("pet", ["animal"])
        b.put("cat", ["pet", "animal"])  # redundant: pet already ⊑ animal
        self.assertEqual(a.commit(), b.commit())

    def test_spellings_of_one_denotation_collapse_to_one_root(self):
        a = declare_weight(eager(MemoryBytesStore()))
        a.put("parcel", ["weight(3kg)"])
        b = declare_weight(eager(MemoryBytesStore()))
        b.put("parcel", ["weight(3000g)"])  # same denotation, other spelling
        self.assertEqual(a.commit(), b.commit())


class TestG2MonotonicityUnderMerge(unittest.TestCase):
    """Merge is union + re-reduction: true stays true, answers only grow."""

    def _pair(self):
        a = ontodag.OntoDAG()
        a.put("pet", [])
        a.put("cat", ["pet"])
        b = ontodag.OntoDAG()
        b.put("pet", [])
        b.put("dog", ["pet"])
        return a, b

    def test_answers_only_grow_and_truths_survive(self):
        a, b = self._pair()
        before = names(a.get(["pet"]))
        self.assertTrue(a.is_below("cat", "pet"))
        a.merge(b)
        after = names(a.get(["pet"]))
        self.assertLessEqual(before, after)          # nothing shrank
        self.assertIn("dog", after)                  # union arrived
        self.assertTrue(a.is_below("cat", "pet"))    # true stayed true
        self.assertTrue(a.is_below("dog", "pet"))

    def test_merge_is_idempotent_and_direction_free_in_answers(self):
        a, b = self._pair()
        a.merge(b)
        once = names(a.get(["pet"]))
        a.merge(b)
        self.assertEqual(once, names(a.get(["pet"])))  # idempotent
        c, d = self._pair()
        d.merge(c)
        self.assertEqual(once, names(d.get(["pet"])))  # either direction


class TestG3Determinism(unittest.TestCase):
    """Same root, same interpretation context: same answers on any
    residency (eager rehydration vs lazy on-demand)."""

    def setUp(self):
        self.blobs = MemoryBytesStore()
        w = eager(self.blobs)
        w.put("pet", [])
        w.put("robot", [])
        w.put("cat", ["pet"])
        w.put("dog", ["pet"])
        w.put("puppy", ["dog"])
        w.put("robodog", ["robot", "dog"])
        self.root = w.commit()

    def test_every_residency_gives_the_same_answers(self):
        readers = [
            ontodag.EagerOntoDAG(RecordStore.at(self.root, self.blobs)),
            ontodag.LazyOntoDAG(RecordStore.at(self.root, self.blobs)),
        ]
        queries = [["pet"], ["dog"], ["robot", "dog"], ["pet", "robot"]]
        expected = [names(readers[0].get(q)) for q in queries]
        for reader in readers[1:]:
            for q, want in zip(queries, expected):
                self.assertEqual(names(reader.get(q)), want, q)
        self.assertEqual(
            names(readers[0].get_any([["cat"], ["robot"]])),
            names(readers[1].get_any([["cat"], ["robot"]])),
        )


class TestG4IsBelowFailClosed(unittest.TestCase):
    """True only with a witness; false means not derivable, never error."""

    def setUp(self):
        self.dag = declare_weight(ontodag.OntoDAG())
        self.dag.put("pet", [])
        self.dag.put("cat", ["pet"])

    def test_reflexive_and_witnessed(self):
        self.assertTrue(self.dag.is_below("cat", "cat"))
        self.assertTrue(self.dag.is_below("cat", "pet"))
        self.assertFalse(self.dag.is_below("pet", "cat"))

    def test_unknown_names_fail_closed_not_loud(self):
        self.assertFalse(self.dag.is_below("nope", "pet"))
        self.assertFalse(self.dag.is_below("cat", "nope"))
        self.assertFalse(self.dag.is_below("nope", "alsonope"))

    def test_virtual_parametric_terms_decide_from_names_alone(self):
        # No weight *values* exist as nodes — arithmetic answers anyway.
        self.assertTrue(self.dag.is_below("weight(3kg)", "weight(..5kg)"))
        self.assertFalse(self.dag.is_below("weight(6kg)", "weight(..5kg)"))


class TestG5Convergence(unittest.TestCase):
    """Writers folding each other's published roots land byte-identically,
    whatever the gossip order."""

    def test_two_writers_converge(self):
        blobs = MemoryBytesStore()
        alice, bob = eager(blobs), eager(blobs)
        alice.put("pet", [])
        alice.put("cat", ["pet"])
        bob.put("pet", [])
        bob.put("dog", ["pet"])
        root_a, root_b = alice.commit(), bob.commit()
        merged_a = alice.sync(root_b)
        merged_b = bob.sync(root_a)
        self.assertEqual(merged_a, merged_b)
        self.assertEqual(alice.sync(merged_b), merged_a)  # idempotent


class TestG6GetOverlapping(unittest.TestCase):
    """Complete for possibility, silent on satisfaction."""

    def setUp(self):
        self.dag = declare_weight(ontodag.OntoDAG())
        self.dag.put("light", ["weight(500g)"])
        self.dag.put("box", ["weight(0.8kg..1.5kg)"])
        self.dag.put("heavy", ["weight(2kg)"])

    def test_candidates_are_recall_complete_but_not_asserted(self):
        need = "weight(1kg..)"
        candidates = names(self.dag.get_overlapping(need))
        satisfied = names(self.dag.get([need]))
        self.assertLessEqual(satisfied, candidates)   # recall-complete
        self.assertIn("heavy", satisfied)             # definite satisfier
        self.assertIn("box", candidates)              # possible satisfier...
        self.assertNotIn("box", satisfied)            # ...not asserted
        self.assertNotIn("light", candidates)         # provably disjoint

    def test_only_parametric_terms_of_declared_dimensions(self):
        with self.assertRaises(ValueError):
            self.dag.get_overlapping("light")

    def test_candidates_grow_monotonically(self):
        need = "weight(1kg..)"
        before = names(self.dag.get_overlapping(need))
        self.dag.put("crate", ["weight(1.2kg)"])
        after = names(self.dag.get_overlapping(need))
        self.assertLessEqual(before, after)
        self.assertIn("crate", after)


def declare_relations(dag):
    """`in` as a transitive dimension, `about` as an enclosing one and
    `for` as a reversed one (§5.1); their kind nodes are not in the
    prelude yet."""
    dag.put("dimension", [])
    dag.put("transitive-dimension", ["dimension"])
    dag.put("in", ["transitive-dimension"])
    dag.put("enclosing-dimension", ["dimension"])
    dag.put("about", ["enclosing-dimension"])
    dag.put("reversed-dimension", ["dimension"])
    dag.put("shared-with", ["reversed-dimension"])
    return dag


PLACES = ("asia", "japan", "tokyo", "osaka", "photo", "guidebook",
          "staff", "alice", "memo")
FACTS = (("japan", "in(asia)"), ("tokyo", "in(japan)"),
         ("photo", "in(tokyo)"), ("photo", "in(japan)"),   # redundant
         ("guidebook", "about(tokyo)"),
         ("alice", "staff"), ("memo", "shared-with(staff)"))


class TestNarrowerRelations(unittest.TestCase):
    """§5.1 (contract 0.3): a relation head filed under another head of its
    kind is a narrower relation; G1 holds whenever it is declared."""

    def build(self, facts, narrower_first=True, dag=None):
        dag = declare_relations(dag if dag is not None else ontodag.OntoDAG())
        if narrower_first:
            dag.put("topic", ["about"])
        else:
            dag.put("topic", ["enclosing-dimension"])
        for name in PLACES:
            dag.put(name, [])
        for child, parent in facts:
            dag.put(child, [parent])
        if not narrower_first:
            dag.put("topic", ["about"])
        return dag

    FACTS = (("japan", "in(asia)"), ("tokyo", "in(japan)"),
             ("guidebook", "topic(tokyo)"), ("guidebook", "about(japan)"))

    def test_the_narrower_term_answers_the_broader_query(self):
        dag = self.build(self.FACTS)
        self.assertTrue(dag.is_below("topic(tokyo)", "about(asia)"))
        self.assertFalse(dag.is_below("about(tokyo)", "topic(tokyo)"))
        self.assertIn("guidebook", {n.name for n in dag.get(["about(asia)"])})

    def test_g1_declaring_late_reaches_the_same_root(self):
        roots = {self.build(self.FACTS, first, eager(MemoryBytesStore())).commit()
                 for first in (True, False)}
        self.assertEqual(len(roots), 1)


class TestDimensionsOverNodes(unittest.TestCase):
    """§5.1 (contract 0.2): relations to entities as dimension terms keep
    G1, G2 and G4, and the strictness guard never makes a merge refuse."""

    TERMS = [f"{head}({place})" for head in ("in", "about", "shared-with")
             for place in PLACES]

    def build(self, facts, dag=None):
        dag = declare_relations(dag if dag is not None else ontodag.OntoDAG())
        for name in PLACES:
            dag.put(name, [])
        for child, parent in facts:
            dag.put(child, [parent])
        return dag

    def test_g1_filing_order_does_not_affect_the_root(self):
        roots = {self.build(order, eager(MemoryBytesStore())).commit()
                 for order in (FACTS, FACTS[::-1])}
        self.assertEqual(len(roots), 1)

    def test_g4_located_in_is_not_being(self):
        dag = self.build(FACTS)
        self.assertTrue(dag.is_below("photo", "in(asia)"))
        self.assertTrue(dag.is_below("guidebook", "about(japan)"))
        # the photo is in Japan, not a Japan; the guidebook is about
        # Tokyo, not in it
        self.assertFalse(dag.is_below("photo", "japan"))
        self.assertFalse(dag.is_below("guidebook", "in(tokyo)"))
        # what is for the staff is for Alice; the memo is not Alice
        self.assertTrue(dag.is_below("memo", "shared-with(alice)"))
        self.assertFalse(dag.is_below("memo", "alice"))

    def test_g2_truths_survive_merge(self):
        ours = self.build(FACTS)
        theirs = self.build([("osaka", "in(japan)")])
        before = {(n, t) for n in PLACES for t in self.TERMS
                  if ours.is_below(n, t)}
        ours.merge(theirs)
        after = {(n, t) for n in PLACES for t in self.TERMS
                 if ours.is_below(n, t)}
        self.assertLess(before, after)
        self.assertIn(("osaka", "in(asia)"), after)

    def test_the_guard_refuses_put_but_never_merge(self):
        dag = self.build(FACTS)
        with self.assertRaises(ValueError):
            dag.put("asia", ["in(tokyo)"])     # Asia inside its own part
        # each store is consistent, their union is not: the merge keeps
        # both facts as data (O5)
        a = self.build([("tokyo", "in(japan)")])
        b = self.build([("japan", "in(tokyo)")])
        a.merge(b)
        self.assertTrue(a.is_below("tokyo", "in(japan)"))
        self.assertTrue(a.is_below("japan", "in(tokyo)"))


class TestG7MonotoneVersions(unittest.TestCase):
    """G7: within one major contract version and one major registry
    version, a newer ontodag never takes away an answer about a fixed
    store. `tests/fixtures/g7.od` is a fixed store over every kind, and
    `g7-answers.json` what it answered when recorded (contract 0.3,
    registry 4.3). Every recorded true `is_below` stays true and every
    recorded `get` answer stays inside the new one; recorded falses may
    become true, since gaining answers is allowed. A failure here means a
    release removes an answer: that is a major bump, and only then is the
    record regenerated (tests/fixtures/make_g7.py says how)."""

    fixture, answers, least = "g7.od", "g7-answers.json", 200

    @classmethod
    def setUpClass(cls):
        import json
        import os
        from ontodag import native
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
        cls.dag = native.load(os.path.join(here, cls.fixture))
        with open(os.path.join(here, cls.answers)) as f:
            cls.record = json.load(f)

    def test_the_record_belongs_to_these_majors(self):
        from ontodag.dimensions import REGISTRY_VERSION   # published there (REFERENCE.md)
        major = lambda v: v.split(".")[0]
        self.assertEqual(major(self.record["contract"]), major(ontodag.CONTRACT_VERSION),
                         "a new contract major: regenerate the record deliberately")
        self.assertEqual(major(self.record["registry"]), major(REGISTRY_VERSION),
                         "a new registry major: regenerate the record deliberately")

    def test_every_recorded_true_below_stays_true(self):
        lost = [(a, b) for a, b in self.record["below"] if not self.dag.is_below(a, b)]
        self.assertEqual(lost, [], "answers taken away within one major")
        self.assertGreater(len(self.record["below"]), self.least)

    def test_every_recorded_answer_stays_inside_the_new_one(self):
        for case in self.record["get"]:
            now = names(self.dag.get(case["terms"]))
            self.assertLessEqual(set(case["answer"]), now, case["terms"])


class TestG7SecondRecord(TestG7MonotoneVersions):
    """G7's second record (tests/fixtures/make_g7b.py), taken under contract
    0.5 / registry 4.3 before the 2026-10 review's decided changes were
    built: graph-kind compounds filed as their parts, relation compounds,
    role terms naming cells and places, and an item a merge left under two
    overlapping values of one head. The same rule: never regenerated to
    make a failure pass."""

    fixture, answers, least = "g7b.od", "g7b-answers.json", 300


class TestG8SignalledSpellings(unittest.TestCase):
    """G8: a valid name's canonical spelling, and what a given set of filings
    stores, change only together with `REGISTRY_VERSION`'s minor.
    `tests/fixtures/g8-spellings.json` holds fixed filings over every kind,
    the spelling of inputs over every kind, and the stored form of the
    filings, recorded under one registry version. A failure means a release
    changes a spelling or a stored form: bump the registry minor, name the
    `ontodag.migrate` step in CHANGELOG, then rerun
    `tests/fixtures/make_g8.py`. Never rerun it without the bump."""

    @classmethod
    def setUpClass(cls):
        import json
        import os
        from ontodag import native, prelude
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
        with open(os.path.join(here, "g8-spellings.json"), encoding="utf-8") as f:
            cls.record = json.load(f)
        cls.dag = ontodag.OntoDAG()
        prelude.apply(cls.dag)
        for name, parents in cls.record["filings"]:
            cls.dag.put(name, parents)
        own = set(prelude.prelude_dag().nodes)
        cls.stored = [line for line in native.dumps(cls.dag).splitlines()
                      if line.split()[0].strip("'") not in own
                      and not line.startswith("#")]

    def test_the_record_belongs_to_this_registry_version(self):
        from ontodag.dimensions import REGISTRY_VERSION
        self.assertEqual(
            self.record["registry"], REGISTRY_VERSION,
            "REGISTRY_VERSION moved: record its spellings with "
            "tests/fixtures/make_g8.py, and name the migrate step in CHANGELOG")

    def test_every_spelling_is_as_recorded(self):
        from ontodag.surface import elaborate
        changed = [(term, recorded, elaborate(term, self.dag))
                   for term, recorded in self.record["spellings"]
                   if elaborate(term, self.dag) != recorded]
        self.assertEqual(changed, [], "a spelling changed within one registry "
                         "version: bump REGISTRY_VERSION's minor (G8)")
        self.assertGreater(len(self.record["spellings"]), 40)

    def test_the_same_filings_store_the_same(self):
        self.assertEqual(self.stored, self.record["stored"],
                         "the same filings store something else within one "
                         "registry version: bump REGISTRY_VERSION's minor (G8)")


class TestG9WritesAndReplays(unittest.TestCase):
    """G9: a replay reaches the same store from the same filings in any
    order; a single write is checked against the store as it is, and the
    cases where order then matters are the three stated in §3 (ingest's
    order-freedom is tested in tests/test_cli.py)."""

    def base(self):
        from ontodag import prelude
        dag = ontodag.OntoDAG()
        prelude.apply(dag)
        for name, parents in (("from", ["geo"]), ("city", []), ("france", [])):
            dag.put(name, parents)
        return dag

    def peer(self, filings):
        """A peer that filed `filings` in an order its author could."""
        dag = self.base()
        for name, parents in filings:
            dag.put(name, parents)
        return dag

    def test_a_merge_does_not_depend_on_order(self):
        import itertools
        from ontodag import native
        # One peer has `home` as a plain city, the other has it placed in
        # geo with a role term naming it: an author holding the first could
        # not file the second's term, a merge takes both in either order.
        a = self.peer([("home", ["city"]), ("paris", ["city", "in(france)"]),
                       ("louvre", ["in(paris)"])])
        b = self.peer([("home", ["geo(u09t)"]), ("parcel", ["from(home)"])])
        stores = set()
        for first, second in itertools.permutations((a, b)):
            dag = self.base()
            dag.merge(first)
            dag.merge(second)
            stores.add(native.dumps(dag))
            self.assertTrue(dag.is_below("parcel", "from(u09)"))
            self.assertTrue(dag.is_below("louvre", "in(france)"))
        self.assertEqual(len(stores), 1)
        # Loading a stored file is a replay too: it reads back what it wrote.
        text = stores.pop()
        self.assertEqual(native.dumps(native.loads(text)), text)

    def test_single_writes_are_refused_in_the_stated_cases(self):
        cases = [
            # 1. what a write names must exist first
            [("dog", ["animal"])],
            [("job", ["in(nowhere)"])],
            [("price-tag", ["mass(5zz)"])],
            # 2. a role term's place must already be in its dimension
            [("home", ["city"]), ("parcel", ["from(home)"])],
            [("parcel", ["from(home)"])],          # no place yet (0.6)
            [("parcel", ["geo(home)"])],           # no geohash either
            # 3. of two writes that contradict, the later is refused
            [("crate", ["mass(3kg)"]), ("crate", ["mass(5kg)"])],
            [("a", ["city"]), ("city", ["a"])],
            [("tokyo", ["city"]), ("tokyo", ["in(tokyo)"])],
        ]
        for writes in cases:
            with self.subTest(writes=writes):
                dag = self.base()
                for name, parents in writes[:-1]:
                    dag.put(name, parents)
                with self.assertRaises(ValueError):
                    dag.put(*writes[-1])

    def test_in_the_other_order_the_same_writes_are_accepted(self):
        for writes in ([("animal", []), ("dog", ["animal"])],
                       [("home", ["geo(u09t)"]), ("parcel", ["from(home)"]),
                        ("home", ["city"])]):
            with self.subTest(writes=writes):
                dag = self.base()
                for name, parents in writes:
                    dag.put(name, parents)


class TestAsOfClause(unittest.TestCase):
    """§4: a root-pinned answer is an immutable, replayable fact."""

    def test_answers_at_a_root_never_move(self):
        blobs = MemoryBytesStore()
        w = eager(blobs)
        w.put("pet", [])
        w.put("cat", ["pet"])
        root1 = w.commit()
        w.put("dog", ["pet"])
        root2 = w.commit()

        at1 = ontodag.LazyOntoDAG(RecordStore.at(root1, blobs))
        at2 = ontodag.LazyOntoDAG(RecordStore.at(root2, blobs))
        self.assertEqual(names(at1.get(["pet"])), {"cat"})
        self.assertEqual(names(at2.get(["pet"])), {"cat", "dog"})
        # replayable: a fresh reader at the old root answers identically
        again = ontodag.LazyOntoDAG(RecordStore.at(root1, blobs))
        self.assertEqual(names(again.get(["pet"])), {"cat"})


if __name__ == "__main__":
    unittest.main()
