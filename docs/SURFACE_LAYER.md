# The Surface Layer: Messy Input, Readable Output, an Exact Core

Status: **discussion draft, 2026-08-01 (Peter + Claude). Nothing implemented,
nothing agreed.** This document exists to be argued with. It was prompted by
the `time(2026)` question — whether a bare year should be read as a year — and
by the observation that the honest answer is not about that one literal but
about where messiness is allowed to live. Open questions are collected in §9
rather than resolved inline; §10 sketches a sequence *if* we decide to do this.

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

## 6. Output side: rendering

The cheapest win and the least dangerous change, because output cannot corrupt
anything. Recognize structure in canonical names and print the friendly form:

| canonical | rendered |
|---|---|
| `time(2026-01-01T00:00:00Z..2026-12-31T23:59:59Z)` | `time(2026)` |
| `time(2026-08-01T00:00:00Z..2026-08-31T23:59:59Z)` | `time(2026-08)` |
| `weight(3000000mg)` | `weight(3kg)` |

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

1. **Is the calendar kind still the right shape** if a surface layer exists? A
   richer surface reduces the pain of declaring kinds but does not remove the
   ambiguity that made the kind necessary. My current view: the kind stays, and
   the surface makes it cheaper to live with — but this is worth attacking.
2. **Declaration ceremony.** A `declare` shorthand, an opt-in prelude of
   standard dimensions, or auto-declare-on-first-use-with-confirmation? A
   prelude changes the canonical root of a "fresh" store, so it cannot be the
   default without thought.
3. **Clock- and locale-dependent input** (`today`, local dates vs UTC). Accept
   with explicit expansion shown, or refuse? Bare dates are UTC days in the core
   today; a surface that accepts local dates lets two users store different
   facts from identical keystrokes.
4. ~~**Pipe semantics** (§7).~~ **Decided 2026-08-01: both.** Canonical
   whenever stdout is not a terminal, *and* a `--render` opt-in for when it
   isn't; `--raw` forces canonical on a terminal. Table and consequences in
   §7. This was the only thing blocking the renderer (§10.1).
5. **Surface versioning.** The surface needs its own version, separate from
   `REGISTRY_VERSION` — rendering changes are harmless, but changing elaboration
   changes what identical input stores. Does that version need to appear
   anywhere, or is it purely informational?
6. **Scope.** Does the surface layer cover only dimension values, or names in
   general — aliases, spelling, language? The roadmap's "Namespaces" item
   (reconciling different people's naming) is the same shape of problem and may
   want to land here rather than beside it.
7. **Where does it live?** A module in `ontodag`, or its own package? An LLM
   elaborator is certainly an optional extra; the pretty-printer probably is
   not.
8. **The legacy time-under-`linear-dimension` path.** Leave it, warn on it, or
   refuse `linear:time` at put time? Today it works until you type a bare year.

## 10. Possible sequencing (only if we decide to do this)

Ordered so each step is independently useful and none blocks a later one:

1. **Renderer + round-trip fuzz test** (§4, §6), under the §7 tty rule.
   Read-only, reversible, immediately fixes the ugliest complaint.
   **Unblocked** — §9.4 is decided; this is now the first thing that could be
   built, and it is self-contained enough to build before the rest of the
   layer is agreed.
2. **`odag canon TERM`** and `--raw`. Makes the layer inspectable and gives the
   escape hatch before anyone depends on the friendly form.
3. **Pure-function input sugar** — weeks, quarters. No new machinery.
4. **Declaration ergonomics** (§9.2), which is what would let dates appear in
   the User Guide's Quick Start.
5. **Clock-dependent input**, if §9.3 says yes.
6. **LLM elaborator** as an optional extra, behind the same contract.

Steps 1–3 are small and self-contained. Step 4 is the one with real design
content left in it. Steps 5–6 should not be started until the contract has been
exercised by 1–4.
