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
