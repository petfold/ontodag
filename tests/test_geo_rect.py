"""The rectangle kind's arithmetic (question 29, DIMENSIONS.md §22): its
spellings, its order and its meets, across the 180th meridian too."""
import random
from fractions import Fraction

import pytest

from ontodag import dimensions as dims
from ontodag.dimensions import KIND_RECT, canonicalize, contains, intersect

K = KIND_RECT


@pytest.mark.parametrize("raw,canonical", [
    ("geo(48.85..48.87,2.28..2.30)", "geo(48.85..48.87,2.28..2.3)"),
    ("geo(48.8584,2.2945)", "geo(48.85835..48.85845,2.29445..2.29455)"),
    ("geo(48,2)", "geo(47.5..48.5,1.5..2.5)"),
    ("geo(48.8584,2.28..2.30)", "geo(48.85835..48.85845,2.28..2.3)"),
    ("geo(48.85..48.85,2.29..2.29)", "geo(48.85..48.85,2.29..2.29)"),
    # a square either way, by the fixed rule
    ("geo(48.8584,2.2945±500m)", "geo(48.853903..48.862897,2.287664..2.301336)"),
    ("geo(48.8584,2.2945+-0.5km)", "geo(48.853903..48.862897,2.287664..2.301336)"),
    ("geo(51.4769,-0.0005±500m)", "geo(51.472403..51.481397,-0.007721..0.006721)"),
    # across 180°: Nukulaelae, and a range typed past 180
    ("geo(-9.38,179.89±20km)", "geo(-9.559865..-9.200135,179.707602..-179.927602)"),
    ("geo(-10..10,170..190)", "geo(-10..10,170..-170)"),
    ("geo(-1..1,179.9..-180)", "geo(-1..1,179.9..180)"),
    ("geo(-1..1,-180..-179.9)", "geo(-1..1,180..-179.9)"),
    # every longitude: typed, and where ± reaches a pole or half the circle
    ("geo(0..1,-180..180)", "geo(0..1,-180..180)"),
    ("geo(0..1,0..360)", "geo(0..1,-180..180)"),
    ("geo(89.999,0±500m)", "geo(89.994503..90,-180..180)"),
    ("geo(89.975,0±2km)", "geo(89.957013..89.992987,-180..180)"),
    ("geo(90,0)", "geo(89.5..90,-0.5..0.5)"),
    # a role writes its base's value by the base's name
    ("from(geo(48.85..48.87,2.28..2.30))", "from(geo(48.85..48.87,2.28..2.3))"),
])
def test_one_name_per_rectangle(raw, canonical):
    assert canonicalize(raw, K) == canonical
    assert canonicalize(canonical, K) == canonical


@pytest.mark.parametrize("raw,teaching", [
    ("geo(u09tunq)", "looks like a geohash cell"),
    ("geo(48.8584)", "no rectangle"),
    ("geo(91..92,0..1)", "-90..90"),
    ("geo(1..0,0..1)", "empty latitude range"),
    ("geo(48,2±5kg)", "a length"),
    ("geo(48..49,2±5km)", "± follows a position"),
    ("geo(48.8584,2.2945e1)", "no decimal number"),
    ("geo(0..1,2..)", "needs both ends"),
    ("geo(0..1,500..-500)", "runs east"),
])
def test_refusals_teach(raw, teaching):
    with pytest.raises(ValueError) as excinfo:
        canonicalize(raw, K)
    assert teaching in str(excinfo.value)


def test_order_and_meets_across_180():
    atoll = "geo(-9.559865..-9.200135,179.707602..-179.927602)"
    assert contains(atoll, "geo(-9.38..-9.38,-179.99..-179.99)", K)   # 10 km east
    assert not contains(atoll, "geo(-9.38..-9.38,-179.8..-179.8)", K)  # 30 km east
    assert contains(atoll, canonicalize("geo(-9.38,179.98±5km)", K), K)
    assert intersect(atoll, "geo(-10..-9,179..180)", K) == \
        "geo(-9.559865..-9.200135,179.707602..180)"
    assert intersect("geo(0..1,0..1)", "geo(2..3,2..3)", K) is None
    assert intersect("geo(0..2,0..2)", "geo(1..3,1..3)", K) == "geo(1..2,1..2)"
    # two pieces: only when the arcs between them cover the circle
    assert intersect("geo(-10..10,170..-170)", "geo(-10..10,-175..175)", K) \
        is dims.SPLIT_MEET
    assert dims.rect_too_wide("geo(-10..10,-175..175)")
    assert not dims.rect_too_wide("geo(-10..10,170..-170)")
    assert not dims.rect_too_wide("geo(0..1,-180..180)")


def test_against_brute_force():
    """Random arcs on a whole-degree grid, many across 180: containment
    and meets agree with every grid point (geo_rect.py's check, on the
    kind)."""
    rng = random.Random(29)
    pts = [Fraction(k) for k in range(-179, 181)]

    def rand():
        if rng.random() < 0.05:
            return dims._parse_rect("0..0,-180..180")
        w = Fraction(rng.randint(-179, 180))
        span = Fraction(rng.choice([0, rng.randint(0, 20), rng.randint(0, 359)]))
        return dims._parse_rect(f"0..0,{dims._decimal_text(w)}..{dims._decimal_text(w + span)}")

    def members(r):
        return {x for x in pts if dims._rect_contains(r, (0, 0, dims._norm_longitude(x), 0))}
    two = 0
    for _ in range(600):
        a, b = rand(), rand()
        in_a, in_b = members(a), members(b)
        assert dims._rect_contains(a, b) == (in_b <= in_a), (a, b)
        pieces = dims._rect_meet(a, b)
        assert set().union(*(members(p) for p in pieces)) == in_a & in_b, (a, b)
        two += len(pieces) == 2
        if len(pieces) == 2:
            assert a[3] + b[3] >= 360
        # and the names say the same as the tuples
        name = lambda r: f"g({dims._render_rect(r)})"
        assert contains(name(a), name(b), K) == dims._rect_contains(a, b)
    assert two > 0
