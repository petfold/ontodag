"""Tests for the `od` command line (ontodag.__main__).

Covers the store-backend layer added for Swarm persistence:

  C1  spec routing      - swarm:NAME -> SwarmBackend, else FileBackend
  C2  spec normalize    - swarm specs kept verbatim, file paths absolutized
  C3  file round-trip   - a Session over a native file persists put/get
  C4  swarm round-trip  - a Session over a swarm backend persists across
                          reload, driven through dispatch() exactly as the
                          CLI does, using an in-memory RecordStore double so
                          no Bee node is required
  C5  swarm set/config  - `set store swarm:NAME` is stored verbatim and
                          resolves back to a SwarmBackend
  C6  swarm import      - import replaces store contents in place

The Bee HTTP path itself is not exercised here (no node); it is covered by
recordstore's own live-node suite. These tests validate the CLI wiring.
"""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

import ontodag.__main__ as cli
from recordstore import MemoryBytesStore, MemoryPointer, RecordStore


def _run(argv, session):
    """Dispatch a command, returning (exit_code, stdout_text)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.dispatch(argv, session)
    return code, buf.getvalue()


class TestBackendRouting(unittest.TestCase):
    def test_routing(self):  # C1
        self.assertIsInstance(cli._make_backend("/tmp/x.od"), cli.FileBackend)
        self.assertIsInstance(cli._make_backend("swarm:pets"), cli.SwarmBackend)

    def test_swarm_name_parsed(self):
        be = cli._make_backend("swarm:pets")
        self.assertEqual(be.name, "pets")
        self.assertEqual(be.describe(), "swarm:pets")

    def test_bad_swarm_names_rejected(self):
        for bad in ("swarm:", "swarm:a/b", "swarm:.."):
            with self.assertRaises(ValueError):
                cli._make_backend(bad)

    def test_normalize_spec(self):  # C2
        self.assertEqual(cli._normalize_spec("swarm:pets"), "swarm:pets")
        norm = cli._normalize_spec("relative/store.od")
        self.assertTrue(os.path.isabs(norm))


class TestFileBackend(unittest.TestCase):
    def test_file_round_trip(self):  # C3
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.od")
            session = cli.Session(path)
            self.assertEqual(_run(["put", "Animal"], session), (0, ""))
            _run(["put", "Dog", "Animal"], session)
            # A fresh session reads it back from disk.
            code, out = _run(["get", "Animal"], cli.Session(path))
            self.assertEqual((code, out), (0, "Dog\n"))


def _mem_swarm_session(shared):
    """A Session wired to an in-memory RecordStore that persists in `shared`
    (a dict holding the bytes store and pointer), mimicking a durable store
    across separate `odag` invocations within one test process."""
    factory = lambda: RecordStore(shared["bytes"], pointer=shared["pointer"])
    session = cli.Session.__new__(cli.Session)
    session.spec = "swarm:t"
    session.backend = cli.SwarmBackend("t", store_factory=factory)
    session.dag = session.backend.load()
    return session


class TestSwarmBackend(unittest.TestCase):
    def setUp(self):
        self.shared = {"bytes": MemoryBytesStore(), "pointer": MemoryPointer()}

    def test_swarm_round_trip_through_dispatch(self):  # C4
        s = _mem_swarm_session(self.shared)
        self.assertEqual(_run(["put", "Animal"], s), (0, ""))
        _run(["put", "Pet"], s)
        _run(["put", "Dog", "Animal", "Pet"], s)
        _run(["put", "Cat", "Animal", "Pet"], s)

        # Reload as a brand-new session over the same durable store.
        s2 = _mem_swarm_session(self.shared)
        code, out = _run(["get", "Animal", "Pet"], s2)
        self.assertEqual((code, out), (0, "Cat\nDog\n"))
        self.assertIn("swarm:t", _run(["set"], s2)[1])

    def test_swarm_remove_persists(self):
        s = _mem_swarm_session(self.shared)
        _run(["put", "Animal"], s)
        _run(["put", "Dog", "Animal"], s)
        _run(["remove", "Dog"], s)
        code, out = _run(["get", "Animal"], _mem_swarm_session(self.shared))
        self.assertEqual((code, out), (0, ""))

    def test_swarm_import_replaces_in_place(self):  # C6
        s = _mem_swarm_session(self.shared)
        _run(["put", "Old"], s)
        self.assertIsInstance(s.dag, __import__("ontodag").SwarmOntoDAG)

        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "new.od")
            other = cli.Session(src)
            _run(["put", "Fresh"], other)
            _run(["put", "Kid", "Fresh"], other)

            s.import_from(cli._load(src))
            # Same object kind (still a SwarmOntoDAG), new contents.
            self.assertIsInstance(s.dag, __import__("ontodag").SwarmOntoDAG)

        code, out = _run(["get", "Fresh"], _mem_swarm_session(self.shared))
        self.assertEqual((code, out), (0, "Kid\n"))
        self.assertEqual(_run(["get", "Old"], _mem_swarm_session(self.shared)),
                         (0, ""))


class TestSetCommand(unittest.TestCase):
    def _session(self, d):
        return cli.Session(os.path.join(d, "store.od"))

    def test_set_no_args_shows_all_settings(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = _run(["set"], self._session(d))
            self.assertEqual(code, 0)
            for key in ("store", "bee_api", "bee_batch"):
                self.assertIn(f"{key} = ", out)

    def test_set_key_without_value_displays_not_errors(self):
        with tempfile.TemporaryDirectory() as d:
            for key in ("store", "bee_api", "bee_batch"):
                code, out = _run(["set", key], self._session(d))
                self.assertEqual(code, 0, f"{key} should display, not error")
                self.assertTrue(out.startswith(f"{key} = "))

    def test_set_key_value_changes_it(self):
        with tempfile.TemporaryDirectory() as d:
            home = os.path.join(d, "home")
            old = os.environ.get("ONTODAG_HOME")
            os.environ["ONTODAG_HOME"] = home
            try:
                s = cli.Session(cli._resolve_store(None))
                self.assertEqual(_run(["set", "bee_api", "http://n:1633"], s),
                                 (0, ""))
                code, out = _run(["set", "bee_api"], s)
                self.assertEqual((code, out), (0, "bee_api = http://n:1633\n"))
            finally:
                if old is None:
                    del os.environ["ONTODAG_HOME"]
                else:
                    os.environ["ONTODAG_HOME"] = old

    def test_set_unknown_key_errors(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = _run(["set", "bogus"], self._session(d))
            self.assertEqual(code, 1)


class TestSwarmMissingDependency(unittest.TestCase):
    def test_missing_requests_gives_actionable_error(self):
        # BeeBytesStore imports `requests` in its constructor; if it's not
        # installed the swarm backend must fail with a clear message pointing
        # at the extra, not a raw ModuleNotFoundError.
        import builtins

        real_import = builtins.__import__

        def block(name, *args, **kwargs):
            if name == "requests" or name.startswith("requests."):
                raise ModuleNotFoundError("No module named 'requests'")
            return real_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as home:
            old_home = os.environ.get("ONTODAG_HOME")
            os.environ["ONTODAG_HOME"] = home
            builtins.__import__ = block
            try:
                with self.assertRaises(ValueError) as ctx:
                    cli.SwarmBackend("pets")._record_store()
            finally:
                builtins.__import__ = real_import
                if old_home is None:
                    del os.environ["ONTODAG_HOME"]
                else:
                    os.environ["ONTODAG_HOME"] = old_home

        msg = str(ctx.exception)
        self.assertIn("requests", msg)
        self.assertIn("swarm extra", msg)


class TestSwarmConfig(unittest.TestCase):
    def test_set_store_swarm_is_verbatim(self):  # C5
        with tempfile.TemporaryDirectory() as home:
            old = os.environ.get("ONTODAG_HOME")
            os.environ["ONTODAG_HOME"] = home
            try:
                cfg = {}
                cli._write_config({"store": cli._normalize_spec("swarm:pets")})
                self.assertEqual(cli._read_config()["store"], "swarm:pets")
                self.assertEqual(cli._resolve_store(None), "swarm:pets")
                self.assertIsInstance(
                    cli._make_backend(cli._resolve_store(None)),
                    cli.SwarmBackend,
                )
            finally:
                if old is None:
                    del os.environ["ONTODAG_HOME"]
                else:
                    os.environ["ONTODAG_HOME"] = old


if __name__ == "__main__":
    unittest.main()
