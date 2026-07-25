"""LazyOntoDAG — query a published OntoDAG without loading all of it.

`SwarmOntoDAG` hydrates the whole store into RAM on construction (fast, but
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

**Read-only by construction.** Writing is refused, not merely discouraged:
`OntoDAG`'s guarantees (transitive reduction, exact counts) are properties of
the *whole* graph, and `SwarmOntoDAG.commit` diffs against a full set of synced
records — neither is well-defined when only part of the graph is resident. Use
`SwarmOntoDAG` to edit and publish, `LazyOntoDAG` to query what was published.

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

from ontodag.dag import Item, OntoDAG, _name_of


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

    `record_store` is duck-typed exactly as in `swarm_adapter`: ``get(key)``
    raising `KeyError` for a missing key is all a query needs (``items()`` is
    used only by `load_all`). Pass a snapshot — e.g.
    ``RecordStore.at(root, bytes_store)`` — since nothing here expects the
    store to change underneath it.
    """

    def __init__(self, record_store, cache_cones=True, max_cached_cones=64):
        super().__init__()
        self.store = record_store
        self.fetches = 0            # store.get calls; the point of all this
        self._records = {}          # name -> record (or None: known absent)
        self._expanded = set()      # names whose edges are filled in
        self._cone_cache = {} if cache_cones else None
        self._max_cached_cones = max_cached_cones
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

    # ------------------------------------------------------- traversals

    def get_descendants(self, node, visited=None):
        name = _name_of(node)
        start = self.nodes.get(name)
        if start is None:
            return set()
        if self._cone_cache is not None and name in self._cone_cache:
            return set(self._cone_cache[name])

        descendants = set()
        seen = {start}
        frontier = [start]
        while frontier:
            for child in self._expand(frontier.pop()).neighbors:
                descendants.add(child)
                if child not in seen:
                    seen.add(child)
                    frontier.append(child)
        self._cache_cone(name, descendants)
        return descendants

    def _cache_cone(self, name, descendants):
        if self._cone_cache is None:
            return
        if len(self._cone_cache) >= self._max_cached_cones:
            # insertion order: drop the oldest entry
            self._cone_cache.pop(next(iter(self._cone_cache)))
        self._cone_cache[name] = set(descendants)

    def _has_ancestors(self, node, targets):
        missing = set(targets)
        seen = set()
        stack = [node]
        while stack and missing:
            for parent in self._expand(stack.pop()).parents:
                if dict.get(self.nodes, parent.name) is not parent:
                    continue
                missing.discard(parent)
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        return not missing

    def get_ancestors(self, node, ignore=()):
        name = _name_of(node)
        start = self.nodes.get(name)
        if start is None:
            raise ValueError(f"Node {name} does not exist in the graph.")

        ancestors = set()
        frontier = [start]
        while frontier:
            for parent in self._expand(frontier.pop()).parents:
                if parent in ancestors or parent in ignore:
                    continue
                if dict.get(self.nodes, parent.name) is parent:
                    ancestors.add(parent)
                    frontier.append(parent)
        return ancestors

    # --------------------------------------------------------------- no writes

    def _read_only(self, *args, **kwargs):
        raise TypeError(
            "LazyOntoDAG is a read-only view: the graph invariants and "
            "commit() need the whole graph resident, so edit through "
            "SwarmOntoDAG and re-publish."
        )

    put = remove = merge = _read_only
    add_edge = remove_edge = add_node = _read_only
    commit = _read_only
