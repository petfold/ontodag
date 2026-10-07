"""What one store shows another reader (docs/plans/SHARING.md).

    R sees node x of O's store iff x is below `shared-with(R)` in O's
    store — evaluated in O's store alone, never in a merge of stores.

`shared-with` is the audience head, a dimension of the reversed kind
(DIMENSIONS.md §18; ROLES.md §7 and §8 items 18 and 20): what is shared
with a group is shared with each of its members, so once Alice is a sales
employee, `shared-with(sales-employee) ⊑ shared-with(alice)` is computed,
and whatever is filed under the group's term is in Alice's reach. People
and groups are ordered by kinds (`alice ⊑ sales-employee ⊑ employee`),
never by `in`, so a location fact never grants access. A *principal* is
the name the term is about, usually a person (categor.io spells them as
addresses, `ada@categor.io`).

Until 0.30 a reader's reach was the cone of the principal's own name, with
groups filed below their members. That made membership and sharing one
edge pointing both ways (`employees ⊑ ada` beside `ada ⊑ employees` is a
cycle), and it is the misuse ROLES.md §1 diagnosed.

- `reach(dag, principals, exclude=())`: what those principals may see.
- `landing(dag, principals, exclude=())`: what is filed directly under
  each principal's term, which is where shares arrive.
- `losses(before, after, principals)`: what an edit would stop each
  principal seeing, for asking before making it.

Reach follows the combined order `get` and `is_below` use, so
`x in reach(dag, [p])` iff `dag.is_below(x, "shared-with(p)")` and x is
not the term itself, when nothing is excluded. It is a down-set
(SHARING.md §2.1): whatever is below something shared is shared. It
includes the audience terms it passes through (`shared-with(employee)`
in Alice's reach): they are what her keys are derived along.

`exclude` is the host's policy, not the rule. An excluded name is never
entered, so what hangs only below it is not reached; what hangs below it
*and* elsewhere in reach still is. `exclude` may be one collection for all
principals, or a mapping from principal to its own collection.

Standard library only; the DAG is duck-typed, so this works over
`OntoDAG`, `EagerOntoDAG`, `SparseOntoDAG` and a read-only `LazyOntoDAG`
view of a published root alike.
"""

from collections.abc import Mapping

HEAD = "shared-with"


def audience(principal):
    """The audience term for a principal: `shared-with(principal)`."""
    return f"{HEAD}({principal})"


def _excluded(exclude, principal):
    if isinstance(exclude, Mapping):
        return frozenset(exclude.get(principal, ()))
    return frozenset(exclude)


def tops(dag, principal):
    """(term name, start nodes): where a principal's reach starts. The
    principal's term itself when it is present; otherwise, since nothing is
    filed directly under it, the present audience terms it contains (a
    group's term, for a member). Empty when the principal or the head is
    unknown: nothing is shared with a name the store doesn't know."""
    term = audience(principal)
    node = dag.nodes.get(term)
    if node is not None:
        return term, [node]
    try:
        parsed = dag._parse_parametric(term)
    except ValueError:
        return term, []                 # the principal is not a node here
    if parsed is None:
        return term, []                 # no audience head declared
    head, kind, canonical = parsed
    node = dag.nodes.get(canonical)
    if node is not None:
        return canonical, [node]
    return canonical, list(dag._contained_values(canonical, head, kind))


def _one(dag, principal, skip):
    term, starts = tops(dag, principal)
    if not starts:
        return frozenset()
    # `visited` stops the walk expanding a node; seeding it with the
    # excluded names means their cones are only reached by other paths.
    stops = {dag.nodes[name] for name in skip if name in dag.nodes}
    found = set()
    for start in starts:
        if start in stops:
            continue
        if start.name != term:
            found.add(start)
        found |= dag.get_descendants(start, visited=stops)
    return frozenset(item.name for item in found) - skip - {term}


def reach(dag, principals, exclude=()):
    """The names `principals` may see in `dag`: a frozenset, the union of
    what is below each one's audience term, never entering an excluded
    name."""
    seen = set()
    for principal in principals:
        seen |= _one(dag, principal, _excluded(exclude, principal))
    return frozenset(seen)


def landing(dag, principals, exclude=()):
    """{principal: sorted names filed directly under its audience term} —
    what was shared with that principal by name, and where a host shows it
    arriving. What arrives through a group is in the group's landing.
    Principals with nothing filed under their term are left out."""
    out = {}
    for principal in principals:
        node = dag.nodes.get(audience(principal))
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
