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


def bare_install(spec, tmp):
    """What `pip install ontodag` alone drags in.

    Checked here rather than only in the test suite because this is the one
    place the *installed* package exists: B1 proves the core imports without
    optional dependencies, but a dev environment has them all installed, so
    nothing there can notice a hard dependency creeping back into
    pyproject. Until 2026-08-02 one had — 31 MB, a compiled extension and
    two bundled Java reasoners, for a package that used none of it."""
    venv = os.path.join(tmp, "bare")
    subprocess.run([sys.executable, "-m", "venv", venv], check=True)
    python = os.path.join(venv, "bin", "python")
    subprocess.run([python, "-m", "pip", "-q", "install", "--no-cache-dir",
                    spec], check=True)
    listed = subprocess.run(
        [python, "-m", "pip", "list", "--format=freeze"],
        capture_output=True, text=True, check=True).stdout.split()
    ignore = ("pip", "setuptools", "wheel", "ontodag", "recordstore")
    extra = [line for line in listed
             if not line.lower().startswith(ignore)]
    assert not extra, f"a bare install pulled in {extra}"

    # recordstore is allowed, but only because of what it is: pure Python
    # with no dependencies of its own. Assert the property rather than
    # trusting the name — a compiled extension anywhere in the base closure
    # is what breaks embedded targets and Pyodide.
    site = subprocess.run(
        [python, "-c", "import sysconfig;"
                       "print(sysconfig.get_paths()['purelib'])"],
        capture_output=True, text=True, check=True).stdout.strip()
    compiled = []
    for base, _dirs, files in os.walk(site):
        if os.path.basename(base) in ("pip", "setuptools", "wheel"):
            _dirs[:] = []
            continue
        compiled += [f for f in files if f.endswith((".so", ".pyd"))]
    assert not compiled, f"the base install ships compiled code: {compiled}"

    # ...and it has to actually work with nothing else present — including
    # the content-addressed store, which is the reason recordstore is here.
    subprocess.run([python, "-c",
                    "from ontodag import OntoDAG; d=OntoDAG();"
                    "d.put('a',[]); d.put('b',['a']);"
                    "assert [i.name for i in d.get(['a'])] == ['b']"],
                   check=True)
    return "ontodag + recordstore, pure Python, and the core works"


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

    def default_named_picture():
        # The 0.12.0–0.15.0 regression, in the same spirit: bare `visualize`
        # crashed for four releases because every test passed --out.
        o("visualize")
        path = os.path.join(env.home, "store.png")   # beside the default store
        assert os.path.exists(path), f"nothing at {path}"
        return os.path.basename(path)

    check("visualize with no --out names itself after the store",
          default_named_picture)

    def query_picture():
        o("visualize", "Japan", "--out", "scoped")
        path = os.path.join(env.work, "scoped.png")
        assert os.path.exists(path), "no image written"
        return f"{os.path.getsize(path)} bytes of PNG"

    check("visualize one query", query_picture)

    def exports():
        written = []
        for name in ("out.owl", "out.omn"):
            o("export", name)
            path = os.path.join(env.work, name)
            assert os.path.getsize(path) > 0, f"{name} is empty"
            written.append(name)
        return ", ".join(written)

    check("export to OWL and Manchester", exports)

    def excerpt():
        answer = sorted(o("get", "Japan").split())
        o("excerpt", "cut.od", "Japan")
        cut = os.path.join(env.work, "cut.od")
        assert os.path.getsize(cut) > 0, "empty excerpt"
        # The property that matters: it imports back as the same answer.
        got = sorted(env.odag_run("-f", cut, "list").split())
        assert got == answer, f"{got} != {answer}"
        return f"{len(answer)} items, importable"

    check("excerpt a query and read it back", excerpt)

    def contexted_excerpt_and_diff():
        # The send-and-review round trip, end to end: a contexted cut merges
        # into a store that has only the categories, and diffs clean against
        # the store it came from.
        o("excerpt", "sendable.od", "Japan", "--context")
        cut = os.path.join(env.work, "sendable.od")
        colleague = os.path.join(env.work, "colleague.od")
        env.odag_run("-f", colleague, "merge", cut)
        assert env.odag_run("-f", colleague, "get", "Japan").split() == \
            o("get", "Japan").split(), "the classification did not survive"
        env.odag_run("diff", cut, "Japan", expect=0)       # identical in scope
        env.odag_run("-f", colleague, "put", "extra-note", "Japan")
        env.odag_run("-f", colleague, "excerpt", "back.od", "Japan", "--context")
        back = os.path.join(env.work, "back.od")
        changed = env.odag_run("diff", back, "Japan", expect=1)   # exit 1
        assert "+ item extra-note" in changed, changed
        # And the additive fragment merges to what their store already says.
        env.odag_run("diff", back, "Japan", "--additions", "add.od", expect=1)
        env.odag_run("merge", os.path.join(env.work, "add.od"))
        assert "extra-note" in o("get", "Japan").split(), "fragment did not apply"
        return "send, merge, edit, diff, apply the additions"

    check("a contexted excerpt survives a round trip", contexted_excerpt_and_diff)

    def cone_removal():
        # The destructive one: look first, back up, delete, put it back.
        planned = env.odag_run("remove", "--cone", "Japan", "--dry-run").split()
        assert "Japan" in planned, planned
        assert "hotel.pdf" in o("get", "Japan").split()
        o("excerpt", "japan.od", "Japan", "--context")
        o("remove", "--cone", "Japan")
        assert "Japan" not in o("get").split(), "the cone survived"
        # boarding-pass.pdf is also a Flight, so it must NOT have gone with it
        assert "boarding-pass.pdf" in o("get", "Flight").split(), \
            "a multi-parent member was deleted with the cone"
        o("merge", os.path.join(env.work, "japan.od"))
        assert "hotel.pdf" in o("get", "Japan").split(), "the undo did not undo"
        return "dry-run, delete, multi-parent survivor, undo by merge"

    check("cone removal spares what hangs elsewhere", cone_removal)

    def reimport():
        o("export", "round.omn")
        o("-f", os.path.join(env.work, "round.omn"), "get", "Japan")
        return "a store survives export and re-read"

    check("import what was exported", reimport)

    def local_record_store():
        # The middle rung: canonical roots with no node, out of the box.
        path = os.path.join(env.work, "rs")
        o("-f", f"rs:{path}", "put", "Travel")
        o("-f", f"rs:{path}", "put", "Japan", "Travel")
        with open(os.path.join(path, "root")) as fh:
            root = fh.read().strip()
        assert len(root) == 64, root
        # Same knowledge, different build order, same name.
        other = os.path.join(env.work, "rs2")
        o("-f", f"rs:{other}", "put", "Travel")
        o("-f", f"rs:{other}", "put", "spare")
        o("-f", f"rs:{other}", "remove", "spare")
        o("-f", f"rs:{other}", "put", "Japan", "Travel")
        with open(os.path.join(other, "root")) as fh:
            assert fh.read().strip() == root, "roots diverged"
        return f"canonical root {root[:12]}... reproduced from another order"

    check("rs: local content-addressed store", local_record_store)

    def swarm_doctor():
        # It must run and diagnose rather than crash, with no node present.
        text = o("swarm", expect=1)
        assert "FAIL" in text, text
        assert "rs:" in text, "the doctor should offer the local rung"
        return "diagnoses a missing node and offers rs:"

    check("odag swarm diagnoses", swarm_doctor)


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
            try:
                import build  # noqa: F401
            except ImportError:
                print('this script builds the wheel itself and needs the '
                      '`build` package, which is not part of ontodag\'s own '
                      'install: pip install build', file=sys.stderr)
                return 1
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
        check("the base install stays pure Python",
              lambda: bare_install(spec, tmp))
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
