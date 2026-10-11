"""Assemble the read-only page into demo/freedom/dist/, and publish it.

    python3 demo/freedom/build.py                      # dist/ only
    python3 demo/freedom/build.py --publish --batch ID # and upload it to Swarm

dist/ holds the page, Pyodide's core files (from demo/pyodide's npm copy),
and wheels built from this checkout and from recordstore's beside it (the
page needs `RecordStore.get_many`, newer than recordstore's last release).
Everything the page loads comes from the same Swarm upload: no CDN, no
PyPI at run time.

Publishing posts dist/ to a Bee node's /bzz as one collection, prints its
reference (open it in Freedom as bzz://REF/, or through a node as
http://localhost:1633/bzz/REF/), and checks that the network can serve it
(GET /stewardship), since an upload that reports success may not have
landed (CLAUDE.md, Bee integration status).
"""

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PYODIDE = os.path.join(REPO, "demo", "pyodide", "node_modules", "pyodide")
PYODIDE_FILES = ("pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm",
                 "python_stdlib.zip", "pyodide-lock.json")
PAGE_FILES = ("index.html", "app.js", "swarm.js")


def wheel(project, out):
    """Build `project`'s wheel into `out`; return its file name."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", tmp, project],
                       check=True, stdout=subprocess.DEVNULL)
        (name,) = [f for f in os.listdir(tmp) if f.endswith(".whl")]
        shutil.copy(os.path.join(tmp, name), os.path.join(out, name))
        return name


def assemble(dist, recordstore, extra=()):
    if os.path.isdir(dist):
        shutil.rmtree(dist)
    os.makedirs(os.path.join(dist, "pyodide"))
    os.makedirs(os.path.join(dist, "wheels"))
    for f in PAGE_FILES:
        shutil.copy(os.path.join(HERE, f), os.path.join(dist, f))
    shutil.copytree(os.path.join(HERE, "vendor"), os.path.join(dist, "vendor"))
    for f in PYODIDE_FILES:
        shutil.copy(os.path.join(PYODIDE, f), os.path.join(dist, "pyodide", f))
    wheels = [wheel(recordstore, os.path.join(dist, "wheels")),
              wheel(REPO, os.path.join(dist, "wheels"))]
    wheels += [wheel(p, os.path.join(dist, "wheels")) for p in extra]
    with open(os.path.join(dist, "wheels", "manifest.json"), "w") as fh:
        json.dump({"wheels": wheels}, fh, indent=1)
    return wheels


def tar_of(dist):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for base, _dirs, files in os.walk(dist):
            for f in sorted(files):
                path = os.path.join(base, f)
                tar.add(path, arcname=os.path.relpath(path, dist))
    return buf.getvalue()


def publish(dist, api, batch):
    req = urllib.request.Request(
        f"{api}/bzz", data=tar_of(dist), method="POST",
        headers={"Content-Type": "application/x-tar",
                 "Swarm-Collection": "true",
                 "Swarm-Index-Document": "index.html",
                 "Swarm-Postage-Batch-Id": batch,
                 "Swarm-Deferred-Upload": "true"})
    with urllib.request.urlopen(req, timeout=600) as res:
        ref = json.load(res)["reference"]
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"{api}/stewardship/{ref}", timeout=120) as res:
                if json.load(res).get("isRetrievable"):
                    return ref, True
        except OSError:
            pass
        time.sleep(15)
    return ref, False


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", default=os.path.join(HERE, "dist"))
    ap.add_argument("--recordstore", default=os.path.join(os.path.dirname(REPO), "recordstore"))
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--api", default=os.environ.get("BEE_API", "http://localhost:1633"))
    ap.add_argument("--batch", default=os.environ.get("BEE_BATCH"))
    args = ap.parse_args()
    wheels = assemble(args.dist, args.recordstore)
    size = sum(os.path.getsize(os.path.join(b, f)) for b, _, fs in os.walk(args.dist) for f in fs)
    print(f"dist: {args.dist} ({size / 2**20:.1f} MB; wheels {', '.join(wheels)})")
    if args.publish:
        if not args.batch:
            sys.exit("publishing needs a postage batch: --batch ID or BEE_BATCH")
        ref, ok = publish(args.dist, args.api.rstrip("/"), args.batch)
        print(f"published: bzz://{ref}/  ({args.api}/bzz/{ref}/)")
        print("retrievable" if ok else "NOT yet retrievable: check GET /stewardship and upload again")


if __name__ == "__main__":
    main()
