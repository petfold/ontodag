import argparse
import sys
import os

from ontodag.dag import OntoDAG, Item, OntoDAGVisualizer
from ontodag.owl import OWLOntology


def _detect_format(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".omn":
        return "manchester"
    return "owl"


def _load(path):
    if _detect_format(path) == "manchester":
        return OWLOntology.import_dag_manchester(file_name=path)
    else:
        return OWLOntology(f"file://{os.path.abspath(path)}").import_dag(file_name=path)


def _save(dag, path):
    if _detect_format(path) == "manchester":
        OWLOntology.export_dag_manchester(dag, path)
    else:
        OWLOntology.export_dag(dag, path)


def _print_dag(dag):
    sorted_nodes = dag.topological_sort()
    for node in sorted_nodes:
        parents = [n.name for n in dag.nodes.values() if node in n.neighbors]
        children = [n.name for n in node.neighbors]
        if node.name == dag.root.name:
            print(f"  {node.name}  [root]  -> {children}")
        else:
            print(f"  {node.name}  (parents: {parents})  -> {children}")


def cmd_show(args):
    dag = _load(args.file)
    print(f"OntoDAG loaded from: {args.file}")
    print(f"Nodes ({len(dag.nodes)}):")
    _print_dag(dag)


def cmd_put(args):
    dag = _load(args.file)
    item = Item(args.item)
    missing = [p for p in args.parents if p not in dag.nodes]
    if missing:
        print(f"Error: parent(s) not found in DAG: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    parents = [dag.nodes[p] for p in args.parents]
    dag.put(item, parents, optimized=args.optimized)
    out = args.output or args.file
    _save(dag, out)
    parent_str = ", ".join(args.parents) if args.parents else "*"
    print(f"Added '{args.item}' under [{parent_str}] -> saved to {out}")


def cmd_get(args):
    dag = _load(args.file)
    missing = [p for p in args.parents if p not in dag.nodes]
    if missing:
        print(f"Error: category/ies not found in DAG: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    categories = [dag.nodes[p] for p in args.parents]
    results = dag.get(categories)
    if results:
        print(f"Subcategories of [{', '.join(args.parents)}]:")
        for item in sorted(results, key=lambda i: i.name):
            print(f"  {item.name}")
    else:
        print(f"No subcategories found for [{', '.join(args.parents)}]")


def cmd_remove(args):
    dag = _load(args.file)
    if args.item not in dag.nodes:
        print(f"Error: '{args.item}' not found in DAG", file=sys.stderr)
        sys.exit(1)
    dag.remove(dag.nodes[args.item])
    out = args.output or args.file
    _save(dag, out)
    print(f"Removed '{args.item}' -> saved to {out}")


def cmd_merge(args):
    dag1 = _load(args.file1)
    dag2 = _load(args.file2)
    dag1.merge(dag2)
    out = args.output or args.file1
    _save(dag1, out)
    print(f"Merged '{args.file2}' into '{args.file1}' -> saved to {out}")


def cmd_export(args):
    dag = _load(args.file)
    out = args.output
    fmt = args.format or _detect_format(out)
    if fmt == "manchester":
        OWLOntology.export_dag_manchester(dag, out)
    else:
        OWLOntology.export_dag(dag, out)
    print(f"Exported to {out} (format: {fmt})")


def cmd_visualize(args):
    dag = _load(args.file)
    out = args.output or os.path.splitext(args.file)[0]
    viz = OntoDAGVisualizer(format=args.format)
    viz.visualize(dag, filename=out)


def main():
    parser = argparse.ArgumentParser(
        prog="ontodag",
        description="Load and manipulate OntoDAG instances from the terminal.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # show
    p_show = sub.add_parser("show", help="Display nodes and edges of a DAG file")
    p_show.add_argument("file", help="OWL (.owl) or Manchester (.omn) file")
    p_show.set_defaults(func=cmd_show)

    # put
    p_put = sub.add_parser("put", help="Add an item to a DAG")
    p_put.add_argument("file", help="OWL or Manchester file to modify")
    p_put.add_argument("item", help="Name of the item to add")
    p_put.add_argument("parents", nargs="*", help="Parent category names (omit for root)")
    p_put.add_argument("--optimized", action="store_true", help="Use optimized put (infers most-specific parents)")
    p_put.add_argument("--output", "-o", help="Output file (default: overwrite input)")
    p_put.set_defaults(func=cmd_put)

    # get
    p_get = sub.add_parser("get", help="Query common subcategories")
    p_get.add_argument("file", help="OWL or Manchester file")
    p_get.add_argument("parents", nargs="+", help="Parent category names to intersect")
    p_get.set_defaults(func=cmd_get)

    # remove
    p_remove = sub.add_parser("remove", help="Remove an item from a DAG")
    p_remove.add_argument("file", help="OWL or Manchester file to modify")
    p_remove.add_argument("item", help="Name of the item to remove")
    p_remove.add_argument("--output", "-o", help="Output file (default: overwrite input)")
    p_remove.set_defaults(func=cmd_remove)

    # merge
    p_merge = sub.add_parser("merge", help="Merge two DAG files")
    p_merge.add_argument("file1", help="Base DAG file (modified in place unless --output given)")
    p_merge.add_argument("file2", help="DAG file to merge into file1")
    p_merge.add_argument("--output", "-o", help="Output file (default: overwrite file1)")
    p_merge.set_defaults(func=cmd_merge)

    # export
    p_export = sub.add_parser("export", help="Convert a DAG to a different OWL format")
    p_export.add_argument("file", help="Source OWL or Manchester file")
    p_export.add_argument("--output", "-o", required=True, help="Output file path")
    p_export.add_argument("--format", choices=["owl", "manchester"], help="Output format (inferred from extension if omitted)")
    p_export.set_defaults(func=cmd_export)

    # visualize
    p_vis = sub.add_parser("visualize", help="Render a DAG to an image")
    p_vis.add_argument("file", help="OWL or Manchester file")
    p_vis.add_argument("--output", "-o", help="Output filename without extension (default: input filename)")
    p_vis.add_argument("--format", default="png", choices=["png", "svg", "pdf"], help="Image format (default: png)")
    p_vis.set_defaults(func=cmd_visualize)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
