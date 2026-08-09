# A simpler web interface

**Status: stages 1–4 SHIPPED on `main` (2026-08-09); the rest is still a
discussion draft.** Two decisions are taken (§8); the demo-site section (§9)
and user spaces (§10) are requirements from Peter's first read and are the
least settled parts. §14 records what the build actually produced, what the
browser found, and what is still owed.

Prompted by: *"the current web view is old fashioned, clunky, overcrowded
and confusing — make a plan for a much simpler interface, maybe include a
console for typing to OntoDAG."* Then: *"a webpage has more opportunities
for graphical and click interactions, so it would be nice to have some
browsability as well… but the command line and the click-and-browse models
are quite different"*, and *"I may want to run a demo website for people to
try OntoDAG without installing anything."*

That second note is the one that shapes this document. §3 argues the two
models are **not** different here — not as a compromise, but because of
what OntoDAG is.

---

## 1. What is actually wrong, measured

Counted from `web/templates/index.html`, not from impression:

| | today |
|---|---|
| interactive controls on one screen | **32** (20 buttons, 8 text inputs, 2 file inputs, 1 select, 1 checkbox) |
| forms stacked above the content | **7** |
| lines of markup / inline script | 80 / 344, one file |
| text box driving more than one verb | `#subcategory` drives **4** (add, remove, delete-cone, move) |

Six faults, in rough order of how much they hurt:

1. **One box, four verbs.** `#subcategory` is labelled *"Subcategories
   (comma-separated)"* inside the **Add Item** form, and it is also the
   input read by *Remove Item*, *Delete + Contents* and *Move Item* — two
   of which are destructive. Pressing "Delete + Contents" acts on whatever
   happens to be sitting in the add box. Nothing on screen says so.

2. **The main content area is a flat dump of every node.** The largest
   region lists all nodes as bordered cards with their children. Fine for
   the twelve-node demo it was built against; unreadable at a hundred,
   useless at a thousand. No focus, no search, no ordering anyone chose.
   **There is nothing here that deserves the name browsing.**

3. **Everything is drawn twice.** The page splits "the DAG" (65%) from
   "the query" (30%), and each half has its own form stack, picture, node
   list, import form and row of four export buttons. `loadDAG()` and
   `queryDAG()` are near-identical functions. Not a styling accident — §2.

4. **It shows names nobody typed.** Executed against a prelude store:

   ```
   time(2026)     is displayed as  time(2026-01-01T00:00:00Z..2026-12-31T23:59:59Z)
   weight(500g)   is displayed as  weight(1/2kg)
   ```

   Both correct; neither is what a person typed or wants to read. The
   renderer that fixes this shipped in 0.9.0 — the CLI renders by default
   on a terminal, MCP carries `display` beside every name, and the web page
   is the one surface showing canonical only (guide §6 records this as a
   deliberate limitation, which by now it need not be).

5. **The whole graph is re-rendered by graphviz on every mutation.** Every
   add, remove, move, prelude and pack handler ends in `reloadDagImage()`,
   a full-graph server-side layout. Cost grows with the store while the
   picture's usefulness shrinks with it.

6. **The feature gap widens on its own.** The CLI has 26 commands; the page
   exposes about 13 verbs. Absent entirely: `count`, `history`, `status`,
   `undo`, `redo`, `diff`, `excerpt`, `show`, `list`, `merge`, `index`,
   `swarm`, `--as-of`. `/dag/overlapping` is a REST route with **no control
   on the page at all** — contract guarantee G6, reachable from Python,
   MCP, the CLI and curl, but not from the surface most people meet first.

## 2. Why it grew this way, and why it keeps growing

The page is organised **one control per verb**. Under that rule the only
way to close a feature gap is to add a widget, so the page necessarily gets
more crowded every time the system gets better. The 2026-08-06 parity pass
added five controls in one sitting (12 → 17); it is 32 controls now. This
is not a styling problem a nicer CSS file fixes — it is the shape of the
design.

The duplication in fault 3 has a specific cause, and it tells you the fix.
In OntoDAG **a query result is a DAG, and the whole store is the answer to
the empty query.** The core already knows this: `odag get`, `odag list` and
`odag get '*'` are *one code path*. The page still has two of everything
because it predates that unification and never followed it. Applying it
deletes half the page before a single new idea is added.

## 3. Browsing and typing are the same operation here

Peter's worry — *"the command line and the click-and-browse models are
quite different"* — is true of most systems and false of this one, for a
reason worth stating precisely.

**In OntoDAG, a path is a query.** This is the ontodag-fs thesis (Gifford's
Semantic File System, SOSP '91): `/pet/dog` does not name a location, it
means *everything that is a pet AND a dog*, and `/dog/pet` is the same
place. So "drilling down" by clicking a category is not navigation to
somewhere else — it is **appending a term to a conjunction**:

```
click Japan     ≡   get Japan
click Flight    ≡   get Japan Flight
remove Japan    ≡   get Flight
```

A breadcrumb is a query. The "folders" you see next are the categories that
usefully narrow what you are looking at. The "files" are the answer. A
newcomer who has used a file manager already knows how to operate this and
never has to be told it is a query.

That gives the design rule that reconciles the two models, and it is the
whole idea of this document:

> **Every click writes its command into the console; every command updates
> the browse state.** They are two inputs to one state, not two interfaces.

So the console is not a power-user annex bolted onto a GUI. It is the
**transcript of what you just did with the mouse**, which makes it the
cheapest possible way to teach the language: you click `Japan`, and
`get Japan` appears in the console having produced exactly the list you are
looking at. Nobody has to read documentation to make that connection. When
they want something the mouse cannot say — `move`, `diff`, `undo`, a union,
a typed range — they are already fluent in the syntax.

This also settles which is "primary": neither. The browse pane is primary
*for the first ten minutes*, the console is primary after, and the ladder
between them is a design feature rather than a fallback.

**A note on what the browse pane really is.** Hiding refinements that cover
the whole current answer (they narrow nothing) and refinements that would
empty it (dead ends) means every click lands on a genuinely different
answer. That is a walk in the concept lattice — which, per the FCA paper
(`paper/ontodag-fca.tex`, result 2), is the Dedekind–MacNeille completion
of the DAG. The browse pane is not a UI convention borrowed from
e-commerce; it is the lattice, walked one step at a time.

## 4. The shape

```
┌──────────────────────────────────────────────────────────────────────────┐
│ OntoDAG   sandbox · demo store   root 9a732928c4d1   412 items   [shown ▾]│
├──────────────────────────────────┬───────────────────────────────────────┤
│  ✱  ›  Japan ✕  ›  Flight ✕      │   JAL7                                │
│                                  │   ─────────────────────────────────   │
│  Refine by                       │   stored as   JAL7                    │
│    Airline        (7)            │                                       │
│    time(2026-08)  (4)            │   above   Flight, Japan               │
│    Booked         (3)            │   below   boarding-pass.pdf           │
│                                  │   under it   1                        │
│  Here — 12 items                 │                                       │
│    JAL7                          │   [ file under… ]  [ move… ]  [ ⋯ ]   │
│    NH209                         │  ┌─────────────────────────────────┐  │
│    boarding-pass.pdf             │  │      clickable neighbourhood    │  │
│    …                             │  │              (SVG)              │  │
├──────────────────────────────────┴───────────────────────────────────────┤
│ > get Japan Flight                                                       │
│     JAL7                                                                 │
│     NH209                    … 12 items                                  │
│ > _                            (drop a file here to import)              │
└──────────────────────────────────────────────────────────────────────────┘
```

Four regions, no modals:

- **Identity bar** — which store, which root, how many items, registry and
  surface versions, and the rendered/raw toggle. The current page shows
  *none* of this, which is why nothing on it feels like it belongs to
  anything.
- **Browse pane** — breadcrumb (= the query, each term removable), *Refine
  by* (categories that narrow the current answer, with counts), *Here* (the
  answer).
- **Focus pane** — whatever you last clicked: rendered name, canonical form
  underneath, parents, children, count, a clickable neighbourhood picture,
  and the two or three verbs natural to click *while pointing at
  something*.
- **Console** — transcript plus one input, echoing every click as a
  command.

32 controls become one input, one breadcrumb and two lists.

## 5. The browse pane

Two new read-only routes, both computable from what exists:

```
GET /dag/browse?cat=Japan,Flight
  -> {"here":   [{name, display, count}, …],       # the answer
      "refine": [{name, display, matching}, …],    # proper refinements, ranked
      "count":  12}

GET /dag/node/<name>   -> the focus payload (parents, children, count, canonical)
```

**Refinements** are the categories held by *some but not all* of the
current answer: hold-them-all narrows nothing, hold-them-none is a dead
end. Rank by how many of the answer they match, show that number, and put
declared dimension values in their own group so a date range does not
compete with an airline for the top of the list.

*Cost, honestly.* Computing this needs the ancestors of the answer members
and a `|cone ∩ answer|` per candidate. At demo and personal scale that is
nothing. At published-store scale it is the same broad-query cost the cone
index was built for, and the same eventual answer applies (`ontodag.cones`,
and the in-memory cone bitmaps parked in SEMANTIC_CODES §8 step 1 — whose
`popcount == descendant_count` oracle makes `|cone ∩ answer|` a single
`AND`). Until measured, cap the computation at the first *N* of the answer
and say so on screen rather than quietly truncating.

## 6. The console

Server side, one route over the existing interpreter:

```
POST /dag/console   {"line": "get Flight Japan"}
  ->  {"out": "JAL7\nNH209\n", "err": "", "code": 0,
       "root": "9a73…", "count": 412, "browse": {…}}
```

`shlex.split` the line, hand the tokens to `dispatch()`, capture both
streams, return them plus the state the identity bar and browse pane need.
`dispatch` hardcodes `out = sys.stdout`, so this wants a small change in
`__main__.py`: `dispatch(argv, session, out=None, err=None)` defaulting to
the process streams. §11 says why `redirect_stdout` is the wrong way.

Discoverability is the usual price of a console, and §3's echo rule pays
most of it — the language teaches itself as you click. The rest is cheap:

1. The transcript opens with three or four examples built **from the
   store's own contents**, not a fictional pet shop.
2. **Tab completion** over commands *and* names, from `GET
   /dag/names?prefix=`. The CLI's `>` prompt has no completion at all, so
   the web console would be the better prompt of the two — and the same
   endpoint could later back a readline completer for the CLI.
3. `help` renders into the transcript; it already exists and already is the
   documentation.
4. Errors are already *teaching* errors ("install the swarm extra",
   "propose again", "odag undo"). Show them verbatim; do not rewrite them
   into web prose.
5. Two things stay direct manipulation because typing them is worse: **drag
   a file onto the console to import**, and `export`/`excerpt` answering
   with a download link rather than writing a server-side path.

## 7. The graph, made clickable — verified, and cheaper than expected

The third way in. Today the picture is a PNG the page re-renders wholesale
and can only enlarge. It should be **navigable**: click a node to focus it,
which is the most natural gesture there is for a graph and the one thing a
picture can do that a list cannot.

This needs no JS graph library, no build step and no new dependency.
Graphviz emits SVG carrying `viz.py`'s synthetic ids, verified by
execution:

```
<g id="node2" class="node"><title>n2</title><ellipse …/><text …>Japan</text></g>
```

Those ids (`n0`, `n1`, …) are already assigned in the DAG's deterministic
iteration order — they exist because DOT reads `:` as a port separator and
canonical names contain them. So: render `format="svg"`, return it inline
with the id→name map, attach one click handler. Three side benefits — SVG
scales, is far smaller than PNG for graphs, and **drops Pillow from the
picture path** (only `generate_image` needs it).

Scope the picture to the focus (neighbourhood at depth *n*, via the
existing `OntoDAG.induced_subdag`) or to the query
(`viz.query_picture`, which already draws virtual terms). The whole-store
picture stays reachable — it is just the empty query — but stops being
something the page redraws by reflex.

## 8. Decisions taken

Both were flagged as Peter's; both are answered *yes* to the
recommendation. Recorded here so a later reader knows they were decided
rather than assumed — **correct this if the "yes" meant something
narrower.**

**(a) What the app looks at: option C — a store spec, sandbox by default.**
The app accepts a store spec exactly as `odag` does, with an explicit
`memory:` sandbox as the default so the demo and the 53 existing tests keep
today's semantics. Pointed at `rs:` or `swarm:`, the identity bar becomes
substantive: root, history, `undo`, `--as-of` all become real, and the web
becomes the first surface where a person can *watch* a canonical root
change as they type. A third mode falls out free: **read-only against a
published Swarm root**, which is how you show someone else's ontology in a
browser — and, per §9, the cheapest possible demo.

**(b) The console runs an allow-list, not everything.** A console handing
arbitrary lines to `dispatch()` is a shell: `import PATH`, `export PATH`,
`merge PATH`, `-o FILE` and `set store PATH` all take filesystem paths and
run as the server user. Allow-list the commands; rewire the path-taking
ones to the browser (upload in, download link out); keep `set store` off
the web surface entirely — pointing the app at a store is a launch
argument, not something a page can do to itself. The allow-list is also
what stops the console silently acquiring every future CLI command without
anyone deciding it should. **The demo site (§9) makes this non-optional.**

## 9. The demo site — try it without installing

New requirement, and the strongest argument for the whole redesign: a
public demo is a page a stranger meets with no context, so it is exactly
the case where 32 controls and a wall of canonical timestamps lose the
visitor in ten seconds — and exactly the case §3's ladder is built for.

**The sandbox is the right default here, for once.** A per-session
in-memory DAG gives isolation for free with no accounts, no storage and no
data to lose. What it needs is the operational care a public endpoint
always needs and this app has never had:

| | today | needed for a public demo |
|---|---|---|
| `app.run(debug=True)` | on | **off** — the Werkzeug debugger is remote code execution. Real WSGI server. |
| `secret_key` | `os.getenv(...)`, `None` if unset | required at startup, fail loudly if missing |
| session store | class-level dict, pruned only when that same visitor returns | bounded: LRU + hard cap + idle eviction. One abandoned visitor = one retained `OntoDAG`, forever |
| graph size | unbounded | per-session node cap, with a friendly message at the ceiling |
| pictures | graphviz layout on a user-controlled graph, any size | node-count ceiling before layout; rate limit; SVG (§7) is cheaper than PNG |
| commands | n/a | the §8(b) allow-list, and it is now load-bearing rather than prudent |

Two content decisions matter as much as the hardening:

1. **Land them in a seeded store, not an empty root.** An empty `*` is the
   worst first impression the system can make: nothing to click, and the
   browse pane — the part that teaches — has nothing to show. Ship a small
   worked example already loaded (the travel one from the guide reads
   better than the car market, and exercises typed values). "Reset to the
   example" and "Start empty" are two buttons in the identity bar.
2. **Adopt the prelude on session start.** Typed values are *refused*
   without declarations, so a visitor who types `weight(3kg)` in the first
   minute currently gets an error for doing the most interesting thing on
   offer. The demo should never be able to produce that error.

**Cheapest first version, worth noting because it needs almost none of the
above:** a *read-only* demo over a published Swarm root — §8(a)'s third
mode. No sessions, no writes, no caps, no allow-list, cacheable, and it
demonstrates the property that actually distinguishes OntoDAG (a canonical
root anyone can fetch and verify). It is a good thing to be able to ship
early and independently, and a good thing to keep even once the writable
sandbox exists: *"browse a real published ontology"* and *"make your own"*
are two different invitations.

## 10. User spaces, later

Peter: *"in the future they may even have their own user spaces, either in
the traditional way, or on Swarm."* Both are reachable from §8(a) — a user
space is a store spec — and they are very different propositions:

- **Traditional.** Accounts, and one `rs:` directory per user on the
  server. Straightforward, well understood, and it makes the operator
  custodian of everyone's data: backups, deletion requests, breach
  exposure, and the server becomes the thing that must not go down.
- **On Swarm.** The user's ontology is their own signed feed; the server
  holds nothing and is a viewer. Identity is a key, "sign in" is *connect a
  wallet*, and the user keeps their store when the demo disappears. This is
  the version worth wanting, and it is the one this repo is already built
  for — `swarm:NAME` with a signer is exactly this shape today.

The obstacle is known and already written up: `ontodag[swarm]` **can never
run in a browser** (25 packages including compiled `coincurve`), so Swarm
from a page goes through JavaScript permanently — `docs/plans/BROWSER.md`,
which also has the miss-and-replay design, the measured round-trip counts,
and the finding that the cone index is *mandatory* there (305 rounds → 10).
Wallet signing is the same JS-interop story as bee-js, so it fits rather
than adds.

Sequence, if this is the direction: read-only published root (§9) → the
browser bridge and cone index from BROWSER.md → wallet identity → writable
feeds. Nothing before the last step needs an account system, and the first
step needs none of it.

## 11. What breaks, and what does not

**Does not break: the REST API.** The routes are a surface in their own
right (guide §1.1) and stay as they are. Of the 53 tests in
`tests/test_web.py`, **48 are REST-only and survive the page rewrite
untouched**; only the 5 in `TestThePageIsWiredUp` are coupled to the
markup, and those five *checks* generalise unchanged (every id the script
uses exists; every URL it fetches is a registered route; the controls are
present; the script parses under `node --check`). Keep them — they are what
catches a silently dead button.

**Two hazards in reusing the CLI interpreter**, both worth fixing before
the console rather than after:

- `_OVERRIDES` and `PARSER` are **module-level globals** in `__main__.py`.
  The dev server is threaded, so concurrent requests can stomp each other's
  `--as-of`, `-m` or `--limit`. Either serialise console requests behind a
  lock (simplest and honest — console traffic is one line at a time from
  one person) or thread the overrides through as a parameter. **On a
  multi-visitor demo site this stops being theoretical.**
- `redirect_stdout` is process-global, so it has the same problem *plus* it
  would swallow output from unrelated requests. Hence the `out=`/`err=`
  parameters in §6: every `cmd_*` function already takes `out`, so the
  change stops at `dispatch` itself.

**Owed regardless: a real browser pass.** The standing evidence here
(2026-08-02) is that three bugs sat behind `200` responses with wrong or
empty content — one a valid 83×59 PNG recorded as success. Static wiring
checks catch dead buttons; they do not catch a picture that disagrees with
the answer beside it. Not done until clicked through in a browser
(`claude --chrome`).

## 12. Staging

Each stage is useful alone; none requires the next.

1. **Console.** `dispatch(out=, err=)`, `POST /dag/console`, transcript,
   allow-list, request lock. Served at `/console` with the current page
   still at `/`, so it is testable end to end before anything is deleted.
2. **Collapse the page.** One result pane, one picture, one import, one
   export row (the empty query *is* the whole store). Identity bar. Delete
   the five form stacks — mostly deletion; this is where 32 controls become
   a handful.
3. **Browse.** `GET /dag/browse`, breadcrumb, refinements, the echo rule in
   both directions. **The stage that decides whether the redesign works**,
   because it is the one a newcomer meets.
4. **Focus pane, rendered names, clickable SVG.** `GET /dag/node/<name>`,
   `surface.render` for display with canonical underneath, SVG picture with
   click-to-focus.
5. **Polish that earns its keep.** Tab completion, up-arrow history,
   drag-to-import, scoped neighbourhood depth.
6. **Demo hardening** (§9) and **store selection** (§8a) — independent of
   each other and of 1–5.

## 13. Open questions

1. Does the browse pane show **items and categories separately**, or as one
   list? OntoDAG deliberately has no class/instance distinction — nodes are
   undifferentiated `Item`s — so the honest answer is one list, but a person
   browsing expects "folders above files". A defensible middle: sort by
   whether anything hangs below (`descendant_count > 0`) and do not claim
   it is a type distinction.
2. Should the console transcript be **persistent**, and if so is it
   scrollback or a *script* — re-runnable, editable? The second is a much
   larger idea, close to a notebook, and would make a demo session
   shareable as a link.
3. `--as-of` as a **mode** (identity bar goes amber, writes refuse) rather
   than a flag typed per command? Reads better and matches how people think
   about looking at the past.
4. Does the `/market` demo keep this page's plumbing or become its own
   thing? It shares the `my_dag` session key, which has already caused one
   500 (fixed 2026-08-02). Recommendation: give it its own key.
5. The query workload log (`QUERY_LOG`, in-memory, process-local) exists
   *only* on this surface — the one least used for real work, which defeats
   what SEMANTIC_CODES §9 wants it for. A public demo would make it the
   most workload-diverse surface instead. Keep it and feed the index
   policy, or move it?

---

## 14. What was built (2026-08-09, merged to `main`)

Stages 1–4 of §12. The old page is still served, unchanged, at `/classic`;
**no REST route was removed or altered**, so the 48 route-level tests passed
untouched and the only tests that needed rewriting were the 5 that read the
markup — the de-risking argument in §11, confirmed rather than assumed.

**In the package** (so no surface can drift from another):

- `ontodag.browse` — `browse(dag, queries)`, `refinements(...)`, `focus(...)`.
  The refinement rule of §5, and the fourth module that **imports nothing at
  all** (the DAG is duck-typed), so it works over `OntoDAG`, `EagerOntoDAG`,
  `SparseOntoDAG` and a read-only `LazyOntoDAG` view alike. Two boundary
  cases pin that `import ontodag` never pulls it.
- `dispatch(argv, session, out=None, err=None)` — the embedding seam. Both
  streams are bound with **ContextVars**, not module globals and not
  `redirect_stdout`: those are process-wide, so under a threaded server one
  request would swallow another's output. The 17 `file=sys.stderr` note sites
  route through `_err()`, and a `_Parser` subclass sends argparse's own usage
  errors and `--help` the same way — without which a confused caller loses
  exactly the two messages they need.
- `OntoDAGVisualizer.generate_svg` + `node_ids` + an optional `label`
  callable. SVG scales, is a fraction of PNG's size, needs no Pillow, and
  carries the ids — so **click-to-focus is one delegated event handler**, no
  graph library and no build step. Layout stays `dot`'s.

**In the web app**: `POST /dag/console`, `GET /dag/browse`, `/dag/node/<name>`,
`/dag/names`, `/dag/picture`, `POST /dag/example`, and `/classic`.

**Front end**: Preact + htm, vendored (13 KB, one file, MIT), **no build
step and no CDN at runtime** — a Python project should not need a JavaScript
toolchain to serve one page, and a demo site should not hand its visitors to
someone else's host. `web/static/app.js` + `app.css`.

**Choices worth recording.** Flask stays: the crime was in the template, not
the server, and swapping it would have rewritten the 48 tests that are the
whole reason this was cheap. Graphviz stays too — `dot`'s layered ranking is
better than anything that would run in the browser, and the interactivity
turned out to be free once the output was SVG. The console **claims to be a
tty** (a `ConsoleStream` whose `isatty()` returns True) rather than plumbing
flags: the CLI already decides between readable spellings and canonical
bytes by asking the stream, and a browser is unambiguously a person, so the
rule is inherited rather than copied.

**Deliberately kept as direct manipulation**: drag a file onto the console to
import, and the Download menu.

### What the browser found that HTTP could not

The standing lesson (2026-08-02) held. `web/browser_check.py` drives the page
with Playwright and asserts what is on screen; it is **not** in the test
suite (it needs a running server and a downloaded browser). Three real bugs,
none of which any status code would have shown:

1. **`&gt;` rendered as four literal characters.** htm does not decode HTML
   entities, so the console prompt read `&gt;`. Invisible to
   `page.content()`, which re-escapes text nodes — it took looking at the
   picture.
2. **The picture never redrew after a mutation.** Its effect depended on the
   query and the focus, and a `put`/`remove`/`move` changes neither. The
   classic page redrew on every keystroke, which was wasteful but never
   wrong. Fixed with an `epoch` counter; the check for it deliberately uses a
   fixed settle rather than waiting on the thing it asserts, since waiting
   for a redraw that never comes would pass nothing.
3. **The whole-store thumbnail was a squiggle.** 33 nodes at thumbnail size
   is legible for the twelve-node example and useless past it. With no focus
   and no query there is now no picture: a picture is worth drawing when it
   is *scoped*.

A fourth thing the screenshot showed rather than a check: the console was
repeating the answer that is already the middle pane, in a form you cannot
click, pushing what you typed off the top. Long output now folds to six
lines and says how many it kept back. **The console's job is what you did;
the panes' job is what is there.**

### The menu (added after Peter's second read)

*"Without making the display more complex, could we have some kind of menu
items, so someone unfamiliar with the commands could explore?"* — the answer
was no, he hadn't missed it: the focus pane had four verbs but only once
something was selected, and nothing anywhere listed the language.

The constraint (**no more permanent chrome**) is what made the solution
good. Rather than a menu bar, the console's completion list became **one
contextual suggestion list** that is also the menu:

- while the *verb* is being typed it lists commands — name, argument shape,
  and one line of what it does;
- past the verb, Tab lists this store's names;
- it is on screen only while it is being used, so it costs one small
  `commands ▾` button beside the prompt and nothing else.

Two properties worth keeping:

- **It is read off the argparse parser** (`GET /dag/commands`) — descriptions,
  argument shapes and the meaning-changing flags all come from the code, so a
  command the console will run but the menu never lists is impossible. Output
  plumbing (`-o`, `--raw`, `-n`) is filtered out: real options, none of them
  about what the command *does*, and `-o` is refused here anyway.
- **It is contextual.** Chosen while something is selected, a command arrives
  with that something filled in (`move JAL7 `). "Takes an item" is not "has a
  positional" — `pack NAME` has one and it names a unit pack, so offering the
  selection there would be nonsense dressed up as help.

The focus pane gained a `more…` button that opens the same list for the
selected item, which is the "what can I do with this thing" question the four
fixed buttons could not answer.

A third real bug came out of it, again only visible by driving the page: an
**empty line popped the whole menu open**, so clearing your input and
pressing Enter silently *inserted* the highlighted command instead of doing
nothing. The menu now appears only when a verb is being typed or when it is
asked for.

### Still owed

- A human looking at it. 19 automated browser checks are a floor, not taste.
- Stage 5 (completion polish beyond Tab, up-arrow history is in), stage 6
  (§9 demo hardening, §8a store selection).
- The `/market` demo still shares the `my_dag` session key (open question 4).
- Unions are typeable but the breadcrumb only lets you *drop* a whole union,
  not one branch of it. Narrowing a union narrows every branch, which is
  right; removing one branch has no obvious gesture yet.
