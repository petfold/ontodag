"""REST-level tests for the Flask web app (web/app.py), with the parametric-
dimensions flow exercised over HTTP. Skips cleanly when the web extras are
not installed (the app imports flask and dot2tex at module level)."""

import os
import sys

import pytest

pytest.importorskip("flask")
pytest.importorskip("dot2tex")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))
from app import app  # noqa: E402  (needs the path insert above)


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
        from app import QUERY_LOG
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
