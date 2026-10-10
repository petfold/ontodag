"""Fill a region from inside with pieces, three ways, and test random squares.

The measurement behind question 29 (docs/DIMENSIONS.md §22). Needs shapely
and numpy (not ontodag dependencies) and three downloads in DATA_DIR:
ne_10m_admin_0_countries.geojson and ne_50m_admin_0_countries.geojson from
github.com/nvkelso/natural-earth-vector (geojson/), and paris.geojson from
OpenStreetMap: nominatim.openstreetmap.org/lookup?osm_ids=R7444&format=geojson&polygon_geojson=1

usage: geo_fill.py DATA_DIR              Paris and mainland France
       geo_fill.py DATA_DIR countries    piece counts for every country

Pixels are geohash cells at the finest precision L (exact grid); a pixel is
inside when it lies wholly inside the boundary. The same inside pixels are
grouped into pieces three ways:
  cells    maximal geohash cells (the tree: each a whole cell, no overlap)
  part     free rectangles, no overlap (greedy row-major partition)
  overlap  free rectangles that may overlap (each grown as large as fits)
A random square wholly inside the true boundary is found when one piece holds
it. "border" misses touch a pixel that is not inside (the same for all three);
"seam" misses lie inside the pixels but in no single piece.
"""
import json, math, sys, time
import numpy as np
import shapely
from shapely.geometry import shape, box

D = sys.argv[1]
rng = np.random.default_rng(1)


def grid(L):
    bits = 5 * L
    return (bits + 1) // 2, bits // 2          # lon bits, lat bits


def rings(geom):
    polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
    for p in polys:
        yield p.exterior
        yield from p.interiors


def inside_mask(geom, L):
    lonb, latb = grid(L)
    pw, ph = 360 / 2 ** lonb, 180 / 2 ** latb
    w, s, e, n = geom.bounds
    ix0, iy0 = math.floor((w + 180) / pw), math.floor((s + 90) / ph)
    nx, ny = math.ceil((e + 180) / pw) - ix0, math.ceil((n + 90) / ph) - iy0
    xs = -180 + (ix0 + np.arange(nx + 1)) * pw
    ys = -90 + (iy0 + np.arange(ny + 1)) * ph
    X, Y = np.meshgrid(xs, ys)
    shapely.prepare(geom)
    c = shapely.contains_xy(geom, X, Y)
    m = c[:-1, :-1] & c[1:, :-1] & c[:-1, 1:] & c[1:, 1:]
    step = min(pw, ph) / 8                       # any pixel the boundary crosses is out
    for ring in rings(geom):
        xy = np.asarray(ring.coords)
        a, b = xy[:-1], xy[1:]
        k = np.maximum(1, (np.hypot(*(b - a).T) / step).astype(int) + 1)
        seg = np.repeat(np.arange(len(a)), k + 1)
        t = np.concatenate([np.linspace(0, 1, kk + 1) for kk in k])
        p = a[seg] + (b - a)[seg] * t[:, None]
        cx = np.floor((p[:, 0] + 180) / pw).astype(int) - ix0
        cy = np.floor((p[:, 1] + 90) / ph).astype(int) - iy0
        ok = (cx >= 0) & (cx < nx) & (cy >= 0) & (cy < ny)
        m[cy[ok], cx[ok]] = False
    return m, (ix0, iy0, pw, ph, lonb, latb)


def cell_pieces(m, meta, L):
    """Maximal whole geohash cells, as half-open pixel rectangles (x0, x1, y0, y1)."""
    ix0, iy0, pw, ph, lonb, latb = meta
    iy, ix = np.nonzero(m)
    gx, gy = (ix + ix0).astype(np.int64), (iy + iy0).astype(np.int64)
    full = {}
    for p in range(L, 0, -1):
        lb, tb = grid(p)
        sx, sy = lonb - lb, latb - tb
        key = ((gx >> sx) << 32) | (gy >> sy)
        u, cnt = np.unique(key, return_counts=True)
        full[p] = (set(u[cnt == (1 << (sx + sy))].tolist()), sx, sy)
    out = []
    for p in range(L, 0, -1):
        cells, sx, sy = full[p]
        if p > 1:
            parents, psx, psy = full[p - 1]
        for k in cells:
            cx, cy = k >> 32, k & 0xFFFFFFFF
            if p > 1 and (((cx << sx >> psx) << 32) | (cy << sy >> psy)) in parents:
                continue
            out.append((cx << sx, (cx + 1) << sx, cy << sy, (cy + 1) << sy))
    return np.array(out, dtype=np.int64).reshape(-1, 4) - [ix0, ix0, iy0, iy0]


def runs(m, axis):
    n = m.shape[axis]
    idx = np.arange(n)
    shape_ = [1, 1]; shape_[axis] = n
    idx = idx.reshape(shape_)
    lo = np.maximum.accumulate(np.where(~m, idx, -1), axis=axis) + 1
    hi = np.flip(np.minimum.accumulate(np.flip(np.where(~m, idx, n), axis=axis), axis=axis), axis=axis)
    return lo, hi


def overlap_pieces(m):
    ny, nx = m.shape
    S = np.zeros((ny + 1, nx + 1), np.int64)
    S[1:, 1:] = m.cumsum(0).cumsum(1)

    def full(y0, y1, x0, x1):
        return S[y1, x1] - S[y0, x1] - S[y1, x0] + S[y0, x0] == (y1 - y0) * (x1 - x0)

    rl, rh = runs(m, 1)
    cl, ch = runs(m, 0)
    covered = np.zeros_like(m)
    out = []
    for flat in np.flatnonzero(m):
        y, x = divmod(int(flat), nx)
        if covered[y, x]:
            continue
        best = None
        for first in ("h", "v"):
            if first == "h":
                x0, x1, y0, y1 = int(rl[y, x]), int(rh[y, x]), y, y + 1
                while y0 > 0 and full(y0 - 1, y1, x0, x1): y0 -= 1
                while y1 < ny and full(y0, y1 + 1, x0, x1): y1 += 1
            else:
                y0, y1, x0, x1 = int(cl[y, x]), int(ch[y, x]), x, x + 1
                while x0 > 0 and full(y0, y1, x0 - 1, x1): x0 -= 1
                while x1 < nx and full(y0, y1, x0, x1 + 1): x1 += 1
            if best is None or (x1 - x0) * (y1 - y0) > (best[1] - best[0]) * (best[3] - best[2]):
                best = (x0, x1, y0, y1)
        x0, x1, y0, y1 = best
        covered[y0:y1, x0:x1] = True
        out.append(best)
    return np.array(out, dtype=np.int64)


def partition_pieces(m):
    ny, nx = m.shape
    todo = m.copy()
    out = []
    for flat in np.flatnonzero(m):
        y, x = divmod(int(flat), nx)
        if not todo[y, x]:
            continue
        x1 = x + 1
        while x1 < nx and todo[y, x1]: x1 += 1
        y1 = y + 1
        while y1 < ny and todo[y1, x:x1].all(): y1 += 1
        todo[y:y1, x:x1] = False
        out.append((x, x1, y, y1))
    return np.array(out, dtype=np.int64)


def squares(geom, side_m, n):
    w, s, e, nn = geom.bounds
    got = []
    while sum(len(g) for g in got) < n:
        cx = rng.uniform(w, e, 4 * n); cy = rng.uniform(s, nn, 4 * n)
        hy = side_m / 2 / 111_320; hx = hy / np.cos(np.radians(cy))
        b = shapely.box(cx - hx, cy - hy, cx + hx, cy + hy)
        ok = shapely.contains(geom, b)
        got.append(np.stack([cx - hx, cx + hx, cy - hy, cy + hy], 1)[ok])
    return np.concatenate(got)[:n]


def test(m, meta, pieces, sq):
    ix0, iy0, pw, ph, _, _ = meta
    fx0 = np.floor((sq[:, 0] + 180) / pw).astype(np.int64) - ix0
    fx1 = np.ceil((sq[:, 1] + 180) / pw).astype(np.int64) - ix0
    fy0 = np.floor((sq[:, 2] + 90) / ph).astype(np.int64) - iy0
    fy1 = np.ceil((sq[:, 3] + 90) / ph).astype(np.int64) - iy0
    S = np.zeros((m.shape[0] + 1, m.shape[1] + 1), np.int64); S[1:, 1:] = m.cumsum(0).cumsum(1)
    inside = (S[fy1, fx1] - S[fy0, fx1] - S[fy1, fx0] + S[fy0, fx0]) == (fy1 - fy0) * (fx1 - fx0)
    found = {}
    for name, P in pieces.items():
        hit = np.zeros(len(sq), bool)
        for i in range(0, len(sq), 64):
            sl = slice(i, i + 64)
            hit[sl] = ((P[None, :, 0] <= fx0[sl, None]) & (fx1[sl, None] <= P[None, :, 1])
                       & (P[None, :, 2] <= fy0[sl, None]) & (fy1[sl, None] <= P[None, :, 3])).any(1)
        found[name] = hit
    return inside, found


def region(name, geom, levels, sides, n=10_000):
    for L in levels:
        t = time.time()
        m, meta = inside_mask(geom, L)
        pw, ph = meta[2], meta[3]
        lat = (geom.bounds[1] + geom.bounds[3]) / 2
        wm, hm = pw * 111_320 * math.cos(math.radians(lat)), ph * 111_320
        cover = m.sum() * pw * ph / geom.area
        pieces = {"cells": cell_pieces(m, meta, L), "part": partition_pieces(m), "overlap": overlap_pieces(m)}
        print(f"\n{name}, finest pixel geohash {L} ({wm:,.0f} m x {hm:,.0f} m): {m.sum():,} pixels inside, "
              f"{100 * cover:.1f}% of the area  [{time.time() - t:.0f} s]")
        print("  pieces: " + ", ".join(f"{k} {len(v):,}" for k, v in pieces.items()))
        for k, P in pieces.items():                  # each covers exactly the inside pixels
            paint = np.zeros(m.shape, np.int32)
            for x0, x1, y0, y1 in P:
                paint[y0:y1, x0:x1] += 1
            assert ((paint > 0) == m).all(), f"{k}: pieces do not cover exactly the inside pixels"
            assert k == "overlap" or paint.max() == 1, f"{k}: pieces overlap"
            if k == "overlap":
                print(f"  overlap: a point inside lies in {paint[m].mean():.1f} pieces on average, "
                      f"at most {paint.max()}")
        for side in sides:
            sq = squares(geom, side, n)
            inside, found = test(m, meta, pieces, sq)
            border = 100 * (~inside).mean()
            seams = ", ".join(f"{k} {100 * (inside & ~v).mean():.1f}%" for k, v in found.items())
            print(f"  {side:,} m squares: border misses {border:.1f}% (all three); seam misses: {seams}")


if sys.argv[2:] == ["countries"]:
    total = {"cells": 0, "overlap": 0, "pixels": 0}
    t = time.time()
    for f in json.load(open(f"{D}/ne_50m_admin_0_countries.geojson"))["features"]:
        g = shape(f["geometry"])
        m, meta = inside_mask(g, 5)
        if not m.any():
            continue
        total["cells"] += len(cell_pieces(m, meta, 5)); total["overlap"] += len(overlap_pieces(m))
        total["pixels"] += int(m.sum())
    print(f"all {len(json.load(open(f'{D}/ne_50m_admin_0_countries.geojson'))['features'])} countries "
          f"(Natural Earth 1:50m) at geohash 5: {total['pixels']:,} pixels inside; pieces: cells "
          f"{total['cells']:,}, overlap {total['overlap']:,}  [{time.time() - t:.0f} s]")
    sys.exit(0)
paris = shape(json.load(open(f"{D}/paris.geojson"))["features"][0]["geometry"])
fr = next(shape(f["geometry"]) for f in json.load(open(f"{D}/ne_10m_admin_0_countries.geojson"))["features"]
          if f["properties"].get("ADM0_A3") == "FRA")
metro = shapely.union_all([p for p in fr.geoms if p.intersects(box(-6, 41, 10, 52))])
print("Paris:", paris.geom_type, "France (mainland and Corsica):", metro.geom_type, len(metro.geoms), "polygons")
region("Paris", paris, (7, 8), (100,))
region("France", metro, (5, 6), (100, 1000))
