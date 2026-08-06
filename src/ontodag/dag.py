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
        return self.name == other.name

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


def _name_of(node_or_name):
    """Identity at the public boundary is the name: accept a plain string or
    anything with a `.name` (an Item), and return the name string."""
    return node_or_name if isinstance(node_or_name, str) else node_or_name.name


class DAG:
    def __init__(self, nodes=None):
        self.nodes = {}
        self._counts_frozen = False  # True while an operation maintains counts itself
        if nodes:
            for node in nodes:
                self.add_node(node)

    def add_node(self, node):
        """Add a node (Item) to the graph."""
        self.nodes[node.name] = node

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

    def add_edge(self, from_node, to_node):
        """Add a directed edge between two nodes."""
        if from_node.name not in self.nodes or to_node.name not in self.nodes:
            raise ValueError("Both nodes must exist in the graph.")

        if from_node == to_node:
            return
        if to_node in from_node.neighbors:
            return
        if self._is_reachable(to_node, from_node):
            raise ValueError(
                f"Edge {from_node.name} -> {to_node.name} would create a cycle."
            )

        deltas = None if self._counts_frozen else self._plan_add(from_node, to_node)
        from_node.neighbors.add(to_node)
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
            if computed:
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
            if computed:
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
            if computed:
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


class OntoDAG(DAG):
    def __init__(self):
        super().__init__()
        self.root = Item("*")
        self.nodes[self.root.name] = self.root

    # ---- parametric dimensions (docs/DIMENSIONS.md) -------------------------
    #
    # A dimension head is an ordinary node asserted under a registry kind node
    # (weight -> linear-dimension); its used values are parametric nodes
    # (weight(3kg)) anchored under it by a schema edge — the "star".
    # The order *within* a dimension is computed from the names and never
    # materialized as edges (dense orders have no transitive reduction).

    def _dimension_kind(self, head_name):
        """The registry kind a declared dimension head inherits (ancestor
        walk from the head to a kind node), or None. Inheriting two
        different kinds is an error, not an MRO puzzle (DIMENSIONS.md §3).
        The walk stops at kind nodes, so kind nodes themselves and plain
        categories resolve to None."""
        node = self.nodes.get(head_name)
        if node is None or head_name in _dims.KINDS:
            return None
        kinds = set()
        seen = set()
        stack = [node]
        while stack:
            for parent in stack.pop().parents:
                if self.nodes.get(parent.name) is not parent:
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
        return split[0], kind, _dims.canonicalize(
            name, kind, units=self._declared_units())

    def _canonical_name(self, name):
        parsed = self._parse_parametric(name)
        return parsed[2] if parsed else name

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

    def _computed_children(self, node):
        """Present same-head terms contained in `node`'s denotation — the
        computed hops of the combined order. Distinct canonical names are
        never mutually contained (equal denotation ⇒ equal name), so this
        relation is a strict partial order on present nodes (I1)."""
        parsed = self._parse_parametric(node.name)
        if parsed is None:
            return
        head, kind, canonical = parsed
        for sibling, _ in self._star(head):
            if sibling is not node and _dims.contains(
                    canonical, sibling.name, kind,
                    units=self._declared_units()):
                yield sibling

    def _computed_parents(self, node):
        parsed = self._parse_parametric(node.name)
        if parsed is None:
            return
        head, kind, canonical = parsed
        for sibling, _ in self._star(head):
            if sibling is not node and _dims.contains(
                    sibling.name, canonical, kind,
                    units=self._declared_units()):
                yield sibling

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
        since overlap is only defined for computed denotations."""
        name = _name_of(term)
        parsed = self._parse_parametric(name)
        if parsed is None:
            raise ValueError(
                f"{name!r} is not a parametric term of a declared dimension"
                " — get_overlapping needs a computed denotation")
        head, kind, canonical = parsed
        result = set()
        for value, _ in self._star(head):
            if _dims.intersect(canonical, value.name, kind,
                               units=self._declared_units()) is not None:
                result.add(value)
                result |= self.get_descendants(value)
        return result

    def _virtual_cone(self, head, kind, canonical):
        """The cone of a parametric term that need not exist as a node: the
        present values of its dimension contained in its denotation, plus
        everything below them. Queries quantify over present nodes only —
        this is why "all integers" can never be an answer, and why a
        read-only client can ask any threshold without writing
        (DIMENSIONS.md §8)."""
        cone = set()
        for value, _ in self._star(head):
            if _dims.contains(canonical, value.name, kind,
                              units=self._declared_units()):
                cone.add(value)
                cone |= self.get_descendants(value)
        return cone

    def _ensure_parametric_node(self, canonical, head, kind):
        """Materialize a used value: one node, one anchor edge under its
        head. Every value of one head must share one value space (one unit
        family, one arity) — checked against the star, which keeps the
        property inductively."""
        node = self.nodes.get(canonical)
        if node is not None:
            return node
        space = _dims.space_of(canonical, kind,
                               units=self._declared_units())
        for sibling, _ in self._star(head):
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
        # Skip the edge entirely if to_node is already reachable in the
        # combined (asserted + computed) order — adding it would violate
        # transitive reduction (and made results depend on the order of
        # super-categories in put). Anchor edges are schema and always kept.
        # Both this and the cycle check below are asked UPWARD (is X among
        # Y's ancestors?): ancestor cones are shallow where descendant cones
        # can be most of the graph — the same direction rule the query
        # planner follows, and what keeps writes local for the
        # partially-resident writer.
        if not anchor and self._has_ancestors(to_node, (from_node,)):
            return
        # Reject cycles — through computed hops too — before anything mutates.
        if self._has_ancestors(from_node, (to_node,)):
            raise ValueError(
                f"Edge {from_node.name} -> {to_node.name} would create a cycle."
            )
        # Plan the delta against the pre-operation graph, add the edge, then
        # prune. Pruning runs with live counts: an edge that is redundant via
        # asserted paths removes nothing from asserted reachability (its
        # _plan_remove is zero), while an edge redundant only via *computed*
        # hops really does change asserted reachability — and persisted
        # counts are asserted-only by design (DIMENSIONS.md §5).
        deltas = None if self._counts_frozen else self._plan_add(from_node, to_node)
        with self._counts_unchanged():
            super().add_edge(from_node, to_node)              # structure only
        self._apply_count_deltas(deltas)
        self._remove_unneeded_edges(from_node, to_node)

    # Stand-in for the typical ancestor-cone size, which is not maintained
    # per node. Used only to choose between two *exact* operators in get(),
    # so a bad estimate costs time, never correctness. Deliberately biased
    # high (ancestor cones in category graphs are usually far smaller than
    # this) so the probe only fires when it is clearly the cheaper plan.
    _PROBE_COST_ESTIMATE = 16

    def get(self, super_categories):
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
        for super_category in super_categories:
            raw = _name_of(super_category)
            parsed = self._parse_parametric(raw)
            if parsed is not None:
                parametric[parsed[2]] = (parsed[0], parsed[1])
                continue
            node = self.nodes.get(raw)
            if node is None:
                return set()
            terms[node.name] = node
        if not terms and not parametric:
            # The EMPTY query is the universe, not an error: an intersection
            # of no cones is unconstrained, so everything qualifies. That is
            # the identity of the operation `get` performs — adding a term can
            # only ever narrow the answer, so removing every term must widen
            # it to the top — and it makes `get` total. Equivalently it is the
            # root's cone, so `get([])`, `get(["*"])` and the CLI's `list` are
            # one question with one answer.
            return self.get_descendants(self.root)

        # 1a. Same-head parametric terms pre-intersect EXACTLY — within a
        # dimension, meets are computable (interval intersection), so this
        # is result-preserving, and an empty meet is an empty result before
        # the graph is touched at all. (Contrast SEMANTIC_CODES.md §10:
        # asserted "meet-named" nodes must never be used this way.)
        if parametric:
            by_head = {}
            for name, (head, kind) in parametric.items():
                if head in by_head:
                    met = _dims.intersect(by_head[head][0], name, kind,
                                          units=self._declared_units())
                    if met is None:
                        return set()
                    by_head[head] = (met, kind)
                else:
                    by_head[head] = (name, kind)
            virtual = {}
            for head, (name, kind) in by_head.items():
                node = self.nodes.get(name)
                if node is not None:
                    terms[name] = node    # present: the planner handles it
                else:
                    virtual[name] = (head, kind)
            # 1b. Virtual cones intersect first (they are computed sets
            # anyway), then the surviving present terms settle by one upward
            # probe per candidate — every step result-preserving.
            if virtual:
                cones = sorted((self._virtual_cone(head, kind, name)
                                for name, (head, kind) in virtual.items()),
                               key=len)
                common = cones[0]
                for cone in cones[1:]:
                    if not common:
                        return set()
                    common &= cone
                if terms and common:
                    remaining = list(terms.values())
                    common = {candidate for candidate in common
                              if self._has_ancestors(candidate, remaining)}
                return common

        # 2. Drop terms subsumed by another term.
        nodes = list(terms.values())
        minimal = [
            node for node in nodes
            if not any(
                other is not node
                and node.descendant_count > other.descendant_count
                and self._has_ancestors(other, (node,))
                for other in nodes
            )
        ]

        # 3. Smallest cone first.
        minimal.sort(key=lambda node: (node.descendant_count, node.name))

        # Adaptive execution: walk or probe, decided per step from the now-
        # known size of the running result.
        common_subcategories = self.get_descendants(minimal[0])
        for index, node in enumerate(minimal[1:], start=1):
            if not common_subcategories:
                break
            remaining = minimal[index:]
            probe_cost = len(common_subcategories) * self._PROBE_COST_ESTIMATE
            if probe_cost < sum(term.descendant_count for term in remaining):
                # One upward walk per candidate settles every remaining term.
                # (Candidates can never equal query terms: a surviving term
                # is an ancestor of no other term, so no term lies inside the
                # first term's cone — strict ancestry is the right test.)
                return {candidate for candidate in common_subcategories
                        if self._has_ancestors(candidate, remaining)}
            common_subcategories &= self.get_descendants(node)
        return common_subcategories

    def get_any(self, queries):
        """Union of conjunctive queries — `get` in disjunctive normal form.

        Each element of `queries` is a collection of terms exactly as
        `get` takes them (names or Items, parametric sugar and virtual
        terms included); the result is everything matching AT LEAST ONE of
        the conjunctions:

            get_any([{"dog", "pet"}, {"cat"}])   # (dog AND pet) OR cat

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
            result |= self.get(terms)
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
                and sub_parsed[0] == sup_parsed[0] \
                and _dims.contains(sup, sub, sup_parsed[1],
                                   units=self._declared_units()):
            return True
        if sub_node is None:
            # A virtual subject relates upward only through the present
            # values that contain it.
            head, kind, _ = sub_parsed
            return any(
                _dims.contains(value.name, sub, kind,
                               units=self._declared_units())
                and self.is_below(value, sup)
                for value, _kind in self._star(head))
        if sup_node is None:
            # A virtual bound is met by any ancestor (or the subject
            # itself, handled by the arithmetic above) whose denotation
            # it contains. Streaming: each ancestor is tested AS the climb
            # reaches it, so the common case — the containing value is a
            # direct parent — answers in one hop instead of after
            # materializing the whole up-cone (which, on a lazy reader,
            # is the difference between a couple of fetches and all of
            # them).
            head, kind, _ = sup_parsed
            for ancestor in self._walk_ancestors(sub_node):
                parsed = self._parse_parametric(ancestor.name)
                if parsed is not None and parsed[0] == head \
                        and _dims.contains(sup, ancestor.name, kind,
                                           units=self._declared_units()):
                    return True
            return False
        return self._has_ancestors(sub_node, (sup_node,))

    def get_by_dag(self, query_dag):
        """
        Returns a new DAG with a new root, with the nodes that are intersected with the query nodes,
        including their common descendants.
        The highest level super-categories from the query DAG are added under the root, and their common descendants
        are added under the respective super-categories.
        """
        intersected_dag = self.intersection_dag(query_dag)
        intersected_dag_nodes = intersected_dag.nodes.values()

        copy_dag = self.copy_subdag(intersected_dag_nodes)
        copy_dag.prune_to_common_descendants(intersected_dag_nodes)
        return copy_dag

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
        ancestors = self.get_ancestors(from_node)  # combined order
        for ancestor in ancestors:
            if to_node in ancestor.neighbors \
                    and not self._is_anchor(ancestor, to_node):
                self.remove_edge(ancestor, to_node)
        # Downward twin. A fresh ordinary leaf has nothing below it — the
        # overwhelmingly common put(item, supers) case costs nothing. A
        # parametric to_node can reach siblings through computed hops even
        # with no asserted children, so it never takes the shortcut.
        if not to_node.neighbors \
                and self._parse_parametric(to_node.name) is None:
            return
        uppers = ancestors | {from_node}
        for descendant in self.get_descendants(to_node):  # combined order
            # Snapshot: remove_edge mutates the parent set mid-iteration.
            # _live_parents is the seam the partially-resident writer
            # overrides, so this walk stays fetch-on-touch there.
            for parent in list(self._live_parents(descendant)):
                if parent in uppers \
                        and not self._is_anchor(parent, descendant):
                    self.remove_edge(parent, descendant)

    def _live_parent_names(self, name):
        """Names of a node's own parents (empty for a name not in the graph)."""
        node = self.nodes.get(name)
        if node is None:
            return []
        return [parent.name for parent in node.parents
                if self.nodes.get(parent.name) is parent]

    def _check_parametric_placement(self, sub_name, super_names, also=()):
        """Refuse a placement the dimension arithmetic can prove wrong.

        Shared by `put` and `reclassify`, because a placement that `put`
        refuses must not be reachable by moving instead. `also` names parents
        the item would *keep* — its existing ones for `put`, the survivors of a
        retraction for `reclassify` — since the guard is about the parent set
        the item ends up with, not about one edge.
        """
        sub_parsed = self._parse_parametric(sub_name)
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
            for (name_a, kind), (name_b, _) in combinations(entries, 2):
                if _dims.intersect(name_a, name_b, kind,
                                   units=self._declared_units()) is None:
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
        sub_parsed = self._parse_parametric(subcategory.name)
        if sub_parsed is not None and subcategory.name != sub_parsed[2]:
            subcategory = Item(sub_parsed[2], metadata=subcategory.metadata)
        super_names = [self._canonical_name(_name_of(sc))
                       for sc in super_categories]

        self._check_parametric_placement(
            subcategory.name, super_names,
            also=self._live_parent_names(subcategory.name))

        # Materialize parametric super-categories on first use, anchored
        # under their head (declare-the-dimension-first is enforced by the
        # existence check below: with an undeclared head the name stays
        # opaque and must exist like any other category).
        for name in super_names:
            if name not in self.nodes:
                parsed = self._parse_parametric(name)
                if parsed is not None:
                    self._ensure_parametric_node(name, parsed[0], parsed[1])

        if any(name not in self.nodes for name in super_names):
            raise ValueError("One or more super-categories do not exist.")
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

    def remove(self, node_to_remove):
        # Accept a name string or any Item, and resolve to this instance's
        # node: a fresh Item("X") has empty parents/neighbors, so operating
        # on the caller's object instead of ours would orphan X's children
        # and corrupt the graph. Parametric sugar canonicalizes first.
        name = self._canonical_name(_name_of(node_to_remove))
        if name not in self.nodes:
            raise ValueError(f"Item {name} does not exist.")
        if name == self.root.name:
            raise ValueError("Cannot remove the root.")
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

            del self.nodes[node_to_remove.name]
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
        for name in to:
            name = self._canonical_name(_name_of(name))
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
                    raise ValueError(f"Category {name} does not exist.")
                pending.append((name, parsed[0], parsed[1]))
            destinations.append(name)

        # Everything is validated against the pre-move graph before a single
        # edge moves, so a refusal never leaves half a move behind.
        retract = {}
        for item in items:
            if from_ is None:
                retract[item] = [name for name in self._live_parent_names(item)
                                 if name != self.root.name
                                 and name not in destinations]
            else:
                wanted = []
                for name in from_:
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
            self._check_parametric_placement(item, destinations, also=keeping)

        for name, head, kind in pending:
            self._ensure_parametric_node(name, head, kind)

        for item in items:
            for destination in destinations:
                self.add_edge(self.nodes[destination], self.nodes[item])

        retracted = set()
        for item, olds in retract.items():
            for old in olds:
                # Already gone means the new parent implied it — see above.
                if self.nodes[item] in self.nodes[old].neighbors:
                    self.remove_edge(self.nodes[old], self.nodes[item])
                    retracted.add((old, item))

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

    def remove_cone(self, names):
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
        cone, deleted = self.cone_removal_plan(names)

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
            del self.nodes[name]

        # The root reaches everything by construction (a survivor always keeps
        # a live parent), so its count is free — which matters, since the root
        # is an ancestor of every deletion and its cone is the whole graph.
        for node in affected:
            if node is self.root:
                node.descendant_count = len(self.nodes) - 1
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
        for other_node in other_dag.topological_sort():
            self_node = self.nodes[other_node.name]
            for neighbor in other_node.neighbors:
                if neighbor.name in self.nodes:
                    self.add_edge(self_node, self.nodes[neighbor.name])

        self._remove_duplicate_root_edges()

    def prune_to_common_descendants(self, interesting_nodes):
        # Gather each node's descendants in a list of sets
        sets_of_descendants = []
        for node in interesting_nodes:
            if node.name in self.nodes:
                sets_of_descendants.append(self.get_descendants(self.nodes[node.name]))
            else:
                sets_of_descendants = []
                break

        # If any interesting node is missing or there's nothing to keep, remove all but root
        if not sets_of_descendants:
            for n in list(self.nodes.values()):
                if getattr(self, 'root', None) and n is not self.root:
                    self.remove(n)
            return

        # Find the intersection of all descendant sets
        common_descendants = set.intersection(*sets_of_descendants)
        only_common_descendants = common_descendants.copy()

        # Include the interesting nodes themselves
        for node in interesting_nodes:
            if node.name in self.nodes:
                common_descendants.add(self.nodes[node.name])

        # Remove all other nodes from the DAG
        for n in list(self.nodes.values()):
            if n not in common_descendants and getattr(self, 'root', None) and n is not self.root:
                self.remove(n)

        # Remove duplicate edges between ancestors and lower level sub-categories
        for n in list(self.nodes.values()):
            for subcategory in list(n.neighbors):
                subcategory_ancestors = self.get_ancestors(subcategory, {self.root})
                for ancestor in subcategory_ancestors:
                    if ancestor in n.neighbors and subcategory in n.neighbors:
                        self.remove_edge(n, subcategory)
                        print(f'Removed edge {n.name} -> {subcategory.name}')

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
