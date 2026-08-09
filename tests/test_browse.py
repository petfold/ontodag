"""`ontodag.browse` — the refinements a browser offers, against `get` itself.

The property that matters is not "the list looks reasonable" but that the
list *tells the truth about what a click will do*: the number beside a
refinement has to be the size of the answer you land on, and every offered
choice has to lead somewhere you are not already. Both are checked against
`get`, which is the authority, rather than against a fixture.
"""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ontodag.browse import browse, focus, refinements  # noqa: E402
from ontodag.dag import OntoDAG  # noqa: E402
from ontodag.prelude import prelude_dag  # noqa: E402


def travel_dag():
    dag = OntoDAG()
    for name, parents in [
        ("Travel", []), ("Japan", []), ("Document", []),
        ("Flight", ["Travel"]), ("Hotel", ["Travel"]),
        ("JAL7", ["Flight", "Japan"]), ("NH209", ["Flight", "Japan"]),
        ("BA1", ["Flight"]), ("Ryokan", ["Hotel", "Japan"]),
        ("boarding-pass.pdf", ["Document", "JAL7"]),
    ]:
        dag.put(name, parents)
    return dag


def random_dag(seed, size=26):
    rng = random.Random(seed)
    dag = OntoDAG()
    names = []
    for index in range(size):
        name = f"n{index}"
        parents = rng.sample(names, min(len(names), rng.randint(0, 2)))
        dag.put(name, parents)
        names.append(name)
    return dag, names


class TestTheOfferedChoicesAreTrue(unittest.TestCase):
    """Each refinement's count must be exactly what clicking it returns."""

    def _check(self, dag, terms):
        view = browse(dag, [list(terms)])
        for name, matching in view.refine:
            landed = dag.get(list(terms) + [name])
            self.assertEqual(len(landed), matching,
                             f"{terms} + {name}: says {matching}, gives "
                             f"{len(landed)}")

    def test_on_the_worked_example(self):
        dag = travel_dag()
        for terms in ([], ["Travel"], ["Japan"], ["Flight"],
                      ["Japan", "Flight"], ["Document"]):
            self._check(dag, terms)

    def test_on_random_graphs(self):
        for seed in range(12):
            dag, names = random_dag(seed)
            self._check(dag, [])
            for name in names[:6]:
                self._check(dag, [name])

    def test_every_choice_leads_somewhere_new(self):
        # A refinement holding for the whole answer would return that same
        # answer — a click that appears to do nothing. None may be offered.
        for seed in range(12):
            dag, names = random_dag(seed)
            for terms in ([], [names[0]], [names[3]]):
                here = len(dag.get(list(terms)))
                for name, matching in browse(dag, [list(terms)]).refine:
                    self.assertLess(matching, here, f"{terms} + {name}")
                    self.assertGreater(matching, 0, f"{terms} + {name}")


class TestWhatIsHere(unittest.TestCase):
    def test_the_empty_query_is_everything(self):
        dag = travel_dag()
        view = browse(dag, [[]])
        self.assertEqual(view.count, len(dag.nodes) - 1)   # all but the root
        self.assertNotIn("*", [name for name, _, _ in view.here])

    def test_no_queries_at_all_is_the_empty_query(self):
        dag = travel_dag()
        self.assertEqual(browse(dag, []).count, browse(dag, [[]]).count)

    def test_here_carries_whether_anything_hangs_below(self):
        dag = travel_dag()
        here = {name: children for name, children, _ in browse(dag, [[]]).here}
        self.assertTrue(here["Flight"])
        self.assertFalse(here["BA1"])

    def test_a_union_is_the_union(self):
        dag = travel_dag()
        both = browse(dag, [["Hotel"], ["Flight"]])
        self.assertEqual({name for name, _, _ in both.here},
                         {"Ryokan", "BA1", "JAL7", "NH209",
                          "boarding-pass.pdf"})

    def test_an_unknown_term_finds_nothing_rather_than_raising(self):
        self.assertEqual(browse(travel_dag(), [["nosuch"]]).count, 0)


class TestVirtualTerms(unittest.TestCase):
    """A parametric term needs no node, so it has no ancestors to be counted
    out of its own refinements — it has to be excluded by name."""

    def setUp(self):
        self.dag = OntoDAG()
        self.dag.merge(prelude_dag())
        self.dag.put("JAL7", ["time(2026-08-15)"])
        self.dag.put("NH209", ["time(2026-08-22)"])

    def test_a_range_nobody_filed_still_answers(self):
        view = browse(self.dag, [["time(2026-08-01..2026-08-20)"]])
        self.assertEqual({name for name, _, _ in view.here},
                         {"JAL7", "time(2026-08-15T00:00:00Z"
                                  "..2026-08-15T23:59:59Z)"})

    def test_the_asked_term_is_not_offered_back(self):
        term = "time(2026-08-01..2026-08-20)"
        offered = {name for name, _ in browse(self.dag, [[term]]).refine}
        self.assertNotIn(term, offered)


class TestSmallAnswers(unittest.TestCase):
    def test_a_single_item_offers_nothing(self):
        dag = travel_dag()
        self.assertEqual(browse(dag, [["Document", "JAL7"]]).refine, [])

    def test_an_empty_answer_offers_nothing(self):
        dag = travel_dag()
        self.assertEqual(browse(dag, [["Hotel", "Document"]]).refine, [])


class TestSampling(unittest.TestCase):
    def test_a_capped_computation_says_so(self):
        dag = travel_dag()
        full = browse(dag, [[]])
        self.assertFalse(full.sampled)
        capped = browse(dag, [[]], sample=3)
        self.assertTrue(capped.sampled)

    def test_the_answer_itself_is_never_sampled(self):
        # The cap is on how the *choices* are computed. The answer is always
        # complete, or the count on screen would be a lie.
        dag = travel_dag()
        self.assertEqual(browse(dag, [[]], sample=2).count,
                         browse(dag, [[]]).count)


class TestFocus(unittest.TestCase):
    def test_it_reports_both_directions(self):
        detail = focus(travel_dag(), "JAL7")
        self.assertEqual(detail["above"], ["Flight", "Japan"])
        self.assertEqual(detail["below"], ["boarding-pass.pdf"])
        self.assertEqual(detail["count"], 1)

    def test_a_missing_name_is_none_not_an_error(self):
        self.assertIsNone(focus(travel_dag(), "nosuch"))

    def test_a_removed_parent_does_not_linger(self):
        # `parents` can hold a stale node after a removal; the live check is
        # the same one `_print_dag` makes.
        dag = travel_dag()
        dag.remove("Flight")
        self.assertNotIn("Flight", focus(dag, "JAL7")["above"])


class TestRefinementsDirectly(unittest.TestCase):
    def test_it_takes_any_iterable_of_items(self):
        dag = travel_dag()
        answer = dag.get(["Japan"])
        offered, sampled = refinements(dag, answer)
        # Flight matches three, not two: `boarding-pass.pdf` is under it too,
        # via JAL7. Subsumption is the whole point, and it is exactly the sort
        # of count a hand-written expectation gets wrong — which is why the
        # counts are checked against `get` elsewhere in this file.
        self.assertEqual(dict(offered), {"Flight": 3, "Hotel": 1,
                                         "Document": 1, "JAL7": 1})
        self.assertFalse(sampled)

    def test_the_root_is_never_a_choice(self):
        dag = travel_dag()
        offered, _ = refinements(dag, dag.get([]))
        self.assertNotIn("*", dict(offered))


if __name__ == "__main__":
    unittest.main()
