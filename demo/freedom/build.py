"""Assemble the read-only page into demo/freedom/dist/, and publish it.

    python3 demo/freedom/build.py                      # dist/ only
    python3 demo/freedom/build.py --publish --batch ID # and upload it to Swarm

dist/ holds the page and wheels built from this checkout and from
recordstore's beside it (the page needs `RecordStore.get_many`, newer than
recordstore's last release). Pyodide is not in it: the pages load Pyodide
from its own folder on Swarm (app.js, PYODIDE), published once with
`--pyodide-only`, so a page publish never stamps Pyodide again.
`--bundle-pyodide` puts a copy in dist/ instead, for a page that must
stand alone. No CDN, no PyPI at run time either way.

Publishing posts dist/ to a Bee node's /bzz as one collection, prints its
reference (open it in Freedom as bzz://REF/, or through a node as
http://localhost:1633/bzz/REF/), and checks that the network can serve it
(GET /stewardship), since an upload that reports success may not have
landed (CLAUDE.md, Bee integration status).
"""

import argparse
import hashlib
import io
import json
import os
import re
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


def copy_pyodide(folder):
    os.makedirs(folder, exist_ok=True)
    for f in PYODIDE_FILES:
        shutil.copy(os.path.join(PYODIDE, f), os.path.join(folder, f))


def assemble(dist, recordstore, extra=(), bundle_pyodide=False):
    if os.path.isdir(dist):
        shutil.rmtree(dist)
    os.makedirs(os.path.join(dist, "wheels"))
    for f in PAGE_FILES:
        shutil.copy(os.path.join(HERE, f), os.path.join(dist, f))
    shutil.copytree(os.path.join(HERE, "vendor"), os.path.join(dist, "vendor"))
    if bundle_pyodide:
        copy_pyodide(os.path.join(dist, "pyodide"))
    wheels = [wheel(recordstore, os.path.join(dist, "wheels")),
              wheel(REPO, os.path.join(dist, "wheels"))]
    wheels += [wheel(p, os.path.join(dist, "wheels")) for p in extra]
    with open(os.path.join(dist, "wheels", "manifest.json"), "w") as fh:
        json.dump({"wheels": wheels}, fh, indent=1)
    fingerprint(dist)
    return wheels


# A script reference the page makes itself: `src="app.js"` in HTML, or
# `from "./swarm.js"` / `import("./x.js")` in a module.
_SCRIPT_REF = re.compile(r"""(\bsrc=|\bfrom\s*|\bimport\s*\(\s*)(["'])((?:\./|\.\./)?[\w./-]+\.js)\2""")


def fingerprint(dist):
    """Give every local script reference a `?v=` of its file's content hash.
    A name's gateway caches scripts by URL (gwei.domains keeps one for as
    long as it is asked for) but not the HTML, so after a republish a
    browser could get the new page with the old scripts. Hashes are taken
    leaves first, so a change in swarm.js changes app.js's URL too."""
    done = {}

    def visit(path):
        if path in done:
            return done[path]
        done[path] = None  # an import cycle keeps the reference as it is
        with open(path, encoding="utf-8") as fh:
            text = fh.read()

        def tag(m):
            target = os.path.normpath(os.path.join(os.path.dirname(path), m.group(3)))
            if not os.path.isfile(target):
                return m.group(0)
            digest = visit(target)
            return m.group(0) if digest is None else \
                f"{m.group(1)}{m.group(2)}{m.group(3)}?v={digest}{m.group(2)}"

        text = _SCRIPT_REF.sub(tag, text)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        done[path] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        return done[path]

    visit(os.path.join(dist, "index.html"))


def tar_of(dist):
    """dist/ as a tar whose bytes depend only on the files: sorted, with no
    times or owners, so the same files publish to the same reference."""
    paths = sorted(os.path.relpath(os.path.join(base, f), dist)
                   for base, _dirs, files in os.walk(dist) for f in files)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for rel in paths:
            info = tarfile.TarInfo(rel)
            with open(os.path.join(dist, rel), "rb") as fh:
                data = fh.read()
            info.size, info.mode = len(data), 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def upload(dist, api, batch):
    req = urllib.request.Request(
        f"{api}/bzz", data=tar_of(dist), method="POST",
        headers={"Content-Type": "application/x-tar",
                 "Swarm-Collection": "true",
                 "Swarm-Index-Document": "index.html",
                 "Swarm-Redundancy-Level": "0",
                 "Swarm-Postage-Batch-Id": batch,
                 "Swarm-Deferred-Upload": "true"})
    with urllib.request.urlopen(req, timeout=600) as res:
        return json.load(res)["reference"]


def retrievable(api, ref, minutes):
    """Ask the node, until `minutes` have passed, whether the network serves
    `ref` (GET /stewardship re-reads it from the network: slow for a page)."""
    deadline = time.time() + 60 * minutes
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{api}/stewardship/{ref}", timeout=300) as res:
                if json.load(res).get("isRetrievable"):
                    return True
            print("  not retrievable yet", flush=True)
        except OSError as e:
            print(f"  stewardship: {e}", flush=True)
        time.sleep(30)
    return False


def advance_feed(name, api, ref, batch):
    """Point the page's feed (page_feed.py) at the new upload, so its stable
    address and its name (ontodag.gwei) open this version, no transaction."""
    sys.path.insert(0, HERE)
    import page_feed
    owner, manifest = page_feed.point(api, name, ref, batch)
    print(f"feed advanced: bzz://{manifest}/ now opens this version", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", default=os.path.join(HERE, "dist"))
    ap.add_argument("--recordstore", default=os.path.join(os.path.dirname(REPO), "recordstore"))
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--api", default=os.environ.get("BEE_API", "http://localhost:1633"))
    ap.add_argument("--batch", default=os.environ.get("BEE_BATCH"))
    ap.add_argument("--no-build", action="store_true", help="publish dist/ as it is")
    ap.add_argument("--bundle-pyodide", action="store_true",
                    help="put Pyodide in dist/ instead of loading the shared folder")
    ap.add_argument("--pyodide-only", action="store_true",
                    help="assemble (and with --publish, publish) the shared Pyodide folder alone")
    ap.add_argument("--wait", type=float, default=20,
                    help="minutes to wait for the network to serve the upload")
    args = ap.parse_args()
    if args.pyodide_only:
        args.dist = os.path.join(HERE, "dist-pyodide")
        if os.path.isdir(args.dist):
            shutil.rmtree(args.dist)
        copy_pyodide(args.dist)
    elif not args.no_build:
        wheels = assemble(args.dist, args.recordstore, bundle_pyodide=args.bundle_pyodide)
        print(f"wheels: {', '.join(wheels)}")
    size = sum(os.path.getsize(os.path.join(b, f)) for b, _, fs in os.walk(args.dist) for f in fs)
    print(f"dist: {args.dist} ({size / 2**20:.1f} MB)", flush=True)
    if args.publish:
        if not args.batch:
            sys.exit("publishing needs a postage batch: --batch ID or BEE_BATCH")
        api = args.api.rstrip("/")
        ref = upload(args.dist, api, args.batch)
        print(f"published: bzz://{ref}/  ({api}/bzz/{ref}/)", flush=True)
        if not args.pyodide_only:
            advance_feed("ontodag", api, ref, args.batch)
        ok = retrievable(api, ref, args.wait)
        print("retrievable" if ok else "NOT yet retrievable: check GET /stewardship later, and upload again if it stays so")


if __name__ == "__main__":
    main()
