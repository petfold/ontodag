"""Publish the cone summaries of shipped packs to Swarm, for the read-only page.

    python3 demo/freedom/publish_index.py core physics --batch ID

A broad query over a lazily read store walks its narrowest term's whole
cone (2,509 records for `physical-object` in core); a cone summary states
that membership in one record (`ontodag.cones`, BROWSER.md §4a). For each
pack this rebuilds the pack under Swarm addressing (its root must equal the
pinned one, `tests/test_packs.py` SWARM_GOLDEN_ROOTS), builds the index
into a record store on the Bee node (a separate store with its own root,
deterministic, never part of the pack's identity), and prints the index
root to pin in `app.js` (CONE_INDEXES). A reader whose pack root or
registry version differs ignores the index and walks: slower, never wrong.
"""

import argparse
import ast
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def golden_roots():
    source = open(os.path.join(REPO, "tests", "test_packs.py")).read()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "SWARM_GOLDEN_ROOTS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise SystemExit("SWARM_GOLDEN_ROOTS not found")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("packs", nargs="+")
    ap.add_argument("--api", default=os.environ.get("BEE_API", "http://localhost:1633"))
    ap.add_argument("--batch", default=os.environ.get("BEE_BATCH"))
    args = ap.parse_args()
    if not args.batch:
        sys.exit("publishing needs a postage batch: --batch ID or BEE_BATCH")
    sys.path.insert(0, os.path.join(REPO, "src"))
    from recordstore import BeeBytesStore, DirBytesStore, RecordStore
    import ontodag
    from ontodag.cones import build_index, summarized_names
    from ontodag.packs import apply

    golden = golden_roots()
    for name in args.packs:
        with tempfile.TemporaryDirectory() as d:
            dag = ontodag.EagerOntoDAG(RecordStore(DirBytesStore(d, addressing="swarm")))
            apply(dag, name)
            data_root = dag.commit()
        if data_root != golden.get(name):
            sys.exit(f"{name}: rebuilt root {data_root} is not the pinned {golden.get(name)}")
        index = RecordStore(BeeBytesStore(args.api.rstrip("/"), args.batch))
        index_root = build_index(dag, index, data_root)
        print(f"{name}: data {data_root} index {index_root} "
              f"({len(summarized_names(dag))} summaries)", flush=True)


if __name__ == "__main__":
    main()
