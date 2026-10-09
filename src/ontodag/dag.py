from collections import namedtuple
import bisect
from contextlib import contextmanager
from itertools import combinations

from ontodag import dimensions as _dims


class _EdgeSet(set):
    """A set of child Items that keeps each child's `parents` set in sync.

    Edges are object references in both directions (`neighbors` down,
    `parents` up). Several call sites — copy routines, tests building deep
    graphs — mutate `item.neighbors` directly rather than going through
    DAG.add_edge, so the reverse adjacency is maintained here in the
    container instead of in DAG methods.
    """

    def __init__(self, owner):
        super().__init__()
        self._owner = owner

    def add(self, item):
        super().add(item)
        item.parents.add(self._owner)

    def remove(self, item):
        super().remove(item)
        item.parents.discard(self._owner)

    def discard(self, item):
        if item in self:
            super().discard(item)
            item.parents.discard(self._owner)

    def update(self, *iterables):
        for iterable in iterables:
            for item in iterable:
                self.add(item)

    def clear(self):
        for item in list(self):
            self.remove(item)

    def pop(self):
        item = super().pop()
        item.parents.discard(self._owner)
        return item


class Item:
    def __init__(self, name, metadata=None):
        self.name = name
        self.parents = set()
        self.neighbors = _EdgeSet(self)
        self.descendant_count = 0
        # Non-structural annotations (e.g. a display label, an object
        # marker). Never identity: equality and hashing stay name-only.
        self.metadata = dict(metadata) if metadata else {}

    def __eq__(self, other):
        name = getattr(other, "name", None)
        if not isinstance(name, str):
            return NotImplemented     # `Item("a") == None` is False, not an error
        return self.name == name

    def __hash__(self):
        return hash(self.name)

    def __repr__(self):
        return f"Item({self.name}, [{', '.join(neighbor.name for neighbor in self.neighbors)}])"

    def to_dict(self):
        out = {
            "name": self.name,
            "neighbors": [neighbor.name for neighbor in self.neighbors],
            "descendant_count": self.descendant_count
        }
        if self.metadata:
            out["metadata"] = self.metadata
        return out


# One cone of a query plan: kind in {"node", "virtual", "overlap"}, an
# estimated size, the canonical name (tiebreak), and the payload the walk
# and the probe read (the node, or the list of values/anchors).
_Cone = namedtuple("_Cone", "kind size name payload")

#: What `OntoDAG.parse_term` reads a typed value as: its head (`mass`), the
#: head's kind (`linear-dimension`) and the canonical spelling the store
#: files it under (`mass(3kg)` for `mass(3000g)`).
Term = namedtuple("Term", "head kind canonical")


def _name_of(node_or_name):
    """Identity at the public boundary is the name: accept a plain string or
    anything with a `.name` (an Item), and return the name string."""
    return node_or_name if isinstance(node_or_name, str) else node_or_name.name


_MISSING = object()


class DAG:
    def __init__(self, nodes=None):
        self.nodes = {}
        self._version = 0
        self._counts_frozen = False  # True while an operation maintains counts itself
        if nodes:
            for node in nodes:
                self.add_node(node)

    def _changed(self):
        """Every change to the graph's shape passes here, so answers
        memoized against an older shape are dropped (`_memo_get`)."""
        self._version = getattr(self, "_version", 0) + 1

    # Answers that are pure functions of the graph's shape are memoized
    # against `_version` and dropped wholesale on any change. Bounded, so a
    # long-lived reader cannot grow it without limit.
    _MEMO_LIMIT = 200_000

    def _trip(self):
        """A re-entrancy guard answered provisionally (False, a literal,
        nothing) to break a loop in the REASONING — the graph itself may be
        acyclic: deciding where a term sits can ask about the very node
        whose ancestors are being walked. The enclosing answer is still
        right, since the search goes on through other branches, but answers
        computed under the provisional one may not be, so they must not be
        memoized (`_memo_put_unless_tripped`)."""
        self._guard_trips = getattr(self, "_guard_trips", 0) + 1

    def _trips(self):
        return getattr(self, "_guard_trips", 0)

    def _memo_put_unless_tripped(self, key, value, trips_before):
        """Memoize `value` only if no guard tripped while computing it."""
        if self._trips() == trips_before:
            self._memo_put(key, value)
        return value

    def _memo_get(self, key):
        memo = getattr(self, "_memo", None)
        if memo is None or self._memo_version != getattr(self, "_version", 0):
            return _MISSING
        return memo.get(key, _MISSING)

    def _memo_put(self, key, value):
        version = getattr(self, "_version", 0)
        memo = getattr(self, "_memo", None)
        if memo is None or self._memo_version != version \
                or len(memo) >= self._MEMO_LIMIT:
            memo = self._memo = {}
            self._memo_version = version
        memo[key] = value
        return value

    def add_node(self, node):
        """Add a node (Item) to the graph."""
        self.nodes[node.name] = node
        self._changed()

    # ---- computed order (parametric dimensions) ----------------------------
    #
    # The combined order = asserted edges ∪ computed pairs among present
    # same-dimension parametric nodes (docs/DIMENSIONS.md §5). The base DAG
    # has no dimension semantics, so the computed relation is empty here;
    # OntoDAG overrides these. Persisted counts stay asserted-only by design,
    # so every count-planning path passes computed=False explicitly, while
    # query-facing traversals default to the combined order.

    def _computed_children(self, node):
        return ()

    def _computed_parents(self, node):
        return ()

    def _canonical_name(self, name):
        return name

    def add_edge(self, from_node, to_node, _cycle_checked=False):
        """Add a directed edge between two nodes. `_cycle_checked`: the caller
        (OntoDAG.add_edge) already asked, upward and in the combined order,
        whether the edge closes a cycle; the downward walk here would cost
        the child's whole cone on every edge."""
        if from_node.name not in self.nodes or to_node.name not in self.nodes:
            raise ValueError("Both nodes must exist in the graph.")

        if from_node == to_node:
            return
        if to_node in from_node.neighbors:
            return
        if not _cycle_checked and self._is_reachable(to_node, from_node):
            raise ValueError(
                f"Edge {from_node.name} -> {to_node.name} would create a cycle."
            )

        deltas = None if self._counts_frozen else self._plan_add(from_node, to_node)
        from_node.neighbors.add(to_node)
        self._changed()
        self._apply_count_deltas(deltas)

    def _is_reachable(self, start, target, computed=False):
        """True if `target` is strictly reachable from `start` (iterative,
        early exit); `computed=True` also follows computed dimension hops."""
        seen = set()
        stack = [start]
        while stack:
            current = stack.pop()
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

    def remove_edge(self, from_node, to_node):
        # Verify nodes exist
        if from_node.name not in self.nodes or to_node.name not in self.nodes:
            raise ValueError("Both nodes must exist in the graph.")

        # Remove child from parent's neighbors
        if to_node not in from_node.neighbors:
            raise ValueError("Edge does not exist.")
        from_node.neighbors.remove(to_node)
        self._changed()
        # "can X still reach c?" is a post-state question, so plan after
        self._apply_count_deltas(
            None if self._counts_frozen else self._plan_remove(from_node, to_node))

    # ---- descendant counts, maintained by delta ---------------------------
    #
    # Counts used to be refreshed by recomputing `len(get_descendants(X))` for
    # every affected ancestor. Since the root is an ancestor of everything,
    # its cone is the whole graph, so *every* write enumerated the entire DAG:
    # per-op cost grew linearly with the graph. But which counts change is
    # local — only the touched node's ancestors — and by how much is derivable
    # from what the operation means. Both rules below prune the ascent on a
    # proof: an ancestor that already reaches the child also reaches
    # everything below it, and so does every ancestor of *that* ancestor, so
    # the whole branch is unaffected.
    #
    # Measured (experiments/delta_counts.py on the experiment/delta-counts
    # branch), per operation at ~2000 items: appends 8.9x cheaper, removals
    # 642x, cross-links 1.9x, verified against a brute-force oracle after
    # every one of ~7,600 operations. Invariant I5 is the standing check.

    @contextmanager
    def _counts_unchanged(self):
        """Structural changes whose counts are *not* this code's business:
        transitive-reduction removals (which by construction change no
        reachability, hence no count) and `remove`'s contraction (whose net
        effect the caller applies itself). Re-entrant."""
        prev, self._counts_frozen = self._counts_frozen, True
        try:
            yield
        finally:
            self._counts_frozen = prev

    def _apply_count_deltas(self, deltas):
        if deltas:
            for node, delta in deltas.items():
                node.descendant_count += delta

    def _live_parents(self, node):
        # only parents belonging to this DAG instance (a foreign Item's edges
        # are not ours to walk)
        return [p for p in node.parents if self.nodes.get(p.name) is p]

    def _count_reachable(self, start, targets):
        """How many of `targets` are reachable from `start`, exiting as soon
        as all of them are found — cheap in exactly the case that matters."""
        remaining = set(targets)
        found = 0
        seen = set()
        frontier = [start]
        while frontier and remaining:
            for neighbor in frontier.pop().neighbors:
                if neighbor in remaining:
                    remaining.discard(neighbor)
                    found += 1
                    if not remaining:
                        return found
                if neighbor not in seen:
                    seen.add(neighbor)
                    frontier.append(neighbor)
        return found

    def _plan_add(self, parent, child):
        """Count deltas for adding `parent` -> `child`, computed *before* the
        edge exists (callers that also run transitive reduction must plan
        first: reduction drops edges that are redundant only *given* the new
        edge, so planning afterwards would read ancestors as newly gaining
        what they already had)."""
        below = self.get_descendants(child, computed=False)
        # "Does this ancestor already reach child?" is asked once per walked
        # ancestor; answered downward it walks that ancestor's cone (which
        # near the root is the whole graph — ruinous in fetches for a
        # partially-resident writer, wasteful in hops everywhere). Answered
        # upward it is ONE walk over child's ancestor cone, then set
        # membership. A child with no parents yet reaches nothing and is
        # reached from nowhere — the common append-a-fresh-item case skips
        # even that walk.
        unreachable = not self._live_parents(child)
        reaches_child = frozenset() if unreachable else \
            self.get_ancestors(child, computed=False)
        deltas = {}
        frontier = [parent]
        seen = set()
        while frontier:
            node = frontier.pop()
            if node in seen:
                continue
            seen.add(node)
            if node in reaches_child:
                continue          # reaches child already, hence all below it
            gained = 1 if not below else (
                1 + len(below) - self._count_reachable(node, below))
            deltas[node] = deltas.get(node, 0) + gained
            frontier.extend(self._live_parents(node))
        return deltas

    def _plan_remove(self, parent, child):
        """Count deltas for a `parent` -> `child` edge that has just been
        removed (reachability questions are about the post-state)."""
        below = self.get_descendants(child, computed=False)
        # Upward probe, as in _plan_add: one walk over child's remaining
        # ancestor cone answers "does this node still reach child?" for
        # every walked ancestor.
        still_reaches_child = self.get_ancestors(child, computed=False)
        deltas = {}
        frontier = [parent]
        seen = set()
        while frontier:
            node = frontier.pop()
            if node in seen:
                continue
            seen.add(node)
            if node in still_reaches_child:
                continue          # still reaches child, hence all below it
            lost = 1 if not below else (
                1 + len(below) - self._count_reachable(node, below))
            deltas[node] = deltas.get(node, 0) - lost
            frontier.extend(self._live_parents(node))
        return deltas

    def _get_affected_nodes(self, node, affected):
        """Get node and all its ancestors that need count updates"""
        frontier = [node]
        while frontier:
            current = frontier.pop()
            if current in affected:
                continue
            affected.add(current)
            for parent in current.parents:
                # Only follow parents that belong to this DAG instance.
                if self.nodes.get(parent.name) is parent:
                    frontier.append(parent)

    def get_descendants(self, node, visited=None, computed=True):
        # Identity at the public boundary is the name (a plain string or an
        # Item): traverse this instance's node, not the caller's object,
        # whose neighbors may be empty (e.g. a fresh Item used to query a
        # rehydrated DAG). An unknown name has no descendants. Parametric
        # sugar canonicalizes first (weight(3000g) -> weight(3kg)), and
        # the walk follows the combined order unless `computed=False`
        # (count maintenance is asserted-only by design).
        if isinstance(node, str):
            node = self.nodes.get(self._canonical_name(node))
            if node is None:
                return set()
        else:
            node = self.nodes.get(self._canonical_name(node.name), node)
        if visited is None:
            visited = set()
        if node in visited:
            return set()
        visited.add(node)
        descendants = set()  # Descendants of the current node
        frontier = [node]
        while frontier:
            current = frontier.pop()
            successors = list(current.neighbors)
            if computed:
                successors.extend(self._computed_children(current))
            for neighbor in successors:
                descendants.add(neighbor)
                if neighbor not in visited:
                    visited.add(neighbor)
                    frontier.append(neighbor)
        return descendants

    @staticmethod
    def _expands(computed, node):
        """`computed` is a flag, or a test deciding per node whether its
        computed parents are walked (`OntoDAG._lean`)."""
        return computed(node) if callable(computed) else computed

    def _has_ancestors(self, node, targets, computed=True):
        """True if every Item in `targets` is a strict ancestor of `node`.

        A single upward walk over `parents`, early-exiting as soon as every
        target has been seen. Cost is bounded by `node`'s ancestor cone —
        shallow in typical category graphs — and never by the size of the
        graph or of any descendant cone. That bound is what makes this safe
        to call from the query planner (see `OntoDAG.get`): checking "is A an
        ancestor of X" downward from A can walk most of the graph when A is
        near the root, while checking it upward from X cannot.
        """
        missing = set(targets)
        seen = set()
        stack = [node]
        while stack and missing:
            current = stack.pop()
            predecessors = [p for p in current.parents
                            # Only follow parents that belong to this DAG.
                            if self.nodes.get(p.name) is p]
            if self._expands(computed, current):
                predecessors.extend(self._computed_parents(current))
            for parent in predecessors:
                missing.discard(parent)
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        return not missing

    def _walk_ancestors(self, node, computed=True):
        """Yield `node`'s ancestors as the upward walk reaches them —
        `get_ancestors` without the materialization, for callers that can
        stop early (`is_below`'s virtual-bound branch). Same visit set,
        same filters; a caller that exhausts it does exactly the work of
        `get_ancestors`, one that returns early does strictly less."""
        seen = set()
        frontier = [node]
        while frontier:
            current = frontier.pop()
            predecessors = [p for p in current.parents
                            # Only follow parents that belong to this DAG.
                            if self.nodes.get(p.name) is p]
            if self._expands(computed, current):
                predecessors.extend(self._computed_parents(current))
            for parent in predecessors:
                if parent not in seen:
                    seen.add(parent)
                    frontier.append(parent)
                    yield parent

    def get_ancestors(self, node, ignore=(), computed=True):
        name = self._canonical_name(_name_of(node))  # strings accepted too
        if name not in self.nodes:
            raise ValueError(f"Node {name} does not exist in the graph.")
        node = self.nodes[name]  # traverse our node, not the caller's

        ancestors = set()
        frontier = [node]
        while frontier:
            current = frontier.pop()
            predecessors = [p for p in current.parents
                            # Only follow parents that belong to this DAG.
                            if self.nodes.get(p.name) is p]
            if self._expands(computed, current):
                predecessors.extend(self._computed_parents(current))
            for parent in predecessors:
                if parent in ancestors or parent in ignore:
                    continue
                ancestors.add(parent)
                frontier.append(parent)
        return ancestors

    def intersection_dag(self, other_dag):
        intersecting_dag = OntoDAG()

        # Add fresh copies of nodes that exist in both DAGs — never the
        # source Item objects themselves, so mutating the result cannot
        # write through to either source (I4).
        mapping = {}
        for node in self.nodes.values():
            if node.name == intersecting_dag.root.name:
                continue
            if node.name in other_dag.nodes:
                copy_item = Item(node.name)
                mapping[node.name] = copy_item
                intersecting_dag.add_node(copy_item)

        for root_subcategory in other_dag.root.neighbors:
            if root_subcategory.name in self.nodes:
                intersecting_dag.root.neighbors.add(mapping[root_subcategory.name])

        return intersecting_dag

    def topological_sort(self):
        # Iterative post-order DFS (I6: no recursion, deep graphs would hit
        # the Python recursion limit).
        #
        # Every iteration point is sorted by name. `neighbors` is a set, so an
        # unsorted walk picks a different (still valid) topological order on
        # every run -- string hashing is randomized per process. That made
        # `odag show` and the OWL/Manchester exports, which both order their
        # output by this function, undiffable across runs for identical
        # content. Names are the identity at every boundary (see the identity
        # note in CLAUDE.md), so name order is the one canonical choice
        # available here.
        #
        # Root-first still holds for OntoDAG regardless of the start order:
        # post-order pushes a node only once all its descendants are done, and
        # every node is a descendant of the root, so the root is pushed last
        # and reversing puts it first.
        # Descending, because the post-order stack is reversed on the way out:
        # sorting high-to-low here makes the returned order read low-to-high.
        def by_name(items):
            return sorted(items, key=lambda item: item.name, reverse=True)

        visited = set()
        stack = []
        for start in by_name(self.nodes.values()):
            if start in visited:
                continue
            visited.add(start)
            path = [(start, iter(by_name(start.neighbors)))]
            while path:
                node, neighbors = path[-1]
                for neighbor in neighbors:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        path.append((neighbor, iter(by_name(neighbor.neighbors))))
                        break
                else:
                    stack.append(node)
                    path.pop()
        # Nodes in topological order, with the root first
        return stack[::-1]


_NEG, _POS = float("-inf"), float("inf")


class _Intervals:
    """The values of one interval head (linear, calendar, count), sorted
    by lower bound, so a value's hops are a range rather than a scan
    (`OntoDAG._hops`). Points can contain only themselves, so the values
    containing a given one are looked for among the wide ones alone."""

    def __init__(self, units):
        self.units = units
        self.family = None
        self.entries, self.los = [], []
        self.wide, self.wide_los = [], []

    def _bounds(self, dag, name, kind, units):
        split = _dims.split_term(name)
        if split is None:
            return None
        if kind is None:
            kind = dag._dimension_kind(split[0])
        try:
            family, lo, hi = _dims._denotation(
                split[1], kind, dag._declared_units() if units is None else units)
        except ValueError:
            return None
        return family, (_NEG if lo is None else lo), (_POS if hi is None else hi)

    def add(self, dag, name, units=None, kind=None):
        bounds = self._bounds(dag, name, kind, units)
        if bounds is None:
            return False
        family, lo, hi = bounds
        if self.family is None:
            self.family = family
        elif family != self.family:
            return False
        entry = (lo, hi, name)
        at = bisect.bisect_left(self.entries, entry)
        if at < len(self.entries) and self.entries[at] == entry:
            return True
        self.entries.insert(at, entry)
        self.los.insert(at, lo)
        if lo != hi:
            at = bisect.bisect_left(self.wide, entry)
            self.wide.insert(at, entry)
            self.wide_los.insert(at, lo)
        return True

    def hops(self, dag, canonical, head, kind, up):
        bounds = self._bounds(dag, canonical, kind, None)
        if bounds is None or (self.family is not None
                              and bounds[0] != self.family):
            return None          # let the scan raise the teaching error
        _family, lo, hi = bounds
        out = []
        if up:
            for wlo, whi, name in self.wide:
                if wlo > lo:
                    break
                if whi >= hi and name != canonical:
                    out.append(name)
            return out
        for at in range(bisect.bisect_left(self.los, lo), len(self.entries)):
            elo, ehi, name = self.entries[at]
            if elo > hi:
                break
            if ehi <= hi and name != canonical:
                out.append(name)
        return out


class _Prefixes:
    """The values of one prefix head, sorted: a cell's finer cells are a
    range, and its coarser ones are its own prefixes (`OntoDAG._hops`).
    For a role head (`literal_role`), the literal parameters of its terms
    (`from(u2e4)`), whatever else its star holds."""

    def __init__(self, units, literal_role=None):
        self.units = units
        self.literal_role = literal_role
        self.params = []

    def add(self, dag, name, units=None, kind=None):
        split = _dims.split_term(name)
        if split is None:
            return False
        if self.literal_role is not None:
            if split[0] != self.literal_role:
                return True
            try:
                if dag._param_node(split[0], split[1]) is not None:
                    return True           # names a node, found by the walk
                _dims._parse_prefix(split[1])
            except ValueError:
                return True
        else:
            try:
                _dims._parse_prefix(split[1])
            except ValueError:
                return False
        at = bisect.bisect_left(self.params, split[1])
        if at == len(self.params) or self.params[at] != split[1]:
            self.params.insert(at, split[1])
        return True

    def below(self, prefix, head):
        """Names `head(q)` for the indexed q that extend `prefix`."""
        out = []
        for other in self.params[bisect.bisect_left(self.params, prefix):]:
            if not other.startswith(prefix):
                break
            if other != prefix:
                out.append(f"{head}({other})")
        return out

    def hops(self, dag, canonical, head, kind, up):
        param = _dims.split_term(canonical)[1]
        if up:
            names = (f"{head}({param[:k]})" for k in range(1, len(param)))
            return [name for name in names if name in dag.nodes]
        out = []
        for other in self.params[bisect.bisect_left(self.params, param):]:
            if not other.startswith(param):
                break
            if other != param:
                out.append(f"{head}({other})")
        return out


class OntoDAG(DAG):
    def __init__(self):
        super().__init__()
        self.root = Item("*")
        self.nodes[self.root.name] = self.root

    # ---- parametric dimensions (docs/DIMENSIONS.md) -------------------------
    #
    # A dimension head is an ordinary node asserted under a registry kind node
    # (mass -> linear-dimension(mass) -> linear-dimension); its used values are parametric nodes
    # (weight(3kg)) anchored under it by a schema edge — the "star".
    # The order *within* a dimension is computed from the names and never
    # materialized as edges (dense orders have no transitive reduction).

    def _dimension_kind(self, head_name):
        """The registry kind a declared dimension head inherits, or None."""
        return self._dimension_of(head_name)[0]

    def _looks_like_value(self, node):
        """Syntactic anchor test — `head(param)` with a parent named `head`.
        No parse and no walk, so the declaration walk can afford it."""
        split = _dims.split_term(node.name)
        if split is None or _dims.is_kind_node(node.name):
            return False      # `linear-dimension(mass)` is a kind node, not a value
        return any(parent.name == split[0] for parent in node.parents)

    def _kind_walk_parents(self, node):
        """The parents the declaration walk follows: this DAG's own, with
        parametric VALUES left out. A value is a leaf of the declaration
        walk, not a link in a head chain — a place filed under a geohash
        cell is not thereby a dimension head, whatever its name looks like.
        Seam for the lazy reader, which expands as it walks."""
        return [parent for parent in node.parents
                if self.nodes.get(parent.name) is parent
                and not self._looks_like_value(parent)]

    def _dimension_of(self, head_name):
        """(kind, base) for a declared dimension head, (None, None) otherwise.

        The kind is the registry node the head inherits (ancestor walk from
        the head to a kind node; inheriting two different kinds is an error,
        not an MRO puzzle — DIMENSIONS.md §3). The *base* is the head
        directly under the kind node on that walk: the dimension's own head.
        A head whose base is another head is a ROLE of that dimension
        (`from` under `geo`, DIMENSIONS.md §14): it shares the value space
        and the kind, and its parameters may name the base dimension's
        nodes. The walk stops at kind nodes, so kind nodes themselves and
        plain categories resolve to (None, None).

        Cached per DAG (issue #18): every containment or overlap decision
        on a role star re-asks this for each member — tens of thousands of
        walks per query on a names-heavy graph — and the answer changes
        only when an edge from a kind node or a head to a plain node is
        added or removed, which is exactly when `_heads` is invalidated
        (`_maybe_invalidate_heads`; `_forget`). Absent names are not
        cached (they may appear), and an ambiguous declaration raises
        uncached, so the error stays loud at every use."""
        node = self.nodes.get(head_name)
        if node is None or _dims.is_kind_node(head_name):
            return None, None
        cache = getattr(self, "_dim_cache", None)
        if cache is None:
            cache = self._dim_cache = {}
        elif head_name in cache:
            return cache[head_name][:2]
        kinds, bases, families = set(), set(), set()
        seen = {node}
        stack = [node]
        while stack:
            current = stack.pop()
            for parent in self._kind_walk_parents(current):
                found = _dims.kind_node(parent.name)
                if found is not None:
                    kinds.add(found[0])
                    bases.add(current.name)
                    if found[1] is not None:
                        families.add(found[1])
                elif parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        if len(kinds) > 1:
            raise ValueError(
                f"dimension {head_name!r} inherits multiple kinds: "
                f"{', '.join(sorted(kinds))} — declare exactly one")
        if not kinds:
            cache[head_name] = (None, None, frozenset())
            return None, None
        if len(bases) > 1:
            raise ValueError(
                f"dimension head {head_name!r} belongs to several "
                f"dimensions: {', '.join(sorted(bases))} — a role has "
                f"exactly one base")
        cache[head_name] = (next(iter(kinds)), next(iter(bases)),
                            frozenset(families))
        return cache[head_name][:2]

    def _refuse_pin_over_values(self, parent_name, head_name):
        """Pinning a head (`mass ⊑ linear-dimension(mass)`) that already
        holds values of another family would leave them unreadable: refuse
        it, naming one. Its roles' values are checked too, since a role
        inherits its base's pin. Merges skip this (they stay total) and
        the disagreement surfaces when values are compared."""
        found = _dims.kind_node(parent_name)
        if found is None or found[1] is None \
                or found[0] not in _dims.FAMILY_KINDS:
            return
        kind, family = found
        heads = [head_name] + sorted(
            h for h, (_, base) in self._heads().items()
            if base == head_name and h != head_name)
        units = self._declared_units()
        for head in heads:
            for value, _ in self._star(head):
                param = _dims.split_term(value.name)[1]
                if self._param_node(head, param) is not None:
                    continue
                other = _dims.family_of(value.name, kind, units=units)
                if other != family:
                    raise ValueError(
                        f"cannot pin {head_name!r} to {family}: it already "
                        f"holds {value.name}, which is {other}")

    def _ensure_family_node(self, name):
        """Materialize a family pin (`linear-dimension(mass)`) on first use,
        under its kind node, as a value is materialized under its head."""
        found = _dims.kind_node(name)
        if found is None or found[1] is None or found[0] not in self.nodes:
            return
        node = Item(name)
        self.add_node(node)
        self.add_edge(self.nodes[found[0]], node)

    def _head_family(self, head_name):
        """The unit family a head is pinned to (`mass ⊑
        linear-dimension(mass)`, ROLES.md §8 item 21), or None for an
        unpinned head, whose first value decides. A role inherits its
        base's pin. Two pins (two merged stores that disagree) and a pin
        naming no known family are refused here, at use: merge itself
        stays total."""
        if self._dimension_of(head_name)[0] is None:
            return None
        families = self._dim_cache[head_name][2]
        if not families:
            return None
        if len(families) > 1:
            raise ValueError(
                f"dimension {head_name!r} is pinned to several unit "
                f"families: {', '.join(sorted(families))} — two merged "
                f"stores disagree; keep one pin")
        family = next(iter(families))
        if family not in _dims.known_families(self._declared_units()):
            raise ValueError(
                f"dimension {head_name!r} is pinned to {family!r}, which is "
                f"no unit family (declare it with "
                f"put 'unit-family({family})' unit-declaration, or fix the pin)")
        return family

    def _heads(self):
        """Every declared head -> (kind, base), walked DOWN from the kind
        nodes through plain (non-parametric) children. Cached — the only
        edges that can change it are a kind node or a head gaining or losing
        a plain child, and `add_edge`/`remove_edge`/`_forget` invalidate on
        exactly those; hydration bypasses `add_edge`, so the cache starts
        empty and builds on first use."""
        cached = getattr(self, "_heads_cache", None)
        if cached is not None:
            return cached
        heads = {}
        for kind in sorted(_dims.KINDS):
            kind_node = self.nodes.get(kind)
            if kind_node is None:
                continue
            stack = list(kind_node.neighbors)
            while stack:
                name = stack.pop().name
                pin = _dims.kind_node(name)
                if pin is None and _dims.split_term(name) is not None:
                    # A value: never a head, so skipped by its name. Fetching
                    # it first made a lazy store's first walk fetch every
                    # value of every head (1,237 fetches for 1,200 values).
                    continue
                child = self.nodes.get(name)               # expands on lazy
                if child is not None and pin not in (None, (name, None)):
                    stack.extend(child.neighbors)          # a family pin
                    continue
                if child is None or child.name in heads \
                        or _dims.is_kind_node(child.name) \
                        or _dims.split_term(child.name) is not None:
                    continue
                try:
                    kind_of, base = self._dimension_of(child.name)
                except ValueError:
                    continue      # ambiguous declarations refuse at use
                if kind_of is None:
                    continue
                heads[child.name] = (kind_of, base)
                stack.extend(child.neighbors)
        self._heads_cache = heads
        return heads

    def _relation_kind(self, name):
        """The kind of `name` when it is a head of a relation kind (§16–§18),
        else None. Quiet about an ambiguous head: while an edge declaring
        one head under another is being placed, the head belongs to two
        dimensions until pruning drops its old kind edge."""
        if _dims.is_kind_node(name) or _dims.split_term(name) is not None:
            return None
        try:
            kind = self._dimension_kind(name)
        except ValueError:
            return None
        return kind if kind in _dims.RELATION_KINDS else None

    def _related_heads(self, a, b):
        """Is one of two heads a narrower relation of the other (or the
        same head)? Then their terms compare (§20)."""
        return a == b or a in self._narrower(b) or b in self._narrower(a)

    def _relation_cache(self):
        """Per-shape cache for `_broader`/`_narrower`, living exactly as long
        as the `_dimension_of` cache, which every edge that can change a
        head's place drops."""
        dims_cache = getattr(self, "_dim_cache", None)
        if dims_cache is None:
            dims_cache = self._dim_cache = {}
        cached = getattr(self, "_rel_cache", None)
        if cached is None or cached[0] is not dims_cache:
            cached = self._rel_cache = (dims_cache, {})
        return cached[1]

    def _broader(self, head):
        """`head` and the relations it is narrower than (ROLES.md §4,
        DIMENSIONS.md §20): the heads of its kind it is declared under.

        A head of a relation kind filed under another head of the same kind
        names a NARROWER relation: `departure ⊑ from` makes every
        `departure(x)` a `from(x)`. Elsewhere a head under a head is a role
        that takes its base's values (§14), or for the graph kind a head of
        its own; a relation's argument is any node, so for these kinds only
        the narrower reading says anything. One upward walk from the head."""
        kind = self._relation_kind(head)
        if kind is None:
            return frozenset((head,))
        cache = self._relation_cache()
        hit = cache.get(("up", head))
        if hit is not None:
            return hit
        out, stack = {head}, [self.nodes.get(head)]
        while stack:
            node = stack.pop()
            if node is None:
                continue
            for parent in self._kind_walk_parents(node):
                if parent.name not in out \
                        and self._relation_kind(parent.name) == kind:
                    out.add(parent.name)
                    stack.append(parent)
        cache[("up", head)] = found = frozenset(out)
        return found

    def _narrower(self, head):
        """`head` and the relations narrower than it: the heads of its kind
        declared under it. One downward walk through the head's plain
        children (its terms are skipped by name, so a lazy reader fetches
        the head and the narrower heads, never the terms)."""
        kind = self._relation_kind(head)
        if kind is None:
            return frozenset((head,))
        cache = self._relation_cache()
        hit = cache.get(("down", head))
        if hit is not None:
            return hit
        out, stack = {head}, [head]
        while stack:
            node = self.nodes.get(stack.pop())
            if node is None:
                continue
            for child in list(node.neighbors):
                if child.name not in out \
                        and _dims.split_term(child.name) is None \
                        and self._relation_kind(child.name) == kind:
                    out.add(child.name)
                    stack.append(child.name)
        cache[("down", head)] = found = frozenset(out)
        return found

    def _role_heads(self):
        """role head -> base head, for every role declared in the graph."""
        return {name: base for name, (_kind, base) in self._heads().items()
                if base != name}

    def _maybe_invalidate_heads(self, from_node, to_node):
        """An edge from a kind node or a head to a PLAIN node can create or
        retire a head (or a role), and change what dimension the nodes
        below it belong to; nothing else can. Both caches go together:
        `_heads` decides "is `from_node` a head" without a walk while it is
        populated; when it is not, the `_dimension_of` cache is dropped on
        every plain edge instead — conservative, and free of the upward
        walk a lazy writer could not afford on each put."""
        if _dims.split_term(to_node.name) is not None \
                and not _dims.is_kind_node(to_node.name):
            return
        cached = getattr(self, "_heads_cache", None)
        if cached is None:
            self._dim_cache = None
            return
        if _dims.is_kind_node(from_node.name) or from_node.name in cached:
            self._heads_cache = None
            self._dim_cache = None

    def _note_star_child(self, head, child):
        """Keep a head's cached value index equal to its star. A value joins
        the star by its anchor edge, which is not always made when the node
        is: a load creates every node first and files them afterwards, so
        the index may have been built from a star the value was not yet in.
        Adding is idempotent; a child that is no value (a role head under
        `geo`) leaves the head unindexable, as building from the star would."""
        values = getattr(self, "_values", None)
        if values is None or head.name not in values:
            return
        index = values[head.name]
        if index is None or not index.add(self, child.name):
            del values[head.name]

    def remove_edge(self, from_node, to_node):
        self._maybe_invalidate_heads(from_node, to_node)
        values = getattr(self, "_values", None)
        if values is not None:
            values.pop(from_node.name, None)        # rebuilt from the star on use
        super().remove_edge(from_node, to_node)
        self._note_escape(from_node, to_node, added=False)
        log = getattr(self, "_edge_log", None)
        if log is not None:
            log.append((from_node, to_node))

    # ---- role parameters that name nodes (DIMENSIONS.md §14) --------------

    def _param_node(self, head, param):
        """The node a role term's parameter names, or None when the parameter
        is a literal value. Only ROLE heads look parameters up — a base
        head's parameters are values by definition, however a place happens
        to be named — and a present node OUTSIDE the role's dimension is
        refused rather than read as a value that spells the same."""
        kind, base = self._dimension_of(head)
        if kind in _dims.GRAPH_ORDERED or base is None or base == head:
            return None                  # a category term's parameter is constraints
        if param == base:
            # The dimension itself is not a place in it. "From anywhere" is
            # said by saying no from(...) at all: an item that states no
            # value of a head is unconstrained on it and passes every
            # overlap term of that head unvisited (§8). A term for the
            # whole space would only ever be redundant beside anything
            # finer — the overlap of everything with A is A (Peter,
            # 2026-09-12) — so it is refused rather than carried.
            raise ValueError(
                f"{head}({param}): {param!r} is the dimension itself, not a "
                f"value or a place in it — an item that is {head} anywhere "
                f"states no {head}(...) at all")
        node = self.nodes.get(param)
        if node is None or _dims.is_kind_node(node.name):
            return None
        # Interpretation can loop without the graph cycling: deciding whether
        # `offer` is in the dimension walks below/above it, and a role term
        # met on the way parses its own parameter. Re-entry on the same
        # (head, param) reads the parameter as a literal — fail closed.
        active = getattr(self, "_param_active", None)
        if active is None:
            active = self._param_active = set()
        if (head, param) in active:
            self._trip()
            return None
        active.add((head, param))
        try:
            inside = self._in_dimension(node, base)
        finally:
            active.discard((head, param))
        if not inside and getattr(self, "_role_lenient", 0):
            # A replay (merge, sync) adds nodes edgeless before their edges:
            # the node is momentarily outside, and as an isolated node it
            # relates to nothing — safe for reduction, which re-runs when
            # its edges land. The loud refusal is for authors, not replays.
            return node
        if not inside:
            raise ValueError(
                f"{head}({param}): {param!r} names a category outside the "
                f"{base!r} dimension — a role of {base!r} takes its values "
                f"or the categories filed in it (a place under a cell, a "
                f"region above cells), never a category from elsewhere")
        return node

    @contextmanager
    def _lenient_roles(self, total=True):
        """A replay (CONTRACT.md G9) lands names before the filings that
        place them, so inside this block a role parameter naming a
        not-yet-placed node is an isolated node rather than a refusal
        (`_param_node`), creating a category a role term names is not
        refused, and a compound's respelling waits for `_respell_deferred`.

        A TOTAL replay — merge, sync, loading a stored file — also keeps
        what an author would be refused: two values of one head that cannot
        both hold, something inside itself, a rule, two unit families under
        one head. A merge must stay total, and a store a merge made must
        open again. `ingest` replays with `total=False`: as order-free as
        the others, but those guards refuse its stream (G9, case 3)."""
        self._role_lenient = getattr(self, "_role_lenient", 0) + 1
        if total:
            self._replay_total = getattr(self, "_replay_total", 0) + 1
        try:
            yield
        finally:
            self._role_lenient -= 1
            if total:
                self._replay_total -= 1

    def _total(self):
        """Inside a total replay (`_lenient_roles`)?"""
        return getattr(self, "_replay_total", 0)

    def _in_dimension(self, node, base):
        """Is `node` a member of the dimension headed by `base`: below its
        head (a place under a cell), or above some value of it (a region)?"""
        base_node = self.nodes.get(base)
        if base_node is None:
            return False
        # Asserted edges suffice upward: every value hangs under its head by
        # its anchor edge, so anything below a value reaches the head
        # without a computed hop — and the computed walk would parse every
        # role star it passes, re-entering this very question.
        if node is base_node \
                or self._has_ancestors(node, (base_node,), computed=False):
            return True
        for value in self._values_below(node):
            if self._dimension_of(self._parse_parametric(value.name)[0])[1] \
                    == base:
                return True
        return False

    def _values_below(self, node):
        """Parametric nodes below `node` along ASSERTED edges, not descending
        past one (finer cells under a covered cell add nothing to what the
        node covers). Refetches by name so the lazy reader expands."""
        seen = {node.name}
        stack = [node]
        while stack:
            current = self.nodes.get(stack.pop().name)
            if current is None:
                continue
            for child in current.neighbors:
                if child.name in seen:
                    continue
                seen.add(child.name)
                if self._parse_parametric(child.name) is not None:
                    yield self.nodes.get(child.name)
                else:
                    stack.append(child)

    def _role_terms_naming(self, name):
        """Present role terms whose parameter names `name` (`from(my_home)`
        for `my_home`) — the terms that would change meaning if it moved.

        Only roles of a value dimension take a node as a value of their
        base (§14). A head the graph orders, declared under another head
        (`courier ⊑ transport`), names any node by constraint, as its base
        does, so its terms keep nothing inside a dimension: moving `bicycle`
        under `courier(bicycle)` is as free as under `transport(bicycle)`.
        Until 2026-10-07 such terms were taken for roles here, and moves
        were refused with a message about the base's dimension. (Removal is
        another matter: no term may be left naming nothing, whatever its
        kind, `_refuse_if_named`.)"""
        return [self.nodes[term] for term in
                (f"{role}({name})" for role in sorted(self._role_heads())
                 if self._dimension_kind(role) not in _dims.GRAPH_ORDERED)
                if term in self.nodes]

    def _check_role_parameters(self, name):
        """Refuse, as a single write would have, a role parameter left
        outside its dimension around `name`: `name` a role term whose
        parameter names a category outside the dimension, or a category a
        role term names, filed outside it. A replay files names before the
        filings that place them (CONTRACT.md G9, case 2), so `ingest`, which
        refuses a contradiction, asks this of each name once its whole
        stream is in."""
        if name not in self.nodes:
            return
        terms = self._role_terms_naming(name)
        if _dims.split_term(name) is not None:
            terms.append(self.nodes[name])
        for term in terms:
            head, param = _dims.split_term(term.name)
            self._param_node(head, param)          # raises when outside

    def _below_guarded(self, sub, sup):
        """`is_below` with a re-entrancy guard: a place filed under a role
        term of itself would otherwise recurse forever. Fail closed."""
        guard = getattr(self, "_role_guard", None)
        if guard is None:
            guard = self._role_guard = set()
        key = (sub, sup)
        if key in guard:
            self._trip()
            return False
        guard.add(key)
        try:
            return self.is_below(sub, sup)
        finally:
            guard.discard(key)

    def _contains(self, outer, inner, kind):
        """denotation(inner) ⊆ denotation(outer) over the combined order:
        arithmetic between values (`dimensions.contains`), the GRAPH when a
        role parameter names a node — `from(x) ⊑ from(y)` iff x ⊑ y in the
        base dimension, values spelled as terms of the base head. So a
        place is below the cells above it, a region is above the cells it
        covers, and two floors of one building are siblings even though
        they share a cell."""
        if kind in _dims.GRAPH_ORDERED:
            return self._graph_contains(outer, inner, kind)
        head, param_outer, param_inner = _dims._same_head(outer, inner)
        node_outer = self._param_node(head, param_outer)
        node_inner = self._param_node(head, param_inner)
        if node_outer is None and node_inner is None:
            try:
                return _dims.contains(outer, inner, kind,
                                      units=self._declared_units())
            except _dims.FamilyMismatch:
                if self._total():
                    # A merge brought values of two families under one head.
                    # Different families never contain each other, so the
                    # replay goes on; comparing them later is refused.
                    return False
                raise
        base = self._dimension_of(head)[1]
        sub = node_inner.name if node_inner is not None \
            else f"{base}({param_inner})"
        sup = node_outer.name if node_outer is not None \
            else f"{base}({param_outer})"
        return self._below_guarded(sub, sup)

    def _fold_meet(self, upper, head, value, kind):
        """upper[head] := upper[head] ∩ value (None once provably empty)."""
        if head not in upper:
            upper[head] = value
        elif upper[head] is not None:
            upper[head] = self._intersect(upper[head], value, kind)

    def _bounds(self, name):
        """What a term or node is known to lie within and known to cover:
        (upper, lower) — `upper` maps head -> the MEET of the parametric
        values above it (the finest cell a place sits in), `lower` maps
        head -> the parametric values below it (the cells a region covers).
        A value term is both its own upper and lower bound; a role term
        whose parameter names a node carries that node's bounds respelled
        under the role. The two are what `overlaps` compares."""
        active = getattr(self, "_bounds_active", None)
        if active is None:
            active = self._bounds_active = set()
        if name in active:
            self._trip()
            return {}, {}
        active.add(name)
        try:
            return self._bounds_uncached(name)
        finally:
            active.discard(name)

    def _bounds_uncached(self, name):
        parsed = self._parse_parametric(name)
        if parsed is not None:
            head, kind, canonical = parsed
            param = _dims.split_term(canonical)[1]
            node = self._param_node(head, param)
            if node is None:
                return {head: canonical}, {head: {canonical}}
            base = self._dimension_of(head)[1]
            upper_raw, lower_raw = self._node_bounds(node)
            respell = lambda term: f"{head}({_dims.split_term(term)[1]})"
            upper, lower = {}, {}
            for other, value in upper_raw.items():
                if self._dimension_of(other)[1] == base:
                    self._fold_meet(upper, head, respell(value), kind)
            for other, values in lower_raw.items():
                if self._dimension_of(other)[1] == base:
                    lower.setdefault(head, set()).update(
                        respell(v) for v in values)
            return ({h: v for h, v in upper.items() if v is not None},
                    lower)
        node = self.nodes.get(name)
        if node is None:
            return {}, {}
        return self._node_bounds(node)

    def _node_bounds(self, node):
        upper, lower = {}, {}
        for ancestor in self._walk_ancestors(node):
            parsed = self._parse_parametric(ancestor.name)
            if parsed is None:
                continue
            head, kind, canonical = parsed
            if self._param_node(head, _dims.split_term(canonical)[1]) is None:
                self._fold_meet(upper, head, canonical, kind)
            else:
                inner, _ = self._bounds(canonical)
                if head in inner:
                    self._fold_meet(upper, head, inner[head], kind)
        for value in self._values_below(node):
            head, kind, canonical = self._parse_parametric(value.name)
            if self._param_node(head, _dims.split_term(canonical)[1]) is None:
                lower.setdefault(head, set()).add(canonical)
            else:
                _, inner = self._bounds(canonical)
                lower.setdefault(head, set()).update(inner.get(head, ()))
        return {h: v for h, v in upper.items() if v is not None}, lower

    def _overlap(self, a, b):
        """Do the denotations of `a` and `b` share a point — as far as the
        graph and the arithmetic can tell? Terms or node names, any mix.

        Values decide by arithmetic. Nodes are individuated by the graph:
        two named places overlap when one is below the other, or when what
        one is known to COVER (its lower bound) meets what the other lies
        within or covers. What is deliberately excluded is upper × upper —
        two distinct named places under the same cell are two places, not
        one — so a ground-floor courier and a fourth-floor want never
        match, while a give to the whole building serves the fourth floor
        (it is below the building). The possibly-satisfies mode of
        `get_overlapping`, generalized to pairs (G6)."""
        if self._below_guarded(a, b) or self._below_guarded(b, a):
            return True
        upper_a, lower_a = self._bounds(a)
        upper_b, lower_b = self._bounds(b)

        def meets(low, up, lows):
            for head, values in low.items():
                kind = self._dimension_of(head)[0]
                if kind in _dims.GRAPH_ORDERED:
                    # No disjointness: any term of this head, or of one
                    # narrower than it, on the other side overlaps (§20).
                    narrower = self._narrower(head)
                    if any(h in narrower for h in [*up, *lows]):
                        return True
                    continue
                others = set(lows.get(head, ()))
                if head in up:
                    others.add(up[head])
                for u in values:
                    for w in others:
                        if self._intersect(u, w, kind) is not None:
                            return True
            return False
        return meets(lower_a, upper_b, lower_b) or meets(lower_b, upper_a, {})

    def _overlap_terms(self, a, b, kind):
        """`_overlap` for two same-head terms — arithmetic when both
        parameters are values, the general rule otherwise."""
        if kind in _dims.GRAPH_ORDERED:
            # Categories carry no disjointness, so two terms of one head,
            # or of a relation and a narrower one (§20), always overlap.
            return True
        head, param_a, param_b = _dims._same_head(a, b)
        if self._param_node(head, param_a) is None \
                and self._param_node(head, param_b) is None:
            return self._intersect(a, b, kind) is not None
        return self._overlap(a, b)

    def _intersect(self, a, b, kind):
        """`dimensions.intersect` with the graph kind routed to the
        graph: the meet of two constraint terms is their union, reduced."""
        if kind in _dims.GRAPH_ORDERED:
            # For a transitive head the union is only a WITNESS below both
            # terms (never empty: categories carry no disjointness), not
            # their meet — `meet` and canonical placement treat it so.
            return self._graph_intersect(a, b)
        return _dims.intersect(a, b, kind, units=self._declared_units())

    # ---- the graph kind: constraints on the graph itself (#19) ---------

    def _graph_contains(self, outer, inner, kind=_dims.KIND_GRAPH):
        key = ("contains", outer, inner, kind)
        hit = self._memo_get(key)
        if hit is not _MISSING:
            return hit
        trips = self._trips()
        return self._memo_put_unless_tripped(
            key, self._graph_contains_uncached(outer, inner, kind), trips)

    def _graph_contains_uncached(self, outer, inner, kind):
        """denotation(inner) ⊆ denotation(outer) for two same-head category
        terms: every constraint of `outer` is above (or is) some constraint
        of `inner` — a thing meeting all of `inner`'s constraints meets all
        of `outer`'s. `H(bicycle weight(5kg)) ⊑ H(small-item weight(..8kg))`
        when `bicycle ⊑ small-item`. Constraints are nodes or terms of
        other dimensions, ordered by `is_below` either way; distinct heads
        are incomparable here, as with every other kind (a role's star is
        its own)."""
        head_o, param_o = _dims.split_term(outer)
        head_i, param_i = _dims.split_term(inner)
        if head_o != head_i:
            if head_o in self._narrower(head_i):
                return False      # something from x need not depart from it
            if head_i not in self._narrower(head_o):
                raise ValueError(
                    f"cannot compare across heads: {outer!r} vs {inner!r}")
            # A narrower relation (§20): departure(x) ⊑ from(y) exactly when
            # from(x) ⊑ from(y), since departure(x) ⊑ from(x) and nothing
            # else relates the two heads. (A broader term is never inside a
            # narrower one: something from x need not depart from it.)
            inner = f"{head_o}({param_i})"
            return self._graph_contains(outer, inner, kind)
        ins = _dims.constraints(param_i)
        outs = _dims.constraints(param_o)
        if kind == _dims.KIND_REVERSED:
            # The order runs against the graph (DIMENSIONS.md §18): what is
            # for the whole of `inner`'s audience is for every part of it,
            # so `inner ⊑ outer` when `outer`'s audience lies inside
            # `inner`'s — every constraint of `inner` is above (or is) some
            # constraint of `outer`. Alice a sales employee puts
            # shared-with(sales-employee) inside shared-with(alice). Kinds only: no `in`.
            return all(any(a == x or self._below_guarded(a, x) for a in outs)
                       for x in ins)
        if all(any(x == a or self._below_guarded(x, a) for x in ins)
               for a in outs):
            return True
        if kind == _dims.KIND_TRANSITIVE:
            # A transitive relation also chains (DIMENSIONS.md §16): when
            # some x is itself related to an `outer` thing, so is whatever
            # is related to x. Tokyo in Japan puts in(tokyo) inside in(japan).
            return any(self._within(x, outer, head_o) for x in ins)
        if kind == _dims.KIND_ENCLOSING and self._dimension_kind(
                _dims.CONTAINMENT_HEAD) == _dims.KIND_TRANSITIVE:
            # An enclosing relation follows containment (§17): when some
            # x is itself located in an `outer` thing, whatever is related
            # to x is related to that thing. A photo about Tokyo is about
            # Japan once Tokyo is in Japan.
            located = f"{_dims.CONTAINMENT_HEAD}({param_o})"
            try:
                self._canonical_name(located)
            except ValueError:
                # `outer` names a constraint that has since been removed
                # (`about(c3 c5)`, then `remove c5`): nothing is inside
                # what no longer exists (raised until 2026-10-09).
                return False
            return any(self._within(x, located, _dims.CONTAINMENT_HEAD)
                       for x in ins)
        return False

    def _within(self, name, outer, head):
        """Is `name` below `outer`, a term of the transitive `head`? Asked
        by the transitive and enclosing rules, and answered by a worklist
        rather than by `is_below`, which would recurse once per level of
        containment: a chain of two hundred places ran out of stack (I6).

        `name` is below `outer` when one of its ancestors is a term
        `head(Z…)` inside `outer`: by the graph rule (every constraint of
        `outer` above some z), or because some z is itself below `outer`,
        which is the same question one container further out. So each z
        joins the worklist, and the containers are walked outward until
        the rule is met or they run out. The graph rule's own questions
        are about plain constraints, answered by an upward walk.

        Every container the search settles is memoized, which is what keeps
        a scan over a head's terms linear: on a miss, everything explored
        misses too (each container's search lies inside the one just
        exhausted), and on a hit, so does every container on the path."""
        key = ("within", name, outer)
        hit = self._memo_get(key)
        if hit is not _MISSING:
            return hit
        trips = self._trips()
        outs = _dims.constraints(_dims.split_term(outer)[1])
        heads = self._narrower(head)     # x ⊑ inside(y) puts x in y (§20)

        def meets(term):
            zs = _dims.constraints(_dims.split_term(term)[1])
            return all(any(z == a or self._below_guarded(z, a) for z in zs)
                       for a in outs), zs

        hit_at = None
        came_from = {name: None}
        frontier = [name]
        while frontier and hit_at is None:
            current = frontier.pop()
            known = self._memo_get(("within", current, outer))
            if known is True:
                hit_at = current
                break
            if known is False:
                continue
            node = self.nodes.get(current)
            if node is None:
                # A virtual term as a constraint (in(in(japan)) names
                # in(japan)): rare, and only as deep as names nest.
                if self._below_guarded(current, outer):
                    hit_at = current
                continue
            for ancestor in [node, *self._walk_ancestors(node, computed=self._lean)]:
                split = _dims.split_term(ancestor.name)
                if split is None or split[0] not in heads \
                        or self._parse_parametric(ancestor.name) is None:
                    continue
                ok, zs = meets(ancestor.name)
                if ok:
                    hit_at = current
                    break
                for z in zs:
                    if z not in came_from:
                        came_from[z] = current
                        frontier.append(z)
        if self._trips() != trips:
            return hit_at is not None
        if hit_at is None:
            for z in came_from:
                self._memo_put(("within", z, outer), False)
            return False
        while hit_at is not None:
            self._memo_put(("within", hit_at, outer), True)
            hit_at = came_from[hit_at]
        return True

    def _graph_intersect(self, a, b):
        """The meet of two same-head category terms: a thing under both
        meets both constraint sets, so the meet is their union — reduced,
        so the name stays canonical (a constraint above another says
        nothing more). Never empty: categories carry no disjointness."""
        head_a, param_a = _dims.split_term(a)
        head_b, param_b = _dims.split_term(b)
        if head_a != head_b:
            raise ValueError(f"cannot compare across heads: {a!r} vs {b!r}")
        union = set(_dims.constraints(param_a)) | set(_dims.constraints(param_b))
        return f"{head_a}({' '.join(self._reduce_constraints(union))})"

    def _reduce_constraints(self, items):
        """Sorted constraints with every one that contains another dropped."""
        items = sorted(set(items))
        return [a for a in items
                if not any(b != a and self._below_guarded(b, a) for b in items)]

    def _canonical_graph_term(self, name):
        """The canonical spelling of a category term — constraints each
        canonical, deduplicated, sorted — with every constraint checked
        (a present category or a term of a declared dimension; anything
        else fails closed). A REDUNDANT constraint — one another
        constraint implies, `small-item` beside `bicycle` once `bicycle ⊑
        small-item` — would give one set two names (I1: distinct canonical
        names are never mutually contained), so it is DROPPED:
        `H(bicycle small-item)` is spelled `H(bicycle)`. Refusing it made
        whether a write was accepted depend on the order facts arrived in.
        The spelling follows the graph, so a stored compound can fall
        behind it: the graph kind never stores one (`_graph_parts`), and a
        relation kind's is re-filed under its current spelling when a fact
        makes one of its constraints redundant (`_respell_stored`, both
        2026-10-08). Replays (merge, sync) land nodes before their edges
        and run lenient, like role parameters naming not-yet-placed
        nodes."""
        lenient = getattr(self, "_role_lenient", 0)
        key = ("graph-term", name)
        trips = self._trips()
        if not lenient:
            hit = self._memo_get(key)
            if hit is not _MISSING:
                return hit
        head, param = _dims.split_term(name)
        canonical = []
        for c in _dims.constraints(param):
            parsed = self._parse_parametric(c)
            if parsed is not None:
                canonical.append(parsed[2])
            elif (c in self.nodes and not _dims.is_kind_node(c)) or lenient:
                canonical.append(c)
            else:
                raise ValueError(
                    f"{name}: {c!r} is neither a category the graph knows "
                    f"nor a term of a declared dimension — a category term's "
                    f"constraints fail closed")
        canonical = sorted(set(canonical))
        if not lenient:
            canonical = self._reduce_constraints(canonical)
            return self._memo_put_unless_tripped(
                key, f"{head}({' '.join(canonical)})", trips)
        return f"{head}({' '.join(canonical)})"

    def _graph_parts(self, name):
        """The terms a graph-kind term is stored as: one per constraint,
        `H(a)` and `H(b)` for `H(a b)`, each canonical (DIMENSIONS.md §15).
        A constraint that is itself a graph-kind term with several
        constraints splits too, since a graph-kind head relates an item to
        ONE thing: `H(G(a b))` is `H(G(a))` and `H(G(b))`. The parts are not
        reduced, because every part a write names is materialized whether or
        not the graph already relates them: that keeps stored form the same
        in every order, and reduction drops the edges a finer part implies,
        then or later. Any other name is its own one part.

        Why parts: a compound name's canonical spelling follows the graph
        (`H(bicycle small-item)` is `H(bicycle)` once bicycles are small
        items), while a stored name never changes. Stored compounds made
        the same knowledge two stored forms, and two names for one class
        once their constraints became related (fixed 2026-10-08)."""
        split = _dims.split_term(name)
        if split is None or self._dimension_kind(split[0]) != _dims.KIND_GRAPH:
            return [name]
        head, param = split
        parts = []
        for constraint in _dims.constraints(param):
            for atom in self._graph_parts(constraint):
                part = self._canonical_name(f"{head}({atom})")
                if part not in parts:
                    parts.append(part)
        return sorted(parts)

    def _declared_units(self):
        """Graph-declared unit vocabulary (UNITS.md §7): the resolved map
        from `unit(...)`/`unit-family(...)` nodes under the registry node
        `unit-declaration`. Cached; the cache self-checks against the
        declaration-name set, so puts, removes and merges are picked up
        without invalidation hooks. Loud on conflicts and unresolvable
        definitions — the conflicting-kind-declaration precedent."""
        node = self.nodes.get(_dims.UNIT_DECLARATION)
        names = frozenset(child.name for child in node.neighbors)             if node is not None else frozenset()
        cached = getattr(self, "_unit_cache", None)
        if cached is not None and cached[0] == names:
            return cached[1]
        units = _dims.resolve_declarations(names)
        self._unit_cache = (names, units)
        return units

    def _parse_parametric(self, name):
        """(head, kind, canonical name) when `name` is a parametric term of a
        *declared* dimension; None otherwise. This is the parse trigger:
        term-shaped names with undeclared heads stay opaque atoms, so
        existing graphs are untouched (DIMENSIONS.md §7)."""
        split = _dims.split_term(name)
        if split is None:
            return None
        kind = self._dimension_kind(split[0])
        if kind is None:
            return None
        if kind in _dims.GRAPH_ORDERED:
            if name in self.nodes:
                # A stored term was canonical when it was made, and is never
                # re-read against the redundancy rule (see
                # `_canonical_graph_term`). Re-reading it here did two kinds
                # of harm. Once its constraints became related, every query
                # that touched it raised. And walks parse every node they
                # pass, so the redundancy checks ran inside walks, recursed
                # into further walks, and went exponential.
                return split[0], kind, name
            return split[0], kind, self._canonical_graph_term(name)
        if "(" in split[1]:
            return None       # the flat kinds: a nested parameter stays opaque, as before
        if self._param_node(split[0], split[1]) is not None:
            # A role parameter naming a node: the node's name IS the
            # parameter's identity (its position may move with the
            # catalogue, which is the point — DIMENSIONS.md §14).
            return split[0], kind, name
        canonical = _dims.canonicalize(name, kind, units=self._declared_units())
        if kind in _dims.FAMILY_KINDS and canonical not in self.nodes:
            # A stored value parses as stored (a pin added later, or a
            # merge, may have brought in one of another family: that is
            # reported when values are compared). A new one must fit.
            family = self._head_family(split[0])
            if family is not None:
                found = _dims.family_of(canonical, kind,
                                        units=self._declared_units())
                if found != family:
                    raise ValueError(
                        f"{name}: dimension {split[0]!r} holds {family} "
                        f"values, and this one is {found}")
        return split[0], kind, canonical

    def _canonical_name(self, name):
        parsed = self._parse_parametric(name)
        return parsed[2] if parsed else name

    def is_term(self, name):
        """Is `name` a typed value of a dimension this DAG declares?

        True for `time(2026-08)` or `weight(3000g)` once `time` and `weight`
        are declared (the prelude does); False for any other name, including
        a term-shaped one whose head is not declared, which stays an opaque
        atom (DIMENSIONS.md §7). A malformed value of a declared head —
        `time(zzz)` — raises the ValueError `put` would give, since there is
        no honest yes or no to answer. For an embedder deciding whether a
        name it has never seen is a category that must exist or a value
        OntoDAG creates on first use."""
        return self._parse_parametric(name) is not None

    def parse_term(self, name):
        """How this DAG reads `name`: a `Term(head, kind, canonical)` when it
        is a typed value of a dimension this DAG declares, else None.

        `parse_term("mass(3000g)")` is `Term("mass", "linear-dimension",
        "mass(3kg)")` once `mass` is declared (the prelude declares it); a
        role term naming a node (`in(paris)`) parses with the node's name as
        its parameter. Any other name is None, a term-shaped one whose head
        is not declared included: it stays an opaque atom (DIMENSIONS.md
        §7). A malformed value of a declared head (`mass(3zz)`) raises the
        ValueError `put` would give."""
        parsed = self._parse_parametric(name)
        return None if parsed is None else Term(*parsed)

    def canonical(self, name):
        """The name this DAG files `name` under: a typed value's canonical
        spelling (`mass(3000g)` is `mass(3kg)`), any other name unchanged.
        Raises like `parse_term`. Every public method that takes a name
        already canonicalizes it; this is for comparing names, keying a
        cache, or showing what was stored."""
        return self._canonical_name(name)

    def parents_of(self, name):
        """The categories `name` is filed under, sorted: its asserted parents
        (a typed value's head included), never the computed order's, and
        never the root, so a top-level name has none. Raises ValueError for
        a name the DAG does not hold, and like `parse_term` for a malformed
        value."""
        canonical = self._canonical_name(name)
        node = self.nodes.get(canonical)
        if node is None:
            raise ValueError(f"{name} is not in the store")
        return sorted(parent for parent in self._live_parent_names(canonical)
                      if parent != self.root.name)

    def _is_anchor(self, parent, child):
        """head -> value edges are schema, not assertions: exempt from
        transitive-reduction pruning (DIMENSIONS.md §5)."""
        parsed = self._parse_parametric(child.name)
        return parsed is not None and parsed[0] == parent.name

    def _star(self, head_name):
        """The present values of a dimension: the head's parametric children
        (this asserted star is the dimension's enumeration index)."""
        head_node = self.nodes.get(head_name)
        if head_node is None:
            return
        for child in head_node.neighbors:
            parsed = self._parse_parametric(child.name)
            if parsed is not None and parsed[0] == head_name:
                yield child, parsed[1]

    def _stars(self, heads):
        """The present values of several heads (a relation and those
        narrower or broader than it, §20), in a stable order."""
        for head in sorted(heads):
            yield from self._star(head)

    def _computed_children(self, node):
        """Present same-head terms contained in `node`'s denotation — the
        computed hops of the combined order. Distinct canonical names are
        never mutually contained (equal denotation ⇒ equal name), so this
        relation is a strict partial order on present nodes (I1).

        Complete under closure, not necessarily at each step: a walk that
        follows these hops reaches every term below `node`, but a term may
        be reached through another rather than listed directly (see
        `_hops`). Every caller walks."""
        parsed = self._parse_parametric(node.name)
        if parsed is None:
            return ()
        head, kind, canonical = parsed
        found = self._hops(canonical, head, kind, up=False)
        if found is None:
            return [sibling for sibling, _ in self._stars(self._narrower(head))
                    if sibling is not node and self._contains(
                        canonical, sibling.name, kind)]
        return [self.nodes[name] for name in found if name in self.nodes]

    def _computed_parents(self, node):
        parsed = self._parse_parametric(node.name)
        if parsed is None:
            return ()
        head, kind, canonical = parsed
        found = self._hops(canonical, head, kind, up=True)
        if found is None:
            return [sibling for sibling, _ in self._stars(self._broader(head))
                    if sibling is not node and self._contains(
                        sibling.name, canonical, kind)]
        return [self.nodes[name] for name in found if name in self.nodes]

    # ---- finding computed hops without scanning (ROLES.md §9 step 4a) -------
    #
    # A computed hop used to be found by scanning the head's whole star, so
    # every walk through a term, and so every put, cost time in proportion
    # to how many terms its head had, and bulk loads were quadratic
    # (DIMENSIONS.md §18). On a resident graph a hop is now found from the
    # term's own parameter: interval values through a per-head index sorted
    # by lower bound, prefix values by their prefixes, and terms the graph
    # orders by walking from their constraints and looking up, in an index
    # that `add_node` and `_forget` keep, the terms naming what the walk
    # meets. A lazy reader keeps the scan, since it pays a fetch for every
    # name it looks up and a star is what it has to fetch anyway; so does
    # anything the indexes do not cover (role heads, the dominance kind,
    # nested constraints, and any head the graph orders whose terms escape).

    _resident = True

    def add_node(self, node):
        super().add_node(node)
        self._index_name(node.name)

    def _index_name(self, name):
        """Keep the argument and value indexes current for a name that just
        became known. The one seam: a subclass that registers nodes another
        way (the lazy reader's stubs, the sparse writer's new nodes) calls
        it too, or what it registers is invisible to re-reduction (until
        2026-10-09 the sparse writer's own new terms were: its root then
        differed from the eager writer's)."""
        split = _dims.split_term(name)
        if split is None:
            return
        if getattr(self, "_args", None) is not None:
            self._index_args(name, split)
        values = getattr(self, "_values", None)
        if values is not None and split[0] in values:
            index = values[split[0]]
            if index is None or not index.add(self, name):
                del values[split[0]]

    def _index_args(self, name, split):
        constraints = _dims.constraints(split[1])
        if len(constraints) > 1 or any(_dims.split_term(c) is not None
                                       for c in constraints):
            self._compound_terms.add(name)      # its spelling can fall behind
        for constraint in constraints:
            named = self._args.setdefault(constraint, set())
            if name in named:
                continue
            named.add(name)
            self._count_shape(constraint, split[0], +1)
            if len(named) == 1 and _dims.split_term(constraint) is not None:
                self._nested_keys.add(constraint)
                self._nested_version = getattr(self, "_nested_version", 0) + 1
                indexes = getattr(self, "_constraint_values", None)
                head = _dims.split_term(constraint)[0]
                if indexes is not None and indexes[1].get(head) is not None \
                        and not indexes[1][head].add(self, constraint):
                    del indexes[1][head]

    def _args_index(self):
        """constraint -> the present terms naming it, built on first use."""
        if getattr(self, "_args", None) is None:
            self._args, self._nested_keys = {}, set()
            self._compound_terms = set()
            for present in list(self.nodes):
                split = _dims.split_term(present)
                if split is not None:
                    self._index_args(present, split)
        return self._args

    def _unindex(self, name):
        split = _dims.split_term(name)
        if split is None:
            return
        args = getattr(self, "_args", None)
        if args is not None:
            self._compound_terms.discard(name)
            for constraint in _dims.constraints(split[1]):
                named = args.get(constraint)
                if named is not None:
                    if name in named:
                        self._count_shape(constraint, split[0], -1)
                    named.discard(name)
                    if not named:
                        del args[constraint]
                        if constraint in self._nested_keys:
                            self._nested_keys.discard(constraint)
                            self._nested_version = getattr(
                                self, "_nested_version", 0) + 1
                            indexes = getattr(self, "_constraint_values", None)
                            if indexes is not None:
                                indexes[1].pop(
                                    _dims.split_term(constraint)[0], None)
        values = getattr(self, "_values", None)
        if values is not None:
            values.pop(split[0], None)

    def _terms_naming(self, name, head):
        """Present terms of `head` with `name` among their constraints;
        `head` may also be a set of heads."""
        heads = {head} if isinstance(head, str) else head
        return [term for term in self._args_index().get(name, ())
                if _dims.split_term(term)[0] in heads and term in self.nodes]

    @staticmethod
    def _constraint_shape(constraint, heads):
        """How the hop walks can reach a term naming `constraint`: None
        when they always can (a node, an opaque name, or a value of a base
        head that `_constraint_index` covers); "nested" for a term of a
        kind the graph orders, which moves by the graph's own hops; "odd"
        for any other value (a dominance value, a role term), which no
        index covers."""
        split = _dims.split_term(constraint)
        if split is None:
            return None
        kind, base = heads.get(split[0], (None, None))
        if kind is None:
            return None
        if kind in _dims.GRAPH_ORDERED:
            return "nested"
        if (kind in _dims._INTERVALISH or kind == _dims.KIND_PREFIX) \
                and base == split[0]:
            return None
        return "odd"

    def _count_shape(self, constraint, term_head, step):
        shapes = getattr(self, "_shapes", None)
        if shapes is None:
            return
        shape = self._constraint_shape(constraint, shapes[0])
        if shape is not None:
            counts = shapes[1] if shape == "nested" else shapes[2]
            counts[term_head] = counts.get(term_head, 0) + step

    def _constraint_shapes(self):
        """(nested, odd): per head, how many of its present terms name a
        constraint the hop walks cannot reach (`_constraint_shape`). Kept
        by `_index_args`/`_unindex` as terms come and go, and rebuilt when
        the declared heads change, since a declaration can turn an opaque
        name into a term."""
        heads = self._heads()
        shapes = getattr(self, "_shapes", None)
        if shapes is None or shapes[0] is not heads:
            self._args_index()
            nested, odd = {}, {}
            for constraint, terms in self._args.items():
                shape = self._constraint_shape(constraint, heads)
                if shape is None:
                    continue
                counts = nested if shape == "nested" else odd
                for term in terms:
                    head = _dims.split_term(term)[0]
                    counts[head] = counts.get(head, 0) + 1
            shapes = self._shapes = (heads, nested, odd)
        return shapes[1], shapes[2]

    def _constraint_index(self, head, kind):
        """The values of `head` that present terms name among their
        constraints, indexed as a star is (`_value_index`). A value named
        only inside a term, `transport(mass(..5kg))`, is not a node, so a
        walk through present nodes never meets it; this is how the hop
        walks find it (fixed 2026-10-08: until then a resident graph's
        `get(["transport(mass(..8kg))"])` missed what was filed under
        `transport(mass(..5kg))`). None when the values cannot be indexed."""
        self._args_index()
        units = self._declared_units()
        units_key = getattr(self, "_unit_cache", (None,))[0]
        indexes = getattr(self, "_constraint_values", None)
        if indexes is None or indexes[0] is not units_key:
            indexes = self._constraint_values = (units_key, {})
        index = indexes[1].get(head)
        if index is not None:
            return index
        index = (_Prefixes if kind == _dims.KIND_PREFIX else _Intervals)(units_key)
        for key in self._nested_keys:
            if _dims.split_term(key)[0] == head \
                    and not index.add(self, key, units=units, kind=kind):
                return None
        indexes[1][head] = index
        return index

    def _value_constraints_near(self, names, above):
        """Value constraints of present terms that contain (`above`) or lie
        inside one of the values among `names`, which a hop walk has just
        met; None when some cannot be found that way (the caller scans)."""
        out = []
        for name in names:
            split = _dims.split_term(name)
            if split is None:
                continue
            kind, base = self._heads().get(split[0], (None, None))
            if kind not in _dims._INTERVALISH and kind != _dims.KIND_PREFIX:
                continue
            if base != split[0]:
                continue
            index = self._constraint_index(split[0], kind)
            if index is None:
                return None
            found = index.hops(self, name, split[0], kind, above)
            if found is None:
                return None
            out.extend(found)
        return out

    def _graph_nested(self):
        """Does some present term name, among its constraints, a term of a
        kind the graph orders (`shared-with(in(japan))`)? Such a constraint moves
        through the graph's own hops, so re-reduction then walks them."""
        self._args_index()
        heads = self._heads()
        version = getattr(self, "_nested_version", 0)
        cached = getattr(self, "_nested_cache", None)
        if cached is not None and cached[0] is heads and cached[1] == version:
            return cached[2]
        answer = any(heads.get(_dims.split_term(key)[0], (None,))[0]
                     in _dims.GRAPH_ORDERED for key in self._nested_keys)
        self._nested_cache = (heads, version, answer)
        return answer

    def _value_index(self, head, kind):
        """The index of `head`'s values, built on first use from its star;
        None when the head's values cannot be indexed."""
        values = getattr(self, "_values", None)
        if values is None:
            values = self._values = {}
        units = self._declared_units()
        index = values.get(head)
        if index is not None and index.units is getattr(
                self, "_unit_cache", (None,))[0]:
            return index
        cls = _Prefixes if kind == _dims.KIND_PREFIX else _Intervals
        index = cls(getattr(self, "_unit_cache", (None,))[0])
        for value, _ in self._star(head):
            if not index.add(self, value.name, units=units, kind=kind):
                values.pop(head, None)
                return None
        values[head] = index
        return index

    def _hops(self, canonical, head, kind, up):
        """Names of present terms of `head` directly above (`up`) or below
        `canonical`, which need not be present itself (a virtual query
        term); or None when the star must be scanned instead."""
        if not self._resident:
            return None
        if kind in _dims.GRAPH_ORDERED:
            # Also a head declared under another head: a narrower relation
            # (§20), or, for the graph kind, a head of its own.
            return self._graph_hops(canonical, head, kind, up)
        base = self._dimension_of(head)[1]
        if base != head:
            return self._role_hops(canonical, head, base, up)
        if kind in _dims._INTERVALISH or kind == _dims.KIND_PREFIX:
            index = self._value_index(head, kind)
            if index is None:
                return None
            return index.hops(self, canonical, head, kind, up)
        return None

    def _ancestry(self, name):
        """`name` and everything above it reachable without walking the
        graph-ordered kinds' own hops: asserted edges, and the computed
        hops of values, which never recurse. A term the graph orders is
        reached as itself, which is all `_graph_hops` asks of it."""
        node = self.nodes.get(name)
        if node is None:
            # A virtual value (`weight(..10kg)` named only in a query) is
            # above whatever is above the present values containing it.
            start = self._virtual_value_hops(name, up=True)
            if not start:
                return [name]
            out, seen, frontier = [name], {name}, []
            for found in start:
                if found.name not in seen:
                    seen.add(found.name)
                    out.append(found.name)
                    frontier.append(found)
        else:
            out, seen, frontier = [name], {name}, [node]
        while frontier:
            current = frontier.pop()
            parents = [p for p in current.parents if self.nodes.get(p.name) is p]
            parsed = _dims.split_term(current.name)
            if parsed is not None:
                kind = self._dimension_kind(parsed[0])
                if kind in _dims._INTERVALISH or kind == _dims.KIND_PREFIX:
                    parents.extend(self._computed_parents(current))
            for parent in parents:
                if parent.name not in seen:
                    seen.add(parent.name)
                    out.append(parent.name)
                    frontier.append(parent)
        return out

    def _below_names(self, name, budget):
        """`name` and everything below it, by asserted edges and the
        computed hops of values; None once more than `budget` nodes are
        met, which tells the caller a scan of the star is cheaper."""
        node = self.nodes.get(name)
        if node is None:
            # A virtual value is above the present values it contains.
            start = self._virtual_value_hops(name, up=False)
            if not start:
                return [name]
            out, seen, frontier = [name], {name}, []
            for found in start:
                if found.name not in seen:
                    seen.add(found.name)
                    out.append(found.name)
                    frontier.append(found)
        else:
            out, seen, frontier = [name], {name}, [node]
        while frontier:
            current = frontier.pop()
            children = list(current.neighbors)
            parsed = _dims.split_term(current.name)
            if parsed is not None:
                kind = self._dimension_kind(parsed[0])
                if kind in _dims._INTERVALISH or kind == _dims.KIND_PREFIX:
                    children.extend(self._computed_children(current))
            for child in children:
                if child.name not in seen:
                    seen.add(child.name)
                    out.append(child.name)
                    if budget is not None and len(out) > budget:
                        return None
                    frontier.append(child)
        return out

    def _role_hops(self, canonical, head, base, up):
        """`_hops` for a role head (DIMENSIONS.md §14): `R(y) ⊑ R(x)` when y
        is below x in the base dimension, a parameter naming either a node
        (`from(my_home)`) or, spelled literally, a value of the base
        (`from(u2e4)`, standing for `geo(u2e4)`). So the base dimension is
        walked from the parameter and both spellings are looked up; literal
        terms whose value is not a node are found through a sorted index of
        the role's literal parameters, by prefix. Only a prefix base is
        covered; any other falls back to the scan."""
        if self._dimension_of(base)[0] != _dims.KIND_PREFIX:
            return None
        param = _dims.split_term(canonical)[1]
        node = self._param_node(head, param)
        start = node.name if node is not None else f"{base}({param})"
        head_node = self.nodes.get(head)
        budget = len(head_node.neighbors) if head_node is not None else 0
        walked = self._ancestry(start) if up else self._below_names(start, budget)
        if walked is None:
            return None
        literals = self._role_literals(head)
        found = set()
        for name in walked:
            split = _dims.split_term(name)
            if split is not None and split[0] == base:
                found.add(f"{head}({split[1]})")
                if up:
                    found.update(f"{head}({split[1][:k]})"
                                 for k in range(1, len(split[1])))
                else:
                    found.update(literals.below(split[1], head))
            else:
                found.add(f"{head}({name})")
        if node is None:
            # A literal parameter also relates to literal terms by prefix,
            # whether or not their values are nodes.
            if up:
                found.update(f"{head}({param[:k]})" for k in range(1, len(param)))
            else:
                found.update(literals.below(param, head))
        found.discard(canonical)
        found = [t for t in found if t in self.nodes]
        kind = self._dimension_of(head)[0]
        if up:
            return [t for t in found if self._contains(t, canonical, kind)]
        return [t for t in found if self._contains(canonical, t, kind)]

    def _role_literals(self, head):
        """The role's literal parameters, sorted (a `_Prefixes` index kept
        with the value indexes)."""
        values = getattr(self, "_values", None)
        if values is None:
            values = self._values = {}
        index = values.get(head)
        if isinstance(index, _Prefixes):
            return index
        index = _Prefixes(None, literal_role=head)
        for term, _ in self._star(head):
            index.add(self, term.name)
        values[head] = index
        return index

    def _virtual_value_hops(self, name, up):
        """The present values directly above (`up`) or below a value term
        that is not present itself, or [] when `name` is no such term."""
        parsed = self._parse_parametric(name)
        if parsed is None or (parsed[1] not in _dims._INTERVALISH
                              and parsed[1] != _dims.KIND_PREFIX):
            return []
        found = self._hops(parsed[2], parsed[0], parsed[1], up)
        if found is None:
            star = [value for value, _ in self._star(parsed[0])]
            return [value for value in star if (
                self._contains(value.name, parsed[2], parsed[1]) if up
                else self._contains(parsed[2], value.name, parsed[1]))]
        return [self.nodes[n] for n in found if n in self.nodes]

    def _graph_hops(self, canonical, head, kind, up):
        """`_hops` for the kinds the graph orders. Candidates come from
        walking near the term's constraints, and each is then checked with
        `_contains`, so a candidate too many costs a check, never a wrong
        hop. What the walks guarantee is that a walk following the hops
        reaches every term the order puts above or below this one."""
        param = _dims.split_term(canonical)[1]
        xs = _dims.constraints(param)
        heads = self._heads()
        if any(_dims.split_term(x) is not None and heads.get(
                _dims.split_term(x)[0], (None,))[0] in _dims.GRAPH_ORDERED
               for x in xs) or any(
                self._escapes(h) for h, (k, _b) in heads.items()
                if k in _dims.GRAPH_ORDERED):
            # A constraint that is itself a term the graph orders moves by
            # the graph's own hops, which these walks do not follow; so does
            # a term filed outside its head. (A value constraint is fine:
            # its place is fixed by arithmetic, and the walks take value
            # hops.)
            return None
        # The terms a hop can reach: those of narrower heads below, of
        # broader heads above (a narrower relation, §20).
        heads_reached = self._broader(head) if up else self._narrower(head)
        # Constraints no walk below can meet: a value no index covers, here
        # or in a term the hop could reach; and, for the graph kind, a term
        # nesting a graph-ordered term (`transport(option(b))` above
        # `transport(piano)` when piano ⊑ option(a) ⊑ option(b): no hop
        # leads there, as one does for the relation kinds' nesting).
        nested, odd = self._constraint_shapes()
        if any(odd.get(h) for h in heads_reached) or any(
                self._constraint_shape(x, heads) == "odd" for x in xs) or (
                kind == _dims.KIND_GRAPH
                and any(nested.get(h) for h in heads_reached)):
            return None
        budget = 0
        for reached in heads_reached:
            reached_node = self.nodes.get(reached)
            budget += len(reached_node.neighbors) if reached_node is not None else 0
        found, scan = set(), []

        def named(names, above):
            # Also the terms naming a value inside (`above`: containing) a
            # value the walk met: such a value need not be a node.
            near = self._value_constraints_near(names, above)
            if near is None:
                scan.append(True)
                return
            for name in [*names, *near]:
                found.update(self._terms_naming(name, heads_reached))

        covariant = kind != _dims.KIND_REVERSED
        if covariant == up and up and kind == _dims.KIND_TRANSITIVE:
            # Above a transitive term: the terms naming what each
            # constraint is below, or is inside. Inside a term of the other
            # head, as an ancestor, is a hop; inside a narrower relation's
            # term (x ⊑ inside(z), §20) stands for the broader term of z,
            # which may not exist, so the walk looks past it, to what z is
            # below or inside. A worklist, never recursion (I6).
            for reached in heads_reached:
                narrower_reached = self._narrower(reached)
                pending, looked = list(xs), set()
                while pending:
                    z = pending.pop()
                    if z in looked:
                        continue
                    looked.add(z)
                    ancestry = self._ancestry(z)
                    near = self._value_constraints_near(ancestry, True)
                    if near is None:
                        return None
                    found.update(term for name in [*ancestry, *near]
                                 for term in self._terms_naming(name, reached))
                    for a in ancestry:
                        split = _dims.split_term(a)
                        if split is None or split[0] not in narrower_reached:
                            continue
                        if split[0] == reached:
                            found.add(a)
                            continue
                        term = f"{reached}({split[1]})"
                        if term in self.nodes:
                            found.add(term)
                        else:
                            pending.extend(_dims.constraints(split[1]))
        elif covariant == up:
            # Above a covariant term, or below a reversed one: every
            # constraint of the other term is above, or is, one of ours.
            for x in xs:
                named(self._ancestry(x), True)
            if up and kind == _dims.KIND_ENCLOSING and self._dimension_kind(
                    _dims.CONTAINMENT_HEAD) == _dims.KIND_TRANSITIVE:
                for x in xs:
                    named(self._containers(x), True)
        else:
            # Below a covariant term, or above a reversed one: some
            # constraint of the other term is below, or is, one of ours.
            # Walk below the constraint with the smallest known cone; a
            # constraint that is not a node (a virtual value) last.
            pick = min(xs, key=lambda x: (
                0, self.nodes[x].descendant_count) if x in self.nodes
                else (1, 0))
            below = self._below_names(pick, budget)
            if below is None:
                return None
            named(below, False)
            if not up and kind == _dims.KIND_TRANSITIVE:
                # ... or inside this very term: what is filed in it, or in
                # a narrower relation's term of the same argument, and, to
                # a fixpoint, in any narrower term found inside: x ⊑
                # inside(z) with z inside y puts x in y (§20), through a
                # term in(z) that may not exist, so a walk through present
                # terms alone would never reach x.
                # A narrower term whose term of this head exists is left to
                # that term: the closure walks through it, and chasing it
                # here too made every term on a chain re-walk the chain.
                def beyond(t):
                    split = _dims.split_term(t)
                    return split[0] != head and f"{head}({split[1]})" not in self.nodes
                chase = [canonical if reached == head else f"{reached}({param})"
                         for reached in sorted(heads_reached)]
                chase += [t for t in found if beyond(t)]
                chased = set()
                while chase:
                    term = chase.pop()
                    if term in chased or term not in self.nodes:
                        continue
                    chased.add(term)
                    inside = self._below_names(term, budget)
                    if inside is None:
                        return None
                    before = set(found)
                    named(inside, False)
                    chase.extend(t for t in found - before if beyond(t))
            if not up and kind == _dims.KIND_ENCLOSING and self._dimension_kind(
                    _dims.CONTAINMENT_HEAD) == _dims.KIND_TRANSITIVE:
                located = f"{_dims.CONTAINMENT_HEAD}({param})"
                inside = self._located_in(located, budget)
                if inside is None:
                    return None
                named(inside, False)
        if scan:
            return None
        found.discard(canonical)
        if up:
            return [t for t in found if self._contains(t, canonical, kind)]
        return [t for t in found if self._contains(canonical, t, kind)]

    def _containers(self, name, head=_dims.CONTAINMENT_HEAD):
        """Everything `name` is inside by the transitive `head` (`in` by
        default): the places named by every `head(...)` above it,
        everything above those places (in(n6) ⊑ in(n1) once n6 ⊑ n1, by
        the graph rule), and, the same way, whatever those are inside.
        One upward walk, whatever is asked of the answer."""
        out, seen = [], {name}
        frontier = [(name, False)]
        heads = self._narrower(head)
        while frontier:
            current, is_place = frontier.pop()
            for ancestor in self._ancestry(current):
                split = _dims.split_term(ancestor)
                if split is not None and split[0] in heads:
                    for place in _dims.constraints(split[1]):
                        if place not in seen:
                            seen.add(place)
                            out.append(place)
                            frontier.append((place, True))
                elif is_place and ancestor not in seen:
                    seen.add(ancestor)
                    out.append(ancestor)
        return out

    def _located_in(self, located, budget):
        """Everything below `in(X…)`, present or virtual, within `budget`."""
        node = self.nodes.get(located)
        if node is not None:
            cone = self.get_descendants(node)
        else:
            try:
                parsed = self._parse_parametric(located)
            except ValueError:
                # `located` is derived from a stored term whose constraint
                # has since been removed (`about(c1 c4)`, then `remove c4`):
                # nothing is known to be inside what no longer exists.
                # Until 2026-10-09 this raised, so every query and write
                # that walked the term failed.
                return []
            if parsed is None:
                return []
            cone = self._virtual_cone(parsed[0], parsed[1], parsed[2])
        if len(cone) > budget:
            return None
        return [n.name for n in cone]

    def get_overlapping(self, term):
        """Present nodes that POSSIBLY satisfy `term`: the values of its
        dimension whose denotation merely *overlaps* the term's, plus
        everything below them.

        This is the weaker of the two matching modes (DIMENSIONS.md §8):
        `get({term})` returns guaranteed satisfaction (denotation ⊆ term —
        an offer of weight(1.2kg) against weight(1kg..)), while this returns
        candidates (an offer of weight(0.8kg..1.5kg) against weight(1kg..)
        might weigh enough — the caller's exact check decides). Overlap is
        not transitive, so it can never be a cone or an edge — it is a
        separate query operation, computed per dimension from the anchor
        star, touching no stored state. The term may be virtual, like any
        query term. Raises ValueError for a term of no declared dimension,
        since overlap is only defined for computed denotations.

        This ENUMERATES what states an overlapping value; an item that
        states nothing under the head is not here. It is a candidate
        generator for a consumer's own exact check, not a query mode:
        `get` is containment, and every query term is a containment term
        (DIMENSIONS.md §8, 2026-09-12)."""
        name = _name_of(term)
        parsed = self._parse_parametric(name)
        if parsed is None:
            raise ValueError(
                f"{name!r} is not a parametric term of a declared dimension"
                " — get_overlapping needs a computed denotation")
        head, kind, canonical = parsed
        result = set()
        for value, _ in self._stars(self._narrower(head)):
            if self._overlap_terms(canonical, value.name, kind):
                result.add(value)
                # ASSERTED descendants only: what hangs below a finer value
                # is decided when the loop reaches that value, which is in
                # the star too — so items under a finer value that does NOT
                # overlap (weight(0.9kg) under weight(0.8kg..1.5kg) against
                # weight(1kg..); a ground-floor courier against the fourth
                # floor) are left out, while everything filed directly
                # under an overlapping value stays in. Completeness for
                # possibility is kept; the walk merely stops inventing it.
                result |= self.get_descendants(value, computed=False)
        return result

    def overlaps(self, a, b):
        """Do the denotations of `a` and `b` share a point? The Boolean face
        of `get_overlapping`, for a given PAIR — the mirror of `is_below` in
        the possibly-satisfies mode (contract G6; issue #16).

        Either side may be a parametric term (present or virtual) or a node
        whose denotation comes from its position: a place under a cell, a
        region above cells, an offer under a role term. Values decide by
        arithmetic; nodes by the graph (DIMENSIONS.md §14): one below the
        other, or what one is known to cover meeting what the other lies
        within or covers — never two distinct places under one cell.
        Units come from the store, as they do for `is_below`. Two terms of
        different heads raise, as `dimensions.intersect` does; a malformed
        value raises; unknown plain names fail closed to False.
        `is_below(a, b) or is_below(b, a)` implies `overlaps(a, b)`.
        Overlap is not transitive, so it is a question, never an edge."""
        a = self._canonical_name(_name_of(a))
        b = self._canonical_name(_name_of(b))
        parsed_a = self._parse_parametric(a)
        parsed_b = self._parse_parametric(b)
        if (parsed_a is None and a not in self.nodes) or \
                (parsed_b is None and b not in self.nodes):
            return False                     # unknown vocabulary fails closed
        if parsed_a is not None and parsed_b is not None:
            if not self._related_heads(parsed_a[0], parsed_b[0]):
                raise ValueError(
                    f"cannot compare across heads: {a!r} vs {b!r}")
            return self._overlap_terms(a, b, parsed_a[1])
        return self._overlap(a, b)

    def meet(self, a, b):
        """The canonical name of denotation(a) ∩ denotation(b) for two
        same-head parametric terms, or None when the intersection is
        provably empty — `dimensions.intersect` with the store's declared
        units, so a consumer can reduce same-head terms before asking
        (issue #16). With a parameter naming a node (DIMENSIONS.md §14)
        the meet is nameable only when one term contains the other (the
        finer one), or empty when they do not overlap; anything else
        raises, since no single term denotes it — pass both to `get`."""
        a = self._canonical_name(_name_of(a))
        b = self._canonical_name(_name_of(b))
        parsed_a = self._parse_parametric(a)
        parsed_b = self._parse_parametric(b)
        if parsed_a is None or parsed_b is None:
            raise ValueError(
                f"meet needs two parametric terms of one declared "
                f"dimension: {a!r}, {b!r}")
        if not self._related_heads(parsed_a[0], parsed_b[0]):
            raise ValueError(f"cannot compare across heads: {a!r} vs {b!r}")
        head, kind = parsed_a[0], parsed_a[1]
        if kind in _dims.MULTI_VALUED:
            # An item can be related to several things at once (Zermatt is
            # in Switzerland and in the Alps), so R(A) ∩ R(B) has no single
            # name unless one term contains the other; and with no
            # disjointness it is never empty.
            if self._contains(a, b, kind):
                return b
            if self._contains(b, a, kind):
                return a
            raise ValueError(
                f"no single term names the meet of {a!r} and {b!r}: "
                f"something can be {head} both at once — query with both "
                f"terms instead")
        if self._param_node(head, _dims.split_term(a)[1]) is None and \
                self._param_node(head, _dims.split_term(b)[1]) is None:
            return self._intersect(a, b, kind)
        if self._contains(a, b, kind):
            return b
        if self._contains(b, a, kind):
            return a
        if not self._overlap(a, b):
            return None
        raise ValueError(
            f"no single term names the meet of {a!r} and {b!r} (a named "
            f"place or region is involved and neither contains the other) "
            f"— query with both terms instead")

    def _virtual_cone(self, head, kind, canonical):
        """The cone of a parametric term that need not exist as a node: the
        present values of its dimension contained in its denotation, plus
        everything below them. Queries quantify over present nodes only —
        this is why "all integers" can never be an answer, and why a
        read-only client can ask any threshold without writing
        (DIMENSIONS.md §8)."""
        # One walk with a shared visited set, as in `_walk_cone`.
        cone, visited = set(), set()
        for value in self._contained_values(canonical, head, kind):
            cone.add(value)
            cone |= self.get_descendants(value, visited)
        return cone

    def _contained_values(self, canonical, head, kind):
        """Present terms of `head` inside `canonical`, which need not be
        present: the term itself if it is, and what its hops lead to (a
        walk from these reaches the rest)."""
        found = self._hops(canonical, head, kind, up=False)
        if found is None:
            return [value for value, _ in self._stars(self._narrower(head))
                    if self._contains(canonical, value.name, kind)]
        values = [self.nodes[name] for name in found if name in self.nodes]
        node = self.nodes.get(canonical)
        if node is not None:
            values.append(node)
        return values

    def _ensure_parametric_node(self, canonical, head, kind):
        """Materialize a used value: one node, one anchor edge under its
        head. Every value of one head must share one value space (one unit
        family, one arity) — checked against the star, which keeps the
        property inductively."""
        node = self.nodes.get(canonical)
        if node is not None:
            return node
        if kind not in _dims.GRAPH_ORDERED and not self._total() and \
                self._param_node(head, _dims.split_term(canonical)[1]) is None:
            # A role parameter naming a node has no value space of its
            # own (it sits in the dimension's); only values are checked.
            # A category term's space is the graph: nothing to check. A
            # total replay keeps the two spaces a merge brought together.
            space = _dims.space_of(canonical, kind,
                                   units=self._declared_units())
            for sibling, _ in self._star(head):
                if self._param_node(
                        head, _dims.split_term(sibling.name)[1]) is not None:
                    continue
                sibling_space = _dims.space_of(sibling.name, kind,
                                               units=self._declared_units())
                if sibling_space != space:
                    raise ValueError(
                        f"dimension {head!r} holds {sibling_space} values "
                        f"({sibling.name}); {canonical} is {space}")
                break  # one consistent sibling proves the whole star
        node = Item(canonical)
        self.add_node(node)
        self.add_edge(self.nodes[head], node)  # the anchor (schema edge)
        return node

    def add_edge(self, from_node, to_node):
        """Add a directed edge between two nodes and remove unneeded edges from ancestors."""
        if from_node == to_node or to_node in from_node.neighbors:
            return
        parsed_from = self._parse_parametric(from_node.name)
        parsed_to = self._parse_parametric(to_node.name)
        if parsed_from is not None and parsed_to is not None \
                and parsed_from[0] == parsed_to[0]:
            raise ValueError(
                f"within dimension {parsed_from[0]!r} the order is computed: "
                f"refusing asserted edge {from_node.name} -> {to_node.name}")
        anchor = parsed_to is not None and parsed_to[0] == from_node.name
        # A value or term anchored under its head as it is first used
        # (`_ensure_parametric_node`) makes no edge redundant, moves no term
        # and closes no loop: any path through it already existed without
        # it, because containment between its head's terms is transitive
        # and every one of them hangs under the same head. So it costs only
        # its count deltas, however many values the head already has.
        fresh_anchor = anchor and not self._live_parents(to_node)
        declaration = not anchor and self._declares_narrower(from_node, to_node)
        if not anchor and parsed_to is not None \
                and parsed_to[1] in _dims.GRAPH_ORDERED \
                and not self._total() \
                and not self._below(to_node, from_node):
            self._refuse_rule(to_node.name, parsed_to[0], from_node.name)
        # Skip the edge entirely if to_node is already below from_node in
        # the combined (asserted + computed) order — adding it would violate
        # transitive reduction (and made results depend on the order of
        # super-categories in put). Anchor edges are schema and always kept.
        # Both this and the cycle check below are `is_below` questions,
        # asked UPWARD: it walks computed hops only where they can lead
        # out of a head's terms and decides a term bound by containment, so
        # neither check enumerates the terms that contain a term.
        if not anchor and self._below(to_node, from_node):
            return
        # Reject cycles — through computed hops too — before anything mutates.
        if not fresh_anchor and self._below(from_node, to_node):
            raise ValueError(
                f"Edge {from_node.name} -> {to_node.name} would create a cycle."
            )
        if not anchor:
            self._refuse_self_containment(from_node.name, to_node.name)
            if not self._total():
                self._refuse_pin_over_values(from_node.name, to_node.name)
        # Plan the delta against the pre-operation graph, add the edge, then
        # prune. Pruning runs with live counts: an edge that is redundant via
        # asserted paths removes nothing from asserted reachability (its
        # _plan_remove is zero), while an edge redundant only via *computed*
        # hops really does change asserted reachability — and persisted
        # counts are asserted-only by design (DIMENSIONS.md §5).
        deltas = None if self._counts_frozen else self._plan_add(from_node, to_node)
        self._maybe_invalidate_heads(from_node, to_node)
        with self._counts_unchanged():
            # structure only; the cycle question was asked above, except
            # for a fresh anchor, whose own (cheap) check stays
            super().add_edge(from_node, to_node,
                             _cycle_checked=not fresh_anchor)
        if fresh_anchor:
            self._note_star_child(from_node, to_node)
            self._apply_count_deltas(deltas)
            return
        self._note_escape(from_node, to_node, added=True)
        looped = self._term_on_new_cycle(from_node, to_node)
        if looped is not None:
            with self._counts_unchanged():
                super().remove_edge(from_node, to_node)       # nothing else moved
            self._note_escape(from_node, to_node, added=False)
            raise ValueError(
                f"Edge {from_node.name} -> {to_node.name} would create a "
                f"cycle through {looped.name}: the computed order would put "
                f"it below itself, giving two names one class")
        self._note_star_child(from_node, to_node)
        self._apply_count_deltas(deltas)
        if not declaration:
            self._remove_unneeded_edges(from_node, to_node)
            self._reduce_roles_touching(from_node, to_node)
            return
        # A head declared under another (§20). Until pruning drops its old
        # kind edge the head belongs to two dimensions at once, so what the
        # declaration does is checked after pruning, and a refusal puts
        # back whatever pruning removed.
        self._edge_log = pruned = []
        try:
            self._remove_unneeded_edges(from_node, to_node)
        finally:
            self._edge_log = None
        inside_itself = self._declared_inside_itself(from_node, to_node)
        if inside_itself is not None:
            self.remove_edge(from_node, to_node)
            for upper, lower in pruned:
                self.add_edge(upper, lower)
            name, head = inside_itself
            raise ValueError(
                f"{to_node.name} ⊑ {from_node.name} would make every "
                f"{to_node.name}(...) a {from_node.name}(...), and so put "
                f"{name} inside itself: {head} is strict (DIMENSIONS.md "
                f"§16, §20)")
        self._reduce_roles_touching(from_node, to_node)
        self._reduce_narrower_declared(from_node, to_node)

    def _declares_narrower(self, from_node, to_node):
        """Is `from ⊑ to`, about to be added, a head of a relation kind
        declared under another head of the same kind (§20)? Asked before
        the edge exists, while both are still unambiguous heads. A head
        filed for the first time has no terms, so nothing to check."""
        if _dims.split_term(to_node.name) is not None \
                or _dims.is_kind_node(from_node.name):
            return False
        heads = self._heads()
        kind = heads.get(from_node.name, (None,))[0]
        return kind in _dims.RELATION_KINDS \
            and heads.get(to_node.name, (None,))[0] == kind

    def _newly_narrower(self, from_node, to_node):
        """The heads that the edge `from ⊑ to` just made narrower than
        some relation (§20): `to` and the heads below it, when both ends
        are heads of one relation kind. Empty otherwise."""
        if _dims.split_term(to_node.name) is not None \
                or _dims.is_kind_node(from_node.name):
            return ()
        heads = self._heads()
        kind = heads.get(to_node.name, (None,))[0]
        if kind not in _dims.RELATION_KINDS \
                or heads.get(from_node.name, (None,))[0] != kind:
            return ()
        return sorted(self._narrower(to_node.name))

    def _declared_inside_itself(self, from_node, to_node):
        """(name, head) when declaring `to` narrower than `from` has put
        `name` inside itself, or None. A transitive relation is strict
        (§16); `put` guards each edge it adds, but a declaration moves
        every term of the narrower head at once (x ⊑ inside(y) becomes x ⊑
        in(y)). Any loop it closes passes through one of those terms, so
        their arguments are what is checked. Replays stay total."""
        if self._total():
            return None
        narrower = self._newly_narrower(from_node, to_node)
        if not narrower or self._dimension_kind(to_node.name) \
                != _dims.KIND_TRANSITIVE:
            return None
        broader = sorted(self._broader(from_node.name))
        for head in narrower:
            for term, _ in list(self._star(head)):
                for x in _dims.constraints(_dims.split_term(term.name)[1]):
                    if x not in self.nodes:
                        continue
                    for outer in broader:
                        if self.is_below(x, f"{outer}({x})"):
                            return x, outer
        return None

    def _reduce_narrower_declared(self, from_node, to_node):
        """Keep stored form canonical when a relation is declared narrower
        than another after terms of it were filed (§20). Filing `departure`
        under `from` makes every `departure(x)` a `from(x)`, so an item
        filed under both `departure(lhr)` and `from(lhr)` now carries a
        redundant edge, which filing in the other order would never have
        stored. Each term of a head that just became narrower re-reduces
        its computed parents. Costs the terms of those heads, once, on a
        declaration edge; nothing on any other edge."""
        for head in self._newly_narrower(from_node, to_node):
            for term, _ in list(self._star(head)):
                if term.name not in self.nodes:
                    continue
                for parent in list(self._computed_parents(term)):
                    if parent.name in self.nodes and term.name in self.nodes:
                        self._prune_rectangle(parent, term)

    def _below(self, lower, upper):
        """Is `lower` strictly below `upper` in the combined order, for two
        present nodes? The `is_below` question (`lower` and `upper` differ
        wherever this is asked), so it shares its memo and its walk."""
        return lower is not upper and self.is_below(lower.name, upper.name)

    # Stand-in for the typical ancestor-cone size, which is not maintained
    # per node. Used only to choose between two *exact* operators in get(),
    # so a bad estimate costs time, never correctness. Deliberately biased
    # high (ancestor cones in category graphs are usually far smaller than
    # this) so the probe only fires when it is clearly the cheaper plan.
    _PROBE_COST_ESTIMATE = 16

    def get(self, super_categories, items_only=False):
        """Return all items that are subcategories of all specified super-categories.

        The result is the intersection of the query terms' descendant cones.
        With no terms at all that intersection is unconstrained, so the answer
        is every item in the DAG — the empty query is the universe, never an
        error (see the note where it is returned).
        The cheap, reliable decisions are planned up front; the decision that
        depends on information only produced by retrieval itself is made
        adaptively between steps. Every step is result-preserving.

        Planned in advance (the inputs — `descendant_count` — are exact,
        maintained statistics, so this needs no runtime correction):

        1. Terms are resolved by name and deduplicated (identity at the public
           boundary is the name, never the caller's object).
        2. A term that is an ancestor of another term is dropped: its cone is
           a superset of the other's, so it cannot narrow the intersection.
           The ancestry test walks *upward* from the smaller-count term via
           `_has_ancestors` (bounded by its shallow ancestor cone), never
           downward from the larger one (whose descendant cone may be most of
           the graph): planner work must scale with the query, not with the
           graph. `descendant_count` supplies the cheap necessary condition —
           a strict ancestor always has a strictly larger count.
        3. The surviving cones are ordered smallest-count-first (name as
           tiebreak, keeping traversal deterministic).

        Decided during retrieval: after each step the running result's size
        is known exactly — something no up-front plan can estimate, since
        cone overlap is not a per-term statistic — so before each remaining
        term the cheaper of two exact operators is chosen:

        - walk: traverse the term's whole cone and intersect
          (cost ~ its `descendant_count`);
        - probe: walk upward from each surviving candidate and keep those
          with every remaining term among their ancestors (cost ~
          len(result) x ancestor-cone size, independent of the remaining
          cones' sizes — and one pass settles *all* remaining terms).

        The loop also stops as soon as the running result is empty, so the
        largest cones are often never walked at all.

        Two kinds of cone take part in the plan (issue #14): present terms
        (walk = the descendant cone, probe = an upward climb) and virtual
        containment terms (walk = the contained present values and their
        cones, probe = a climb to a contained value — `is_below`'s virtual
        bound). There is no overlap mode: `get` is containment, and every
        term of a query is a containment term — a want's place and time
        are terms like its categories, and the gives in the answer fit
        within all of them (Peter, 2026-09-12: a want is the wider cone,
        a give the narrower one; overlap terms in the planner were built
        that day and withdrawn the same night, DIMENSIONS.md §8). A
        possibly-satisfies question is `get_overlapping`/`overlaps`, asked
        separately by a consumer that wants candidates rather than answers.

        `items_only=True` drops what carries the order rather than answers
        the question: parametric values (and any node with something filed
        under it) — the leaves that are not typed values. OntoDAG has no
        class/instance distinction, so "item" here is structural: nothing
        below it, not a value. On the lazy reader this costs one record per
        answer member served from a cone index.

        Note for future optimizers: a node whose parents are exactly {A, B} is
        NOT the meet of A and B — put(X, [A, B]) creates a *sibling* of such a
        node, never a child of it — so rewriting a query through "meet-named"
        nodes (answering get([A, B, C]) as cone(AB) ∩ cone(C)) silently loses
        results. See docs/plans/SEMANTIC_CODES.md §10 before adding such a rewrite;
        it is sound only with a canonical-placement invariant on put().
        """
        # 1. Resolve and deduplicate; terms may be name strings or Items
        # (names are the identity at the public boundary, and parametric
        # sugar canonicalizes first). An unknown ordinary term has an empty
        # cone; an unknown *parametric* term of a declared dimension is a
        # VIRTUAL term — its cone is computed, no node needs to exist and
        # none is created (DIMENSIONS.md §8).
        terms = {}
        parametric = {}  # canonical name -> (head, kind), present or not
        # A compound graph-kind term asks for its parts at once (§15): one
        # thing that meets every constraint, which is where `put` files it.
        names = [part for super_category in super_categories
                 for part in self._query_parts(_name_of(super_category))]
        for raw in names:
            parsed = self._parse_parametric(raw)
            if parsed is not None:
                parametric[parsed[2]] = (parsed[0], parsed[1])
                continue
            node = self.nodes.get(raw)
            if node is None:
                return set()
            terms[node.name] = node
        finish = self._items_only if items_only else (lambda found: found)
        if not terms and not parametric:
            # The EMPTY query is the universe, not an error: an intersection
            # of no cones is unconstrained, so everything qualifies. That is
            # the identity of the operation `get` performs — adding a term can
            # only ever narrow the answer, so removing every term must widen
            # it to the top — and it makes `get` total. Equivalently it is the
            # root's cone, so `get([])`, `get(["*"])` and the CLI's `list` are
            # one question with one answer.
            return finish(self.get_descendants(self.root))

        # 1a. Same-head parametric terms: one below the other keeps the
        # finer (its cone is the subset); provably disjoint ones are an
        # empty result before the graph is touched. Incomparable ones stay
        # SEPARATE cones for the planner to intersect — until 0.26.1 they
        # were met into one virtual term, which is not result-preserving:
        # the meet's cone holds the present values inside it, and an item
        # filed under both terms (a legacy or merged store; `put` now files
        # it under the meet, DIMENSIONS.md §9) is below neither of those.
        virtual = {}
        if parametric:
            by_head, head_kind = {}, {}
            for name, (head, kind) in parametric.items():
                head_kind[head] = kind
                kept = by_head.setdefault(head, [])
                for index, other in enumerate(kept):
                    if self._contains(other, name, kind):
                        kept[index] = name
                        break
                    if self._contains(name, other, kind):
                        break
                    if self._param_node(head, _dims.split_term(name)[1]) \
                            is None and self._param_node(
                                head, _dims.split_term(other)[1]) is None \
                            and self._intersect(other, name, kind) is None:
                        return set()
                else:
                    kept.append(name)
            for head, kept in by_head.items():
                for name in kept:
                    node = self.nodes.get(name)
                    if node is not None:
                        terms[name] = node   # present: an ordinary cone
                    else:
                        virtual[name] = (head, head_kind[head])

        # 2. Drop present terms subsumed by another present term. Asserted
        # edges only: same-head terms were compared by containment above,
        # and a climb through the computed order can cross every range
        # containing a value, which cost more than the query (§15). A drop
        # missed costs a cone, never an answer.
        nodes = list(terms.values())
        minimal = [
            node for node in nodes
            if not any(
                other is not node
                and node.descendant_count > other.descendant_count
                and self._has_ancestors(other, (node,), computed=False)
                for other in nodes
            )
        ]

        # 3. One list of cones, smallest estimated first (name as tiebreak,
        # keeping traversal deterministic). Sizes are asserted counts — the
        # exact walk cost for present terms, a lower bound for the others.
        cones = []
        for node in minimal:
            size = node.descendant_count
            parsed = self._parse_parametric(node.name)
            if parsed is not None:
                # A present graph-kind term's cone runs on through the terms
                # inside it, which its asserted count does not see.
                estimate = self._graph_part_estimate(node.name, *parsed[:2])
                if estimate is not None:
                    size = max(size, estimate)
            cones.append(_Cone("node", size, node.name, node))
        for name, (head, kind) in virtual.items():
            estimate = self._graph_part_estimate(name, head, kind)
            if estimate is not None:
                # Found only if walked: a broad part (`transport(mass(..30kg))`
                # beside `transport(c0)`) is cheaper probed per candidate.
                cones.append(_Cone("lazy", estimate, name, (head, kind)))
                continue
            values = self._contained_values(name, head, kind)
            cones.append(_Cone("virtual", self._cone_size(values), name,
                               values))
        cones.sort(key=lambda cone: (cone.size, cone.name))

        # Adaptive execution: walk or probe, decided per step from the now-
        # known size of the running result.
        result = self._walk_cone(cones[0])
        for index, cone in enumerate(cones[1:], start=1):
            if not result:
                break
            remaining = cones[index:]
            probe_cost = len(result) * self._PROBE_COST_ESTIMATE
            if probe_cost < sum(other.size for other in remaining):
                # One climb per candidate settles every remaining cone.
                # (A candidate can never equal a present query term: a
                # surviving term is an ancestor of no other term, so no term
                # lies inside another's cone — strict ancestry is right.)
                result = {candidate for candidate in result
                          if self._probe_cones(candidate, remaining)}
                break
            result &= self._walk_cone(cone)
        return finish(result)

    def _graph_part_estimate(self, name, head, kind):
        """A cheap size for a graph-kind query term, whose contained terms
        the planner then finds only if it walks it (None for other kinds,
        which keep their computed size). One part of a compound is often
        broad, and finding every term inside it, to intersect with a small
        answer, cost more than the answer (§15). A category constraint
        gives its asserted count. A value-only term gets the store's size:
        walking it finds every term inside its values, nested ranges each
        inside the next, so it is probed whenever another term narrows the
        query, and walked only when none does."""
        if kind != _dims.KIND_GRAPH:
            return None
        sizes = []
        for x in _dims.constraints(_dims.split_term(name)[1]):
            node = self.nodes.get(x) if _dims.split_term(x) is None else None
            if node is not None:
                sizes.append(node.descendant_count + 1)
        return min(sizes) if sizes else len(self.nodes) + 1

    def _query_parts(self, name):
        """A query term as the terms it asks for together: a compound
        graph-kind term is its parts, reduced (the finer of two related
        parts says all the coarser one does); any other name is itself."""
        split = _dims.split_term(name)
        if split is None or self._dimension_kind(split[0]) != _dims.KIND_GRAPH:
            return [name]
        return self._graph_parts(self._canonical_name(name))

    def _cone_size(self, values):
        """Estimated size of a computed cone: the values and what is
        asserted below them. Counts on an unexpanded lazy stub read 0, so
        a small anchor set is resolved through `self.nodes` first (which
        expands on the lazy reader, is a dict hit on the eager one); a large
        one is already a large estimate by its count alone."""
        if len(values) <= 32:
            values[:] = [self.nodes.get(value.name, value) for value in values]
        return sum(value.descendant_count + 1 for value in values)

    def _walk_cone(self, cone):
        if cone.kind == "node":
            return self.get_descendants(cone.payload)
        if cone.kind == "lazy":
            cone = cone._replace(payload=self._contained_values(
                cone.name, *cone.payload))
        # Virtual: one walk over every contained value, sharing what it
        # has visited. The values can nest (an interval inside an
        # interval), and a walk per value re-walked every value inside:
        # quadratic in the nesting.
        found, visited = set(), set()
        for value in cone.payload:
            found.add(value)
            found |= self.get_descendants(value, visited)   # combined order
        return found

    def _probe_cones(self, candidate, cones):
        """Is `candidate` in every one of `cones`, decided by climbing from
        it: present terms are strict ancestors (one combined climb, all at
        once); a virtual containment term is met when the candidate or a
        combined ancestor is one of its contained values."""
        # Each is an `is_below` question: it climbs from the candidate with
        # computed hops only where they can lead out of a head's terms, and
        # meets a term bound by containment, so a probe never enumerates
        # the terms that contain the candidate's own.
        return all(self.is_below(candidate.name, cone.name) for cone in cones)

    def _items_only(self, found):
        """The answer minus what only carries the order: parametric values
        and anything with something filed under it (DIMENSIONS.md §8's
        "items-only is a presentation flag", made real by issue #14)."""
        kept = set()
        for item in found:
            if self._parse_parametric(item.name) is not None:
                continue
            node = self.nodes.get(item.name, item)   # expands on lazy
            if not node.neighbors:
                kept.add(item)
        return kept

    def get_any(self, queries, items_only=False):
        """Union of conjunctive queries — `get` in disjunctive normal form.

        Each element of `queries` is a collection of terms exactly as
        `get` takes them (names or Items, parametric sugar and virtual
        terms included); the result is everything matching AT LEAST ONE of
        the conjunctions:

            get_any([{"Flight", "Japan"}, {"Hotel"}])  # (Flight AND Japan) OR Hotel

        `items_only` applies to every disjunct exactly as it does to `get`.

        Query-side only: no stored state, no new edge kind, canonical form
        untouched (DATABASE_DIRECTION.md "Pure now" item 3 — union is a
        question you ask, never a thing you store). Planner note, result-
        preserving like every planner step: after canonicalization, a
        disjunct whose term set is a strict superset of another's can only
        return a subset of that other's result (adding a term never widens
        a cone intersection), so it is skipped; the survivors each run
        through the ordinary `get` planner and their results union. An
        unknown term empties only its own disjunct — the other branches
        still answer.
        """
        normalized = []
        for query in queries:
            terms = frozenset(self._canonical_name(_name_of(term))
                              for term in query)
            # An empty disjunct is the universe (see `get`), and the pruning
            # below then does the right thing without a special case: the
            # empty term set is a strict subset of every other, so every
            # other disjunct is dropped and the union is everything.
            if terms not in normalized:
                normalized.append(terms)
        if not normalized:
            # The dual of the empty conjunction: a union of no disjuncts is
            # the empty set, as an intersection of no cones is everything.
            return set()
        minimal = [terms for terms in normalized
                   if not any(other < terms for other in normalized)]
        result = set()
        for terms in minimal:
            result |= self.get(terms, items_only=items_only)
        return result

    def is_below(self, node, super_category):
        """True iff `node` fits within `super_category` — equal to it, or
        below it in the combined (asserted + computed) order. The Boolean
        face of the DAG's one relation: "is A a solution to query B?".

        Answered UPWARD from `node` with early exit (the planner's
        direction rule: ancestor cones are shallow where descendant cones
        can be most of the graph — never answer a subsumption question by
        enumerating a cone). Unknown names fail closed to False, like
        `get`. Either side may be a *virtual* parametric term: same-head
        pairs decide by arithmetic from the names alone (no graph state
        needed — `is_below("weight(3kg)", "weight(..5kg)")` is a pocket
        containment check), a virtual bound is met by climbing to any
        present value contained in it, and a virtual subject relates
        upward only through the present values containing it.

        Note there is deliberately NO descendant_count pre-filter here:
        counts are asserted-only while this order is combined, so
        "a strict ancestor has a strictly larger count" — sound for the
        planner's optional term-dropping — would be an unsound *rejection*
        rule with dimensions (a point value with a large asserted cone
        sits below an interval whose asserted cone is empty).
        """
        sub = self._canonical_name(_name_of(node))
        sup = self._canonical_name(_name_of(super_category))
        key = ("below", sub, sup)
        hit = self._memo_get(key)
        if hit is not _MISSING:
            return hit
        trips = self._trips()
        return self._memo_put_unless_tripped(
            key, self._is_below_names(sub, sup), trips)

    def _is_below_names(self, sub, sup):
        """`is_below` on canonical names, unmemoized."""
        sub_parsed = self._parse_parametric(sub)
        sup_parsed = self._parse_parametric(sup)
        sub_node = self.nodes.get(sub)
        sup_node = self.nodes.get(sup)
        if (sub_node is None and sub_parsed is None) or \
                (sup_node is None and sup_parsed is None):
            return False                 # unknown vocabulary fails closed
        if sub == sup:
            return True                  # fits-within is reflexive
        # Same-dimension arithmetic is sound unconditionally (the computed
        # order is real whether or not the nodes exist) — and for a pair
        # with a virtual side it is also complete, short of cross edges.
        if sub_parsed is not None and sup_parsed is not None \
                and sub_parsed[0] in self._narrower(sup_parsed[0]) \
                and self._contains(sup, sub, sup_parsed[1]):
            return True
        if sup_parsed is not None and sup_parsed[1] == _dims.KIND_GRAPH:
            # A compound graph-kind bound: below it is below every part,
            # where `put` files a thing meeting every constraint (§15).
            parts = self._graph_parts(sup)
            if len(parts) > 1:
                return all(self.is_below(sub, part) for part in parts)
        if sub_node is None:
            # A virtual subject relates upward only through the present
            # values that contain it.
            head, kind, _ = sub_parsed
            above = self._hops(sub, head, kind, up=True)
            if above is None:
                return any(
                    self._contains(value.name, sub, kind)
                    and self.is_below(value, sup)
                    for value, _kind in self._stars(self._broader(head)))
            return any(self.is_below(name, sup) for name in above)
        if sup_parsed is not None:
            # A bound that is a term, present or virtual, is met by an
            # ancestor of its head whose denotation it contains (or the
            # subject itself, handled by the arithmetic above). Containment
            # is transitive, so the walk needs no computed hops between
            # same-head terms, and other heads' hops only where their terms
            # escape their star (`_lean`) — which keeps the walk from asking
            # where every term it passes sits, the questions that looped.
            # Streaming: each ancestor is tested AS the climb reaches it, so
            # the common case — the containing value is a direct parent —
            # answers in one hop (on a lazy reader, a couple of fetches
            # instead of all of them).
            head, kind, _ = sup_parsed
            narrower = self._narrower(head)
            same = []
            for ancestor in self._walk_ancestors(sub_node, computed=self._lean):
                parsed = self._parse_parametric(ancestor.name)
                if parsed is not None and parsed[0] in narrower:
                    if self._contains(sup, ancestor.name, kind):
                        return True
                    same.append(ancestor.name)
            if sup_node is not None or kind in _dims.MULTI_VALUED:
                return False     # no meet for these: the walk is complete
            # A subject under several same-head values (a legacy or merged
            # store; `put` files under the meet since 0.26.2) sits in their
            # meet, which may be inside the bound though no single value is.
            if len(same) < 2:
                return False     # one value, or none: the walk was the answer
            if kind not in _dims.GRAPH_ORDERED \
                    and self._dimension_of(head)[1] != head:
                upper = self._bounds(sub)[0].get(head)   # a role: base bounds
            else:
                # The meet of the values the walk just met: what
                # `_bounds` would compute, without walking every head's
                # ancestors again (which recursed through this very
                # fallback, and went exponential).
                upper = same[0]
                for other in same[1:]:
                    upper = self._intersect(upper, other, kind)
                    if upper is None:
                        return False
            return upper is not None and upper != sub \
                and self._contains(sup, upper, kind)
        return self._has_ancestors(sub_node, (sup_node,), computed=self._lean)

    def _remove_duplicate_root_edges(self):
        # No longer load-bearing since _remove_unneeded_edges covers the
        # full redundancy rectangle (2026-08-04): instrumented across the
        # suite and the replay fuzz, this never fires on graphs built
        # through add_edge. Kept as a safety net for merges ON TOP OF a
        # hydrated legacy store, whose pre-existing duplicate root edge
        # sits outside every replayed edge's rectangle (hydrate is
        # verbatim by design; ontodag.migrate is the real fix there).
        edges_to_remove = set()
        root = self.root
        for root_neighbor in root.neighbors:
            ancestors = self.get_ancestors(root_neighbor, ignore={root})
            if any(ancestor in root.neighbors for ancestor in ancestors):
                edges_to_remove.add(root_neighbor)

        for root_neighbor in edges_to_remove:
            self.remove_edge(root, root_neighbor)

    def _remove_unneeded_edges(self, from_node, to_node):
        """Remove every edge made redundant by the new from -> to edge.

        An edge (x, y) is *newly* redundant exactly when its only witness
        paths run through the new edge, i.e. x reaches `from_node` and
        `to_node` reaches y — both in the combined (asserted + computed)
        order. So x ∈ {from} ∪ ancestors(from) and y ∈ {to} ∪
        descendants(to), and the two loops below cover that rectangle:
        the upward rule handles y = to, the downward twin y below to.
        (The witness path can never traverse (x, y) itself — either
        segment doing so would close a cycle through the new edge — so
        every rectangle edge is genuinely redundant, and nothing outside
        it can be.) This completeness is what keeps the stored form the
        unique transitive reduction of the asserted union whatever order
        edges arrive in — the precondition for canonical roots and for
        the multi-writer merge converging byte-identically (I2/I3/I7).

        Anchor edges (head -> value) are schema and never pruned — they
        are the dimension's enumeration index (DIMENSIONS.md §5), and
        pruning them would leave stored form dependent on which other
        values happen to exist. They remain valid witness-path steps."""
        self._prune_rectangle(from_node, to_node)

    def _prune_rectangle(self, upper, lower):
        """Remove every asserted edge made redundant by upper ⇒ lower — the
        new asserted edge in `_remove_unneeded_edges`, or a COMPUTED hop
        that has just appeared (`_reduce_roles_touching`). The pair
        itself is never touched: as an asserted edge it is the one being
        added, as a computed hop it is not an edge at all.

        Every test here is an `is_below` question about one candidate
        edge, so the cost is the parents of `lower` and of what lies below
        it, never the whole ancestry of `upper` (a term's containing terms
        can be a long chain, or every member of a group)."""
        from_node, to_node = upper, lower
        if self._below(from_node, to_node) or (
                self._total()
                and from_node in self.get_ancestors(from_node)):
            # The pair lies on a cycle. Only a merge of contradictory
            # knowledge makes one (x in y in one store, y in x in another:
            # a transitive head's terms then contain each other), since
            # `put` refuses both cycles and self-containment. Every witness
            # path here could run through the edge it would prune, so
            # nothing is pruned: the asserted edges stay as data, and no
            # node is left without a parent.
            return
        for parent in list(self._live_parents(to_node)):
            if parent is not from_node \
                    and not self._is_anchor(parent, to_node) \
                    and self._below(from_node, parent):
                self.remove_edge(parent, to_node)
        # Downward twin. A fresh ordinary leaf has nothing below it — the
        # overwhelmingly common put(item, supers) case costs nothing. A
        # parametric to_node can reach siblings through computed hops even
        # with no asserted children, so it never takes the shortcut.
        if not to_node.neighbors \
                and self._parse_parametric(to_node.name) is None:
            return
        for descendant in self.get_descendants(to_node):  # combined order
            # Snapshot: remove_edge mutates the parent set mid-iteration.
            # _live_parents is the seam the partially-resident writer
            # overrides, so this walk stays fetch-on-touch there.
            for parent in list(self._live_parents(descendant)):
                if (parent is from_node or self._below(from_node, parent)) \
                        and not self._is_anchor(parent, descendant):
                    self.remove_edge(parent, descendant)

    def _reduce_roles_touching(self, from_node, to_node):
        """Keep stored form canonical when an edge moves a term's arguments.

        A computed hop such as `from(my_home) ⊑ from(u2e4x)` or
        `in(tokyo) ⊑ in(japan)` holds only while the nodes the terms name
        stand where they do, so filing one of those nodes can make an
        asserted edge redundant that no rectangle around the new edge sees
        (the hop is a wormhole between a head's terms and the graph).
        `_moved_terms` finds the terms that gained a parent, from what the
        edge put under something new, and their computed parents are
        re-reduced. A reversed head works the other way round: a term
        naming a node above the edge gains, as a parent, a term naming a
        node below it, and those pairs are re-reduced. Without this the
        stored form would depend on whether places were filed before or
        after the offers naming them (I3, and therefore I7). The graph
        kind's terms move the same way: a job under `transport(piano)` and
        `transport(heavy-item)` keeps one edge once pianos are heavy, as it
        would had that been known when the job was filed (§15)."""
        roles = self._role_heads()
        heads = self._multi_valued_heads() + self._graph_kind_heads()
        if not roles and not heads:
            return
        touched = []
        moved, pairs = self._moved_terms(from_node, to_node, roles, heads,
                                         touched)
        # A stored compound whose constraints the edge related is re-filed
        # under its current spelling first (`_respell_stored`); then what
        # moved is read again from the graph that re-filing left.
        compounds = [t.name for t in touched if t.name in self._compound_terms]
        if compounds and self._respell_stored(compounds):
            moved, pairs = self._moved_terms(from_node, to_node, roles, heads)
        for term in moved:
            for parent in list(self._computed_parents(term)):
                self._prune_rectangle(parent, term)
        for upper, lower in pairs:
            if upper.name in self.nodes and lower.name in self.nodes:
                self._prune_rectangle(upper, lower)

    def _respelling(self, name):
        """The current spelling of `name`, a stored term the graph orders,
        or None when it is current. A compound's spelling follows the graph
        (a redundant constraint is dropped, `_canonical_graph_term`), and a
        stored name does not: once `sales-employee ⊑ employee` is filed,
        `shared-with(employee sales-employee)` is spelled
        `shared-with(sales-employee)`."""
        split = _dims.split_term(name)
        if split is None or getattr(self, "_role_lenient", 0):
            return None
        if self._dimension_kind(split[0]) not in _dims.GRAPH_ORDERED:
            return None
        try:
            current = self._canonical_graph_term(name)
        except ValueError:
            return None          # a constraint no longer parses: leave it
        return None if current == name else current

    def _refile(self, term, name):
        """Re-file what is filed under `term`, a stored spelling the graph
        has left behind, under `name`, its current spelling (the same
        class), and drop `term`: one class keeps one name (I1), and the
        stored form is the same whether the term or the fact that made one
        of its constraints redundant came first (Peter's option 1,
        2026-10-08)."""
        term = self.nodes.get(term.name, term)           # expands on lazy
        head, kind, _ = self._parse_parametric(name)
        target = self._ensure_parametric_node(name, head, kind)
        children = list(term.neighbors)
        for child in children:
            self.remove_edge(term, child)
        for parent in list(self._live_parents(term)):
            self.remove_edge(parent, term)
        self._forget(term.name)
        for child in children:
            if child.name in self.nodes and not self.is_below(child.name, name):
                self.add_edge(target, self.nodes[child.name])

    def _respell_stored(self, names):
        """Re-file every stored compound among `names` whose spelling the
        graph has left behind (`_respelling`), inner terms first, and then
        the terms naming each one re-filed, whose own spelling changes
        with it (`in(in(employee sales-employee))`). Returns whether
        anything moved. A replay (merge, sync) lands nodes before their
        edges, so inside one the names wait for `_respell_deferred`."""
        if getattr(self, "_role_lenient", 0):
            later = getattr(self, "_respell_later", None)
            if later is None:
                later = self._respell_later = set()
            later.update(names)
            return False
        depth = lambda n: (n.count("("), n)
        pending = sorted({n for n in names if n in self.nodes}, key=depth)
        moved = False
        while pending:
            name = pending.pop(0)
            if name not in self.nodes:
                continue
            current = self._respelling(name)
            if current is None:
                continue
            naming = [t for t in self._args_index().get(name, ())
                      if t in self.nodes and t not in pending]
            self._refile(self.nodes[name], current)
            moved = True
            if naming:
                pending = sorted(set(pending) | set(naming), key=depth)
        return moved

    def _respell_deferred(self, names=()):
        """After a replay: re-spell what its edges touched, and `names`
        (the compounds the replay brought in, which may arrive in a store
        that already relates their constraints)."""
        later = getattr(self, "_respell_later", None) or set()
        self._respell_later = set()
        self._args_index()
        return self._respell_stored(
            [n for n in {*later, *names} if n in self._compound_terms])

    def _moved_terms(self, from_node, to_node, roles, heads, touched=None):
        """The terms the edge `from ⊑ to` gave a new parent, as
        (covariant terms, [(upper, lower) pairs of a reversed head]).

        Only terms can move: a term's place depends on the nodes it names,
        and the edge put `to` and everything below it under something new.
        Each of those names is looked up in the argument index (and, for a
        role, under the spelling the role gives it), and a term found there
        takes its own cone along, which is looked up in turn, to a
        fixpoint. A term of a reversed head naming one of those nodes is
        the upper end of a new hop whose lower end is a reversed term
        naming a node above `from`. With no nested constraint the walks
        follow asserted edges and the hops of values only, since nothing
        else they could reach is named by any term."""
        nested = self._graph_nested()
        flipped = {h for h in heads
                   if self._dimension_kind(h) == _dims.KIND_REVERSED}
        straight = set(heads) - flipped
        if nested:
            start = [to_node.name] + [d.name for d in self.get_descendants(to_node)]
        else:
            start = self._below_names(to_node.name, None)
        upper_terms = []
        if flipped:
            above = ([from_node.name] + [a.name for a in self.get_ancestors(from_node)]
                     if nested else self._ancestry(from_node.name))
            upper_terms = [self.nodes[t] for name in above
                           for t in self._args_index().get(name, ())
                           if t in self.nodes and _dims.split_term(t)[0] in flipped]
        base_of = {role: self._dimension_of(role)[1] for role in roles}
        seen, queue = set(start), list(start)
        moved, moved_names, pairs = [], set(), []

        def take(term):
            for node in [term, *self.get_descendants(term)]:
                if node.name not in seen:
                    seen.add(node.name)
                    queue.append(node.name)

        nested_keys = []
        if nested:
            heads_now = self._heads()
            nested_keys = [k for k in self._nested_keys if heads_now.get(
                _dims.split_term(k)[0], (None,))[0] in _dims.GRAPH_ORDERED]
        while queue:
            name = queue.pop()
            # A term the graph orders, named only as a constraint (`option(
            # transport(piano))` with no transport(piano) node), moves with
            # what it names, and so do the terms naming it.
            for key in nested_keys:
                if key not in seen and name in _dims.constraints(
                        _dims.split_term(key)[1]):
                    seen.add(key)
                    queue.append(key)
            found = [t for t in self._args_index().get(name, ())
                     if t in self.nodes]
            if touched is not None:
                touched.extend(self.nodes[t] for t in found)
            for role in roles:
                spellings = [f"{role}({name})"]
                split = _dims.split_term(name)
                if split is not None and split[0] == base_of[role]:
                    spellings.append(f"{role}({split[1]})")
                found.extend(t for t in spellings if t in self.nodes)
            for t in found:
                head = _dims.split_term(t)[0]
                if head in flipped:
                    upper = self.nodes[t]
                    narrower = self._narrower(head)
                    for lower in upper_terms:
                        if lower is not upper and _dims.split_term(
                                lower.name)[0] in narrower and self._contains(
                                    upper.name, lower.name, _dims.KIND_REVERSED):
                            pairs.append((upper, lower))
                            take(lower)
                elif (head in straight or head in base_of) \
                        and t not in moved_names:
                    moved_names.add(t)
                    moved.append(self.nodes[t])
                    take(self.nodes[t])
        return moved, pairs

    def _terms_moved_by(self, from_node, to_node, roles, heads):
        """Present terms whose computed hops the edge `from ⊑ to` can move
        (for `_term_on_new_cycle`): both ends of every hop it creates."""
        moved, pairs = self._moved_terms(from_node, to_node, roles, heads)
        out, seen = [], set()
        for term in [*moved, *(t for pair in pairs for t in pair)]:
            if term.name not in seen:
                seen.add(term.name)
                out.append(term)
        return out

    def _term_on_new_cycle(self, from_node, to_node):
        """A present term the edge just added has put below itself, or None.

        The cycle check in `add_edge` runs before the edge exists, so it
        sees only the computed hops already there. The edge can create new
        ones, and a new hop can close a loop: with `transport(vehicle) ⊑
        rush ⊑ transport(bicycle)`, filing `bicycle` under `vehicle` adds
        `transport(bicycle) ⊑ transport(vehicle)` (DIMENSIONS.md §18). The
        same holds for role terms. Such a loop must leave the terms of some
        head through an asserted parent other than the head (`_escapes`),
        so only heads with such a term are checked: role heads, and merged
        data, since `put` refuses it for every graph-ordered kind
        (`_refuse_rule`). A transitive term inside itself needs no loop at
        all, which is what `_refuse_self_containment` is for. Replays
        (merge, sync) stay total and are never checked."""
        if self._total():
            return None
        heads = self._heads()
        if not heads:
            return None
        # Only heads whose terms the graph orders can gain a hop from an
        # edge; a value's place is fixed by its name. (A head filed under
        # an ordinary node, as loopmarket files `transport` under
        # `operator`, opens no way out: checking it anyway would refuse
        # plain facts whenever a folded graph-kind term became redundant.)
        roles = [head for head, (_kind, base) in heads.items()
                 if base != head and self._escapes(head)]
        graph = [head for head, (kind, _base) in heads.items()
                 if kind in _dims.GRAPH_ORDERED and self._escapes(head)]
        if not roles and not graph:
            return None
        for term in self._terms_moved_by(from_node, to_node, roles, graph):
            if term in self.get_ancestors(term):
                return term
        return None

    def _escapes(self, head):
        """Does some term of `head` hang under something other than its
        head? Only then can a walk through those terms' computed hops reach
        anything their own anchor edge does not: otherwise the hops lead to
        more terms of the same head, and from them only to the head, the
        kind, `dimension` and the root.

        Cached per DAG rather than per shape, because `add_edge` asks it on
        every edge: an edge into a term from anything but its head sets
        the head's entry, removing one drops it (`_note_escape`), and
        `_forget` drops them all. A hydrated graph, or a lazy reader that
        expands the star as it scans, computes an entry on first use."""
        cache = getattr(self, "_escape_cache", None)
        if cache is None:
            cache = self._escape_cache = {}
        hit = cache.get(head)
        if hit is not None:
            return hit
        head_node = self.nodes.get(head)
        escapes = False
        for child in list(head_node.neighbors) if head_node is not None else ():
            split = _dims.split_term(child.name)
            if split is None or split[0] != head:
                continue
            term = self.nodes.get(child.name)           # expands on lazy
            if term is not None and any(
                    parent is not head_node and self.nodes.get(parent.name) is parent
                    for parent in term.parents):
                escapes = True
                break
        cache[head] = escapes
        return escapes

    def _note_escape(self, from_node, to_node, added):
        """Keep `_escapes` current across one edge into a term."""
        cache = getattr(self, "_escape_cache", None)
        split = _dims.split_term(to_node.name)
        if cache is None or split is None or split[0] == from_node.name:
            return
        if added:
            cache[split[0]] = True
        else:
            cache.pop(split[0], None)

    def _lean(self, node):
        """The walk test `is_below` uses: a node's computed parents are
        walked only when it is a term whose head escapes (`_escapes`). A
        bound that is itself a term is decided by containment against the
        same-head ancestors directly, which is transitive, so it never needs
        those ancestors' own computed parents."""
        parsed = self._parse_parametric(node.name)
        return parsed is not None and self._escapes(parsed[0])

    def _transitive_heads(self):
        """Every declared head of the transitive kind (DIMENSIONS.md §16)."""
        return [head for head, (kind, _base) in self._heads().items()
                if kind == _dims.KIND_TRANSITIVE]

    def _multi_valued_heads(self):
        """Every declared head an item can hold several values of at once:
        the transitive, enclosing and reversed kinds (§16–§18)."""
        return [head for head, (kind, _base) in self._heads().items()
                if kind in _dims.MULTI_VALUED]

    def _graph_kind_heads(self):
        """Every declared head of the graph kind (§15)."""
        return [head for head, (kind, _base) in self._heads().items()
                if kind == _dims.KIND_GRAPH]

    def _refuse_rule(self, term, head, parent):
        """A graph-ordered term filed under anything but its head states a
        rule about every item under it, not a fact about one item:
        `in(japan)` under `japanese` says that whatever is in Japan is
        Japanese. Rules are not stored (CONTRACT.md §5.1): with them,
        whether one term contains another stops being a walk from the names
        involved and becomes a computation over every rule in the store
        (it went exponential, DIMENSIONS.md §18), and two stores that know
        the same thing could hold different roots."""
        raise ValueError(
            f"{term} goes only under {head!r}: filing it under {parent} "
            f"would state a rule, that everything under {term} is under "
            f"{parent}, and rules are not stored (CONTRACT.md §5.1). File "
            f"each item under both, or apply the rule outside the store")

    def _refuse_self_containment(self, parent_name, child_name):
        """A transitive relation here is STRICT: nothing is in itself
        (DIMENSIONS.md §16). Allowing it would let two different names
        denote one class — with x in y and y in x, in(x) and in(y) contain
        each other — and the core gives each class one name (I1).

        `child ⊑ parent` can only put something inside itself if that
        something is `child` or below it, so each of those is checked
        against every transitive head, asking whether `parent` is already
        below R(that thing) in the graph as it stands. The rest of such a
        path needs no new edge, or the cycle check would have refused it.
        Nothing is checked unless some transitive term is at or above
        `parent`, which is the common case's fast path. Names, not nodes,
        so `put` and `reclassify` can ask before materializing anything:
        a refusal leaves no new vocabulary behind. Replays (merge, sync)
        are lenient, as with role parameters: a merge must stay total, so
        a merged store can hold what `put` refuses."""
        if self._total():
            return
        heads = self._transitive_heads()
        child = self.nodes.get(child_name)
        if not heads or child is None:
            return        # a new name is not yet anywhere, nor named by a term
        def transitive_term(name):
            parsed = self._parse_parametric(name)
            return parsed is not None and parsed[1] == _dims.KIND_TRANSITIVE
        parent = self.nodes.get(parent_name)
        if not transitive_term(parent_name) and (parent is None or not any(
                transitive_term(a.name)
                for a in self._walk_ancestors(parent, computed=self._lean))):
            return
        split = _dims.split_term(parent_name)
        if _dims.split_term(child_name) is None and not child.neighbors \
                and not any(self._terms_naming(child_name, head)
                            for head in heads) \
                and (split is None or split[0] not in heads
                     or child_name not in _dims.constraints(split[1])):
            # Nothing is below `child` and no term names it, so nothing can
            # be inside it, and the parent does not name it either: the
            # edge cannot put anything inside itself. The common filing of
            # a new place. (The parent may not exist yet; a parent naming
            # the child, `x ⊑ in(x)`, must reach the check below, here,
            # before put materializes it.)
            return
        # What the parent is inside, once per head; then each node the edge
        # puts under it is looked up there. (Asking is_below(parent, R(x))
        # node by node walked the parent's containers again for each: a
        # chain filed one place at a time cost quadratic time.)
        inside = {head: set(self._containers(parent_name, head))
                  for head in heads}
        for node in [child, *self.get_descendants(child)]:
            name = node.name
            if name == self.root.name or _dims.is_kind_node(name) \
                    or _dims.constraints(name) != (name,):
                continue          # cannot be an argument, so never inside itself
            for head in heads:
                if name in inside[head]:
                    raise ValueError(
                        f"{child_name} ⊑ {parent_name} would put {name} "
                        f"inside itself: {head} is strict, so nothing is "
                        f"{head} itself (DIMENSIONS.md §16)")

    def _forget(self, name):
        """Drop a node from the graph — the ONE place a node stops existing.

        A single seam because a partially-resident writer has to know: it stages
        a store delete from it (`SparseOntoDAG`). `remove_cone` deleting nodes
        directly is exactly how a sparse cone removal came to commit a root
        that still contained the deleted records."""
        del self.nodes[name]
        self._changed()
        self._unindex(name)
        self._heads_cache = None
        self._dim_cache = None
        self._escape_cache = None

    # ---- terms that name a category: removal and rename -------------------
    #
    # A term names categories (`in(paris)`, `about(paris)`,
    # `shared-with(alice)`, `transport(bicycle)`, a role's `from(my_home)`),
    # so a category must not stop existing while a term still names it: the
    # term would be left naming nothing, quietly cut off from everything the
    # category related it to (the Louvre, `in(paris)`, would no longer be in
    # France), and a share naming a removed contact would come back by
    # itself if the contact were ever added again. So removal refuses,
    # naming the terms, unless the terms go too, and then each is contracted
    # the way `remove` contracts any category: what was under it moves to
    # the terms just above it (decided with Peter, 2026-10-09; DIMENSIONS.md
    # §14). `rename` is the other way out, for a name that was the mistake.

    def _naming_term(self, name):
        """Is `name` a term that names a category: a term of a head the graph
        orders, or a role term whose parameter is a place (not a value)."""
        split = _dims.split_term(name)
        if split is None or _dims.is_kind_node(name):
            return False
        found = self._heads().get(split[0])
        if found is None:
            return False
        kind, base = found
        if kind in _dims.GRAPH_ORDERED:
            return True
        return base != split[0] and self._param_node(split[0], split[1]) is not None

    def _namers(self, name):
        """The present terms with `name` among their constraints: terms of the
        heads the graph orders (`in(paris)`, `in(museum paris)`,
        `shared-with(paris)`) and role terms naming it as a place. Found in
        the argument index on a resident graph; a partial one reads each
        such head's list of terms instead, one record per head, since a term
        it never loaded is in no index."""
        found = {term.name for term in self._role_terms_naming(name)}
        ordered = {head for head, (kind, _base) in self._heads().items()
                   if kind in _dims.GRAPH_ORDERED}
        if not ordered:
            return sorted(found)
        if self._resident:
            candidates = list(self._args_index().get(name, ()))
        else:
            candidates = [child.name for head in sorted(ordered)
                          if self.nodes.get(head) is not None
                          for child in list(self.nodes[head].neighbors)]
        for term in candidates:
            split = _dims.split_term(term)
            if split is not None and split[0] in ordered and term in self.nodes \
                    and name in _dims.constraints(split[1]):
                found.add(term)
        return sorted(found)

    def _names_any(self, term, names):
        """Does `term` name one of `names`, at any depth of nesting?"""
        split = _dims.split_term(term)
        if split is None:
            return False
        return any(constraint in names or self._names_any(constraint, names)
                   for constraint in _dims.constraints(split[1]))

    def _refuse_if_named(self, name, gone=()):
        """Refuse to let `name` stop existing while a term not in `gone`
        names it."""
        naming = [term for term in self._namers(name) if term not in gone]
        if not naming:
            return
        def filed(term):
            n = len(self.nodes[term].neighbors)
            return f"{term} ({n} item{'' if n == 1 else 's'})"
        raise ValueError(
            f"{name} is named by {', '.join(filed(t) for t in naming)}: "
            f"removing it would leave {'that term' if len(naming) == 1 else 'them'} "
            f"naming nothing. Remove {'it' if len(naming) == 1 else 'them'} with it "
            f"(--with-terms: what is under a term moves to the terms just "
            f"above it), rename {name}, or re-file what is under "
            f"{'it' if len(naming) == 1 else 'them'} first (DIMENSIONS.md §14)")

    def _below_quiet(self, sub, sup):
        try:
            return self.is_below(sub, sup)
        except (ValueError, KeyError):
            return False

    def _substitution_parents(self, constraint, gone, memo):
        """What may stand in for `constraint` once it is gone: a removed
        term's own replacements for a nested one, else the parents of the
        node it names, climbing past parents that are going too."""
        heads = self._heads()

        def usable(name):
            # A relation head stands for no class of things: `in(in)` is sound
            # and says nothing, so a bare head never becomes a constraint.
            found = heads.get(name)
            return found is None or found[0] not in _dims.GRAPH_ORDERED

        if constraint in gone and self._naming_term(constraint):
            return [r for r in self._replacements(constraint, gone, memo)
                    if usable(r)]
        out, seen = [], {constraint}
        stack = [constraint]
        while stack:
            node = self.nodes.get(stack.pop())
            if node is None:
                continue
            parents = [p for p in self._live_parents(node) if p is not self.root]
            parents += list(self._computed_parents(node))
            for parent in parents:
                if parent.name in seen:
                    continue
                seen.add(parent.name)
                if parent.name in gone:
                    if self._naming_term(parent.name):   # a term going too
                        out.extend(r for r in self._replacements(
                            parent.name, gone, memo)
                            if usable(r) and r not in out)
                    else:
                        stack.append(parent.name)     # going too: its parents
                elif usable(parent.name) and parent.name not in out:
                    out.append(parent.name)
        return out

    def _replacements(self, term, gone, memo=None):
        """Where what is filed under `term` goes when `term` is removed: the
        lowest terms above it in the combined order that name nothing in
        `gone` — what `remove` means for any category, applied to a term.

        Each constraint of `term` in `gone` is replaced by each parent of the
        node it names, or dropped (when none is gone, the term itself is
        what goes, and its constraints are replaced one at a time). Paris
        was a city and was in France, so `in(paris)` gives `in(city)` and
        `in(france)`: a parent `in(Z…)` also gives `Z…` under the relations
        that follow containment, beside the other constraints and alone. A
        candidate is kept only where the order puts it above `term`, which
        is also what keeps a share from widening: `shared-with(employee)` is
        *below* `shared-with(alice)`, so a share naming a removed person goes
        to the bare `shared-with`, where it reaches nobody. With nothing
        left, the bare head."""
        memo = {} if memo is None else memo
        if term in memo:
            return memo[term]
        memo[term] = []                           # a cycle of names: nothing
        head, param = _dims.split_term(term)
        kind, base = self._heads()[head]
        constraints = list(_dims.constraints(param))
        removed = [c for c in constraints if c in gone]
        plans = [removed] if removed else [[c] for c in constraints]
        follows = set()
        if kind in (_dims.KIND_TRANSITIVE, _dims.KIND_ENCLOSING):
            follows = {h for h, (k, _b) in self._heads().items()
                       if k == _dims.KIND_TRANSITIVE}
        role_base = base if kind not in _dims.GRAPH_ORDERED and base != head else None

        sets = set()
        for plan in plans:
            rest = [c for c in constraints if c not in plan]
            choices = []
            for constraint in plan:
                options = [()]                    # dropped
                for parent in self._substitution_parents(constraint, gone, memo):
                    split = _dims.split_term(parent)
                    if split is not None and split[0] in follows:
                        # Paris in France: `in(paris)` gives `in(france)`. The
                        # nested `in(in(france))` sits just below it in the
                        # order, but the relation's own rule already says
                        # whatever is in Paris is in France, so it says
                        # nothing a reader wants and is not offered.
                        inside = tuple(_dims.constraints(split[1]))
                        options.append(inside)
                        sets.add(frozenset(inside))
                        continue
                    options.append((parent,))
                    if role_base is not None and split is not None \
                            and split[0] == role_base:
                        options.append((split[1],))   # a value of the base
                choices.append(options)
            combos = [()]
            for options in choices:
                combos = [combo + option for combo in combos for option in options]
            for combo in combos:
                sets.add(frozenset(rest) | frozenset(combo))

        names = set()
        for constraints_set in sets:
            if not constraints_set:
                continue
            try:
                names.add(self._canonical_name(
                    f"{head}({' '.join(sorted(constraints_set))})"))
            except ValueError:
                continue
        kept = [name for name in sorted(names - {term})
                if not self._names_any(name, gone)
                and self._below_quiet(term, name)]
        lowest = [name for name in kept
                  if not any(other != name and self._below_quiet(other, name)
                             for other in kept)]
        memo[term] = lowest or [head]
        return memo[term]

    def _contract_term(self, term, targets):
        """Remove the term node `term`, filing what was under it under
        `targets` (its `_replacements`). A target is materialized only when
        an item needs it, so no empty term is left behind, and an item left
        under nothing goes top-level, as everywhere."""
        node = self.nodes[term]
        children = sorted(node.neighbors, key=lambda n: n.name)
        for child in children:
            self.remove_edge(node, child)
        for parent in list(self._live_parents(node)):
            self.remove_edge(parent, node)
        self._forget(term)
        parts = []
        for target in targets:
            for part in self._graph_parts(target):
                if part not in parts:
                    parts.append(part)
        for child in children:
            child = self.nodes.get(child.name)
            if child is None:
                continue
            for part in parts:
                if self.is_below(child.name, part):
                    continue
                target = self.nodes.get(part)
                if target is None:
                    parsed = self._parse_parametric(part)
                    target = self._ensure_parametric_node(part, parsed[0], parsed[1])
                self.add_edge(target, child)
            if not self._live_parents(child):
                self.add_edge(self.root, child)

    def removal_plan(self, names, with_terms=False):
        """What `remove_many(names, with_terms)` would do, without doing it:
        (the names that go, terms included, and {term: the terms what is
        under it moves to}). Raises as the removal would — an unknown name,
        the root, or a category still named by a term that is not going too.

        A term goes when it is named here, or, with `with_terms`, when it
        names something that goes (and so on, for a term naming such a
        term)."""
        resolved = self._resolve_for_removal(names)
        gone = set(resolved)
        frontier = list(resolved)
        while frontier:
            name = frontier.pop()
            naming = [term for term in self._namers(name) if term not in gone]
            if naming and not with_terms:
                self._refuse_if_named(name, gone)
            for term in naming:
                gone.add(term)
                frontier.append(term)
        memo = {}
        moves = {term: self._replacements(term, gone, memo)
                 for term in sorted(gone) if self._naming_term(term)}
        return sorted(gone), moves

    def remove_many(self, names, with_terms=False):
        """Remove categories by contraction: each one goes and its children
        reattach to its parents, so nothing below it is lost. Terms are
        contracted the same way, into the terms just above them
        (`_replacements`). Everything is checked before anything moves, so
        a refusal leaves the store as it was. Returns the names removed."""
        gone, moves = self.removal_plan(names, with_terms)
        gone_set = set(gone)
        for term, targets in moves.items():
            parts = [part for target in targets
                     for part in self._graph_parts(target)]
            for child in sorted(self.nodes[term].neighbors, key=lambda n: n.name):
                keeping = [n for n in self._live_parent_names(child.name)
                           if n not in gone_set and n != self.root.name]
                self._check_parametric_placement(child.name, parts, also=keeping)
        depth = lambda n: (-n.count("("), n)       # outer terms first
        for term in sorted(moves, key=depth):
            if term in self.nodes:
                self._contract_term(term, moves[term])
        for name in gone:
            if name in self.nodes and name not in moves:
                self._contract_node(name, gone_set)
        return gone

    def clear(self):
        """Remove every node but the root, in place: what `import` does before
        merging what it imports, so a persisted store keeps its identity and
        its commit diffs against what it hydrated. Everything goes together,
        so no term is left naming anything and nothing is refused."""
        everything = set(self.nodes) - {self.root.name}
        for name in list(self.nodes):
            if name != self.root.name and name in self.nodes:
                self._contract_node(name, everything)

    def _carry_extras(self, old, new):
        """What a node carries besides its edges, carried from `old` to `new`
        when `old` is renamed (metadata here; a persisted store's payload in
        the subclasses). What `new` already has wins."""
        for key, value in self.nodes[old].metadata.items():
            self.nodes[new].metadata.setdefault(key, value)

    def rename(self, old, new):
        """Give the category `old` the name `new`, for a name that was the
        mistake. Everything filed under it, its own placement, and every term
        naming it follow (`in(old)` becomes `in(new)`, a role's `from(old)`
        becomes `from(new)`), and `old` is gone. When `new` already exists
        the two become one category: the correction for a duplicate or a
        misspelling of one. Not for a term or a value (its name follows its
        constraints: rename the category it names) nor for a dimension head
        or a registry node (every term of it is spelled with it).

        Like every removal, a rename is local: a peer that still has `old`
        brings it back when merged. Returns {old spelling: new spelling} of
        the terms re-spelled."""
        old = self._canonical_name(_name_of(old))
        new = _name_of(new).strip()
        if old == self.root.name or new == self.root.name:
            raise ValueError("Cannot rename the root.")
        if old not in self.nodes:
            raise ValueError(f"Category {old} does not exist.")
        heads = self._heads()
        reserved = {_dims.DIMENSION_ROOT, _dims.UNIT_DECLARATION}
        for name in (old, new):
            if not name:
                raise ValueError("A category's name cannot be empty.")
            if _dims.split_term(name) is not None or _dims.is_kind_node(name):
                raise ValueError(
                    f"{name} is a term: its name follows its constraints, so "
                    f"rename the category it names instead.")
            if name in heads or name in reserved:
                raise ValueError(
                    f"{name} is a dimension head or a registry node: every "
                    f"term of it is spelled with it, so it cannot be renamed.")
        if old == new:
            return {}

        node = self.nodes[old]
        parents = [p.name for p in self._live_parents(node) if p is not self.root]
        children = sorted(c.name for c in node.neighbors)
        naming, frontier = [], [old]
        while frontier:
            for term in self._namers(frontier.pop()):
                if term not in naming:
                    naming.append(term)
                    frontier.append(term)

        # Checked before anything moves. Merging into an existing `new`
        # skips what would close a cycle: a parent of `old` already below
        # `new`, a child of `old` already above it. And nothing may end up
        # inside itself under a strict relation.
        merging = new in self.nodes
        if merging:
            parents = [p for p in parents if p != new and not self.is_below(p, new)]
            children = [c for c in children if c != new and not self.is_below(new, c)]
        for term in naming:
            split = _dims.split_term(term)
            if self._heads().get(split[0], (None,))[0] == _dims.KIND_TRANSITIVE \
                    and old in _dims.constraints(split[1]) \
                    and any(child.name == new for child in self.nodes[term].neighbors):
                raise ValueError(
                    f"{new} is filed under {term}: as one category, {new} would "
                    f"be inside itself, and {split[0]} is strict (DIMENSIONS.md §16)")

        if merging:
            for parent in parents:
                self.add_edge(self.nodes[parent], self.nodes[new])
        else:
            self.put(Item(new, metadata=dict(node.metadata)), parents)
        self._carry_extras(old, new)
        for child in children:
            self.add_edge(self.nodes[new], self.nodes[child])
        respelled = {}
        for term in sorted(naming, key=lambda n: (n.count("("), n)):
            if term not in self.nodes:
                continue
            head, param = _dims.split_term(term)
            parts = [respelled.get(c, new if c == old else c)
                     for c in _dims.constraints(param)]
            target = self._canonical_name(f"{head}({' '.join(sorted(parts))})")
            respelled[term] = target
            if target != term:
                self._refile(self.nodes[term], target)
        self._contract_node(old, {old})
        return respelled

    def _check_role_reference_stays(self, name, parent_names):
        """A move must leave a role-named node inside its dimension. A
        replay files names before their places (G9, case 2): a total one
        keeps what it is given, and `ingest` checks its stream once it is
        all in (`_check_role_parameters`)."""
        if getattr(self, "_role_lenient", 0):
            return
        terms = self._role_terms_naming(name)
        if not terms:
            return
        node = self.nodes.get(name)      # None while being created
        for term in terms:
            base = self._dimension_of(_dims.split_term(term.name)[0])[1]
            base_node = self.nodes.get(base)
            still = False
            for parent in parent_names:
                if parent == base:
                    still = True
                elif parent not in self.nodes:
                    # A value about to be materialized: in the dimension
                    # iff its head is.
                    parsed = self._parse_parametric(parent)
                    still = parsed is not None and \
                        self._dimension_of(parsed[0])[1] == base
                elif base_node is not None and self._has_ancestors(
                        self.nodes[parent], (base_node,), computed=False):
                    still = True
                if still:
                    break
            if not still and node is not None and any(
                    self._dimension_of(
                        self._parse_parametric(v.name)[0])[1] == base
                    for v in self._values_below(node)):
                still = True
            if not still:
                raise ValueError(
                    f"{name} is named by {term.name} and would sit outside "
                    f"the {base!r} dimension — a role parameter must name a "
                    f"category in its dimension; file {name} under {base!r} "
                    f"(or retract the term) first (DIMENSIONS.md §14)")

    def _live_parent_names(self, name):
        """Names of a node's own parents (empty for a name not in the graph)."""
        node = self.nodes.get(name)
        if node is None:
            return []
        return [parent.name for parent in node.parents
                if self.nodes.get(parent.name) is parent]

    def _fold_same_head_values(self, sub_name, super_names, live=()):
        """Canonical placement (DIMENSIONS.md §9): an item that would sit
        under several VALUE terms of one head is filed under their meet
        instead — `weight(1kg..3kg)` and `weight(2kg..5kg)` become
        `weight(2kg..3kg)` — because an item sits in the intersection of
        its parents and that intersection has a name. One denotation, one
        stored form, and every query path sees the item where it is: before
        this (until 0.26.1) the planner met two same-head query terms into
        one virtual term whose cone held neither parent, so `get([A, B])`
        silently missed an item filed under both. Parents the item already
        has (`live`) fold in too, and the reduction pass prunes their edges
        once the meet's edge exists. Role terms naming nodes have no
        nameable meet and stay as they are (the graph orders them); a
        provably empty meet is the disjoint-parents refusal (a total replay
        keeps such values unfolded, as the merge that made them did). Terms
        of a transitive or enclosing head have no meet either — Zermatt is in
        Switzerland and in the Alps, a photo about Mars and about Earth — so
        they stay as they are too, and reduction keeps the finer of two
        that are ordered (DIMENSIONS.md §16, §17). Terms of the graph kind
        are filed as their parts instead (`_graph_parts`): their meet is a
        compound, whose spelling would follow the graph, so they stay apart
        and reduction keeps the finer ones (§15). Returns the super names
        to file under."""
        by_head = {}
        for name in [*super_names, *live]:
            parsed = self._parse_parametric(name)
            if parsed is None or parsed[1] in _dims.MULTI_VALUED \
                    or parsed[1] == _dims.KIND_GRAPH \
                    or self._param_node(
                        parsed[0], _dims.split_term(name)[1]) is not None:
                continue
            by_head.setdefault(parsed[0], (parsed[1], []))[1].append(name)
        folded = {}
        for head, (kind, names) in by_head.items():
            distinct = list(dict.fromkeys(names))
            if len(distinct) < 2:
                continue
            meet = distinct[0]
            for other in distinct[1:]:
                met = self._intersect(meet, other, kind)
                if met is None:
                    if self._total():
                        break      # kept as a merge keeps it, unfolded
                    raise ValueError(
                        f"{sub_name} cannot sit under both {meet} "
                        f"and {other}: provably disjoint {head!r} terms — "
                        "an item is in the intersection of its parents; for "
                        "a union, use a region node (DIMENSIONS.md §9)")
                meet = met
            else:
                for name in distinct:
                    folded[name] = meet
        out = []
        for name in [*super_names, *live]:
            target = folded.get(name)
            if name in super_names or target is not None:
                if (target or name) not in out:
                    out.append(target or name)
        return out

    def _check_parametric_placement(self, sub_name, super_names, also=()):
        """Refuse a placement the dimension arithmetic can prove wrong.

        Shared by `put` and `reclassify`, because a placement that `put`
        refuses must not be reachable by moving instead. `also` names parents
        the item would *keep* — its existing ones for `put`, the survivors of a
        retraction for `reclassify` — since the guard is about the parent set
        the item ends up with, not about one edge.
        """
        sub_parsed = self._parse_parametric(sub_name)
        # A graph-ordered term goes only under its head (CONTRACT.md §5.1):
        # asked before anything is materialized. One already below the
        # parent is a no-op, as add_edge makes it.
        if sub_parsed is not None and sub_parsed[1] in _dims.GRAPH_ORDERED \
                and not self._total():
            for name in super_names:
                if name != sub_parsed[0] and not (
                        sub_name in self.nodes and self.is_below(sub_name, name)):
                    self._refuse_rule(sub_name, sub_parsed[0], name)
        # Nothing may end up inside itself under a transitive head (§16);
        # asked here, before put or reclassify materializes anything.
        for name in super_names:
            self._refuse_self_containment(name, sub_name)
        parametric_supers = {}  # head -> [(canonical name, kind), ...]
        for name in super_names:
            parsed = self._parse_parametric(name)
            if parsed is not None:
                parametric_supers.setdefault(parsed[0], []).append(
                    (name, parsed[1]))

        # Within a dimension the order is computed, full stop: a value under
        # a same-head term would assert it (add_edge also refuses, but this
        # raises before any node is created).
        if sub_parsed is not None and sub_parsed[0] in parametric_supers:
            raise ValueError(
                f"within dimension {sub_parsed[0]!r} the order is computed: "
                f"refusing {sub_name} under "
                f"{parametric_supers[sub_parsed[0]][0][0]}")

        # The disjoint-parents guard (DIMENSIONS.md §9): an item sits in the
        # INTERSECTION of its parents, so provably disjoint same-dimension
        # parents assert membership of an empty concept — the
        # union-vs-intersection footgun, caught exactly. Parents it keeps
        # participate too.
        for name in also:
            parsed = self._parse_parametric(name)
            if parsed is not None and parsed[0] in parametric_supers:
                parametric_supers[parsed[0]].append((name, parsed[1]))
        for head, entries in parametric_supers.items():
            if self._total():
                break          # a merge keeps it, and so does its replay
            for (name_a, kind), (name_b, _) in combinations(entries, 2):
                if self._param_node(head, _dims.split_term(name_a)[1]) \
                        is not None or self._param_node(
                            head, _dims.split_term(name_b)[1]) is not None:
                    continue   # named places: the graph proves no disjointness
                if self._intersect(name_a, name_b, kind) is None:
                    raise ValueError(
                        f"{sub_name} cannot sit under both {name_a} "
                        f"and {name_b}: provably disjoint {head!r} terms — "
                        "an item is in the intersection of its parents; for "
                        "a union, use a region node (DIMENSIONS.md §9)")

    def put(self, subcategory, super_categories, optimized=False):
        # Names are the identity at the public boundary: plain strings are
        # accepted anywhere an Item is (see "Identity" in CLAUDE.md), and
        # parametric sugar resolves to the canonical name before anything
        # else looks at it (weight(3000g) -> weight(3kg), §7).
        if isinstance(subcategory, str):
            subcategory = Item(subcategory)
        parts = self._graph_parts(subcategory.name)
        if len(parts) > 1:
            # A compound graph-kind term is stored as its parts (§15).
            for part in parts:
                self.put(Item(part, metadata=dict(subcategory.metadata)),
                         super_categories, optimized=optimized)
            return
        sub_parsed = self._parse_parametric(subcategory.name)
        if sub_parsed is not None and subcategory.name != sub_parsed[2]:
            subcategory = Item(sub_parsed[2], metadata=subcategory.metadata)
        # A graph-kind parent with several constraints is filed as its
        # parts, unreduced, so every part it names is materialized in every
        # order; reduction then keeps the finer ones (§15).
        super_names = []
        for sc in super_categories:
            for name in self._graph_parts(_name_of(sc)):
                name = self._canonical_name(name)
                if name not in super_names:
                    super_names.append(name)

        self._check_parametric_placement(
            subcategory.name, super_names,
            also=self._live_parent_names(subcategory.name))
        if subcategory.name not in self.nodes:
            # A role term may already spell this name as a LITERAL value
            # (`from(my_home)` filed before the place existed). Creating the
            # category turns the parameter into a node — fine inside the
            # dimension (the reduction pass below follows), refused outside
            # it, where the term would otherwise turn loud on every read.
            self._check_role_reference_stays(subcategory.name, super_names)

        # Materialize parametric super-categories on first use, anchored
        # under their head (declare-the-dimension-first is enforced by the
        # existence check below: with an undeclared head the name stays
        # opaque and must exist like any other category).
        for name in super_names:
            if name not in self.nodes:
                parsed = self._parse_parametric(name)
                if parsed is not None:
                    self._ensure_parametric_node(name, parsed[0], parsed[1])
                else:
                    self._ensure_family_node(name)

        if any(name not in self.nodes for name in super_names):
            raise ValueError("One or more super-categories do not exist.")
        # Canonical placement (DIMENSIONS.md §9): several values of one head
        # fold to their meet — after the named values are materialized, so
        # stored form does not depend on the order of puts (a value once
        # named stays, whether or not an edge to it survives).
        super_names = self._fold_same_head_values(
            subcategory.name, super_names, self._live_parent_names(subcategory.name))
        for name in super_names:
            if name not in self.nodes:
                parsed = self._parse_parametric(name)
                self._ensure_parametric_node(name, parsed[0], parsed[1])
        if subcategory.name == self.root.name and self.root.name in self.nodes:
            raise ValueError("Already exists as root.")

        if subcategory.name in self.nodes:
            existing = self.nodes[subcategory.name]
            # A re-put asserts the incoming metadata: its keys win.
            if subcategory is not existing and subcategory.metadata:
                existing.metadata.update(subcategory.metadata)
            subcategory = existing
        elif sub_parsed is not None:
            node = self._ensure_parametric_node(
                subcategory.name, sub_parsed[0], sub_parsed[1])
            if subcategory.metadata:
                node.metadata.update(subcategory.metadata)
            subcategory = node
        else:
            self.add_node(subcategory)

        super_categories = [self.nodes[name] for name in super_names]

        if not super_categories:
            super_categories = [self.root]

        if optimized:
            def element_set(dag, items):
                elements = set()
                for node in items:
                    ancestors = dag.get_ancestors(node, {dag.root})
                    elements.update(ancestors)
                return elements

            def extended_set(dag, nodes):
                extended_set = nodes.copy()
                for node in nodes:
                    down_set = dag.get_descendants(node)
                    for descendant in down_set:
                        if all(ancestor in extended_set for ancestor in dag.get_ancestors(descendant, {dag.root})):
                            extended_set.add(descendant)
                return extended_set

            def bottom_set(nodes):
                filtered = [node for node in DAG(nodes).topological_sort() if node in nodes]

                def has_no_neighbors(node):
                    return len(node.neighbors) == 0

                return list(filter(has_no_neighbors, filtered))

            elements = element_set(self, super_categories)
            extended = extended_set(self, elements)
            bottom = bottom_set(extended)
            super_categories = bottom

        for super_cat in super_categories:
            self.add_edge(super_cat, subcategory)

    def remove(self, node_to_remove, with_terms=False):
        """Remove a category by contraction: it goes, and its children
        reattach to its parents, so nothing below it is lost. Refused while
        a term names it, unless `with_terms` (see `remove_many`)."""
        # Accept a name string or any Item, and resolve to this instance's
        # node: a fresh Item("X") has empty parents/neighbors, so operating
        # on the caller's object instead of ours would orphan X's children
        # and corrupt the graph. Parametric sugar canonicalizes first.
        return self.remove_many([node_to_remove], with_terms=with_terms)

    def _contract_node(self, name, gone=()):
        """`remove`'s contraction of one node, its guard already passed."""
        self._refuse_if_named(name, gone)
        node_to_remove = self.nodes[name]

        super_categories = {parent for parent in node_to_remove.parents
                            if self.nodes.get(parent.name) is parent}
        subcategories = set(node_to_remove.neighbors)
        # Contraction follows the COMBINED order (DIMENSIONS.md §5): the
        # children of a removed parametric node reattach to the present
        # containing terms as well, restoring exactly what reduction-modulo-
        # computed pruned. (A once-asserted parcel -> weight(..5kg) edge,
        # pruned when parcel -> weight(3kg) arrived, comes back when the
        # point is removed.) Captured before the graph moves.
        computed_containers = list(self._computed_parents(node_to_remove))

        # The whole operation costs exactly one subtraction per ancestor:
        # contraction reconnects the removed node's children to its parents,
        # so nothing *below* it becomes unreachable — every ancestor loses
        # precisely `node_to_remove` itself. Captured before the graph moves.
        affected = set()
        self._get_affected_nodes(node_to_remove, affected)
        ancestors = affected - {node_to_remove}

        with self._counts_unchanged():
            # Remove edges pointing from the removed node
            for subcategory in subcategories:
                self.remove_edge(node_to_remove, subcategory)

            # Remove edges pointing to the removed node
            for super_category in super_categories:
                self.remove_edge(super_category, node_to_remove)

            self._forget(node_to_remove.name)
            del node_to_remove

            # Add edges from all super-categories of the removed node to all its subcategories
            for super_category in super_categories:
                # If the node has any super-category other than the root, an edge from the root is not needed
                if super_category is self.root and any(super_cat != self.root for super_cat in super_categories):
                    continue
                for subcategory in subcategories:
                    self.add_edge(super_category, subcategory)

        for ancestor in ancestors:
            ancestor.descendant_count -= 1

        # Live adds, after the bookkeeping above: reattaching to a computed
        # container genuinely changes ASSERTED reachability (the container
        # gains an asserted cone), so these run with normal count planning;
        # add_edge's combined-order checks drop any that are already implied
        # and prune the asserted-contraction edges they make redundant.
        for container in computed_containers:
            for subcategory in subcategories:
                self.add_edge(container, subcategory)

    def reclassify(self, names, to=(), from_=None):
        """Move items: assert the new classifications, retract the old ones.

        The retracting counterpart of `put`, and the operation a lifecycle needs
        (`active` -> `archive`). `put` only ever adds a parent, and `remove`
        deletes the item itself, so without this the only way to reclassify is
        remove-then-put, which loses everything filed *under* the item: its
        children reattach to the old parent and stay there.

        * `to` — the categories it should be under now.
        * `from_` — which classifications to retract. `None` means *all* of its
          current ones, so `reclassify(["X"], to=["archive"])` reads as "X is
          archived, and nothing else". Naming them makes it surgical.
        * `to=()` with `from_` given is a pure retraction (an unfiling).

        Order is not an implementation detail: **assert before retract**, so a
        cycle or an unknown name leaves the store untouched — and because
        adding the new parent can make the old edge *redundant*, which prunes it
        for us. An edge that is already gone by the time we retract it counts as
        retracted; treating that as an error would fail on the legitimate case
        of moving something to a finer category under the same parent.

        Nothing is ever orphaned: an item left with no parent becomes top-level
        under `*`, exactly as `put(name, [])` would file it. Reachability from
        the root is what makes an item visible at all.

        What the DAG will NOT do is decide a contested state for you. Moving `A`
        to `archive` moves everything below it — but a child that also hangs
        under a still-active `B` ends up *both* archived and active, because
        subsumption inherits and exclusive status cannot. That is a true
        statement about a shared item, and `get([old, new])` lists exactly those
        items (the CLI reports them). Nothing here enforces exclusivity;
        nothing in the core can.

        Returns the set of retracted `(parent, item)` name pairs.
        """
        items = []
        for name in names:
            name = self._canonical_name(_name_of(name))
            if name == self.root.name:
                raise ValueError("Cannot reclassify the root.")
            if name not in self.nodes:
                raise ValueError(f"Item {name} does not exist.")
            items.append(name)

        destinations, pending = [], []
        # A compound graph-kind destination is its parts, as under `put`.
        to = [part for name in to for part in self._graph_parts(_name_of(name))]
        for name in to:
            name = self._canonical_name(_name_of(name))
            if name in destinations:
                continue
            if name not in self.nodes:
                # A typed value materializes on first use here exactly as it
                # does under `put`, anchored beneath its head — otherwise
                # `move X --to 'weight(10kg)'` would be impossible until
                # something else had been filed there. An opaque name (no
                # declared dimension) must exist, like any other category.
                # Deferred until validation has passed: a refused move must not
                # leave new vocabulary behind, which `put` also avoids by
                # checking first.
                parsed = self._parse_parametric(name)
                if parsed is None:
                    found = _dims.kind_node(name)
                    if found is None or found[1] is None \
                            or found[0] not in self.nodes:
                        raise ValueError(f"Category {name} does not exist.")
                    pending.append((name, None, None))   # a family pin
                else:
                    pending.append((name, parsed[0], parsed[1]))
            destinations.append(name)

        # Everything is validated against the pre-move graph before a single
        # edge moves, so a refusal never leaves half a move behind.
        retract, targets = {}, {}
        for item in items:
            if from_ is None:
                retract[item] = [name for name in self._live_parent_names(item)
                                 if name != self.root.name
                                 and name not in destinations]
            else:
                wanted = []
                for name in from_:
                    parts = self._graph_parts(_name_of(name))
                    if len(parts) > 1:
                        # A compound graph-kind term was filed as its parts:
                        # retracting it retracts the parts filed directly
                        # (a part reduction dropped is implied by those).
                        direct = [p for p in parts if p in self.nodes and
                                  self.nodes[item] in self.nodes[p].neighbors]
                        if not direct:
                            raise ValueError(
                                f"{item} is not filed under "
                                f"{self._canonical_name(_name_of(name))}.")
                        wanted.extend(p for p in direct if p not in wanted)
                        continue
                    name = self._canonical_name(_name_of(name))
                    if name not in self.nodes:
                        raise ValueError(f"Category {name} does not exist.")
                    if self.nodes[item] not in self.nodes[name].neighbors:
                        if self.is_below(item, name):
                            raise ValueError(
                                f"{item} is not filed directly under {name}: it "
                                f"is below it through "
                                f"{', '.join(sorted(self._live_parent_names(item)))}"
                                f" — reclassify that instead")
                        raise ValueError(f"{item} is not under {name}.")
                    wanted.append(name)
                retract[item] = wanted

            for destination in destinations:
                if self.is_below(destination, item):     # reflexive: catches self
                    raise ValueError(
                        f"Edge {destination} -> {item} would create a cycle.")
            keeping = [name for name in self._live_parent_names(item)
                       if name not in retract[item] and name != self.root.name]
            targets[item] = self._fold_same_head_values(item, destinations, keeping)
            self._check_parametric_placement(item, targets[item], also=keeping)
            self._check_role_reference_stays(item, targets[item] + keeping)

        for name, head, kind in pending:
            if head is None:
                self._ensure_family_node(name)
            else:
                self._ensure_parametric_node(name, head, kind)

        for item in items:
            for destination in targets[item]:
                if destination not in self.nodes:      # a meet the fold named
                    parsed = self._parse_parametric(destination)
                    self._ensure_parametric_node(destination, parsed[0], parsed[1])
                self.add_edge(self.nodes[destination], self.nodes[item])

        retracted = set()
        for item, olds in retract.items():
            for old in olds:
                # Already gone means the new parent implied it — see above.
                if self.nodes[item] in self.nodes[old].neighbors:
                    self.remove_edge(self.nodes[old], self.nodes[item])
                    retracted.add((old, item))

        # A destination above an old parent was skipped as redundant when it
        # was asserted (`x ⊑ b ⊑ a`, moving x from b to a), and the
        # retraction just took away the path that implied it. Assert it again,
        # or the item would end up under nothing it was moved to.
        for item in items:
            for destination in targets[item]:
                if not self.is_below(item, destination):
                    self.add_edge(self.nodes[destination], self.nodes[item])

        for item in items:
            if not self._live_parent_names(item):
                self.add_edge(self.root, self.nodes[item])

        return retracted

    def _resolve_for_removal(self, names):
        """Canonical names of removable nodes, or raise before anything moves."""
        resolved = []
        for name in names:
            name = self._canonical_name(_name_of(name))
            if name == self.root.name:
                raise ValueError("Cannot remove the root.")
            if name not in self.nodes:
                raise ValueError(f"Item {name} does not exist.")
            if name not in resolved:
                resolved.append(name)
        return resolved

    def cone_removal_plan(self, names):
        """What `remove_cone(names)` would touch: (in the cone, deleted).

        The survival rule is what makes cone deletion well defined in a
        multi-parent DAG: a member of the cone is deleted **iff the root can no
        longer reach it once the targets are gone**. So deleting `Japan` takes
        an item filed only under Japan, and leaves one that is also a Flight
        exactly where it still belongs. Everything in the cone that is not
        deleted is a node that hangs somewhere else too.

        The walk is over **asserted** edges only, deliberately. The computed
        order between parametric values is derived from names, so a coarse term
        would otherwise sweep in every finer value ever filed — a far larger
        claim than the one being made, and one no stored edge asserted. It also
        keeps this consistent with `descendant_count`, which is asserted-only.

        Pure: nothing is mutated, so a caller can show the plan first."""
        targets = self._resolve_for_removal(names)
        cone = set(targets)
        for name in targets:
            cone |= {node.name for node in
                     self.get_descendants(self.nodes[name], computed=False)}

        deleted = set(targets)
        changed = True
        while changed:                      # orphan collection == unreachability
            changed = False
            for name in sorted(cone - deleted):
                if not any(self.nodes.get(parent.name) is parent
                           and parent.name not in deleted
                           for parent in self.nodes[name].parents):
                    deleted.add(name)
                    changed = True
        return cone, deleted

    def cone_terms_plan(self, names, with_terms=False):
        """The terms a cone deletion has to contract: {term: the terms what is
        under it moves to}, for every term naming a node the deletion takes
        (and every term naming such a term). Raises, as the deletion would,
        when there are any and `with_terms` is not set."""
        _cone, deleted = self.cone_removal_plan(names)
        gone = set(deleted)
        frontier = sorted(deleted)
        while frontier:
            name = frontier.pop()
            naming = [term for term in self._namers(name) if term not in gone]
            if naming and not with_terms:
                self._refuse_if_named(name, gone)
            for term in naming:
                gone.add(term)
                frontier.append(term)
        memo = {}
        return {term: self._replacements(term, gone, memo)
                for term in sorted(gone - set(deleted))}

    def remove_cone(self, names, with_terms=False):
        """Delete these categories and whatever only existed underneath them.

        The *other* removal: `remove` CONTRACTS (the node goes, its children
        reattach to its parents, nothing below it is lost), this DELETES. Both
        are needed and they are not variants of one operation — looping
        `remove` over a cone would destroy multi-parent members too, because
        contracting a leaf just drops it.

        Surviving children are **detached, never contracted**. Contraction here
        would invent claims: if `Japan` hung under `Asia`, reattaching a
        surviving `JAL` to Japan's parents would file it as `Asia` — something
        no one asserted and the deletion certainly did not imply.

        Returns the set of deleted names. Removal is not a merge operation
        (it is lossy and does not commute with a concurrent addition), so
        this is a local edit like `remove`; take an `excerpt --context` of the
        cone first if you want it back — merging that restores the exact root.
        """
        moves = self.cone_terms_plan(names, with_terms)
        cone, deleted = self.cone_removal_plan(names)
        # Terms naming what goes (asked for with `with_terms`) are contracted
        # first, as `remove` contracts them; then the cone is deleted.
        for term, targets in moves.items():
            parts = [part for target in targets
                     for part in self._graph_parts(target)]
            for child in sorted(self.nodes[term].neighbors, key=lambda n: n.name):
                keeping = [n for n in self._live_parent_names(child.name)
                           if n not in deleted and n not in moves
                           and n != self.root.name]
                self._check_parametric_placement(child.name, parts, also=keeping)
        for term in sorted(moves, key=lambda n: (-n.count("("), n)):
            if term in self.nodes:
                self._contract_term(term, moves[term])
        cone, deleted = self.cone_removal_plan(names)
        for name in sorted(deleted):
            self._refuse_if_named(name, gone=deleted)

        # Whose counts can move: the asserted ancestors of everything going.
        # Captured before the graph moves, recomputed after it — because the
        # per-ancestor *delta* that `remove` and `add_edge` use does NOT
        # generalize to deletion. Contraction preserves everything below the
        # removed node, so each ancestor loses exactly one item; deletion can
        # also strand a SURVIVING subtree, when an ancestor reached it only
        # through a node that is going. (Measured: assuming -1 per deleted node
        # left 22 of 25 random cases with wrong counts.) An exact delta needs
        # per-ancestor reachability, which is the recomputation anyway.
        affected = set()
        for name in deleted:
            affected |= {node for node
                         in self.get_ancestors(self.nodes[name], computed=False)
                         if node.name not in deleted}

        with self._counts_unchanged():
            for name in sorted(deleted):
                node = self.nodes[name]
                # Edges to children: removed here whether the child is doomed
                # or surviving — a surviving child cannot be orphaned by this,
                # since a node whose every parent is doomed is doomed itself.
                for child in list(node.neighbors):
                    self.remove_edge(node, child)
                # Edges from live parents; a doomed parent's edge is removed by
                # its own pass above, so this never double-removes.
                for parent in list(node.parents):
                    if (self.nodes.get(parent.name) is parent
                            and parent.name not in deleted):
                        self.remove_edge(parent, node)

        for name in deleted:
            self._forget(name)

        # The root is the one ancestor whose delta IS exact: the survival rule
        # is *defined* by reachability from the root, so the root loses exactly
        # the deleted nodes and nothing else can be stranded from it. That
        # matters twice — its cone is the whole graph, and on a partially
        # resident writer `len(self.nodes)` would be the resident count, not
        # the graph's (which is what made a sparse `remove_cone` commit a
        # different root from the eager one).
        for node in affected:
            if node is self.root:
                node.descendant_count -= len(deleted)
            else:
                node.descendant_count = len(
                    self.get_descendants(node, computed=False))

        return deleted

    def merge(self, other_dag):
        """Merge another OntoDAG into this one.

        Args:
            other_dag (OntoDAG): The DAG to merge into this one.
        """
        if not isinstance(other_dag, OntoDAG):
            raise ValueError("Can only merge with another OntoDAG instance.")

        # Pass 1: add all missing nodes (no edges yet). Metadata merges
        # per key with ours winning on conflict (same policy as the
        # payload/meta carry-over in EagerOntoDAG.merge).
        for node_name, other_node in other_dag.nodes.items():
            if node_name not in self.nodes:
                self.add_node(Item(node_name, metadata=other_node.metadata))
            else:
                for key, value in other_node.metadata.items():
                    self.nodes[node_name].metadata.setdefault(key, value)

        # Pass 2: add edges in topological order (general → specific) using
        # add_edge so _remove_unneeded_edges prunes redundant edges correctly.
        # Lenient about role parameters meanwhile: a place arrives here
        # before the edge that files it (DIMENSIONS.md §14).
        with self._lenient_roles():
            for other_node in other_dag.topological_sort():
                self_node = self.nodes[other_node.name]
                for neighbor in other_node.neighbors:
                    if neighbor.name in self.nodes:
                        self.add_edge(self_node, self.nodes[neighbor.name])

            self._remove_duplicate_root_edges()
        # A compound either side stored before the other learned a fact
        # relating its constraints takes its current spelling (§16–§18).
        self._respell_deferred(other_dag.nodes)

    def excerpt_names(self, queries, context=False):
        """The names an excerpt of `queries` covers.

        `queries` is DNF — a list of conjunctions whose answers union, the shape
        `get_any` takes (`[[]]` is the empty query, i.e. everything; `[]` is the
        empty union, i.e. nothing). With `context`, the *asserted* ancestors of
        every answer come too: the categories the answers hang from, which is
        what makes the result mergeable into another store and diffable against
        this one. Asserted only — the computed order between parametric values is
        derived from names, so a reader recomputes it, and pulling coarser values
        in would drag unrelated members of their dimension along. Declarations
        travel regardless, a head like `weight` being a real parent of its
        values."""
        answer = (self.get(queries[0]) if len(queries) == 1
                  else self.get_any(queries))
        names = {item.name for item in answer}
        if context:
            for item in answer:
                names |= {node.name for node
                          in self.get_ancestors(item, computed=False)}
        names.discard(self.root.name)
        return names

    def excerpt(self, queries, context=False):
        """A query's answer as a standalone DAG — the materialized cut.

        `intersection_dag` is the live *view*; this is the *excerpt*. The edges
        among the answers are kept (cones are downward-closed under
        intersection, so the answer carries its own shape), and an answer with
        no parent inside the cut hangs under `*`, so the result is a well-formed
        OntoDAG that `merge`/`import` can take.

        Query terms are NOT added as nodes. That is the difference from
        `ontodag.viz.query_picture`, which may invent one to *draw* a
        constraint: a picture is discarded, while an excerpt gets imported back,
        and filing the question as though it were an answer would be a lie.
        Pass `context=True` when sending it somewhere — see `excerpt_names`."""
        cut = self.induced_subdag(self.excerpt_names(queries, context=context))
        for name in sorted(cut.nodes):
            node = cut.nodes[name]
            if node is not cut.root and not node.parents:
                cut.add_edge(cut.root, node)
        return cut

    def contested(self, first, second):
        """Items below BOTH categories — the two-states-at-once question.

        Empty when one entails the other, which is refinement rather than
        tension: everything under `recent` is under `active` by construction and
        reporting that would cry wolf. What is left is the real list — the
        shared items a reclassification left in two states, which subsumption
        cannot resolve for you (it inherits; exclusive status does not)."""
        if self.is_below(first, second) or self.is_below(second, first):
            return set()
        return {item.name for item in self.get([first, second])}

    def induced_subdag(self, names):
        """The subgraph induced on `names`: fresh nodes, the real edges among them.

        The third member of the derived-DAG family, and the most literal:
        `intersection_dag` intersects two DAGs, `copy_subdag` closes
        *downward* over descendants, and this copies exactly the set it is
        given. The caller chose the set, so nothing is added to it — which is
        what makes it usable for cuts whose boundary matters (`odag excerpt`)
        and for scoping a comparison (`odag diff`).

        Edges from the root are kept where a kept node's parent is this DAG's
        root, so an ancestor-closed set arrives already hanging from `*`.
        A node whose parents were all left out arrives parentless: that is
        information, not a defect, and what it means is the caller's business
        (an excerpt hangs such nodes under `*`; a diff never materializes them).

        The result is reduced whenever this DAG is, because deleting nodes can
        only remove paths, and an edge with no bypass keeps having none.
        Unknown names are ignored — a caller computing a name set from queries
        and closures should not have to filter it first. Never aliases (I4).
        """
        new_dag = OntoDAG()
        kept = {name for name in names if name in self.nodes}
        kept.discard(self.root.name)

        mapping = {}
        for name in sorted(kept):                     # sorted: deterministic
            node = self.nodes[name]
            copy_item = Item(name, metadata=node.metadata)
            mapping[name] = copy_item
            new_dag.add_node(copy_item)

        for name, copy_item in mapping.items():
            for parent in self.nodes[name].parents:
                if self.nodes.get(parent.name) is not parent:
                    continue                          # not ours (see get_ancestors)
                if parent.name == self.root.name:
                    new_dag.root.neighbors.add(copy_item)
                elif parent.name in mapping:
                    mapping[parent.name].neighbors.add(copy_item)

        for copy_item in new_dag.nodes.values():
            copy_item.descendant_count = len(
                new_dag.get_descendants(copy_item, computed=False))

        return new_dag

    def copy_subdag(self, nodes_to_copy):
        new_dag = OntoDAG()
        root_to_copy = None

        # Collect all nodes to copy, including descendants
        all_nodes_to_copy = set()
        for node in nodes_to_copy:
            if node.name == new_dag.root.name:
                root_to_copy = node
                continue
            original_node = self.nodes[node.name]
            all_nodes_to_copy.add(original_node)
            all_nodes_to_copy.update(self.get_descendants(original_node))

        mapping = {}

        # Create new items for all relevant nodes
        for node in all_nodes_to_copy:
            copy_item = Item(node.name, metadata=node.metadata)
            mapping[node] = copy_item
            new_dag.add_node(copy_item)

        # Preserve edges among copied nodes
        for original_node, copy_item in mapping.items():
            for neighbor in original_node.neighbors:
                if neighbor in mapping:
                    copy_item.neighbors.add(mapping[neighbor])
        # Set edges from the root
        if root_to_copy is not None:
            for root_neighbor in root_to_copy.neighbors:
                new_dag.root.neighbors.add(mapping[root_neighbor])

        # Recalculate descendant counts (asserted-only, like all counts)
        for copy_item in new_dag.nodes.values():
            copy_item.descendant_count = len(
                new_dag.get_descendants(copy_item, computed=False))

        return new_dag

    def deepcopy(self):
        new_dag = OntoDAG()
        mapping = {}

        # Create new items
        for original_item in self.nodes.values():
            copy_item = Item(original_item.name, metadata=original_item.metadata)
            mapping[original_item] = copy_item
            new_dag.add_node(copy_item)

        # Connect neighbors
        for original_item, copy_item in mapping.items():
            for neighbor in original_item.neighbors:
                copy_item.neighbors.add(mapping[neighbor])

        # Update the root reference
        new_dag.root = mapping[self.root]

        # Recalculate descendant counts (asserted-only, like all counts)
        for node in new_dag.nodes.values():
            node.descendant_count = len(
                new_dag.get_descendants(node, computed=False))

        return new_dag


def __getattr__(name):
    """`OntoDAGVisualizer` moved to `ontodag.viz` (2026-08-02): rendering is
    an optional consumer of a DAG, not part of one, and keeping it here made
    `dag.py` carry a dependency the core never needs. The old import path
    still works — this forwards it — but new code should use
    `from ontodag.viz import OntoDAGVisualizer`, or `ontodag.OntoDAGVisualizer`."""
    if name == "OntoDAGVisualizer":
        from ontodag.viz import OntoDAGVisualizer

        return OntoDAGVisualizer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
