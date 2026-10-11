"""Stability in absolute numbers: the pieces a boundary edit rewrites, per cover.

The third measurement behind question 29 (docs/DIMENSIONS.md §22), with
geo_fill.py's downloads in DATA_DIR.

usage: geo_stability.py DATA_DIR

Two edits: the whole boundary simplified within a quarter of a grid square
(a new version of the data), and a block of 3x3 squares at one random point
of the edge taken out or put in (a local correction), 20 times. A piece is
rewritten when the old cover has it and the new one does not, or the other
way round; the count is what a new version of a places pack would change.
"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geo_fill as gf                                           # noqa: E402
import geo_bounds as gb                                         # noqa: E402

rng = np.random.default_rng(7)


def covers(m, meta, L):
    maximal = gf.maximal_pieces(m)
    T = gf.largest_first_partition(m)
    C = gf.cell_pieces(m, meta, L)
    return {"cells": C, "largest first, tiling": T,
            "largest first, overlapping": gf.largest_first_overlap(m, maximal),
            "cells + margin": gb.grow(m, C, 1), "tiling + margin": gb.grow(m, T, 1)}


def diff(a, b):
    A = set(map(tuple, a.tolist())); B = set(map(tuple, b.tolist()))
    return len(A - B), len(B - A)


def main():
    D = sys.argv[1]
    paris, france = gf.load(D)
    for name, geom, L, k in (("Paris", paris, 7, 3), ("France", france, 5, 3)):
        m, meta = gf.inside_mask(geom, L)
        base = covers(m, meta, L)
        print(f"\n{name}, geohash {L}: " + ", ".join(f"{n} {len(P):,}" for n, P in base.items()))
        m2, _ = gf.inside_mask(geom.simplify(min(meta[2], meta[3]) / 4), L)
        g = covers(m2, meta, L)
        print(f"  global edit (whole boundary simplified, {(m != m2).sum():,} squares flip): pieces "
              "removed+added: " + ", ".join(f"{n} {sum(diff(base[n], g[n]))}" for n in base), flush=True)
        # local edits: a k x k block at a random point of the edge taken out or put in
        ny, nx = m.shape
        pad = np.pad(m, 1)
        edge_in = m & ~(pad[:-2, 1:-1] & pad[2:, 1:-1] & pad[1:-1, :-2] & pad[1:-1, 2:])
        edge_out = ~m & (pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:])
        res = {n: [] for n in base}
        trials = 10
        for t in range(2 * trials):
            src = edge_in if t < trials else edge_out
            ys, xs = np.nonzero(src)
            i = rng.integers(len(ys))
            y, x = ys[i], xs[i]
            e = m.copy()
            e[max(0, y - k // 2):y + k // 2 + 1, max(0, x - k // 2):x + k // 2 + 1] = t >= trials
            c = covers(e, meta, L)
            for n in base:
                res[n].append(sum(diff(base[n], c[n])))
        print(f"  local edit ({k}x{k} squares at one point of the edge, out or in; {2 * trials} trials): "
              "pieces removed+added, median / most: " + ", ".join(
                  f"{n} {int(np.median(v))} / {max(v)}" for n, v in res.items()), flush=True)


if __name__ == "__main__":
    main()
