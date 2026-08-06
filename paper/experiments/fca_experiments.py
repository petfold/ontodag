"""Experiments backing the OntoDAG/FCA tutorial paper.

Everything the paper states as a number is computed here. Run from the repo
root (or anywhere -- the path insert below finds ``src/``):

    python3 paper/experiments/fca_experiments.py

It writes ``paper/experiments/results.txt`` (quoted in the paper) and the
Graphviz sources in ``paper/figures/*.dot`` that dot2tex turns into figures.

The FCA half is implemented from scratch, in the standard library only, so
the paper's claims about concept lattices do not rest on a library the
reader would have to trust: NextClosure (Ganter 1984) for enumeration, plus
brute-force oracles for the small cases.
"""

import copy
import itertools
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER = os.path.dirname(HERE)
REPO = os.path.dirname(PAPER)
sys.path.insert(0, os.path.join(REPO, "src"))

from ontodag import OntoDAG  # noqa: E402

FIGURES = os.path.join(PAPER, "figures")
OUT = []


def say(line=""):
    print(line)
    OUT.append(line)


def rule(title):
    say()
    say("=" * 72)
    say(title)
    say("=" * 72)


# --------------------------------------------------------------------------
# A minimal Formal Concept Analysis kernel
# --------------------------------------------------------------------------

class Context:
    """A formal context K = (G, M, I): objects G, attributes M, incidence I."""

    def __init__(self, objects, attributes, incidence):
        self.G = list(objects)
        self.M = list(attributes)
        # incidence: dict object -> set of attributes
        self.I = {g: set(incidence[g]) for g in self.G}

    def prime_objects(self, objs):
        """A' -- the attributes shared by every object in A."""
        objs = list(objs)
        if not objs:
            return set(self.M)
        common = set(self.I[objs[0]])
        for g in objs[1:]:
            common &= self.I[g]
        return common

    def prime_attributes(self, attrs):
        """B' -- the objects carrying every attribute in B."""
        attrs = set(attrs)
        return {g for g in self.G if attrs <= self.I[g]}

    def closure(self, attrs):
        """B'' -- the closure of an attribute set."""
        return self.prime_objects(self.prime_attributes(attrs))

    def density(self):
        cells = len(self.G) * len(self.M)
        ones = sum(len(v) for v in self.I.values())
        return ones / cells if cells else 0.0


def next_closure(ctx):
    """Ganter's NextClosure: enumerate all closed attribute sets in
    lectic order. Returns the list of concepts as (extent, intent) pairs."""
    order = list(ctx.M)
    rank = {m: i for i, m in enumerate(order)}
    concepts = []

    def lectic_next(B):
        for m in reversed(order):
            if m in B:
                B = B - {m}
                continue
            candidate = ctx.closure(B | {m})
            # the candidate must not introduce an attribute smaller than m
            smaller = {x for x in candidate - B if rank[x] < rank[m]}
            if not smaller:
                return candidate
        return None

    B = ctx.closure(set())
    while B is not None:
        concepts.append((frozenset(ctx.prime_attributes(B)), frozenset(B)))
        B = lectic_next(B)
    return concepts


def brute_force_concepts(ctx):
    """Oracle: every closed attribute set, found by closing every subset.
    Exponential on purpose -- it is only used to check NextClosure."""
    seen = set()
    for r in range(len(ctx.M) + 1):
        for combo in itertools.combinations(ctx.M, r):
            seen.add(frozenset(ctx.closure(set(combo))))
    return seen


def lattice_cover_edges(concepts):
    """Covering relation (the Hasse diagram) of the concept lattice,
    ordered by intent containment: (A1,B1) <= (A2,B2) iff B2 subseteq B1."""
    intents = [b for _, b in concepts]
    n = len(concepts)
    below = [[False] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            # i is below j  <=>  intent_i contains intent_j
            if i != j and intents[j] < intents[i]:
                below[i][j] = True
    edges = []
    for i in range(n):
        for j in range(n):
            if not below[i][j]:
                continue
            # cover: nothing strictly between
            if not any(below[i][k] and below[k][j] for k in range(n)):
                edges.append((i, j))
    return edges


def stability(ctx, extent, intent):
    """Kuznetsov's (intensional) stability of a concept: the fraction of
    subsets of the extent whose closure is still the intent. High stability
    means the concept does not depend on any few objects."""
    ext = list(extent)
    if len(ext) > 16:
        return None  # brute force only for small extents
    good = 0
    total = 0
    for r in range(len(ext) + 1):
        for sub in itertools.combinations(ext, r):
            total += 1
            if ctx.prime_objects(sub) == set(intent):
                good += 1
    return good / total


# --------------------------------------------------------------------------
# Bridge: OntoDAG <-> formal context
# --------------------------------------------------------------------------

def reflexive_ancestors(dag, name, skip_root=True):
    """code(x): the reflexive ancestor set of x -- the paper's Section 6
    'ancestor-set code'. This is what an FCA intent corresponds to."""
    code = {a.name for a in dag.get_ancestors(name)}
    code.add(name)
    if skip_root:
        code.discard("*")
    return code


def dag_to_context(dag):
    """K(G): objects = attributes = the nodes; incidence = reachability.
    The concept lattice of this context is the Dedekind-MacNeille
    completion of the DAG's reachability order."""
    names = [n for n in dag.nodes if n != "*"]
    incidence = {n: reflexive_ancestors(dag, n) for n in names}
    return Context(names, names, incidence)


def codes_to_cover_edges(codes):
    """The inverse direction: rebuild the transitive reduction from the
    codes alone, as the covering relation of code containment."""
    names = list(codes)
    edges = []
    for x in names:
        for y in names:
            if x == y or not (codes[y] < codes[x]):
                continue  # y must be strictly above x
            between = any(
                z != x and z != y and codes[y] < codes[z] < codes[x]
                for z in names
            )
            if not between:
                edges.append((y, x))  # parent, child
    return set(edges)


def asserted_edges(dag):
    return {
        (p, c.name)
        for p, node in dag.nodes.items()
        for c in node.neighbors
        if p != "*"
    }


# --------------------------------------------------------------------------
# Graphviz emission
# --------------------------------------------------------------------------

def write_dot(name, body):
    path = os.path.join(FIGURES, name)
    with open(path, "w") as fh:
        fh.write(body)
    return path


def esc(s):
    return s.replace('"', r"\"")


# --------------------------------------------------------------------------
# The running example
# --------------------------------------------------------------------------

# A trip to Japan, filed as a formal context. Objects are documents,
# attributes are the properties a document may have.
DOCS = {
    "outbound.pdf":  ["Flight", "Japan", "Booked", "Refundable"],
    "inbound.pdf":   ["Flight", "Japan", "Booked"],
    "kyoto-inn.pdf": ["Hotel", "Japan", "Booked", "Refundable"],
    "rail-pass.pdf": ["Japan", "Booked", "Refundable"],
    "paris-hop.pdf": ["Flight", "Booked"],
    "visa-note.md":  ["Japan"],
}
ATTRS = ["Flight", "Hotel", "Japan", "Booked", "Refundable"]


def experiment_1_running_example():
    rule("EXPERIMENT 1 -- the running example as a formal context")
    ctx = Context(list(DOCS), ATTRS, DOCS)
    say(f"objects |G| = {len(ctx.G)}   attributes |M| = {len(ctx.M)}   "
        f"density = {ctx.density():.2f}")

    say()
    say("The cross table:")
    head = "  " + " " * 14 + " ".join(f"{m[:4]:>5}" for m in ctx.M)
    say(head)
    for g in ctx.G:
        cells = " ".join(f"{'  X  ' if m in ctx.I[g] else '  .  '}"
                         for m in ctx.M)
        say(f"  {g:<14}{cells}")

    concepts = next_closure(ctx)
    oracle = brute_force_concepts(ctx)
    assert {b for _, b in concepts} == oracle, "NextClosure disagrees with oracle"
    say()
    say(f"NextClosure found {len(concepts)} formal concepts "
        f"(brute-force oracle agrees: {len(oracle)}).")
    say(f"Upper bound if every attribute set were closed: 2^{len(ctx.M)} = "
        f"{2 ** len(ctx.M)}.")

    say()
    say("Every formal concept (extent | intent), with support and stability:")
    rows = []
    for extent, intent in sorted(concepts, key=lambda c: (-len(c[0]), sorted(c[1]))):
        supp = len(extent)
        stab = stability(ctx, extent, intent)
        ext = ", ".join(sorted(e.split(".")[0] for e in extent)) or "(nothing)"
        itn = ", ".join(sorted(intent)) or "(no attributes)"
        rows.append((ext, itn, supp, stab))
        say(f"  supp={supp}  stab={stab:.2f}   {{{itn}}}")
        say(f"                       <- {{{ext}}}")

    # The concept lattice, drawn with FCA's standard *reduced labelling*:
    # attribute m labels the concept (m', m''), object g labels (g'', g').
    # Each name then appears exactly once, and "object g has attribute m"
    # is read off as "you can walk upward from g's node to m's node".
    attr_at, obj_at = {}, {}
    for i, (extent, intent) in enumerate(concepts):
        for m in ctx.M:
            if frozenset(ctx.closure({m})) == intent:
                attr_at.setdefault(i, []).append(m)
        for g in ctx.G:
            if frozenset(ctx.prime_attributes(ctx.I[g])) == extent:
                obj_at.setdefault(i, []).append(g)
    say()
    say("Reduced labelling (each name introduced exactly once):")
    for i in range(len(concepts)):
        if i in attr_at or i in obj_at:
            say(f"  concept {i}: attributes {sorted(attr_at.get(i, []))}, "
                f"objects {sorted(obj_at.get(i, []))}")

    edges = lattice_cover_edges(concepts)
    br = r"\\\\"  # becomes a LaTeX line break after dot2tex
    lines = ["digraph lattice {", "  rankdir=BT;",
             "  node [shape=box, fontsize=10];"]
    for i in range(len(concepts)):
        parts = []
        if i in attr_at:
            parts.append(", ".join(sorted(attr_at[i])))
        if i in obj_at:
            parts.append(", ".join(sorted(g.split(".")[0]
                                          for g in obj_at[i])))
        if parts:
            lines.append(f'  c{i} [label="{esc(br.join(parts))}"];')
        else:
            lines.append(f'  c{i} [label="", shape=circle, width=0.16, '
                         f"style=filled, fillcolor=black];")
    for i, j in edges:
        lines.append(f"  c{i} -> c{j} [dir=none];")
    lines.append("}")
    write_dot("lattice_travel.dot", "\n".join(lines) + "\n")
    say()
    say(f"Concept lattice written to figures/lattice_travel.dot "
        f"({len(concepts)} nodes, {len(edges)} covering edges).")
    return ctx, concepts


def experiment_2_ontodag_of_the_same_facts():
    rule("EXPERIMENT 2 -- the same facts as an OntoDAG")
    dag = OntoDAG()
    # The categories, as categories -- OntoDAG has no object/attribute split,
    # so an attribute is simply a node like any other.
    dag.put("Japan", ["*"])
    dag.put("Booked", ["*"])
    dag.put("Flight", ["*"])
    dag.put("Hotel", ["*"])
    dag.put("Refundable", ["*"])
    for doc, attrs in DOCS.items():
        dag.put(doc, attrs)

    nodes = [n for n in dag.nodes if n != "*"]
    edges = asserted_edges(dag)
    say(f"nodes = {len(nodes)}   asserted edges = {len(edges)}")
    say()
    say("A query is one intersection of cones:")
    for terms in (["Japan", "Flight"], ["Japan", "Refundable"],
                  ["Flight", "Hotel"], ["Japan"]):
        res = sorted(i.name for i in dag.get(terms))
        say(f"  get({', '.join(terms):<22}) = {res}")

    say()
    say("descendant_count is an exact COUNT(*) per category:")
    for n in ("Japan", "Booked", "Flight", "Hotel", "Refundable"):
        say(f"  |cone({n:<11})| = {dag.nodes[n].descendant_count}")

    lines = ["digraph ontodag {", "  rankdir=BT;",
             '  node [shape=box, fontname="Helvetica"];']
    for n in sorted(dag.nodes):
        # categories drawn with a double border, items with a single one;
        # no colour, so the figure survives greyscale printing
        peri = 2 if (n in ATTRS or n == "*") else 1
        shape = "ellipse" if n == "*" else "box"
        lines.append(f'  "{esc(n)}" [shape={shape}, peripheries={peri}];')
    for p, c in sorted(asserted_edges(dag) |
                       {("*", ch.name) for ch in dag.nodes["*"].neighbors}):
        lines.append(f'  "{esc(c)}" -> "{esc(p)}";')
    lines.append("}")
    write_dot("ontodag_travel.dot", "\n".join(lines) + "\n")
    say()
    say("OntoDAG written to figures/ontodag_travel.dot")
    return dag


def experiment_3_dedekind_macneille(dag):
    rule("EXPERIMENT 3 -- what FCA adds: the Dedekind-MacNeille completion")
    ctx = dag_to_context(dag)
    concepts = next_closure(ctx)
    say(f"OntoDAG nodes (excluding the root)      : {len(ctx.G)}")
    say(f"Concepts of K(G) = (nodes, nodes, reach): {len(concepts)}")
    say()
    say("Every OntoDAG node appears in the completion as a concept whose")
    say("intent is its own reflexive ancestor set. The EXTRA concepts are")
    say("the meets the DAG never named:")
    node_intents = {frozenset(reflexive_ancestors(dag, n)) for n in ctx.G}
    everything = set(ctx.G)
    genuine, bookends = [], []
    for extent, intent in sorted(concepts, key=lambda c: len(c[1])):
        if intent in node_intents:
            continue
        if set(extent) == everything or not extent:
            bookends.append((extent, intent))
        else:
            genuine.append((extent, intent))
    for extent, intent in genuine:
        ext = ", ".join(sorted(extent))
        itn = ", ".join(sorted(intent))
        say(f"  + unnamed meet: everything under {{{itn}}}")
        say(f"                  = {{{ext}}}")
    say()
    say(f"{len(concepts)} concepts = {len(ctx.G)} that are OntoDAG nodes")
    say(f"                + {len(genuine)} genuine unnamed meets")
    say(f"                + {len(bookends)} bookends (the top and bottom a")
    say("                  complete lattice must have, even when nothing")
    say("                  in the data corresponds to them).")
    say()
    say("Each genuine meet is a combination of categories that happens to")
    say("be shared by a set of items, but that nobody asserted as a")
    say("category. FCA materialises them all; OntoDAG materialises none.")

    # A picture of the completion, restricted to the category level: the
    # asserted category nodes in solid boxes, the meets the completion adds
    # in dashed ellipses, drawn as a proper Hasse diagram of intent
    # containment. The documents are left out -- with them the figure is
    # three times as wide and unreadable, and they add nothing to the point,
    # which is where the *unnamed* elements sit.
    elements = {}          # id -> (label, intent, is_meet)
    for n in sorted(ctx.G):
        if n in DOCS:
            continue
        elements[n] = (n, frozenset(reflexive_ancestors(dag, n)), False)
    for k, (_extent, intent) in enumerate(genuine):
        # "$\wedge$" reaches LaTeX intact through dot2tex's raw texmode
        elements[f"meet{k}"] = (r"$\wedge$".join(sorted(intent)),
                                frozenset(intent), True)

    ids = list(elements)
    def below(a, b):        # a is strictly below b: b's intent is a's subset
        return elements[b][1] < elements[a][1]
    covers = [(a, b) for a in ids for b in ids
              if below(a, b)
              and not any(below(a, c) and below(c, b) for c in ids)]

    lines = ["digraph completion {", "  rankdir=BT;", "  nodesep=0.2;",
             "  ranksep=0.4;",
             '  node [shape=box, fontsize=10, margin="0.06,0.03"];']
    for nid, (label, _intent, is_meet) in elements.items():
        shape = "ellipse, style=dashed" if is_meet else "box"
        lines.append(f'  "{nid}" [label="{label}", shape={shape}];')
    for a, b in covers:
        style = " [style=dashed]" if (elements[a][2] or elements[b][2]) else ""
        lines.append(f'  "{a}" -> "{b}"{style};')
    # every asserted category here is maximal, so keep them on one row --
    # otherwise graphviz drops the ones with no edges to the bottom, which
    # reads as if they were the most specific things in the picture
    tops = " ".join(f'"{n}";' for n, v in elements.items() if not v[2])
    lines.append("  { rank=same; " + tops + " }")
    lines.append("}")
    write_dot("dm_completion.dot", "\n".join(lines) + "\n")
    say()
    say("Written to figures/dm_completion.dot (asserted edges solid, the")
    say("meets the completion adds dashed).")
    return concepts


def experiment_4_the_round_trip():
    rule("EXPERIMENT 4 -- codes and DAGs are the same information")
    say("Claim (SEMANTIC_CODES.md Section 2): the family of reflexive")
    say("ancestor sets is a lossless, canonical re-encoding of the DAG.")
    say("Test: build random DAGs, take their codes, rebuild the covering")
    say("relation from the codes alone, and compare with the stored edges.")
    say()
    rng = random.Random(20260806)
    ok = 0
    for trial in range(200):
        dag = OntoDAG()
        n = rng.randint(4, 12)
        names = [f"n{i}" for i in range(n)]
        for i, name in enumerate(names):
            pool = names[:i]
            k = rng.randint(1, 2) if pool else 0
            supers = rng.sample(pool, min(k, len(pool))) or ["*"]
            dag.put(name, supers)
        codes = {x: frozenset(reflexive_ancestors(dag, x)) for x in names}
        rebuilt = codes_to_cover_edges(codes)
        stored = asserted_edges(dag)
        assert rebuilt == stored, (
            f"trial {trial}: rebuilt {sorted(rebuilt)} != stored "
            f"{sorted(stored)}"
        )
        ok += 1
    say(f"{ok}/200 random DAGs: covering relation of code containment ==")
    say("the stored transitive reduction, edge for edge. The two directions")
    say("(DAG -> codes by ancestor closure, codes -> DAG by covering) are")
    say("mutually inverse, so subsumption really is a subset test.")


def experiment_5_the_explosion():
    rule("EXPERIMENT 5 -- why OntoDAG refuses to close: the blow-up")
    say("The contranominal scale N_n = ({1..n}, {1..n}, !=) is the standard")
    say("worst case: every attribute subset is closed, so the lattice has")
    say("2^n concepts for n objects and n attributes.")
    say()
    say("   n   |G|=|M|   concepts   OntoDAG nodes   OntoDAG edges")
    for n in range(1, 13):
        objs = [f"g{i}" for i in range(n)]
        attrs = [f"m{i}" for i in range(n)]
        inc = {f"g{i}": [f"m{j}" for j in range(n) if j != i] for i in range(n)}
        ctx = Context(objs, attrs, inc)
        cs = len(next_closure(ctx))
        dag = OntoDAG()
        for a in attrs:
            dag.put(a, ["*"])
        for i in range(n):
            dag.put(f"g{i}", inc[f"g{i}"] or ["*"])
        nodes = len([x for x in dag.nodes if x != "*"])
        edges = len(asserted_edges(dag))
        say(f"  {n:2d}   {n:5d}   {cs:9d}   {nodes:13d}   {edges:13d}")
    say()
    say("The OntoDAG columns are linear in the data; the concept column is")
    say("not. This is the whole reason OntoDAG stores only what was said.")

    say()
    say("Random contexts (30 objects, 12 attributes, 20 trials each):")
    say("   density   mean concepts   max concepts   OntoDAG edges (mean)")
    rng = random.Random(7)
    rows = []
    for density in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6):
        counts, edgecounts = [], []
        for _ in range(20):
            objs = [f"g{i}" for i in range(30)]
            attrs = [f"m{j}" for j in range(12)]
            inc = {g: [m for m in attrs if rng.random() < density]
                   for g in objs}
            ctx = Context(objs, attrs, inc)
            counts.append(len(next_closure(ctx)))
            edgecounts.append(sum(len(v) for v in inc.values()))
        mean = sum(counts) / len(counts)
        rows.append((density, mean, max(counts),
                     sum(edgecounts) / len(edgecounts)))
        say(f"    {density:4.1f}   {mean:13.1f}   {max(counts):12d}   "
            f"{sum(edgecounts) / len(edgecounts):18.1f}")
    with open(os.path.join(HERE, "explosion.dat"), "w") as fh:
        fh.write("density concepts edges\n")
        for d, mean, _mx, e in rows:
            fh.write(f"{d} {mean} {e}\n")
    say()
    say("Written to experiments/explosion.dat for the plot.")


def experiment_6_meet_trap():
    rule("EXPERIMENT 6 -- OntoDAG is not closed under meets (on purpose)")
    dag = OntoDAG()
    dag.put("A", ["*"])
    dag.put("B", ["*"])
    dag.put("AB", ["A", "B"])
    dag.put("X", ["A", "B"])
    cone_a = {i.name for i in dag.get_descendants("A")}
    cone_b = {i.name for i in dag.get_descendants("B")}
    cone_ab = {i.name for i in dag.get_descendants("AB")}
    say("Put AB under {A, B}. Then put X under {A, B} as well.")
    say(f"  cone(A)          = {sorted(cone_a)}")
    say(f"  cone(B)          = {sorted(cone_b)}")
    say(f"  cone(A) & cone(B)= {sorted(cone_a & cone_b)}")
    say(f"  cone(AB)         = {sorted(cone_ab)}")
    say()
    say("So cone(AB) is a STRICT subset of cone(A) & cone(B): X is under")
    say("both A and B but not under AB. In lattice terms AB is a *sibling*")
    say("of the meet, never the meet itself. A query planner that")
    say("substituted AB for the pair {A, B} would silently lose X.")
    say("In FCA the meet always exists and is the concept with intent")
    say("closure({A,B}); in OntoDAG a named node is only ever what somebody")
    say("said it was.")
    write_dot("meet_trap.dot", (
        "digraph meettrap {\n"
        "  rankdir=BT;\n"
        "  node [shape=box, fontsize=10];\n"
        '  AB [label="AB"];\n'
        '  X  [label="X"];\n'
        "  AB -> A; AB -> B;\n"
        "  X -> A; X -> B;\n"
        '  meet [label="the real meet' + r"\\\\" + '(A and B)", '
        "style=dashed, shape=ellipse];\n"
        "  meet -> A [style=dashed]; meet -> B [style=dashed];\n"
        "}\n"
    ))


def experiment_7_canonical_form():
    rule("EXPERIMENT 7 -- one canonical form, whatever the history")
    facts = [
        ("outbound.pdf", ["Flight", "Japan"]),
        ("kyoto-inn.pdf", ["Hotel", "Japan"]),
        ("Flight", ["Travel"]),
        ("Hotel", ["Travel"]),
        ("Japan", ["*"]),
        ("Travel", ["*"]),
    ]
    rng = random.Random(11)
    signatures = set()
    for _ in range(50):
        order = facts[:]
        rng.shuffle(order)
        dag = OntoDAG()
        pending = list(order)
        # replay in this order, deferring facts whose parents do not exist
        # yet -- the same knowledge, a different history
        while pending:
            progressed = False
            still = []
            for item, supers in pending:
                if all(s == "*" or s in dag.nodes for s in supers):
                    dag.put(item, supers)
                    progressed = True
                else:
                    still.append((item, supers))
            pending = still
            if not progressed:
                for item, supers in pending:
                    dag.put(item, supers)
                break
        sig = tuple(sorted(asserted_edges(dag)))
        signatures.add(sig)
    say(f"50 random build orders of the same six facts produced "
        f"{len(signatures)} distinct graph(s).")
    say()
    say("The single canonical edge set:")
    for p, c in sorted(next(iter(signatures))):
        say(f"    {c}  ->  {p}")
    say()
    say("Note what is NOT there: outbound.pdf -> Travel. It was never")
    say("asserted, and had it been, transitive reduction would have")
    say("dropped it, because Flight -> Travel already implies it.")

    # And the same thing through the persistence layer, if available.
    try:
        from recordstore import RecordStore, MemoryBytesStore
        from ontodag import EagerOntoDAG
    except Exception as exc:  # pragma: no cover - optional dependency
        say()
        say(f"(recordstore not importable here: {exc!r}; skipping the "
            f"root-hash half.)")
        return
    roots = set()
    for _ in range(10):
        order = facts[:]
        rng.shuffle(order)
        store = RecordStore(MemoryBytesStore())
        dag = EagerOntoDAG(store)
        pending = list(order)
        while pending:
            still = []
            progressed = False
            for item, supers in pending:
                if all(s == "*" or s in dag.nodes for s in supers):
                    dag.put(item, supers)
                    progressed = True
                else:
                    still.append((item, supers))
            pending = still
            if not progressed:
                for item, supers in pending:
                    dag.put(item, supers)
                break
        roots.add(dag.commit())
    say()
    say(f"Through the content-addressed store: 10 build orders, "
        f"{len(roots)} distinct root hash(es).")
    for r in roots:
        say(f"    root = {r}")
    say()
    say("That single 32-byte string is the paper's Section 10 in one line:")
    say("equal knowledge, equal address, whoever built it and in whatever")
    say("order.")


def experiment_8_implications():
    rule("EXPERIMENT 8 -- implications FCA would find in the same data")
    ctx = Context(list(DOCS), ATTRS, DOCS)
    say("An attribute implication B -> C holds when every object with all")
    say("of B also has all of C. Here are the non-trivial ones with a")
    say("single-attribute premise, computed by closure:")
    say()
    found = []
    for m in ctx.M:
        cl = ctx.closure({m})
        consequent = cl - {m}
        if consequent:
            found.append((m, sorted(consequent)))
            say(f"  {m:<11} -> {', '.join(sorted(consequent))}"
                f"    (support {len(ctx.prime_attributes({m}))})")
    if not found:
        say("  (none)")
    say()
    say("Read as advice to the ontology: 'Flight -> Booked' says every")
    say("flight in this store happens to be booked. That is a fact about")
    say("today's population, not a rule -- filing one unbooked flight")
    say("destroys it. Section 8.1 of the paper is about exactly this")
    say("distinction, and why such implications belong in a derived,")
    say("local, regenerable layer rather than in the shared graph.")


def experiment_9_certificates():
    rule("EXPERIMENT 9 -- an answer a stranger can check")
    try:
        from recordstore import RecordStore, MemoryBytesStore
        from ontodag import EagerOntoDAG
        from ontodag.certificates import (prove_below, verify_below,
                                          CertificateError)
    except Exception as exc:  # pragma: no cover - optional dependency
        say(f"(skipped: {exc!r})")
        return
    store = RecordStore(MemoryBytesStore())
    dag = EagerOntoDAG(store)
    dag.put("Travel", ["*"])
    dag.put("Flight", ["Travel"])
    dag.put("outbound.pdf", ["Flight"])
    root = dag.commit()
    say(f"root = {root}")

    cert = prove_below(dag, "outbound.pdf", "Travel")
    say(f"certificate format  : {cert['format']} v{cert['version']}")
    say(f"claims              : {cert['sub']} is below {cert['sup']} "
        f"-> {cert['result']}")
    say(f"records proved      : {len(cert['proofs'])}")
    say(f"registry pinned at  : {cert['registry_version']}")

    say()
    say("A verifier holding ONLY the root -- no store, no network -- checks:")
    say(f"  verify_below(cert, root) = {verify_below(cert, root)}")

    say()
    say("Tampering is caught. Flip the claimed answer:")
    forged = copy.deepcopy(cert)
    forged["result"] = False
    try:
        verify_below(forged, root)
        say("  !! forged certificate verified -- THIS WOULD BE A BUG")
    except CertificateError as exc:
        say(f"  refused: {type(exc).__name__}")

    say()
    say("And a negative answer is provable too, in the same way:")
    dag.put("Hotel", ["Travel"])
    root2 = dag.commit()
    neg = prove_below(dag, "outbound.pdf", "Hotel")
    say(f"  {neg['sub']} below {neg['sup']}? {neg['result']} "
        f"(verified: {verify_below(neg, root2)})")
    say()
    say("This is what Section 10 means by 'trust nobody': the answer")
    say("travels, the store does not, and a wrong answer cannot verify.")


def main():
    say("OntoDAG / FCA experiments")
    say("Every number quoted in the paper is produced by this file.")
    experiment_1_running_example()
    dag = experiment_2_ontodag_of_the_same_facts()
    experiment_3_dedekind_macneille(dag)
    experiment_4_the_round_trip()
    experiment_5_the_explosion()
    experiment_6_meet_trap()
    experiment_7_canonical_form()
    experiment_8_implications()
    experiment_9_certificates()
    say()
    say("=" * 72)
    say("All experiments completed.")
    with open(os.path.join(HERE, "results.txt"), "w") as fh:
        fh.write("\n".join(OUT) + "\n")


if __name__ == "__main__":
    main()
