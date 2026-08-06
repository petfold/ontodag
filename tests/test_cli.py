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
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout

import ontodag.__main__ as cli
from ontodag.dag import Item, OntoDAG
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


class TestNativeStoreMetadata(unittest.TestCase):
    """The native format persists node metadata (`#:meta` lines).

    It did not, and dropped it on save with no diagnostic, so the format could
    not represent a DAG that the recordstore backend can: `_record_for` puts
    `meta` in the record, hence in the canonical root, while `_save_native`
    wrote names and edges only. A save+load therefore *changed the root*, and
    any consumer keeping data in metadata — ontodag-fs marks objects and
    carries display labels there — silently lost it through a file store.
    """

    def _roundtrip(self, dag, tmp):
        path = os.path.join(tmp, "store.od")
        cli._save_native(dag, path)
        return path, cli._load_native(path)

    def test_metadata_survives_a_round_trip(self):
        dag = OntoDAG()
        dag.put("dog", [])
        dag.put(Item("rex", metadata={"object": True, "label": "rex.txt",
                                      "count": 7}), ["dog"])
        with tempfile.TemporaryDirectory() as tmp:
            _path, back = self._roundtrip(dag, tmp)
        self.assertEqual(back.nodes["rex"].metadata,
                         {"object": True, "label": "rex.txt", "count": 7})
        self.assertEqual(back.nodes["dog"].metadata, {})   # absent stays absent

    def test_hostile_values_survive(self):
        """A label is an arbitrary string, and the format is line-oriented —
        so a newline in a value is the hazard that matters. JSON escapes it,
        which is why the annotation is one token rather than free text."""
        nasty = 'said "hi"\nnewline\ttab café \'quoted\' 100% a/b \\ #:meta'
        dag = OntoDAG()
        dag.put(Item("n", metadata={"label": nasty}), [])
        with tempfile.TemporaryDirectory() as tmp:
            path, back = self._roundtrip(dag, tmp)
            with open(path, encoding="utf-8") as fh:
                body = fh.read()
        self.assertEqual(back.nodes["n"].metadata["label"], nasty)
        # one physical line per record: the value's newline must not split it
        self.assertEqual(len([ln for ln in body.splitlines()
                              if ln.startswith(cli._META_LINE)]), 1)

    def test_the_file_stays_canonical(self):
        """Saving twice is byte-identical, so the store still diffs and merges
        — metadata keys are sorted for the same reason node names are."""
        dag = OntoDAG()
        dag.put(Item("n", metadata={"z": 1, "a": 2, "m": 3}), [])
        with tempfile.TemporaryDirectory() as tmp:
            one = os.path.join(tmp, "a.od")
            two = os.path.join(tmp, "b.od")
            cli._save_native(dag, one)
            cli._save_native(cli._load_native(one), two)
            with open(one, "rb") as fh, open(two, "rb") as gh:
                self.assertEqual(fh.read(), gh.read())

    def test_a_file_written_before_this_still_loads(self):
        """Backward compatibility: no `#:meta` lines is a valid store."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.od")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# ontodag store v1\ndog '*'\npuppy dog\n")
            dag = cli._load_native(path)
        self.assertEqual(sorted(n for n in dag.nodes if n != dag.root.name),
                         ["dog", "puppy"])
        self.assertEqual(dag.nodes["dog"].metadata, {})

    def test_a_reader_that_predates_metadata_sees_no_junk(self):
        """Forward compatibility, and the reason the annotation is a comment:
        every released reader skips `#` lines, so it reads a metadata-bearing
        file as edges only — not as nodes named after a JSON blob."""
        dag = OntoDAG()
        dag.put(Item("rex", metadata={"label": "rex.txt"}), [])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "store.od")
            cli._save_native(dag, path)
            with open(path, encoding="utf-8") as fh:
                lines = [ln.strip() for ln in fh
                         if ln.strip() and not ln.strip().startswith("#")]
        self.assertEqual(lines, ["rex '*'"])

    def test_a_malformed_annotation_is_an_error_not_a_shrug(self):
        """Ignoring an unreadable annotation would be the same silent loss this
        line type exists to end, so it fails loudly and names the line."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.od")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# ontodag store v1\n#:meta dog {not json}\ndog '*'\n")
            with self.assertRaises(ValueError) as caught:
                cli._load_native(path)
        self.assertIn(":2:", str(caught.exception))

    def test_the_canonical_root_survives_a_round_trip(self):
        """The property the whole change is for: routing a DAG through the text
        format no longer changes what it hashes to."""
        from ontodag.eager import EagerOntoDAG

        def commit(source):
            eager = EagerOntoDAG(RecordStore(MemoryBytesStore()))
            for node in source.topological_sort():
                if node.name == source.root.name:
                    continue
                parents = sorted(
                    p.name for p in node.parents
                    if source.nodes.get(p.name) is p
                    and p.name != source.root.name)
                eager.put(Item(node.name, metadata=dict(node.metadata)),
                          parents)
            return eager.commit()

        dag = OntoDAG()
        dag.put("dog", [])
        dag.put(Item("rex", metadata={"object": True, "label": "rex.txt"}),
                ["dog"])
        before = commit(dag)
        with tempfile.TemporaryDirectory() as tmp:
            _path, back = self._roundtrip(dag, tmp)
        self.assertEqual(before, commit(back))


def _mem_swarm_session(shared):
    """A Session wired to an in-memory RecordStore that persists in `shared`
    (a dict holding the bytes store and pointer), mimicking a durable store
    across separate `odag` invocations within one test process."""
    factory = lambda: RecordStore(shared["bytes"], pointer=shared["pointer"])
    session = cli.Session.__new__(cli.Session)
    session.spec = "swarm:t"
    session._backend = cli.SwarmBackend("t", store_factory=factory)
    session._dag = session._backend.load()
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

    def test_concurrent_remove_survivor_reaches_the_store(self):
        """The concurrent-delete gap, without swarmfs: session 2 hydrates
        while Dog exists, session 1 removes Dog (head moves), session 2
        saves an unrelated put — the union keeps Dog, and the committed
        root must too (see the local-first twin of this test for the
        full story)."""
        s1 = _mem_swarm_session(self.shared)
        _run(["put", "Animal"], s1)
        _run(["put", "Dog", "Animal"], s1)
        s2 = _mem_swarm_session(self.shared)      # hydrates holding Dog
        _run(["remove", "Dog"], s1)               # head moves: Dog deleted
        _run(["put", "Cat", "Animal"], s2)        # merge on save
        code, out = _run(["get", "Animal"], _mem_swarm_session(self.shared))
        self.assertEqual((code, out), (0, "Cat\nDog\n"))

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
    """Settings resolve by flag > environment > config file > default, so these
    tests have to own the environment: with `BEE_API` exported — which is what
    the User Guide's setup step tells you to do — an assertion about what the
    *config file* holds is testing the wrong layer, and the suite went red for
    anyone who had followed the instructions. The neighbouring swarm classes
    already save and restore these; this one did not."""

    _ENV = ("BEE_API", "BEE_BATCH", "BEE_SIGNER", "ONTODAG_STORE",
            "ONTODAG_LIMIT", "ONTODAG_SURFACE")

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self._ENV}
        for key in self._ENV:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

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
    def test_missing_swarmfs_gives_actionable_error(self):
        # local_first_store imports swarmfs's localstore machinery; if it's
        # not installed the swarm backend must fail with a clear message
        # pointing at the extra, not a raw ModuleNotFoundError.
        import builtins

        real_import = builtins.__import__

        def block(name, *args, **kwargs):
            if name == "swarmfs" or name.startswith("swarmfs."):
                raise ModuleNotFoundError("No module named 'swarmfs'",
                                          name="swarmfs")
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
        self.assertIn("swarmfs", msg)
        self.assertIn("swarm extra", msg)


class TestSwarmNodeDown(unittest.TestCase):
    """Opening a `swarm:NAME` store is network I/O, so it fails whenever the
    node is down. The store opens lazily — on the first command that touches
    it, inside dispatch()'s handler — so the CLI contract (one line on
    stderr, non-zero exit) holds, the message names the way out (start the
    node, or use the local default store), and commands that never touch the
    store (`help`, `set`) keep working with the node down. It must NOT
    quietly switch to the local store, which would let two stores diverge
    with no signal about which one is authoritative."""

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

        with mock.patch.object(cli, "_make_backend", lambda spec: cli.SwarmBackend(
                "pets", store_factory=self._raiser(boom))), \
             mock.patch.object(cli, "_resolve_store", lambda *a: "swarm:pets"), \
             redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["get", "Dog"])

        self.assertEqual(ctx.exception.code, 1)
        text = err.getvalue()
        self.assertTrue(text.startswith("odag: "), text)
        self.assertNotIn("Traceback", text)
        self.assertIn("start your Bee node", text)

    def test_help_and_set_work_with_the_node_down(self):
        # The reason the store opens lazily: `odag help` is what a user
        # types to find the way out, and `odag set store <local>` IS the
        # way out — neither may fail because the node is unreachable.
        from unittest import mock

        boom = self._aiohttp_style_refusal()
        with mock.patch.object(cli, "_make_backend", lambda spec: cli.SwarmBackend(
                "pets", store_factory=self._raiser(boom))):
            session = cli.Session("swarm:pets")

            code, out = _run(["help"], session)
            self.assertEqual(code, 0)
            self.assertIn("Documentation:", out)

            code, out = _run(["set"], session)          # show settings
            self.assertEqual(code, 0)
            self.assertIn("swarm:pets", out)            # described, unopened

            code, _ = _run(["set", "limit", "10"], session)
            self.assertEqual(code, 0)

            # A command that DOES touch the store still gets the contract:
            err = io.StringIO()
            with redirect_stderr(err):
                code, _ = _run(["get", "Dog"], session)
            self.assertEqual(code, 1)
            self.assertIn("start your Bee node", err.getvalue())

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
        session.spec, session._backend = "swarm:pets", backend
        session._dag = backend.load()
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
    """The swarm: backend is local-first (recordstore 0.19): commits land
    in a store directory and sync in the background. With a signer the
    head is additionally published to a Swarm feed — only after network
    confirmation (publish_pointer=SwarmFeedPointer). Without one, nothing
    is publishable and publish_pointer stays None. Wiring only; the live
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

    def test_signer_routes_to_feed_publication(self):
        from unittest import mock
        import recordstore

        os.environ["BEE_SIGNER"] = "0x" + "11" * 32
        sentinel, feed = object(), object()
        with mock.patch.object(recordstore, "local_first_store",
                               return_value=sentinel) as factory, \
             mock.patch.object(recordstore, "SwarmFeedPointer",
                               return_value=feed) as pointer:
            store = cli.SwarmBackend("pets")._record_store()
        self.assertIs(store, sentinel)
        pointer.assert_called_once_with(
            "http://node:1633", "pets", signer="0x" + "11" * 32,
            postage_batch_id="beef" * 16)
        factory.assert_called_once_with(
            cli.SwarmBackend("pets").store_dir(), "http://node:1633",
            stamp="beef" * 16, publish_pointer=feed)

    def test_signer_from_config_file(self):
        from unittest import mock
        import recordstore

        _, out = _run(["set", "bee_signer", "0x" + "22" * 32],
                      cli.Session(os.path.join(self._home.name, "ignore.od")))
        with mock.patch.object(recordstore, "local_first_store",
                               return_value=object()), \
             mock.patch.object(recordstore, "SwarmFeedPointer",
                               return_value=object()) as pointer:
            cli.SwarmBackend("pets")._record_store()
        self.assertEqual(pointer.call_args.kwargs["signer"], "0x" + "22" * 32)

    def test_without_signer_no_publication(self):
        from unittest import mock
        import recordstore

        with mock.patch.object(recordstore, "local_first_store",
                               return_value=object()) as factory:
            cli.SwarmBackend("pets")._record_store()
        self.assertIsNone(factory.call_args.kwargs["publish_pointer"])
        self.assertEqual(factory.call_args.args[0],
                         cli.SwarmBackend("pets").store_dir())

    def test_legacy_root_migrates_into_head(self):
        from unittest import mock
        import recordstore

        backend = cli.SwarmBackend("pets")
        os.makedirs(os.path.dirname(backend.pointer_path()), exist_ok=True)
        with open(backend.pointer_path(), "w") as f:
            f.write("ab" * 32)
        with mock.patch.object(recordstore, "local_first_store",
                               return_value=object()):
            backend._record_store()
        with open(os.path.join(backend.store_dir(), "HEAD")) as f:
            self.assertEqual(f.read(), "ab" * 32)

    def test_head_not_overwritten_by_stale_legacy_root(self):
        from unittest import mock
        import recordstore

        backend = cli.SwarmBackend("pets")
        os.makedirs(backend.store_dir(), exist_ok=True)
        with open(os.path.join(backend.store_dir(), "HEAD"), "w") as f:
            f.write("cd" * 32)
        os.makedirs(os.path.dirname(backend.pointer_path()), exist_ok=True)
        with open(backend.pointer_path(), "w") as f:
            f.write("ab" * 32)
        with mock.patch.object(recordstore, "local_first_store",
                               return_value=object()):
            backend._record_store()
        with open(os.path.join(backend.store_dir(), "HEAD")) as f:
            self.assertEqual(f.read(), "cd" * 32)

    def test_set_shows_bee_signer(self):
        session = cli.Session(os.path.join(self._home.name, "ignore.od"))
        code, out = _run(["set"], session)
        self.assertEqual(code, 0)
        self.assertIn("bee_signer = ", out)


if __name__ == "__main__":
    unittest.main()


class TestLocalRecordStore(unittest.TestCase):
    """`rs:PATH` — the rung between a text file and Swarm.

    Its reason to exist is that canonical roots, snapshots and certificates
    used to require a Bee node, a funded wallet and a postage batch before
    you could see any of them. Everything asserted here runs on a directory.
    """

    def _run(self, argv, session):
        return _run(argv, session)

    def test_routing_and_normalization(self):
        backend = cli._make_backend("rs:/tmp/x")
        self.assertIsInstance(backend, cli.LocalRecordBackend)
        # The path is absolutised inside the prefix, so a spec saved to
        # config means the same thing from any working directory.
        self.assertTrue(
            cli._normalize_spec("rs:./rel").startswith("rs:/"))
        self.assertEqual(cli._normalize_spec("swarm:x"), "swarm:x")

    def test_it_persists_and_has_a_real_root(self):
        with tempfile.TemporaryDirectory() as home:
            spec = f"rs:{os.path.join(home, 'store')}"
            session = cli.Session(spec)
            for argv in (["put", "Travel"], ["put", "Japan", "Travel"],
                         ["put", "doc", "Japan"]):
                self.assertEqual(_run(argv, session)[0], 0)
            root = session.dag.store.root
            self.assertTrue(root, "a record store must produce a root")

            reopened = cli.Session(spec)          # a fresh process would
            self.assertEqual(_run(["get", "Travel"], reopened)[1],
                             "Japan\ndoc\n")
            self.assertEqual(reopened.dag.store.root, root)

    def test_the_root_is_canonical_across_build_orders(self):
        # The property the whole content-addressed story rests on, available
        # here with no node: equal knowledge, equal name.
        def build(path, order):
            session = cli.Session(f"rs:{path}")
            for argv in order:
                _run(argv, session)
            return session.dag.store.root

        with tempfile.TemporaryDirectory() as home:
            first = build(os.path.join(home, "a"),
                          [["put", "Travel"], ["put", "Japan", "Travel"],
                           ["put", "doc", "Japan"]])
            second = build(os.path.join(home, "b"),
                           [["put", "Travel"], ["put", "Japan", "Travel"],
                            ["put", "other"], ["remove", "other"],
                            ["put", "doc", "Japan"]])
            self.assertEqual(first, second)

    def test_index_accepts_it_where_a_text_store_is_refused(self):
        with tempfile.TemporaryDirectory() as home:
            record = cli.Session(f"rs:{os.path.join(home, 's')}")
            _run(["put", "a"], record)
            self.assertEqual(_run(["index"], record)[0], 0)

            plain = cli.Session(os.path.join(home, "s.od"))
            _run(["put", "a"], plain)
            code, _ = _run(["index"], plain)
            self.assertEqual(code, 1)

    def test_describe_round_trips_through_set(self):
        with tempfile.TemporaryDirectory() as home:
            path = os.path.join(home, "store")
            session = cli.Session(f"rs:{path}")
            self.assertEqual(session.describe(), f"rs:{path}")


class TestSwarmDoctor(unittest.TestCase):
    """`odag swarm` walks the setup in dependency order and stops at the
    first failure. The failures are the product here, not the successes."""

    def _diagnose(self, session):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.dispatch(["swarm"], session)
        return code, out.getvalue()

    def test_it_reports_a_missing_extra_before_touching_the_network(self):
        with tempfile.TemporaryDirectory() as home, \
             mock.patch.object(cli.importlib.util, "find_spec",
                               return_value=None):
            code, text = self._diagnose(cli.Session(os.path.join(home, "s.od")))
        self.assertEqual(code, 1)
        self.assertIn('pip install "ontodag[swarm]"', text)
        # ...and does not pretend to know anything about the node.
        self.assertNotIn("node reachable", text)

    def test_an_unreachable_node_names_the_next_step(self):
        with tempfile.TemporaryDirectory() as home, \
             mock.patch.object(cli.importlib.util, "find_spec",
                               return_value=object()), \
             mock.patch.object(cli, "_bee_get",
                               side_effect=OSError("refused")):
            code, text = self._diagnose(cli.Session(os.path.join(home, "s.od")))
        self.assertEqual(code, 1)
        self.assertIn("nothing answering", text)
        self.assertIn("odag set bee_api", text)

    def test_a_healthy_node_with_no_batch_says_how_to_buy_one(self):
        replies = {
            "/": {}, "/health": {"status": "ok"},
            "/chainstate": {"block": 42},
            "/wallet": {"bzzBalance": "10", "nativeTokenBalance": "10"},
            "/stamps": {"stamps": [{"usable": False}]},
        }
        with tempfile.TemporaryDirectory() as home, \
             mock.patch.object(cli.importlib.util, "find_spec",
                               return_value=object()), \
             mock.patch.object(cli, "_bee_get",
                               side_effect=lambda api, path, **kw: replies[path]):
            code, text = self._diagnose(cli.Session(os.path.join(home, "s.od")))
        self.assertEqual(code, 1)
        self.assertIn("none usable", text)
        self.assertIn("/stamps/", text)      # the command to run
        self.assertIn("~70s", text)          # and the wait nobody expects

    def test_a_fully_ready_node_exits_zero(self):
        replies = {
            "/": {}, "/health": {"status": "ok"},
            "/chainstate": {"block": 42},
            "/wallet": {"bzzBalance": "10", "nativeTokenBalance": "10"},
            "/stamps": {"stamps": [{"usable": True, "batchID": "ab" * 16,
                                    "batchTTL": 86400 * 3}]},
        }
        with tempfile.TemporaryDirectory() as home, \
             mock.patch.object(cli.importlib.util, "find_spec",
                               return_value=object()), \
             mock.patch.object(cli, "_bee_get",
                               side_effect=lambda api, path, **kw: replies[path]):
            code, text = self._diagnose(cli.Session(os.path.join(home, "s.od")))
        self.assertEqual(code, 0)
        self.assertIn("TTL 3.0 days", text)
        self.assertIn("odag set store swarm:", text)

    def test_the_unready_path_offers_the_local_record_store(self):
        # The adoption point: someone who cannot run a node today should
        # still be told how to get the properties Swarm is *for*.
        with tempfile.TemporaryDirectory() as home, \
             mock.patch.object(cli.importlib.util, "find_spec",
                               return_value=None):
            _, text = self._diagnose(cli.Session(os.path.join(home, "s.od")))
        self.assertIn("rs:", text)

    def test_a_healthy_node_is_reported_reachable(self):
        """The bug this guards: reachability was asked of `/`, which Bee serves
        as `text/plain` ("Ethereum Swarm Bee"), and the probe parsed every
        response as JSON. So a healthy node raised JSONDecodeError and was
        reported as "nothing answering" — and because the walk stops at the
        first failure, that ended the diagnosis and told the user to start a
        node that was already running.

        It needs a real socket: any test that stubs `_bee_get` shares the
        parsing assumption that was wrong, and sees nothing.
        """
        import http.server
        import threading

        class Bee(http.server.BaseHTTPRequestHandler):
            def do_GET(self):                       # noqa: N802
                if self.path == "/":                # plain text, like Bee
                    body, kind = b"Ethereum Swarm Bee\n", "text/plain"
                elif self.path == "/health":
                    body, kind = (b'{"status":"ok","version":"2.8.1"}',
                                  "application/json")
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):           # keep the test quiet
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Bee)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            api = f"http://127.0.0.1:{server.server_port}"
            # The walk stops at the first failure, and its first check is that
            # the swarm extra is installed — which it is not in a plain test
            # environment. Satisfy that one so this test is about the probe it
            # names, rather than about how the suite happens to be installed.
            with mock.patch.object(cli.importlib.util, "find_spec",
                                   return_value=object()):
                checks = dict((label, ok)
                              for ok, label, _ in cli._swarm_checks(api))
        finally:
            server.shutdown()
            server.server_close()
        self.assertTrue(checks.get("swarm extra installed"), checks)
        self.assertTrue(checks.get("node reachable"), checks)
        self.assertTrue(checks.get("node healthy"), checks)


class TestConfigSecrecy(unittest.TestCase):
    """`bee_signer` is a private key that can publish to your feed, so the two
    places it could leak are closed: the file it is written to, and the command
    that reads settings back."""

    _ENV = ("BEE_API", "BEE_BATCH", "BEE_SIGNER", "ONTODAG_HOME")
    KEY = "1" * 60 + "abcd"

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in self._ENV}
        for key in self._ENV:
            os.environ.pop(key, None)
        os.environ["ONTODAG_HOME"] = self._home.name

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._home.cleanup()

    def _session(self):
        return cli.Session(cli._resolve_store(None))

    def test_the_config_file_is_owner_only(self):
        session = self._session()
        self.assertEqual(_run(["set", "bee_signer", self.KEY], session),
                         (0, ""))
        mode = os.stat(cli._config_path()).st_mode & 0o777
        self.assertEqual(mode, 0o600, f"config is {oct(mode)}, not 0o600")

    def test_a_config_written_before_this_gets_repaired(self):
        """The case that matters: the key is already on disk, world-readable,
        written by an older version. The next write must tighten it."""
        os.makedirs(self._home.name, exist_ok=True)
        path = cli._config_path()
        with open(path, "w") as fh:
            fh.write("bee_api = http://n:1633\n")
        os.chmod(path, 0o644)
        _run(["set", "bee_signer", self.KEY], self._session())
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_showing_all_settings_does_not_print_the_key(self):
        session = self._session()
        _run(["set", "bee_signer", self.KEY], session)
        _code, out = _run(["set"], session)
        self.assertNotIn(self.KEY, out)
        self.assertIn("bee_signer = <hidden, ends abcd>", out)

    def test_showing_the_key_alone_does_not_print_it_either(self):
        session = self._session()
        _run(["set", "bee_signer", self.KEY], session)
        _code, out = _run(["set", "bee_signer"], session)
        self.assertNotIn(self.KEY, out)
        self.assertIn("<hidden, ends abcd>", out)

    def test_an_unset_signer_reads_as_empty_not_as_hidden(self):
        _code, out = _run(["set", "bee_signer"], self._session())
        self.assertEqual(out, "bee_signer = \n")

    def test_a_signer_from_the_environment_is_masked_too(self):
        os.environ["BEE_SIGNER"] = self.KEY
        _code, out = _run(["set"], self._session())
        self.assertNotIn(self.KEY, out)

    def test_the_stored_value_is_still_the_real_key(self):
        """Masking is display-only: the config remains the place to read it."""
        _run(["set", "bee_signer", self.KEY], self._session())
        self.assertEqual(cli._read_config()["bee_signer"], self.KEY)
        self.assertEqual(cli._configured("bee_signer"), self.KEY)

    def test_non_secret_settings_are_still_shown_in_full(self):
        session = self._session()
        _run(["set", "bee_batch", "c0ffee"], session)
        _code, out = _run(["set", "bee_batch"], session)
        self.assertEqual(out, "bee_batch = c0ffee\n")


class TestGenerateSigner(unittest.TestCase):
    """`odag set bee_signer generate` — because the alternative was asking
    people to type a shell incantation that produces 32 random bytes, which is
    hostile and easy to get subtly wrong in a way that only fails later."""

    _ENV = ("BEE_API", "BEE_BATCH", "BEE_SIGNER", "ONTODAG_HOME")

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in self._ENV}
        for key in self._ENV:
            os.environ.pop(key, None)
        os.environ["ONTODAG_HOME"] = self._home.name

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._home.cleanup()

    def _session(self):
        return cli.Session(cli._resolve_store(None))

    def _set(self, *argv):
        """Run `set`, returning (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.dispatch(["set", *argv], self._session())
        return code, out.getvalue(), err.getvalue()

    def test_it_generates_a_usable_key(self):
        code, out, _err = self._set("bee_signer", "generate")
        self.assertEqual((code, out), (0, ""))      # silent on stdout
        key = cli._read_config()["bee_signer"]
        self.assertEqual(len(key), 64)
        self.assertTrue(cli._looks_like_a_signer(key))

    def test_the_generated_key_parses_with_the_real_signer_library(self):
        """The shape check above is the contract; this is the cross-check
        against the library that will actually consume it. It needs the `swarm`
        extra, so it skips on a plain test install rather than making the whole
        suite depend on an optional dependency."""
        try:
            from bee.swarm.keys import PrivateKey
        except ImportError:
            self.skipTest("needs the swarm extra (bee) for the real parser")
        self._set("bee_signer", "generate")
        PrivateKey.from_hex(cli._read_config()["bee_signer"])

    def test_two_generations_differ(self):
        self._set("bee_signer", "generate")
        first = cli._read_config()["bee_signer"]
        self._set("bee_signer", "generate", "--force")
        self.assertNotEqual(cli._read_config()["bee_signer"], first)

    def test_the_key_is_never_printed(self):
        _code, out, err = self._set("bee_signer", "generate")
        key = cli._read_config()["bee_signer"]
        self.assertNotIn(key, out)
        self.assertNotIn(key, err)
        self.assertIn(f"ends {key[-4:]}", err)      # only the tail, to identify

    def test_it_says_where_the_key_went_and_to_back_it_up(self):
        """A secret the user will never be shown again is the one case where
        silence is unhelpful."""
        _code, _out, err = self._set("bee_signer", "generate")
        self.assertIn(cli._config_path(), err)
        self.assertIn("back it up", err)

    def test_the_file_is_owner_only(self):
        self._set("bee_signer", "generate")
        self.assertEqual(os.stat(cli._config_path()).st_mode & 0o777, 0o600)

    def test_replacing_a_key_is_refused_by_default(self):
        self._set("bee_signer", "generate")
        original = cli._read_config()["bee_signer"]
        code, _out, err = self._set("bee_signer", "generate")
        self.assertEqual(code, 1)
        self.assertIn("--force", err)
        self.assertIn("strand", err)
        # and it really did not touch the stored key
        self.assertEqual(cli._read_config()["bee_signer"], original)

    def test_force_replaces_it(self):
        self._set("bee_signer", "generate")
        original = cli._read_config()["bee_signer"]
        code, _out, _err = self._set("bee_signer", "generate", "--force")
        self.assertEqual(code, 0)
        self.assertNotEqual(cli._read_config()["bee_signer"], original)

    def test_it_warns_when_the_environment_would_win(self):
        os.environ["BEE_SIGNER"] = "ab" * 32
        _code, _out, err = self._set("bee_signer", "generate")
        self.assertIn("BEE_SIGNER", err)
        self.assertIn("outranks", err)

    def test_a_malformed_key_is_refused_at_set_time(self):
        """The failure a real user hit: a stray character on a paste gives 65
        characters, and without this it is accepted here and blows up later at
        the first command that opens the store."""
        code, _out, err = self._set("bee_signer", "a" * 65)
        self.assertEqual(code, 1)
        self.assertIn("64 characters", err)
        self.assertIn("generate", err)              # points at the easy way
        self.assertNotIn("bee_signer", cli._read_config())

    def test_a_real_key_is_still_accepted_either_spelling(self):
        for value in ("cd" * 32, "0x" + "cd" * 32):
            code, _out, _err = self._set("bee_signer", value, "--force")
            self.assertEqual(code, 0, value)
            self.assertEqual(cli._read_config()["bee_signer"], value)


class TestSwarmBackendLocalFirst(unittest.TestCase):
    """End to end, offline: the swarm: backend is local-first — a commit
    succeeds with the node unreachable (durable in the store directory,
    synced by a later run), and reopening resumes at the committed head."""

    def setUp(self):
        try:
            import swarmfs.localstore  # noqa: F401
        except ImportError:
            self.skipTest("swarmfs not installed")
        self._home = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k)
                       for k in ("ONTODAG_HOME", "BEE_API", "BEE_BATCH")}
        os.environ["ONTODAG_HOME"] = self._home.name
        os.environ["BEE_API"] = "http://127.0.0.1:9"  # nothing listens here
        os.environ["BEE_BATCH"] = "beef" * 16
        self._timeout = cli._SYNC_TIMEOUT
        cli._SYNC_TIMEOUT = 0.2

    def tearDown(self):
        cli._SYNC_TIMEOUT = self._timeout
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._home.cleanup()

    def test_commit_offline_then_reopen(self):
        import io
        from contextlib import redirect_stderr

        backend = cli.SwarmBackend("pets")
        dag = backend.load()                 # transient: lock released here
        dag.put("cat", [])
        err = io.StringIO()
        with redirect_stderr(err):
            backend.save(dag)                # node down: still succeeds
        self.assertIn("committed locally", err.getvalue())

        dag2 = cli.SwarmBackend("pets").load()   # reopen at the same head
        self.assertIn("cat", dag2.nodes)

    def test_no_lock_held_between_windows(self):
        """The transient-window contract: after load()/save() return, the
        store's writer lock is free — a second opener never blocks."""
        b1 = cli.SwarmBackend("pets")
        dag = b1.load()
        # while dag serves from memory, another process-alike opens freely
        store = cli.SwarmBackend("pets")._record_store()
        try:
            self.assertIsNotNone(store)
        finally:
            store.close()
        backendless = cli.SwarmBackend("pets").load()
        self.assertEqual(set(backendless.nodes), set(dag.nodes))

    def test_concurrent_windows_converge_by_merge_not_lww(self):
        """Multi-writer convergence is the CRDT merge, not locking: two
        sessions hydrate the same store, edit the SAME node under
        different parents, and save in turn — the second save merges the
        moved head, so the parents union instead of last-write-wins."""
        b1, b2 = cli.SwarmBackend("pets"), cli.SwarmBackend("pets")
        dag1 = b1.load()
        dag2 = b2.load()                    # concurrent session, no lock held

        dag1.put("p1", [])
        dag1.put("child", ["p1"])
        import io
        from contextlib import redirect_stderr
        with redirect_stderr(io.StringIO()):
            b1.save(dag1)

        dag2.put("p2", [])
        dag2.put("child", ["p2"])           # same node, different parent
        with redirect_stderr(io.StringIO()):
            b2.save(dag2)                   # head moved -> CRDT merge

        dag3 = cli.SwarmBackend("pets").load()
        parents = {p.name for p in dag3.nodes["child"].parents}
        self.assertEqual(parents, {"p1", "p2"})

    def test_concurrent_remove_loses_and_the_survivor_reaches_the_store(self):
        """A peer deletes a record another session still holds; union says
        the held copy survives (the grow-only stance, same as
        remove-loses-to-readd) — and it must survive IN THE STORE, not
        just in memory. commit() used to diff against the session's base
        lineage, stage nothing for the held-but-unchanged record, and so
        silently keep the head's deletion in the committed root: the
        store said remove-WINS while memory said remove-LOSES."""
        import io
        from contextlib import redirect_stderr

        b1, b2 = cli.SwarmBackend("pets"), cli.SwarmBackend("pets")
        seed = b1.load()
        seed.put("p1", [])
        seed.put("child", ["p1"])
        with redirect_stderr(io.StringIO()):
            b1.save(seed)

        dag1 = b1.load()
        dag2 = b2.load()                    # still holds child
        dag1.remove("child")
        with redirect_stderr(io.StringIO()):
            b1.save(dag1)                   # head moves: child deleted

        dag2.put("p2", [])                  # unrelated concurrent edit
        with redirect_stderr(io.StringIO()):
            b2.save(dag2)                   # merge: child must be re-staged

        dag3 = cli.SwarmBackend("pets").load()
        self.assertIn("p2", dag3.nodes)
        self.assertIn("child", dag3.nodes)


class TestExcerpt(unittest.TestCase):
    """`excerpt` is the materialized cut: the query's answer, with the edges
    among the answers, in a file you can import back.

    Every assertion here is against the *query answer*, never against an exit
    code — the web session learned that a 200 with the wrong picture in it
    reads as a pass.
    """

    def _session(self, home):
        session = cli.Session(os.path.join(home, "trips.od"))
        for argv in (["put", "Travel"], ["put", "Japan"],
                     ["put", "Flight", "Travel"],
                     ["put", "Hotel", "Travel"],
                     ["put", "JAL", "Flight", "Japan"],
                     ["put", "JAL-cheap", "JAL"],
                     ["put", "Ryokan", "Hotel", "Japan"]):
            self.assertEqual(_run(argv, session)[0], 0)
        return session

    def _excerpt(self, home, session, *categories):
        path = os.path.join(home, "cut.od")
        self.assertEqual(_run(["excerpt", path] + list(categories), session),
                         (0, ""))
        return cli._load(path)

    def _answer(self, session, *categories):
        return {item.name for item in cli._query(list(categories), session.dag)}

    def test_excerpt_is_exactly_the_answer(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            cut = self._excerpt(home, session, "Travel", "Japan")
            names = set(cut.nodes) - {cut.root.name}
            self.assertEqual(names, self._answer(session, "Travel", "Japan"))
            self.assertEqual(names, {"JAL", "JAL-cheap", "Ryokan"})

    def test_the_answers_keep_their_own_edges(self):
        # Cones are downward-closed under intersection, so JAL-cheap must
        # arrive still under JAL, not flattened to the root.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            cut = self._excerpt(home, session, "Travel", "Japan")
            self.assertEqual(
                {p.name for p in cut.nodes["JAL-cheap"].parents}, {"JAL"})

    def test_query_terms_are_not_in_the_excerpt(self):
        # The whole point of "keep it importable": a constraint is not a fact.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            cut = self._excerpt(home, session, "Travel", "Japan")
            self.assertNotIn("Travel", cut.nodes)
            self.assertNotIn("Japan", cut.nodes)

    def test_it_round_trips_through_import(self):
        # Top answers hang under `*`, so the importing store can see them
        # with the empty query — otherwise they would load as orphans.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            path = os.path.join(home, "cut.od")
            self.assertEqual(_run(["excerpt", path, "Travel", "Japan"],
                                  session)[0], 0)
            fresh = cli.Session(os.path.join(home, "fresh.od"))
            self.assertEqual(_run(["import", path], fresh)[0], 0)
            self.assertEqual(_run(["list"], fresh),
                             (0, "JAL\nJAL-cheap\nRyokan\n"))
            self.assertEqual(_run(["get", "JAL"], fresh), (0, "JAL-cheap\n"))

    def test_union_queries_excerpt_too(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            cut = self._excerpt(home, session, "Hotel", "or", "Flight")
            self.assertEqual(set(cut.nodes) - {cut.root.name},
                             self._answer(session, "Hotel", "or", "Flight"))

    def test_the_empty_query_excerpts_the_whole_store(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            cut = self._excerpt(home, session)
            self.assertEqual(set(cut.nodes) - {cut.root.name},
                             set(session.dag.nodes) - {session.dag.root.name})
            self.assertEqual({p.name for p in cut.nodes["Flight"].parents},
                             {"Travel"})

    def test_an_empty_answer_is_an_empty_excerpt(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            cut = self._excerpt(home, session, "Flight", "Hotel")
            self.assertEqual(set(cut.nodes), {cut.root.name})

    def test_the_store_is_untouched(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            before = _run(["show"], session)
            self._excerpt(home, session, "Japan")
            self.assertEqual(_run(["show"], session), before)

    def test_a_dangling_or_is_still_an_error(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            path = os.path.join(home, "cut.od")
            self.assertNotEqual(_run(["excerpt", path, "Japan", "or"],
                                     session)[0], 0)

    def test_a_virtual_term_excerpts_its_answer(self):
        # The bug this guards against is the one the web *picture* had: a
        # parametric term is not a node, so anything that intersects by name
        # silently drops it. The answer here contains the real stored value
        # node; the virtual constraint itself is still not filed.
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "boxes.od"))
            for argv in (["prelude"], ["put", "box", "weight(3kg)"],
                         ["put", "lid", "box"]):
                self.assertEqual(_run(argv, session)[0], 0)
            cut = self._excerpt(home, session, "weight(..5kg)")
            names = set(cut.nodes) - {cut.root.name}
            self.assertEqual(names, self._answer(session, "weight(..5kg)"))
            self.assertIn("box", names)
            self.assertNotIn("weight(..5kg)", names)

    def test_the_empty_excerpt_is_byte_identical_to_export(self):
        # Pins the doc claim in §5.4, and with it the property that makes the
        # widened query safe: an unconstrained excerpt is the whole store.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            cut, exported = (os.path.join(home, n) for n in ("cut.od", "exp.od"))
            self.assertEqual(_run(["excerpt", cut], session)[0], 0)
            self.assertEqual(_run(["export", exported], session)[0], 0)
            with open(cut, encoding="utf-8") as a, \
                    open(exported, encoding="utf-8") as b:
                self.assertEqual(a.read(), b.read())


class TestVisualizeScoping(unittest.TestCase):
    """`visualize CAT...` draws the query, not the store — and draws the
    query *terms* too, which is exactly where it differs from `excerpt`.

    Graphviz is never invoked here: the shaping is what can be wrong, and
    asserting on it keeps the test free of the `viz` extra and the `dot`
    binary.
    """

    def _session(self, home):
        session = cli.Session(os.path.join(home, "trips.od"))
        for argv in (["put", "Travel"], ["put", "Japan"],
                     ["put", "Flight", "Travel"],
                     ["put", "Hotel", "Travel"],
                     ["put", "JAL", "Flight", "Japan"],
                     ["put", "Ryokan", "Hotel", "Japan"]):
            self.assertEqual(_run(argv, session)[0], 0)
        return session

    def _drawn(self, session, *categories):
        """The DAG `visualize` handed the renderer."""
        drawn = []

        class FakeVisualizer:
            def __init__(self, format=None):
                pass

            def visualize(self, dag, filename=None):
                drawn.append(dag)

        with mock.patch("ontodag.viz.OntoDAGVisualizer", FakeVisualizer):
            code, _ = _run(["visualize"] + list(categories), session)
        self.assertEqual(code, 0)
        self.assertEqual(len(drawn), 1)
        return drawn[0]

    def test_no_categories_draws_the_store_itself(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertIs(self._drawn(session), session.dag)

    def test_a_query_draws_its_answer_under_its_terms(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            picture = self._drawn(session, "Travel", "Japan")
            self.assertEqual(set(picture.nodes) - {picture.root.name},
                             {"Travel", "Japan", "JAL", "Ryokan"})
            for term in ("Travel", "Japan"):
                self.assertEqual(
                    {n.name for n in picture.nodes[term].neighbors},
                    {"JAL", "Ryokan"})

    def test_the_picture_is_a_view_not_the_store(self):
        # It invents nodes; nothing about that may reach the real DAG.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            before = _run(["show"], session)
            self._drawn(session, "weight(..5kg)")
            self.assertEqual(_run(["show"], session), before)

    def test_a_union_draws_two_branches(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            picture = self._drawn(session, "Flight", "or", "Hotel")
            self.assertEqual({n.name for n in picture.nodes["Flight"].neighbors},
                             {"JAL"})
            self.assertEqual({n.name for n in picture.nodes["Hotel"].neighbors},
                             {"Ryokan"})

    def test_a_virtual_term_is_drawn_even_with_no_such_node(self):
        # The bug that made every query picture untrustworthy: a parametric
        # term has no node, so a name-based intersection dropped it.
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "boxes.od"))
            for argv in (["prelude"], ["put", "box", "weight(3kg)"]):
                self.assertEqual(_run(argv, session)[0], 0)
            picture = self._drawn(session, "weight(..5kg)")
            self.assertIn("weight(..5kg)", picture.nodes)
            self.assertIn("box", picture.nodes)
            self.assertNotIn("weight(..5kg)", session.dag.nodes)

    def test_a_dangling_or_is_still_an_error(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            with mock.patch("ontodag.viz.OntoDAGVisualizer"):
                self.assertNotEqual(
                    _run(["visualize", "Japan", "or"], session)[0], 0)

    def test_it_names_the_file_after_the_store_when_told_nothing(self):
        # Regression: `visualize` read `session.path`, which stopped existing
        # when `rs:` stores landed, so bare `odag visualize` raised
        # AttributeError for four releases. No test had ever omitted --out.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            written = []

            class FakeVisualizer:
                def __init__(self, format=None):
                    pass

                def visualize(self, dag, filename=None):
                    written.append(filename)

            with mock.patch("ontodag.viz.OntoDAGVisualizer", FakeVisualizer):
                self.assertEqual(_run(["visualize"], session)[0], 0)
            self.assertEqual(written, [os.path.join(home, "trips")])

    def test_every_backend_spelling_yields_a_name(self):
        self.assertEqual(cli._image_base("/store/trips.od"), "/store/trips")
        self.assertEqual(cli._image_base("swarm:pets"), "pets")
        self.assertEqual(cli._image_base("rs:/store/pets/"), "/store/pets")
