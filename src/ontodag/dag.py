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
        # A child with no parents yet cannot be reached from anywhere, so the
        # "does this ancestor already reach it?" probe is provably False for
        # every ancestor and is skipped. That is the common case — appending a
        # fresh item — and it is what keeps the whole operation proportional to
        # the ancestor set instead of to the cones: an exhaustive probe is the
        # expensive direction (it can only conclude "no" by walking the lot).
        unreachable = not self._live_parents(child)
        deltas = {}
        frontier = [parent]
        seen = set()
        while frontier:
            node = frontier.pop()
            if node in seen:
                continue
            seen.add(node)
            if not unreachable and self._is_reachable(node, child):
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
        deltas = {}
        frontier = [parent]
        seen = set()
        while frontier:
            node = frontier.pop()
            if node in seen:
                continue
            seen.add(node)
            if self._is_reachable(node, child):
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
        # sugar canonicalizes first (weight(3kg) -> weight(3000000mg)), and
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
        visited = set()
        stack = []
        for start in self.nodes.values():
            if start in visited:
                continue
            visited.add(start)
            path = [(start, iter(start.neighbors))]
            while path:
                node, neighbors = path[-1]
                for neighbor in neighbors:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        path.append((neighbor, iter(neighbor.neighbors)))
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
    # (weight(3000000mg)) anchored under it by a schema edge — the "star".
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
        return split[0], kind, _dims.canonicalize(name, kind)

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
                    canonical, sibling.name, kind):
                yield sibling

    def _computed_parents(self, node):
        parsed = self._parse_parametric(node.name)
        if parsed is None:
            return
        head, kind, canonical = parsed
        for sibling, _ in self._star(head):
            if sibling is not node and _dims.contains(
                    sibling.name, canonical, kind):
                yield sibling

    def _ensure_parametric_node(self, canonical, head, kind):
        """Materialize a used value: one node, one anchor edge under its
        head. Every value of one head must share one value space (one unit
        family, one arity) — checked against the star, which keeps the
        property inductively."""
        node = self.nodes.get(canonical)
        if node is not None:
            return node
        space = _dims.space_of(canonical, kind)
        for sibling, _ in self._star(head):
            sibling_space = _dims.space_of(sibling.name, kind)
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
        if not anchor and self._is_reachable(from_node, to_node, computed=True):
            return
        # Reject cycles — through computed hops too — before anything mutates.
        if self._is_reachable(to_node, from_node, computed=True):
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
        results. See docs/SEMANTIC_CODES.md §10 before adding such a rewrite;
        it is sound only with a canonical-placement invariant on put().
        """
        # 1. Resolve and deduplicate; terms may be name strings or Items
        # (names are the identity at the public boundary, and parametric
        # sugar canonicalizes first); an unknown term has an empty cone.
        terms = {}
        for super_category in super_categories:
            node = self.nodes.get(self._canonical_name(_name_of(super_category)))
            if node is None:
                return set()
            terms[node.name] = node
        if not terms:
            # Preserves the pre-planner behavior (set.intersection() with no
            # sets raised TypeError), with an intelligible message.
            raise TypeError("get() requires at least one super-category")

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
        edges_to_remove = set()
        root = self.root
        for root_neighbor in root.neighbors:
            ancestors = self.get_ancestors(root_neighbor, ignore={root})
            if any(ancestor in root.neighbors for ancestor in ancestors):
                edges_to_remove.add(root_neighbor)

        for root_neighbor in edges_to_remove:
            self.remove_edge(root, root_neighbor)

    def _remove_unneeded_edges(self, from_node, to_node):
        """Remove edges made redundant by the from -> to edge: a direct edge
        from any *combined-order* ancestor of `from_node` down to `to_node`
        is now implied. Anchor edges (head -> value) are schema and never
        pruned — they are the dimension's enumeration index (DIMENSIONS.md
        §5), and pruning them would leave stored form dependent on which
        other values happen to exist."""
        ancestors = self.get_ancestors(from_node)  # combined order
        for ancestor in ancestors:
            if to_node in ancestor.neighbors \
                    and not self._is_anchor(ancestor, to_node):
                self.remove_edge(ancestor, to_node)

    def put(self, subcategory, super_categories, optimized=False):
        # Names are the identity at the public boundary: plain strings are
        # accepted anywhere an Item is (see "Identity" in CLAUDE.md), and
        # parametric sugar resolves to the canonical name before anything
        # else looks at it (weight(3kg) -> weight(3000000mg), §7).
        if isinstance(subcategory, str):
            subcategory = Item(subcategory)
        sub_parsed = self._parse_parametric(subcategory.name)
        if sub_parsed is not None and subcategory.name != sub_parsed[2]:
            subcategory = Item(sub_parsed[2], metadata=subcategory.metadata)
        super_names = [self._canonical_name(_name_of(sc))
                       for sc in super_categories]

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
                f"refusing {subcategory.name} under "
                f"{parametric_supers[sub_parsed[0]][0][0]}")

        # The disjoint-parents guard (DIMENSIONS.md §9): an item sits in the
        # INTERSECTION of its parents, so provably disjoint same-dimension
        # parents assert membership of an empty concept — the
        # union-vs-intersection footgun, caught exactly. Existing parametric
        # parents of the node participate too.
        existing_node = self.nodes.get(subcategory.name)
        if existing_node is not None:
            for parent in existing_node.parents:
                if self.nodes.get(parent.name) is not parent:
                    continue
                parsed = self._parse_parametric(parent.name)
                if parsed is not None and parsed[0] in parametric_supers:
                    parametric_supers[parsed[0]].append((parent.name, parsed[1]))
        for head, entries in parametric_supers.items():
            for (name_a, kind), (name_b, _) in combinations(entries, 2):
                if _dims.intersect(name_a, name_b, kind) is None:
                    raise ValueError(
                        f"{subcategory.name} cannot sit under both {name_a} "
                        f"and {name_b}: provably disjoint {head!r} terms — "
                        "an item is in the intersection of its parents; for "
                        "a union, use a region node (DIMENSIONS.md §9)")

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


class OntoDAGVisualizer:
    def __init__(self, format="png", layout="TB", default_color="seashell", root_color="seashell3"):
        self.format = format
        self.layout = layout
        self.default_color = default_color
        self.root_color = root_color

    def visualize(self, dag, filename="ontodag_vis", color_mapping=None):
        from graphviz import Digraph
        dag_type = dag.__class__.__name__
        graph = Digraph(comment=dag_type, format=self.format)
        graph.attr(rankdir=self.layout)

        for node in dag.nodes.values():
            self._render_node(graph, node, is_root=node.name == dag.root.name, color_mapping=color_mapping)

        # Render the graph to a file
        output_path = graph.render(filename)
        print(f"{dag_type} visualization saved as: {output_path}")

    def generate_dot_source(self, dag, color_mapping=None):
        from graphviz import Digraph
        dag_type = dag.__class__.__name__
        graph = Digraph(comment=dag_type, format="dot")
        graph.attr(rankdir=self.layout)

        for node in dag.nodes.values():
            self._render_node(graph, node, is_root=node.name == dag.root.name, color_mapping=color_mapping)

        # Return the DOT source string
        return graph.source

    def generate_image(self, dag, color_mapping=None):
        from graphviz import Digraph
        from io import BytesIO
        from PIL import Image

        dag_type = dag.__class__.__name__
        graph = Digraph(comment=dag_type, format=self.format)
        graph.attr(rankdir=self.layout)

        for node in dag.nodes.values():
            self._render_node(graph, node, is_root=node.name == dag.root.name, color_mapping=color_mapping)

        png_data = graph.pipe(format="png")
        return Image.open(BytesIO(png_data))

    def _render_node(self, graph, node, is_root=False, color_mapping=None):
        if color_mapping is None:
            color = self.root_color if is_root else self.default_color
        else:
            color = self.root_color if is_root else color_mapping.get(node, self.default_color)
        # Add nodes
        graph.node(node.name, f'{node.name}: {node.descendant_count}', style="filled", fillcolor=color)
        # Add edges for each super-category-to-subcategory relationship
        for subcategory in node.neighbors:
            graph.edge(node.name, subcategory.name)
