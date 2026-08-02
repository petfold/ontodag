# The Surface Layer: Messy Input, Readable Output, an Exact Core

Status: **discussion draft, 2026-08-01 (Peter + Claude)** — though no longer
"nothing implemented": **§10 steps 1–2 shipped later the same day**
(`ontodag.surface`, the CLI's §9.4 pipe rule, `odag canon`; see §10 for what
exactly). Everything not marked decided or done remains discussion. This
document exists to be argued with. It was prompted by
the `time(2026)` question — whether a bare year should be read as a year — and
by the observation that the honest answer is not about that one literal but
about where messiness is allowed to live. Open questions are collected in §9
rather than resolved inline; §10 sketches a sequence *if* we decide to do this.

**Part II (§11–§14)** collects wider questions Peter raised while reading Part
I: that the surface layer is not separate software from OntoDAG and should be
built out of it where it can be (§11, which corrects §3); multilingual naming
(§12); how far OntoDAG should travel toward knowledge representation and
inference, and what belongs in a higher layer instead (§13); and what role a
canonical, verifiable store plays in a world of AI agents (§14). Those last two
are bigger than a rendering layer and may want their own documents once they
have shape.

**Update 2026-08-01 (later the same day).** The strategy discussion happened,
and Part II got its outcomes: **agents-first is agreed** as the priority
(§14), §13 grew into the predicted standalone document — `CONTRACT.md`, which
sharpens its criterion into two axes and adds the as-of/root-pinning clause
and a verifiability section — and §14's provenance prerequisite became the
design note `PROVENANCE.md`. Positions were also recorded (not decided) on
the remaining §9 questions and on §12's fork; they are marked inline below.
The working plan is in `ROADMAP.md` ("Next up") and `CLAUDE.md`.

Read `DIMENSIONS.md` first for the canonical-form discipline this must not
break, and `SEMANTIC_CODES.md` §9 for the precedent of a derived, local,
never-merged layer — which is exactly the category this belongs to.

## 1. The problem, stated once

Three complaints, one shape:

- `time(2026)` looked like it should obviously mean the year. Making it mean
  that required declaring a `calendar-dimension`, because in a linear
  dimension a bare integer is a dimensionless count.
- The canonical form is unreadable. `odag show` prints
  `time(2026-01-01T00:00:00Z..2026-12-31T23:59:59Z)` where a person wants
  `time(2026)`.
- Filing a first date costs three registry `put`s before anything works.

None of these are bugs in the core. They are all the same missing thing: **the
core is the only layer, so it has to be both the exact substrate and the human
interface, and those two jobs want opposite properties.**

## 2. What the core must keep

Non-negotiable, because the persistence and multi-writer story rests on it:

> The map from **stored canonical name** to **denotation** is identical on
> every replica, and depends only on (a) declarations that are themselves part
> of the merged graph and (b) a pinned `REGISTRY_VERSION`.

Everything the core rejects today, it rejects because guessing would put two
honest replicas into disagreement about what a stored name means. That is the
one failure this system cannot absorb: it breaks canonical roots, and canonical
roots are what make the store diffable, mergeable and content-addressable.

Note what this rule does *not* say. It does not say interpretation is
context-free — it never was. `contains(outer, inner, kind)` has always taken
the kind, resolved by an ancestor walk in the graph, and `weight(3kg)` has
always needed the unit table. The rule is about *which* context: **context that
merges**.

## 3. The two layers

```
    what a person types  ──elaborate──▶  canonical term  ──▶  core (exact)
    what a person reads  ◀───render────  canonical term  ◀──  core (exact)
```

The surface layer is that pair of functions. It is:

- **Derived** — computable from the canonical data plus the declarations; it
  stores nothing of its own.
- **Local and per-user** — my renderer may be friendlier than yours without us
  disagreeing about any fact.
- **Never merged** — it is not in the asserted graph and never travels with it.

That triple is not new. Cone indexes are derived-local-never-merged; so is the
materialization layer of `SEMANTIC_CODES.md` §9. This is the third instance of
a pattern the project already has a category for.

**But the triple is too simple, and §11 corrects it.** Part of what this layer
needs — that `weight` is a linear dimension, that `vol` is another name for
`Flight` — is knowledge, and knowledge merges. The honest split is *shared
vocabulary in the graph, local policy outside it*; see §11.

**Half of it already exists.** Canonicalization *is* elaboration:

```
time(2026)                    →  time(2026-01-01T00:00:00Z..2026-12-31T23:59:59Z)
time(2026-01-01..2026-12-31)  →  the same string, byte for byte
```

Two spellings of one denotation collapse to one identity. What is missing is
the other direction, and any notion that the input direction is a *layer* with
a contract rather than a few `if` branches inside the parser.

## 4. The round-trip law

The property that makes rendering safe to add, and that should be fuzz-tested
the way the trie already is:

> For every canonical term `t`: `elaborate(render(t)) == t`.

Rendering may be pretty; it may not be lossy in a way that changes denotation.
`render` is a *pure function of the canonical name* — never of what someone
originally typed.

That last clause has a consequence worth stating, because the alternative is
tempting: **do not store the user's spelling.** Keeping "they typed `2026`" in
`meta` would put it in the record, hence in the root, and two people who filed
the same fact by different spellings would get different roots. Intent must be
*recomputed* structurally (a range that exactly spans a calendar period renders
as that period), not remembered.

Three sharpenings from the 2026-08-01 discussion:

- **Policy picks, vocabulary defines.** The law interacts with local policy:
  if my renderer prefers `weight(3lb)`, elaboration must be able to read
  `lb` — and that unit table is *shared vocabulary* (§11), not policy. So:
  rendering policy may only choose among spellings the shared vocabulary
  already defines, never invent one. That is what makes `--render` output
  safe to hand to a user with different preferences — same vocabulary, same
  canonical result. Without this clause the law can hold on my machine and
  fail on yours.
- **Injectivity per context.** The law requires `render` to be injective on
  canonical terms: it may collapse a range to `time(2026)` only when the
  span is *exact*. The almost-a-year range is the fuzz case that matters.
- **The non-law.** `render(elaborate(s)) == s` is deliberately **not**
  promised — the user's spelling normalizes away, per the paragraph above.
  Stated so nobody "fixes" it later. The fuzz test therefore runs in one
  direction (canonical → surface → canonical) plus a determinism check on
  elaboration, never the other round trip.

## 5. Input side: elaboration

Because the core validates everything, the surface can afford to be liberal.
The contract that keeps that safe:

1. **Propose, don't decide.** Elaboration returns a canonical candidate.
2. **Validate.** The candidate goes through the ordinary core parse. There is
   no path by which the surface writes something the core would have refused.
3. **Show, and confirm when ambiguous.** Unambiguous sugar (`2026-W32`) can
   pass silently. Anything with more than one reading is displayed as its
   canonical expansion before it is stored.
4. **Never store the ambiguity.** What lands in the graph is the expansion.

Candidate sugar, in rough order of "obviously fine" to "needs a decision":
ISO weeks and quarters (`2026-W32`, `2026-Q3`); open-ended shorthands;
`today`/`yesterday`; relative ranges (`last summer`); free text.

Note where the line naturally falls: everything up to `today` is a *pure
function of the input string*; `today` needs a clock, and `last summer` needs a
clock and a convention. Clock-dependent input is the first place where two
users typing the same characters store different data — not corruption, but
worth an explicit decision (§9.3).

**Time zones (position recorded 2026-08-01, prompted by Peter).** A bare
date is genuinely ambiguous: "2026-08-01" is a different set of instants
in Vienna than in Tokyo, and in a DST-shift zone the civil day is 23 or
25 hours long. The core currently resolves bare dates as the UTC day by
fiat — deterministic, sometimes not what the human meant. The right home
for local-time interpretation is exactly this layer, under the §4 rule
(policy picks, vocabulary defines):

- **Default = local time is a legitimate elaboration policy**, with an
  explicit-zone spelling for overrides. The zone-dependence must die at
  input: elaboration resolves the civil day to a concrete UTC interval
  and only that canonical name is stored. Two users meaning different
  civil days SHOULD store different names — that is correctness. What
  may never happen is the zone reaching stored semantics, so the same
  bytes read differently in different places.
- **tzdata mutability is contained by this placement**: IANA tables
  (stdlib `zoneinfo`; `timezonefinder` for zone *shapes* from
  coordinates) are consulted once, at elaboration; an already-stored
  interval is immune to later table changes. This is the same move as
  the §13-of-DIMENSIONS wall on political zones — the table never
  touches canonical arithmetic.
- **The residue is cross-zone querying**: a Tokyo query for
  "2026-08-01" won't exactly match Vienna filings of the "same" day.
  Reality, not a bug; `get_overlapping` is the honest tool.

## 6. Output side: rendering

The cheapest win and the least dangerous change, because output cannot corrupt
anything. Recognize structure in canonical names and print the friendly form:

| canonical | rendered |
|---|---|
| `time(2026-01-01T00:00:00Z..2026-12-31T23:59:59Z)` | `time(2026)` |
| `time(2026-08-01T00:00:00Z..2026-08-31T23:59:59Z)` | `time(2026-08)` |
| `weight(3000000mg)` | `weight(3kg)` |

(Historical note, 2026-08-01 evening: registry v3 — `UNITS.md` D9 — moved
canonical values to rationals of the SI anchor, so the weight row now reads
`weight(1/2000kg)` → `weight(500g)`; `weight(3kg)` became its own canonical
spelling. The law and the layering are unchanged.)

The weight row shows this is not a calendar feature: "render friendly units" is
already noted as UI work in `dimensions.py` and has never been done.

Consequence to accept up front: the same node is now printed differently by
different tools and versions. That is fine for reading and **not** fine for
anything that compares text. So rendered output must never be what gets
diffed, hashed, or piped into another `odag`, which leads directly to §7.

## 7. Who sees which layer

Peter's requirement, and I think it is the right one: *both, always
reachable.* Not a friendly tool and a separate expert tool — one tool with an
honest switch.

- **Python.** The core API keeps taking and returning canonical names. A
  separate `ontodag.surface` module offers `elaborate()` and `render()`, opt-in
  by import. The core must never call it — that keeps `B1` intact and keeps the
  library predictable for people building on it.
- **CLI.** Friendly by default, with a global `--raw` (and `ONTODAG_SURFACE=0`)
  that turns both directions off. Plus a `canon TERM` command that prints what
  a surface term elaborates to, so the mapping is inspectable rather than
  folklore — the single most useful debugging affordance here.
- **Piping — decided (2026-08-01).** Both halves of the choice, which turn out
  to compose rather than compete: **canonical whenever stdout is not a
  terminal**, and **rendering opt-in** when it isn't. So

  | stdout | default | override |
  |---|---|---|
  | a terminal | rendered | `--raw` for canonical |
  | a pipe, a file, `-o FILE` | canonical | `--render` to force friendly |

  The precedence is flag, then `$ONTODAG_SURFACE` (`0`/`1`/`auto`), then the
  tty test — `ls --color=auto` and `git`'s pager use the same shape, so it is a
  convention people already have. `odag get | odag put` round-trips by default;
  `odag get --render | grep` is available and is the user's explicit choice to
  break that, exactly as `ls --color=always | grep` is.

  Three consequences worth writing down:

  - **The rule is output-only.** `put` and `get` accept surface *input*
    regardless of where stdout goes; elaboration is never conditioned on a tty.
  - **stderr always renders.** Diagnostics are for people and nothing parses
    them — but that does mean an error can name a term in a spelling that
    differs from the stored one, so error text should show the canonical form
    too when the two differ.
  - **Testing needs a real pty**, not just a flag, or the default path goes
    unexercised. There is already precedent for driving `odag` under a pty.
- **Web/REST.** Return both: canonical as the field, rendered as a sibling
  display field. The UI shows one and sends back the other.

## 8. LLM elaborators

Peter raised a locally-running LLM as a future surface. Taking it seriously is
useful precisely because it is the extreme case, and the extreme case is what
tells you whether the contract is right.

An LLM is just an elaborator with a very wide input domain: natural language in,
candidate canonical terms out. Under §5 it is admissible **only** because its
output is validated by the core and confirmed by the user before storage. It is
non-deterministic and unversioned, so it can never sit inside the hard layer —
but it does not have to, and that is the point: *the surface contract is what
makes it pluggable later without the core learning it exists.*

Why local specifically matters: privacy (your ontology is your filing cabinet),
offline operation, and the fact that a remote shared model would not be
reproducible either, so it buys nothing on determinism and costs
confidentiality.

Two asymmetric uses, worth separating:

- **Input** (text → terms) is the risky one and needs confirm-before-store.
- **Output** (summarizing a cone, naming a cluster, explaining why something
  matched) touches nothing and is a genuinely low-risk place to start.

There is a third, further out and more interesting: an LLM proposing *category
structure* rather than terms. That is the `mdl-fca` provenance question
(`asserted` vs `derived`) and belongs to that discussion, not this one.

## 9. Open questions

Positions recorded 2026-08-01 (from the strategy discussion) are marked
*Position:* — they are recommendations on the record, not decisions.

1. **Is the calendar kind still the right shape** if a surface layer exists? A
   richer surface reduces the pain of declaring kinds but does not remove the
   ambiguity that made the kind necessary. My current view: the kind stays, and
   the surface makes it cheaper to live with — but this is worth attacking.
   *Position: the kind stays. It was never about parsing — a calendar year
   denotes a range and has irregular arithmetic; no surface can make that
   ambiguity go away, only make declaring it cheap.*
2. **Declaration ceremony.** A `declare` shorthand, an opt-in prelude of
   standard dimensions, or auto-declare-on-first-use-with-confirmation? A
   prelude changes the canonical root of a "fresh" store, so it cannot be the
   default without thought.
   *Position: the prelude should be a **published ontology with a well-known
   root, adopted by explicit `merge`** — not a config default. Merge is
   idempotent and canonical, so everyone who adopts prelude-vX converges; the
   root change becomes a feature (adoption is explicit, versioned, visible in
   the fingerprint). This is simultaneously the upper-ontology answer from
   the issues list: don't bake one in, publish optional vocabularies as
   stores and let people merge them. One mechanism, three problems.*
   **Implemented (2026-08-01):** `ontodag.prelude` + `odag prelude [--show]`
   — the kind registry plus six everyday heads, adopted by idempotent merge,
   with prelude v1's canonical root pinned by a golden test
   (`tests/test_prelude.py`), so "prelude v1" *is* a specific fingerprint.
   Publishing it as a Swarm store others `sync` is the same move one
   deployment step later.
3. **Clock- and locale-dependent input** (`today`, local dates vs UTC). Accept
   with explicit expansion shown, or refuse? Bare dates are UTC days in the core
   today; a surface that accepts local dates lets two users store different
   facts from identical keystrokes.
   *Position: accept **interactively only** (stdin is a tty), with the
   canonical echo on screen; refuse in batch/pipe mode without an explicit
   flag. Mirrors the §9.4 output rule exactly — liberal where a human is
   present to see the expansion, strict where a script runs blind.*
4. ~~**Pipe semantics** (§7).~~ **Decided 2026-08-01: both.** Canonical
   whenever stdout is not a terminal, *and* a `--render` opt-in for when it
   isn't; `--raw` forces canonical on a terminal. Table and consequences in
   §7. This was the only thing blocking the renderer (§10.1).
   *Extended 2026-08-02: the rule turned out to generalize past spelling.*
   When the empty query became the universe (`odag get` with no terms), a
   terminal needed protecting from a whole-store dump — and the answer was
   the same rule again: cap at 50 lines when stdout is a tty, never in a
   pipe, `-n N` / `-n 0` to override, withheld count on stderr. So §7 is
   better read as a rule about **audience** than about rendering: a
   terminal gets output shaped for a person, everything else gets the
   complete canonical answer. The two settings (`render`, `limit`) share
   the `auto` default and the same precedence chain, which is now the
   general settings rule (flag > env > config > default) rather than a
   surface-layer special case. Note the agent surface deliberately
   diverges: MCP `query` has no default cap, because a caller that cannot
   see a terminal cannot see a truncation either — it must opt in and is
   told (`truncated`, with `count` still complete). See `AGENT_SURFACE.md`
   §2.
5. **Surface versioning.** The surface needs its own version, separate from
   `REGISTRY_VERSION` — rendering changes are harmless, but changing elaboration
   changes what identical input stores. Does that version need to appear
   anywhere, or is it purely informational?
   *Position: purely informational — nothing in the graph. But `odag canon`
   should print it and the confirm echo should carry it.*
6. **Scope.** Does the surface layer cover only dimension values, or names in
   general — aliases, spelling, language? The roadmap's "Namespaces" item
   (reconciling different people's naming) is the same shape of problem and may
   want to land here rather than beside it.
   *Position: dimension values only in v1. Aliases and languages are
   knowledge by §11's own criterion, and belong to §12/Namespaces — don't let
   the renderer grow a lexicon.*
7. **Where does it live?** A module in `ontodag`, or its own package? An LLM
   elaborator is certainly an optional extra; the pretty-printer probably is
   not.
   *Position: `ontodag.surface` in-package (the renderer is dependency-free);
   the LLM elaborator a separate package or extra, behind the same contract.*
8. **The legacy time-under-`linear-dimension` path.** Leave it, warn on it, or
   refuse `linear:time` at put time? Today it works until you type a bare year.
   *Position: warn at **declaration** time (`put time linear-dimension` is
   the mistake moment), refuse nothing.*

## 10. Possible sequencing (only if we decide to do this)

Ordered so each step is independently useful and none blocks a later one:

1. ~~**Renderer + round-trip fuzz test**~~ **Done (2026-08-01):**
   `src/ontodag/surface.py` — `render()`/`elaborate()` plus
   `SURFACE_VERSION`, a pure function of the canonical name and the declared
   kind (opaque heads pass through untouched, or the law would break on
   them; §4's sharpenings implemented: only vocabulary-defined spellings are
   emitted, collapses only on exact denotation match). The CLI follows the
   §9.4 table exactly (per-command `--render`/`--raw` > leading global flag
   > `$ONTODAG_SURFACE` > tty test on the actual output stream, so `-o FILE`
   is canonical). Tests: `tests/test_surface.py` — the §6 table, a seeded
   one-direction fuzz (`elaborate(render(t)) == t` across all four kinds),
   the almost-a-year injectivity guard, the CLI rule including a **real pty**
   for the tty default, and a boundary check that the core never imports the
   surface.
2. ~~**`odag canon TERM`** and `--raw`.~~ **Done (same commit):** `canon TERM`
   prints the stored form of any spelling (malformed parameters raise the
   core's teaching error, exit 1); `canon` with no term prints the surface
   and registry versions — the §9.5 position, implemented.
3. **Pure-function input sugar** — weeks, quarters. No new machinery.
4. **Declaration ergonomics** (§9.2), which is what would let dates appear in
   the User Guide's Quick Start.
5. **Clock-dependent input**, if §9.3 says yes.
6. **LLM elaborator** as an optional extra, behind the same contract.

Steps 1–3 are small and self-contained. Step 4 is the one with real design
content left in it. Steps 5–6 should not be started until the contract has been
exercised by 1–4.

---

# Part II — wider questions this opened

Raised by Peter, 2026-08-01, while reading Part I. They are recorded here
because the surface-layer discussion produced them, but §13 and §14 are plainly
bigger than a rendering layer and may deserve their own documents once they
have shape. **None of these are answered here on purpose.**

## 11. The surface layer is not separate software

The observation that reframes Part I: **the interpreter is already partly made
of OntoDAG.** `time(2026)` is resolved by an ancestor walk to a kind node — the
registry is not a config file, it is nodes and edges in the graph, read with
the graph's own primitive. The dimension declarations *are* interpreter
configuration expressed as data.

So the default should invert. Not "build a surface layer beside OntoDAG", but
**do as much of it in OntoDAG as OntoDAG can express**, and treat anything else
as a departure that has to justify itself. What that buys is not elegance for
its own sake: interpreter configuration then merges with the data, is versioned
with it, is queryable with the one primitive, and is inspectable with `show`. A
store carries its own reading instructions, which is exactly what you want when
the store outlives the tool that wrote it.

This contradicts §3's "never merged", and the fix is a sharper line:

| | example | where it lives |
|---|---|---|
| shared **vocabulary** | `weight` is a linear dimension; `vol` is another name for `Flight`; a boarding pass is a travel document | in the graph, merges |
| local **policy** | display in French; prefer `kg` to `mg`; collapse aligned ranges to periods; verbosity | outside, never merges |

The criterion: **claims about the world merge; preferences about presentation
do not.** A synonym is a claim — someone is asserting two names denote the same
category, and someone else may disagree. "Show me French" asserts nothing.

The genuine departure is the LLM (§8, §14): a separate mechanism, and one that
must stay **optional and never a dependency** — the same boundary `B1` already
draws around Swarm. The core must remain fully functional, and fully useful,
with no model present.

Open: how much of *rendering policy* could also be graph-expressed without
merging it — a locally-held OntoDAG of preferences, using the same code, kept
in a separate store the way cone indexes are? That would make the surface layer
"OntoDAG all the way down" without putting preferences into shared data.

## 12. Languages

Two problems wear the same clothes:

1. **The fixed vocabulary** — command names, kind names, error text. Ordinary
   i18n, not an OntoDAG question. Though note the registry's own names
   (`linear-dimension`, `dimension`) are English strings baked into the graph,
   so even this is not entirely outside.
2. **User names** — `Flight` / `vol` / `航班`. This *is* knowledge, and it is
   the roadmap's existing **Namespaces** item ("reconciling different people's
   naming — spelling, language, and the same word used for different things")
   arriving from a new direction.

For (2) the fork is: **is a translation an identity or a relation?** Names are
identity in OntoDAG, so:

- *One node, many labels.* Labels ride in the record, hence in the root — which
  is correct (a label is new knowledge, so the fingerprint should change) but
  means every community's labels land in everyone's data.
- *Many nodes, linked.* Keeps names primary and makes "these are the same" an
  assertion that can be disputed, refined, or scoped. Costs an extra hop and a
  new kind of edge, which is precisely the thing §13 says to be careful about.
- *A separate lexicon store.* Translations in their own store with their own
  root, adopted by reference — the separation cone indexes already have. Lets a
  community share a vocabulary without touching anyone's asserted graph.

Prior art worth reading before deciding: SKOS uses `prefLabel`/`altLabel` with
language tags and is deliberately weaker than `owl:sameAs`, for the reason
below.

The hard part, which should not be glossed: **translation is rarely identity of
extension.** If `vol` and `Flight` carve slightly differently, asserting
identity destroys information, asserting subsumption in both directions is
identity again, and leaving them unrelated loses the link. That residue *is*
the Namespaces problem; a language feature that pretends otherwise will be
wrong in exactly the cases that matter.

**Proposed resolution (2026-08-01, recorded so the fork is not re-litigated;
build nothing until the Namespaces tripwire fires).** The two cases split
along §11's own line. *Exact* aliases — typos, abbreviations, `vol` really
does mean `Flight` — are identity, hence elaboration's job: a **lexicon
store** (the third option above), shared by reference like a cone index,
mapping surface names to canonical names without touching anyone's root.
*Near-synonyms* — where the carving differs — are claims, hence graph
content: distinct nodes plus relation edges, SKOS-shaped, disputable. The
lexicon handles the easy majority invisibly; the graph holds the disputed
residue, where the dispute *is* the information. The option ruled out is
labels-in-records: every community's labels in everyone's data, and a label
edit changing a knowledge fingerprint.

## 13. What are the limits of OntoDAG?

The question: from a deliberately small query formalism, how far toward full
knowledge representation and inference should this go?

The project already has the machinery for answering that shape of question —
`DATABASE_DIRECTION.md`'s **walls and tripwires**: features named as not-built,
each with the signal that would justify building it. Dimension lattices were an
escape hatch fired by a real tripwire. So this section should eventually become
walls, not opinions.

What the core is today, stated so a limit can be drawn against it:

1. one query primitive — intersection of descendant cones;
2. one structural invariant — the unique transitive reduction;
3. names as identity;
4. an exact, computed order for parametric values.

Everything shipped so far preserves all four. A useful first pass at candidate
KR features and what each would actually cost:

| feature | cost to the four |
|---|---|
| properties / roles beyond subsumption | a second edge type; cones stop being the only question; reduction is unique only per-relation |
| disjunction | already available query-side (`get_any`), deliberately never stored — the model to copy |
| negation | not a cone, and not monotone: merge stops being union |
| cardinality restrictions | needs individuals distinct from categories, which the item/category collapse deliberately refuses |
| rules / derived facts | derived content must be marked derived or the canonical form absorbs it; makes provenance mandatory |
| defaults, non-monotonic reasoning | directly incompatible with merge-as-union |
| weights, probabilities | breaks exactness, hence canonical roots |

A criterion falls out of that table, and it is sharper than "keep it simple":
**monotone and computable from names is admissible; non-monotone fights merge.**
Negation, defaults and closed-world assumptions are not merely bigger — they
are the ones that would take the CRDT property with them.

Which suggests the shape Peter proposed is right: **a higher layer that
compiles down.** An inference engine treats OntoDAG as its exact, shareable,
extensional substrate, keeps its own derived closure locally and unmerged (the
cone-index pattern again), and pushes down what it can express as cone
intersections. For that to work the interface must be written down explicitly —
*what a higher layer may assume* — so it cannot come to depend on internals:
`put`/`get`/`get_any`/`is_below`/`remove`/`merge`/`sync`, the canonical root,
and the guarantee that equal knowledge yields equal roots. Nothing else.

**Continued in `CONTRACT.md` (2026-08-01)** — the document this section
predicted. What it adds beyond the paragraph above: the criterion sharpened
into **two axes** (monotone, so merge survives; *and* cheaply **semantically**
canonicalizable, so equal knowledge keeps yielding equal roots — the second is
what the relations/EL step fails: EL is monotone, but without research-grade
work on canonicalizing entailment closures the root degrades from a
fingerprint of knowledge to a fingerprint of phrasing); the **as-of clause**
(non-monotone questions — negation, aggregation, closed-world, absence — are
honest when pinned to a root, and `RecordStore.at()` + `LazyOntoDAG` already
implement it); the observation that both axes are necessary but not
sufficient (computed values pass both and still wait behind a tripwire); and
this section's feature table re-sorted into `DATABASE_DIRECTION.md`'s walls.
The direction — core gains no further expressiveness; the higher layer
compiles down under the written contract — was **agreed 2026-08-01**.

## 14. OntoDAG among AI agents

The most practical and most urgent of these, and the least settled.

Start from the asymmetry rather than the rivalry:

- **A model has** coverage, fluency, and speed on fuzzy tasks. It very likely
  already "knows" most of what a small ontology would record.
- **OntoDAG has** structure that is *canonical, addressable, verifiable and
  attributable*. Equal knowledge yields an equal hash. A claim can be cited by
  root. Two parties can prove they agree, and a disagreement shows up as
  structure rather than as two paragraphs of confident prose.

A model's knowledge is none of those four: not addressable, not diffable, not
attributable, not stable across versions. So the proposition is not "store
facts the model already knows" — it is **a substrate for what has been agreed,
that can be shared unambiguously and checked cheaply.**

Roles that follow, and they are worth separating:

- **Shared ground truth between agents**, cited by root rather than restated.
- **Convergence without a server** — two agents `sync` and land on the same
  fingerprint, or discover exactly where they differ.
- **An audit surface.** Once agents write, provenance (`asserted` vs `derived`,
  already sketched on the roadmap) stops being a nicety.
- **A cheap verifier.** `is_below` is one bounded question an agent can *check*
  instead of asserting confidently — arguably the single most valuable thing to
  offer a model.

Interface questions to work through, phrased as questions:

- **Discoverability.** What does an agent read *first* to learn what a store is
  about, without downloading it? Anchor stars and cone summaries exist; a
  compact "what is in here" overview record does not.
- **Usability.** Tool-shaped operations, and errors that teach — the calendar
  error naming its own fix is the model to follow. Canonical echo matters
  disproportionately: the agent must be shown what was *stored*, not what it
  typed, or it will keep re-asserting variants.
- **Effectiveness.** Idempotent writes, bounded fetches, batch operations,
  propose-then-confirm, and a cheap "do you already have this?".
- **Surface.** MCP is the obvious candidate today. The CLI's contract (silent
  on success, one fact per line, non-zero exit) is already close to
  agent-shaped, which is some evidence the shape is right.
- **Risk.** Agents can produce structure faster than anyone can review it.
  Canonicity makes duplicates free to *detect* and does nothing to make content
  *good*; provenance plus endorsement is the sketched mitigation and would have
  to become real before this is safe at volume.

Finally, keep the two model roles apart, because they have different contracts:
§8's LLM is an **elaborator** inside one person's surface layer, whose output is
validated and confirmed before storage. This section's LLM is a **peer** that
reads and writes the store directly, and the question there is not elaboration
but authority, provenance and review.

**Decisions and follow-ups (2026-08-01).** This section stopped being open:

- **Agents-first is agreed** — the priority consumer, with a decent human
  interface kept alongside. Rationale in `CONTRACT.md` §1: reasoning is
  abundant, agreement is scarce; the four properties above are what a model's
  knowledge is not.
- **Canonical echo is §5's confirm step** — one mechanism serves humans and
  agents, which is evidence the surface contract is right, and means building
  §10 step 1 *is* building agent infrastructure.
- **Provenance is promoted** from research horizon to prerequisite: no agent
  write path before `PROVENANCE.md` is settled (attribution in a parallel
  store, never in the knowledge record — or agreement-by-fingerprint dies).
- **Verification upgrades the verifier role to trustless**: `is_below`
  certificates in both polarities (`CONTRACT.md` §7) let a third party check
  an agent's citation while holding only the root. The read-only MCP surface
  is queued first, writes gated on provenance; the MCP surface doubles as the
  **tripwire instrument** — what agents try to express and can't is exactly
  the evidence `DATABASE_DIRECTION.md`'s walls wait for.
- The review problem (the risk bullet above) is answered in design by
  *claims merge, acceptance is policy* — endorsement filtering per reader,
  `PROVENANCE.md` §5 — and must exist before writes run at volume.
