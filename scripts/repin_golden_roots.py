"""Recompute the shipped packs' golden roots and rewrite them in
tests/test_packs.py.

A golden root pins what everyone adopting a pack converges on, so it may
move only deliberately: when the prelude, core or a pack changes. This
script is that deliberate step. It prints old -> new for every root it
changes, and rewrites nothing else.

    python3 scripts/repin_golden_roots.py            # sha256 roots (fast)
    python3 scripts/repin_golden_roots.py --swarm    # also the BMT roots
    python3 scripts/repin_golden_roots.py --union    # also core + all ten (minutes)

Run from the repo root. The BMT roots need the swarm addressing extra.
"""

import argparse
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))

from recordstore import MemoryBytesStore, RecordStore  # noqa: E402

import ontodag  # noqa: E402
from ontodag.packs import apply  # noqa: E402

TESTS = os.path.join(os.path.dirname(__file__), "..", "tests", "test_packs.py")


def root(name, blobs):
    dag = ontodag.EagerOntoDAG(RecordStore(blobs))
    apply(dag, name)
    return dag.commit()


def rewrite(source, table, roots):
    """Replace each pack's hash inside `table = { ... }`."""
    start = source.index(f"{table} = {{")
    end = source.index("\n}\n", start)
    body = source[start:end]
    for name, new in roots.items():
        pattern = re.compile(rf'("{re.escape(name)}":[^\n]*\n\s*")([0-9a-f]{{64}})(")')
        match = pattern.search(body)
        if match is None:
            raise SystemExit(f"{table}: no entry for {name!r}")
        if match.group(2) != new:
            print(f"{table}[{name}]: {match.group(2)[:12]}… -> {new[:12]}…")
            body = body[:match.start(2)] + new + body[match.end(2):]
    return source[:start] + body + source[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--swarm", action="store_true")
    parser.add_argument("--union", action="store_true")
    args = parser.parse_args()

    import test_packs
    source = open(TESTS).read()
    roots = {name: root(name, MemoryBytesStore()) for name in test_packs.GOLDEN_ROOTS}
    source = rewrite(source, "GOLDEN_ROOTS", roots)
    if args.swarm:
        from recordstore import DirBytesStore
        swarm = {}
        for name in test_packs.SWARM_GOLDEN_ROOTS:
            with tempfile.TemporaryDirectory() as d:
                swarm[name] = root(name, DirBytesStore(d, addressing="swarm"))
        source = rewrite(source, "SWARM_GOLDEN_ROOTS", swarm)
    if args.union:
        dag = ontodag.EagerOntoDAG(RecordStore(MemoryBytesStore()))
        apply(dag, "core")
        for name in test_packs.DOMAIN_PACKS:
            apply(dag, name)
        new = dag.commit()
        old = re.search(r'UNION_ROOT = \([^\n]*\n\s*"([0-9a-f]{64})"\)', source)
        if old.group(1) != new:
            print(f"UNION_ROOT: {old.group(1)[:12]}… -> {new[:12]}… "
                  f"({len(dag.nodes) - 1} categories)")
            source = source.replace(old.group(1), new)
    open(TESTS, "w").write(source)


if __name__ == "__main__":
    main()
