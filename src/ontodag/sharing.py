"""What one store shows another reader (docs/plans/SHARING.md).

    R sees node x of O's store iff x is below one of R's principals in O's
    store — evaluated in O's store alone, never in a merge of stores.

A *principal* is a name that stands for a reader (categor.io spells them as
addresses, `ada@categor.io`). How a store should mark its principals is
SHARING.md's open question Q1, so here the caller names them.

- `reach(dag, principals, exclude=())`: what those principals may see.
- `landing(dag, principals, exclude=())`: what is filed directly under
  each principal, which is where shares arrive.
- `losses(before, after, principals)`: what an edit would stop each
  principal seeing, for asking before making it.
- `timeline(dag, principals, role="posted")`: what they see, in time
  order: the author's wall as those readers see it (WALLS_AND_INBOXES §2).

Reach follows the combined order `get` and `is_below` use (asserted edges
plus the computed order of typed values). So `x in reach(dag, [p])` iff
`dag.is_below(x, p)` and `x != p`, when nothing is excluded. It is a
down-set (SHARING.md §2.1): whatever is below something shared is shared.

`exclude` is the host's policy, not the rule. categor.io passes what
already sat below an address before it was registered, because a grant
cannot wait for its holder to appear. An excluded name is never entered,
so what hangs only below it is not reached; what hangs below it *and*
elsewhere in reach still is. `exclude` may be one collection for all
principals, or a mapping from principal to its own collection.

Standard library only; the DAG is duck-typed (`nodes`, `get_descendants`),
so this works over `OntoDAG`, `EagerOntoDAG`, `SparseOntoDAG` and a
read-only `LazyOntoDAG` view of a published root alike.
"""

from collections.abc import Mapping


def _excluded(exclude, principal):
    if isinstance(exclude, Mapping):
        return frozenset(exclude.get(principal, ()))
    return frozenset(exclude)


def _one(dag, principal, skip):
    node = dag.nodes.get(principal)
    if node is None:
        return frozenset()
    # `visited` stops the walk expanding a node; seeding it with the
    # excluded names means their cones are only reached by other paths.
    stops = {dag.nodes[name] for name in skip if name in dag.nodes}
    found = dag.get_descendants(node, visited=stops)
    return frozenset(item.name for item in found) - skip - {principal}


def reach(dag, principals, exclude=()):
    """The names `principals` may see in `dag`: a frozenset, the union of
    what is below each of them, never entering an excluded name."""
    seen = set()
    for principal in principals:
        seen |= _one(dag, principal, _excluded(exclude, principal))
    return frozenset(seen)


def landing(dag, principals, exclude=()):
    """{principal: sorted names filed directly under it} — the top of what
    each principal is shared, and where a host shows it arriving.
    Principals with nothing filed under them are left out."""
    out = {}
    for principal in principals:
        node = dag.nodes.get(principal)
        if node is None:
            continue
        skip = _excluded(exclude, principal)
        direct = sorted(child.name for child in node.neighbors if child.name not in skip)
        if direct:
            out[principal] = direct
    return out


def losses(before, after, principals, exclude=()):
    """{principal: sorted names} that `before` shows the principal and
    `after` does not — per principal, never pooled, so a name one of them
    still sees through another right is not a loss for the others."""
    out = {}
    for principal in principals:
        skip = _excluded(exclude, principal)
        gone = _one(before, principal, skip) - _one(after, principal, skip)
        if gone:
            out[principal] = sorted(gone)
    return out


def point_values(dag, name, role):
    """The points of `role` (a time dimension or a role of one, such as
    `posted`) that `name` is filed under directly, as names. A range such
    as `posted(2026)` is not a point, and is left out."""
    from ontodag.dimensions import split_term
    out = []
    for parent in dag.nodes[name].parents:
        parts = split_term(parent.name)
        if (parts and parts[0] == role and ".." not in parts[1]
                and dag.is_term(parent.name)):
            out.append(parent.name)
    return sorted(out)


def timeline(dag, principals, role="posted", exclude=()):
    """What `principals` see, in time order: `(value, name)` for each name
    in their reach filed under a point of `role`, oldest first. With the
    default role this is an author's wall as those readers see it
    (WALLS_AND_INBOXES §2). The value is the author's claim, as ever.
    Values that are themselves typed values are not posts, and are skipped."""
    out = []
    for name in reach(dag, principals, exclude):
        if dag.is_term(name):
            continue
        for value in point_values(dag, name, role):
            out.append((value, name))
    return sorted(out, key=_by_time)


def _by_time(pair):
    from ontodag.dimensions import split_term
    return (split_term(pair[0])[1], pair[1])
