"""LazyOntoDAG — query a published OntoDAG without loading all of it.

Named for its *residency*, not its backend (see `eager.py`): like its sibling
it takes any duck-typed record store, and Swarm — when Swarm is involved at
all — is chosen one layer down by whoever builds that store.

`EagerOntoDAG` hydrates the whole store into RAM on construction (fast, but
bounded by memory and hostile to browsers or huge published ontologies). This
module is the other end of that trade: nodes are fetched *as a query walks
them*, so cost scales with the query, not with the store.

What makes it possible is the record schema (`SWARM_DESIGN.md` §3): each record
already carries both directions (``up``/``down``) and its own ``count``, which
is exactly the information the query planner needs about a node —

- term resolution needs one record per query term,
- the planner's term-dropping step and the probe operator walk *upward* via
  ``up``,
- cone walks descend via ``down``,
- and ``descendant_count`` — the planner's only statistic — is read straight
  out of the record, so ordering cones smallest-first costs one fetch per term
  rather than a traversal.

**Read-only by construction.** Writing is refused, not merely discouraged —
though the reasons have narrowed. Exact counts are *no longer* one of them:
they are maintained by local delta (see the "counts" note in `dag.py`), proven
exact against a brute-force oracle and cheaper than the recompute they
replaced, so nothing about them needs the whole graph. What still does:
`EagerOntoDAG.commit` detects change by diffing a *complete* set of synced
records, which a partially-resident writer would have to replace with
dirty-tracking; and transitive reduction, while bounded by the ancestors and
cones it touches (so plausibly local), has not been tested under partial
residency. Until both are settled: use `EagerOntoDAG` to edit and publish,
`LazyOntoDAG` to query what was published. Groundwork in
`experiments/RESULTS.md` on the `experiment/delta-counts` branch; status in
`docs/plans/ROADMAP.md` item 2.

**Nodes exist in two states.** A *stub* is an `Item` that is known to exist
(some record referenced it) but whose record has not been fetched: it has a
name and nothing else. *Expanding* a stub fetches its record and fills in its
count, metadata, children and parents — as stubs in turn. Every traversal here
expands each node before reading its edges, which is the whole trick; the
inherited traversals in `dag.py` would happily walk a half-built graph and
return a wrong answer, so the three that the query path uses are overridden.

Consequences worth knowing:

- ``self.nodes`` holds only what has been touched (stubs included), so
  ``len(dag.nodes)`` is not the size of the store and whole-graph operations
  inherited from `DAG` (``topological_sort``, ``intersection_dag``,
  visualization) would silently see a fragment. Call ``load_all()`` first if
  you want those.
- Fetches are counted in ``self.fetches`` — tests assert on it, and it is the
  honest measure of whether laziness is paying off.
- Cones are memoized by name (the snapshot is immutable, so a cached cone can
  never go stale) and this is what makes repeated queries over a hot category
  free. ``max_cached_cones`` bounds the memory that costs.

**Cost, measured** (3,221-record store: 20 top categories, 200 mid, 3,000
leaves, each under two parents):

===========================  ======  ==========
query                        result  fetches
===========================  ======  ==========
one mid category                 41          42
two mid categories (empty)        0          82
one top + one mid                 3          81
two top categories              140       1,071
===========================  ======  ==========

So the cost is roughly *the smallest cone walked, plus one upward walk per
surviving candidate* — a specific query touches a few dozen records out of
thousands, and even a broad-plus-specific pair stays small because the planner
probes upward instead of walking the broad cone (§4). What is still cone-sized
is a query whose *narrowest* term is itself broad: nothing here can beat walking
a cone it has to enumerate. That case is what published cone summaries are for
(`DATABASE_DIRECTION.md` "Pure now" item 1, `SEMANTIC_CODES.md`): a
deterministically-derived bitmap blob per hot category, fetched instead of
walked. This class deliberately stops short of that — it is the on-demand
*reader*; the summaries are a derived index with its own design note.

Batching note: a walk expands one node at a time because the duck-typed store
interface offers only single-key ``get``. A store-level multi-key get would let
each BFS level fetch concurrently (recordstore already batches at the blob
layer for ``items()``); the traversals below are written so that change is
local to ``_expand_many``.
"""

from ontodag import dimensions as _dims
from ontodag.dag import DAG, Item, OntoDAG, _name_of


class _LazyNodes(dict):
    """`DAG.nodes` that materializes a stub on first mention of a real key.

    `dag.py` reaches for `self.nodes.get(name)` both to resolve public
    arguments and to check that a walked edge belongs to this instance
    (`self.nodes.get(parent.name) is parent`). Registering every stub here on
    creation keeps that identity check true, and makes an unknown name — one
    with no record in the store — return `None` exactly as it would for an
    in-memory DAG.
    """

    def __init__(self, dag):
        super().__init__()
        self._dag = dag

    def get(self, name, default=None):
        # A resident node — expanded from the store, or created locally by
        # the sparse writer (which has no record: _load would wrongly report
        # it absent) — is the truth as it stands in memory.
        node = dict.get(self, name)
        if node is not None and name in self._dag._expanded:
            return node
        if self._dag._load(name) is None:
            return default
        # Resolution expands: the planner reads `descendant_count` off the
        # nodes it gets back, and an unexpanded stub reports 0, which would
        # leave it ordering cones and dropping subsumed terms on no
        # information at all. The record is already fetched by `_load`, so
        # expanding here costs nothing beyond it.
        return self._dag._expand(self._dag._stub(name))

    def __contains__(self, name):
        return self.get(name) is not None

    def __missing__(self, name):
        node = self.get(name)
        if node is None:
            raise KeyError(name)
        return node


class LazyOntoDAG(OntoDAG):
    """Read-only `OntoDAG` view over a record store, fetched on demand.

    `record_store` is duck-typed exactly as in `eager`: ``get(key)``
    raising `KeyError` for a missing key is all a query needs (``items()`` is
    used only by `load_all`). Pass a snapshot — e.g.
    ``RecordStore.at(root, bytes_store)`` — since nothing here expects the
    store to change underneath it.
    """

    def __init__(self, record_store, cache_cones=True, max_cached_cones=64,
                 cone_index=None):
        super().__init__()
        self.store = record_store
        self.fetches = 0            # store.get calls; the point of all this
        self._records = {}          # name -> record (or None: known absent)
        self._expanded = set()      # names whose edges are filled in
        self._cone_cache = {} if cache_cones else None
        self._max_cached_cones = max_cached_cones
        # Optional published cone summaries (ontodag.cones.ConeIndex, duck-
        # typed): a hit turns a whole-cone enumeration into one fetch and
        # returns STUB members (names registered, unexpanded — no per-item
        # fetches unless the caller wants payload/meta). A cache with an
        # exact fallback: misses and stale indexes just walk.
        self._cone_index = cone_index
        root = self.root
        self.nodes = _LazyNodes(self)
        dict.__setitem__(self.nodes, root.name, root)

    # ------------------------------------------------------------- fetching

    def _load(self, name):
        """The record for `name`, or None if the store has no such key."""
        if name in self._records:
            return self._records[name]
        try:
            record = self.store.get(name)
        except KeyError:
            record = None
        self.fetches += 1
        self._records[name] = record
        return record

    def _stub(self, name):
        """The `Item` for `name`, created (edgeless) and registered if new."""
        node = dict.get(self.nodes, name)
        if node is None:
            node = Item(name)
            dict.__setitem__(self.nodes, name, node)
        return node

    def _expand(self, node):
        """Fill in `node`'s count, metadata and both edge directions."""
        if node.name in self._expanded:
            return node
        self._expanded.add(node.name)
        record = self._load(node.name)
        if record is None:
            return node
        node.descendant_count = record["count"]
        if record.get("meta"):
            node.metadata = dict(record["meta"])
        for child_name in record["down"]:
            node.neighbors.add(self._stub(child_name))
        for parent_name in record["up"]:
            # `neighbors` is an _EdgeSet, so the parent's own expansion will
            # add this edge downward too; adding it upward here is what lets a
            # probe walk ancestors without expanding whole cones.
            node.parents.add(self._stub(parent_name))
        return node

    def _expand_many(self, nodes):
        """Expand a whole frontier — the seam for a future batched store get."""
        return [self._expand(node) for node in nodes]

    def load_all(self):
        """Fetch every record, making this a fully resident (still read-only)
        graph — for the whole-graph operations inherited from `DAG`."""
        items = getattr(self.store, "items", None)
        pairs = items() if callable(items) else (
            (name, self.store.get(name)) for name in self.store.keys())
        for name, record in pairs:
            self._records.setdefault(name, record)
        for name in list(self._records):
            if self._records[name] is not None:
                self._expand(self._stub(name))
        return self

    # ------------------------------------------------------- dimensions
    #
    # DIMENSIONS.md §12 step 5: the inherited dimension machinery (_star,
    # _computed_children/_parents, _virtual_cone, get, get_overlapping)
    # works on names and on `self.nodes.get(...)`, which loads-and-expands
    # here — the one thing it cannot do on stubs is walk *upward*, so the
    # kind lookup expands as it climbs. Records carry `up`, so the walk
    # costs the climbed path, never the graph; names without "(" short-
    # circuit before any fetch, keeping dimension-free budgets unchanged.

    def _dimension_kind(self, head_name):
        node = self.nodes.get(head_name)   # loads + expands (or None)
        if node is None or head_name in _dims.KINDS:
            return None
        kinds = set()
        seen = set()
        stack = [node]
        while stack:
            for parent in self._expand(stack.pop()).parents:
                if dict.get(self.nodes, parent.name) is not parent:
                    continue
                if parent.name in _dims.KINDS:
                    kinds.add(parent.name)
                elif parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        if len(kinds) > 1:
            raise ValueError(
                f"dimension {head_name!r} inherits multiple kinds: "
                f"{', '.join(sorted(kinds))} — declare exactly one")
        return next(iter(kinds), None)

    # ------------------------------------------------------- traversals

    def get_descendants(self, node, visited=None, computed=True):
        name = self._canonical_name(_name_of(node))
        start = self.nodes.get(name)
        if start is None:
            return set()
        # Cones are cached only in the combined order (the query semantics);
        # an asserted-only request — e.g. a count recomputation in a copy —
        # must not be served a combined cone, or vice versa.
        if computed and self._cone_cache is not None \
                and name in self._cone_cache:
            return set(self._cone_cache[name])
        # Published summary: one fetch instead of the enumeration. Combined-
        # order requests only — summaries state the query-path cone, and an
        # asserted-only caller (count recomputation) must never see it.
        if computed and self._cone_index is not None:
            members = self._cone_index.cone(name)
            if members is not None:
                descendants = {self._stub(member) for member in members}
                self._cache_cone(name, descendants)
                return descendants

        descendants = set()
        seen = {start}
        frontier = [start]
        while frontier:
            current = self._expand(frontier.pop())
            successors = list(current.neighbors)
            if computed:
                successors.extend(self._computed_children(current))
            for child in successors:
                descendants.add(child)
                if child not in seen:
                    seen.add(child)
                    frontier.append(child)
        if computed:
            self._cache_cone(name, descendants)
        return descendants

    def _cache_cone(self, name, descendants):
        if self._cone_cache is None:
            return
        if len(self._cone_cache) >= self._max_cached_cones:
            # insertion order: drop the oldest entry
            self._cone_cache.pop(next(iter(self._cone_cache)))
        self._cone_cache[name] = set(descendants)

    def _has_ancestors(self, node, targets, computed=True):
        missing = set(targets)
        seen = set()
        stack = [node]
        while stack and missing:
            current = self._expand(stack.pop())
            predecessors = [p for p in current.parents
                            if dict.get(self.nodes, p.name) is p]
            if computed:
                predecessors.extend(self._computed_parents(current))
            for parent in predecessors:
                missing.discard(parent)
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        return not missing

    def _walk_ancestors(self, node, computed=True):
        # Expansion-aware version of DAG._walk_ancestors: parents are only
        # known after a node is expanded. Yielded ancestors stay STUBS —
        # the virtual-bound test needs only their names, so an early
        # return costs the records climbed through, not the ones seen.
        seen = set()
        frontier = [node]
        while frontier:
            current = self._expand(frontier.pop())
            predecessors = [p for p in current.parents
                            if dict.get(self.nodes, p.name) is p]
            if computed:
                predecessors.extend(self._computed_parents(current))
            for parent in predecessors:
                if parent not in seen:
                    seen.add(parent)
                    frontier.append(parent)
                    yield parent

    def get_ancestors(self, node, ignore=(), computed=True):
        name = self._canonical_name(_name_of(node))
        start = self.nodes.get(name)
        if start is None:
            raise ValueError(f"Node {name} does not exist in the graph.")

        ancestors = set()
        frontier = [start]
        while frontier:
            current = self._expand(frontier.pop())
            predecessors = [p for p in current.parents
                            if dict.get(self.nodes, p.name) is p]
            if computed:
                predecessors.extend(self._computed_parents(current))
            for parent in predecessors:
                if parent in ancestors or parent in ignore:
                    continue
                ancestors.add(parent)
                frontier.append(parent)
        return ancestors

    # --------------------------------------------------------------- no writes

    def _read_only(self, *args, **kwargs):
        raise TypeError(
            "LazyOntoDAG is a read-only view: the graph invariants and "
            "commit() need the whole graph resident, so edit through "
            "EagerOntoDAG and re-publish."
        )

    put = remove = merge = _read_only
    add_edge = remove_edge = add_node = _read_only
    commit = _read_only


class SparseOntoDAG(LazyOntoDAG):
    """The partially-resident WRITER: LazyOntoDAG's residency model with the
    full OntoDAG mutation semantics (ROADMAP "writing back from a
    partially-loaded graph").

    The two problems that kept the lazy reader read-only, and how they are
    solved here:

    - **Change detection.** `EagerOntoDAG.commit()` diffs a complete record
      set; a partially-resident writer cannot enumerate what it never
      loaded. But it doesn't need to: every mutation runs on *expanded*
      nodes (the overrides below expand before touching anything), so a
      mutated node is always resident — and `self._records` already holds
      each resident node's as-loaded record. `commit()` therefore diffs the
      RESIDENT set against those baselines and stages only real changes:
      cost scales with what was touched, never with the store.
    - **Reduction locality.** Transitive reduction, cycle checks and count
      deltas are bounded by the ancestor sets and cones they walk; the
      traversal seams (`_is_reachable`, `_count_reachable`, `_live_parents`,
      `_get_affected_nodes`, plus LazyOntoDAG's read overrides) expand as
      they go, so those walks fetch what they touch and nothing else. The
      oracle test (tests/test_sparse.py) asserts byte-identical roots
      against an eager writer applying the same operations.

    Construct it over a WRITABLE store at the published base
    (``RecordStore(blobs, root=base)``), not a read-only snapshot. Cone
    caching and published cone indexes are disabled — both describe an
    immutable snapshot, which a writer is not. Whole-peer ``merge`` (an
    O(|other|) hydration) remains EagerOntoDAG's job, but ``sync`` does
    not need it: the diff-driven fold (``merge_delta``) reads only the
    records that diverged, which is exactly the cost shape a partially
    resident writer exists for.
    """

    def __init__(self, record_store):
        super().__init__(record_store, cache_cones=False)
        self._deleted = set()   # store-backed names removed since last commit
        self._payloads = {}     # payloads adopted from a peer fold; the
        #                         as-loaded record's payload always wins
        # The root of this writer's own hydrate/commit lineage — same role
        # as EagerOntoDAG.base_root (see there for why `store.root` is not
        # a substitute).
        self.base_root = getattr(record_store, "root", None)

    # ------------------------------------------------ expansion-aware seams
    #
    # dag.py's structural machinery walks `neighbors`/`parents` directly;
    # on stubs those are empty, which would silently corrupt reduction and
    # counts. Each seam expands what it walks — that is the entire cost of
    # a write: the ancestors and cones the operation genuinely touches.

    def _is_reachable(self, start, target, computed=False):
        seen = set()
        stack = [start]
        while stack:
            current = self._expand(stack.pop())
            successors = list(current.neighbors)
            if computed:
                successors.extend(self._computed_children(current))
            for neighbor in successors:
                if neighbor == target:
                    return True
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        return False

    def _count_reachable(self, start, targets):
        remaining = set(targets)
        found = 0
        seen = set()
        frontier = [start]
        while frontier and remaining:
            for neighbor in self._expand(frontier.pop()).neighbors:
                if neighbor in remaining:
                    remaining.discard(neighbor)
                    found += 1
                    if not remaining:
                        return found
                if neighbor not in seen:
                    seen.add(neighbor)
                    frontier.append(neighbor)
        return found

    def _live_parents(self, node):
        self._expand(node)
        return [p for p in node.parents
                if dict.get(self.nodes, p.name) is p]

    def _get_affected_nodes(self, node, affected):
        frontier = [node]
        while frontier:
            current = frontier.pop()
            if current in affected:
                continue
            affected.add(current)
            frontier.extend(self._live_parents(current))

    # ------------------------------------------------------------ mutations
    #
    # LazyOntoDAG blocks these with class attributes, so super() would hit
    # the guard: delegate to OntoDAG/DAG explicitly. Every entry expands its
    # endpoints first, keeping the invariant that mutated nodes are resident
    # (and therefore that _records holds their pre-change baseline).

    def add_node(self, node):
        DAG.add_node(self, node)
        # A created node is fully known: nothing in the store to expand.
        self._records.setdefault(node.name, None)
        self._expanded.add(node.name)

    def add_edge(self, from_node, to_node):
        self._expand(from_node)
        self._expand(to_node)
        OntoDAG.add_edge(self, from_node, to_node)

    def remove_edge(self, from_node, to_node):
        self._expand(from_node)
        self._expand(to_node)
        DAG.remove_edge(self, from_node, to_node)

    def put(self, subcategory, super_categories, optimized=False):
        OntoDAG.put(self, subcategory, super_categories, optimized=optimized)

    def remove(self, node_to_remove):
        name = self._canonical_name(_name_of(node_to_remove))
        persisted = name in self.nodes and self._load(name) is not None
        OntoDAG.remove(self, node_to_remove)
        self._records[name] = None      # later lookups: known absent
        self._expanded.discard(name)
        if persisted:
            self._deleted.add(name)

    # --------------------------------------------------------------- commit

    def _record_for(self, node):
        loaded = self._records.get(node.name) or {}
        payload = loaded.get("payload")     # preserved, never edited here
        if payload is None:                 # adopted from a peer fold
            payload = self._payloads.get(node.name)
        return {
            "up": sorted(p.name for p in node.parents
                         if dict.get(self.nodes, p.name) is p),
            "down": sorted(child.name for child in node.neighbors),
            "count": node.descendant_count,
            "payload": payload,
            "meta": dict(node.metadata),
        }

    def commit(self):
        """Stage the resident diff, commit, return the new root.

        Sweeps only `self._expanded` — every node a mutation could have
        touched — comparing each against its as-loaded record; unchanged
        residents stage nothing. A node re-added after removal simply
        diffs as changed, so deletion bookkeeping stays consistent."""
        for name in sorted(self._deleted):
            if name not in self.nodes:      # not re-added since
                self.store.delete(name)
        self._deleted.clear()
        for name in sorted(self._expanded):
            node = dict.get(self.nodes, name)
            if node is None:
                continue
            record = self._record_for(node)
            if self._records.get(name) != record:
                self.store.put(name, record)
                self._records[name] = record
        root = self.store.commit()
        self.base_root = root
        return root

    # ----------------------------------------------------------------- sync

    def sync(self, other_root, bytes_store=None) -> str:
        """Fold a peer's published root in and commit the union — the same
        multi-writer merge rule as ``EagerOntoDAG.sync`` (I7: commutative,
        idempotent, union re-reduced against the combined order), at the
        cost shape this writer exists for: only the diverged records are
        read (``merge_delta``), never the store."""
        if other_root is not None and other_root != self.base_root:
            self.merge_delta(other_root, bytes_store)
        return self.commit()

    def merge_delta(self, other_root, bytes_store=None) -> bool:
        """The diff-driven fold, partially resident (see
        ``EagerOntoDAG.merge_delta`` for the semantics — union of states,
        ours-win metadata and payloads, edges replayed through the
        expansion-aware ``add_edge`` so reduction and counts re-derive).

        One deliberate difference: this writer folds and commits onto its
        OWN lineage, so its store handle must still be at ``base_root``.
        Everything this graph lazily loads mid-fold comes through that
        handle, and a handle rebound to the peer's moved head would serve
        the PEER's records to plain expansions — a raw, reduction-blind
        merge through the back door. The rebind-to-moved-head flow
        (transient windows) is the eager writer's; a sparse writer that
        needs it should hand off to one.
        """
        if getattr(self.store, "root", None) != self.base_root:
            raise ValueError(
                "sparse sync needs the store at this writer's own lineage "
                f"(base_root {self.base_root!r}); a store rebound to "
                "another root would serve foreign records to lazy "
                "expansions mid-fold. Fold through EagerOntoDAG for the "
                "rebind-to-moved-head flow.")
        from ontodag._extras import require
        rs = require("recordstore", "store", "sync()")

        blobs = bytes_store or self.store.blobs
        snapshot = rs.RecordStore.at(self.base_root, blobs)
        diff = list(snapshot.diff(other_root))
        diff_keys = {key for key, _, _ in diff}

        touched = {}                     # name -> the peer-side record
        for key, _mine, theirs in diff:
            if theirs is not rs.ABSENT:
                touched[key] = theirs
            # theirs ABSENT: the union keeps ours, and committing onto our
            # own base keeps it with no staging — nothing to do.
        # Locally dirty residents and uncommitted removals: the peer's
        # record equals the as-loaded baseline whenever the key is not in
        # the diff. A removal destroyed its baseline (`_records[k] = None`),
        # so it re-reads the one record from the base snapshot.
        for name in sorted(self._expanded | self._deleted):
            if name in diff_keys or name in touched \
                    or name == self.root.name:
                continue
            baseline = self._records.get(name)
            if name in self._deleted:
                if baseline is None:
                    try:
                        baseline = snapshot.get(name)
                    except KeyError:
                        baseline = None
                if baseline is not None:
                    touched[name] = baseline
                continue
            node = dict.get(self.nodes, name)
            if node is not None and baseline is not None \
                    and self._record_for(node) != baseline:
                touched[name] = baseline

        # Pass 1: nodes, ours-win metadata and payloads.
        for key in sorted(touched):
            if key == self.root.name:
                continue
            record = touched[key]
            node = self.nodes.get(key)   # loads-and-expands from OUR base
            if node is None:
                self.add_node(Item(key, metadata=record.get("meta") or {}))
            else:
                for meta_key, value in (record.get("meta") or {}).items():
                    node.metadata.setdefault(meta_key, value)
            if record.get("payload") is not None \
                    and key not in self._payloads:
                self._payloads[key] = record["payload"]
        # Pass 2: replay the peer's asserted edges (order-free: add_edge
        # maintains the complete redundancy rectangle).
        for key in sorted(touched):
            if key == self.root.name:
                continue
            node = self.nodes[key]
            for parent_name in touched[key]["up"]:
                parent = self.nodes.get(parent_name)
                if parent is not None:
                    self.add_edge(parent, node)
        return bool(touched)
