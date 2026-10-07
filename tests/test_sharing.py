"""ontodag.sharing — what one store shows another (docs/plans/SHARING.md).

Since 0.30 a reader sees what is below `shared-with(reader)` (ROLES.md §8
items 18 and 20): people and groups are ordered by kinds, and a share is
filed under an audience term. The scenarios are categor.io's Acme, restated
in that model.
"""

import os
import random
import tempfile

import pytest

from ontodag import prelude, sharing
from ontodag.__main__ import Session, dispatch
from ontodag.dag import OntoDAG

ADA, BOB, HARRY = "ada@categor.io", "bob@categor.io", "harry@categor.io"


def audience(dag=None):
    dag = dag if dag is not None else OntoDAG()
    dag.put("dimension", [])
    dag.put("reversed-dimension", ["dimension"])
    dag.put("shared-with", ["reversed-dimension"])
    return dag


def sw(name):
    return f"shared-with({name})"


def acme():
    """Acme's store: three employees, Harry also in sales; the employee
    information shared with every employee, the sales leads with sales."""
    dag = audience()
    for name, parents in [
            ("acme-employee", []), ("sales-employee", ["acme-employee"]),
            (ADA, ["acme-employee"]), (BOB, ["acme-employee"]),
            (HARRY, ["sales-employee"]), ("document", []), ("merger-plans", []),
            ("employee-information", [sw("acme-employee"), "merger-plans"]),
            ("handbook", ["employee-information", "document"]),
            ("sales-leads", [sw("sales-employee")])]:
        dag.put(name, parents)
    return dag


EMPLOYEE = {sw("acme-employee"), "employee-information", "handbook"}
SALES = {sw("sales-employee"), "sales-leads"}


# ---- the rule ----------------------------------------------------------------

def test_what_each_reader_sees():
    dag = acme()
    assert sharing.reach(dag, [ADA]) == EMPLOYEE
    assert sharing.reach(dag, [HARRY]) == EMPLOYEE | SALES


def test_parents_stay_closed():
    reach = sharing.reach(acme(), [ADA])
    assert "merger-plans" not in reach and "document" not in reach


def test_members_do_not_see_each_other():
    reach = sharing.reach(acme(), [ADA])
    assert BOB not in reach and HARRY not in reach and ADA not in reach


def test_a_group_is_a_principal_too():
    assert sharing.reach(acme(), ["sales-employee"]) == EMPLOYEE | SALES - {sw("sales-employee")}


def test_several_principals_unite():
    dag = acme()
    assert sharing.reach(dag, [ADA, HARRY]) == sharing.reach(dag, [HARRY])


def test_an_unknown_principal_sees_nothing():
    assert sharing.reach(acme(), ["nobody@categor.io"]) == frozenset()


def test_without_the_audience_head_nothing_is_shared():
    dag = OntoDAG()
    dag.put(ADA, [])
    dag.put("note", [ADA])                   # the pre-0.30 model: no longer a share
    assert sharing.reach(dag, [ADA]) == frozenset()


def test_reach_is_is_below():
    dag = acme()
    dag.put("note-to-ada", [sw(ADA)])        # the term present, beside group shares
    for principal in (ADA, BOB, HARRY):
        reach = sharing.reach(dag, [principal])
        for name in dag.nodes:
            assert (name in reach) == (dag.is_below(name, sw(principal))
                                       and name != sw(principal)), (principal, name)


def test_typed_values_follow_the_combined_order():
    """A value filed under an audience term shares what is filed at values
    inside it, with no edge stored between them — the order `get` uses."""
    dag = audience(OntoDAG())
    prelude.apply(dag)
    dag.put(ADA, [])
    dag.put("time(2026)", [sw(ADA)])
    dag.put("trip", ["time(2026-08)"])
    assert "trip" in sharing.reach(dag, [ADA])


def test_classifying_in_another_store_shares_nothing():
    """The rule reads one store. Bob's `rex ⊑ dog` is not in Acme's store,
    so nothing Acme shares under `dog` reaches `rex` — whereas merging the
    two stores first would."""
    dag = acme()
    dag.put("dog", [sw("acme-employee")])
    bobs = OntoDAG()
    bobs.put("dog", [])
    bobs.put("rex", ["dog"])
    assert "rex" not in sharing.reach(dag, [ADA])
    merged = acme()
    merged.put("dog", [sw("acme-employee")])
    merged.merge(bobs)
    assert "rex" in sharing.reach(merged, [ADA])   # why a merged view is never used


@pytest.mark.parametrize("seed", range(40))
def test_reach_is_a_down_set_that_keeps_the_reduction(seed):
    """SHARING.md §2.1: whatever is below something shared is shared, so the
    subgraph induced by reach keeps exactly the store's reduced edges."""
    random.seed(seed)
    dag = audience()
    names = [f"n{i}" for i in range(16)]
    for i, name in enumerate(names):
        dag.put(name, random.sample(names[:i], min(i, random.randint(0, 3))))
    principal = random.choice(names)
    for name in random.sample(names, 3):
        if name != principal and not dag.is_below(principal, name):
            dag.put(name, [sw(principal)])
    reach = sharing.reach(dag, [principal])
    for name in reach:
        assert {c.name for c in dag.nodes[name].neighbors} <= reach
    sub = dag.induced_subdag(reach)

    def edges(g):
        return {(p.name, n) for n in reach for p in g.nodes[n].parents
                if g.nodes.get(p.name) is p and p.name in reach}
    assert edges(sub) == edges(dag)


# ---- exclusion (a host's policy) ----------------------------------------------

def test_an_excluded_name_is_never_entered():
    dag = acme()
    dag.put("old-note", [sw(ADA)])
    dag.put("under-old", ["old-note"])
    dag.put("also-shared", ["old-note", "employee-information"])
    reach = sharing.reach(dag, [ADA], exclude={"old-note"})
    assert "old-note" not in reach and "under-old" not in reach
    assert "also-shared" in reach                # reached through another right


def test_exclusions_can_be_per_principal():
    dag = acme()
    dag.put("note", [sw(ADA), sw(BOB)])
    exclude = {ADA: {"note"}}
    assert "note" not in sharing.reach(dag, [ADA], exclude=exclude)
    assert "note" in sharing.reach(dag, [BOB], exclude=exclude)
    assert "note" in sharing.reach(dag, [ADA, BOB], exclude=exclude)


# ---- landing and losses -----------------------------------------------------

def test_landing():
    dag = acme()
    dag.put("note-to-ada", [sw(ADA)])
    assert sharing.landing(dag, [ADA, HARRY, "nobody@categor.io"]) == {
        ADA: ["note-to-ada"]}                    # Harry's shares land on his groups
    assert sharing.landing(dag, ["sales-employee"]) == {"sales-employee": ["sales-leads"]}


def test_losses_are_per_principal():
    before = acme()
    after = acme()
    after.reclassify(["employee-information"], to=(), from_=[sw("acme-employee")])
    assert sharing.losses(before, after, [ADA, BOB, HARRY]) == {
        ADA: ["employee-information", "handbook"],
        BOB: ["employee-information", "handbook"],
        HARRY: ["employee-information", "handbook"]}
    assert sharing.losses(before, before, [ADA]) == {}


def test_leaving_a_group_loses_its_shares():
    before = acme()
    after = acme()
    after.reclassify([HARRY], to=["acme-employee"], from_=["sales-employee"])
    assert sharing.losses(before, after, [ADA, HARRY]) == {
        HARRY: sorted(SALES)}


# ---- any DAG ----------------------------------------------------------------

def test_over_a_stored_dag():
    import ontodag
    from recordstore import MemoryBytesStore, RecordStore
    stored = ontodag.EagerOntoDAG(RecordStore(MemoryBytesStore()))
    stored.merge(acme())
    stored.commit()
    assert sharing.reach(stored, [ADA]) == sharing.reach(acme(), [ADA])


def test_over_a_lazy_reader():
    import ontodag
    from recordstore import MemoryBytesStore, RecordStore
    blobs = MemoryBytesStore()
    stored = ontodag.EagerOntoDAG(RecordStore(blobs))
    stored.merge(acme())
    root = stored.commit()
    lazy = ontodag.LazyOntoDAG(RecordStore.at(root, blobs))
    assert sharing.reach(lazy, [HARRY]) == sharing.reach(acme(), [HARRY])


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
    assert out.split() == ["employee-information", "handbook", sw("acme-employee")]


def test_get_and_count_as(store):
    _, out, _ = _run(["get", "document", "--as", ADA], store)
    assert out.split() == ["handbook"]
    _, out, _ = _run(["get", "--as", BOB], store)
    assert "sales-leads" not in out.split() and "merger-plans" not in out.split()
    _, out, _ = _run(["count", "--as", HARRY], store)
    assert out.strip() == "5"
    # what is shared with every employee is shared with sales employees too
    _, out, _ = _run(["get", sw("sales-employee"), "--as", ADA, "--as", HARRY], store)
    assert out.split() == ["employee-information", "handbook", "sales-leads",
                           sw("acme-employee")]
    _, out, _ = _run(["get", sw("sales-employee"), "--as", ADA], store)
    assert "sales-leads" not in out.split()


def test_as_reads_the_store_alone_never_the_overlays(store, monkeypatch):
    from ontodag import native
    with tempfile.TemporaryDirectory() as tmp:
        overlay = os.path.join(tmp, "machine.od")
        extra = OntoDAG()
        extra.put("employee-information", [])
        extra.put("scanned-payslips", ["employee-information"])
        native.save(extra, overlay)
        monkeypatch.setenv("ONTODAG_OVERLAYS", overlay)
        _, plain, _ = _run(["get", "employee-information"], store)
        _, as_ada, _ = _run(["get", "employee-information", "--as", ADA], store)
    assert "scanned-payslips" in plain.split()          # the overlay answers `get`...
    assert "scanned-payslips" not in as_ada.split()     # ...but shares nothing
