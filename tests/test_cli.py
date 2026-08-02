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
from contextlib import redirect_stderr, redirect_stdout

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
        self.assertIsInstance(s.dag, __import__("ontodag").EagerOntoDAG)

        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "new.od")
            other = cli.Session(src)
            _run(["put", "Fresh"], other)
            _run(["put", "Kid", "Fresh"], other)

            s.import_from(cli._load(src))
            # Same object kind (still a EagerOntoDAG), new contents.
            self.assertIsInstance(s.dag, __import__("ontodag").EagerOntoDAG)

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


class TestSwarmNodeDown(unittest.TestCase):
    """Opening a `swarm:NAME` store is network I/O, so it fails whenever the
    node is down — and it happens in main(), before dispatch()'s handler. The
    CLI contract (one line on stderr, non-zero exit) must hold there too, and
    the message must name the way out: start the node, or use the local
    default store. It must NOT quietly switch to the local store, which would
    let two stores diverge with no signal about which one is authoritative."""

    _ENV = ("ONTODAG_HOME", "BEE_API", "BEE_BATCH", "BEE_SIGNER")

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in self._ENV}
        os.environ["ONTODAG_HOME"] = self._home.name
        os.environ["BEE_API"] = "http://localhost:1633"
        os.environ.pop("BEE_SIGNER", None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._home.cleanup()

    @staticmethod
    def _wrapped(name, cause):
        """An OSError subclass named `name` carrying `cause` — the shape both
        HTTP clients produce: not a builtin ConnectionError, real refusal
        underneath."""
        exc = type(name, (OSError,), {})("Cannot connect to host localhost:1633")
        exc.__cause__ = cause
        return exc

    def _aiohttp_style_refusal(self):
        """What swarmfs's stamp selection actually raised in the wild."""
        return self._wrapped("ClientConnectorError",
                             ConnectionRefusedError(111, "Connect call failed"))

    def test_detects_unreachable_by_type_name(self):
        self.assertTrue(cli._is_unreachable(self._aiohttp_style_refusal()))
        self.assertTrue(cli._is_unreachable(
            ConnectionRefusedError(111, "Connection refused")))

    def test_detects_unreachable_through_the_cause_chain(self):
        # An unfamiliar wrapper type: only the chain gives it away.
        self.assertTrue(cli._is_unreachable(self._wrapped(
            "SomeFutureClientError",
            ConnectionRefusedError(111, "Connection refused"))))

    def test_node_answering_is_not_unreachable(self):
        # The node answering with a complaint is a different failure: no
        # "start your node" advice for it.
        self.assertFalse(cli._is_unreachable(
            OSError("no usable postage stamp on http://localhost:1633")))
        self.assertFalse(cli._is_unreachable(
            self._wrapped("BeeAPIError", ValueError("402 Payment Required"))))

    def test_unreachable_node_gives_actionable_error(self):
        backend = cli.SwarmBackend(
            "pets", store_factory=self._aiohttp_style_refusal_raiser())
        with self.assertRaises(ValueError) as ctx:
            backend.load()
        msg = str(ctx.exception)
        self.assertIn("cannot reach the Bee node at http://localhost:1633", msg)
        self.assertIn("swarm:pets", msg)
        self.assertIn("start your Bee node", msg)
        # ...and the local escape hatches, pointing at the real default path.
        self.assertIn(f"odag -f {cli._default_store_path()}", msg)
        self.assertIn(f"odag set store {cli._default_store_path()}", msg)

    def test_node_answering_with_an_error_uses_the_other_branch(self):
        def factory():
            raise OSError("no usable postage stamp on http://localhost:1633")

        with self.assertRaises(ValueError) as ctx:
            cli.SwarmBackend("pets", store_factory=factory).load()
        msg = str(ctx.exception)
        self.assertIn("cannot open swarm store 'pets'", msg)
        self.assertIn("no usable postage stamp", msg)
        self.assertNotIn("start your Bee node", msg)
        self.assertIn("odag set store", msg)  # fallback still offered

    def test_main_reports_one_line_not_a_traceback(self):
        from unittest import mock

        err = io.StringIO()
        boom = self._aiohttp_style_refusal()

        def raising_session(spec):
            raise cli._swarm_open_error("pets", "http://localhost:1633", boom)

        with mock.patch.object(cli, "Session", raising_session), \
             mock.patch.object(cli, "_resolve_store", lambda *a: "swarm:pets"), \
             redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["get", "Dog"])

        self.assertEqual(ctx.exception.code, 1)
        text = err.getvalue()
        self.assertTrue(text.startswith("odag: "), text)
        self.assertNotIn("Traceback", text)
        self.assertIn("start your Bee node", text)

    def test_failed_switch_leaves_the_session_on_its_old_store(self):
        from unittest import mock

        local = os.path.join(self._home.name, "local.od")
        session = cli.Session(local)
        _run(["put", "Animal"], session)

        # `set store swarm:down` with the node unreachable.
        boom = self._aiohttp_style_refusal()
        with mock.patch.object(cli, "_make_backend", lambda spec: cli.SwarmBackend(
                "down", store_factory=self._raiser(boom))):
            code, _ = _run(["set", "store", "swarm:down"], session)
        self.assertEqual(code, 1)

        # The session still serves the store it had — not a half-switched one.
        self.assertEqual(session.spec, local)
        self.assertEqual(_run(["get", "Animal"], session), (0, ""))
        self.assertEqual(_run(["list"], session), (0, "Animal\n"))
        # ...while the setting itself was saved, so starting the node and
        # re-running picks it up.
        self.assertEqual(cli._read_config()["store"], "swarm:down")

    def test_failed_switch_says_the_setting_was_saved(self):
        from unittest import mock

        session = cli.Session(os.path.join(self._home.name, "local.od"))
        err = io.StringIO()
        with mock.patch.object(cli, "_make_backend", lambda spec: cli.SwarmBackend(
                "down", store_factory=self._raiser(
                    self._aiohttp_style_refusal()))), redirect_stderr(err):
            code = cli.dispatch(["set", "store", "swarm:down"], session)
        self.assertEqual(code, 1)
        msg = err.getvalue()
        self.assertTrue(msg.startswith("odag: "), msg)
        self.assertIn("cannot reach the Bee node", msg)
        self.assertIn("setting was still saved as swarm:down", msg)

    @staticmethod
    def _raiser(exc):
        def factory():
            raise exc

        return factory

    def _aiohttp_style_refusal_raiser(self):
        exc = self._aiohttp_style_refusal()

        def factory():
            raise exc

        return factory


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


class TestGetOr(unittest.TestCase):
    def test_or_separates_disjuncts(self):
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "zoo.od"))
            for argv in (["put", "animal"], ["put", "machine"],
                         ["put", "pet"], ["put", "dog", "animal", "pet"],
                         ["put", "drone", "machine"]):
                self.assertEqual(_run(argv, session)[0], 0)
            code, out = _run(["get", "animal", "pet", "or", "machine"],
                             session)
            self.assertEqual((code, out), (0, "dog\ndrone\n"))
            # A trailing/leading `or` is a usage error, not a silent empty.
            code, _ = _run(["get", "animal", "or"], session)
            self.assertNotEqual(code, 0)


class TestEmptyQueryAndCount(unittest.TestCase):
    """`get` with no terms is everything, `list` is the same question under
    another name, and `count` answers it as a number."""

    def _session(self, home):
        session = cli.Session(os.path.join(home, "zoo.od"))
        for argv in (["put", "animal"], ["put", "machine"], ["put", "pet"],
                     ["put", "dog", "animal", "pet"],
                     ["put", "drone", "machine"]):
            self.assertEqual(_run(argv, session)[0], 0)
        return session

    ALL = "animal\ndog\ndrone\nmachine\npet\n"

    def test_get_with_no_terms_is_everything(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertEqual(_run(["get"], session), (0, self.ALL))

    def test_list_get_and_get_star_are_one_answer(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            answers = {_run(argv, session)[1]
                       for argv in (["get"], ["list"], ["get", "*"])}
            self.assertEqual(answers, {self.ALL})

    def test_dangling_or_is_still_an_error(self):
        # The empty query is a request; an empty *disjunct* is a typo, and
        # reading it as "everything" would silently widen a narrow query.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertNotEqual(_run(["get", "animal", "or"], session)[0], 0)

    def test_count_is_a_number_for_the_same_queries(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertEqual(_run(["count"], session), (0, "5\n"))
            self.assertEqual(_run(["count", "animal"], session), (0, "1\n"))
            self.assertEqual(_run(["count", "animal", "or", "machine"],
                                  session), (0, "2\n"))
            self.assertEqual(_run(["count", "nope"], session), (0, "0\n"))


class TestDisplayLimit(unittest.TestCase):
    """The cap is a display decision: a pipe is never capped, the query is
    always complete, and what was withheld is always said out loud."""

    def _session(self, home, n=10):
        session = cli.Session(os.path.join(home, "many.od"))
        for i in range(n):
            _run(["put", f"item{i:02d}"], session)
        return session

    def _run_err(self, argv, session):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.dispatch(argv, session)
        return code, out.getvalue(), err.getvalue()

    def setUp(self):
        cli._OVERRIDES.clear()
        self._env = os.environ.pop("ONTODAG_LIMIT", None)

    def tearDown(self):
        cli._OVERRIDES.clear()
        os.environ.pop("ONTODAG_LIMIT", None)
        if self._env is not None:
            os.environ["ONTODAG_LIMIT"] = self._env

    def test_a_pipe_is_never_capped(self):
        # StringIO is not a tty, which is exactly the pipe case.
        with tempfile.TemporaryDirectory() as home:
            code, out, err = self._run_err(["get"], self._session(home))
            self.assertEqual((code, len(out.splitlines()), err), (0, 10, ""))

    def test_explicit_limit_truncates_and_says_so(self):
        with tempfile.TemporaryDirectory() as home:
            code, out, err = self._run_err(["get", "-n", "3"],
                                           self._session(home))
            self.assertEqual(code, 0)
            # A deterministic prefix of the canonical sort, not an arbitrary
            # three: the same command twice gives the same three.
            self.assertEqual(out.splitlines(), ["item00", "item01", "item02"])
            self.assertIn("7 more not shown", err)

    def test_the_withheld_note_never_lands_in_the_data(self):
        with tempfile.TemporaryDirectory() as home:
            _, out, _ = self._run_err(["get", "-n", "3"], self._session(home))
            self.assertNotIn("not shown", out)

    def test_limit_zero_means_all(self):
        with tempfile.TemporaryDirectory() as home:
            code, out, err = self._run_err(["get", "-n", "0"],
                                           self._session(home))
            self.assertEqual((code, len(out.splitlines()), err), (0, 10, ""))

    def test_count_ignores_the_cap_entirely(self):
        # The point of `count` is to be the complete answer when printing
        # the results is what you are trying to avoid.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            os.environ["ONTODAG_LIMIT"] = "3"
            self.assertEqual(self._run_err(["count"], session)[1], "10\n")

    def test_env_sets_it_and_a_flag_beats_the_env(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            os.environ["ONTODAG_LIMIT"] = "2"
            self.assertEqual(len(self._run_err(["get"], session)[1]
                                 .splitlines()), 2)
            self.assertEqual(len(self._run_err(["get", "-n", "5"], session)[1]
                                 .splitlines()), 5)

    def test_a_bad_limit_is_refused_when_it_is_set_not_later(self):
        with tempfile.TemporaryDirectory() as home:
            code, _, err = self._run_err(["get", "-n", "banana"],
                                         self._session(home))
            self.assertEqual(code, 1)
            self.assertIn("limit", err)


class TestBelow(unittest.TestCase):
    def _session(self, home):
        session = cli.Session(os.path.join(home, "zoo.od"))
        for argv in (["put", "animal"], ["put", "dog", "animal"]):
            self.assertEqual(_run(argv, session)[0], 0)
        return session

    def test_true_false_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertEqual(_run(["below", "dog", "animal"], session),
                             (0, "true\n"))
            self.assertEqual(_run(["below", "animal", "dog"], session),
                             (1, "false\n"))
            # Unknown names are false, not errors: nothing on stderr.
            self.assertEqual(_run(["below", "typo", "animal"], session),
                             (1, "false\n"))

    def test_question_mark_alias(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertEqual(_run(["?", "dog", "animal"], session),
                             (0, "true\n"))

    def test_typed_values_from_names_alone(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            for argv in (["put", "dimension"],
                         ["put", "linear-dimension", "dimension"],
                         ["put", "weight", "linear-dimension"]):
                self.assertEqual(_run(argv, session)[0], 0)
            self.assertEqual(
                _run(["below", "weight(3kg)", "weight(..5kg)"], session),
                (0, "true\n"))
            self.assertEqual(
                _run(["below", "weight(9kg)", "weight(..5kg)"], session),
                (1, "false\n"))


class TestIndexCommand(unittest.TestCase):
    def test_publish_and_consume_cone_summaries(self):
        data_blobs = MemoryBytesStore()
        data_pointer = MemoryPointer()
        index_blobs = MemoryBytesStore()
        index_pointer = MemoryPointer()
        backend = cli.SwarmBackend(
            "pets",
            store_factory=lambda: RecordStore(data_blobs,
                                              pointer=data_pointer),
            index_store_factory=lambda: RecordStore(index_blobs,
                                                    pointer=index_pointer))
        session = cli.Session.__new__(cli.Session)
        session.spec, session.backend = "swarm:pets", backend
        session.dag = backend.load()
        for i in range(70):   # enough descendants to clear the threshold
            self.assertEqual(_run(["put", f"dog-{i}", "animal"]
                                  if i else ["put", "animal"], session)[0], 0)
        code, out = _run(["index"], session)
        self.assertEqual(code, 0, out)
        lines = dict(line.split(None, 1) for line in out.splitlines())
        self.assertEqual(lines["data"], session.dag.store.root)

        # The published pair actually serves a lazy reader.
        from ontodag.cones import ConeIndex
        from ontodag.lazy import LazyOntoDAG
        reader = LazyOntoDAG(
            RecordStore.at(lines["data"], data_blobs),
            cone_index=ConeIndex(RecordStore.at(lines["index"], index_blobs),
                                 lines["data"]))
        result = reader.get(["animal"])
        self.assertEqual(len(result), 69)
        self.assertLess(reader.fetches, 10)   # summary, not the cone

        # Indexing wrote nothing to the data store.
        self.assertEqual(lines["data"], session.dag.store.root)

    def test_file_backend_refuses(self):
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "zoo.od"))
            _run(["put", "animal"], session)
            code, _ = _run(["index"], session)
            self.assertNotEqual(code, 0)


class TestSwarmSignerWiring(unittest.TestCase):
    """The published-root pointer (roadmap item 2, DIMENSIONS-era queue):
    with a signer configured the backend builds its store through
    recordstore.swarm_store — blobs on Bee AND the latest root in a signed
    Swarm feed (SwarmFeedPointer), a followable address. Without one it
    stays BeeBytesStore + local FilePointer. Wiring only; the live feed
    cycle is tests/test_swarm_bee.py's (gated) job."""

    _ENV = ("ONTODAG_HOME", "BEE_API", "BEE_BATCH", "BEE_SIGNER")

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in self._ENV}
        os.environ["ONTODAG_HOME"] = self._home.name
        os.environ["BEE_API"] = "http://node:1633"
        os.environ["BEE_BATCH"] = "beef" * 16
        os.environ.pop("BEE_SIGNER", None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._home.cleanup()

    def test_signer_routes_to_swarm_store(self):
        from unittest import mock
        import recordstore

        os.environ["BEE_SIGNER"] = "0x" + "11" * 32
        sentinel = object()
        with mock.patch.object(recordstore, "swarm_store",
                               return_value=sentinel) as factory:
            store = cli.SwarmBackend("pets")._record_store()
        self.assertIs(store, sentinel)
        factory.assert_called_once_with(
            "pets", api_url="http://node:1633", stamp="beef" * 16,
            signer="0x" + "11" * 32)

    def test_signer_from_config_file(self):
        from unittest import mock
        import recordstore

        _, out = _run(["set", "bee_signer", "0x" + "22" * 32],
                      cli.Session(os.path.join(self._home.name, "ignore.od")))
        with mock.patch.object(recordstore, "swarm_store",
                               return_value=object()) as factory:
            cli.SwarmBackend("pets")._record_store()
        self.assertEqual(factory.call_args.kwargs["signer"], "0x" + "22" * 32)

    def test_without_signer_uses_local_file_pointer(self):
        from unittest import mock
        import recordstore

        with mock.patch.object(recordstore, "BeeBytesStore",
                               lambda api, batch: MemoryBytesStore()), \
             mock.patch.object(recordstore, "FilePointer") as pointer:
            cli.SwarmBackend("pets")._record_store()
        pointer.assert_called_once_with(
            cli.SwarmBackend("pets").pointer_path())

    def test_set_shows_bee_signer(self):
        session = cli.Session(os.path.join(self._home.name, "ignore.od"))
        code, out = _run(["set"], session)
        self.assertEqual(code, 0)
        self.assertIn("bee_signer = ", out)


if __name__ == "__main__":
    unittest.main()
