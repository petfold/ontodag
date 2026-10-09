"""Build tests/fixtures/g7b.od and g7b-answers.json, G7's second record.

Recorded under contract 0.5 / registry 4.3, before the 2026-10 review's
decided changes were built (a merge that folds overlapping values, a cell
in a role written `geo(...)`, a same-named category outside a role's
dimension), to hold those changes to G7: within one major, a newer ontodag
never takes away an answer about a fixed store. It holds what g7.od lacks:
graph-kind compounds filed as their parts, relation compounds, role terms
naming cells and places, and an item a merge left under two overlapping
values of one head.

The same rule as make_g7.py: NEVER rerun this to make a failing test pass.
A failure means a release takes an answer away, which is a major bump;
rerun it only after one, deliberately, and say so in the commit.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))
from ontodag import OntoDAG, native, prelude, CONTRACT_VERSION  # noqa: E402
from ontodag.dimensions import REGISTRY_VERSION  # noqa: E402

FILINGS = [
    ("document", []), ("guide", ["document"]), ("plan", ["document"]),
    ("place", []), ("europe", ["place"]), ("france", ["place"]),
    ("paris", ["place"]), ("louvre", ["place"]), ("garden", ["place"]),
    ("japan", ["place"]), ("tokyo", ["place"]),
    ("france", ["in(europe)"]), ("paris", ["in(france)"]),
    ("louvre", ["in(paris)"]), ("tokyo", ["in(japan)"]),
    ("mona-lisa", ["in(louvre)"]), ("statue", ["in(louvre garden)"]),
    ("person", []), ("employee", ["person"]),
    ("sales-employee", ["employee"]), ("alice", ["sales-employee"]),
    ("bob", ["employee"]),
    ("handbook", ["document", "shared-with(employee)"]),
    ("memo", ["document", "shared-with(alice bob)"]),
    ("guide", ["about(louvre tokyo)"]), ("plan", ["about(paris)"]),
    ("small-item", []), ("bicycle", ["small-item"]), ("fragile", []),
    ("graph-dimension", ["dimension"]), ("transport", ["graph-dimension"]),
    ("courier", ["transport(small-item mass(..8kg))"]),
    ("mover", ["transport(bicycle fragile)"]),
    ("from", ["geo"]), ("to", ["geo"]), ("home", ["geo(u2ed4x)"]),
    ("delivery", ["from(u2ed4)", "to(home)"]), ("parcel", ["from(u2e)"]),
    ("bouquet", ["count(5)"]), ("trip", ["time(2026-08-15)"]),
]

# Filed by two writers and merged, so the item keeps both values of one
# head where a single writer's `put` would have filed it under their meet.
PEERS = [
    [("crate", ["mass(..5kg)"]), ("festival", ["time(2026-08)"])],
    [("crate", ["mass(2kg..)"]), ("festival", ["time(2026-08-10..2026-09-20)"])],
]

PROBES = {
    "mass(2kg..5kg)", "mass(..6kg)", "mass(..5kg)", "mass(2kg..)",
    "in(france)", "in(europe)", "in(paris)", "in(louvre)", "in(garden)",
    "about(louvre)", "about(tokyo)", "about(france)", "shared-with(alice)",
    "shared-with(bob)", "transport(bicycle)", "transport(small-item)",
    "transport(mass(5kg))", "from(u2e)", "from(u2ed)", "to(u2ed4x)",
    "to(u2e)", "geo(u2ed)", "time(2026)", "time(2026-08)",
    "time(2026-08-15..2026-08-20)", "count(2..)",
}

QUERIES = [
    [], ["document"], ["in(france)"], ["in(europe)"], ["in(louvre)"],
    ["about(tokyo)"], ["about(france)"], ["shared-with(alice)"],
    ["transport(bicycle)"], ["transport(small-item)"], ["mass(..5kg)"],
    ["mass(2kg..5kg)"], ["from(u2e)"], ["to(u2ed4x)"],
    ["document", "about(louvre)"], ["time(2026)"],
    ["time(2026-08-15..2026-08-20)"],
]


def build():
    d = OntoDAG()
    prelude.apply(d)
    for name, parents in FILINGS:
        d.put(name, parents)
    for filings in PEERS:
        peer = OntoDAG()
        prelude.apply(peer)
        for name, parents in filings:
            peer.put(name, parents)
        d.merge(peer)
    return d


if __name__ == "__main__":
    d = build()
    names = sorted(n for n in d.nodes if n != "*")
    probes = sorted(set(names) | PROBES)
    below = sorted([a, b] for a in names for b in probes
                   if a != b and d.is_below(a, b))
    gets = [{"terms": q, "answer": sorted(n.name for n in d.get(q))}
            for q in QUERIES]
    native.save(d, os.path.join(HERE, "g7b.od"))
    lines = ["{", f' "contract": "{CONTRACT_VERSION}",',
             f' "registry": "{REGISTRY_VERSION}",', ' "below": [']
    lines += [f"  {json.dumps(x)}," for x in below]
    lines[-1] = lines[-1].rstrip(",")
    lines += [" ],", ' "get": [']
    lines += [f"  {json.dumps(g)}," for g in gets]
    lines[-1] = lines[-1].rstrip(",")
    lines += [" ]", "}"]
    with open(os.path.join(HERE, "g7b-answers.json"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print(len(names), "names,", len(below), "true below answers,",
          len(gets), "queries")
