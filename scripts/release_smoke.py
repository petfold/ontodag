#!/usr/bin/env python3
"""Use the built artifact before publishing it. Or after, against PyPI.

Why this exists: 0.10.0 was published unable to draw any DAG containing a
typed date. The test suite was green, CI was green, the docs pass had been
done. What nobody did was install the thing and ask it for a picture.

So this installs the package into a throwaway virtualenv — no repo on the
path, no editable install, no local state — and drives the `odag` command
the way a new user would. It is deliberately end-to-end and shallow rather
than clever: every check here is something a user would notice in their
first ten minutes.

    python3 scripts/release_smoke.py                # build, then check
    python3 scripts/release_smoke.py --wheel W.whl  # check an existing build
    python3 scripts/release_smoke.py --pypi 0.10.1  # check what PyPI serves

The --pypi mode is the post-publish verification: run it against a version
number and it proves the artifact users actually receive works, rather than
the one on your disk. Note PyPI's index takes a short while to propagate
after an upload, so a run immediately after `twine upload` can install the
*previous* release; this script fails loudly on a version mismatch rather
than quietly testing the wrong thing.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Optional deps the rendering and export checks need. They are not part of
# the package's own requirements, which is the point: a user who wants
# pictures installs these, and this is where we find out whether that works.
EXTRA_DEPS = ["graphviz", "pillow", "owlready2", "dot2tex"]

results = []


def check(name, fn):
    try:
        detail = fn()
        results.append((True, name, detail or ""))
    except Exception as exc:                      # noqa: BLE001 - a report
        results.append((False, name, f"{type(exc).__name__}: {exc}"))


class Env:
    """A throwaway virtualenv with the package installed into it."""

    def __init__(self, tmp):
        self.dir = os.path.join(tmp, "venv")
        self.home = os.path.join(tmp, "home")
        self.work = os.path.join(tmp, "work")
        os.makedirs(self.work)
        subprocess.run([sys.executable, "-m", "venv", self.dir], check=True)

    @property
    def python(self):
        return os.path.join(self.dir, "bin", "python")

    @property
    def odag(self):
        return os.path.join(self.dir, "bin", "odag")

    def pip(self, *args):
        subprocess.run([self.python, "-m", "pip", "-q", "install",
                        "--no-cache-dir", *args], check=True)

    def run(self, *argv, expect=0):
        """Run odag with an isolated home, so no developer config leaks in."""
        env = dict(os.environ, ONTODAG_HOME=self.home)
        env.pop("ONTODAG_STORE", None)
        env.pop("ONTODAG_LIMIT", None)
        env.pop("ONTODAG_SURFACE", None)
        proc = subprocess.run(argv, capture_output=True, text=True,
                              env=env, cwd=self.work)
        if expect is not None and proc.returncode != expect:
            raise AssertionError(
                f"{' '.join(argv[1:])!r} exited {proc.returncode}, "
                f"wanted {expect}: {(proc.stderr or proc.stdout).strip()[:200]}")
        return proc.stdout

    def odag_run(self, *args, expect=0):
        return self.run(self.odag, *args, expect=expect)


def smoke(env, expect_version):
    o = env.odag_run

    def version():
        got = o("-V").strip()
        assert got == expect_version, f"got {got}, expected {expect_version}"
        return got

    check("version is the one being released", version)

    check("the core imports with no optional dependency in play",
          lambda: env.run(env.python, "-c",
                          "import ontodag; ontodag.OntoDAG()") and "ok")

    check("prelude adopts the standard dimensions",
          lambda: o("prelude") and "" or "silent, as designed")

    def build():
        o("put", "Travel")
        o("put", "Japan", "Travel")
        o("put", "Flight", "Travel")
        o("put", "boarding-pass.pdf", "Flight", "Japan",
          "time(2026-08-15)", "weight(3kg)")
        o("put", "hotel.pdf", "Japan")
        return "5 items, two of them typed"

    check("put, including typed values", build)

    def query():
        got = sorted(o("get", "Japan").split())
        assert got == ["boarding-pass.pdf", "hotel.pdf"], got
        return " ".join(got)

    check("get returns what was filed", query)

    def computed():
        # The containment nobody stored: filed under a day, found by year.
        got = o("get", "Travel", "time(2026)").split()
        assert got == ["boarding-pass.pdf"], got
        assert o("below", "time(2026-08-15)", "time(2026)").strip() == "true"
        return "a day is inside its year, computed from the names"

    check("dimension arithmetic answers a query", computed)

    def empty():
        everything = o("get").split()
        assert "hotel.pdf" in everything, everything
        assert o("count").strip() == str(len(everything))
        assert o("list").split() == everything
        return f"{len(everything)} items, get == list == count"

    check("the empty query is everything", empty)

    def capped():
        lines = o("-n", "2", "get").splitlines()
        assert len(lines) == 2, lines
        return "-n 2 gives 2 lines"

    check("the display cap", capped)

    def canon():
        got = o("canon", "time(2026-08-15)").strip()
        assert got.startswith("time(2026-08-15T00:00:00Z"), got
        return got

    check("canon shows the stored form", canon)

    def picture():
        # THE 0.10.0 REGRESSION. A store containing a typed date could not
        # be drawn at all, and no amount of green test suite said so.
        o("visualize", "--out", "smoke")
        path = os.path.join(env.work, "smoke.png")
        assert os.path.exists(path), "no image written"
        with open(path, "rb") as fh:
            assert fh.read(4) == b"\x89PNG", "not a PNG"
        return f"{os.path.getsize(path)} bytes of PNG"

    check("visualize a DAG containing a typed date", picture)

    def exports():
        written = []
        for name in ("out.owl", "out.omn"):
            o("export", name)
            path = os.path.join(env.work, name)
            assert os.path.getsize(path) > 0, f"{name} is empty"
            written.append(name)
        return ", ".join(written)

    check("export to OWL and Manchester", exports)

    def reimport():
        o("export", "round.omn")
        o("-f", os.path.join(env.work, "round.omn"), "get", "Japan")
        return "a store survives export and re-read"

    check("import what was exported", reimport)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wheel", help="check this wheel instead of building")
    ap.add_argument("--pypi", metavar="VERSION",
                    help="check what PyPI serves for this version")
    args = ap.parse_args()

    if args.pypi:
        spec, expect = f"ontodag=={args.pypi}", args.pypi
        source = f"PyPI ({args.pypi})"
    else:
        wheel = args.wheel
        if not wheel:
            print("building ...", flush=True)
            subprocess.run([sys.executable, "-m", "build", "--wheel",
                            "--outdir", os.path.join(ROOT, "dist")],
                           cwd=ROOT, check=True,
                           stdout=subprocess.DEVNULL)
            built = sorted(
                os.path.join(ROOT, "dist", f)
                for f in os.listdir(os.path.join(ROOT, "dist"))
                if f.endswith(".whl"))
            wheel = built[-1]
        spec, source = wheel, os.path.basename(wheel)
        expect = os.path.basename(wheel).split("-")[1]

    print(f"smoke-testing {source}\n", flush=True)
    tmp = tempfile.mkdtemp(prefix="ontodag-smoke-")
    try:
        env = Env(tmp)
        env.pip(spec, *EXTRA_DEPS)
        smoke(env, expect)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    width = max(len(name) for _, name, _ in results)
    for ok, name, detail in results:
        mark = "PASS" if ok else "FAIL"
        print(f"  {mark}  {name.ljust(width)}  {detail}")
    failed = [name for ok, name, _ in results if not ok]
    print()
    if failed:
        print(f"{len(failed)} check(s) failed — do not publish this build.")
        return 1
    print(f"all {len(results)} checks passed on {source}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
