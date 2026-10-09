"""Removal and the terms that name what it removes (decided 2026-10-09,
DIMENSIONS.md §14).

A term names categories (`in(paris)`, `about(paris)`, `shared-with(alice)`,
`transport(bicycle)`, a role's `from(my_home)`), so a category may not stop
existing while a term still names it. Before, the term stayed behind naming
nothing: the Louvre, `in(paris)`, silently stopped being in France, and a
share naming a removed contact came back by itself when the contact was
added again. Now removal refuses, naming the terms, unless they go too:
named in the same call, or all of them with `with_terms`. A removed term is
contracted the way `remove` contracts any category: what was under it moves
to the terms just above it (`in(paris)` → `in(city)`, `in(france)`), and a
share, which must never widen, ends instead. `rename` is the way out when
the name was the mistake.
"""

import random
import unittest

from recordstore import MemoryBytesStore, RecordStore

from ontodag import prelude, sharing
from ontodag.dag import OntoDAG
from ontodag.eager import EagerOntoDAG
from ontodag.lazy import SparseOntoDAG


def edge_set(dag):
    return {(parent.name, child.name)
            for parent in dag.nodes.values() for child in parent.neighbors
            if dag.nodes.get(parent.name) is parent}


def parents(dag, name):
    return {parent.name for parent in dag.nodes[name].parents
            if dag.nodes.get(parent.name) is parent}


PARIS = (("city", []), ("france", []), ("district", []), ("person", []),
         ("paris", ["city", "in(france)"]), ("alice", ["person"]),
         ("louvre", ["in(paris)"]), ("photo", ["about(paris)"]),
         ("museum-district", ["district"]),
         ("gallery", ["in(museum-district paris)"]),
         ("plan", ["shared-with(alice)"]), ("memo", ["shared-with(paris)"]))


def world(dag=None, filings=PARIS):
    dag = dag if dag is not None else OntoDAG()
    prelude.apply(dag)
    for name, supers in filings:
        dag.put(name, supers)
    return dag


PARIS_TERMS = ["about(paris)", "in(museum-district paris)", "in(paris)",
               "shared-with(paris)"]


class TestTheGuard(unittest.TestCase):
    def test_a_named_category_is_refused_and_nothing_moves(self):
        dag = world()
        before = edge_set(dag)
        with self.assertRaises(ValueError) as caught:
            dag.remove("paris")
        message = str(caught.exception)
        for term in PARIS_TERMS:
            self.assertIn(f"{term} (1 item)", message)
        self.assertIn("--with-terms", message)
        self.assertIn("rename paris", message)
        self.assertEqual(edge_set(dag), before)

    def test_every_kind_of_term_guards(self):
        dag = world()
        dag.put("graph-dimension", ["dimension"])
        dag.put("transport", ["graph-dimension"])
        dag.put("bicycle", [])
        dag.put("courier-job", ["transport(bicycle)"])
        dag.put("from", ["geo"])
        dag.put("home", ["geo(u09t)"])
        dag.put("parcel", ["from(home)"])
        for name, term in (("bicycle", "transport(bicycle)"),
                           ("home", "from(home)"),
                           ("alice", "shared-with(alice)"),
                           ("france", "in(france)")):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError,
                                            rf"{name} is named by .*{term.replace('(', '[(]').replace(')', '[)]')}"):
                    dag.remove(name)

    def test_naming_the_terms_in_the_same_call_lets_it_through(self):
        named, flagged = world(), world()
        named.remove_many(["paris", *PARIS_TERMS])
        flagged.remove("paris", with_terms=True)
        self.assertEqual(edge_set(named), edge_set(flagged))
        self.assertNotIn("paris", named.nodes)

    def test_a_refusal_anywhere_leaves_everything(self):
        dag = world()
        dag.put("rome", ["city"])
        before = edge_set(dag)
        with self.assertRaisesRegex(ValueError, "paris is named by"):
            dag.remove_many(["rome", "paris"])
        self.assertEqual(edge_set(dag), before)      # rome too: checked first

    def test_a_category_no_term_names_goes_as_before(self):
        dag = world()
        dag.put("rome", ["city"])
        dag.put("colosseum", ["rome"])
        dag.remove("rome")
        self.assertEqual(parents(dag, "colosseum"), {"city"})

    def test_the_cone_deletion_is_guarded_too(self):
        dag = world()
        dag.put("paris", ["france"])
        before = edge_set(dag)
        with self.assertRaisesRegex(ValueError, r"france is named by in\(france\)"):
            dag.remove_cone(["france"])
        self.assertEqual(edge_set(dag), before)
        dag.remove_cone(["france"], with_terms=True)
        self.assertNotIn("france", dag.nodes)
        self.assertNotIn("in(france)", dag.nodes)
        # France had nothing above it, so paris is in something unnamed.
        self.assertEqual(parents(dag, "paris"), {"city", "in"})


class TestRemovingTheTermsToo(unittest.TestCase):
    def test_what_was_under_a_term_moves_to_the_terms_just_above_it(self):
        dag = world()
        gone, moves = dag.removal_plan(["paris"], with_terms=True)
        self.assertEqual(gone, sorted(["paris", *PARIS_TERMS]))
        self.assertEqual(moves, {
            "about(paris)": ["about(city)", "about(france)"],
            "in(museum-district paris)": ["in(city museum-district)", "in(france)"],
            "in(paris)": ["in(city)", "in(france)"],
            "shared-with(paris)": ["shared-with"]})
        dag.remove("paris", with_terms=True)
        self.assertEqual(parents(dag, "louvre"), {"in(city)", "in(france)"})
        self.assertEqual(parents(dag, "photo"), {"about(city)", "about(france)"})
        # In one thing that is a museum district and in Paris: so in one that
        # is a museum district and a city, and in France — but not in one
        # thing that is both a museum district and France.
        self.assertEqual(parents(dag, "gallery"),
                         {"in(city museum-district)", "in(france)"})
        self.assertFalse(any("paris" in name for name in dag.nodes))

    def test_the_result_is_the_store_filed_that_way(self):
        removed = world()
        removed.remove("paris", with_terms=True)
        direct = world(filings=(
            ("city", []), ("france", []), ("district", []), ("person", []),
            ("alice", ["person"]), ("louvre", ["in(city)", "in(france)"]),
            ("photo", ["about(city)", "about(france)"]),
            ("museum-district", ["district"]),
            ("gallery", ["in(city museum-district)", "in(france)"]),
            ("plan", ["shared-with(alice)"]), ("memo", ["shared-with"])))
        self.assertEqual(edge_set(removed), edge_set(direct))

    def test_a_share_never_widens(self):
        dag = world()
        dag.put("bob", ["person"])
        dag.put("memo2", ["shared-with(bob)"])
        dag.remove("alice", with_terms=True)
        self.assertEqual(parents(dag, "plan"), {"shared-with"})
        self.assertEqual(sorted(sharing.reach(dag, ["bob"])), ["memo2"])
        self.assertNotIn("plan", sharing.reach(dag, ["person"]))
        # And adding her again brings nothing back.
        dag.put("alice", ["person"])
        self.assertEqual(sorted(sharing.reach(dag, ["alice"])), [])

    def test_removing_a_group_ends_what_was_shared_with_it(self):
        dag = world()
        dag.put("team", ["person"])
        dag.put("bob", ["team"])
        dag.put("roadmap", ["shared-with(team)"])
        self.assertIn("roadmap", sharing.reach(dag, ["bob"]))
        dag.remove("team", with_terms=True)
        self.assertEqual(parents(dag, "bob"), {"person"})
        self.assertNotIn("roadmap", sharing.reach(dag, ["bob"]))

    def test_a_term_removed_on_its_own_follows_the_same_rule(self):
        for extra in ((), (("unrelated", ["about(france)"]),)):
            with self.subTest(extra=extra):
                dag = world(filings=PARIS + extra)
                dag.remove("about(paris)")
                # Whatever else happens to be filed: the terms above it, not
                # the bare head and not only the ones that already existed.
                self.assertEqual(parents(dag, "photo"),
                                 {"about(city)", "about(france)"})

    def test_a_nested_term_follows(self):
        dag = world(filings=PARIS + (("ring", ["in(in(paris))"]),))
        dag.remove("paris", with_terms=True)
        # In something in Paris: so in a city, and in France.
        self.assertEqual(parents(dag, "ring"), {"in(city)", "in(france)"})

    def test_a_graph_kind_term_follows_its_constraint_up(self):
        dag = world()
        dag.put("graph-dimension", ["dimension"])
        dag.put("transport", ["graph-dimension"])
        dag.put("vehicle", [])
        dag.put("bicycle", ["vehicle"])
        dag.put("job", ["transport(bicycle)"])
        dag.remove("bicycle", with_terms=True)
        self.assertEqual(parents(dag, "job"), {"transport(vehicle)"})

    def test_a_role_term_follows_its_place_up(self):
        dag = world()
        dag.put("from", ["geo"])
        dag.put("ljubljana", ["geo(u2e4)"])
        dag.put("home", ["ljubljana"])
        dag.put("parcel", ["from(home)"])
        dag.remove("home", with_terms=True)
        self.assertEqual(parents(dag, "parcel"), {"from(ljubljana)"})

    def test_counts_and_reduction_hold(self):
        for seed in range(12):
            dag = world()
            rng = random.Random(seed)
            for k in range(8):
                dag.put(f"x{k}", [rng.choice(["in(paris)", "about(paris)",
                                              "in(france)", "city",
                                              "shared-with(alice)"])])
            dag.remove(rng.choice(["paris", "alice", "france"]), with_terms=True)
            for node in dag.nodes.values():
                self.assertEqual(node.descendant_count,
                                 len(dag.get_descendants(node, computed=False)),
                                 (seed, node.name))
                for child in node.neighbors:
                    others = [p for p in child.parents
                              if p is not node and dag.nodes.get(p.name) is p]
                    self.assertFalse(any(dag.is_below(p.name, node.name)
                                         for p in others),
                                     (seed, node.name, child.name))

    def test_eager_and_sparse_writers_commit_one_root(self):
        blobs = MemoryBytesStore()
        base = world(EagerOntoDAG(RecordStore(blobs)))
        root = base.commit()
        for act in (lambda w: w.remove("paris", with_terms=True),
                    lambda w: w.remove("alice", with_terms=True),
                    lambda w: w.remove_cone(["district"], with_terms=True),
                    lambda w: w.rename("paris", "paris-fr")):
            roots = set()
            for writer in (EagerOntoDAG, SparseOntoDAG):
                w = writer(RecordStore(blobs, root=root))
                w.put("warm-up", ["city"])
                act(w)
                roots.add(w.commit())
            self.assertEqual(len(roots), 1)


TYPO = (("city", []), ("france", []), ("from", ["geo"]),
        ("NAME", ["city", "in(france)", "geo(u09t)"]),
        ("louvre", ["in(NAME)"]), ("photo", ["about(NAME)"]),
        ("parcel", ["from(NAME)"]), ("notre-dame", ["NAME"]),
        ("ring", ["in(in(NAME))"]))


def named(spelling):
    return tuple((name.replace("NAME", spelling),
                  [s.replace("NAME", spelling) for s in supers])
                 for name, supers in TYPO)


class TestRename(unittest.TestCase):
    def test_a_misspelling_becomes_the_store_with_the_right_name(self):
        dag = world(filings=named("pairs"))
        respelled = dag.rename("pairs", "paris")
        self.assertEqual(respelled, {"about(pairs)": "about(paris)",
                                     "from(pairs)": "from(paris)",
                                     "in(pairs)": "in(paris)",
                                     "in(in(pairs))": "in(in(paris))"})
        self.assertEqual(edge_set(dag), edge_set(world(filings=named("paris"))))

    def test_into_an_existing_category_the_two_become_one(self):
        dag = world(filings=named("paris") + (("pairs", ["city"]),
                                              ("cafe", ["in(pairs)"]),
                                              ("tower", ["pairs"])))
        dag.rename("pairs", "paris")
        self.assertNotIn("pairs", dag.nodes)
        self.assertNotIn("in(pairs)", dag.nodes)
        self.assertEqual(parents(dag, "cafe"), {"in(paris)"})
        self.assertEqual(parents(dag, "tower"), {"paris"})
        self.assertTrue(dag.is_below("cafe", "in(france)"))

    def test_it_refuses_terms_heads_registry_nodes_and_the_root(self):
        dag = world(filings=named("paris"))
        before = edge_set(dag)
        for old, new in (("in(paris)", "x"), ("geo", "place"), ("from", "x"),
                         ("dimension", "x"), ("*", "x"), ("paris", "in(x)"),
                         ("paris", "from"), ("nowhere", "x")):
            with self.subTest(old=old, new=new):
                with self.assertRaises(ValueError):
                    dag.rename(old, new)
        self.assertEqual(edge_set(dag), before)

    def test_nothing_ends_up_inside_itself(self):
        dag = world(filings=named("paris") + (("ile", ["in(paris)"]),))
        before = edge_set(dag)
        with self.assertRaisesRegex(ValueError, "inside itself"):
            dag.rename("paris", "ile")
        self.assertEqual(edge_set(dag), before)

    def test_metadata_and_payload_travel(self):
        blobs = MemoryBytesStore()
        dag = world(EagerOntoDAG(RecordStore(blobs)), filings=named("pairs"))
        dag.put("pairs", ["city"], payload="ref-123", meta={"label": "Paris"})
        dag.rename("pairs", "paris")
        root = dag.commit()
        back = EagerOntoDAG(RecordStore.at(root, blobs))
        self.assertEqual(back.nodes["paris"].metadata, {"label": "Paris"})
        self.assertEqual(back._payloads.get("paris"), "ref-123")


if __name__ == "__main__":
    unittest.main()
