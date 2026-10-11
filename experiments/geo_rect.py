"""Rectangles on the sphere across the 180th meridian: a prototype of
question 29's `geo` value and question 30's `±` (docs/DIMENSIONS.md §22).

usage: geo_rect.py

A value is a latitude interval and a longitude arc, all exact Fractions. The
arc runs east from its west bound to its east bound, so it wraps across 180°
when the west bound is the larger (`179.7..-179.9`); longitudes are kept in
(-180, 180], and the full circle is spelled `-180..180`. Containment and
meets are computed on the circle; the conversion of a size in metres uses
Decimal arithmetic with a fixed precision, never the machine's floating
point. The checks at the end compare everything against brute force.
"""
import random
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, getcontext
from fractions import Fraction as F

getcontext().prec = 40
PI = Decimal("3.141592653589793238462643383279502884197")
EARTH_M_PER_DEG = Decimal("6371008.8") * PI / 180      # mean radius, 111,195 m
GRID = Decimal("0.000001")                              # bounds in millionths of a degree
FULL = (F(-180), F(180))


def norm(lon):
    """A longitude in (-180, 180]."""
    lon = (F(lon) + 180) % 360 - 180
    return F(180) if lon == -180 else lon


def arc(w, e):
    """A canonical arc from bounds as typed; the full circle when they span it."""
    w, e = F(w), F(e)
    if e - w >= 360 or (w, e) == FULL:
        return FULL
    return norm(w), norm(e)


def length(a):
    return F(360) if a == FULL else (a[1] - a[0]) % 360


def rect(s, n, w, e):
    s, n = F(s), F(n)
    assert -90 <= s <= n <= 90, (s, n)
    return (s, n), arc(w, e)


def text(x):
    d = Decimal(x.numerator) / Decimal(x.denominator)
    return format(d.normalize(), "f")


def name(r):
    (s, n), (w, e) = r
    return f"geo({text(s)}..{text(n)},{text(w)}..{text(e)})"


def arc_contains(outer, inner):
    if outer == FULL:
        return True
    if inner == FULL:
        return False
    return (inner[0] - outer[0]) % 360 + length(inner) <= length(outer)


def contains(outer, inner):
    (os_, on), oa = outer
    (is_, in_), ia = inner
    return os_ <= is_ and in_ <= on and arc_contains(oa, ia)


def arc_meet(a, b):
    """The arcs two arcs share: none, one, or two (when they cover the circle
    between them and overlap at both ends)."""
    if a == FULL:
        return [b]
    if b == FULL:
        return [a]
    la, lb = length(a), length(b)
    d = (b[0] - a[0]) % 360
    out = []
    for lo, hi in ((d, d + lb), (d - 360, d + lb - 360)):
        lo, hi = max(lo, F(0)), min(hi, la)
        if lo <= hi:
            out.append(arc(a[0] + lo, a[0] + hi))
    return sorted(set(out))


def meet(a, b):
    (as_, an), aa = a
    (bs, bn), ba = b
    s, n = max(as_, bs), min(an, bn)
    if s > n:
        return []
    return [((s, n), piece) for piece in arc_meet(aa, ba)]


def cos_deg(x):
    """cos of x degrees by its series at 40 digits: the same on every machine."""
    r = Decimal(x) * PI / 180
    term, total, k = Decimal(1), Decimal(1), 0
    while True:
        k += 2
        term = -term * r * r / (k * (k - 1))
        if abs(term) < Decimal("1e-38"):
            return total
        total += term


def around(lat, lon, metres):
    """`geo(LAT,LON±SIZE)`: the square SIZE either way, rounded outwards to
    the grid; widened to every longitude when it reaches a pole."""
    lat, lon, metres = Decimal(lat), Decimal(lon), Decimal(metres)
    dlat = metres / EARTH_M_PER_DEG
    s = max((lat - dlat).quantize(GRID, ROUND_FLOOR), Decimal(-90))
    n = min((lat + dlat).quantize(GRID, ROUND_CEILING), Decimal(90))
    edge = max(abs(s), abs(n))
    if edge >= 90:
        return rect(F(s), F(n), *FULL)
    dlon = dlat / cos_deg(edge)                 # the wider of the two edges
    w = (lon - dlon).quantize(GRID, ROUND_FLOOR)
    e = (lon + dlon).quantize(GRID, ROUND_CEILING)
    return rect(F(s), F(n), F(w), F(e))


def point(lat, lon):
    return rect(lat, lat, lon, lon)


def demo():
    atoll = around("-9.38", "179.89", 20_000)
    print("Nukulaelae ±20 km:", name(atoll), f"(arc {float(length(atoll[1])):.4f}°)")
    for where, p in (("on the atoll", point(F("-9.38"), F("179.89"))),
                     ("10 km east, across 180", point(F("-9.38"), F("-179.99"))),
                     ("30 km east", point(F("-9.38"), F("-179.8"))),
                     ("Greenwich", point(F("-9.38"), 0))):
        print(f"  {where:24s} inside: {contains(atoll, p)}")
    small = around("-9.38", "179.98", 5_000)
    print("  ±5 km straddling 180:", name(small), "inside:", contains(atoll, small))
    west = rect(-10, -9, 179, 180)
    print("  meet with", name(west), "->", [name(m) for m in meet(atoll, west)])
    taveuni = rect(F("-16.97"), F("-16.67"), F("179.89"), F("-179.81"))
    print("Taveuni, one value though Natural Earth cuts it in two:", name(taveuni))
    a, b = rect(-10, 10, 170, -170), rect(-10, 10, -175, 175)
    print("Two pieces:", name(a), "meet", name(b), "->", [name(m) for m in meet(a, b)])
    print("Near a pole:", name(around("89.999", "179.5", 500)))


def brute():
    """Random rectangles on a half-degree grid, many across 180; containment
    and meets against every grid point."""
    rng = random.Random(29)
    pts = [F(k, 2) for k in range(-359, 361)]           # (-180, 180] by halves
    on = lambda a, x: arc_contains(a, (x, x))

    def rand():
        if rng.random() < 0.05:
            return FULL
        w = F(rng.randint(-359, 360), 2)
        return arc(w, w + F(rng.choice([0, rng.randint(0, 40), rng.randint(0, 719)]), 2))
    bad, two, n = 0, 0, 4000
    for _ in range(n):
        a, b = rand(), rand()
        inside = {x for x in pts if on(a, x)}
        if arc_contains(a, b) != all(on(a, x) for x in pts if on(b, x)):
            bad += 1
        pieces = arc_meet(a, b)
        two += len(pieces) == 2
        shared = {x for x in inside if on(b, x)}
        if shared != {x for x in pts if any(on(p, x) for p in pieces)}:
            bad += 1
        if len(pieces) == 2 and length(a) + length(b) < 360:
            bad += 1
    print(f"brute force: {n} random pairs of arcs, {bad} disagreements; "
          f"{two} meets in two pieces, every one from arcs covering the circle between them")


if __name__ == "__main__":
    demo()
    brute()
