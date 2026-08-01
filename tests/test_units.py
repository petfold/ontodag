"""The registry-v3 unit system (docs/UNITS.md, all verdicts accepted).

What must hold: every unit in the table is an exact positive rational of
its family's SI anchor and round-trips through canonicalization; the
flagship cross-system comparisons are exact (psi vs bar, pound vs kg, inch
vs metre, knot vs km/h); rational values like the shaku work with no base
to divide them; the honest exclusions stay excluded; and migration from
v2 spellings is a pure, idempotent rename.
"""

import subprocess
import sys
import unittest
from fractions import Fraction

from ontodag.dimensions import (KIND_DOMINANCE, KIND_LINEAR,
                                REGISTRY_VERSION, _ANCHOR, _UNITS,
                                canonicalize, contains, registry_compatible)


class TestTable(unittest.TestCase):
    def test_every_family_has_an_anchor_with_factor_one(self):
        families = {family for family, _ in _UNITS.values()}
        self.assertEqual(families, set(_ANCHOR))
        for family, anchor in _ANCHOR.items():
            self.assertEqual(_UNITS[anchor], (family, Fraction(1)))

    def test_every_unit_is_an_exact_positive_rational(self):
        for suffix, (family, factor) in _UNITS.items():
            self.assertIsInstance(factor, Fraction, suffix)
            self.assertGreater(factor, 0, suffix)

    def test_every_unit_round_trips_through_canonicalization(self):
        for suffix, (family, factor) in _UNITS.items():
            if family == "count":
                continue
            once = canonicalize(f"x(1{suffix})", KIND_LINEAR)
            self.assertEqual(canonicalize(once, KIND_LINEAR), once, suffix)
            # ... and denotes exactly its factor of the anchor
            anchor = _ANCHOR[family]
            expected = canonicalize(
                f"x({factor.numerator}/{factor.denominator}{anchor})",
                KIND_LINEAR)
            self.assertEqual(once, expected, suffix)

    def test_registry_version_and_compatibility(self):
        self.assertEqual(REGISTRY_VERSION, "3.2")
        self.assertTrue(registry_compatible("3.9"))
        self.assertFalse(registry_compatible("2"))
        self.assertFalse(registry_compatible("4.0"))


class TestFlagshipExactness(unittest.TestCase):
    def test_tyres_compare_across_the_atlantic(self):
        # 32 psi ≈ 2.206 bar: inside ..3bar, outside ..2bar — exactly.
        self.assertTrue(contains("p(..3bar)", "p(32psi)", KIND_LINEAR))
        self.assertFalse(contains("p(..2bar)", "p(32psi)", KIND_LINEAR))
        self.assertEqual(canonicalize("p(1atm)", KIND_LINEAR),
                         "p(101325Pa)")

    def test_pounds_and_inches_are_exact(self):
        self.assertEqual(canonicalize("w(1lb)", KIND_LINEAR),
                         "w(45359237/100000000kg)")
        self.assertEqual(canonicalize("l(1in)", KIND_LINEAR),
                         "l(127/5000m)")
        self.assertTrue(contains("w(..1lb)", "w(453g)", KIND_LINEAR))
        self.assertFalse(contains("w(..1lb)", "w(454g)", KIND_LINEAR))

    def test_the_shaku_needs_no_base(self):
        self.assertEqual(canonicalize("l(10/33m)", KIND_LINEAR),
                         "l(10/33m)")
        self.assertTrue(contains("l(..1m)", "l(10/33m)", KIND_LINEAR))

    def test_knots_and_kmh_share_a_lattice(self):
        # 1 kn = 1.852 km/h exactly.
        self.assertTrue(contains("v(..2kmh)", "v(1kn)", KIND_LINEAR))
        self.assertFalse(contains("v(..1kmh)", "v(1kn)", KIND_LINEAR))

    def test_electronvolts_since_si_2019(self):
        self.assertEqual(
            canonicalize("e(1eV)", KIND_LINEAR),
            "e(801088317/5000000000000000000000000000J)")

    def test_dominance_units_mix_systems(self):
        # A 19x23x39 cm case fits a 9x10x16 inch box — exactly.
        self.assertTrue(contains("size(9x10x16in)", "size(19x23x39cm)",
                                 KIND_DOMINANCE))

    def test_bits_bytes_and_the_binary_decimal_split(self):
        # 1 TiB = 1.0995... TB: inside ..2TB, NOT inside ..1TB — exactly.
        self.assertTrue(contains("d(..2TB)", "d(1TiB)", KIND_LINEAR))
        self.assertFalse(contains("d(..1TB)", "d(1TiB)", KIND_LINEAR))
        self.assertEqual(canonicalize("d(1KiB)", KIND_LINEAR),
                         "d(8192bit)")
        self.assertTrue(contains("r(..1Gbps)", "r(100MBps)", KIND_LINEAR))

    def test_crypto_denominations_are_protocol_exact(self):
        self.assertEqual(canonicalize("p(1sat)", KIND_LINEAR),
                         "p(1/100000000BTC)")
        self.assertEqual(canonicalize("g(21Gwei)", KIND_LINEAR),
                         "g(21/1000000000ETH)")
        self.assertTrue(contains("f(..1xBZZ)", "f(9999PLUR)", KIND_LINEAR))
        # ... but currencies never share a lattice: exchange rates float,
        with self.assertRaises(ValueError):
            contains("x(..1BTC)", "x(15ETH)", KIND_LINEAR)
        # ... and BRIDGES are promises too — a nominal 1:1 costs a fee,
        # takes time, and can fail, so it is a relation, not an identity:
        with self.assertRaises(ValueError):
            contains("x(..1BZZ)", "x(1xBZZ)", KIND_LINEAR)
        with self.assertRaises(ValueError):
            contains("x(..1DAI)", "x(1xDAI)", KIND_LINEAR)

    def test_second_round_additions(self):
        # Torr and mmHg: near-identical, deliberately DISTINCT exact values
        # in one family — the difference is real and preserved.
        self.assertFalse(contains("p(1Torr)", "p(1mmHg)", KIND_LINEAR)
                         and contains("p(1mmHg)", "p(1Torr)", KIND_LINEAR))
        self.assertTrue(contains("p(..1000Torr)", "p(760mmHg)",
                                 KIND_LINEAR))
        # kitchen measures are exact US-liquid fractions
        self.assertTrue(contains("v(1cup)", "v(16tbsp)", KIND_LINEAR))
        self.assertTrue(contains("v(1tbsp)", "v(3tsp)", KIND_LINEAR))
        # troy is not avoirdupois
        self.assertFalse(contains("w(1oz)", "w(1ozt)", KIND_LINEAR)
                         and contains("w(1ozt)", "w(1oz)", KIND_LINEAR))
        # Rankine is scalar from absolute zero: admissible, exact
        self.assertTrue(contains("t(..300K)", "t(500Ra)", KIND_LINEAR))
        # percent/ppm/bp on the dimensionless family
        self.assertEqual(canonicalize("n(50pct)", KIND_LINEAR), "n(1/2)")
        self.assertEqual(canonicalize("n(25bp)", KIND_LINEAR), "n(1/400)")
    def test_honest_exclusions(self):
        for bad in ("t(20degC)", "t(70degF)", "a(1rad)"):
            with self.assertRaises(ValueError):
                canonicalize(bad, KIND_LINEAR)


class TestMigration(unittest.TestCase):
    def test_v2_spellings_replay_to_v3_canonicals(self):
        import os
        import tempfile

        from ontodag.migrate import migrate_native
        lines = "\n".join([
            "# ontodag store v1",
            "dimension",
            "linear-dimension dimension",
            "weight linear-dimension",
            "'weight(3000000mg)' weight",       # v2 canonical spelling
            "parcel 'weight(3000000mg)'",
        ]) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.od")
            with open(path, "w") as fh:
                fh.write(lines)
            migrate_native(path)
            first = open(path).read()
            self.assertIn("weight(3kg)", first)
            self.assertNotIn("3000000mg", first)
            migrate_native(path)                # idempotent
            self.assertEqual(open(path).read(), first)

    def test_cli_entry_point(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s.od")
            open(path, "w").write("cat\n")
            repo_src = os.path.join(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))), "src")
            proc = subprocess.run(
                [sys.executable, "-m", "ontodag.migrate", path],
                capture_output=True, text=True,
                env=dict(os.environ, PYTHONPATH=repo_src), timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
