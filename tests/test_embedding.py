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


# ---- the canonical marker (2026-10-09) ----------------------------------------

def _typed():
    """A store with values, a pack's units, a relation and a role term."""
    from ontodag import prelude
    dag = OntoDAG()
    prelude.apply(dag)
    dag.merge(packs.pack_dag("crypto-core"))
    for name, parents in (("price", ["linear-dimension"]), ("place", ["geo"]),
                          ("paris", ["place"]), ("louvre", ["place", "in(paris)"]),
                          ("from", ["geo"]), ("parcel", ["from(paris)", "mass(5kg)"]),
                          ("coffee", ["price(5000sat)", "about(paris)"])):
        dag.put(name, parents)
    return dag


def _unmarked(text):
    """The same file as a release before the marker wrote it."""
    head, marker, body = text.split("\n", 2)
    assert marker.startswith(native.CANONICAL_LINE)
    return f"{head}\n{body}"


def test_dumps_marks_what_it_writes():
    import hashlib
    from ontodag.dimensions import REGISTRY_VERSION
    text = native.dumps(_typed())
    head, marker, body = text.split("\n", 2)
    assert head == native.HEADER
    assert marker == (f"{native.CANONICAL_LINE} {REGISTRY_VERSION} "
                      f"{hashlib.sha256(body.encode()).hexdigest()}")


def test_a_marked_file_is_built_as_written(monkeypatch):
    text = native.dumps(_typed())
    def refuse(*args, **kwargs):
        raise AssertionError("a marked file was reduced again")
    monkeypatch.setattr(OntoDAG, "add_edge", refuse)
    back = native.loads(text)
    assert native.dumps(back) == text
    assert back.is_below("coffee", "price(..1/1000BTC)")
    assert back.nodes["*"].descendant_count == len(back.nodes) - 1


@pytest.mark.parametrize("change", ["no marker", "another registry", "edited"])
def test_any_other_file_is_restored_to_the_same_store(change, monkeypatch):
    text = native.dumps(_typed())
    head, marker, body = text.split("\n", 2)
    if change == "no marker":
        other = _unmarked(text)
    elif change == "another registry":
        word, _, digest = marker.split()
        other = f"{head}\n{word} 4.2 {digest}\n{body}"
    else:
        other = f"{head}\n{marker}\n{body}".replace("\nparcel ", "\nparcel  ")
    def refuse(*args, **kwargs):
        raise AssertionError("an unvouched file was trusted")
    monkeypatch.setattr(native, "_direct", refuse)
    assert native.dumps(native.loads(other)) == text


@pytest.mark.parametrize("written", ["'mass(5000g)'", "'mass(5kg)'",
                                     "'mass(5000000mg)' 'mass(5kg)'"])
def test_a_hand_written_value_is_read_by_its_one_name(written):
    # Until 2026-10-09 `x mass(5000g)` loaded as a second name for 5 kg,
    # outside mass's star: is_below(x, mass(5kg)) was true while
    # get mass(5kg) missed x.
    from ontodag import prelude
    body = native.dumps(prelude.prelude_dag()).split("\n", 2)[2]
    dag = native.loads(f"{native.HEADER}\n{body}x {written}\n")
    assert [p.name for p in dag.nodes["x"].parents] == ["mass(5kg)"]
    assert not {"mass(5000g)", "mass(5000000mg)"} & set(dag.nodes)
    assert "x" in {i.name for i in dag.get(["mass(5kg)"])}
    assert "x" in {i.name for i in dag.get(["mass(..6kg)"])}


def test_a_value_waits_for_its_vocabulary_whatever_the_names_sort_as():
    # `area(1ha)` sorts before the kind node that makes `area` a head, and
    # `price(...BTC)` before the pack declaration of BTC: read too early,
    # each was an opaque name filed beside its head.
    body = _unmarked(native.dumps(_typed())).split("\n", 1)[1]
    dag = native.loads(f"{native.HEADER}\n{body}x 'area(1ha)' 'price(1000sat)'\n")
    assert sorted(p.name for p in dag.nodes["x"].parents) == \
        ["area(10000m2)", "price(1/100000BTC)"]
    assert "area(1ha)" not in dag.nodes
    assert dag.is_below("x", "price(..1/1000BTC)")


def _merged(*peers):
    from ontodag import prelude
    stores = []
    for filings in peers:
        dag = OntoDAG()
        prelude.apply(dag)
        for name, parents in filings:
            dag.put(name, parents)
        stores.append(dag)
    out = OntoDAG()
    prelude.apply(out)
    for peer in stores:
        out.merge(peer)
    return out


@pytest.mark.parametrize("peers", [
    # two values of one head that cannot both hold: put refuses the second
    ([("crate", ["mass(1kg)"])], [("crate", ["mass(2kg)"])]),
    # two that overlap: put files under the meet, a merge keeps both
    ([("box", ["mass(1kg..5kg)"])], [("box", ["mass(2kg..8kg)"])]),
    # each inside the other: put refuses the second
    ([("place", []), ("x", ["place"]), ("y", ["place", "in(x)"])],
     [("place", []), ("y", ["place"]), ("x", ["place", "in(y)"])]),
], ids=["disjoint values", "overlapping values", "each inside the other"])
def test_a_store_a_merge_made_opens_again_as_it_was(peers):
    text = native.dumps(_merged(*peers))
    assert native.dumps(native.loads(_unmarked(text))) == text


@pytest.mark.parametrize("make", ["sample", "typed", "fragment", "g7"])
def test_on_what_odag_writes_the_replay_reads_what_the_marker_vouches_for(make):
    if make == "g7":
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "fixtures", "g7.od")
        dag = native.load(path)
    elif make == "fragment":
        # what `diff --additions` writes: an arrival's parent without one
        entries, metadata, _ = native._parse(
            ["Ryokan", "Ryokan-Kyoto Ryokan", "JAL-cheap Ryokan"], "add.od")
        dag = native._direct(entries, metadata)
    else:
        dag = _sample() if make == "sample" else _typed()
    text = native.dumps(dag)
    entries, metadata, lined = native._parse(text.splitlines(), "t")
    assert native.dumps(native._restore(entries, metadata, lined)) == \
        native.dumps(native._direct(entries, metadata)) == text


def test_a_parent_never_given_a_line_is_top_level():
    dag = native.loads("# ontodag store v1\nrex dog\n")
    assert dag.root in dag.nodes["dog"].parents
    assert {i.name for i in dag.get([])} == {"dog", "rex"}


def test_an_older_release_s_store_loads_as_it_was():
    # g7.od was written by 0.30.1, before the marker, and holds a compound
    # that release folded: loading reads it, it does not migrate it (G7).
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fixtures", "g7.od")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert native.CANONICAL_LINE not in text
    dag = native.loads(text)
    assert "transport(mass(..8kg) small-item)" in dag.nodes
    assert native.dumps(dag).split("\n", 2)[2] == text.split("\n", 1)[1]


def test_a_file_git_could_not_merge_is_refused_not_read_as_names():
    text = native.dumps(_sample())
    head, marker, body = text.split("\n", 2)
    conflicted = (f"{head}\n<<<<<<< HEAD\n{marker}\n=======\n"
                  f"{native.CANONICAL_LINE} 4.3 {'0' * 64}\n>>>>>>> laptop\n{body}")
    with pytest.raises(ValueError, match=r"me\.od:2: an unresolved merge conflict"):
        native.loads(conflicted, source="me.od")
    resolved = f"{head}\n{body}"
    assert native.dumps(native.loads(resolved)) == text


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
    # (0.28, reads only) and `rename` (0.30.9, decided with `remove
    # --with-terms`): it must not move without someone deciding.
    assert CONSOLE_COMMANDS == {
        "put", "get", "count", "below", "?", "canon", "list", "show",
        "move", "rename", "remove", "overlapping", "overlaps", "meet",
        "prelude", "pack", "help", "shared-with"}
    # Every command it refuses still says why.
    assert set(COMMAND_EFFECTS) - CONSOLE_COMMANDS <= set(CONSOLE_REFUSALS)


# ---- ontodag.open, ontodag.settings (review question 5) ----------------------
#
# What loopmarket and ontodag-fs reached for in `ontodag.__main__`'s private
# names, public. Pinned to the CLI on both sides: a program and `odag` open the
# same store from the same settings, and the old names are the new objects.

import ontodag
import ontodag.__main__ as cli
from ontodag import settings, stores


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fresh odag home, no store setting from the environment, and an empty
    flag layer (restored afterwards: it is one dict for the process)."""
    monkeypatch.setenv("ONTODAG_HOME", str(tmp_path / "home"))
    for setting in settings.SETTINGS.values():
        monkeypatch.delenv(setting.env, raising=False)
    saved = dict(settings.OVERRIDES)
    settings.OVERRIDES.clear()
    yield tmp_path
    settings.OVERRIDES.clear()
    settings.OVERRIDES.update(saved)


def test_open_finds_the_store_odag_would(home, monkeypatch):
    default = os.path.join(str(home), "home", "store.od")
    assert ontodag.open().spec == default == cli._resolve_store()
    settings.write_config({"store": "rs:" + str(home / "configured")})
    assert ontodag.open().spec == "rs:" + str(home / "configured")
    monkeypatch.setenv("ONTODAG_STORE", str(home / "env.od"))
    assert ontodag.open().spec == str(home / "env.od")
    settings.OVERRIDES["store"] = str(home / "flag.od")
    assert ontodag.open().spec == str(home / "flag.od")
    assert ontodag.open(str(home / "given.od")).spec == str(home / "given.od")
    # Normalized as odag's -f is: absolute, inside an rs: prefix too.
    monkeypatch.chdir(home)
    assert ontodag.open("rs:here").spec == "rs:" + str(home / "here")


def test_a_program_and_odag_share_one_store(home, capsys):
    path = str(home / "travel.od")
    store = ontodag.open(path)
    store.dag.put("japan", [])
    store.dag.put("kyoto", ["japan"])
    store.save()
    assert cli.dispatch(["get", "japan"], cli.Session(path)) == 0
    assert capsys.readouterr().out == "kyoto\n"
    assert cli.dispatch(["put", "osaka", "japan"], cli.Session(path)) == 0
    assert {n.name for n in ontodag.open(path).dag.get(["japan"])} == {"kyoto", "osaka"}


def test_open_reads_nothing_until_the_store_is_used(home):
    path = home / "broken.od"
    path.write_text("# ontodag store v1\n<<<<<<< HEAD\nx\n", encoding="utf-8")
    store = ontodag.open(str(path))          # constructing never fails on the store
    assert store.describe() == str(path)
    with pytest.raises(ValueError, match="merge conflict"):
        store.dag


def test_a_past_version_reads_as_it_was_and_takes_no_writes(home, capsys):
    pytest.importorskip("recordstore")
    spec = "rs:" + str(home / "versions")
    store = ontodag.open(spec)
    store.dag.put("rex", [])
    store.save(message="rex arrives")
    first = store.dag.store.root
    store.dag.put("tweety", [])
    store.save(message="tweety arrives")
    assert cli.dispatch(["history"], cli.Session(spec)) == 0
    shown = capsys.readouterr().out
    assert "rex arrives" in shown and "tweety arrives" in shown
    past = ontodag.open(spec, as_of=first[:12])     # the prefix history shows
    assert "tweety" not in past.dag.nodes and "rex" in past.dag.nodes
    with pytest.raises(ValueError, match="read-only"):
        past.save()
    assert "tweety" in ontodag.open(spec).dag.nodes   # the store stayed put


def test_settings_resolve_by_one_rule(home, monkeypatch):
    assert settings.configured("limit") == "auto"                 # default
    settings.write_config({"limit": "7"})
    assert settings.read_config() == {"limit": "7"}
    assert settings.configured("limit") == "7"                    # config file
    monkeypatch.setenv("ONTODAG_LIMIT", "9")
    assert settings.configured("limit") == "9"                    # environment
    settings.OVERRIDES["limit"] = "3"
    assert settings.configured("limit") == "3"                    # flag layer
    assert settings.configured("limit", "5") == "5"               # the command's own flag
    with pytest.raises(KeyError):
        settings.configured("no_such_setting")


def test_the_cli_names_are_the_public_objects():
    """loopmarket's and ontodag-fs's released versions still reach for these;
    an alias that became a copy would let the two drift (a write to
    `cli._OVERRIDES` must be a write to the flag layer)."""
    assert cli._OVERRIDES is settings.OVERRIDES
    assert cli._SETTINGS is settings.SETTINGS
    for old, new in (("_configured", "configured"), ("_read_config", "read_config"),
                     ("_write_config", "write_config"), ("_resolve_store", "resolve_store"),
                     ("_normalize_spec", "normalize_spec"), ("_home_dir", "home_dir"),
                     ("_config_path", "config_path"),
                     ("_default_store_path", "default_store_path"),
                     ("_overlay_specs", "overlay_specs")):
        assert getattr(cli, old) is getattr(settings, new), old
    assert cli.Session is stores.Store
    assert cli._make_backend is stores.make_backend
    for name in ("FileBackend", "SwarmBackend", "LocalRecordBackend"):
        assert getattr(cli, name) is getattr(stores, name)


# ---- OntoDAG.parse_term / canonical / parents_of (review question 5) ----------

def _typed_places():
    from ontodag import prelude
    dag = OntoDAG()
    prelude.apply(dag)
    dag.put("place", [])
    dag.put("city", ["place"])
    dag.put("paris", ["city"])
    dag.put("museum", [])
    dag.put("louvre", ["in(paris)", "museum"])
    dag.put("crate", ["mass(3000g)"])
    return dag


def test_parse_term():
    dag = _typed_places()
    term = dag.parse_term("mass(3000g)")
    assert term == ("mass", "linear-dimension", "mass(3kg)")
    assert (term.head, term.kind, term.canonical) == term
    assert dag.parse_term("in(paris)") == ("in", "transitive-dimension", "in(paris)")
    assert dag.parse_term("paris") is None
    assert dag.parse_term("foo(bar)") is None            # term-shaped, undeclared head
    with pytest.raises(ValueError, match="unknown unit"):
        dag.parse_term("mass(3zz)")                      # declared head, malformed value
    for name in ("mass(3000g)", "time(2026-08)", "in(paris)", "paris", "foo(bar)"):
        assert dag.parse_term(name) == dag._parse_parametric(name)


def test_canonical():
    dag = _typed_places()
    assert dag.canonical("mass(3000g)") == "mass(3kg)"
    assert dag.canonical("paris") == "paris"
    assert dag.canonical("foo(bar)") == "foo(bar)"
    with pytest.raises(ValueError):
        dag.canonical("mass(3zz)")
    for name in ("mass(3000g)", "time(2026-08)", "paris"):
        assert dag.canonical(name) == dag._canonical_name(name)


def test_parents_of():
    dag = _typed_places()
    assert dag.parents_of("louvre") == ["in(paris)", "museum"]     # sorted
    assert dag.parents_of("paris") == ["city"]
    assert dag.parents_of("place") == []                           # top level: not "*"
    assert dag.parents_of("crate") == ["mass(3kg)"]
    assert dag.parents_of("mass(3000g)") == ["mass"]               # any spelling, its head
    with pytest.raises(ValueError, match="not in the store"):
        dag.parents_of("berlin")
    for name in ("louvre", "paris", "place", "crate"):
        live = dag._live_parent_names(name)
        assert dag.parents_of(name) == sorted(p for p in live if p != "*")
