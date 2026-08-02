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
