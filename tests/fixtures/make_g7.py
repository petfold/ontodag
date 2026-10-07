"""Build tests/fixtures/g7.od and g7-answers.json (CONTRACT.md G7).

The answers are a record of what this store answered under contract 0.3 /
registry 4.3, and G7 promises every true answer stays true within the same
majors. So NEVER rerun this to make a failing test pass: a failure means a
release takes an answer away, which is a major bump. Rerun it only after a
major bump, deliberately, and say so in the commit.
"""
import itertools, json, sys
import os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))
from ontodag import OntoDAG, native, prelude, CONTRACT_VERSION
from ontodag.dimensions import REGISTRY_VERSION

d = OntoDAG()
prelude.apply(d)
for name, parents in [
    ("document", []), ("ticket", ["document"]), ("plane-ticket", ["ticket"]),
    ("place", []), ("japan", ["place"]), ("tokyo", ["place"]), ("louvre", ["place"]),
    ("denon-wing", ["place"]),
    ("tokyo", ["in(japan)"]), ("denon-wing", ["in(louvre)"]),
    ("mona-lisa", ["in(denon-wing)"]),
    ("person", []), ("employee", ["person"]), ("sales-employee", ["employee"]),
    ("alice", ["sales-employee"]),
    ("handbook", ["document", "shared-with(employee)"]),
    ("trip.pdf", ["plane-ticket", "about(tokyo)", "time(2026-08-15)"]),
    ("crate", ["mass(3kg)", "size(20x30x40cm)"]), ("bouquet", ["count(5)"]),
    ("photo.jpg", ["geo(u2ed4)", "about(japan)"]),
    ("small-item", []), ("bicycle", ["small-item"]),
    ("graph-dimension", ["dimension"]), ("transport", ["graph-dimension"]),
    ("courier", ["transport(small-item mass(..8kg))"]),
    ("located-at", ["in"]), ("statue", ["located-at(louvre)"]),
    ("from", ["geo"]), ("delivery", ["from(u2ed)"]),
]:
    d.put(name, parents)

names = sorted(n for n in d.nodes if n != "*")
probes = sorted(set(names) | {
    "mass(..5kg)", "time(2026)", "geo(u2e)", "count(2..)", "size(25x35x45cm)",
    "in(japan)", "in(louvre)", "about(japan)", "shared-with(alice)",
    "transport(bicycle mass(5kg))", "from(u2e)", "located-at(louvre)"})
below = sorted([a, b] for a in names for b in probes
               if a != b and d.is_below(a, b))
queries = [[], ["document"], ["in(japan)"], ["in(louvre)"], ["about(japan)"],
           ["shared-with(alice)"], ["mass(..5kg)"], ["time(2026)"], ["geo(u2e)"],
           ["count(2..)"], ["size(25x35x45cm)"], ["document", "about(japan)"],
           ["from(u2e)"], ["transport(small-item)"]]
gets = [{"terms": q, "answer": sorted(n.name for n in d.get(q))} for q in queries]
native.save(d, os.path.join(HERE, "g7.od"))
lines = ['{', f' "contract": "{CONTRACT_VERSION}",', f' "registry": "{REGISTRY_VERSION}",', ' "below": [']
lines += [f'  {json.dumps(x)},' for x in below]; lines[-1] = lines[-1].rstrip(',')
lines += [' ],', ' "get": [']
lines += [f'  {json.dumps(g)},' for g in gets]; lines[-1] = lines[-1].rstrip(',')
lines += [' ]', '}']
open(os.path.join(HERE, "g7-answers.json"), "w").write("\n".join(lines) + "\n")
print(len(names), "names,", len(below), "true below answers,", len(gets), "queries")
