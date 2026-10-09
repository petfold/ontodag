"""The API for programs that embed OntoDAG (0.27.0).

Everything here existed before, privately: a web app built on OntoDAG
(categor.io) had to reach into `ontodag.__main__` for the `.od` reader,
into `OntoDAG._parse_parametric` to tell a typed value from a missing
category, and build whole pack DAGs to learn a pack's top. These pin the
public forms, and pin them to the private behaviour they replace.
"""

import os
import tempfile

import pytest

from ontodag import native, packs
from ontodag.__main__ import (COMMAND_EFFECTS, EFFECTS, PARSER, _load_native,
                              _save_native, effects)
from ontodag.dag import OntoDAG


def _sample():
    dag = OntoDAG()
    dag.put("animal", [])
    dag.put("dog", ["animal"])
    dag.put("C++ & notes", [])
    dag.put("rex", ["dog", "C++ & notes"])
    dag.nodes["rex"].metadata["label"] = "Rex, the dog\nline two"
    return dag


# ---- ontodag.native ----------------------------------------------------------

def test_dumps_is_what_the_cli_writes():
    dag = _sample()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "s.od")
        _save_native(dag, path)
        with open(path, encoding="utf-8") as fh:
            assert fh.read() == native.dumps(dag)


def test_loads_round_trips_byte_identically():
    text = native.dumps(_sample())
    back = native.loads(text)
    assert native.dumps(back) == text
    assert back.nodes["rex"].metadata == {"label": "Rex, the dog\nline two"}
    assert back.is_below("rex", "animal")


def test_loads_reduces_a_hand_written_file():
    dag = native.loads("# ontodag store v1\nanimal\ndog animal\nrex dog animal\n")
    assert [p.name for p in dag.nodes["rex"].parents] == ["dog"]


def test_a_malformed_meta_line_names_its_source_and_line():
    with pytest.raises(ValueError, match=r"upload\.od:2: malformed #:meta"):
        native.loads("# ontodag store v1\n#:meta rex 'not json'\nrex\n", source="upload.od")


@pytest.mark.parametrize("line", ["#:meta rex '[1, 2]'", "#:meta rex 5",
                                  "#:meta rex null", "rex 'unclosed"])
def test_every_malformed_line_is_a_value_error_naming_its_line(line):
    # JSON that is not an object escaped as TypeError, and an unbalanced
    # quote named no line (until 2026-10-09)
    with pytest.raises(ValueError, match=r"upload\.od:2: malformed"):
        native.loads(f"# ontodag store v1\n{line}\nrex\n", source="upload.od")


def test_a_store_with_a_role_term_naming_a_place_reopens():
    # A role term sorts before the place it names is placed in its
    # dimension, and a strict replay refused it: such a store could not be
    # loaded again (0.25.0 to 0.30.8).
    from ontodag import prelude
    dag = OntoDAG()
    prelude.apply(dag)
    for name, parents in (("place", ["geo"]), ("my_home", ["place"]),
                          ("from", ["geo"]), ("parcel", ["from(my_home)"])):
        dag.put(name, parents)
    text = native.dumps(dag)
    back = native.loads(text)
    assert native.dumps(back) == text
    assert back.is_below("parcel", "from(place)")
    assert [i.name for i in back.get(["from(my_home)"]) if i.name == "parcel"]


def test_load_of_a_missing_file_is_an_empty_store():
    with tempfile.TemporaryDirectory() as tmp:
        dag = native.load(os.path.join(tmp, "nothing-here.od"))
        assert set(dag.nodes) == {dag.root.name}


def test_the_cli_names_are_the_public_functions():
    assert _load_native is native.load and _save_native is native.save


# ---- OntoDAG.is_term ---------------------------------------------------------

def test_is_term():
    from ontodag import prelude
    dag = OntoDAG()
    assert not dag.is_term("time(2026-08)")          # undeclared: an opaque atom
    prelude.apply(dag)
    assert dag.is_term("time(2026-08)")
    assert dag.is_term("mass(3000g)")
    assert not dag.is_term("dog")
    assert not dag.is_term("foo(bar)")               # term-shaped, undeclared head
    with pytest.raises(ValueError, match="calendar value"):
        dag.is_term("time(zzz)")                     # declared head, malformed value
    assert dag.is_term("time(2026-08)") == (dag._parse_parametric("time(2026-08)") is not None)


# ---- packs.pack_members / pack_top -------------------------------------------

@pytest.mark.parametrize("name", sorted(packs.PACKS))
def test_pack_members_are_what_describe_counts(name):
    members = packs.pack_members(name)
    assert len(members) == int(packs.describe(name).split()[0])
    assert members <= set(packs.pack_dag(name).nodes)


@pytest.mark.parametrize("name", sorted(packs.PACKS))
def test_pack_top_is_the_top_of_the_pack_dag(name):
    dag = packs.pack_dag(name)
    assert packs.pack_top(name) == sorted(n.name for n in dag.root.neighbors)


def test_pack_functions_teach_on_an_unknown_pack():
    with pytest.raises(ValueError, match="unknown pack"):
        packs.pack_top("no-such-pack")


# ---- command effects ---------------------------------------------------------

def test_every_command_declares_its_effects():
    sub = next(a for a in PARSER._actions if getattr(a, "choices", None))
    assert set(COMMAND_EFFECTS) == set(sub.choices)
    for name, touched in COMMAND_EFFECTS.items():
        assert touched <= EFFECTS, name


def test_effects_follow_the_flags():
    assert effects(["get", "dog"]) == {"reads"}
    assert effects(["get", "dog", "-o", "out.txt"]) == {"reads", "files"}
    assert effects(["count", "--output=x"]) == {"reads", "files"}
    assert effects(["?", "rex", "dog"]) == {"reads"}
    assert effects(["pack"]) == {"reads"}
    assert effects(["pack", "core", "--show"]) == {"reads"}
    assert effects(["pack", "core", "--diff"]) == {"reads"}
    assert "writes" in effects(["pack", "core"])
    assert effects(["prelude", "--show"]) == {"reads"}
    assert "writes" in effects(["prelude"])
    assert "files" in effects(["export", "x.od"])
    assert effects(["set", "store", "rs:x"]) == {"settings"}
    with pytest.raises(ValueError, match="unknown command"):
        effects(["rm", "-rf", "/"])


def test_the_web_console_is_derived_from_the_effects():
    pytest.importorskip("flask")
    pytest.importorskip("dot2tex")
    from ontodag.web.app import CONSOLE_COMMANDS, CONSOLE_REFUSALS
    # What the sandbox ran before the list was derived, plus `shared-with`
    # (0.28, reads only): it must not move without someone deciding.
    assert CONSOLE_COMMANDS == {
        "put", "get", "count", "below", "?", "canon", "list", "show",
        "move", "remove", "overlapping", "overlaps", "meet", "prelude", "pack",
        "help", "shared-with"}
    # Every command it refuses still says why.
    assert set(COMMAND_EFFECTS) - CONSOLE_COMMANDS <= set(CONSOLE_REFUSALS)
