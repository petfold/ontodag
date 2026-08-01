"""Published cone summaries — a derived index that removes the lazy
reader's fetch floor (docs/CONE_SUMMARIES_PLAN.md; SEMANTIC_CODES.md §7).

A query's cost over a published store is bounded below by the size of its
narrowest term's cone, because that first cone must be enumerated to exist
as a set at all (measured: 1,071 fetches for a two-broad-term query on a
3,221-record store). A cone summary is one record that *states* a broad
category's membership, so one fetch replaces the enumeration.

The purity constraints, in force here:

- **Derived, never merged, never part of the ontology's identity.** The
  index lives in a SEPARATE record store with its own root; building it
  does not touch the asserted root ("same knowledge ⇒ same fingerprint"
  must not depend on a threshold constant or an index format).
- **Deterministic.** Selection is a pure rule from the graph
  (``descendant_count >= threshold`` — expensive queries are exactly those
  whose narrowest term is broad, so the graph alone identifies them); any
  publisher regenerates a byte-identical index root from the same data
  root.
- **A cache with an exact fallback.** The manifest pins the ``data_root``
  it describes; on any mismatch (stale index, unknown format) the reader
  ignores the index and walks — slower, never wrong.
- **Encoding v0 is sorted name lists**, not bitmaps: bitmaps are
  positional, so a thin client would need the whole name↔position
  dictionary to interpret one answer, which defeats the purpose (see the
  plan's encoding table). The manifest carries the format name so bitmaps
  can land later without touching readers.

Summaries state the COMBINED cone (asserted + computed dimension hops) —
what `get_descendants` returns on the query path; readers must never serve
an asserted-only request from them (counts stay asserted-only by design).

Stores are duck-typed exactly as in `eager`/`lazy` (``get``/``put``/
``commit``); this module imports nothing from recordstore (B1/B2).

Because summaries state COMBINED cones, they are a function of the graph
*and* of the dimensions interpreter: the manifest therefore also pins the
builder's ``dimensions.REGISTRY_VERSION`` (the DIMENSIONS.md §10 rule —
shared parametric-derived state pins the arithmetic that produced it). A
reader on a different registry version ignores the index and walks with
its own arithmetic — consistent by definition, never silently different.
"""

from ontodag import dimensions as _dims

FORMAT = "cone-names-v1"
MANIFEST_KEY = "manifest"
CONE_PREFIX = "cone/"
DEFAULT_THRESHOLD = 64


def summarized_names(dag, threshold=DEFAULT_THRESHOLD):
    """The categories that get a summary: deterministic, graph-only rule."""
    return sorted(
        name for name, node in dag.nodes.items()
        if name != dag.root.name and node.descendant_count >= threshold)


def build_index(dag, index_store, data_root, threshold=DEFAULT_THRESHOLD):
    """Write cone summaries for `dag` (committed as `data_root`) into the
    separate `index_store`; return the index root. Same graph ⇒ same index
    root, regardless of the history that built either store."""
    for name in summarized_names(dag, threshold):
        index_store.put(
            CONE_PREFIX + name,
            sorted(item.name for item in dag.get_descendants(name)))
    index_store.put(MANIFEST_KEY, {
        "format": FORMAT,
        "data_root": data_root,
        "policy": f"descendant_count>={threshold}",
        "registry_version": _dims.REGISTRY_VERSION,
    })
    return index_store.commit()


class ConeIndex:
    """Read side: `cone(name)` returns the summarized membership as a list
    of names, or None (not summarized / stale / unknown format) — in which
    case the caller walks. `fetches` counts index-store reads."""

    def __init__(self, index_store, data_root):
        self.store = index_store
        self.fetches = 0
        try:
            manifest = index_store.get(MANIFEST_KEY)
            self.fetches += 1
        except KeyError:
            manifest = None
        self._live = bool(
            manifest
            and manifest.get("format") == FORMAT
            and manifest.get("data_root") == data_root
            and _dims.registry_compatible(manifest.get("registry_version")))

    def cone(self, name):
        if not self._live:
            return None
        try:
            members = self.store.get(CONE_PREFIX + name)
        except KeyError:
            return None
        finally:
            self.fetches += 1
        return members
