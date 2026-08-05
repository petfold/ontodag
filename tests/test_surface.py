"""The surface layer's output half (docs/plans/SURFACE_LAYER.md §4, §6, §7).

The one law, fuzzed here in its only promised direction:

    elaborate(render(t)) == t        for every canonical term t

`render(elaborate(s)) == s` is deliberately NOT asserted anywhere — the
user's spelling normalizes away (§4's non-law; do not "fix" this).

CLI coverage: the §9.4 pipe rule (canonical when stdout is not a terminal,
--render/--raw/$ONTODAG_SURFACE overrides, flag > env > tty) and the
`canon` command. The tty *default* needs a real pty, tested at the end.
"""

import io
import os
import pty
import random
import select
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

import ontodag
from ontodag import dimensions as dims
from ontodag import surface
from ontodag.__main__ import Session, dispatch, _OVERRIDES

REPO_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def declared_dag():
    dag = ontodag.OntoDAG()
    dag.put("dimension", [])
    dag.put("linear-dimension", ["dimension"])
    dag.put("calendar-dimension", ["dimension"])
    dag.put("prefix-dimension", ["dimension"])
    dag.put("dominance-dimension", ["dimension"])
    dag.put("weight", ["linear-dimension"])
    dag.put("logged", ["linear-dimension"])      # legacy linear time
    dag.put("time", ["calendar-dimension"])
    dag.put("geo", ["prefix-dimension"])
    dag.put("size", ["dominance-dimension"])
    return dag


class TestRenderingTable(unittest.TestCase):
    """The §6 table and its neighbours, against a declared DAG."""

    def setUp(self):
        self.dag = declared_dag()

    def r(self, name):
        return surface.render(name, self.dag)

    def test_calendar_periods_collapse(self):
        self.assertEqual(
            self.r("time(2026-01-01T00:00:00Z..2026-12-31T23:59:59Z)"),
            "time(2026)")
        self.assertEqual(
            self.r("time(2026-08-01T00:00:00Z..2026-08-31T23:59:59Z)"),
            "time(2026-08)")
        self.assertEqual(
            self.r("time(2026-08-15T00:00:00Z..2026-08-15T23:59:59Z)"),
            "time(2026-08-15)")

    def test_calendar_ranges_collapse_per_end(self):
        self.assertEqual(
            self.r("time(2026-03-01T00:00:00Z..2026-08-31T23:59:59Z)"),
            "time(2026-03..2026-08)")
        self.assertEqual(self.r("time(..2025-12-31T23:59:59Z)"),
                         "time(..2025)")
        self.assertEqual(self.r("time(2026-01-01T00:00:00Z..)"),
                         "time(2026..)")

    def test_an_instant_stays_a_timestamp(self):
        self.assertEqual(self.r("time(2026-08-15T12:00:00Z)"),
                         "time(2026-08-15T12:00:00Z)")

    def test_units_re_express(self):
        self.assertEqual(self.r("weight(3kg)"), "weight(3kg)")
        self.assertEqual(self.r("weight(..5kg)"), "weight(..5kg)")
        self.assertEqual(self.r("weight(800000mg..1500000mg)"),
                         "weight(800g..1500g)")
        self.assertEqual(self.r("weight(1500mg)"), "weight(1500mg)")
        self.assertEqual(self.r("weight(1000000000mg)"), "weight(1t)")
        self.assertEqual(self.r("weight(0mg)"), "weight(0kg)")  # zero keeps the anchor

    def test_dominance_and_prefix(self):
        self.assertEqual(self.r("size(390x230x190mm)"), "size(39x23x19cm)")
        self.assertEqual(self.r("geo(u2ed)"), "geo(u2ed)")

    def test_linear_time_collapses_days_but_never_years(self):
        # Bare dates are admissible in the linear grammar; bare years are a
        # count there, so the year spelling would change the meaning.
        self.assertEqual(
            self.r("logged(2026-08-15T00:00:00Z..2026-08-15T23:59:59Z)"),
            "logged(2026-08-15)")
        self.assertEqual(
            self.r("logged(2026-01-01T00:00:00Z..2026-12-31T23:59:59Z)"),
            "logged(2026-01-01..2026-12-31)")

    def test_opaque_and_contextless_names_pass_through(self):
        # An undeclared head only *looks* parametric: rendering it would
        # break the law, since elaboration keeps it opaque.
        self.assertEqual(self.r("foo(3000000mg)"), "foo(3000000mg)")
        self.assertEqual(self.r("cat"), "cat")
        self.assertEqual(surface.render("weight(3kg)"),  # no context
                         "weight(3kg)")

    def test_kind_direct_context(self):
        self.assertEqual(
            surface.render("weight(3kg)", kind=dims.KIND_LINEAR),
            "weight(3kg)")

    def test_injectivity_the_almost_a_year_range(self):
        t = "time(2026-01-01T00:00:00Z..2026-12-31T23:59:58Z)"  # 1s short
        rendered = surface.render(t, self.dag)
        self.assertNotEqual(rendered, "time(2026)")
        self.assertEqual(surface.elaborate(rendered, self.dag), t)

    def test_render_is_a_pure_function_of_the_canonical_name(self):
        spellings = ["weight(3kg)", "weight(3000g)", "weight(3kg)"]
        rendered = {surface.render(surface.elaborate(s, self.dag), self.dag)
                    for s in spellings}
        self.assertEqual(rendered, {"weight(3kg)"})

    def test_version_constant(self):
        self.assertEqual(surface.SURFACE_VERSION, "0.1")


class TestRoundTripFuzz(unittest.TestCase):
    """elaborate(render(t)) == t over randomized canonical terms, plus
    rendering determinism. Seeded: failures reproduce."""

    def setUp(self):
        self.dag = declared_dag()
        self.rnd = random.Random(20260801)

    def check(self, raw):
        t = surface.elaborate(raw, self.dag)
        r1 = surface.render(t, self.dag)
        r2 = surface.render(t, self.dag)
        self.assertEqual(r1, r2, f"nondeterministic render of {t!r}")
        self.assertEqual(surface.elaborate(r1, self.dag), t,
                         f"round trip broke: {raw!r} -> {t!r} -> {r1!r}")

    def _mass(self):
        scale = self.rnd.choice([1, 1, 10**3, 10**6, 10**9])
        return self.rnd.randint(0, 5000) * scale

    def test_linear_masses(self):
        for _ in range(120):
            shape = self.rnd.randrange(4)
            if shape == 0:
                raw = f"weight({self._mass()}mg)"
            elif shape == 1:
                lo, hi = sorted((self._mass(), self._mass()))
                raw = f"weight({lo}mg..{hi}mg)"
            elif shape == 2:
                raw = f"weight(..{self._mass()}mg)"
            else:
                raw = f"weight({self._mass()}mg..)"
            self.check(raw)

    def _instant(self):
        return (f"{self.rnd.randint(1990, 2100):04d}-"
                f"{self.rnd.randint(1, 12):02d}-"
                f"{self.rnd.randint(1, 28):02d}T"
                f"{self.rnd.randint(0, 23):02d}:"
                f"{self.rnd.randint(0, 59):02d}:"
                f"{self.rnd.randint(0, 59):02d}Z")

    def _calendar_literal(self, ts):
        # A random truncation of `ts`: year, month, day or the instant.
        return ts[:self.rnd.choice([4, 7, 10, 20])]

    def test_calendar_terms(self):
        for _ in range(120):
            a, b = sorted((self._instant(), self._instant()))
            lo, hi = self._calendar_literal(a), self._calendar_literal(b)
            # lo expands downward from a, hi upward from b, so lo <= hi
            # always holds and every generated range is non-empty.
            shape = self.rnd.randrange(4)
            if shape == 0:
                raw = f"time({lo})"
            elif shape == 1:
                raw = f"time({lo}..{hi})"
            elif shape == 2:
                raw = f"time(..{hi})"
            else:
                raw = f"time({lo}..)"
            self.check(raw)

    def test_dominance_and_prefix_terms(self):
        for _ in range(60):
            parts = [str(self.rnd.randint(0, 400) *
                         self.rnd.choice([1, 10, 1000]))
                     for _ in range(self.rnd.randint(2, 4))]
            self.check(f"size({'x'.join(parts)}mm)")
        for _ in range(20):
            cell = "".join(self.rnd.choice("0123456789bcdefghjkmnpqrstuvwxyz")
                           for _ in range(self.rnd.randint(1, 8)))
            self.check(f"geo({cell})")


class TestSurfaceCLI(unittest.TestCase):
    """The §9.4 pipe rule through dispatch(), and `canon`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "store.od")
        self.session = Session(self.store)
        self._env = os.environ.pop("ONTODAG_SURFACE", None)
        _OVERRIDES.clear()
        for line in ("put dimension", "put calendar-dimension dimension",
                     "put linear-dimension dimension",
                     "put time calendar-dimension",
                     "put weight linear-dimension"):
            self.run_cmd(line.split())
        self.run_cmd(["put", "doc", "time(2026)"])
        self.run_cmd(["put", "parcel", "weight(3kg)"])

    def tearDown(self):
        if self._env is not None:
            os.environ["ONTODAG_SURFACE"] = self._env
        else:
            os.environ.pop("ONTODAG_SURFACE", None)
        _OVERRIDES.clear()
        self.tmp.cleanup()

    def run_cmd(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = dispatch(argv, self.session)
        return code, buf.getvalue().splitlines()

    CANONICAL = "time(2026-01-01T00:00:00Z..2026-12-31T23:59:59Z)"

    def test_pipe_default_is_canonical(self):
        _, lines = self.run_cmd(["list"])          # StringIO is not a tty
        self.assertIn(self.CANONICAL, lines)
        self.assertNotIn("time(2026)", lines)

    def test_render_flag_forces_friendly(self):
        _, lines = self.run_cmd(["list", "--render"])
        self.assertIn("time(2026)", lines)
        self.assertIn("weight(3kg)", lines)
        self.assertNotIn(self.CANONICAL, lines)

    def test_env_turns_rendering_on_and_flag_beats_env(self):
        os.environ["ONTODAG_SURFACE"] = "1"
        _, lines = self.run_cmd(["list"])
        self.assertIn("time(2026)", lines)
        _, lines = self.run_cmd(["list", "--raw"])  # flag > env
        self.assertIn(self.CANONICAL, lines)
        self.assertNotIn("time(2026)", lines)

    def test_global_override_applies_to_plain_commands(self):
        _OVERRIDES["render"] = "on"                 # what a leading --render
        _, lines = self.run_cmd(["list"])           # in main() sets
        self.assertIn("time(2026)", lines)

    def test_show_renders_too(self):
        _, raw_lines = self.run_cmd(["show"])
        self.assertTrue(any(self.CANONICAL in line for line in raw_lines))
        _, lines = self.run_cmd(["show", "--render"])
        self.assertTrue(any("time(2026)" in line for line in lines))
        self.assertFalse(any(self.CANONICAL in line for line in lines))

    def test_canon_prints_the_stored_form(self):
        _, lines = self.run_cmd(["canon", "time(2026)"])
        self.assertEqual(lines, [self.CANONICAL])
        _, lines = self.run_cmd(["canon", "weight(3kg)"])
        self.assertEqual(lines, ["weight(3kg)"])
        _, lines = self.run_cmd(["canon", "cat"])   # opaque: itself
        self.assertEqual(lines, ["cat"])

    def test_canon_without_a_term_prints_versions(self):
        _, lines = self.run_cmd(["canon"])
        self.assertEqual(lines, [f"surface {surface.SURFACE_VERSION}",
                                 f"registry {dims.REGISTRY_VERSION}"])

    def test_canon_surfaces_the_teaching_error(self):
        code, _ = self.run_cmd(["canon", "weight(3zz)"])
        self.assertEqual(code, 1)

    def test_round_trips_through_a_pipe_by_default(self):
        # The reason the rule exists: canonical bytes out, canonical in.
        _, lines = self.run_cmd(["list"])
        for name in lines:
            self.assertEqual(surface.elaborate(name, self.session.dag), name)


class TestTtyDefault(unittest.TestCase):
    """The default path of the §9.4 rule needs a real pty: on a terminal,
    names render friendly with no flag and no env."""

    def _run(self, tty):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = os.path.join(tmp.name, "store.od")
        session = Session(store)
        for line in ("put dimension", "put calendar-dimension dimension",
                     "put time calendar-dimension"):
            dispatch(line.split(), session)
        dispatch(["put", "doc", "time(2026)"], session)

        env = dict(os.environ, PYTHONPATH=REPO_SRC, ONTODAG_HOME=tmp.name)
        env.pop("ONTODAG_SURFACE", None)
        argv = [sys.executable, "-m", "ontodag", "-f", store, "list"]
        if not tty:
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  env=env, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return proc.stdout.splitlines()
        # Drain the pty WHILE the child runs, and drop our own copy of the
        # slave fd straight away so that the child holds the only writer.
        # Reading only after the child has exited — which is what
        # subprocess.run forces — works on Linux and returns nothing at all on
        # macOS: there the kernel discards whatever is still sitting in a pty's
        # buffer once the last writer reference goes away, so the test read an
        # empty terminal and blamed the renderer for it. Draining first also
        # removes the deadlock that would otherwise appear if the output ever
        # outgrew the pty buffer.
        master, slave = pty.openpty()
        proc = subprocess.Popen(argv, stdout=slave, stderr=subprocess.PIPE,
                                env=env)
        os.close(slave)
        chunks = []
        try:
            while True:
                if not select.select([master], [], [], 60)[0]:
                    raise AssertionError("timed out draining the pty")
                try:
                    data = os.read(master, 65536)
                except OSError:
                    break               # EIO: the writing end is gone
                if not data:
                    break               # EOF
                chunks.append(data)
            stderr = proc.communicate(timeout=60)[1]
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertEqual(proc.returncode, 0, stderr)
        text = b"".join(chunks).decode()
        return [line.strip() for line in text.replace("\r", "").splitlines()]

    def test_terminal_renders_pipe_does_not(self):
        self.assertIn("time(2026)", self._run(tty=True))
        piped = self._run(tty=False)
        self.assertNotIn("time(2026)", piped)
        self.assertIn("time(2026-01-01T00:00:00Z..2026-12-31T23:59:59Z)",
                      piped)


if __name__ == "__main__":
    unittest.main()
