"""Comparing two stores — what one has that the other doesn't.

An opt-in consumer of the core, like `ontodag.surface` and `ontodag.viz`: the
arrow points one way (this reads DAGs, nothing in the core reads this), it needs
no dependency at all, and it imports nothing — the DAGs are duck-typed, so an
`OntoDAG`, an `EagerOntoDAG` and a `SparseOntoDAG` all work.

The whole module rests on one decision, and it was measured rather than assumed:

**Claims decide what is reported; edges display it.**

Comparing reduced edge sets accuses people of deletions they did not make. The
transitive reduction is unique, so adding one edge can *prune* others: filing
`Z` under `B` in a graph where `p→B`, `p→Z`, `B→leaf`, `Z→leaf` measured as
`edges +1 -2` while the store entailed strictly *more* than before. Nothing was
forgotten; two edges were re-routed. So an edge that vanished is reported only
when the claim it carried vanished with it, which `is_below` on the other side
settles exactly (and cheaply — no closure needed for that question).

The converse is just as real: claims alone cascade with depth. A leaf added
twelve levels down is thirteen new claims; one edge added high in a chain is
eleven. So the *listing* stays at edge grain — one line per change — and the
cascade becomes a count, for whoever wants to know how much moved.

Deliberately two-way. `compare(ours, theirs)` cannot distinguish "they deleted
it" from "we added it after they copied it": that needs the base they started
from, which is a three-way merge (`recordstore.RecordStore.merge`), and an `rs:`
or `swarm:` store records that base for free as the root it was at.
"""


def parents_of(dag, name):
    """The categories `name` is filed under, root excluded, sorted.

    Root excluded because "under `*`" means "under nothing in particular", which
    is noise in a comparison and in a listing."""
    node = dag.nodes[name]
    return sorted(parent.name for parent in node.parents
                  if dag.nodes.get(parent.name) is parent
                  and parent.name != dag.root.name)


def asserted_edges(dag, scope):
    """Asserted parent→child pairs with BOTH ends in scope, as (child, parent)."""
    return {(name, parent)
            for name in scope if name in dag.nodes
            for parent in parents_of(dag, name) if parent in scope}


def entailed_claims(dag, scope):
    """Every `sub ⊑ sup` the store entails within scope — the honest unit.

    Combined order (asserted edges *and* the computed order between parametric
    values), because that is what the store answers `below` with: two stores can
    entail different things with no edge difference at all, when one of them
    carries a dimension declaration the other lacks.

    Restricted to scope on both ends so a scoped comparison stays bounded. The
    unscoped case walks every cone — a report's cost, not a query's, which is
    why the listing never needs this and only the summary count does.
    """
    claims = set()
    for name in scope:
        node = dag.nodes.get(name)
        if node is None:
            continue
        for descendant in dag.get_descendants(node):
            if descendant.name != name and descendant.name in scope:
                claims.add((descendant.name, name))
    return claims


def scope_of(ours, theirs, queries=None):
    """The names a comparison covers.

    With `queries` (DNF, as `get_any` takes it) both sides are cut to the set an
    `excerpt --context` would take — the answer plus the categories it hangs
    from, on each side, unioned. That is what makes comparing a *cut* against
    the store it came from meaningful: unscoped, everything outside the cut
    reads as a deletion. Without queries, everything either side mentions."""
    if queries:
        return (ours.excerpt_names(queries, context=True)
                | theirs.excerpt_names(queries, context=True))
    return ((set(ours.nodes) | set(theirs.nodes))
            - {ours.root.name, theirs.root.name})


class Comparison:
    """The result of `compare`: what differs, at both grains.

    `only_ours`/`only_theirs` are items one side has and the other does not,
    each carrying the parents it is filed under on that side. `removed`/`added`
    are claim changes about items *both* sides have — as `(sub, sup)` pairs,
    filtered so a re-routed edge is not reported (see the module docstring); an
    item present on only one side carries its parents on its own line, so
    listing its edges as well would say the same thing twice.

    `entailed_added`/`entailed_removed` are the cascade, computed on first
    access because they are the expensive half and most callers only want the
    size of them.
    """

    def __init__(self, ours, theirs, scope):
        self.ours, self.theirs, self.scope = ours, theirs, scope
        self.only_ours = sorted(n for n in scope
                                if n in ours.nodes and n not in theirs.nodes)
        self.only_theirs = sorted(n for n in scope
                                  if n in theirs.nodes and n not in ours.nodes)
        self.common = scope - set(self.only_ours) - set(self.only_theirs)
        ours_edges = asserted_edges(ours, self.common)
        theirs_edges = asserted_edges(theirs, self.common)
        self.added = sorted(edge for edge in theirs_edges - ours_edges
                            if not ours.is_below(*edge))
        self.removed = sorted(edge for edge in ours_edges - theirs_edges
                              if not theirs.is_below(*edge))
        self._entailed = None

    def __bool__(self):
        """True when anything differs — `if compare(a, b): ...` reads right."""
        return bool(self.only_ours or self.only_theirs
                    or self.added or self.removed)

    def _entailment(self):
        if self._entailed is None:
            self._entailed = (entailed_claims(self.ours, self.scope),
                              entailed_claims(self.theirs, self.scope))
        return self._entailed

    @property
    def entailed_added(self):
        ours, theirs = self._entailment()
        return theirs - ours

    @property
    def entailed_removed(self):
        ours, theirs = self._entailment()
        return ours - theirs

    def parents_ours(self, name):
        return parents_of(self.ours, name)

    def parents_theirs(self, name):
        return parents_of(self.theirs, name)

    def additions(self):
        """Their additions as a standalone DAG that `merge` applies.

        Their new items with the parents those hang from, plus both ends of each
        new claim: the minimum that merges to the same place. Measured: merging
        this reaches the byte-identical root to merging their whole store, which
        is why there is no patch format — the additive half of a patch *is* a
        merge, so it needs no new mechanism, only a smaller file.

        Removals cannot be in it, and never will be. A removal is lossy (removing
        a category reattaches its children to its parents; putting it back does
        not put them back under it) and does not commute with a concurrent
        addition — apply `remove X` before `put D X` and the put fails, after it
        and you silently get a different graph. A file whose effect depends on
        when it is applied cannot be a fold, so it would take the canonical-root
        property with it. Callers that offer this must say what it leaves out:
        `len(only_ours) + len(removed)`.

        A node whose parents were left out arrives parentless and is absorbed by
        reduction on merge, since the receiving store already has it properly
        filed — the same property that makes an excerpt a no-op in the store it
        came from.
        """
        names = set(self.only_theirs)
        for name in self.only_theirs:
            names |= set(parents_of(self.theirs, name))
        for sub, sup in self.added:
            names |= {sub, sup}
        return self.theirs.induced_subdag(names)


def compare(ours, theirs, queries=None):
    """Compare two DAGs; `queries` (DNF) scopes both sides. See `Comparison`."""
    return Comparison(ours, theirs, scope_of(ours, theirs, queries))
