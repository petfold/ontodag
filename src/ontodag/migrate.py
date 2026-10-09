"""Registry migration: re-canonicalize a store under the current interpreter.

Registry v3 (docs/UNITS.md) changed canonical value spellings from
integers-in-tiny-bases to rationals-at-SI-anchors — the one canonical-name
migration in the system's life (D9 abolishes the class that caused it).
The old spellings (``mg``, ``mm``, ``s``…) remain valid *input* under v3,
which makes migration nothing but a replay: rebuild the graph through
``put``, which canonicalizes every name, parents-first. The replay reads
the RAW entries (file lines, records) rather than a live ``OntoDAG`` —
the new interpreter canonicalizes lookups, so a graph stored under old
spellings cannot even be traversed as-is; raw name→parents pairs can.
Scaling preserves containment, so the shape is untouched: a migration is
a pure rename, deterministic, and therefore verifiable by recomputation.
What a node carries travels with it: native `#:meta` lines, and a record's
`meta` and `payload` (until 2026-10-09 both were dropped).

    python3 -m ontodag.migrate STORE.od        # native file, in place
    migrate_record_store(old_rs, new_rs)       # record stores, programmatic
"""

import sys

from ontodag.native import _parse, _replay, _stored_as


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
    native.save(_replay(entries, metadata), path)


def migrate_record_store(old_store, new_store):
    """Replay a record-store-backed ontology (records read raw, never
    interpreted) into `new_store` — a fresh, writable RecordStore — under
    current canonicalization; returns the committed new root. The old root
    stays retrievable forever (content addressing forgets nothing) and
    remains verifiable under its pinned registry version."""
    from ontodag.eager import EagerOntoDAG
    entries, metadata, payloads = {}, {}, {}
    for key, record in old_store.items():
        if key == "*":     # the implicit root has a record but is never replayed
            continue
        entries[key] = [p for p in record.get("up", []) if p != "*"]
        if record.get("meta"):
            metadata[key] = record["meta"]
        if record.get("payload") is not None:
            payloads[key] = record["payload"]
    new = EagerOntoDAG(new_store)
    new.merge(_replay(entries, metadata))
    for key, payload in payloads.items():
        for stored in _stored_as(new, key):
            new._payloads[stored] = payload
    return new.commit()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python3 -m ontodag.migrate STORE.od", file=sys.stderr)
        return 2
    try:
        migrate_native(argv[0])
    except (OSError, ValueError) as exc:
        print(f"ontodag.migrate: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
