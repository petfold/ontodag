"""Registry migration: re-canonicalize a store under the current interpreter.

Registry v3 (docs/UNITS.md) changed canonical value spellings from
integers-in-tiny-bases to rationals-at-SI-anchors (D9 abolishes the class
that caused it). Later changes migrate the same way (4.0's `coulomb` and
`farad`, the graph kind's parts in 0.30.6), and since contract 0.5 (G8)
each comes with a registry minor and a migrate step named in CHANGELOG.
The old spellings (``mg``, ``mm``, ``s``…) remain valid *input* under v3,
which makes migration nothing but a replay: rebuild the graph through
``put``, which canonicalizes every name, parents-first. The replay reads
the RAW entries (file lines, records) rather than a live ``OntoDAG`` —
the new interpreter canonicalizes lookups, so a graph stored under old
spellings cannot even be traversed as-is; raw name→parents pairs can.
A rescale preserves containment, so it is a pure rename; a stored-form
change (a folded compound filed as its parts, overlapping values as their
meet) reshapes the graph. Either is deterministic, and therefore
verifiable by recomputation.
What a node carries travels with it: native `#:meta` lines, and a record's
`meta` and `payload` (until 2026-10-09 both were dropped).

Registry 5.0 made `geo` a rectangle head (questions 29, 30 and 33): before
the replay, a store that declares `geo` a prefix head has every geohash cell
rewritten as its rectangle, exactly (a cell's bounds are dyadic, so finite
decimals), in `geo(...)` values and in its roles' terms, nested
(`from(geo(u2e4))`) or bare as stored before registry 4.4 (`from(u2e4)`,
no place being named so), and `geo` re-declared under the rectangle kind.

Registry 6.0 stores a role's rectangle bare (question 50): the replay
spells `from(geo(48..49,2..3))` as `from(48..49,2..3)`, since the old
spelling stays valid input, and needs no rewrite of its own.

    python3 -m ontodag.migrate STORE.od        # native file, in place
    python3 -m ontodag.migrate rs:PATH         # a store odag opens, in place
    migrate_record_store(old_rs, new_rs)       # record stores, programmatic
"""

import re
import sys
from fractions import Fraction

from ontodag import dimensions as dims
from ontodag.native import _parse, _replay, _stored_as

_GEOHASH = re.compile(r"^[0-9b-hjkmnp-z]+$")
_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def cell_rectangle(cell):
    """The exact rectangle of a geohash cell, `S..N,W..E`."""
    lon, lat, even = [Fraction(-180), Fraction(180)], [Fraction(-90), Fraction(90)], True
    for char in cell:
        bits = _BASE32.index(char)
        for shift in range(4, -1, -1):
            half = lon if even else lat
            mid = (half[0] + half[1]) / 2
            half[0 if bits >> shift & 1 else 1] = mid
            even = not even
    return dims._render_rect((lat[0], lat[1], *dims._geo_arc(lon[0], lon[1], cell)))


def rewrite_geohash_cells(entries):
    """`entries` ({name: [parents]}) with a pre-5.0 store's geo cells as
    rectangles (see the module's docstring); unchanged when `geo` is not
    declared a prefix head."""
    if dims.KIND_PREFIX not in entries.get(dims.GEO_HEAD, ()):
        return entries
    roles, grew = set(), True
    while grew:                       # heads whose base is geo
        grew = False
        for name, parents in entries.items():
            if name not in roles and dims.split_term(name) is None and \
                    any(p == dims.GEO_HEAD or p in roles for p in parents):
                roles.add(name)
                grew = True

    def renamed(name):
        split = dims.split_term(name)
        if split is None:
            return name
        head, param = split
        if head == dims.GEO_HEAD and _GEOHASH.match(param):
            return f"geo({cell_rectangle(param)})"
        if head in roles:
            inner = dims.split_term(param)
            if inner is not None and inner[0] == dims.GEO_HEAD and _GEOHASH.match(inner[1]):
                return f"{head}(geo({cell_rectangle(inner[1])}))"
            if inner is None and _GEOHASH.match(param) and param not in entries:
                return f"{head}(geo({cell_rectangle(param)}))"
        return name
    out = {}
    for name, parents in entries.items():
        if name == dims.GEO_HEAD:
            parents = [dims.KIND_RECT if p == dims.KIND_PREFIX else p for p in parents]
        new = renamed(name)
        merged = out.setdefault(new, [])
        merged.extend(p for p in map(renamed, parents) if p not in merged)
    out.setdefault(dims.KIND_RECT, [dims.DIMENSION_ROOT])
    return out


def _native_entries(path):
    """A native file's raw entries and metadata, read by `native`'s own
    parser, so a malformed line, or git's conflict markers, is refused
    naming the line."""
    with open(path, encoding="utf-8") as fh:
        entries, metadata, _ = _parse(fh.read().splitlines(), path)
    return entries, metadata


def migrate_native(path) -> None:
    """Re-canonicalize a native text store in place. Idempotent."""
    from ontodag import native
    entries, metadata = _native_entries(path)
    native.save(_replay(rewrite_geohash_cells(entries), metadata), path)


def _record_entries(record_store):
    """({name: [parents]}, {name: meta}, {name: payload}) of a record
    store's records, read raw, never interpreted."""
    entries, metadata, payloads = {}, {}, {}
    for key, record in record_store.items():
        if key == "*":     # the implicit root has a record but is never replayed
            continue
        entries[key] = [p for p in record.get("up", []) if p != "*"]
        if record.get("meta"):
            metadata[key] = record["meta"]
        if record.get("payload") is not None:
            payloads[key] = record["payload"]
    return entries, metadata, payloads


def _write_replay(dag, record_store):
    """Replace `dag`'s contents (an EagerOntoDAG) with `record_store`'s
    records replayed under current canonicalization, payloads following
    their names."""
    entries, metadata, payloads = _record_entries(record_store)
    replayed = _replay(rewrite_geohash_cells(entries), metadata)
    dag.clear()
    dag.merge(replayed)
    for key, payload in payloads.items():
        for stored in _stored_as(dag, key):
            dag._payloads[stored] = payload


def migrate_record_store(old_store, new_store):
    """Replay a record-store-backed ontology (records read raw, never
    interpreted) into `new_store` — a fresh, writable RecordStore — under
    current canonicalization; returns the committed new root. The old root
    stays retrievable forever (content addressing forgets nothing) and
    remains verifiable under its pinned registry version."""
    from ontodag.eager import EagerOntoDAG
    new = EagerOntoDAG(new_store)
    _write_replay(new, old_store)
    return new.commit()


def migrate_store(spec, message="migrate"):
    """Re-canonicalize a store `odag` opens (`rs:PATH`, `swarm:NAME`) in
    place, as one new state on its history, the way `odag import` writes a
    file: `odag undo` goes back to the state it replayed. Idempotent: a
    store already in the current form gets no new state."""
    from ontodag.stores import Store
    store = Store(spec)
    dag = store.dag
    before = {name: sorted(p.name for p in node.parents)
              for name, node in dag.nodes.items()}
    _write_replay(dag, dag.store)
    after = {name: sorted(p.name for p in node.parents)
             for name, node in dag.nodes.items()}
    if after != before:
        store.save(message=message)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python3 -m ontodag.migrate STORE.od | rs:PATH | swarm:NAME",
              file=sys.stderr)
        return 2
    try:
        if argv[0].startswith(("rs:", "swarm:")):
            migrate_store(argv[0])
        else:
            migrate_native(argv[0])
    except (OSError, ValueError) as exc:
        print(f"ontodag.migrate: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
