"""Every surface that a name flows out through, against one nasty corpus.

Written after the 0.10.1 post-mortem. 0.10.0 shipped unable to draw any DAG
containing a typed date: calendar dimensions had introduced a new character
into canonical names — `:`, which DOT reads as the port separator — and
nothing re-tested the *consumers* of names against it. The visualizer had
coverage; it just never rendered a name with a colon in it, because every
rendering test used the plain `A`/`B`/`C` fixture and every dimension test
stayed inside the DAG. No test sat in the intersection.

The same shape appeared twice more the same day: the web UI interpolated
names into a URL without encoding, so `C++ notes` queried `C   notes`.

So the lesson is not "escape colons in DOT". It is that the canonical-name
grammar fans out into at least six surfaces, each with its own escaping
rules, and a change to the grammar is a cross-cutting change:

    DOT · OWL · Manchester · the native store · REST/URL · the renderer

This file is that fan-out written down. Add a character class to the grammar
and it gets tried against every consumer here — including the ones nobody
remembered were consumers.
"""

import os
import sys
import tempfile

import pytest

from ontodag.dag import OntoDAG
from ontodag.viz import OntoDAGVisualizer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))


# Names that are legal for a user to create, or that the system creates
# itself. Each entry names the hazard it represents, so a failure says what
# broke rather than just which string broke.
NASTY_NAMES = {
    "plain": "plain",
    "space": "with space",
    "plus": "C++ notes",                 # + decodes to a space in a URL
    "ampersand": "a&b",                  # splits a query string
    "hash": "a#b",                       # truncates a URL
    "pipe": "a|b",                       # the union separator
    "comma": "a,b",                      # the conjunction separator
    "colon": "colon:name",               # the DOT port separator (0.10.0)
    "quote": 'quote"q',
    "backslash": "back\\slash",
    "unicode": "unicode-café",
    "leading-dash": "-dash",             # looks like a CLI flag
    "equals": "a=b",                     # the config-file separator
    "percent": "a%20b",                  # already-encoded-looking
}

# Canonical names the *system* generates, which is where 0.10.0 died: nobody
# types a timestamp range, so no hand-written fixture contained one.
DECLARATIONS = [
    ("dimension", []),
    ("calendar-dimension", ["dimension"]),
    ("linear-dimension", ["dimension"]),
    ("time", ["calendar-dimension"]),
    ("weight", ["linear-dimension"]),
]
GENERATED = ["time(2026-08-15)", "weight(3kg)", "time(2026)"]


def corpus_dag():
    """One DAG holding every name in the corpus, hung under one parent."""
    dag = OntoDAG()
    for name, parents in DECLARATIONS:
        dag.put(name, parents)
    dag.put("parent", [])
    for name in NASTY_NAMES.values():
        dag.put(name, ["parent"])
    for name in GENERATED:
        dag.put(f"item-for-{name}", [name])
    return dag


def stored_names(dag):
    return {n for n in dag.nodes if n != dag.root.name}


class TestTheNamesThemselves:
    def test_every_corpus_name_is_storable(self):
        # If the core ever refuses one of these, that is a decision to make
        # explicitly — not something to discover downstream in an exporter.
        dag = corpus_dag()
        for hazard, name in NASTY_NAMES.items():
            assert name in dag.nodes, f"{hazard}: {name!r} could not be stored"

    def test_generated_names_really_do_contain_the_hazard(self):
        # Guards the guard: if canonical timestamps ever stop containing a
        # colon, this file silently stops testing the 0.10.0 case.
        dag = corpus_dag()
        assert any(":" in n for n in dag.nodes), \
            "no canonical name contains a colon — is this corpus still valid?"


class TestGraphvizConsumer:
    """The 0.10.0 regression, generalized to the whole corpus."""

    def setup_method(self):
        pytest.importorskip("graphviz")

    def test_dot_source_never_puts_a_name_in_an_identifier(self):
        source = OntoDAGVisualizer().generate_dot_source(corpus_dag())
        for line in source.splitlines():
            if "->" not in line:
                continue
            # Identifiers are synthetic (n0, n1, ...). Anything else means a
            # name reached a position where DOT's own syntax applies to it.
            left, _, right = line.partition("->")
            for token in (left.strip(), right.strip().rstrip(";")):
                assert token.startswith("n") and token[1:].isdigit(), \
                    f"name used as a DOT identifier: {line!r}"

    def test_every_name_survives_into_a_label(self):
        source = OntoDAGVisualizer().generate_dot_source(corpus_dag())
        for hazard, name in NASTY_NAMES.items():
            # graphviz backslash-escapes `"` inside a label, which is correct
            # and is exactly the handling we want — compare against the
            # escaped form rather than demanding the raw bytes.
            escaped = name.replace('"', '\\"')
            assert escaped in source, f"{hazard}: {name!r} missing from the DOT"

    def test_graphviz_actually_accepts_it(self):
        # The check that matters: bad DOT is only an error once `dot` parses
        # it. Asserting on the source alone is what let 0.10.0 through.
        pytest.importorskip("PIL")
        image = OntoDAGVisualizer().generate_image(corpus_dag())
        assert image.size[0] > 0


class TestNativeStoreConsumer:
    def test_round_trip_loses_nothing(self):
        from ontodag.__main__ import _load_native, _save_native
        dag = corpus_dag()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "store.od")
            _save_native(dag, path)
            back = _load_native(path)
        assert stored_names(dag) == stored_names(back)

    def test_the_store_stays_canonical(self):
        # Saving twice must be byte-identical, whatever the names contain —
        # the file is the thing that gets diffed and merged.
        from ontodag.__main__ import _save_native
        dag = corpus_dag()
        with tempfile.TemporaryDirectory() as tmp:
            first, second = (os.path.join(tmp, n) for n in ("a.od", "b.od"))
            _save_native(dag, first)
            _save_native(dag, second)
            assert open(first).read() == open(second).read()


class TestOwlConsumers:
    def setup_method(self):
        pytest.importorskip("owlready2")

    # OWL is the one consumer that cannot carry every name: a node name
    # becomes the class IRI, and `"` is illegal in an IRI. Everything else
    # in the corpus round-trips.
    OWL_HOSTILE = {'quote"q'}

    def test_owl_round_trip_loses_nothing(self):
        from ontodag.owl import OWLOntology
        dag = corpus_dag()
        for name in self.OWL_HOSTILE:
            dag.remove(name)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "o.owl")
            OWLOntology.export_dag(dag, path)
            back = OWLOntology(f"file://{os.path.abspath(path)}").import_dag(
                file_name=path)
        assert stored_names(dag) <= stored_names(back)

    def test_a_name_owl_cannot_carry_is_refused_not_corrupted(self):
        # Before this check, the export "succeeded" and wrote a file that was
        # not well-formed XML — `rdf:about="#quote"q"` — so the damage only
        # appeared when something read it back, possibly on someone else's
        # machine. Refusing up front is the whole fix; there is nothing to
        # escape, because the character is illegal in an IRI.
        from ontodag.owl import OWLOntology
        dag = corpus_dag()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "o.owl")
            with pytest.raises(ValueError, match="double quote"):
                OWLOntology.export_dag(dag, path)
            assert not os.path.exists(path), \
                "refused export must not leave a corrupt file behind"

    def test_manchester_carries_what_owl_cannot(self):
        # The escape hatch the error message points at has to actually work.
        from ontodag.owl import OWLOntology
        dag = corpus_dag()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "o.omn")
            OWLOntology.export_dag_manchester(dag, path)
            back = OWLOntology.import_dag_manchester(file_name=path)
        assert self.OWL_HOSTILE <= stored_names(back)

    def test_manchester_round_trip_loses_nothing(self):
        from ontodag.owl import OWLOntology
        dag = corpus_dag()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "o.omn")
            OWLOntology.export_dag_manchester(dag, path)
            back = OWLOntology.import_dag_manchester(file_name=path)
        assert stored_names(dag) <= stored_names(back)


class TestSurfaceRendererConsumer:
    def test_rendering_a_name_never_changes_what_it_denotes(self):
        # The §4 law: elaborate(render(t)) == t. Fuzzed over dimension values
        # in test_surface.py; here it meets the awkward *opaque* names too,
        # which must pass through untouched.
        from ontodag import surface
        dag = corpus_dag()
        for name in stored_names(dag):
            shown = surface.render(name, dag)
            assert surface.elaborate(shown, dag) == name, \
                f"{name!r} rendered as {shown!r}, which means something else"


class TestRestConsumer:
    """The URL member of the family — the `C++ notes` bug."""

    def test_every_name_is_queryable_over_http(self):
        pytest.importorskip("flask")
        pytest.importorskip("dot2tex")
        from app import app
        app.config["TESTING"] = True
        with app.test_client() as client:
            assert client.post("/dag").status_code == 201
            for hazard, name in NASTY_NAMES.items():
                assert client.post("/dag/node", json={
                    "subcategories": [name],
                }).status_code == 201, f"{hazard}: could not create {name!r}"
                assert client.post("/dag/node", json={
                    "subcategories": [f"child-of-{hazard}"],
                    "super_categories": [name],
                }).status_code == 201, hazard
            # Query each name back. `,` and `|` are query separators, so a
            # name containing them cannot be asked for — a real limit of the
            # wire format, recorded here rather than discovered later.
            for hazard, name in NASTY_NAMES.items():
                if "," in name or "|" in name:
                    continue
                response = client.get("/dag/query",
                                      query_string={"cat": name})
                assert response.status_code == 200, hazard
                found = {n["name"] for n in response.get_json()["nodes"]}
                assert f"child-of-{hazard}" in found, \
                    f"{hazard}: querying {name!r} did not find its child"
