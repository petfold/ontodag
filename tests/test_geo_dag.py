"""Rectangle values in a graph (question 29, DIMENSIONS.md §22): filing,
queries, roles, the half-circle rule, and the index that finds a value's
computed hops without scanning its head's star."""
import random
import unittest
from unittest import mock

from ontodag import dimensions as dims
from ontodag import native, prelude
from ontodag.dag import OntoDAG


def names(items):
    return {item.name for item in items if "(" not in item.name}


def edge_set(dag):
    return {(parent.name, child.name)
            for parent in dag.nodes.values() for child in parent.neighbors}


def sited(resident=True):
    dag = OntoDAG()
    dag._resident = resident
    prelude.apply(dag)
    dag.put("rectangle-dimension", ["dimension"])
    dag.put("site", ["rectangle-dimension"])
    return dag


class TestFilingAndQueries(unittest.TestCase):
    def test_places_and_squares(self):
        dag = sited()
        dag.put("eiffel-tower", ["site(48.8584,2.2945)"])
        dag.put("louvre", ["site(48.8606,2.3376)"])
        dag.put("big-ben", ["site(51.5007,-0.1246)"])
        self.assertEqual(names(dag.get(["site(48.8..48.9,2.2..2.4)"])),
                         {"eiffel-tower", "louvre"})
        self.assertEqual(names(dag.get(["site(48.8584,2.2945±500m)"])), {"eiffel-tower"})
        self.assertTrue(dag.is_below("eiffel-tower", "site(48..49,2..3)"))
        self.assertFalse(dag.is_below("big-ben", "site(48..49,2..3)"))

    def test_across_the_180th_meridian(self):
        dag = sited()
        dag.put("atoll", ["site(-9.38,179.89±10km)"])
        dag.put("shop", ["site(-9.38..-9.38,-179.99..-179.99)"])
        dag.put("suva", ["site(-18.1416,178.4419)"])
        self.assertEqual(names(dag.get(["site(-10..-9,179.5..-179.5)"])), {"atoll", "shop"})
        self.assertEqual(names(dag.get(["site(-20..0,178..-179)"])), {"atoll", "shop", "suva"})
        self.assertEqual(names(dag.get(["site(-90..90,-179..179)"])), {"suva"})

    def test_two_values_fold_to_their_meet(self):
        dag = sited()
        dag.put("crate", ["site(0..2,0..2)", "site(1..3,1..3)"])
        self.assertEqual({p.name for p in dag.nodes["crate"].parents}, {"site(1..2,1..2)"})
        with self.assertRaisesRegex(ValueError, "provably disjoint"):
            dag.put("box", ["site(0..1,0..1)", "site(2..3,2..3)"])


class TestHalfCircleRule(unittest.TestCase):
    def test_a_wide_value_is_refused_when_written_and_may_be_queried(self):
        dag = sited()
        dag.put("crate", ["site(0..1,10..20)"])
        before = edge_set(dag)
        with self.assertRaisesRegex(ValueError, "less than half the circle"):
            dag.put("x", ["site(-1..1,-170..170)"])
        self.assertEqual(edge_set(dag), before)
        dag.put("band", ["site(-1..1,-180..180)"])         # all of it is fine
        dag.put("narrow", ["site(-1..1,170..-170)"])        # the narrow way across 180
        self.assertEqual(names(dag.get(["site(-5..5,-170..170)"])), {"crate"})

    def test_a_replay_keeps_a_wide_value_and_two_of_them_stay_unfolded(self):
        dag = sited()
        dag.put("crate", ["site(0..1,10..20)"])
        text = native.dumps(dag) + (
            "'site(-10..10,-175..175)' site\n'site(-10..10,170..-170)' site\n"
            "parcel 'site(-10..10,-175..175)' 'site(-10..10,170..-170)'\n")
        text = "\n".join(line for line in text.splitlines() if not line.startswith("#:"))
        loaded = native.loads(text)
        self.assertEqual({p.name for p in loaded.nodes["parcel"].parents},
                         {"site(-10..10,-175..175)", "site(-10..10,170..-170)"})
        self.assertTrue(loaded.is_below("parcel", "site(-10..10,170..-170)"))
        self.assertEqual(loaded.contradictions(), [])
        with self.assertRaisesRegex(ValueError, "two separate pieces"):
            loaded.meet("site(-10..10,-175..175)", "site(-10..10,170..-170)")
        with self.assertRaisesRegex(ValueError, "two separate pieces"):
            loaded.put("box", ["site(-10..10,-175..175)", "site(-10..10,170..-170)"])


class TestRoles(unittest.TestCase):
    def test_a_role_takes_a_place_or_a_rectangle_by_the_bases_name(self):
        dag = sited()
        dag.put("from", ["site"])
        dag.put("eiffel-tower", ["site(48.8584,2.2945)"])
        dag.put("parcel", ["from(eiffel-tower)"])
        dag.put("drone", ["from(site(48.85..48.87,2.28..2.30))"])
        self.assertEqual(names(dag.get(["from(site(48.8..48.9,2.2..2.4))"])), {"parcel", "drone"})
        for bad in ("from(sydney)", "from(48..49,2..3)"):
            with self.assertRaisesRegex(ValueError, "no place filed in the 'site' dimension"):
                dag.put("y", [bad])


def random_world(seed, resident, size=120):
    rnd = random.Random(seed)
    dag = sited(resident)
    dag.put("from", ["site"])
    places = []

    def rect():
        lat = rnd.uniform(-80, 80)
        lon = rnd.choice([rnd.uniform(-180, 180), rnd.uniform(178, 180), rnd.uniform(-180, -178)])
        h, w = rnd.choice([0, 0.001, 0.05, 1, 10]), rnd.choice([0, 0.001, 0.05, 1, 10])
        if rnd.random() < 0.05:
            return f"site({lat:.3f}..{lat + h:.3f},-180..180)"
        return f"site({lat:.3f}..{lat + h:.3f},{lon:.3f}..{lon + w:.3f})"
    for i in range(size):
        r = rect()
        if rnd.random() < 0.3:
            dag.put(f"p{i}", [r])
            places.append(f"p{i}")
        elif rnd.random() < 0.5 and places:
            dag.put(f"x{i}", [f"from({rnd.choice(places)})"])
        else:
            dag.put(f"x{i}", [r if rnd.random() < 0.6 else f"from({r})"])
    queries = [rect() for _ in range(40)]
    return dag, queries


class TestTheIndexAgreesWithTheScan(unittest.TestCase):
    def test_random_worlds(self):
        for seed in range(6):
            fast, queries = random_world(seed, True)
            slow, _ = random_world(seed, False)
            self.assertEqual(edge_set(fast), edge_set(slow), seed)
            for q in queries:
                for term in (q, f"from({q})"):
                    self.assertEqual(names(fast.get([term])), names(slow.get([term])), (seed, term))


class TestAQueryCostsItsAnswer(unittest.TestCase):
    def test_a_small_query_checks_few_values(self):
        rnd = random.Random(7)
        dag = sited()
        for i in range(3000):
            lat, lon = rnd.uniform(-60, 60), rnd.uniform(-180, 180)
            dag.put(f"x{i}", [f"site({lat:.4f},{lon:.4f})"])
        checks = []
        real = dims._rect_contains

        def counted(a, b):
            checks.append(1)
            return real(a, b)
        with mock.patch.object(dims, "_rect_contains", counted):
            index = dag._value_index("site", dims.KIND_RECT)
            found = index.hops(dag, "site(10..12,20..22)", "site", dims.KIND_RECT, up=False)
        self.assertLess(len(checks), 10 * (len(found) + 1) + 20, (len(checks), len(found)))
        self.assertLess(len(checks), 100)                    # of 3,000 values
