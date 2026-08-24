"""Graphviz rendering — an optional consumer of the DAG, never part of it.

This lives outside `dag.py` for the same reason `owl.py` does: it is one of
several *consumers* of a DAG, and the core must not carry them. The arrow
points one way — this module imports from the core, nothing in the core
imports this — which is what makes `pip install ontodag` need no renderer,
no `dot` binary, and no C toolchain.

Requires the `viz` extra AND the Graphviz *system* program:

    pip install "ontodag[viz]"
    apt install graphviz    # or: brew install graphviz
"""

# The half of the answer the pip command alone does not give.
_INSTALL_BINARY = (
    "  sudo apt install graphviz     # or: brew install graphviz\n"
    "  winget install graphviz       # on Windows, then check `dot -V` in a "
    "NEW shell")

_BINARY = (
    "  ...and the Graphviz system program:\n"
    + _INSTALL_BINARY + "\n"
    "(the `graphviz` PyPI package is only a wrapper — the `dot` binary has "
    "to come from your OS. To render elsewhere, ask for the DOT source "
    "instead and hand it to any Graphviz implementation.)"
)


def _rendered(call):
    """Run a Graphviz call, or explain that the *program* is missing.

    The other half of `_digraph`'s job, and the half that actually bites:
    `pip install "ontodag[viz]"` satisfies the import, so rendering gets all
    the way to spawning `dot` before failing — with a graphviz-internal
    `ExecutableNotFound` traceback that arrives through thirty lines of
    stack. That is the single most likely Windows failure (the binary is a
    separate download there and is not added to PATH by default), and it is
    an instruction, not a bug, so it is raised as one.

    Matched by class name rather than by importing the exception: this stays
    honest across graphviz versions, and the module is deliberately reachable
    without knowing anything about graphviz's internals.
    """
    try:
        return call()
    except Exception as exc:                     # noqa: BLE001 - re-raised
        if type(exc).__name__ != "ExecutableNotFound":
            raise
        from ontodag._extras import MissingExtra
        raise MissingExtra(
            "rendering needs the Graphviz system program `dot`, which pip "
            "does not install:\n" + _INSTALL_BINARY + "\n"
            "(the `graphviz` package is only a wrapper — `dot` does the "
            "drawing. Nothing else needs it: only pictures fail.)"
        ) from exc


def _digraph():
    """Import graphviz, or explain how to get it.

    A bare ModuleNotFoundError names a package, which is the least useful
    half of the answer: `pip install graphviz` alone leaves you without the
    binary that does the actual work, and the failure then moves to a
    confusing ExecutableNotFound later on."""
    from ontodag._extras import require
    return require("graphviz", "viz", "rendering", hint=_BINARY).Digraph


def query_picture(dag, queries):
    """The drawable form of a query: its answer, under a node per query term.

    `queries` is DNF — a list of conjunctions whose results union, the same
    shape `get_any` takes. Each term hangs above the answers *its own
    disjunct* produced, so a union reads as the two branches it is.

    Built from `get()` — the authoritative query path — because the obvious
    alternative is wrong. `get_by_dag` intersects by *name*, so a parametric
    term with no node of its own (a virtual term like `weight(..5kg)`, which
    is the whole point of dimensions) simply vanished from the query: asking
    for `weight(..5kg)` drew an empty graph, and asking for
    `Japan,weight(..5kg)` drew all of Japan — a picture that contradicted the
    result list beside it. A picture that disagrees with the answer is worse
    than no picture.

    Query terms become nodes here even when no such node exists in the store.
    That is sound because this DAG is a *view*: it is drawn and discarded,
    never merged or committed, so inventing a node to draw the constraint
    costs nothing and is the only way to show what was asked. It is also
    exactly why `odag excerpt` — the *materialized* cut of the same answer —
    does the opposite: a file that gets imported back must not carry the
    constraint as though it were knowledge.

    Lives here rather than in the web app because the CLI's `visualize` and
    the web's query image must not drift into drawing different pictures of
    the same answer. It needs no Graphviz — this is the shaping step that
    precedes rendering.
    """
    from ontodag.dag import Item

    results = dag.get(queries[0]) if len(queries) == 1 else dag.get_any(queries)
    # Cones are downward-closed under intersection — everything below a
    # result is also a result — so the answer copies with its own structure
    # intact, and copy_subdag's descendant closure adds nothing extra.
    picture = dag.copy_subdag(list(results))

    for terms in queries:
        branch = dag.get(terms)
        names = {item.name for item in branch}
        # Hang each term above the topmost answers of its own disjunct;
        # deeper answers keep the real edges copied above, so the shape of
        # the answer survives.
        tops = [item for item in branch
                if not any(parent.name in names for parent in item.parents)]
        for term in terms:
            node = picture.nodes.get(term) or Item(term)
            picture.add_node(node)
            picture.root.neighbors.add(node)
            for top in tops:
                if top.name != term:
                    node.neighbors.add(picture.nodes[top.name])
    return picture


class OntoDAGVisualizer:
    """Renders a DAG through Graphviz.

    Node *identifiers* in the emitted DOT are synthetic (`n0`, `n1`, ...) and
    the item name lives in the label. That indirection is not cosmetic: DOT
    gives `:` a meaning inside an identifier (the port separator), and the
    graphviz package's quoting splits on it — so a canonical timestamp name
    like `time(2026-01-01T00:00:00Z..2026-12-31T23:59:59Z)` used as an
    identifier emits `"time(2026-01-01T00":00:00Z...` and the render dies
    with a syntax error. Labels are quoted correctly, so putting names there
    makes every name renderable whatever characters a dimension canonical
    form happens to use. Ids are assigned in the DAG's own iteration order,
    which is deterministic, so the DOT output stays diffable."""

    def __init__(self, format="png", layout="TB", default_color="seashell",
                 root_color="seashell3", label=None):
        self.format = format
        self.layout = layout
        self.default_color = default_color
        self.root_color = root_color
        # How a node is captioned, given (name, descendant_count). The default
        # is the historical `name: count`; a surface that renders names for
        # people passes its own, so the picture agrees with the list beside it.
        self.label = label or (lambda name, count: f"{name}: {count}")

    @staticmethod
    def node_ids(dag):
        """name -> the synthetic DOT identifier used for it.

        Public because a *clickable* rendering needs to map back: Graphviz
        emits these ids into the SVG (`<g class="node"><title>n2</title>`), so
        a caller can turn a click on a shape into the name it stands for
        without parsing labels — which would be ambiguous, since labels carry
        counts and may be rendered rather than canonical.
        """
        return {name: f"n{index}" for index, name in enumerate(dag.nodes)}

    _ids = node_ids   # the name this had before anything outside needed it

    def _build(self, dag, color_mapping=None, format=None):
        """The whole graph, assembled once. The three public entry points
        differ only in what they do with it afterwards."""
        Digraph = _digraph()
        graph = Digraph(comment=dag.__class__.__name__,
                        format=format or self.format)
        graph.attr(rankdir=self.layout)
        ids = self._ids(dag)
        for node in dag.nodes.values():
            self._render_node(graph, node, ids,
                              is_root=node.name == dag.root.name,
                              color_mapping=color_mapping)
        return graph

    def visualize(self, dag, filename="ontodag_vis", color_mapping=None):
        graph = self._build(dag, color_mapping)
        output_path = _rendered(lambda: graph.render(filename))
        print(f"{dag.__class__.__name__} visualization saved as: "
              f"{output_path}")

    def generate_dot_source(self, dag, color_mapping=None):
        return self._build(dag, color_mapping, format="dot").source

    def generate_svg(self, dag, color_mapping=None):
        """The graph as SVG text, ready to inline.

        SVG rather than PNG wherever a person will interact with the picture:
        it scales, it is a fraction of the size, the ids survive into the
        markup (see `node_ids`) so clicking a node is one event handler and no
        graph library, and — unlike `generate_image` — it needs no Pillow.
        Layout is still Graphviz's: `dot`'s layered ranking is the thing worth
        keeping about DOT, and it is better than anything that would run in
        the browser.
        """
        graph = self._build(dag, color_mapping)
        return _rendered(lambda: graph.pipe(format="svg")).decode("utf-8")

    def generate_image(self, dag, color_mapping=None):
        from io import BytesIO
        try:
            from PIL import Image
        except ImportError as exc:
            raise ImportError(
                "returning an image object needs Pillow "
                '(pip install "ontodag[viz]"); `visualize()` writes a file '
                "without it, and `generate_dot_source()` needs neither."
            ) from exc
        graph = self._build(dag, color_mapping)
        png = _rendered(lambda: graph.pipe(format="png"))
        return Image.open(BytesIO(png))

    def _render_node(self, graph, node, ids, is_root=False,
                     color_mapping=None):
        if color_mapping is None:
            color = self.root_color if is_root else self.default_color
        else:
            color = self.root_color if is_root else color_mapping.get(
                node, self.default_color)
        # Synthetic id, real name in the label (see the class note).
        graph.node(ids[node.name], self.label(node.name, node.descendant_count),
                   style="filled", fillcolor=color)
        for subcategory in sorted(node.neighbors, key=lambda n: n.name):
            graph.edge(ids[node.name], ids[subcategory.name])
