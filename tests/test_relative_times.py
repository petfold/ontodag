"""Relative times in `time(...)` (question 31, decided A by Peter on
2026-10-11): `now`, `today`, `tomorrow` and offsets from now are read where
a person or an agent types — the `odag` command, the agent tool, the web
console and `surface.elaborate(..., now=)` — and turned into absolute UTC
there; the core and every replay never see one."""

import io
import os
import re
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone

import pytest

from ontodag import OntoDAG, native, prelude, settings, surface
from ontodag.__main__ import Session, dispatch
from ontodag.mcp import AgentSurface

NOW = int(datetime(2026, 10, 11, 9, 46, 5, tzinfo=timezone.utc).timestamp())


def dag():
    d = OntoDAG()
    prelude.apply(d)
    d.put("depart", ["time"])                  # a role of time
    return d


@pytest.mark.parametrize("typed, stored", [
    ("today", "2026-10-11"),
    ("tomorrow", "2026-10-12"),
    ("now", "2026-10-11T09:46:05Z"),
    ("+2h", "2026-10-11T11:46:05Z"),
    ("-90min", "2026-10-11T08:16:05Z"),
    ("today..+7d", "2026-10-11..2026-10-18T09:46:04Z"),      # an instant closes before itself
    ("now..+2h", "2026-10-11T09:46:05Z..2026-10-11T11:46:04Z"),
    ("..+90d", "..2027-01-09T09:46:04Z"),                     # `..` is an open end
    ("now..", "2026-10-11T09:46:05Z.."),
    ("2026-10-12..+1wk", "2026-10-12..2026-10-18T09:46:04Z"),  # offsets count from now
    ("2026-10", "2026-10"),                                   # nothing relative: as typed
])
def test_a_relative_value_is_the_absolute_one_it_spells(typed, stored):
    assert surface.relative_calendar(typed, NOW) == stored


def test_today_is_the_utc_day_holding_now():
    late = int(datetime(2026, 10, 11, 23, 59, 59, tzinfo=timezone.utc).timestamp())
    assert surface.relative_calendar("today", late) == "2026-10-11"
    assert surface.relative_calendar("tomorrow", late) == "2026-10-12"
    assert surface.relative_calendar("today", late + 1) == "2026-10-12"


@pytest.mark.parametrize("typed, says", [
    ("+90m", "metres in ontodag; an offset from now is a duration: write +90min"),
    ("+90", "an offset from now is a duration"),
    ("+90kg", "an offset from now is a duration"),
    ("+2w", "a week is wk: write +2wk"),
    ("+1/3s", "kept to the second"),
])
def test_an_offset_is_a_whole_duration_in_ontodags_units(typed, says):
    with pytest.raises(ValueError, match=re.escape(says)):
        surface.relative_calendar(typed, NOW)


def test_elaborate_reads_them_with_a_clock_and_refuses_them_without():
    d = dag()
    assert surface.elaborate("time(today..+7d)", d, now=NOW) == \
        "time(2026-10-11T00:00:00Z..2026-10-18T09:46:04Z)"
    assert surface.elaborate("depart(tomorrow)", d, now=NOW) == \
        "depart(2026-10-12T00:00:00Z..2026-10-12T23:59:59Z)"
    assert surface.elaborate("time(today)", kind="calendar-dimension", now=NOW) == \
        "time(2026-10-11T00:00:00Z..2026-10-11T23:59:59Z)"
    with pytest.raises(ValueError, match="a relative time is read only where it is typed"):
        surface.elaborate("time(today)", d)


def test_only_calendar_values_are_read():
    d = dag()
    d.put("today", [])                         # a category may be called today
    for name in ("in(today)", "mass(today)", "today", "about(time)"):
        assert surface.absolute(name, d, NOW) == name
    assert surface.absolute("time(today)", None, NOW) == "time(today)"   # no context


def test_the_core_and_a_replay_never_read_one():
    d = dag()
    with pytest.raises(ValueError, match="surface.elaborate"):
        d.put("concert", ["time(today)"])
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "s.od")
        native.save(d, path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("concert time(today)\n")    # no longer canonical: read as lines
        with pytest.raises(ValueError, match="relative time"):
            native.load(path)


# ------------------------------------------------------------- the command line

def run(argv, session):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = dispatch(argv, session)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTODAG_NOW", "2026-10-11T09:46:05Z")
    session = Session(str(tmp_path / "s.od"))
    assert run(["prelude"], session)[0] == 0
    return session


def test_odag_stores_the_absolute_value_and_says_so(store):
    code, _, err = run(["put", "concert", "time(today..+7d)"], store)
    assert code == 0
    assert "odag: time(today..+7d) → time(2026-10-11..2026-10-18T09:46:04Z)" in err
    assert store.dag.parents_of("concert") == \
        ["time(2026-10-11T00:00:00Z..2026-10-18T09:46:04Z)"]
    assert run(["below", "concert", "time(..+90d)"], store)[:2] == (0, "true\n")
    code, out, _ = run(["get", "time(2026-10)"], store)
    assert "concert" in out


def test_the_clock_is_a_setting(store, monkeypatch):
    monkeypatch.setenv("ONTODAG_NOW", "2026-12-24")
    run(["put", "eve", "time(today)"], store)
    assert store.dag.parents_of("eve") == ["time(2026-12-24T00:00:00Z..2026-12-24T23:59:59Z)"]
    assert settings.parse_clock("1790834400") == 1790834400
    code, _, err = run(["set", "now", "soon"], store)
    assert code == 1 and "a time such as 2026-10-11T09:00:00Z" in err


def test_nothing_reads_the_clock_when_nothing_is_relative(store, monkeypatch):
    def no_clock():
        raise AssertionError("the clock was read")
    monkeypatch.setattr(settings, "clock", no_clock)
    assert run(["put", "doc", "time(2026)"], store)[0] == 0
    assert run(["get", "time(2026)", "doc"], store)[0] == 0


def test_the_web_console_reads_them(store):
    pytest.importorskip("flask")
    from ontodag.web.app import run_console_line
    out, err, code = run_console_line("put gig 'time(tomorrow)'", store.dag)
    assert code == 0 and "time(tomorrow) → time(2026-10-12)" in err
    assert store.dag.parents_of("gig") == ["time(2026-10-12T00:00:00Z..2026-10-12T23:59:59Z)"]


# ---------------------------------------------------------------- the agent tool

def test_the_agent_tool_reads_them_and_echoes_the_dates(store):
    run(["put", "concert", "time(2026-10-14T19:00:00Z..2026-10-14T21:59:59Z)"], store)
    store.save()
    agent = AgentSurface(store.spec)
    answer = agent.call("query", {"terms": ["time(today..+7d)"]})
    assert answer["terms"] == ["time(2026-10-11T00:00:00Z..2026-10-18T09:46:04Z)"]
    assert "concert" in answer["items"]
    below = agent.call("is_below", {"sub": "concert", "sup": "time(now..+1wk)"})
    assert below["result"] and below["sup"] == "time(2026-10-11T09:46:05Z..2026-10-18T09:46:04Z)"
    either = agent.call("query", {"any_of": [["time(tomorrow)"], ["time(today)"]]})
    assert either["any_of"] == [["time(2026-10-12T00:00:00Z..2026-10-12T23:59:59Z)"],
                                ["time(2026-10-11T00:00:00Z..2026-10-11T23:59:59Z)"]]
