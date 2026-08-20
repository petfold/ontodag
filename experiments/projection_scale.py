#!/usr/bin/env python3
"""The PROJECTIONS.md §10.1 measurement: full-rebuild ingestion and
overlay-view composition at personal-corpus scale, with no real files.

Generates a datacat-shaped projection stream (fake hashes; sys:on:MEDIUM,
sys:type:EXT, sys:backup:N supercategories; ~20% of items on a second
medium) and times, per size:

  ingest        fresh store <- stream (the first build)
  re-ingest     same stream again (idempotence cost: all puts are no-ops)
  rebuild       ingest --drop sys: (the contract's full-rebuild path)
  cold query    a fresh session's first cross-layer `get` through the
                overlay view — composition (merge of the whole projection)
                plus the query; this is what every one-shot CLI call pays
  warm query    the same query again in the same session (view cached)
  file          the projection store's size on disk
  peak RSS      of this process after the run (cumulative high-water mark)

Run:  python3 experiments/projection_scale.py [N ...]   (default 10k 100k)

The verdict this exists to produce: whether "idempotent full rebuild, no
diffing" and per-invocation view composition survive 10^5-10^6 memberships,
or whether the overlay view needs a composed cache / a resident session
(interactive prompt, web, fs mount) at that scale.
"""

import io
import json
import os
import random
import resource
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import ontodag.__main__ as cli  # noqa: E402

MEDIA = ["laptop", "drive-budapest", "drive-standrews"]
TYPES = ("jpg png gif heic mp4 mov mp3 flac pdf epub txt md tex bib doc "
         "docx xls ods csv json xml yaml html css js ts py go rs c h java "
         "sh sql zip gz tar iso log ics vcf eml none").split()
BACKUPS = [0, 0, 1, 1, 2, 3]


def write_stream(path, n, seed=7):
    rng = random.Random(seed)
    with open(path, "w", encoding="utf-8") as fh:
        for i in range(n):
            supers = {f"sys:on:{rng.choice(MEDIA)}",
                      f"sys:type:{rng.choice(TYPES)}",
                      f"sys:backup:{rng.choice(BACKUPS)}"}
            if rng.random() < 0.2:          # duplicated onto a second medium
                supers.add(f"sys:on:{rng.choice(MEDIA)}")
            fh.write(json.dumps({"item": f"sha256:{i:064x}",
                                 "supercategories": sorted(supers)}) + "\n")


def run(argv, session):
    out = io.StringIO()
    code = cli.dispatch(argv, session, out=out, err=io.StringIO())
    assert code == 0, (argv, code)
    return out.getvalue()


def timed(fn):
    t0 = time.perf_counter()
    result = fn()
    return time.perf_counter() - t0, result


def measure(n):
    with tempfile.TemporaryDirectory() as home:
        os.environ["ONTODAG_HOME"] = home
        os.environ.pop("ONTODAG_OVERLAYS", None)
        proj = os.path.join(home, "proj.od")
        human = os.path.join(home, "human.od")
        stream = os.path.join(home, "stream.jsonl")
        write_stream(stream, n)

        session = cli.Session(proj)
        t_ingest, _ = timed(lambda: run(["ingest", stream], session))
        t_reingest, _ = timed(lambda: run(["ingest", stream], session))
        t_rebuild, _ = timed(
            lambda: run(["ingest", "--drop", "sys:", stream], session))

        curator = cli.Session(human)
        run(["put", "papers"], curator)
        run(["put", f"sha256:{0:064x}", "papers"], curator)

        os.environ["ONTODAG_OVERLAYS"] = proj
        reader = cli.Session(human)
        query = ["get", "papers", f"sys:on:{MEDIA[0]}"]
        t_cold, _ = timed(lambda: run(query, reader))     # compose + query
        t_warm, _ = timed(lambda: run(query, reader))     # cached view
        os.environ.pop("ONTODAG_OVERLAYS", None)

        size_mb = os.path.getsize(proj) / 1e6
        rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        print(f"{n:>9,} | {t_ingest:8.2f} | {t_reingest:9.2f} | "
              f"{t_rebuild:8.2f} | {t_cold:8.2f} | {t_warm:6.3f} | "
              f"{size_mb:7.1f} | {rss_mb:7.0f}")


def main():
    sizes = [int(float(a)) for a in sys.argv[1:]] or [10_000, 100_000]
    print(f"{'items':>9} | {'ingest':>8} | {'re-ingest':>9} | "
          f"{'rebuild':>8} | {'cold get':>8} | {'warm':>6} | "
          f"{'file MB':>7} | {'RSS MB':>7}")
    for n in sizes:
        measure(n)


if __name__ == "__main__":
    main()
