"""The native store format, as text: `loads(text)` and `dumps(dag)`.

One line per node, `name parent1 parent2 ...` (shell-quoted), under a
`# ontodag store v1` header, plus a `#:meta <name> <json>` line for each node
carrying metadata. The format is canonical — nodes, parents and metadata
keys sorted — so equal knowledge gives equal bytes.

A file `dumps` wrote carries a `#:canonical <registry version> <sha256>` line
after the header: the hash of everything below it, and the registry version
whose spelling rules wrote it. A file whose marker holds — the current
registry version, the hash matching — is built straight from its lines,
since it is already canonical: under one registry version the same filings
always store the same (CONTRACT.md G8). On the 11,900-category store of core
plus the ten domain packs that takes 0.47 s, where the reducing load every
file used to get took 9.1 s (decided with Peter, 2026-10-09). The marker
is a checksum, not a signature: it tells a file `odag` wrote from one it did
not, not a friend from a foe.

Any other file — edited by hand, written under another registry version, or
written before the marker existed — is read as a merge of its lines would
be (`_restore`): every name it lists on a line of its own stays a category
under the parents it gives, spelled as this registry spells it, a value
anchored under its head, every edge reduced, and nothing migrated. So a
hand-written `x mass(5000g)` loads as `x` under `mass(5kg)`, the one name
of that class, inside `mass`'s star; while what an older release stored
loads as it was (a compound it folded, a contradiction a merge kept), since
a newer release never takes an answer away (G7) and a store a merge made
must open again (G9). Bringing such a store to the current stored form is
`ontodag.migrate`'s job, which replays it through `put` (`_replay`). Both
replays take unit declarations first and every term after the heads its
spelling depends on, so a value reads its vocabulary whatever the file's
order.

This is what `odag` reads and writes for a `.od` store. It is public so that
a program embedding OntoDAG — a web app, a sync tool — can move stores as
text without a file on disk or a reach into the CLI module. Standard library
only (B1).
"""

import hashlib
import heapq
import json
import os
import shlex

from ontodag.dag import Item, OntoDAG
from ontodag.dimensions import (REGISTRY_VERSION, UNIT_DECLARATION,
                                constraints, split_term)

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

# The canonical marker rides on a comment line for the same reason: a reader
# released before it skips it, and reads the file as before.
CANONICAL_LINE = "#:canonical"

# The lines git writes into a file it could not merge.
_CONFLICT = ("<<<<<<<", "|||||||", "=======", ">>>>>>>")


def loads(text, source="<text>"):
    """`.od` text -> OntoDAG. Raises ValueError, naming `source` and the
    line, on a malformed line (a metadata line that is not a JSON object, an
    unbalanced quote); the graph's own errors (a cycle) propagate as they
    would from `put`."""
    entries, metadata, lined = _parse(text.splitlines(), source)
    if _trusted(text):
        return _direct(entries, metadata)
    return _restore(entries, metadata, lined)


def dumps(dag):
    """OntoDAG -> canonical `.od` text, ending in a newline, with the marker
    that lets the next load trust it."""
    lines = []
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
    body = "\n".join(lines) + "\n" if lines else ""
    return (f"{HEADER}\n{CANONICAL_LINE} {REGISTRY_VERSION} {_digest(body)}\n"
            f"{body}")


def load(path):
    """Read a `.od` file. A missing file is an empty DAG (the default store
    need not exist yet)."""
    if not os.path.exists(path):
        return OntoDAG()
    with open(path, encoding="utf-8") as fh:
        return loads(fh.read(), path)


def save(dag, path):
    """Write `dag` to `path` as `.od`."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps(dag))


def _digest(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _trusted(text):
    """Was this text written by `dumps` under this registry version, and left
    as it was?"""
    head, _, rest = text.partition("\n")
    marker, _, body = rest.partition("\n")
    parts = marker.split()
    return (head.strip() == HEADER and len(parts) == 3
            and parts[0] == CANONICAL_LINE and parts[1] == REGISTRY_VERSION
            and parts[2] == _digest(body))


def _parse(lines, source):
    """The lines as {name: [parent names]} — every name a line or a parent
    mentions, the root's `*` kept — {name: metadata}, and the names that
    have a line of their own."""
    entries, metadata, lined = {}, {}, set()
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        if line.startswith(META_LINE):
            # Strict on purpose: dropping an unreadable annotation is the
            # silent data loss this line type exists to end.
            try:
                _, name, blob = shlex.split(line)
                values = json.loads(blob)
                if not isinstance(values, dict):
                    # JSON, but not an object: it escaped as TypeError at
                    # `metadata.update` until 2026-10-09
                    raise ValueError("the annotation is not a JSON object")
                metadata[name] = values
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"{source}:{number}: malformed {META_LINE} line ({exc})"
                ) from exc
            continue
        if line.startswith(_CONFLICT):
            # Read as names, git's markers became categories called
            # `<<<<<<<` and `HEAD` (until 2026-10-09). The marker line makes
            # a conflict routine: two branches that both change a store both
            # change its checksum.
            raise ValueError(
                f"{source}:{number}: an unresolved merge conflict — keep the "
                f"lines you want from each side, then delete git's markers "
                f"and the {CANONICAL_LINE} lines: odag reads the file as a "
                f"merge of its lines, and the next save marks it again")
        if line.startswith("#"):
            continue
        try:
            tokens = shlex.split(line)
        except ValueError as exc:        # an unbalanced quote
            raise ValueError(f"{source}:{number}: malformed line ({exc})") from exc
        lined.add(tokens[0])
        parents = entries.setdefault(tokens[0], [])
        for parent in tokens[1:]:
            entries.setdefault(parent, [])
            if parent not in parents:
                parents.append(parent)
    return entries, metadata, lined


def _direct(entries, metadata):
    """Build a canonical file as written: its nodes, its edges, and the
    counts computed once. Nothing is reduced or canonicalized, because a
    file the marker vouches for is already both."""
    dag = OntoDAG()
    for name in entries:
        if name not in dag.nodes:
            dag.add_node(Item(name))
    for name, parents in entries.items():
        child = dag.nodes[name]
        for parent in parents:
            dag.nodes[parent].neighbors.add(child)
    for node in dag.nodes.values():
        node.descendant_count = len(dag.get_descendants(node, computed=False))
    _annotate(dag, metadata)
    return dag


def _restore(entries, metadata, lined):
    """Read a file the marker does not vouch for as a merge of its lines
    would be. Each name with a line of its own stays a category (spelled
    as this registry spells it: a hand-written `mass(5000g)` is `mass(5kg)`,
    a value is anchored under its head); a name met only as a parent is a
    filing, so a compound of the graph kind there is filed as its parts, as
    `put` files it. Edges go in through `add_edge` as a total replay, as a
    merge's do (CONTRACT.md G9): reduced, and nothing an author would have
    been refused is refused here. A name this registry cannot read as a term
    stays as it is written, as every release before read it."""
    pending = {name: [p for p in parents if p != "*"]
               for name, parents in entries.items() if name != "*"}
    dag = OntoDAG()
    stored = {}

    def arrive(name):
        """The names `name` is stored as, materialized."""
        if name not in stored:
            try:
                parts = [name] if name in lined else dag._graph_parts(name)
                names = [dag._canonical_name(part) for part in parts]
            except ValueError:
                names = [name]
            for spelled in names:
                if spelled not in dag.nodes:
                    parsed = _parametric(dag, spelled)
                    if parsed is not None:
                        dag._ensure_parametric_node(spelled, parsed[0], parsed[1])
                    else:
                        dag.add_node(Item(spelled))
            stored[name] = names
        return stored[name]

    with dag._lenient_roles():
        for name in _load_order(pending):
            names = arrive(name)
            if len(names) != 1:
                continue                 # a compound met only as a parent
            node = dag.nodes[names[0]]
            parents = [dag.nodes[p] for parent in pending[name]
                       for p in arrive(parent)]
            if "*" in entries[name] or (
                    name not in lined and not parents
                    and _parametric(dag, node.name) is None):
                # Top level as written, or a parent never given a line of
                # its own, which `put` would have made top level; a line
                # with no parents stays as written, as it always loaded.
                parents.append(dag.root)
            for parent in parents:
                dag.add_edge(parent, node)
    dag._respell_deferred()
    dag._fold_replayed()          # as a merge of the lines files them (§9)
    for name, values in metadata.items():
        for spelled in stored.get(name, ()):
            if spelled in dag.nodes:
                dag.nodes[spelled].metadata.update(values)
    return dag


def _parametric(dag, name):
    """`dag._parse_parametric(name)`, or None for a name it cannot read."""
    try:
        return dag._parse_parametric(name)
    except ValueError:
        return None


def _stored_as(dag, name):
    """The present names `name` was stored as: itself canonicalized, a
    graph-kind compound's parts (DIMENSIONS.md §15), or a role of geo's
    cell spelled the old way, by the cell's own name (question 14)."""
    names = [dag._canonical_name(part) for part in dag._graph_parts(name)]
    found = [n for n in names if n in dag.nodes]
    value = None if found else dag._old_cell_value(name)
    if value is not None:
        respelled = dag._cell_spellings(split_term(name)[0], value)[0]
        found = [respelled] if respelled in dag.nodes else []
    return found


def _replay(entries, metadata=None):
    """Rebuild from raw {name: [parent names]} through `put`, which
    canonicalizes every spelling, anchors every value and reduces every edge,
    and stores what it is given as the current release stores it: a folded
    compound as its parts, two overlapping values of one head as their meet.
    That is a migration, so it is `ontodag.migrate`'s replay; loading a file
    is `_restore`'s. Total (CONTRACT.md G9), in `_load_order`. Raises on a
    cycle."""
    pending = {name: [p for p in parents if p != "*"]
               for name, parents in entries.items() if name != "*"}
    dag = OntoDAG()
    with dag._lenient_roles():
        for name in _load_order(pending):
            dag.put(name, pending[name])
    dag._respell_deferred()
    # A role of geo's cell stored as a bare word (`from(u2e4x)`) is spelled
    # by the cell's own name since registry 4.4 (review question 14).
    dag._respell_old_cells(list(dag.nodes), every=True)
    for name, values in (metadata or {}).items():
        for stored in _stored_as(dag, name):
            dag.nodes[stored].metadata.update(values)
    return dag


def _load_order(pending):
    """Unit declarations, and what they hang from, first, so every value
    reads its units; then parents before children, and every term after the
    heads its spelling depends on, so a value whose line does not name its
    head (`x mass(5000g)`, written by hand) is read once `mass` is declared.
    Kahn's order, ties broken by name, so a replay is deterministic. Raises
    on a cycle."""
    first = _upward(pending, [name for name, parents in pending.items()
                              if UNIT_DECLARATION in parents])
    head = _order({name: pending[name] for name in first}, {})
    rest = {name: [p for p in parents if p not in first]
            for name, parents in pending.items() if name not in first}
    tail = _order(rest, _heads_first(rest)) or _order(rest, {})
    if head is None or tail is None:
        done = set(_order(pending, {}, partial=True))
        stuck = sorted(name for name in pending if name not in done)
        raise ValueError(f"cannot order entries (a cycle among them, or a "
                         f"parent never given): {stuck[:5]}")
    return head + tail


def _upward(pending, names):
    """`names` and everything they hang from, within `pending`."""
    seen, stack = set(), [n for n in names if n in pending]
    while stack:
        name = stack.pop()
        if name not in seen:
            seen.add(name)
            stack.extend(p for p in pending[name] if p in pending)
    return seen


def _heads_named(name):
    """The heads a term's spelling depends on: its own and, inside it,
    its constraints'."""
    split = split_term(name)
    if split is None:
        return []
    heads = [split[0]]
    for constraint in constraints(split[1]):
        heads.extend(_heads_named(constraint))
    return heads


def _heads_first(pending):
    """name -> the heads its spelling depends on, among `pending`."""
    return {name: [head for head in _heads_named(name)
                   if head in pending and head != name]
            for name in pending if split_term(name) is not None}


def _order(pending, waits, partial=False):
    """Kahn's order over parents plus `waits`, ties broken by name: every
    name after what it waits on, or None when there is no such order (a
    cycle, or a parent missing from `pending`). `partial`: what could be
    ordered."""
    needs = {name: set(parents) | set(waits.get(name, ()))
             for name, parents in pending.items()}
    blocking = {}
    for name, before in needs.items():
        for other in before:
            blocking.setdefault(other, []).append(name)
    count = {name: len(before) for name, before in needs.items()}
    ready = [name for name, n in count.items() if n == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        name = heapq.heappop(ready)
        order.append(name)
        for later in blocking.get(name, ()):
            count[later] -= 1
            if count[later] == 0:
                heapq.heappush(ready, later)
    if partial or len(order) == len(pending):
        return order
    return None


def _annotate(dag, metadata):
    for name, values in metadata.items():
        node = dag.nodes.get(name)
        if node is not None:          # an annotation for a node with no edges
            node.metadata.update(values)
