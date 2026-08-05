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

    python3 -m ontodag.migrate STORE.od        # native file, in place
    migrate_record_store(old_rs, new_rs)       # record stores, programmatic
"""

import shlex
import sys

from ontodag.dag import OntoDAG


def _replay(entries) -> OntoDAG:
    """Rebuild from raw {name: [parent names]} through put (which
    canonicalizes), parents-first. Raises on unresolvable parents."""
    out = OntoDAG()
    pending = {name: list(parents) for name, parents in entries.items()}
    done = set()
    while pending:
        ready = sorted(name for name, parents in pending.items()
                       if all(p in done for p in parents))
        if not ready:
            raise ValueError(
                f"cannot order entries (missing parents or a cycle): "
                f"{sorted(pending)[:5]}")
        for name in ready:
            out.put(name, pending.pop(name))
            done.add(name)
    return out


def _native_entries(path):
    entries = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tokens = shlex.split(line)
            entries.setdefault(tokens[0], [])
            for parent in tokens[1:]:
                if parent == "*":      # the implicit root, never replayed
                    continue
                entries.setdefault(parent, [])
                entries[tokens[0]].append(parent)
    return entries


def migrate_native(path) -> None:
    """Re-canonicalize a native text store in place. Idempotent."""
    from ontodag.__main__ import _save_native
    _save_native(_replay(_native_entries(path)), path)


def migrate_record_store(old_store, new_store):
    """Replay a record-store-backed ontology (records read raw, never
    interpreted) into `new_store` — a fresh, writable RecordStore — under
    current canonicalization; returns the committed new root. The old root
    stays retrievable forever (content addressing forgets nothing) and
    remains verifiable under its pinned registry version."""
    from ontodag.eager import EagerOntoDAG
    entries = {}
    for key, record in old_store.items():
        if key == "*":     # the implicit root has a record but is never replayed
            continue
        entries[key] = [p for p in record.get("up", []) if p != "*"]
    new = EagerOntoDAG(new_store)
    new.merge(_replay(entries))
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
