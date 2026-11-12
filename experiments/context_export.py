"""Write a store as a formal context, for FCA's programs and for mdl-fca
(docs/plans/CODES_AND_FACTORS.md, step 1).

    python3 experiments/context_export.py OUT --packs core,geography
    python3 experiments/context_export.py OUT --store rs:~/work/travel
    python3 experiments/context_export.py OUT --packs all --below place

The objects are the store's items: what `get` calls an item, a node with
nothing filed under it that is no typed value. The attributes are the
categories above them, and a cross says the object is below the attribute,
in the order `get` answers by (asserted edges and the computed order of
terms). The root is left out, and so is any other attribute every object
has, since it tells the objects apart no better.

Three files come out:

    OUT.cxt   Burmeister's format, which ConExp and In-Close read
    OUT.npy   the same table as bytes, one row an object (numpy.load)
    OUT.json  what the table was made from and how to check it: the
              source, its knowledge id, the names in order, and the
              store's own edges among them, the reduced graph a learner
              should find

The table is a function of the store's knowledge: a new version of a pack
or a changed store has another knowledge id, and the table is written
again. This script reads the store through `ontodag.open`, `get` and
`get_ancestors`, so it need not change with it.
"""
import argparse
import hashlib
import json
import os
import struct
import sys

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, SRC)

import ontodag  # noqa: E402
from ontodag import dimensions, native, packs, prelude  # noqa: E402
from ontodag.dag import OntoDAG  # noqa: E402

DOMAINS = ["physics", "mathematics", "chemistry", "biology", "medicine", "ai",
           "economics", "computing", "geography", "space"]


def packs_dag(names):
    dag = OntoDAG()
    prelude.apply(dag)
    for name in names:
        dag.merge(packs.adoption_dag(dag, name))
    return dag


def identity(dag):
    """What names this state of the store: its knowledge id where the
    `swarm` extra is installed, and the hash of its canonical text."""
    text = native.dumps(dag)
    found = {"text_sha256": hashlib.sha256(text.encode()).hexdigest()}
    try:
        from ontodag.knowledge import knowledge_id
        found["knowledge_id"] = knowledge_id(dag)
    except Exception as error:          # the extra is missing: say so
        found["knowledge_id"] = None
        found["knowledge_id_missing"] = str(error).splitlines()[0]
    return found


def context(dag, below=None):
    """(objects, attributes, rows, left out) for the items of `dag`, or of
    the cone of `below`; a row is the set of its object's attributes."""
    root = dag.root.name
    objects = sorted(item.name for item in dag.get(
        [below] if below else [], items_only=True))
    rows = []
    for name in objects:
        rows.append({a.name for a in dag.get_ancestors(name)} - {root})
    held = {}
    for row in rows:
        for name in row:
            held[name] = held.get(name, 0) + 1
    by_all = sorted(name for name, n in held.items() if n == len(objects))
    attributes = sorted(name for name, n in held.items() if n < len(objects))
    kept = set(attributes)
    return objects, attributes, [row & kept for row in rows], by_all


def edges(dag, names):
    """The store's own edges among `names`, as [below, above] pairs."""
    names = set(names)
    found = []
    for name in sorted(names):
        node = dag.nodes[name]
        for parent in sorted(p.name for p in node.parents
                             if dag.nodes.get(p.name) is p):
            if parent in names:
                found.append([name, parent])
    return found


def closure(pairs):
    """Every (below, above) pair the edges imply."""
    above = {}
    for low, high in pairs:
        above.setdefault(low, set()).add(high)
    closed = {}
    for start in above:
        seen, stack = set(), [start]
        while stack:
            for high in above.get(stack.pop(), ()):
                if high not in seen:
                    seen.add(high)
                    stack.append(high)
        closed[start] = seen
    return closed


def write_cxt(path, objects, attributes, rows):
    with open(path, "w", encoding="utf-8") as out:
        out.write(f"B\n\n{len(objects)}\n{len(attributes)}\n\n")
        for name in objects:
            out.write(name + "\n")
        for name in attributes:
            out.write(name + "\n")
        for row in rows:
            out.write("".join("X" if a in row else "." for a in attributes)
                      + "\n")


def write_npy(path, objects, attributes, rows):
    """The table as a version 1.0 `.npy` file of unsigned bytes, written
    without numpy so that the base install can make it."""
    header = ("{'descr': '|u1', 'fortran_order': False, "
              f"'shape': ({len(objects)}, {len(attributes)}), }}")
    header += " " * (-(10 + len(header) + 1) % 64) + "\n"
    with open(path, "wb") as out:
        out.write(b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)))
        out.write(header.encode("latin1"))
        for row in rows:
            out.write(bytes(1 if a in row else 0 for a in attributes))


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", help="the path the three files start with")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--store", help="a store, as odag's -f names it")
    source.add_argument("--packs", help="shipped packs, comma-separated, "
                        "or `all` for core and the ten domain packs")
    parser.add_argument("--below", help="only the items below this category")
    args = parser.parse_args(argv)

    if args.packs:
        names = ["core", *DOMAINS] if args.packs == "all" \
            else args.packs.split(",")
        dag, made_from = packs_dag(names), {"packs": names}
    else:
        dag, made_from = ontodag.open(args.store).dag, {"store": args.store}
    if args.below and args.below not in dag.nodes:
        raise SystemExit(f"no category {args.below!r} in the store")

    objects, attributes, rows, by_all = context(dag, args.below)
    if not objects:
        raise SystemExit("no items to write")
    pairs = edges(dag, [*objects, *attributes])
    implied = closure(pairs)
    crosses = sum(len(row) for row in rows)
    by_edges = sum(len(row & implied.get(name, set()))
                   for name, row in zip(objects, rows))
    parents = {}
    for low, high in pairs:
        parents.setdefault(low, set()).add(high)

    write_cxt(args.out + ".cxt", objects, attributes, rows)
    write_npy(args.out + ".npy", objects, attributes, rows)
    with open(args.out + ".json", "w", encoding="utf-8") as out:
        json.dump({
            "made_from": made_from,
            "below": args.below,
            **identity(dag),
            "ontodag": getattr(ontodag, "__version__", None),
            "contract": ontodag.CONTRACT_VERSION,
            "registry": dimensions.REGISTRY_VERSION,
            "objects": objects,
            "attributes": attributes,
            "held_by_every_object": by_all,
            "edges": pairs,
        }, out, indent=1, ensure_ascii=False)
        out.write("\n")

    cells = len(objects) * len(attributes)
    print(f"{len(objects)} objects, {len(attributes)} attributes, "
          f"{crosses} crosses ({100 * crosses / cells:.2f}% of the table), "
          f"{crosses / len(objects):.1f} a row")
    print(f"left out, held by every object: {len(by_all)}"
          + (f" ({', '.join(by_all[:6])}"
             f"{', …' if len(by_all) > 6 else ''})" if by_all else ""))
    print(f"crosses the store's edges imply: {by_edges}; the computed "
          f"order of terms adds {crosses - by_edges}")
    print(f"different rows: {len({frozenset(row) for row in rows})}; "
          f"different parent sets: "
          f"{len({frozenset(parents.get(n, ())) for n in objects})}")
    several = sum(1 for n in attributes if len(parents.get(n, ())) > 1)
    print(f"attributes with several parents among the attributes: "
          f"{several}; edges written: {len(pairs)}")
    for suffix in (".cxt", ".npy", ".json"):
        print(f"  {args.out + suffix}: "
              f"{os.path.getsize(args.out + suffix)} bytes")


if __name__ == "__main__":
    main(sys.argv[1:])
