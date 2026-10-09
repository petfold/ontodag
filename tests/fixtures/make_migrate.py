"""Build tests/fixtures/migrate-in.od and migrate-out.od: what `ontodag.migrate`
writes, byte for byte, for one hand-shaped legacy store.

migrate-in.od is a store as an older release or a hand edit leaves it: no
canonical mark, values in old spellings (`mass(3000g)`), node metadata, an
item under two overlapping values of one head, a graph-kind compound
stored folded, a role term naming a cell. migrate-out.od is what
`migrate_native` makes of it. tests/test_migrate.py checks the bytes.

Rerun this only together with a deliberate change to what `migrate`
writes (a registry minor's migrate step, CONTRACT.md G8), and let the diff
of migrate-out.od be the review of that change.
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))
from ontodag import OntoDAG, migrate, native, prelude  # noqa: E402

LEGACY = [   # (canonical spelling the store holds, how the legacy file spells it)
    ("'mass(3kg)'", "'mass(3000g)'"),
    ("'duration(5400s)'", "'duration(90min)'"),
]


def legacy_text():
    d = OntoDAG()
    prelude.apply(d)
    for name, parents in [
        ("parcel", ["mass(3kg)"]), ("lesson", ["duration(5400s)"]),
        ("small-item", []), ("graph-dimension", ["dimension"]),
        ("transport", ["graph-dimension"]),
        ("from", ["geo"]), ("delivery", ["from(u2ed4)"]),
    ]:
        d.put(name, parents)
    d.nodes["parcel"].metadata["label"] = "Parcel 7"
    text = native.dumps(d)
    lines = [line for line in text.splitlines() if not line.startswith("#:canonical")]
    # an item under two overlapping values, as a merge stored it before 4.4
    lines += ["'mass(..5kg)' mass", "'mass(2kg..)' mass",
              "crate 'mass(..5kg)' 'mass(2kg..)'"]
    # a graph-kind compound as releases before 0.30.6 stored it, folded
    lines.append("courier 'transport(small-item mass(..8kg))'")
    text = "\n".join(lines) + "\n"
    for canonical, old in LEGACY:
        assert canonical in text, canonical
        text = text.replace(canonical, old)
    return text


if __name__ == "__main__":
    text = legacy_text()
    with open(os.path.join(HERE, "migrate-in.od"), "w") as f:
        f.write(text)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "store.od")
        shutil.copy(os.path.join(HERE, "migrate-in.od"), path)
        migrate.migrate_native(path)
        shutil.copy(path, os.path.join(HERE, "migrate-out.od"))
    print("migrate-in.od and migrate-out.od written")
