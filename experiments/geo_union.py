"""Several rectangles in one `geo` value: a union, stored as its maximal
rectangles (docs/DIMENSIONS.md §22, question 29).

usage: geo_union.py

The maximal rectangles of an area are fixed by the area alone, so they are
a canonical form however the union was listed; and any rectangle inside the
area lies inside one of them, so one union is inside another exactly when
each of its pieces is inside one piece of the other. This measures how many
pieces random unions of k rectangles have in that form, how many of them
hold a point (the work a query does per thing it finds), and checks the
containment rule and the meet against brute force. Planar, on integer
coordinates (the 180° seam is the prototype's other half, geo_rect.py).
Needs numpy, and shapely for geo_fill's import.
"""
import os, random, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geo_fill as gf                                           # noqa: E402


def canonical(rects):
    """The maximal rectangles of a union of closed rectangles (x0, x1, y0, y1),
    found on the grid of their own coordinates."""
    xs = sorted({v for r in rects for v in r[:2]})
    ys = sorted({v for r in rects for v in r[2:]})
    m = np.zeros((len(ys) - 1, len(xs) - 1), bool)
    for x0, x1, y0, y1 in rects:
        m[ys.index(y0):ys.index(y1), xs.index(x0):xs.index(x1)] = True
    P = gf.maximal_pieces(m)
    return sorted((xs[a], xs[b], ys[c], ys[d]) for a, b, c, d in P.tolist())


def inside(r, q):
    return q[0] <= r[0] and r[1] <= q[1] and q[2] <= r[2] and r[3] <= q[3]


def union_inside(U, V):
    return all(any(inside(u, v) for v in V) for u in U)


def meet(U, V):
    parts = [(max(u[0], v[0]), min(u[1], v[1]), max(u[2], v[2]), min(u[3], v[3]))
             for u in U for v in V]
    parts = [p for p in parts if p[0] < p[1] and p[2] < p[3]]
    return canonical(parts) if parts else []


def cells(U, n):
    g = np.zeros((n, n), bool)
    for x0, x1, y0, y1 in U:
        g[y0:y1, x0:x1] = True
    return g


def rand_rects(rng, k, n, big):
    out = []
    for _ in range(k):
        w, h = rng.randint(1, big), rng.randint(1, big)
        x, y = rng.randint(0, n - w), rng.randint(0, n - h)
        out.append((x, x + w, y, y + h))
    return out


def main():
    rng = random.Random(30)
    n = 200
    print("k listed | pieces in canonical form: median, most | pieces holding a point: mean, most")
    for k in (1, 2, 3, 5, 10, 20, 50):
        sizes, depth, most = [], [], 0
        for _ in range(200):
            C = canonical(rand_rects(rng, k, n, 80))
            sizes.append(len(C))
            d = np.zeros((n, n), np.int32)
            for x0, x1, y0, y1 in C:
                d[y0:y1, x0:x1] += 1
            depth.append(d[d > 0].mean()); most = max(most, int(d.max()))
        print(f"{k:8d} | {int(np.median(sizes)):6d} {max(sizes):6d} | {np.mean(depth):6.2f} {most:6d}")
    # the same area listed two ways gives one form; containment and meets by brute force
    bad = 0
    for _ in range(1000):
        U = rand_rects(rng, rng.randint(1, 6), 40, 20)
        V = rand_rects(rng, rng.randint(1, 6), 40, 20)
        cu, cv = canonical(U), canonical(V)
        if canonical(cu + rand_rects(rng, 0, 40, 20)) != cu or canonical(U[::-1] + cu) != cu:
            bad += 1
        gu, gv = cells(U, 40), cells(V, 40)
        if union_inside(cu, cv) != bool((gu <= gv).all()):
            bad += 1
        if not (cells(meet(cu, cv), 40) == (gu & gv)).all():
            bad += 1
    print(f"brute force: 1,000 pairs of unions, {bad} disagreements (one form per area, "
          f"containment piece by piece, meets)")


if __name__ == "__main__":
    main()
