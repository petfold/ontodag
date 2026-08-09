# OntoDAG Reference

Compact, definition-first, no narrative. The story lives in the
[User Guide](USER_GUIDE.md); the *why* in [HOW_IT_WORKS.md](HOW_IT_WORKS.md);
the normative guarantees in [CONTRACT.md](CONTRACT.md). Tables here are
pinned against the code by `tests/test_reference.py` — if a name in this
file and the code disagree, the suite fails.

Versions this file describes: contract `0.1` · registry `4.1` ·
prelude `3` · surface `0.1`.

## 1. Vocabulary

| term | definition |
|---|---|
| item / category | The same thing: a named node. There is no class/instance distinction. |
| name | The identity. Equality of names is equality of nodes, across all stores. |
| edge | Asserted subsumption: parent → child, "child fits within parent". |
| `*` | The root; implicit ancestor of every top-level item. |
| cone | A category's set of descendants (itself included) — a principal down-set. |
| transitive reduction | The unique minimal edge set with the same reachability. Stores hold only this; it is what makes a DAG canonical, diffable, mergeable. |
| canonical name | The one spelling of a parametric value that is stored (`weight(1/2kg)`, never `500g`). Two spellings of one denotation are one identity. |
| denotation | The value set a parametric name stands for; containment of denotations is the computed order. |
| head / kind / family | `weight(3kg)`: head `weight`, declared under a kind node (`linear-dimension`), value in a unit family (`mass`). |
| claim | `sub ⊑ sup` — the subject of provenance records; survives edge pruning. |
| root (store) | Content hash of the whole store; equal content ⇒ equal root, whatever the history. |
| prelude | The standard declarations, adopted by explicit idempotent merge (`odag prelude`). |
| pack | A published ontology meant to be merged (unit vocabularies today). |

## 2. Install

Base install (`pip install ontodag`) is pure Python: the core plus
`recordstore` (canonical roots, snapshots, certificates). Extras:

| extra | adds | for |
|---|---|---|
| `viz` | graphviz, Pillow | `visualize`, images |
| `owl` | owlready2 | `.owl` / `.omn` import and export |
| `store` | recordstore | alias of the base dependency |
| `swarm` | recordstore[swarm-only,local-first-swarm] ≥ 0.19 | `swarm:` stores — local-first: commits land in a store directory instantly (offline works) and sync to Swarm in the background; with a signer the head publishes to a feed after network confirmation |
| `web` | flask, dot2tex, viz, owl | the web app and REST API |
| `all` | everything above | |
| `test` | pytest + viz, owl, store | the suite (deliberately no swarm) |

The dependencies keep their own test-pinned references:
[recordstore REFERENCE.md](https://github.com/petfold/recordstore/blob/main/docs/REFERENCE.md)
and [swarmfs REFERENCE.md](https://github.com/petfold/swarmfs/blob/main/docs/REFERENCE.md);
`docs/recordstore-interface.md` here is only the consumer-side view.

## 3. Query semantics

| operation | answer | notes |
|---|---|---|
| `get(A, B, …)` | intersection of the cones | complete; empty query = everything (the universe) |
| `get_any` / `or` / `\|` | union of intersections (DNF) | `get_any([])` = empty set |
| `is_below(sub, sup)` | Boolean, reflexive, **fail-closed** | asserted edges + computed order, uniformly |
| `get_overlapping(term)` | possibly-satisfies | complete for possibility, silent on satisfaction (G6) |
| `count` | size of the `get` answer | never capped |

Structural invariants (I1–I7, `tests/test_invariants.py`): acyclicity;
transitive reduction; order-independence of `put`; no aliasing between
derived DAGs; exact descendant counts; iterative traversals; `merge`
commutative and idempotent (the CRDT property).

## 4. The `odag` command line

Unix-shaped: silent on success, errors to stderr with non-zero exit,
results one per line on stdout. No command = read commands from stdin
(pipe) or an interactive prompt (tty).

| command | does |
|---|---|
| `put NAME [SUPER…]` | file NAME under the supers (creates as needed at top level) |
| `get [CAT…]` | items below all CATs; `or` separates disjuncts; empty = everything |
| `count [CAT…]` | the same query, as one number |
| `below SUB SUP` | prints `true`/`false`, exits 0/1 (grep-style); alias `?` at the prompt |
| `overlapping TERM` | items that *might* satisfy a typed term — candidates whose value overlaps it (G6). A term of no declared dimension is an error, not an empty answer |
| `list` | everything (same path as the empty `get`) |
| `show` | the whole DAG as indented text |
| `move NAME… --to CAT… [--from CAT…] [--dry-run]` | reclassify: assert the new categories, retract the old ones (`--from` omitted = all of them, so `--to` alone means "under this and nothing else"; `--to` omitted = unfile, becoming top-level). Reports the **contested set** — items now under both the old and new category, which subsumption cannot resolve |
| `remove NAME… [--cone] [--dry-run]` | contract: the items go, their children reattach to their parents (order-independent, so several at once is a function of the set). `--cone` deletes instead: each item plus whatever only existed under it, sparing cone members that hang elsewhere |
| `merge PATH` | merge another store/file into this one |
| `import` / `export PATH` | native `.od`, or OWL/Manchester by extension (`.owl`/`.omn`) |
| `excerpt PATH [CAT…] [--context]` | write just that query's answer (with the edges among the answers) to PATH — an importable cut; FILE comes first because CATs are variadic. `--context` adds the categories the answers hang from, which is what makes the file merge *and* diff into another store |
| `diff OTHER [CAT…] [--additions PATH]` | compare this store with OTHER: `+` is theirs, `-` is ours; exits 0 identical / 1 different. Claims decide what is reported, edges display it; cascade counts on stderr. `--additions` writes OTHER's additions as a store file `merge` applies — never removals, and it says how many it left out |
| `visualize [CAT…] [--out NAME]` | render an image (needs the `viz` extra); with CATs, draws that query's answer under its terms — the drawn twin of `excerpt`, which omits them |
| `canon [TERM]` | the stored (canonical) form of TERM; bare: surface+registry versions |
| `prelude [--show]` | adopt (or preview) the standard declarations |
| `pack [NAME] [--show]` | adopt (or preview) a shipped vocabulary pack |
| `index` | publish cone summaries for the current store |
| `history [-n N]` | the states this store has been in, newest first (`*` = where it is now); needs `rs:`/`swarm:` |
| `status` | store, root, item count, and how much can be undone/redone |
| `undo` / `redo` [--dry-run] | step back / forward one state; the pointer moves, nothing is destroyed |
| `set [KEY [VALUE]]` | show or persist a setting (table below) |
| `swarm` | doctor: is a Bee node reachable and usable, step by step |
| `help` | the built-in help text |

**Exit codes**: 0 success; 1 error (and `below`'s "false").

**Settings** — one precedence rule: **flag > environment > config file >
default**. `auto` means "decide from whether output is a terminal".

| key | env | flag | default |
|---|---|---|---|
| `store` | `ONTODAG_STORE` | `-f PATH` | `~/.ontodag/store.od` |
| `bee_api` | `BEE_API` | `--bee-api URL` | `http://localhost:1633` |
| `bee_batch` | `BEE_BATCH` | `--bee-batch ID` | (unset) |
| `bee_signer` | `BEE_SIGNER` | `--bee-signer KEY` | (unset; secret — never echoed) |
| `render` | `ONTODAG_SURFACE` | `--render` / `--raw` | `auto` |
| `limit` | `ONTODAG_LIMIT` | `-n N` | `auto` (50 at a tty, all in a pipe, 0 = all) |

**Two pre-command flags are not settings.** `-m MESSAGE` labels whatever state
this invocation commits, readable back with `odag history`; the label lives in
the store's timeline and never in the root, so equal content commits to equal
roots whatever the words. `--as-of ROOT` reads a *past* version instead of the
current one — any unambiguous prefix `odag history` prints — and is read-only,
since a past state is history rather than a place to write from (`undo`/`redo`
are how the store moves). Both need a store that keeps versions (`rs:`/`swarm:`).

**Store specs** (for `-f`, `$ONTODAG_STORE`, `set store`):

| spec | is | gives |
|---|---|---|
| a path (`.od`) | native text file | a DAG that persists; zero dependencies |
| `rs:PATH` | local record store | canonical roots, snapshots, certificates, sync — no node |
| `swarm:NAME` | Swarm-backed store | the same, shared; root in a signed feed when a signer is set |

**Output rule**: canonical bytes whenever stdout is not a terminal
(`odag get \| odag put` round-trips); readable rendering at a tty.
Input is elaborated regardless.

## 5. Python API

```python
from ontodag.dag import OntoDAG          # always available, no extras
```

| method | one line |
|---|---|
| `put(name, supers, optimized=False)` | file under supers (strings or Items) |
| `get(terms)` / `get_any(queries)` | intersection / union-of-intersections; returns Items |
| `get_by_dag(query_dag)` | intersect against another DAG's categories (the web app's path) |
| `is_below(sub, sup)` | reflexive, fail-closed Boolean |
| `get_overlapping(term)` | possibly-satisfies candidates |
| `get_descendants` / `get_ancestors` | one cone, either direction |
| `remove(name)` | remove with contraction (children keep coarser parents) |
| `reclassify(names, to, from_=None)` | assert new classifications, retract old ones; asserts before retracting, never orphans, and refuses any placement `put` would refuse |
| `cone_removal_plan(names)` / `remove_cone(names)` | the *deleting* removal: the categories plus whatever only existed under them; a cone member that hangs elsewhere survives. The plan is pure, so it can be previewed |
| `merge(other)` | commutative, idempotent union with re-reduction |
| `copy_subdag` / `induced_subdag` / `intersection_dag` / `prune_to_common_descendants` | derived DAGs, never aliasing (`copy_subdag` closes downward, `induced_subdag` copies exactly the names given) |
| `excerpt(queries, context=False)` / `excerpt_names(...)` | a query's answer as a standalone DAG (query terms never added; `context` also brings the categories it hangs from) |
| `contested(a, b)` | items below both — the two-states-at-once list; empty when one entails the other |

Comparing two stores (`from ontodag.compare import compare` — an opt-in
consumer, imported by nothing in the core):

| call | one line |
|---|---|
| `compare(ours, theirs, queries=None)` | → `Comparison`; `queries` (DNF) scopes both sides to the set an `excerpt --context` would take |
| `Comparison.only_ours` / `.only_theirs` | items one side has and the other does not |
| `Comparison.added` / `.removed` | claim changes about items both sides have, as `(sub, sup)`; a re-routed edge is **not** reported |
| `Comparison.entailed_added` / `.entailed_removed` | the cascade — every claim gained/lost in scope (computed on first access) |
| `Comparison.additions()` | their additions as a DAG `merge` applies; merging it reaches the same root as merging their whole store. Never removals |
| `bool(Comparison)` | whether anything differs |
| `topological_sort()` | deterministic (sorted) order |
| `add_node` / `add_edge` / `remove_edge` | low level; `remove_edge` can orphan — prefer `remove`/`put` |

Persistence adapters (all reachable as `ontodag.X`, imported lazily):

| class | residency | writes | for |
|---|---|---|---|
| `EagerOntoDAG(store)` | full hydration | yes, `commit()` diffs | canonical roots, `sync(other_root)` multi-writer merge (diff-driven: reads the divergence, not the store) |
| `LazyOntoDAG(store)` | fetch-as-walked | read-only | querying a published store at query cost; `as-of` via `store.at(root)` |
| `SparseOntoDAG(store)` | resident set | yes | writing into a large store without hydrating it; `sync(other_root)` folds a peer at divergence cost (store must sit at the writer's own lineage) |

Related modules: `ontodag.prelude` (`apply(dag)`), `ontodag.packs`
(`crypto-core`, `crypto-majors`, `stablecoins`, `fiat-iso4217`),
`ontodag.surface` (`render`/`elaborate`; law `elaborate(render(t)) == t`),
`ontodag.cones` (published cone summaries), `ontodag.certificates`
(`prove_below`/`verify_below` — self-contained proofs against a root),
`ontodag.provenance` (signed claim records), `ontodag.migrate`
(replay a store across registry majors), `ontodag.OWLOntology` (OWL).

## 6. Dimensions (typed values)

A head is declared by one edge to a kind node; values are parametric
names; the order *within* a dimension is computed from names, never
stored as edges. Registry `4.1`; same major = same arithmetic.

| kind node | values | order | example |
|---|---|---|---|
| `linear-dimension` | exact rationals of the family anchor; ranges `lo..hi`, either end open | interval containment | `weight(..5kg)` contains `weight(3kg)` |
| `calendar-dimension` | `2026`, `2026-08`, `2026-08-15`, timestamps; ranges | period containment | `time(2026)` contains `time(2026-08)` |
| `count-dimension` | whole numbers ≥ 1; ranges (floor 1) | interval containment | `count(2..)` contains `count(24)` |
| `prefix-dimension` | path strings | prefix | `geo(u2)` contains `geo(u2ed)` |
| `dominance-dimension` | sorted tuples `AxBxC` + unit | componentwise ≥ | `size(20x30x40cm)` contains `size(19x23x39cm)` |

Rules that refuse, with teaching errors: cycles; a point filed under two
provably disjoint values of one head; `count(0)` (an absence claim);
fractional counts; negatives (except affine `C`/`F` spellings); values
below absolute zero; unknown units (the error names the pack or
declaration that would define them); a head inheriting two kinds.

Unit vocabulary: ~250 built-in suffixes (physical/digital measurement
only — generated listing in [UNIT_TABLE.md](UNIT_TABLE.md)); everything
market-shaped ships as packs; graph-declared units via
`unit(NAME=VALUE)` / `unit-family(NAME)` nodes under `unit-declaration`
travel with the store.

Prelude v3 declares: the five kind nodes and heads `weight`, `length`,
`duration`, `area`, `volume`, `speed`, `pressure`, `temperature`,
`energy`, `count`, `time`, `geo`, `size`.

## 7. REST API (`web/`, needs the `web` extra)

Whole-DAG and query variants; `cat` takes `,` for AND and `|` for OR;
empty `cat` = everything.

| endpoint | methods | does |
|---|---|---|
| `/dag` | GET, POST | dump / reset |
| `/dag/node` | POST, DELETE | put / remove |
| `/dag/query?cat=A,B\|C` | GET | query (DNF) |
| `/dag/below?sub=&sup=` | GET | Boolean containment |
| `/dag/image`, `/dag/query/image` | GET | rendered PNG |
| `/dag/import`, `/dag/query/import` | POST | native/OWL upload |
| `/dag/export[/omn\|/dot\|/tex]` | GET | exports of the whole DAG |
| `/dag/query/export[/omn\|/dot\|/tex]` | GET | export of the query's **excerpt** — `?cat=` (DNF) and `?context=1`; never the picture, so it re-imports without the query terms |
| `/dag/node` | PATCH | reclassify: `{subcategories, to, from}`; answers with `retracted` and the `contested` set |
| `/dag/node?cone=1` | DELETE | delete the items and whatever only existed under them; answers with `deleted` and `kept` |
| `/dag/removal?name=…&cone=1` | GET | what that delete would take, without taking it |
| `/dag/overlapping?term=…` | GET | candidates whose value merely overlaps the term (G6) |
| `/dag/canon[?term=…]` | GET | what a spelling stores (`canonical` + `display`); bare: surface/registry versions |
| `/dag/prelude` | GET / POST | preview / adopt the standard dimension declarations — **typed values need this first on this surface** |
| `/dag/pack` | GET / POST `{name}` | list / adopt a unit vocabulary pack |
| `/market`, `/cars…` | GET | the car-market demo |

Serving the page (all read-only except the console and the example):

| endpoint | methods | does |
|---|---|---|
| `/dag/console` | POST `{line}` | run one `odag` command line; answers `{out, err, code}` plus the page's state. **Allow-listed** — the 13 commands that neither touch a filesystem path nor need a store with versions |
| `/dag/commands` | GET | every OntoDAG command with its description, argument shape, group and `available`/`why` — read off the argparse parser, so it cannot drift |
| `/dag/browse?cat=` | GET | the answer plus `refine`: the categories held by *some but not all* of it, each with the count clicking it returns |
| `/dag/node/<name>` | GET | one node: parents, children, count, rendered *and* canonical name |
| `/dag/names?prefix=` | GET | names, for completion |
| `/dag/picture[?cat=\|?focus=&depth=]` | GET | `{svg, ids}` — inline SVG plus the map from shape id back to name, which is what makes the drawing clickable |
| `/dag/example` | POST | load the worked example, with the prelude its typed values need |
| `/classic` | GET | the previous page, unchanged |

The web DAG is server memory per session — not your `odag` store.

## 8. MCP agent surface (`odag-mcp`)

Read tools: `about` (the discoverability record), `query` (`terms` xor
`any_of`, explicit `limit`, answers carry `truncated` and complete
`count`), `is_below` (accepts `certify: true` → a verifiable
certificate), `overlapping`, `describe`, `canon`, `review` (per-claim
audit: every record signature-verified, standing from verified records
only, reader-side `trust`). Write tools (`--write`, signer required,
`swarm:`/`rs:` stores only): `propose_put`/`put`,
`propose_remove`/`remove` (compare-and-confirm via a proposal token
bound to the current root), `endorse`/`retract` (signed speech acts).
Every answer cites its root and contract version; canonical names
throughout, `display` beside them.

## 9. Formats and proofs

| artifact | format |
|---|---|
| native store | `.od` text, sorted, one node per line — diffable |
| OWL / Manchester | `.owl` / `.omn` by extension, via the `owl` extra |
| store root | 64-hex content address; equal content ⇔ equal root |
| certificate | JSON envelope of authenticated records; `verify_below(cert, root)` needs no store access |
| provenance record | signed JSON (`v`, subject hash, basis root, `ext` map), content-addressed under `s/<subject>/<record>` |

## 10. Where the rest lives

| document | job |
|---|---|
| [USER_GUIDE.md](USER_GUIDE.md) | tutorial and how-to, with executed snippets |
| [HOW_IT_WORKS.md](HOW_IT_WORKS.md) | explanation — the ideas and why |
| [CONTRACT.md](CONTRACT.md) | normative guarantees G1–G6, as-of semantics |
| [PROVENANCE.md](PROVENANCE.md) | the attribution design (agreed) |
| [AGENT_SURFACE.md](AGENT_SURFACE.md) | MCP surface design record |
| [DIMENSIONS.md](DIMENSIONS.md), [UNITS.md](UNITS.md) | dimension and unit design records |
| [SWARM_DESIGN.md](SWARM_DESIGN.md) | persistence architecture |
| [UNIT_TABLE.md](UNIT_TABLE.md) | generated: every unit spelling |
| [plans/](plans/) | discussion drafts, future features, directions — nothing in there is shipped |
