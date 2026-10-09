"""Build tests/fixtures/g8-spellings.json (CONTRACT.md G8, signalled spellings).

G8 promises that a valid name's canonical spelling, and what a given set of
filings stores, change only together with REGISTRY_VERSION's minor. The
record holds a fixed set of filings over every kind, the canonical spelling
of inputs over every kind in the store they make, and the stored form of the
filings (the store's native lines, the prelude's own left out).

Rerun this ONLY together with a registry bump, and say in the CHANGELOG what
changed and which `ontodag.migrate` step brings an older store along. Never
rerun it to make a failing test pass without bumping: that failure is a
spelling or stored form changing silently, which is what G8 forbids.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))
from ontodag import CONTRACT_VERSION, OntoDAG, native, prelude  # noqa: E402
from ontodag.dimensions import REGISTRY_VERSION  # noqa: E402
from ontodag.surface import elaborate  # noqa: E402

FILINGS = [
    ("document", []), ("ticket", ["document"]),
    ("place", []), ("japan", ["place"]), ("tokyo", ["place", "in(japan)"]),
    ("paris", ["place"]), ("museum-district", ["place"]),
    ("gallery", ["in(museum-district paris)"]),
    ("person", []), ("employee", ["person"]),
    ("sales-employee", ["employee"]),
    ("plan", ["shared-with(employee sales-employee)"]),
    ("trip.pdf", ["ticket", "about(tokyo)", "time(2026-08-15)"]),
    ("parcel", ["mass(500g)", "size(20x30x40cm)"]),
    ("box", ["mass(1kg..5kg)", "mass(2kg..8kg)"]),
    ("bouquet", ["count(2dz)"]),
    ("photo.jpg", ["geo(u2ed4)", "about(japan)"]),
    ("small-item", []), ("bicycle", ["small-item"]), ("fragile", []),
    ("graph-dimension", ["dimension"]), ("transport", ["graph-dimension"]),
    ("job", ["transport(bicycle fragile)"]),
    ("courier", ["transport(small-item mass(..8kg))"]),
    ("located-at", ["in"]), ("statue", ["located-at(tokyo)"]),
    ("from", ["geo"]), ("delivery", ["from(u2ed)"]),
    ("ring", ["in(in(japan))"]),
]

INPUTS = [
    "mass(500g)", "mass(1.5kg)", "mass(3lb)", "mass(1kg..2000g)",
    "mass(..5kg)", "mass(2kg..)", "mass(1/2kg)",
    "length(1in)", "length(1ft..2m)", "length(10/33m)", "length(5mi)",
    "area(1ha)", "volume(1L)", "volume(2gal)", "speed(100kmh)",
    "pressure(32psi)",
    "energy(1kWh)", "temperature(24C)", "temperature(-40F)",
    "temperature(0C..100C)", "duration(90min)", "duration(1h..2h)",
    "duration(1d)",
    "time(2026)", "time(2026-10)", "time(2026-10-09)",
    "time(2026-10-09T12:00:00Z)", "time(2026-10-09T12:00:00Z..)",
    "time(..2026)",
    "count(2dz)", "count(..5)", "count(3..)",
    "geo(u2e4)", "geo(u2ed4)", "size(20x30x40cm)",
    "transport(fragile bicycle)", "transport(small-item bicycle)",
    "transport(mass(..8kg) small-item)",
    "in(paris museum-district)", "in(japan)", "in(in(japan))",
    "about(tokyo japan)", "shared-with(sales-employee employee)",
    "shared-with(person)", "located-at(tokyo)", "from(u2ed)",
]


def build():
    dag = OntoDAG()
    prelude.apply(dag)
    for name, parents in FILINGS:
        dag.put(name, parents)
    return dag


def stored_lines(dag):
    """The store's native lines for every name the prelude does not hold."""
    own = set(prelude.prelude_dag().nodes)
    return [line for line in native.dumps(dag).splitlines()[1:]
            if line.split()[0].strip("'") not in own
            and not line.startswith("#:meta")]


if __name__ == "__main__":
    dag = build()
    record = {
        "contract": CONTRACT_VERSION,
        "registry": REGISTRY_VERSION,
        "filings": FILINGS,
        "spellings": [[term, elaborate(term, dag)] for term in INPUTS],
        "stored": stored_lines(dag),
    }
    with open(os.path.join(HERE, "g8-spellings.json"), "w") as fh:
        json.dump(record, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(len(FILINGS), "filings,", len(INPUTS), "spellings,",
          len(record["stored"]), "stored lines, registry", REGISTRY_VERSION)
