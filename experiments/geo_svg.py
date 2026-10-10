"""Draw geo_fill.py's covers as SVG: one drawing per region and method.

usage: geo_svg.py DATA_DIR OUT_DIR

Writes OUT_DIR/<region>-<method>.svg and OUT_DIR/summary.json. The drawings
carry classes, not colours (`bnd` the true boundary, `piece` a piece of a
cover without overlap, `over` one of a cover with overlap), so the page that
shows them sets the colours; an overlapping cover's fill opacity is set so
a point under the average number of pieces is half covered.
"""
import json, math, os, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geo_fill as gf                                           # noqa: E402

WIDTH = 600


def draw(geom, m, meta, P, overlap, depth):
    ix0, iy0, pw, ph = meta[:4]
    w, s, e, n = geom.bounds
    k = math.cos(math.radians((s + n) / 2))
    scale = WIDTH / ((e - w) * k)
    X = lambda lon: (lon - w) * k * scale
    Y = lambda lat: (n - lat) * scale
    height = Y(s)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-4 -4 {WIDTH + 8:.0f} {height + 8:.0f}" '
           f'role="img">']
    alpha = 1 - 0.5 ** (1 / depth) if overlap else None
    cls = "over" if overlap else "piece"
    style = f' style="fill-opacity:{alpha:.4f}"' if overlap else ""
    out.append(f'<g class="{cls}"{style}>')
    for x0, x1, y0, y1 in P:
        lon0, lon1 = -180 + (ix0 + x0) * pw, -180 + (ix0 + x1) * pw
        lat0, lat1 = -90 + (iy0 + y0) * ph, -90 + (iy0 + y1) * ph
        out.append(f'<rect x="{X(lon0):.2f}" y="{Y(lat1):.2f}" width="{X(lon1) - X(lon0):.2f}" '
                   f'height="{Y(lat0) - Y(lat1):.2f}" fill="#1f7a8c"/>')
    out.append('</g>')
    simple = geom.simplify(min(pw, ph) / 3)
    d = []
    for ring in gf.rings(simple):
        xy = np.asarray(ring.coords)
        d.append("M" + " L".join(f"{X(a):.1f} {Y(b):.1f}" for a, b in xy) + " Z")
    out.append(f'<path class="bnd" fill="none" stroke="#8a2d6b" d="{" ".join(d)}"/>')
    out.append('</svg>')
    return "\n".join(out)


def main():
    D, OUT = sys.argv[1], sys.argv[2]
    os.makedirs(OUT, exist_ok=True)
    paris, france = gf.load(D)
    summary = {}
    for region, geom, L in (("paris", paris, 7), ("france", france, 5)):
        m, meta = gf.inside_mask(geom, L)
        pieces = gf.methods(m, meta, L, coarse=True)
        for method, P in pieces.items():
            d = np.zeros((m.shape[0] + 1, m.shape[1] + 1), np.int64)
            for dy, dx, sign in ((2, 0, 1), (2, 1, -1), (3, 0, -1), (3, 1, 1)):
                np.add.at(d, (P[:, dy], P[:, dx]), sign)
            paint = d.cumsum(0).cumsum(1)[:-1, :-1]
            depth = float(paint[m].mean())
            overlap = int(paint.max()) > 1
            with open(f"{OUT}/{region}-{method}.svg", "w") as fh:
                fh.write(draw(geom, m, meta, P, overlap, depth))
            summary[f"{region}-{method}"] = {"pieces": len(P), "depth": round(depth, 1),
                                             "most": int(paint.max())}
            print(region, method, summary[f"{region}-{method}"], flush=True)
    with open(f"{OUT}/summary.json", "w") as fh:
        json.dump(summary, fh, indent=1)


if __name__ == "__main__":
    main()
