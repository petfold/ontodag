"""Inner and outer covers against real towns, and what overlap costs against a tiling.

The second measurement behind question 29 (docs/DIMENSIONS.md §22). Needs
geo_fill.py's downloads in DATA_DIR and GeoNames' towns of 1,000 people or
more (CC BY 4.0), cities1000.txt from download.geonames.org/export/dump/cities1000.zip

usage: geo_bounds.py DATA_DIR

The inner cover of a region is the grid squares wholly inside it (what
geo_fill.py fills), the outer cover the squares that touch it. Part one asks,
for each grid, how many French towns the inner cover leaves out and how many
foreign towns the outer cover takes in, each town tested with its own grid
square against Natural Earth's polygon. Part two compares a tiling with the
overlapping cover and with tilings whose pieces grow one square into their
neighbours: how much area the pieces add up to, how many pieces hold each
random square found (the work of a query that walks every piece), how many
are missed, and how many pieces a small edit of the boundary changes.
"""
import math, os, sys, time
import numpy as np
import shapely

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geo_fill as gf                                           # noqa: E402


def towns(D):
    """GeoNames cities1000 near mainland France: lon, lat, population, is French, name."""
    lon, lat, pop, fr, name = [], [], [], [], []
    for line in open(f"{D}/cities1000.txt", encoding="utf-8"):
        f = line.rstrip("\n").split("\t")
        x, y = float(f[5]), float(f[4])
        if -6 <= x <= 10 and 41 <= y <= 52:
            lon.append(x); lat.append(y); pop.append(int(f[14] or 0)); fr.append(f[8] == "FR")
            name.append(f"{f[1]} ({f[8]})")
    return np.array(lon), np.array(lat), np.array(pop), np.array(fr), np.array(name)


def bounds_part(D, france):
    lon, lat, pop, fr, name = towns(D)
    shapely.prepare(france)
    inpoly = shapely.contains_xy(france, lon, lat)
    print(f"GeoNames towns of 1,000+ people in the box: {fr.sum():,} French, {(~fr).sum():,} not")
    print(f"  French towns outside Natural Earth's polygon itself (data, not grid): "
          f"{(fr & ~inpoly).sum():,} ({100 * (fr & ~inpoly).mean() / fr.mean():.1f}%), "
          f"{pop[fr & ~inpoly].sum():,} people")
    print(f"  foreign towns inside it: {(~fr & inpoly).sum():,}")
    for L in (5, 6, 7, 8):
        lonb, latb = gf.grid(L)
        pw, ph = 360 / 2 ** lonb, 180 / 2 ** latb
        x0 = -180 + np.floor((lon + 180) / pw) * pw
        y0 = -90 + np.floor((lat + 90) / ph) * ph
        boxes = shapely.box(x0, y0, x0 + pw, y0 + ph)
        inner = shapely.contains(france, boxes)
        outer = shapely.intersects(france, boxes)
        wm = pw * 111_320 * math.cos(math.radians(46.5)); hm = ph * 111_320
        a = fr & inpoly
        missed = a & ~inner
        b = ~fr & ~inpoly
        wrong = b & outer
        print(f"\ngeohash {L} grid ({wm:,.0f} m x {hm:,.0f} m):")
        print(f"  inner cover misses {missed.sum():,} of {a.sum():,} French towns "
              f"({100 * missed.sum() / a.sum():.1f}%; {100 * pop[missed].sum() / pop[a].sum():.1f}% of their people)")
        print(f"  outer cover takes in {wrong.sum():,} of {b.sum():,} foreign towns "
              f"({100 * wrong.sum() / b.sum():.2f}%), {pop[wrong].sum():,} people")
        big = np.argsort(-pop * wrong)[:6]
        print("    largest: " + ", ".join(f"{name[i]} {pop[i]:,}" for i in big if wrong[i]))
        bigm = np.argsort(-pop * missed)[:6]
        print("    largest French missed: " + ", ".join(f"{name[i]} {pop[i]:,}" for i in bigm if missed[i]))


def outer_mask(geom, L):
    m, meta = gf.inside_mask(geom, L)
    ix0, iy0, pw, ph, lonb, latb = meta
    ny, nx = m.shape
    xs = -180 + (ix0 + np.arange(nx + 1)) * pw
    ys = -90 + (iy0 + np.arange(ny + 1)) * ph
    X, Y = np.meshgrid(xs, ys)
    c = shapely.contains_xy(geom, X, Y)
    o = c[:-1, :-1] | c[1:, :-1] | c[:-1, 1:] | c[1:, 1:]
    step = min(pw, ph) / 8
    for ring in gf.rings(geom):
        xy = np.asarray(ring.coords)
        a, b = xy[:-1], xy[1:]
        k = np.maximum(1, (np.hypot(*(b - a).T) / step).astype(int) + 1)
        seg = np.repeat(np.arange(len(a)), k + 1)
        t = np.concatenate([np.linspace(0, 1, kk + 1) for kk in k])
        p = a[seg] + (b - a)[seg] * t[:, None]
        cx = np.floor((p[:, 0] + 180) / pw).astype(int) - ix0
        cy = np.floor((p[:, 1] + 90) / ph).astype(int) - iy0
        ok = (cx >= 0) & (cx < nx) & (cy >= 0) & (cy < ny)
        o[cy[ok], cx[ok]] = True
    return m, o, meta


def grow(m, P, k):
    """Each piece grown by up to k squares on each side, as far as it stays inside."""
    ny, nx = m.shape
    S = np.zeros((ny + 1, nx + 1), np.int64); S[1:, 1:] = m.cumsum(0).cumsum(1)
    full = lambda x0, x1, y0, y1: S[y1, x1] - S[y0, x1] - S[y1, x0] + S[y0, x0] == (y1 - y0) * (x1 - x0)
    out = []
    for x0, x1, y0, y1 in P.tolist():
        for _ in range(k):
            if x0 > 0 and full(x0 - 1, x0, y0, y1): x0 -= 1
            if x1 < nx and full(x1, x1 + 1, y0, y1): x1 += 1
            if y0 > 0 and full(x0, x1, y0 - 1, y0): y0 -= 1
            if y1 < ny and full(x0, x1, y1, y1 + 1): y1 += 1
        out.append((x0, x1, y0, y1))
    return np.array(out, dtype=np.int64)


def depth_of(m, P):
    d = np.zeros((m.shape[0] + 1, m.shape[1] + 1), np.int64)
    for dy, dx, sign in ((2, 0, 1), (2, 1, -1), (3, 0, -1), (3, 1, 1)):
        np.add.at(d, (P[:, dy], P[:, dx]), sign)
    paint = d.cumsum(0).cumsum(1)[:-1, :-1]
    assert ((paint > 0) == m).all()
    return paint


def visits(m, meta, P, sq):
    """For each square, how many pieces hold it (0 = missed)."""
    ix0, iy0, pw, ph, _, _ = meta
    fx0 = np.floor((sq[:, 0] + 180) / pw).astype(np.int64) - ix0
    fx1 = np.ceil((sq[:, 1] + 180) / pw).astype(np.int64) - ix0
    fy0 = np.floor((sq[:, 2] + 90) / ph).astype(np.int64) - iy0
    fy1 = np.ceil((sq[:, 3] + 90) / ph).astype(np.int64) - iy0
    S = np.zeros((m.shape[0] + 1, m.shape[1] + 1), np.int64); S[1:, 1:] = m.cumsum(0).cumsum(1)
    inside = (S[fy1, fx1] - S[fy0, fx1] - S[fy1, fx0] + S[fy0, fx0]) == (fy1 - fy0) * (fx1 - fx0)
    n = np.zeros(len(sq), np.int64)
    for i in range(0, len(sq), 64):
        sl = slice(i, i + 64)
        n[sl] = ((P[None, :, 0] <= fx0[sl, None]) & (fx1[sl, None] <= P[None, :, 1])
                 & (P[None, :, 2] <= fy0[sl, None]) & (fy1[sl, None] <= P[None, :, 3])).sum(1)
    return inside, n


def covers(m, meta, L):
    maximal = gf.maximal_pieces(m)
    T = gf.largest_first_partition(m)
    C = gf.cell_pieces(m, meta, L)
    return {"cells (tiling)": C, "largest first, tiling": T,
            "largest first, overlapping": gf.largest_first_overlap(m, maximal),
            "cells + 1 square margin": grow(m, C, 1), "tiling + 1 square margin": grow(m, T, 1)}


def overlap_part(paris, france):
    for name, geom, L, sides in (("Paris", paris, 7, (100, 300)), ("France", france, 5, (1000, 5000))):
        m, o, meta = outer_mask(geom, L)
        print(f"\n{name}, geohash {L}: inner {m.sum():,} squares, outer {o.sum():,} "
              f"({100 * (o.sum() - m.sum()) / m.sum():.1f}% more); polygon area = "
              f"{geom.area / (meta[2] * meta[3]):,.0f} squares")
        Co, To = gf.cell_pieces(o, meta, L), gf.largest_first_partition(o)
        print(f"  pieces of the outer cover: cells {len(Co):,}, largest-first tiling {len(To):,}")
        t = time.time()
        P = covers(m, meta, L)
        sqs = {s: gf.squares(geom, s, 10_000) for s in sides}
        for k, Q in P.items():
            paint = depth_of(m, Q)
            row = (f"  {k:28s} {len(Q):6,} pieces; area sum {paint[m].mean():5.2f}x the region, "
                   f"most {paint.max():4d}")
            for s, sq in sqs.items():
                inside, n = visits(m, meta, Q, sq)
                ok = inside & (n > 0)
                row += (f"; {s:,} m: missed {100 * (inside & (n == 0)).mean():4.1f}%, "
                        f"visits {n[ok].mean():5.2f}")
            print(row, flush=True)
        print(f"  [{time.time() - t:.0f} s]")
        # stability of the margin covers
        m2, _ = gf.inside_mask(geom.simplify(min(meta[2], meta[3]) / 4), L)
        P2 = covers(m2, meta, L)
        print("  pieces that change when the boundary is simplified a little: " + ", ".join(
            f"{k} {100 * len(set(map(tuple, P[k].tolist())) - set(map(tuple, P2[k].tolist()))) / len(P[k]):.0f}%"
            for k in P))


def main():
    D = sys.argv[1]
    paris, france = gf.load(D)
    bounds_part(D, france)
    overlap_part(paris, france)


if __name__ == "__main__":
    main()
