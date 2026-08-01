"""Step 1 of docs/DIMENSIONS.md §12: the pure grammar/registry/arithmetic
module, tested against explicit denotation oracles (materialized value sets),
mirroring the independent-oracle style of test_invariants.py."""

import itertools

import pytest

from ontodag import dimensions as dims
from ontodag.dimensions import (
    KIND_CALENDAR, KIND_DOMINANCE, KIND_LINEAR, KIND_PREFIX,
    canonicalize, contains, intersect, space_of, split_term,
)


class TestSplitTerm:
    def test_shapes(self):
        assert split_term("weight(3kg)") == ("weight", "3kg")
        assert split_term("time(2026-08-10..2026-08-20)") == (
            "time", "2026-08-10..2026-08-20")

    def test_non_terms_stay_opaque(self):
        for name in ["weight", "weight()", "(3kg)", "weight(3kg", "3kg)",
                     "a(b)(c)", "smiley:-)", 42, None]:
            assert split_term(name) is None


class TestLinearCanonicalization:
    @pytest.mark.parametrize("raw,canonical", [
        # Registry v3 (UNITS.md D9): canonical values are reduced rationals
        # of the SI coherent anchor — kg, m, s — so integer-anchor values
        # are already their own canonical spelling.
        ("weight(3kg)", "weight(3kg)"),
        ("weight(0.5g)", "weight(1/2000kg)"),
        ("weight(05kg)", "weight(5kg)"),
        ("weight(3.0kg)", "weight(3kg)"),
        ("weight(3000g)", "weight(3kg)"),
        ("weight(..5kg)", "weight(..5kg)"),
        ("weight(1kg..)", "weight(1kg..)"),
        ("weight(1kg..5kg)", "weight(1kg..5kg)"),
        ("weight(2kg..2000g)", "weight(2kg)"),        # degenerate -> point
        ("weight(1lb)", "weight(45359237/100000000kg)"),
        ("weight(0.0005g)", "weight(1/2000000kg)"),   # exact, never rounded
        ("length(1km)", "length(1000m)"),
        ("length(1in)", "length(127/5000m)"),
        ("length(10/33m)", "length(10/33m)"),         # the shaku, day one
        ("pressure(1atm)", "pressure(101325Pa)"),
        ("wait(2min)", "wait(120s)"),
        ("number(5)", "number(5)"),
        ("number(0)", "number(0)"),
        # No negatives in the grammar, so 0 IS unbounded-below: one
        # denotation, one canonical name.
        ("number(..0)", "number(0)"),
        ("number(0..5)", "number(..5)"),
        ("number(0..)", "number(0..)"),
    ])
    def test_units_scale_exactly(self, raw, canonical):
        assert canonicalize(raw, KIND_LINEAR) == canonical

    def test_idempotent(self):
        for raw in ["weight(3kg)", "weight(..5kg)", "number(1..9)",
                    "time(2026-08-15)"]:
            once = canonicalize(raw, KIND_LINEAR)
            assert canonicalize(once, KIND_LINEAR) == once

    @pytest.mark.parametrize("raw,canonical", [
        ("time(2026-08-15T14:00:00Z)", "time(2026-08-15T14:00:00Z)"),
        ("time(2026-08-15)",
         "time(2026-08-15T00:00:00Z..2026-08-15T23:59:59Z)"),
        ("time(2026-08-10..2026-08-20)",
         "time(2026-08-10T00:00:00Z..2026-08-20T23:59:59Z)"),
        ("time(..2026-01-01T00:00:00Z)", "time(..2026-01-01T00:00:00Z)"),
    ])
    def test_timestamps_and_date_sugar(self, raw, canonical):
        assert canonicalize(raw, KIND_LINEAR) == canonical

    @pytest.mark.parametrize("raw", [
        "weight(3zz)",            # unknown unit
        "weight(..)",             # no end at all
        "weight(5kg..1kg)",       # empty range
        "weight(1..2..3)",        # two separators
        "weight(1kg..2s)",        # mixed families in one range
        "time(2026-13-40)",       # not a real date
        "time(2026-02-30T00:00:00Z)",  # not a real timestamp
        "weight(-3kg)",           # no negative quantities in the grammar
    ])
    def test_malformed_raise(self, raw):
        with pytest.raises(ValueError):
            canonicalize(raw, KIND_LINEAR)


class TestDominanceCanonicalization:
    def test_shared_unit_and_sorting(self):
        assert canonicalize("size(19x23x39cm)", KIND_DOMINANCE) == \
            "size(39/100x23/100x19/100m)"
        assert canonicalize("size(1mx50cm)", KIND_DOMINANCE) == \
            "size(1x1/2m)"
        assert canonicalize("shape(3x4x5)", KIND_DOMINANCE) == "shape(5x4x3)"

    def test_idempotent(self):
        once = canonicalize("size(19x23x39cm)", KIND_DOMINANCE)
        assert canonicalize(once, KIND_DOMINANCE) == once

    @pytest.mark.parametrize("raw", [
        "size(5cm)",              # needs at least two components
        "size(3x4mmx5)",          # count component left of a unit one
        "size(3xx4)",             # empty component
    ])
    def test_malformed_raise(self, raw):
        with pytest.raises(ValueError):
            canonicalize(raw, KIND_DOMINANCE)


class TestPrefixCanonicalization:
    def test_passthrough(self):
        assert canonicalize("geo(u2ed)", KIND_PREFIX) == "geo(u2ed)"

    @pytest.mark.parametrize("raw", ["geo(a..b)", "geo(a b)", "geo(.x)"])
    def test_malformed_raise(self, raw):
        with pytest.raises(ValueError):
            canonicalize(raw, KIND_PREFIX)


class TestContains:
    def test_courier_and_flour(self):
        # The two worked examples of DIMENSIONS.md §2, verbatim.
        assert contains("weight(..5kg)", "weight(3kg)", KIND_LINEAR)
        assert contains("weight(1kg..)", "weight(1.2kg)", KIND_LINEAR)
        # Points are incomparable: a 3 kg parcel is not a 5 kg parcel.
        assert not contains("weight(5kg)", "weight(3kg)", KIND_LINEAR)
        assert not contains("weight(3kg)", "weight(5kg)", KIND_LINEAR)

    def test_reflexive_never_mutual_between_distinct_canonicals(self):
        assert contains("weight(3kg)", "weight(3000g)", KIND_LINEAR)
        assert contains("weight(3000g)", "weight(3kg)", KIND_LINEAR)
        # ... but those two ARE the same canonical name (same denotation).
        assert canonicalize("weight(3kg)", KIND_LINEAR) == \
            canonicalize("weight(3000g)", KIND_LINEAR)

    def test_time_windows(self):
        assert contains("time(2026-08-10..2026-08-20)",
                        "time(2026-08-15T14:00:00Z)", KIND_LINEAR)
        assert contains("time(2026-08-15)",
                        "time(2026-08-15T14:00:00Z..2026-08-15T17:00:00Z)",
                        KIND_LINEAR)
        assert not contains("time(2026-08-15)",
                            "time(2026-08-15T14:00:00Z..2026-08-16T10:00:00Z)",
                            KIND_LINEAR)

    def test_dominance_fits_in(self):
        # The luggage example: sorted componentwise dominance.
        assert contains("size(20x30x40cm)", "size(19x23x39cm)",
                        KIND_DOMINANCE)
        assert not contains("size(19x23x39cm)", "size(20x30x40cm)",
                            KIND_DOMINANCE)
        # Rotation is free: canonical sorting compares largest to largest.
        assert contains("size(40x30x20cm)", "size(39x19x23cm)",
                        KIND_DOMINANCE)

    def test_prefix(self):
        assert contains("geo(u2)", "geo(u2ed)", KIND_PREFIX)
        assert not contains("geo(u2ed)", "geo(u2)", KIND_PREFIX)
        assert not contains("geo(u2ed)", "geo(u3)", KIND_PREFIX)

    def test_cross_head_and_family_mismatch_raise(self):
        with pytest.raises(ValueError):
            contains("weight(..5kg)", "height(3mm)", KIND_LINEAR)
        with pytest.raises(ValueError):
            contains("weight(..5kg)", "weight(3s)", KIND_LINEAR)
        with pytest.raises(ValueError):
            contains("size(3x4)", "size(3x4x5)", KIND_DOMINANCE)


class TestIntersect:
    def test_linear(self):
        assert intersect("weight(1kg..5kg)", "weight(3kg..9kg)",
                         KIND_LINEAR) == "weight(3kg..5kg)"
        assert intersect("weight(..5kg)", "weight(2kg..)",
                         KIND_LINEAR) == "weight(2kg..5kg)"
        assert intersect("weight(..2kg)", "weight(3kg..)",
                         KIND_LINEAR) is None
        assert intersect("weight(..5kg)", "weight(3kg)",
                         KIND_LINEAR) == "weight(3kg)"

    def test_dominance_never_empty(self):
        assert intersect("size(20x30x40cm)", "size(50x10x35cm)",
                         KIND_DOMINANCE) == "size(2/5x3/10x1/10m)"

    def test_prefix(self):
        assert intersect("geo(u2)", "geo(u2ed)", KIND_PREFIX) == "geo(u2ed)"
        assert intersect("geo(u2ed)", "geo(u2)", KIND_PREFIX) == "geo(u2ed)"
        assert intersect("geo(u2)", "geo(u3)", KIND_PREFIX) is None


class TestSpaceOf:
    def test_tags(self):
        assert space_of("weight(3kg)", KIND_LINEAR) == "linear:mass"
        assert space_of("time(2026-08-15)", KIND_LINEAR) == "linear:time"
        assert space_of("size(3x4x5cm)", KIND_DOMINANCE) == \
            "dominance:length:3"
        assert space_of("geo(u2)", KIND_PREFIX) == "prefix"


class TestAgainstDenotationOracle:
    """Brute force: materialize denotations as explicit finite sets and check
    contains/intersect against set operations — the independent oracle.
    Upper-open intervals are materialized over an *extended* grid so that
    open-vs-bounded distinctions stay faithful (an unbounded set contains
    beyond-grid values no bounded set has)."""

    GRID = range(0, 13)
    EXTENT = max(GRID) + 3  # where "unbounded above" is materialized to

    def _terms(self):
        """canonical name -> materialized denotation set (duplicates like
        number(0..5) and number(..5) merge into one canonical entry)."""
        raw = [(f"number({v})", {v}) for v in self.GRID]
        for lo, hi in itertools.combinations(self.GRID, 2):
            raw.append((f"number({lo}..{hi})", set(range(lo, hi + 1))))
        for v in self.GRID:
            raw.append((f"number(..{v})", set(range(0, v + 1))))
            raw.append((f"number({v}..)", set(range(v, self.EXTENT + 1))))
        terms = {}
        for name, values in raw:
            canonical = canonicalize(name, KIND_LINEAR)
            assert terms.setdefault(canonical, values) == values
        return terms

    def test_contains_matches_subset(self):
        terms = self._terms()
        for (name_a, set_a), (name_b, set_b) in itertools.product(
                terms.items(), repeat=2):
            assert contains(name_a, name_b, KIND_LINEAR) == \
                (set_b <= set_a), f"{name_a} vs {name_b}"

    def test_intersect_matches_set_intersection(self):
        terms = self._terms()
        for (name_a, set_a), (name_b, set_b) in itertools.product(
                terms.items(), repeat=2):
            met = intersect(name_a, name_b, KIND_LINEAR)
            expected = set_a & set_b
            if not expected:
                assert met is None, f"{name_a} vs {name_b}"
            else:
                assert met is not None, f"{name_a} vs {name_b}"
                # The meet's denotation must be exactly the intersection.
                assert terms[met] == expected, f"{name_a} vs {name_b}"

    def test_dominance_oracle(self):
        # All 2-tuples over a small grid; denotation = the down-set.
        tuples = list(itertools.product(range(1, 6), repeat=2))

        def downset(t):
            s = tuple(sorted(t, reverse=True))
            return {(x, y) for x in range(0, s[0] + 1)
                    for y in range(0, s[1] + 1) if x >= y}

        for ta, tb in itertools.product(tuples, repeat=2):
            name_a = f"shape({ta[0]}x{ta[1]})"
            name_b = f"shape({tb[0]}x{tb[1]})"
            assert contains(name_a, name_b, KIND_DOMINANCE) == \
                (downset(tb) <= downset(ta)), f"{name_a} vs {name_b}"


class TestCalendarCanonicalization:
    """A calendar dimension reads reduced precision as the whole period it
    names — the rule the linear grammar already applied to a bare date,
    extended up to months and years. It is a separate kind because in a
    linear dimension a bare integer is a dimensionless count, so `time(2026)`
    there can only mean the number 2026."""

    @pytest.mark.parametrize("param, expected", [
        ("2026", "2026-01-01T00:00:00Z..2026-12-31T23:59:59Z"),
        ("2026-08", "2026-08-01T00:00:00Z..2026-08-31T23:59:59Z"),
        ("2026-02", "2026-02-01T00:00:00Z..2026-02-28T23:59:59Z"),
        ("2024-02", "2024-02-01T00:00:00Z..2024-02-29T23:59:59Z"),  # leap
        ("2026-08-15", "2026-08-15T00:00:00Z..2026-08-15T23:59:59Z"),
        ("2026-08-15T14:30:00Z", "2026-08-15T14:30:00Z"),           # a point
        ("2026-03..2026-08", "2026-03-01T00:00:00Z..2026-08-31T23:59:59Z"),
        ("..2026", "..2026-12-31T23:59:59Z"),
        ("2026..", "2026-01-01T00:00:00Z.."),
    ])
    def test_period_bounds(self, param, expected):
        assert canonicalize(f"t({param})", KIND_CALENDAR) == f"t({expected})"

    @pytest.mark.parametrize("param", [
        "2026-13", "2026-00", "2026-02-30", "20260", "26", "abc", "2026-8",
        "2026-12..2026-01",          # empty range
        "..",                        # no end at all
    ])
    def test_rejected(self, param):
        with pytest.raises(ValueError):
            canonicalize(f"t({param})", KIND_CALENDAR)

    @pytest.mark.parametrize("inner, outer", [
        ("2026-08-15", "2026"), ("2026-08-15", "2026-08"),
        ("2026-08", "2026"), ("2026-08-15T14:30:00Z", "2026-08-15"),
        ("2026", "2026"), ("2026-03..2026-04", "2026"),
    ])
    def test_contains(self, inner, outer):
        assert contains(f"t({outer})", f"t({inner})", KIND_CALENDAR)

    @pytest.mark.parametrize("inner, outer", [
        ("2026-08-15", "2025"), ("2026", "2026-08"),
        ("2026-08-15", "2026-09"), ("2026", "2026-01-01"),
    ])
    def test_does_not_contain(self, inner, outer):
        assert not contains(f"t({outer})", f"t({inner})", KIND_CALENDAR)

    def test_shares_the_linear_time_space_tag(self):
        # So a dimension declared linear can be re-declared calendar without
        # any stored value changing identity or space.
        assert space_of("t(2026-08-15)", KIND_CALENDAR) == \
            space_of("t(2026-08-15)", KIND_LINEAR) == "linear:time"
        assert canonicalize("t(2026-08-15)", KIND_CALENDAR) == \
            canonicalize("t(2026-08-15)", KIND_LINEAR)

    def test_intersect(self):
        assert intersect("t(2026)", "t(2026-08)", KIND_CALENDAR) == \
            "t(2026-08-01T00:00:00Z..2026-08-31T23:59:59Z)"
        assert intersect("t(2025)", "t(2026)", KIND_CALENDAR) is None

    def test_bare_year_stays_a_count_under_the_linear_kind(self):
        # The reason this kind exists: unchanged linear semantics.
        assert canonicalize("n(2026)", KIND_LINEAR) == "n(2026)"
        assert space_of("n(2026)", KIND_LINEAR) == "linear:count"

    def test_family_mismatch_names_the_fix(self):
        with pytest.raises(ValueError) as excinfo:
            contains("t(2026-08-15)", "t(2026)", KIND_LINEAR)
        message = str(excinfo.value)
        assert "is the number, not the year" in message
        assert KIND_CALENDAR in message


class TestRegistry:
    def test_reserved_names(self):
        assert dims.KINDS == {"linear-dimension", "prefix-dimension",
                              "dominance-dimension", "calendar-dimension"}
        assert dims.DIMENSION_ROOT == "dimension"
        # MAJOR.MINOR since v3 (UNITS.md D10): same major = same
        # canonical-name arithmetic; minors add vocabulary only.
        assert dims.REGISTRY_VERSION == "4.0"
        assert dims.registry_compatible("4.7")
        assert not dims.registry_compatible("3.2")
