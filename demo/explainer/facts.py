"""Run the film's examples on the real `odag`, and keep what it answered.

    ../../../.venv/bin/python facts.py

Every command, answer and root the film shows comes from here: the
commands run in a throwaway home, and `out/facts.json` holds their output
for `scenes.py` to draw. The checks at the end are what the pictures and
the narration claim; if a release changes one of them, this stops and the
film has to change with it.
"""

import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The store the film builds, in the order the film builds it.
TRIP = [
    ("Flight", []),
    ("Japan", []),
    ("japan-outbound.pdf", ["Flight", "Japan"]),
    ("boarding-pass.png", ["japan-outbound.pdf"]),
    ("Hotel", []),
    ("hotel-tokyo.pdf", ["Hotel", "Japan"]),
    ("berlin-flight.pdf", ["Flight"]),
]

# The same knowledge filed by someone else: another order, and detours
# (the boarding pass under Japan first; under Flight as well, later).
TRIP_AGAIN = [
    ("Japan", []),
    ("boarding-pass.png", ["Japan"]),
    ("Hotel", []),
    ("hotel-tokyo.pdf", ["Japan", "Hotel"]),
    ("Flight", []),
    ("berlin-flight.pdf", ["Flight"]),
    ("japan-outbound.pdf", ["Japan", "Flight"]),
    ("boarding-pass.png", ["japan-outbound.pdf"]),
    ("boarding-pass.png", ["Flight"]),
]

FLIGHTS = [
    ("berlin-flight.pdf", ["Flight", "time(2026-03-02)"]),
    ("japan-outbound.pdf", ["Flight", "time(2026-08-15)"]),
    ("japan-return.pdf", ["Flight", "time(2026-08-29)"]),
]

PARCELS = [
    ("parcel-a", ["mass(500g)"]),
    ("parcel-b", ["mass(3kg)"]),
    ("parcel-c", ["mass(12kg)"]),
]

# Values of other kinds, each below the one beside it by its name alone.
PAIRS = [
    ("mass(3kg)", "mass(..5kg)"),
    ("length(2m)", "length(1m..3m)"),
    ("size(19x23x39cm)", "size(20x30x40cm)"),
    ("geo(48.8584,2.2945)", "geo(48..49,2..3)"),
]


def main():
    with tempfile.TemporaryDirectory() as home:
        facts = gather(Path(home))
    check(facts)
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    (out / "facts.json").write_text(json.dumps(facts, indent=1))
    print("facts.json:", len(facts), "groups; the trip's root is",
          facts["trip"]["root"][:12])


def gather(home):
    """Run the examples in `home`, an empty directory; what odag answered."""
    import ontodag
    env = dict(os.environ, ONTODAG_HOME=str(home / "home"),
               # the odag that runs is the ontodag that was imported
               PYTHONPATH=os.pathsep.join(filter(None, [
                   str(Path(ontodag.__file__).resolve().parents[1]),
                   os.environ.get("PYTHONPATH")])))
    (home / "home").mkdir()

    def run(store, *args, commands=None):
        done = subprocess.run(
            [sys.executable, "-m", "ontodag", "-f", f"rs:{home / store}",
             *args], env=env, capture_output=True, text=True, input=commands)
        return done.returncode, done.stdout.splitlines(), done.stderr.strip()

    def ask(store, *commands):
        """Give odag several commands down a pipe, as a script would; the
        lines each printed. A marker is echoed between them to part the
        output, and nothing may be said on stderr."""
        lines = []
        for number, command in enumerate(commands):
            lines += [shlex.join(command), f"canon ~cut-{number}~"]
        code, out, err = run(store, commands="\n".join(lines) + "\n")
        assert code == 0 and not err, (store, err)
        answers, current = [], []
        for line in out:
            if line == f"canon ~cut-{len(answers)}~"[6:]:
                answers.append(current)
                current = []
            else:
                current.append(line)
        assert len(answers) == len(commands), (store, out)
        return answers

    def puts(things):
        return [["put", name, *parents] for name, parents in things]

    def root(status):
        return dict(line.split(" = ", 1) for line in status)["root"]

    facts = {}
    pass_ = "boarding-pass.png"

    *_, status, japan, both, both_again, below, _, after = ask(
        "trip", *puts(TRIP), ["status"], ["get", "Japan"],
        ["get", "Flight", "Japan"], ["get", "Japan", "Flight"],
        ["below", pass_, "Japan"],
        ["put", pass_, "Japan"], ["status"])    # a link the others imply
    trip = facts["trip"] = {
        "root": root(status), "get Japan": japan, "get Flight Japan": both,
        "get Japan Flight": both_again, "below": below[0],
        "implied": {"said": "", "root": root(after)}}
    code, _, err = run("trip", "put", "Flight", pass_)      # a loop
    after, _ = ask("trip", ["status"], ["export", str(home / "trip.od")])
    trip["loop"] = {"exit": code, "said": err, "root": root(after)}

    *_, status = ask("again", *puts(TRIP_AGAIN), ["status"])
    facts["again"] = {"root": root(status)}

    # Two writers start from the same store, and each adds something.
    merge = facts["merge"] = {"start": [], "apart": []}
    for writer, thing in (("alice", ("hotel-kyoto.pdf", ["Hotel", "Japan"])),
                          ("bob", ("rail-pass.pdf", ["Japan"]))):
        _, start, _, apart, _ = ask(
            writer, ["merge", str(home / "trip.od")], ["status"],
            *puts([thing]), ["status"],
            ["export", str(home / f"{writer}.od")])
        merge["start"].append(root(start))
        merge["apart"].append(root(apart))
    _, merged, _, again, japan = ask(
        "alice", ["merge", str(home / "bob.od")], ["status"],
        ["merge", str(home / "bob.od")], ["status"], ["get", "Japan"])
    _, other = ask("bob", ["merge", str(home / "alice.od")], ["status"])
    merge.update(merged=[root(merged), root(other)], again=root(again))
    merge["get Japan"] = japan

    summer = "time(2026-06-01..2026-08-31)"
    periods = ("time(2026-08)", summer, "time(2026)")
    *_, found, stored, in_august, in_summer, in_year = ask(
        "flights", ["prelude"], *puts([("Flight", [])] + FLIGHTS),
        ["get", "Flight", summer], ["canon", "time(2026-08-15)"],
        *(["below", "time(2026-08-15)", period] for period in periods))
    facts["flights"] = {
        "summer": summer, "get Flight summer": found,
        "below": dict(zip(periods, (in_august[0], in_summer[0], in_year[0]))),
        "stored": stored[0]}

    spellings = ("mass(500g)", "mass(3kg)", "mass(12kg)", "mass(1lb)")
    answers = ask(
        "parcels", ["prelude"], *puts(PARCELS),
        ["get", "--items-only", "mass(..5kg)"],
        *(["canon", spelling] for spelling in spellings),
        *(["below", below, above] for below, above in PAIRS))
    answers = answers[1 + len(PARCELS):]
    facts["parcels"] = {
        "get mass(..5kg)": answers[0],
        "stored": {spelling: answer[0] for spelling, answer
                   in zip(spellings, answers[1:1 + len(spellings)])}}
    facts["pairs"] = [[below, above, answer[0]] for (below, above), answer
                      in zip(PAIRS, answers[1 + len(spellings):])]

    facts["proof"] = prove()
    return facts


def prove():
    """The certificate of one answer, checked with the root alone."""
    from recordstore import MemoryBytesStore, RecordStore

    import ontodag
    from ontodag.certificates import prove_below, verify_below

    dag = ontodag.EagerOntoDAG(RecordStore(MemoryBytesStore()))
    for name, parents in TRIP:
        dag.put(name, parents)
    root = dag.commit()
    certificate = prove_below(dag, "boarding-pass.png", "Japan")
    return {
        "root": root,
        "result": certificate["result"],
        "records": len(certificate["proofs"]),
        "bytes": len(json.dumps(certificate)),
        "verified": verify_below(certificate, root),
    }


def check(facts):
    trip = facts["trip"]
    assert trip["get Japan"] == [
        "boarding-pass.png", "hotel-tokyo.pdf", "japan-outbound.pdf"], trip
    assert trip["get Flight Japan"] == trip["get Japan Flight"] == [
        "boarding-pass.png", "japan-outbound.pdf"], trip
    assert trip["below"] == "true"
    # a link the others imply changes nothing, and nothing is said of it
    assert trip["implied"] == {"said": "", "root": trip["root"]}
    # a loop is refused, and the store is as it was
    assert trip["loop"]["exit"] == 1 and "cycle" in trip["loop"]["said"]
    assert trip["loop"]["root"] == trip["root"]
    # equal knowledge, equal root
    assert facts["again"]["root"] == trip["root"]
    assert facts["proof"]["root"] == trip["root"]

    merge = facts["merge"]
    assert merge["start"] == [trip["root"]] * 2
    assert len({trip["root"], *merge["apart"]}) == 3
    assert merge["merged"][0] == merge["merged"][1] == merge["again"]
    assert merge["merged"][0] not in merge["apart"]
    assert {"hotel-kyoto.pdf", "rail-pass.pdf"} <= set(merge["get Japan"])

    flights = facts["flights"]
    assert flights["get Flight summer"] == [
        "japan-outbound.pdf", "japan-return.pdf"], flights
    assert set(flights["below"].values()) == {"true"}
    parcels = facts["parcels"]
    assert parcels["get mass(..5kg)"] == ["parcel-a", "parcel-b"], parcels
    assert parcels["stored"]["mass(500g)"] == "mass(1/2kg)"
    # a pound is 0.45359237 kg by definition, and is kept so
    assert parcels["stored"]["mass(1lb)"] == "mass(45359237/100000000kg)"

    assert all(answer == "true" for _, _, answer in facts["pairs"])

    proof = facts["proof"]
    assert proof["result"] is True and proof["verified"] is True


if __name__ == "__main__":
    main()
