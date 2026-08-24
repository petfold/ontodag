"""REST-level tests for the Flask web app (`ontodag.web.app`), with the
parametric-dimensions flow exercised over HTTP. Skips cleanly when the web
extras are not installed (the app imports flask and dot2tex at module
level) — and, per test, when Graphviz's `dot` binary is missing, which is
its own gate: the `viz` extra installs the Python wrapper, the binary comes
from the OS and is a separate download on Windows."""

import shutil

import pytest

pytest.importorskip("flask")
pytest.importorskip("dot2tex")

requires_dot = pytest.mark.skipif(
    shutil.which("dot") is None,
    reason="needs the Graphviz `dot` binary on PATH")

from ontodag.web.app import app  # noqa: E402


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        assert client.post("/dag").status_code == 201  # fresh session DAG
        yield client


def put(client, sub, supers=None):
    return client.post("/dag/node", json={
        "subcategories": [sub],
        "super_categories": supers or [],
    })


def query_names(client, cats):
    response = client.get("/dag/query", query_string={"cat": cats})
    assert response.status_code == 200, response.get_json()
    return {node["name"] for node in response.get_json()["nodes"]}


class TestPlainRest:
    def test_put_and_query(self, client):
        assert put(client, "animal").status_code == 201
        assert put(client, "dog", ["animal"]).status_code == 201
        assert "dog" in query_names(client, "animal")

    def test_unknown_term_fails_closed(self, client):
        put(client, "animal")
        assert query_names(client, "no-such-thing") == set()

    def test_query_log_counts_category_sets(self, client):
        from ontodag.web.app import QUERY_LOG
        QUERY_LOG.clear()
        put(client, "animal")
        put(client, "pet")
        query_names(client, "animal,pet")
        query_names(client, "pet,animal")     # same set, same key
        query_names(client, "animal|pet")     # two disjuncts, two keys
        stats = client.get("/dag/stats/queries").get_json()["queries"]
        counts = {row["cat"]: row["count"] for row in stats}
        assert counts == {"animal,pet": 2, "animal": 1, "pet": 1}

    def test_below_endpoint(self, client):
        put(client, "animal")
        put(client, "dog", ["animal"])
        response = client.get("/dag/below",
                              query_string={"sub": "dog", "sup": "animal"})
        assert (response.status_code, response.get_json()) == \
            (200, {"below": True})
        response = client.get("/dag/below",
                              query_string={"sub": "animal", "sup": "dog"})
        assert response.get_json() == {"below": False}
        assert client.get("/dag/below",
                          query_string={"sub": "dog"}).status_code == 400

    def test_pipe_is_union(self, client):
        put(client, "animal")
        put(client, "machine")
        put(client, "pet")
        put(client, "dog", ["animal", "pet"])
        put(client, "drone", ["machine"])
        # cat=animal,pet|machine  ->  (animal AND pet) OR machine
        assert query_names(client, "animal,pet|machine") == {"dog", "drone"}

    def test_missing_super_is_client_error(self, client):
        response = put(client, "dog", ["no-such-parent"])
        assert response.status_code == 400


class TestDimensionsOverRest:
    def _declare(self, client):
        put(client, "dimension")
        put(client, "linear-dimension", ["dimension"])
        put(client, "weight", ["linear-dimension"])

    def test_courier_flow(self, client):
        self._declare(client)
        put(client, "parcel", ["weight(3kg)"])
        put(client, "heavy-parcel", ["weight(9kg)"])
        result = query_names(client, "weight(..5kg)")  # a VIRTUAL term
        assert "parcel" in result
        assert "heavy-parcel" not in result

    def test_sugar_is_one_identity(self, client):
        self._declare(client)
        put(client, "a", ["weight(3kg)"])
        put(client, "b", ["weight(3000g)"])
        assert {"a", "b"} <= query_names(client, "weight(3.0kg)")

    def test_malformed_parameter_is_client_error(self, client):
        self._declare(client)
        response = client.get("/dag/query",
                              query_string={"cat": "weight(3zz)"})
        assert response.status_code == 400

    def test_disjoint_parents_are_client_error(self, client):
        self._declare(client)
        response = client.post("/dag/node", json={
            "subcategories": ["x"],
            "super_categories": ["weight(..2kg)", "weight(3kg..)"],
        })
        assert response.status_code == 400
        assert "disjoint" in response.get_json()["error"]

    def test_remove_accepts_sugar(self, client):
        self._declare(client)
        put(client, "parcel", ["weight(3kg)"])
        response = client.delete("/dag/node",
                                 json={"subcategories": ["weight(3kg)"]})
        assert response.status_code == 200
        assert query_names(client, "weight(..5kg)") == set()
        # parcel contracted onto the head, still present in the graph
        assert "parcel" in query_names(client, "weight")


@requires_dot
class TestPicturesAndExports:
    """The rendering endpoints, which had never been covered here — and were
    broken in two independent ways when this suite was written (2026-08-02).

    Both bugs needed a *rendering* call to show up, which is why the REST
    tests above missed them: session state was only initialized by the two
    page routes, so an API-only client got a KeyError traceback; and
    canonical dimension names were used as DOT node identifiers, where
    graphviz's quoting splits them at the `:` it reads as a port separator.
    """

    def _declare(self, client):
        put(client, "dimension")
        put(client, "calendar-dimension", ["dimension"])
        put(client, "linear-dimension", ["dimension"])
        put(client, "time", ["calendar-dimension"])
        put(client, "weight", ["linear-dimension"])

    def test_api_only_session_can_render(self, client):
        # This client never requested "/" — the REST API is a surface in its
        # own right and initializes whatever it needs.
        put(client, "animal")
        response = client.get("/dag/image")
        assert response.status_code == 200
        assert response.data[:4] == b"\x89PNG"

    def test_parametric_names_render(self, client):
        self._declare(client)
        put(client, "doc", ["time(2026-08-15)", "weight(3kg)"])
        for endpoint in ("/dag/image", "/dag/export/dot", "/dag/export/tex"):
            response = client.get(endpoint)
            assert response.status_code == 200, \
                f"{endpoint}: {response.get_json()}"

    def test_empty_cat_draws_everything(self, client):
        # The empty query is everything, so its picture is everything's —
        # the UI hits this whenever the query box is submitted blank.
        put(client, "animal")
        blank = client.get("/dag/query/image", query_string={"cat": ""})
        assert blank.status_code == 200
        assert blank.data == client.get("/dag/image").data

    def test_query_image_of_a_virtual_term(self, client):
        self._declare(client)
        put(client, "parcel", ["weight(3kg)"])
        response = client.get("/dag/query/image",
                              query_string={"cat": "weight(..5kg)"})
        assert response.status_code == 200
        assert response.data[:4] == b"\x89PNG"

    def test_a_name_that_needs_url_encoding_survives(self, client):
        # `+` decodes to a space unless encoded; the page's JS now encodes
        # each term (`,` and `|` stay separators). Flask's test client
        # encodes query_string for us, so this pins the server side.
        put(client, "C++ notes")
        put(client, "chapter1", ["C++ notes"])
        assert query_names(client, "C++ notes") == {"chapter1"}


class TestAMissingRendererIsAnInstruction:
    """`pip install "ontodag[viz]"` satisfies the import; the drawing is done
    by the `dot` program, which comes from the OS. So the picture routes fail
    at render time, and used to answer 500 with a graphviz traceback in the
    log. 501 with the sentence that fixes it is the honest answer — and it is
    the likeliest Windows failure, where the binary is a separate download."""

    def test_the_picture_routes_say_what_to_install(self, client, monkeypatch):
        from ontodag._extras import MissingExtra
        from ontodag.viz import OntoDAGVisualizer

        def refuse(*_args, **_kwargs):
            raise MissingExtra("rendering needs the Graphviz system program "
                               "`dot`, which pip does not install")

        monkeypatch.setattr(OntoDAGVisualizer, "generate_image", refuse)
        monkeypatch.setattr(OntoDAGVisualizer, "generate_svg", refuse)
        put(client, "animal")
        for url in ("/dag/image", "/dag/query/image?cat=animal", "/dag/picture"):
            response = client.get(url)
            assert response.status_code == 501, f"{url}: {response.status_code}"
            assert "dot" in response.get_json()["error"]


@requires_dot
class TestQueryPictureAgreesWithTheAnswer:
    """The query image is built from `get()`, not from a name-intersection.

    Found by clicking through the UI (2026-08-02): the old `get_by_dag`
    route matched query terms by NAME, so a *virtual* parametric term —
    one with no node of its own, which is the entire point of dimensions —
    silently dropped out of the query. `weight(..5kg)` drew an empty graph,
    and `Japan,weight(..5kg)` drew all of Japan: a picture that contradicted
    the result list printed beside it. A picture that disagrees with the
    answer is worse than no picture, so these tests compare the two.
    """

    def _fixture(self, client):
        put(client, "dimension")
        put(client, "calendar-dimension", ["dimension"])
        put(client, "linear-dimension", ["dimension"])
        put(client, "time", ["calendar-dimension"])
        put(client, "weight", ["linear-dimension"])
        put(client, "Flight")
        put(client, "Hotel")
        put(client, "Japan")
        put(client, "jp-flight.pdf",
            ["Flight", "Japan", "weight(3kg)", "time(2026-08-15)"])
        put(client, "kyoto-hotel.pdf", ["Hotel", "Japan", "time(2026-08-16)"])

    def _pictured(self, client, cat):
        # The endpoint stashes the DAG it drew; that is what the PNG shows.
        assert client.get("/dag/query/image",
                          query_string={"cat": cat}).status_code == 200
        from flask import session as flask_session
        with client.session_transaction() as sess:
            drawn = sess["query_result_dag"]
        return {name for name in drawn.nodes if name != "*"}

    def test_a_virtual_term_appears_with_its_matches(self, client):
        self._fixture(client)
        drawn = self._pictured(client, "weight(..5kg)")
        assert "weight(..5kg)" in drawn      # the term, though no node exists
        assert "jp-flight.pdf" in drawn
        assert "kyoto-hotel.pdf" not in drawn

    def test_a_parametric_constraint_is_not_silently_dropped(self, client):
        # The bad case: not an empty picture but a WRONG one — the old code
        # drew every Japan item, weight constraint and all.
        self._fixture(client)
        drawn = self._pictured(client, "Japan,weight(..5kg)")
        answer = query_names(client, "Japan,weight(..5kg)")
        assert answer == {"jp-flight.pdf"}
        assert "kyoto-hotel.pdf" not in drawn
        assert answer <= drawn

    def test_union_is_drawn_as_two_branches(self, client):
        # The image endpoint split on "," only, so `Japan|Hotel` became one
        # node with that literal name and matched nothing.
        self._fixture(client)
        drawn = self._pictured(client, "Flight,Japan|Hotel")
        assert not any("|" in name for name in drawn)
        assert {"Flight", "Japan", "Hotel"} <= drawn
        assert query_names(client, "Flight,Japan|Hotel") <= drawn

    def test_the_picture_contains_the_answer_for_plain_queries_too(self, client):
        self._fixture(client)
        assert query_names(client, "Japan") <= self._pictured(client, "Japan")

    def test_an_unknown_term_draws_itself_and_nothing_else(self, client):
        self._fixture(client)
        assert self._pictured(client, "no-such-thing") == {"no-such-thing"}


def projects(client):
    """active/archive with a shared item, the lifecycle shape."""
    for name, supers in (("active", []), ("archive", []),
                         ("A", ["active"]), ("B", ["active"]),
                         ("C", ["A", "B"]), ("a1", ["A"])):
        assert put(client, name, supers).status_code == 201


class TestQueryExportIsTheExcerptNotThePicture:
    """A download must not contain the query terms.

    These routes served `session["query_result_dag"]`, which the image route
    sets to the *picture* — terms invented as nodes so the constraint is
    visible. Downloading that and importing it filed the question as knowledge,
    and which file you got depended on which endpoint you hit last.
    """

    def _classes(self, client, query_string=None):
        response = client.get("/dag/query/export/omn",
                              query_string=query_string or {})
        assert response.status_code == 200, response.data[:200]
        return {line.split(":", 1)[1].strip().lstrip(":")
                for line in response.data.decode().splitlines()
                if line.startswith("Class:")}

    @requires_dot
    def test_the_terms_are_not_in_the_download(self, client):
        projects(client)
        # Look at the picture first — that is what used to poison the export.
        assert client.get("/dag/query/image",
                          query_string={"cat": "A,B"}).status_code == 200
        classes = self._classes(client)
        assert "C" in classes
        assert "A" not in classes and "B" not in classes

    def test_an_explicit_query_needs_no_prior_request(self, client):
        projects(client)
        assert self._classes(client, {"cat": "A,B"}) == {"*", "C"}

    def test_context_brings_the_classification(self, client):
        projects(client)
        classes = self._classes(client, {"cat": "A,B", "context": "1"})
        assert {"A", "B", "C", "active"} <= classes

    @requires_dot
    def test_the_dot_export_matches_too(self, client):
        projects(client)
        client.get("/dag/query/image", query_string={"cat": "A,B"})
        body = client.get("/dag/query/export/dot").data.decode()
        assert '"C' in body or "C:" in body       # the answer is drawn
        assert "label=A" not in body and 'label="A"' not in body

    def test_a_union_query_exports_both_branches(self, client):
        # A|B is (below A) OR (below B) — the answers, not the terms.
        projects(client)
        assert self._classes(client, {"cat": "A|B"}) == {"*", "a1", "C"}


class TestMoveOverRest:
    """PATCH /dag/node — the verb POST and DELETE could not express."""

    def test_it_moves_the_item_and_reports_the_contested_set(self, client):
        projects(client)
        response = client.patch("/dag/node", json={
            "subcategories": ["A"], "to": ["archive"], "from": ["active"]})
        assert response.status_code == 200, response.get_json()
        body = response.get_json()
        assert body["retracted"] == [["active", "A"]]
        assert body["contested"] == ["C"]        # also under a still-active B
        assert query_names(client, "archive") == {"A", "a1", "C"}
        assert query_names(client, "active") == {"B", "C"}

    def test_the_contents_travel_with_it(self, client):
        projects(client)
        client.patch("/dag/node", json={"subcategories": ["A"],
                                        "to": ["archive"]})
        assert "a1" in query_names(client, "archive")

    def test_to_alone_replaces_every_classification(self, client):
        projects(client)
        client.patch("/dag/node", json={"subcategories": ["C"],
                                        "to": ["archive"]})
        assert "C" not in query_names(client, "A")

    def test_from_alone_unfiles_without_orphaning(self, client):
        projects(client)
        assert client.patch("/dag/node", json={"subcategories": ["A"],
                                              "from": ["active"]}).status_code == 200
        assert "A" not in query_names(client, "active")
        assert "A" in query_names(client, "")     # still visible: top-level

    def test_bad_requests_are_client_errors(self, client):
        projects(client)
        for payload in ({"subcategories": ["C"]},                  # nothing to do
                        {"to": ["archive"]},                        # no items
                        {"subcategories": ["C"], "to": ["nope"]},   # unknown
                        {"subcategories": ["nope"], "to": ["archive"]},
                        {"subcategories": ["active"], "to": ["C"]}):  # cycle
            response = client.patch("/dag/node", json=payload)
            assert response.status_code == 400, payload
            assert "error" in response.get_json()

    def test_a_refused_move_changes_nothing(self, client):
        projects(client)
        before = query_names(client, "active")
        client.patch("/dag/node", json={"subcategories": ["A"],
                                        "to": ["nope"], "from": ["active"]})
        assert query_names(client, "active") == before


class TestConeRemovalOverRest:
    def test_the_preview_says_what_would_go_and_what_would_stay(self, client):
        projects(client)
        body = client.get("/dag/removal",
                          query_string={"name": "A", "cone": "1"}).get_json()
        assert body == {"cone": ["A", "C", "a1"], "deleted": ["A", "a1"],
                        "kept": ["C"]}
        assert query_names(client, "active") == {"A", "B", "C", "a1"}  # untouched

    def test_the_delete_spares_what_hangs_elsewhere(self, client):
        projects(client)
        response = client.delete("/dag/node?cone=1",
                                 json={"subcategories": ["A"]})
        assert response.status_code == 200
        body = response.get_json()
        assert body["deleted"] == ["A", "a1"]
        assert body["kept"] == ["C"]
        assert query_names(client, "B") == {"C"}

    def test_without_the_flag_it_still_contracts(self, client):
        projects(client)
        assert client.delete("/dag/node",
                             json={"subcategories": ["A"]}).status_code == 200
        assert "C" in query_names(client, "active")     # contraction kept it
        assert "a1" in query_names(client, "active")

    def test_the_preview_refuses_nonsense(self, client):
        projects(client)
        assert client.get("/dag/removal").status_code == 400
        assert client.get("/dag/removal",
                          query_string={"name": "nope", "cone": "1"}
                          ).status_code == 400


class TestTheClassicPageIsWiredUp:
    """Static checks on the classic page, because the failure mode of a button
    is a typo: an id the script looks up but the markup never defines, or a URL
    the app does not route. Both give a control that silently does nothing,
    which no status-code test can see.

    (Clicking through in a real browser is still the only way to see layout and
    rendering — that pass found three bugs in 2026-08-02 that HTTP checks had
    called green. These checks are the cheap floor, not a substitute.)
    """

    def _page(self, client):
        response = client.get("/classic")
        assert response.status_code == 200
        return response.data.decode()

    def _script(self, page):
        import re
        return re.search(r"<script>(.*)</script>", page, re.S).group(1)

    def test_every_id_the_script_uses_exists_in_the_markup(self, client):
        import re
        page = self._page(client)
        defined = set(re.findall(r'id="([^"]+)"', page))
        used = set(re.findall(r'getElementById\("([^"]+)"\)',
                              self._script(page)))
        assert used <= defined, f"referenced but never defined: {used - defined}"

    def test_every_url_the_page_calls_is_a_real_route(self, client):
        import re
        script = self._script(self._page(client))
        urls = set(re.findall(r'(?:fetch|href = )\s*\(?\s*"(/[^"?]*)', script))
        # Paths built by helper functions, which the regex cannot see.
        urls |= {"/dag/query/export", "/dag/query/export/omn",
                 "/dag/query/export/dot", "/dag/query/export/tex"}
        routes = {rule.rule for rule in app.url_map.iter_rules()}
        assert urls <= routes, f"no such route(s): {sorted(urls - routes)}"

    def test_the_new_controls_are_present(self, client):
        page = self._page(client)
        for control in ("move-item-form", "move-to", "move-from",
                        "delete-cone-button", "export-with-context", "notice"):
            assert f'id="{control}"' in page, control

    def test_the_move_and_cone_handlers_use_the_right_methods(self, client):
        script = self._script(self._page(client))
        assert '"PATCH"' in script                      # move
        assert "/dag/removal?cone=1&" in script         # preview before deleting
        assert '"/dag/node?cone=1"' in script           # then the deletion
        # The destructive one asks first; the contracting one never did.
        assert "window.confirm" in script

    def test_the_script_is_valid_javascript(self, client):
        import shutil
        import subprocess
        import tempfile
        node = shutil.which("node") or shutil.which("nodejs")
        if node is None:
            pytest.skip("node not installed")
        script = self._script(self._page(client))
        with tempfile.NamedTemporaryFile("w", suffix=".js") as handle:
            handle.write(script)
            handle.flush()
            result = subprocess.run([node, "--check", handle.name],
                                    capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def console(client, line, cat=None):
    response = client.post("/dag/console",
                           query_string={"cat": cat} if cat else {},
                           json={"line": line})
    assert response.status_code == 200, response.data
    return response.get_json()


class TestConsole:
    """The command language, over HTTP.

    The console is the same interpreter the CLI uses, so these tests are not
    about what the commands *do* — that is `tests/test_cli.py`'s job, against
    the same `dispatch`. They are about the seam: that both streams come back,
    that the exit code survives, and that the allow-list holds.
    """

    def test_a_command_runs_and_its_output_comes_back(self, client):
        put(client, "animal")
        put(client, "dog", ["animal"])
        answer = console(client, "get animal")
        assert answer["code"] == 0
        assert answer["out"] == "dog\n"
        assert answer["err"] == ""

    def test_the_exit_code_survives(self, client):
        put(client, "animal")
        put(client, "dog", ["animal"])
        # `below` is grep-shaped: 0 for true, 1 for false, and the word is
        # the answer rather than an error.
        assert console(client, "below dog animal")["code"] == 0
        assert console(client, "below animal dog")["code"] == 1
        assert console(client, "below animal dog")["out"] == "false\n"

    def test_errors_arrive_on_their_own_stream(self, client):
        answer = console(client, "put orphan nosuchparent")
        assert answer["code"] == 1
        assert answer["out"] == ""
        assert "unknown super-category: 'nosuchparent'" in answer["err"]

    def test_argparse_messages_are_captured_too(self, client):
        # Without the stream plumbing in dispatch() these went to the
        # server's own stderr, so a usage error looked like silence.
        answer = console(client, "get --nonsense")
        assert answer["code"] == 2
        assert "unrecognized arguments" in answer["err"]

    def test_a_mutation_is_visible_to_the_rest_of_the_app(self, client):
        console(client, "put dog")
        assert query_names(client, "dog") == set()      # exists, nothing under it
        # The empty query is everything, and everything is now `dog`.
        assert console(client, "count")["out"] == "1\n"

    def test_names_are_rendered_for_a_person(self, client):
        # The console claims to be a terminal, so it inherits the CLI's
        # terminal behaviour: readable spellings rather than canonical bytes.
        client.post("/dag/prelude")
        console(client, "put shipment 'weight(500g)'")
        answer = console(client, "canon 'weight(500g)'")
        assert answer["out"].strip() == "weight(1/2kg)"
        assert "weight(500g)" in console(client, "get weight")["out"]

    def test_a_blank_line_does_nothing(self, client):
        answer = console(client, "   ")
        assert (answer["code"], answer["out"], answer["err"]) == (0, "", "")

    def test_unbalanced_quotes_are_a_client_error_not_a_crash(self, client):
        answer = console(client, "get 'unclosed")
        assert answer["code"] == 1
        assert "odag:" in answer["err"]


class TestConsoleAllowList:
    """What a page may NOT run.

    Each of these takes a filesystem path and would run as the server user,
    which on a public demo is the whole ball game. The refusals are checked
    by *effect* where an effect is observable, not just by message.
    """

    def test_path_taking_commands_are_refused(self, client):
        for line in ("import /etc/passwd", "export /tmp/x.owl",
                     "merge /tmp/x.od", "excerpt /tmp/x.od",
                     "diff /tmp/other.od", "visualize", "index", "swarm"):
            answer = console(client, line)
            assert answer["code"] == 2, line
            assert answer["err"].startswith("odag: `"), line

    def test_output_redirection_is_refused_even_on_an_allowed_command(
            self, client, tmp_path):
        # `get` is allowed, and `-o` writes wherever it is pointed — so the
        # check has to be on the line, not on the command.
        target = tmp_path / "written"
        for flag in (f"-o {target}", f"--output {target}", f"--output={target}"):
            answer = console(client, f"get {flag}")
            assert answer["code"] == 2, flag
        assert not target.exists()

    def test_set_store_cannot_repoint_the_app(self, client):
        answer = console(client, "set store /tmp/somewhere.od")
        assert answer["code"] == 2
        assert "launch argument" in answer["err"]

    def test_history_explains_itself_rather_than_traceback(self, client):
        for line in ("history", "undo", "redo", "status"):
            answer = console(client, line)
            assert answer["code"] == 2, line
            assert "keeps no versions" in answer["err"], line

    def test_an_unknown_command_says_how_many_there_are(self, client):
        answer = console(client, "frobnicate")
        assert answer["code"] == 2
        assert "unknown command" in answer["err"]

    def test_help_says_which_commands_this_surface_runs(self, client):
        answer = console(client, "help")
        assert answer["code"] == 0
        assert "in the browser:" in answer["err"]
        assert " put " in answer["err"]


class TestBrowse:
    """The refinements are the point: categories held by SOME but not all of
    the answer. One held by all narrows nothing; one held by none is a dead
    end. Every choice offered therefore leads somewhere different."""

    def _shop(self, client):
        for name, parents in [("Travel", []), ("Japan", []),
                              ("Flight", ["Travel"]), ("Hotel", ["Travel"]),
                              ("JAL7", ["Flight", "Japan"]),
                              ("NH209", ["Flight", "Japan"]),
                              ("BA1", ["Flight"]),
                              ("Ryokan", ["Hotel", "Japan"])]:
            assert put(client, name, parents).status_code == 201

    def _browse(self, client, cat=None):
        response = client.get("/dag/browse",
                              query_string={"cat": cat} if cat else {})
        assert response.status_code == 200
        return response.get_json()

    def test_the_empty_query_is_everything(self, client):
        self._shop(client)
        assert self._browse(client)["count"] == 8

    def test_refinements_split_the_answer(self, client):
        self._shop(client)
        refine = {r["name"]: r["matching"] for r in
                  self._browse(client, "Japan")["refine"]}
        assert refine == {"Flight": 2, "Hotel": 1}

    def test_a_category_every_answer_has_is_not_offered(self, client):
        self._shop(client)
        # All three Flights are under Travel, so clicking Travel would return
        # the same answer — it is not a choice.
        refine = {r["name"] for r in self._browse(client, "Flight")["refine"]}
        assert "Travel" not in refine
        assert refine == {"Japan"}

    def test_the_matching_count_is_what_the_click_returns(self, client):
        self._shop(client)
        for entry in self._browse(client, "Japan")["refine"]:
            narrowed = self._browse(client, f"Japan,{entry['name']}")
            assert narrowed["count"] == entry["matching"], entry

    def test_a_fully_determined_answer_offers_nothing(self, client):
        self._shop(client)
        assert self._browse(client, "Japan,Flight")["refine"] == []

    def test_declarations_are_grouped_apart_from_things(self, client):
        client.post("/dag/prelude")
        self._shop(client)
        here = {h["name"]: h["vocab"] for h in self._browse(client)["here"]}
        assert here["weight"] is True and here["dimension"] is True
        assert here["JAL7"] is False and here["Travel"] is False

    def test_something_filed_at_a_typed_value_is_not_vocabulary(self, client):
        # It hangs under `time(...)`, which hangs under `time`, which is a
        # declaration — so the whole cone of `dimension` is the wrong set.
        client.post("/dag/prelude")
        put(client, "JAL7", ["time(2026-08-15)"])
        here = {h["name"]: h["vocab"] for h in self._browse(client)["here"]}
        assert here["JAL7"] is False
        assert here["time"] is True

    def test_a_union_narrows_every_branch(self, client):
        self._shop(client)
        both = self._browse(client, "Hotel|Flight")
        assert both["count"] == 4                      # BA1 JAL7 NH209 Ryokan
        narrowed = self._browse(client, "Hotel,Japan|Flight,Japan")
        assert narrowed["count"] == 3                  # BA1 drops out


class TestNodeDetail:
    def test_it_answers_with_both_spellings(self, client):
        client.post("/dag/prelude")
        put(client, "JAL7", ["time(2026-08-15)"])
        detail = client.get("/dag/node/JAL7").get_json()
        assert detail["name"] == "JAL7"
        above = {p["display"]: p["name"] for p in detail["above"]}
        # The page shows what a person typed; the store keeps the range.
        assert "time(2026-08-15)" in above
        assert above["time(2026-08-15)"].startswith("time(2026-08-15T00:00:00Z")

    def test_a_missing_name_is_a_404_not_a_traceback(self, client):
        assert client.get("/dag/node/nosuch").status_code == 404

    def test_a_name_that_needs_encoding_survives(self, client):
        put(client, "C++ & notes")
        detail = client.get("/dag/node/C%2B%2B%20%26%20notes").get_json()
        assert detail["name"] == "C++ & notes"


@requires_dot
class TestPictureIsClickable:
    """A picture nobody can click is a screenshot. Graphviz writes viz.py's
    synthetic ids into the SVG, which is what lets a click become a name
    without a graph library — so the id map is load-bearing, not decoration."""

    def test_every_drawn_node_can_be_traced_back_to_its_name(self, client):
        import re
        put(client, "animal")
        put(client, "dog", ["animal"])
        answer = client.get("/dag/picture").get_json()
        drawn = set(re.findall(r"<title>(n\d+)</title>", answer["svg"]))
        assert drawn, "no node groups in the SVG"
        assert drawn <= set(answer["ids"])
        assert {"animal", "dog", "*"} <= set(answer["ids"].values())

    def test_labels_are_rendered_while_the_map_stays_canonical(self, client):
        client.post("/dag/prelude")
        put(client, "JAL7", ["time(2026-08-15)"])
        answer = client.get("/dag/picture",
                            query_string={"focus": "JAL7"}).get_json()
        # Readable in the picture... (Graphviz entity-escapes `-` in labels.)
        import html as _html
        assert "time(2026-08-15)" in _html.unescape(answer["svg"])
        # ...canonical in the map, or a click would land on nothing.
        assert any(name.startswith("time(2026-08-15T00:00:00Z")
                   for name in answer["ids"].values())

    def test_a_focus_draws_its_neighbourhood_not_the_store(self, client):
        for i in range(12):
            put(client, f"item{i}")
        put(client, "dog")
        put(client, "rex", ["dog"])
        answer = client.get("/dag/picture",
                            query_string={"focus": "dog"}).get_json()
        assert set(answer["ids"].values()) == {"*", "dog", "rex"}

    def test_a_query_picture_shows_the_terms_it_was_asked(self, client):
        put(client, "animal")
        put(client, "dog", ["animal"])
        answer = client.get("/dag/picture",
                            query_string={"cat": "animal"}).get_json()
        assert "animal" in answer["ids"].values()

    def test_too_big_to_draw_says_so_instead_of_grinding(self, client):
        from ontodag.web.app import PICTURE_LIMIT
        for i in range(PICTURE_LIMIT + 1):
            put(client, f"item{i}")
        response = client.get("/dag/picture")
        assert response.status_code == 413
        assert "too many to draw" in response.get_json()["error"]


class TestNamesForCompletion:
    def test_it_offers_names(self, client):
        put(client, "Japan")
        put(client, "JAL7")
        answer = client.get("/dag/names", query_string={"prefix": "ja"}).get_json()
        assert answer["names"] == ["JAL7", "Japan"]      # case-insensitive

    def test_the_root_is_not_a_name_anyone_completes_to(self, client):
        assert "*" not in client.get("/dag/names").get_json()["names"]


class TestTheCommandMenu:
    """The menu that makes a console explorable.

    Read off the argparse parser rather than written out, so a command the
    browser can run but nobody listed is impossible — the same
    can't-drift discipline as docs/REFERENCE.md's tables.
    """

    def _menu(self, client):
        answer = client.get("/dag/commands")
        assert answer.status_code == 200
        return {c["name"]: c for c in answer.get_json()["commands"]}

    def test_it_lists_every_command_ontodag_has(self, client):
        # All of them, not the sandbox's subset: someone opening this is
        # asking what the system does, and the answer is not "whatever a
        # browser is allowed to do".
        from ontodag.web.app import NOT_IN_THE_BROWSER
        from ontodag.__main__ import PARSER
        sub = next(action for action in PARSER._actions
                   if getattr(action, "choices", None))
        assert set(self._menu(client)) == set(sub.choices) - NOT_IN_THE_BROWSER

    def test_the_command_that_starts_this_page_is_not_offered_on_it(self, client):
        # `web` is a real command; listing it here would offer to do the
        # thing you are already looking at.
        menu = self._menu(client)
        assert "web" not in menu
        assert console(client, "web")["code"] == 2
        assert "looking at" in console(client, "web")["err"]

    def test_it_says_which_ones_run_here(self, client):
        from ontodag.web.app import CONSOLE_COMMANDS
        menu = self._menu(client)
        runs = {name for name, entry in menu.items() if entry["available"]}
        assert runs == CONSOLE_COMMANDS - {"?"}

    def test_every_command_it_cannot_run_says_why(self, client):
        for name, entry in self._menu(client).items():
            if not entry["available"]:
                assert entry["why"], f"{name} is refused with no reason given"

    def test_every_command_is_in_exactly_one_group(self, client):
        # The guard that keeps this from falling behind the CLI: a new
        # command has to be classified, or this fails.
        from ontodag.web.app import COMMAND_GROUPS, NOT_IN_THE_BROWSER
        from ontodag.__main__ import PARSER
        sub = next(action for action in PARSER._actions
                   if getattr(action, "choices", None))
        grouped = [name for _, names in COMMAND_GROUPS for name in names]
        assert sorted(grouped) == sorted(set(sub.choices) - NOT_IN_THE_BROWSER)
        assert len(grouped) == len(set(grouped)), "a command is in two groups"

    def test_the_groups_come_back_in_a_stated_order(self, client):
        from ontodag.web.app import COMMAND_GROUPS
        answer = client.get("/dag/commands").get_json()
        assert answer["groups"] == [group for group, _ in COMMAND_GROUPS]

    def test_every_entry_explains_itself(self, client):
        for name, entry in self._menu(client).items():
            assert entry["help"], f"{name} has no description"
            assert entry["help"] == entry["help"].lstrip(), name

    def test_argument_shapes_come_from_the_parser(self, client):
        menu = self._menu(client)
        assert menu["put"]["args"] == "ITEM [PARENTS...]"
        assert menu["below"]["args"] == "SUB SUP"
        assert menu["get"]["args"] == "[CATEGORIES...]"
        assert menu["list"]["args"] == ""

    def test_output_plumbing_is_not_offered_as_a_choice(self, client):
        # `-o`, `--raw`, `-n` are real options and none of them is about what
        # the command does — and `-o` is refused on this surface anyway.
        for entry in self._menu(client).values():
            assert not ({"--raw", "--render", "--limit", "--output"}
                        & set(entry["flags"])), entry

    def test_the_flags_that_change_meaning_are_offered(self, client):
        menu = self._menu(client)
        assert "--cone" in menu["remove"]["flags"]
        assert {"--to", "--from"} <= set(menu["move"]["flags"])

    def test_only_commands_about_an_item_take_the_selected_one(self, client):
        menu = self._menu(client)
        for name in ("put", "move", "remove", "below", "get", "canon"):
            assert menu[name]["takes_item"], name
        # `pack NAME` has a positional too, and it names a unit pack — filling
        # in whatever is selected would be nonsense dressed up as help.
        for name in ("pack", "prelude", "list", "show", "help"):
            assert not menu[name]["takes_item"], name

    def test_a_refused_command_is_listed_but_marked(self, client):
        # Listing it and saying why turns a limitation into an explanation of
        # the design; hiding it would just make OntoDAG look smaller than it
        # is to whoever reads this page first.
        menu = self._menu(client)
        for name in ("import", "export", "set", "undo", "diff", "visualize"):
            assert name in menu, name
            assert not menu[name]["available"], name
            assert menu[name]["why"], name


class TestTheExample:
    def test_it_loads_with_the_declarations_its_values_need(self, client):
        # Typed values are refused without them, so a visitor who types
        # weight(3kg) in the first minute would get an error for doing the
        # most interesting thing on offer.
        assert client.post("/dag/example").status_code == 201
        assert console(client, "put parcel 'weight(3kg)'")["code"] == 0

    def test_it_is_idempotent(self, client):
        client.post("/dag/example")
        first = client.get("/dag/browse").get_json()["count"]
        client.post("/dag/example")
        assert client.get("/dag/browse").get_json()["count"] == first


class TestTheNewPageIsWiredUp:
    """The new page is a module, not an inline script, so the checks differ in
    mechanism from the classic page's — but they answer the same question: is
    every control connected to something that exists?"""

    def _script(self):
        import pathlib
        import ontodag.web
        return (pathlib.Path(ontodag.web.__file__).parent
                / "static" / "app.js").read_text()

    def test_the_page_loads_and_asks_for_its_module(self, client):
        page = client.get("/").data.decode()
        assert 'src="/static/app.js"' in page
        assert 'href="/static/app.css"' in page

    def test_every_url_the_module_calls_is_a_real_route(self, client):
        import re
        script = self._script()
        urls = set(re.findall(r'["`](/dag[a-z/]*)[`"?]', script))
        routes = {rule.rule for rule in app.url_map.iter_rules()}
        # Routes with a path parameter are spelled with the value inline.
        routes |= {"/dag/node", "/dag/export", "/dag/query/export"}
        missing = {url for url in urls
                   if url not in routes
                   and not any(url.startswith(r.rstrip("/") + "/")
                               for r in routes)}
        assert not missing, f"no such route(s): {sorted(missing)}"

    def test_the_module_is_valid_javascript(self, client):
        import shutil
        import subprocess
        import tempfile
        node = shutil.which("node") or shutil.which("nodejs")
        if node is None:
            pytest.skip("node not installed")
        with tempfile.NamedTemporaryFile("w", suffix=".mjs") as handle:
            handle.write(self._script())
            handle.flush()
            result = subprocess.run([node, "--check", handle.name],
                                    capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def test_the_vendored_module_is_present_and_served(self, client):
        response = client.get("/static/vendor/preact-htm.module.js")
        assert response.status_code == 200
        assert b"export{" in response.data          # it is an ES module
        assert 'from "/static/vendor/preact-htm.module.js"' in self._script()

    def test_the_classic_page_is_still_reachable(self, client):
        assert client.get("/classic").status_code == 200


class TestDeclaringDimensionsOverRest:
    """Typed values need their dimension declared, and until `/dag/prelude`
    existed the only way to do that here was to hand-create the three
    declaration nodes — which is what this file's other tests still do, and
    which no browser user would guess.
    """

    def test_a_typed_value_is_refused_before_any_declaration(self, client):
        response = put(client, "parcel", ["weight(3kg)"])
        assert response.status_code == 400
        assert "super-categories" in response.get_json()["error"]

    def test_the_prelude_makes_typed_values_work(self, client):
        assert client.post("/dag/prelude").status_code == 201
        assert put(client, "parcel", ["weight(3kg)"]).status_code == 201
        assert "parcel" in query_names(client, "weight(..5kg)")

    def test_adopting_it_twice_changes_nothing(self, client):
        client.post("/dag/prelude")
        before = client.get("/dag").get_json()["nodes"]
        client.post("/dag/prelude")
        assert client.get("/dag").get_json()["nodes"] == before

    def test_the_declarations_can_be_previewed(self, client):
        body = client.get("/dag/prelude").get_json()
        assert body["version"] >= 3
        assert any("weight" in str(d) for d in body["declarations"])
        # a preview declares nothing
        assert put(client, "parcel", ["weight(3kg)"]).status_code == 400

    def test_packs_are_listed_and_adoptable(self, client):
        packs = {p["name"] for p in client.get("/dag/pack").get_json()["packs"]}
        assert "crypto-core" in packs
        client.post("/dag/prelude")
        assert client.post("/dag/pack", json={"name": "crypto-core"}
                           ).status_code == 201
        assert put(client, "wallet", ["price(1BTC)"]).status_code in (201, 400)

    def test_an_unknown_pack_is_a_client_error(self, client):
        response = client.post("/dag/pack", json={"name": "nope"})
        assert response.status_code == 400
        assert "crypto-core" in response.get_json()["error"]   # names the real ones
        assert client.post("/dag/pack", json={}).status_code == 400


class TestOverlappingOverRest:
    """The weaker matching mode (contract G6) — candidates, not guarantees."""

    def _fixture(self, client):
        client.post("/dag/prelude")
        put(client, "parcel", ["weight(3kg)"])
        put(client, "wide", ["weight(2kg..6kg)"])

    def test_it_returns_what_query_cannot(self, client):
        self._fixture(client)
        guaranteed = query_names(client, "weight(..5kg)")
        response = client.get("/dag/overlapping",
                              query_string={"term": "weight(..5kg)"})
        assert response.status_code == 200
        candidates = {node["name"] for node in response.get_json()["nodes"]}
        assert "parcel" in guaranteed and "parcel" in candidates
        # `wide` might weigh under 5kg — a candidate, never a guarantee
        assert "wide" not in guaranteed
        assert "wide" in candidates

    def test_a_term_of_no_dimension_is_a_client_error(self, client):
        self._fixture(client)
        response = client.get("/dag/overlapping", query_string={"term": "parcel"})
        assert response.status_code == 400
        assert "denotation" in response.get_json()["error"]

    def test_a_missing_term_is_a_client_error(self, client):
        assert client.get("/dag/overlapping").status_code == 400


class TestCanonOverRest:
    """This surface shows canonical names, which makes "what would this store?"
    more useful here than anywhere — and it had no way to ask."""

    def test_a_spelling_resolves_to_what_is_stored(self, client):
        client.post("/dag/prelude")
        body = client.get("/dag/canon",
                          query_string={"term": "weight(3000g)"}).get_json()
        assert body["canonical"] == "weight(3kg)"
        assert body["display"]

    def test_bare_canon_reports_the_versions(self, client):
        body = client.get("/dag/canon").get_json()
        assert body["surface"] and body["registry"]

    def test_a_malformed_term_is_a_client_error(self, client):
        client.post("/dag/prelude")
        response = client.get("/dag/canon", query_string={"term": "weight(zz)"})
        assert response.status_code == 400
        assert "error" in response.get_json()
