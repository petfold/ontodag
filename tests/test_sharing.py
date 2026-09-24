"""ontodag.sharing — what one store shows another (docs/plans/SHARING.md).

The scenarios are categor.io's (its tests/test_site.py, `test_acme` and
the rest), restated over plain DAGs: the site was the first to need the
rule, and its behaviour is what this module must keep.
"""

import os
import random
import tempfile

import pytest

from ontodag import prelude, sharing
from ontodag.__main__ import Session, dispatch
from ontodag.dag import OntoDAG

ADA, BOB, HARRY = "ada@categor.io", "bob@categor.io", "harry@categor.io"


def acme():
    """Acme's store, as DESIGN §5 of categor.io builds it."""
    dag = OntoDAG()
    for name, parents in [
            (ADA, []), (BOB, []), (HARRY, []), ("document", []),
            ("employees", [ADA, BOB, HARRY]),       # a group: filed under its members
            ("sales", [HARRY]),                     # a department
            ("employees", ["sales"]),               # sales has all that employees have
            ("merger-plans", []),
            ("employee-information", ["employees", "merger-plans"]),
            ("handbook", ["employee-information", "document"]),
            ("sales-leads", ["sales"])]:
        dag.put(name, parents)
    return dag


# ---- the rule ----------------------------------------------------------------

def test_what_each_reader_sees():
    dag = acme()
    assert sharing.reach(dag, [ADA]) == {"employees", "employee-information", "handbook"}
    assert sharing.reach(dag, [HARRY]) == {"employees", "employee-information", "handbook",
                                           "sales", "sales-leads"}


def test_parents_stay_closed():
    reach = sharing.reach(acme(), [ADA])
    assert "merger-plans" not in reach and "document" not in reach


def test_members_do_not_see_each_other():
    reach = sharing.reach(acme(), [ADA])
    assert BOB not in reach and HARRY not in reach


def test_the_reader_is_not_in_their_own_reach():
    assert ADA not in sharing.reach(acme(), [ADA])


def test_several_principals_unite():
    dag = acme()
    assert sharing.reach(dag, [ADA, HARRY]) == sharing.reach(dag, [HARRY])


def test_an_unknown_principal_sees_nothing():
    assert sharing.reach(acme(), ["nobody@categor.io"]) == frozenset()


def test_reach_is_is_below():
    dag = acme()
    for principal in (ADA, BOB, HARRY):
        reach = sharing.reach(dag, [principal])
        for name in dag.nodes:
            assert (name in reach) == (dag.is_below(name, principal) and name != principal)


def test_typed_values_follow_the_combined_order():
    """A value filed under a principal shares what is filed at values inside
    it, with no edge stored between them — the order `get` uses. (categor.io's
    own walk followed asserted edges only, and missed this.)"""
    dag = OntoDAG()
    prelude.apply(dag)
    dag.put(ADA, [])
    dag.put("time(2026)", [ADA])
    dag.put("trip", ["time(2026-08)"])
    assert "trip" in sharing.reach(dag, [ADA])


def test_classifying_in_another_store_shares_nothing():
    """The rule reads one store. Bob's `rex ⊑ dog` is not in Acme's store,
    so nothing Acme shares under `dog` reaches `rex` — whereas merging the
    two stores first would."""
    dag = acme()
    dag.put("dog", ["employees"])            # Acme shares `dog` with its employees
    bobs = OntoDAG()
    bobs.put("dog", [])
    bobs.put("rex", ["dog"])
    assert "rex" not in sharing.reach(dag, [ADA])
    merged = acme()
    merged.put("dog", ["employees"])
    merged.merge(bobs)
    assert "rex" in sharing.reach(merged, [ADA])   # why a merged view is never used


@pytest.mark.parametrize("seed", range(40))
def test_reach_is_a_down_set_that_keeps_the_reduction(seed):
    """SHARING.md §2.1: whatever is below something shared is shared, so the
    subgraph induced by reach keeps exactly the store's reduced edges."""
    random.seed(seed)
    dag = OntoDAG()
    names = [f"n{i}" for i in range(16)]
    for i, name in enumerate(names):
        dag.put(name, random.sample(names[:i], min(i, random.randint(0, 3))))
    principal = random.choice(names)
    reach = sharing.reach(dag, [principal]) | {principal}
    for name in reach:
        assert {c.name for c in dag.nodes[name].neighbors} <= reach
    sub = dag.induced_subdag(reach)

    def edges(g):
        return {(p.name, n) for n in reach for p in g.nodes[n].parents
                if g.nodes.get(p.name) is p and p.name in reach}
    assert edges(sub) == edges(dag)


# ---- exclusion (a host's policy: categor.io DESIGN §10) ----------------------

def test_an_excluded_name_is_never_entered():
    dag = acme()
    dag.put("old-note", [ADA])                   # filed before ADA was registered
    dag.put("under-old", ["old-note"])
    dag.put("also-shared", ["old-note", "employee-information"])
    reach = sharing.reach(dag, [ADA], exclude={"old-note"})
    assert "old-note" not in reach and "under-old" not in reach
    assert "also-shared" in reach                # reached through another right


def test_exclusions_can_be_per_principal():
    dag = acme()
    dag.put("note", [ADA, BOB])
    exclude = {ADA: {"note"}}
    assert "note" not in sharing.reach(dag, [ADA], exclude=exclude)
    assert "note" in sharing.reach(dag, [BOB], exclude=exclude)
    assert "note" in sharing.reach(dag, [ADA, BOB], exclude=exclude)


# ---- landing and losses -----------------------------------------------------

def test_landing():
    dag = acme()
    assert sharing.landing(dag, [ADA, HARRY, "nobody@categor.io"]) == {
        ADA: ["employees"], HARRY: ["sales"]}   # employees ⊑ harry was pruned: implied via sales


def test_losses_are_per_principal():
    before = acme()
    after = acme()
    after.reclassify(["employee-information"], to=(), from_=["employees"])
    assert sharing.losses(before, after, [ADA, BOB, HARRY]) == {
        ADA: ["employee-information", "handbook"],
        BOB: ["employee-information", "handbook"],
        HARRY: ["employee-information", "handbook"]}
    assert sharing.losses(before, before, [ADA]) == {}


def test_a_loss_through_one_right_is_not_a_loss_if_another_remains():
    before = acme()
    after = acme()
    after.reclassify(["employees"], to=(), from_=["sales"])   # sales no longer gets employees
    lost = sharing.losses(before, after, [ADA, HARRY])
    assert ADA not in lost
    # harry keeps employees only if he was a member in his own right; the
    # explicit `employees ⊑ harry` was pruned as implied (SHARING.md Q2)
    assert lost[HARRY] == ["employee-information", "employees", "handbook"]


# ---- any DAG ----------------------------------------------------------------

def test_over_a_stored_dag():
    import ontodag
    from recordstore import MemoryBytesStore, RecordStore
    stored = ontodag.EagerOntoDAG(RecordStore(MemoryBytesStore()))
    stored.merge(acme())
    stored.commit()
    assert sharing.reach(stored, [ADA]) == sharing.reach(acme(), [ADA])


# ---- the CLI ------------------------------------------------------------------

def _run(argv, path):
    import io
    out, err = io.StringIO(), io.StringIO()
    code = dispatch(argv, Session(path), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture()
def store():
    from ontodag import native
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "acme.od")
        native.save(acme(), path)
        yield path


def test_shared_with(store):
    code, out, _ = _run(["shared-with", ADA], store)
    assert code == 0
    assert out.split() == ["employee-information", "employees", "handbook"]


def test_get_and_count_as(store):
    _, out, _ = _run(["get", "document", "--as", ADA], store)
    assert out.split() == ["handbook"]
    _, out, _ = _run(["get", "--as", BOB], store)
    assert "sales-leads" not in out.split() and "merger-plans" not in out.split()
    _, out, _ = _run(["count", "--as", HARRY], store)
    assert out.strip() == "5"
    _, out, _ = _run(["get", "sales", "--as", ADA, "--as", HARRY], store)
    assert out.split() == ["employee-information", "employees", "handbook", "sales-leads"]


def test_as_reads_the_store_alone_never_the_overlays(store, monkeypatch):
    from ontodag import native
    with tempfile.TemporaryDirectory() as tmp:
        overlay = os.path.join(tmp, "machine.od")
        extra = OntoDAG()
        extra.put("employees", [])
        extra.put("scanned-payslips", ["employees"])
        native.save(extra, overlay)
        monkeypatch.setenv("ONTODAG_OVERLAYS", overlay)
        _, plain, _ = _run(["get", "employees"], store)
        _, as_ada, _ = _run(["get", "employees", "--as", ADA], store)
    assert "scanned-payslips" in plain.split()          # the overlay answers `get`...
    assert "scanned-payslips" not in as_ada.split()     # ...but shares nothing


# ---- the wall: reach in time order (WALLS_AND_INBOXES §2) ---------------------

def walls():
    dag = OntoDAG()
    prelude.apply(dag)
    dag.put("posted", ["time"])
    for p in (ADA, BOB, "everyone"):
        dag.put(p, [])
    dag.put("friends", [ADA, BOB])
    dag.put("trip-photos", ["friends", "posted(2026-09-24T10:00:00Z)", "time(2026-08)"])
    dag.put("hello-world", ["everyone", "posted(2026-09-20T08:30:00Z)"])
    dag.put("note-to-ada", [ADA, "posted(2026-09-24T12:15:00Z)"])
    dag.put("draft", ["friends"])                       # no posted time: not on the wall
    dag.put("posted(2026)", [BOB])                      # all of 2026's posts, for Bob
    return dag


def test_a_wall_is_reach_in_posted_order():
    dag = walls()
    assert sharing.timeline(dag, [ADA, "everyone"]) == [
        ("posted(2026-09-20T08:30:00Z)", "hello-world"),
        ("posted(2026-09-24T10:00:00Z)", "trip-photos"),
        ("posted(2026-09-24T12:15:00Z)", "note-to-ada")]
    assert sharing.timeline(dag, ["everyone"]) == [
        ("posted(2026-09-20T08:30:00Z)", "hello-world")]


def test_a_share_of_a_year_brings_its_posts_and_skips_the_values_themselves():
    names = [n for _v, n in sharing.timeline(walls(), [BOB])]
    assert names == ["hello-world", "trip-photos", "note-to-ada"]


def test_about_time_is_not_publish_time():
    dag = walls()
    assert sharing.point_values(dag, "trip-photos", "posted") == ["posted(2026-09-24T10:00:00Z)"]
    assert sharing.timeline(dag, [ADA], role="time") == []   # time(2026-08) is a range
