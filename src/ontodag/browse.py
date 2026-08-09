"""Browsing an OntoDAG: a query, its answer, and the ways to narrow it.

A path is a query. `/pet/dog` is not a location, it means *pet AND dog*, and
`/dog/pet` is the same place — the ontodag-fs thesis, and Gifford's Semantic
File System before it. So "drilling down" by clicking a category is not
navigation, it is appending a term to a conjunction:

    click Japan   ==  get Japan
    click Flight  ==  get Japan Flight

which is why a browse pane and a command line are two inputs to one state
rather than two interfaces.

What a browser needs beyond the answer is the list of *useful* next steps.
A category held by **every** member of the answer narrows nothing (asking for
it again returns what you already have); one held by **none** is a dead end.
The refinements are what is left: held by some but not all. Every click
therefore lands on a genuinely different answer — which is to say it is a
walk in the concept lattice, the Dedekind-MacNeille completion of the DAG
(`paper/ontodag-fca.tex`, result 2).

This lives in the package rather than in the web app for the reason
`query_picture` does: the CLI, the web page and any future surface must not
drift into disagreeing about what the choices are.

Imports nothing. The DAG is duck-typed, so this works over `OntoDAG`,
`EagerOntoDAG`, `SparseOntoDAG` and a read-only `LazyOntoDAG` view of a
published root alike.
"""

# How many answer members to inspect when collecting refinements. The
# computation is O(answer x ancestors); at personal and demo scale that is
# nothing, and on a published store it is the same broad-query cost the cone
# index exists for (`ontodag.cones`). Rather than get slow quietly, stop and
# say so — `Browse.sampled` reports it, and the caller can show it.
SAMPLE = 2000


class Browse:
    """One position: the query, what is there, and where you can go next."""

    __slots__ = ("queries", "here", "refine", "count", "sampled")

    def __init__(self, queries, here, refine, count, sampled):
        self.queries = queries
        self.here = here          # [(name, has_children, count)]
        self.refine = refine      # [(name, matching)] most-matching first
        self.count = count        # the complete size of the answer
        self.sampled = sampled    # refinements come from a sample, not all

    def __repr__(self):
        return (f"<Browse {self.queries!r} count={self.count} "
                f"refine={len(self.refine)}>")


def _answer(dag, queries):
    if not queries:
        queries = [[]]
    if len(queries) == 1:
        return dag.get(queries[0])
    return dag.get_any(queries)


def refinements(dag, answer, exclude=(), sample=SAMPLE):
    """The categories that split `answer` — held by some of it, not all.

    Returns `[(name, matching), ...]`, most-matching first then alphabetical,
    where `matching` is how many of the answer would survive the click. That
    number is exact for the categories reported: adding a term C to the query
    intersects the answer with C's cone, which is precisely the answer members
    having C as an ancestor.
    """
    answer = list(answer)
    total = len(answer)
    if total < 2:
        # One item cannot be split, and nothing is left to choose between.
        return [], False
    sampled = sample and total > sample
    inspected = answer[:sample] if sampled else answer

    root = dag.root.name
    skip = {root, *exclude}
    counts = {}
    for item in inspected:
        for ancestor in dag.get_ancestors(item.name):
            name = ancestor.name
            if name not in skip:
                counts[name] = counts.get(name, 0) + 1

    seen = len(inspected)
    # Held by everything inspected -> narrows nothing. Under sampling this is
    # a judgement on the sample, which is why `sampled` travels with it.
    return (sorted(((name, n) for name, n in counts.items() if n < seen),
                   key=lambda pair: (-pair[1], pair[0])),
            bool(sampled))


def browse(dag, queries, sample=SAMPLE):
    """Everything a browser needs about one position in the lattice.

    `queries` is DNF — a list of conjunctions whose answers union — the same
    shape `get_any` takes, so `[[]]` (or `[]`) is the empty query, which is
    everything.
    """
    queries = [list(terms) for terms in queries] or [[]]
    answer = _answer(dag, queries)

    asked = {term for terms in queries for term in terms}
    # A term already in the query, and anything above it, is implied — those
    # are dropped by the held-by-everything rule anyway, but a *virtual*
    # parametric term (`weight(..5kg)`, which needs no node) has no ancestors
    # to be counted, so name it explicitly.
    refine, sampled = refinements(dag, answer, exclude=asked, sample=sample)

    here = sorted((item.name, bool(item.neighbors), item.descendant_count)
                  for item in answer)
    return Browse(queries, here, refine, len(here), sampled)


def focus(dag, name):
    """What one node looks like up close: its neighbours in both directions.

    Parents are filtered to *live* ones — a removed node can linger in a
    child's `parents` set — the same check `_print_dag` makes.
    """
    node = dag.nodes.get(name)
    if node is None:
        return None
    return {
        "name": node.name,
        "above": sorted(p.name for p in node.parents
                        if dag.nodes.get(p.name) is p and p.name != name),
        "below": sorted(n.name for n in node.neighbors),
        "count": node.descendant_count,
        "root": node.name == dag.root.name,
    }
