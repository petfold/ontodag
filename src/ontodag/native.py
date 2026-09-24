"""The native store format, as text: `loads(text)` and `dumps(dag)`.

One line per node, `name parent1 parent2 ...` (shell-quoted), under a
`# ontodag store v1` header, plus a `#:meta <name> <json>` line for each node
carrying metadata. The format is canonical — nodes, parents and metadata
keys sorted — so equal knowledge gives equal bytes, and the graph is rebuilt
through `add_edge`, so even a hand-edited, non-reduced file loads as its
unique transitive reduction.

This is what `odag` reads and writes for a `.od` store. It is public so that
a program embedding OntoDAG — a web app, a sync tool — can move stores as
text without a file on disk or a reach into the CLI module. Standard library
only (B1).
"""

import json
import os
import shlex

from ontodag.dag import Item, OntoDAG

HEADER = "# ontodag store v1"

# Node metadata rides on a comment line, which is what makes the extension
# safe in both directions. Readers released before it existed skip every line
# starting with `#`, so they read a metadata-bearing file exactly as they read
# one without: edges only, nothing corrupted. Putting the annotation on the
# node's own line instead — `name parent1 | {...}` — would have every existing
# reader take the JSON for a list of parent names and invent nodes from it.
# The file therefore stays a valid v1 store and the header does not move: the
# edge grammar is unchanged, and metadata is optional enrichment.
META_LINE = "#:meta"


def loads(text, source="<text>"):
    """`.od` text -> OntoDAG. Raises ValueError, naming `source` and the
    line, on a malformed metadata line; the graph's own errors (a cycle)
    propagate as they would from `put`."""
    return _read(text.splitlines(), source)


def dumps(dag):
    """OntoDAG -> canonical `.od` text, ending in a newline."""
    lines = [HEADER]
    for name in sorted(dag.nodes):
        if name == dag.root.name:
            continue
        node = dag.nodes[name]
        if node.metadata:
            # sort_keys so the file is byte-stable; json escapes newlines, so
            # the token cannot break the line-oriented parse whatever a label
            # contains.
            blob = json.dumps(node.metadata, sort_keys=True, ensure_ascii=False)
            lines.append(f"{META_LINE} {shlex.quote(name)} {shlex.quote(blob)}")
        parents = sorted(
            p.name for p in node.parents if dag.nodes.get(p.name) is p
        )
        lines.append(" ".join(shlex.quote(t) for t in [name] + parents))
    return "\n".join(lines) + "\n"


def load(path):
    """Read a `.od` file. A missing file is an empty DAG (the default store
    need not exist yet)."""
    if not os.path.exists(path):
        return OntoDAG()
    with open(path, encoding="utf-8") as fh:
        return _read(fh, path)


def save(dag, path):
    """Write `dag` to `path` as `.od`."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps(dag))


def _read(lines, source):
    dag = OntoDAG()
    edges = []
    metadata = {}
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        if line.startswith(META_LINE):
            # Strict on purpose: dropping an unreadable annotation is the
            # silent data loss this line type exists to end.
            try:
                _, name, blob = shlex.split(line)
                metadata[name] = json.loads(blob)
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"{source}:{number}: malformed {META_LINE} line ({exc})"
                ) from exc
            continue
        if line.startswith("#"):
            continue
        tokens = shlex.split(line)
        name = tokens[0]
        if name not in dag.nodes:
            dag.add_node(Item(name))
        for parent in tokens[1:]:
            if parent not in dag.nodes:
                dag.add_node(Item(parent))
            edges.append((parent, name))
    for parent, child in edges:
        dag.add_edge(dag.nodes[parent], dag.nodes[child])
    for name, values in metadata.items():
        node = dag.nodes.get(name)
        if node is not None:          # an annotation for a node with no edges
            node.metadata.update(values)
    return dag
