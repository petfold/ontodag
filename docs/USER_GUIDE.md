# OntoDAG User Guide

OntoDAG helps you organize things — files, notes, photos, products, ideas — into
**categories that can overlap**. You put items in, telling OntoDAG which categories
each one belongs to, and later you ask questions like *"show me everything that is
both a Flight document and part of the Japan trip."*

This guide is for everyday users. It assumes you can open a terminal and copy-paste
commands, but not much more. Every example in it has been run for real — the outputs
you see are genuine. If you want to know how OntoDAG works internally,
read [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md) afterwards.

---

## Quick start (two minutes)

Install, and you have the `odag` command (no file to create — a default
store appears in `~/.ontodag`):

```console
$ pip install ontodag
```

File things under **as many categories as apply** — no folder to choose.
Run `odag prelude` once and dates, weights and sizes work as typed values:

```console
$ odag put Travel
$ odag put Japan Travel
$ odag put Flight Travel
$ odag prelude
$ odag put boarding-pass.pdf Flight Japan 'time(2026-08-15)'
$ odag put hotel-kyoto.pdf Japan
```

Then ask. Every question is "everything under *all* of these":

```console
$ odag get Japan
boarding-pass.pdf
hotel-kyoto.pdf
$ odag get Travel 'time(2026)'
boarding-pass.pdf
$ odag below boarding-pass.pdf Travel
true
```

The boarding pass came back for `time(2026)` although you filed it under a
single *day* — the containment is computed, no link was stored. That's the
whole system: `put` with categories, `get` with categories, `below` to
check one fact. Everything else in this guide — Python, typed values in
depth, the web app, publishing to Swarm, AI agents — builds on exactly
this.

The same in Python, if that's your home ground:

```pycon
>>> from ontodag import OntoDAG
>>> dag = OntoDAG()
>>> dag.put("Travel", [])
>>> dag.put("Japan", ["Travel"])
>>> dag.put("hotel-kyoto.pdf", ["Japan"])
>>> sorted(item.name for item in dag.get(["Travel"]))
['Japan', 'hotel-kyoto.pdf']
```

---

## 1. Why OntoDAG? (one minute)

Computers usually offer two ways to organize things, and both are frustrating:

- **Folders** force every item into exactly one place. Where does your flight
  confirmation for the Japan trip go — `Flights/` or `Japan/`? You must choose, and
  whichever you choose, you'll look in the other one first.
- **Tags** let an item carry many labels, but the labels themselves are a flat,
  unstructured heap. Tagging a scan `boarding-pass` doesn't make it show up when you
  search for `flight`, unless you remembered to add `flight` too. And `Japan`. Every
  time.

OntoDAG sits exactly between the two:

- Like tags, an item can belong to **many categories at once**.
- Like folders, categories are **organized**: a boarding pass can live under the
  flight it belongs to, which lives under `Flight` and `Japan` — so the boarding pass
  automatically counts as part of the trip, without you repeating yourself.

There is one more idea, and it's the whole query language: **asking = intersecting.**
You ask with a set of categories, and you get back everything that is under *all* of
them. `Flight` + `Japan` → the flights for that trip, but not the hotel booking (also
Japan, but not a flight) and not last year's flight to Berlin (a flight, but not this
trip).

A note on vocabulary: in OntoDAG there is no difference between an "item" and a
"category." Everything is just a named thing that can sit under other named things
and can have things under it. Today's item is tomorrow's category — file a flight
confirmation, and later file the boarding pass under *it*. This is deliberate, and
it is how the trip's paperwork ends up organizing itself.

### 1.1 Ways in and out

The same DAG is reachable five ways. They are surfaces over one store, not
separate products — point them at the same store and they see the same thing.

| Surface | What it is | Where |
| --- | --- | --- |
| **Python** | `from ontodag import OntoDAG` — the library everything else wraps | §3, §4 |
| **Command line** | `odag`, a Unix tool: silent on success, pipes cleanly | §5 |
| **Web** | a browser UI with live pictures, plus a REST API for `curl` | §6 |
| **Agents** | `odag-mcp`, the store as MCP tools, with verifiable answers | §9 |
| **Filesystem** | [ontodag-fs](https://github.com/petfold/ontodag-fs): paths as queries, FUSE-mountable | separate repo |

Not everything is available everywhere. The gaps are deliberate rather than
accidental — each surface exposes what makes sense for who is using it:

| | Python | CLI | Web | MCP |
| --- | --- | --- | --- | --- |
| put / remove | ✓ | ✓ | ✓ | ✓ (with `--write`) |
| query, union (`or`), `below` | ✓ | ✓ | ✓ | ✓ |
| typed values (`weight(3kg)`) | ✓ | ✓ | ✓ | ✓ |
| readable rendering | ✓ (`ontodag.surface`) | ✓ | — | ✓ (beside the exact name) |
| import / export / merge | ✓ | ✓ | ✓ | — |
| pictures | ✓ | ✓ | ✓ | — |
| Swarm stores | ✓ | ✓ | — | ✓ |
| as-of (query a past root) | ✓ | — | — | ✓ |
| certificates, provenance, review | ✓ | — | — | ✓ |

The two surfaces with the most on them are Python (which has everything, being
the thing the others call) and MCP (which is deliberately the *verifiable*
surface — see §9). The CLI is the one to reach for interactively; the web app
is the one to show someone.

---

## 2. Installation

You need **Python 3.11 or newer**.

```bash
pip install ontodag
```

This installs the `odag` command and the Python library, along with its
dependencies (`graphviz`, `owlready2`, and `recordstore`).

### Which platforms

The core is pure Python with no compiled extensions, and paths are resolved
portably — `~` means your home directory on every platform, including
`C:\Users\you` on Windows. What differs is how much has actually been *run*:

| Platform | Status |
| --- | --- |
| Linux | Tested — the full suite runs here on every change. |
| macOS | Expected to work, not routinely tested. Install Graphviz with `brew install graphviz`. |
| Windows | Core, CLI and file store are expected to work; not tested. The Swarm *signer* needs the `bee` package, which builds a native secp256k1 extension — the least likely piece to install cleanly. |

Nothing in the store itself is platform-specific: it is a canonical text file
(§5.1), so the same store works on any of the three, and `$ONTODAG_HOME`
overrides its location if you want it somewhere other than your home directory.
If you hit a platform problem, please report it — that is how the table above
gets shorter.

### If that fails with `externally-managed-environment`

```
error: externally-managed-environment
× This environment is externally managed
```

You are on Debian, Ubuntu 23.04+, Fedora, or Homebrew Python, which reserve the
system Python for the OS package manager (PEP 668). Nothing is wrong with your
setup — pick the route that matches what you actually want:

- **Just the `odag` command.** [pipx](https://pipx.pypa.io) installs it into its
  own private environment and puts the command on your `PATH`:

  ```bash
  sudo apt install pipx          # once, if you don't have it
  pipx install ontodag
  ```

  Extras go in the same spec — `pipx install "ontodag[web]"` — and later
  upgrades are `pipx upgrade ontodag`. The catch: this gives you the *command*
  only. `import ontodag` in your own Python scripts will not find it.

- **The Python library as well.** Use a virtual environment:

  ```bash
  python3 -m venv ~/.venvs/ontodag
  source ~/.venvs/ontodag/bin/activate
  pip install ontodag
  ```

  Both `odag` and `import ontodag` work while that environment is active.

- **Override the guard**, if you accept that pip and apt then share a directory:

  ```bash
  pip install --user --break-system-packages ontodag
  ```

Three optional extras:

- **Pictures.** To render your DAG as an image you also need the Graphviz *system
  program* (the Python package alone is not enough):

  ```bash
  sudo apt install graphviz        # Debian/Ubuntu
  brew install graphviz            # macOS
  ```

- **The web app.** For the browser interface and REST API:

  ```bash
  pip install "ontodag[web]"
  ```

- **Swarm storage.** To keep a store on Ethereum Swarm rather than in a local
  file (§5.1):

  ```bash
  pip install "ontodag[swarm]"
  ```

> **Working from a source checkout instead:** `git clone
> https://github.com/petfold/ontodag.git && cd ontodag`, then either
> `pip install -e .` (subject to the same PEP 668 guard as above — inside a
> venv, or with `--user --break-system-packages`) or prefix commands with
> `PYTHONPATH=src`, e.g. `PYTHONPATH=src python3 -m ontodag show`, which needs
> no install at all. Everything below works either way; we'll write `odag` for
> short, which is the same as `PYTHONPATH=src python3 -m ontodag`.
>
> Install the checkout *once*, one way. Two editable installs of the same
> repository (say a venv and a `--user` one) both put an `odag` on your `PATH`
> and the later one silently wins — they run the same code, but `odag -V`
> reports whichever install's metadata is found, so a stale one can claim an old
> version number indefinitely.

---

## 3. A five-minute tour (Python)

Start `python3` and type along. Everything is done with plain names:

```python
>>> from ontodag import OntoDAG

>>> dag = OntoDAG()

# Top-level categories: no parents. Two kinds of document, one trip.
>>> dag.put("Flight", [])
>>> dag.put("Hotel", [])
>>> dag.put("Japan", [])

# Things under several categories at once — this is the point of OntoDAG.
>>> dag.put("japan-outbound.pdf", ["Flight", "Japan"])
>>> dag.put("japan-return.pdf", ["Flight", "Japan"])
>>> dag.put("hotel-tokyo.pdf", ["Hotel", "Japan"])

# A document filed under another document: the boarding pass for that flight.
>>> dag.put("boarding-pass.png", ["japan-outbound.pdf"])
```

Here is the resulting graph, drawn by OntoDAG's own visualizer (§4.5). Arrows
point from general to specific; `*` is the built-in root above everything; the
number after each name is how many things sit below it:

![The travel DAG](images/travel.svg)

Now ask questions. A query is a list of categories; the answer is everything under
**all** of them:

```python
>>> for item in dag.get(["Flight", "Japan"]):
...     print(item.name)
japan-return.pdf
boarding-pass.png
japan-outbound.pdf

>>> for item in dag.get(["Hotel", "Japan"]):
...     print(item.name)
hotel-tokyo.pdf
```

(Results are a set, so the order can vary.) Notice `boarding-pass.png` appeared
under `Flight` + `Japan` even though you never said it was a flight document or
part of the Japan trip — it's under `japan-outbound.pdf`, and that's enough. That's
the inheritance doing your bookkeeping for you.

And asking for the trip alone gathers everything, whatever kind of document it is:

```python
>>> sorted(item.name for item in dag.get(["Japan"]))
['boarding-pass.png', 'hotel-tokyo.pdf', 'japan-outbound.pdf', 'japan-return.pdf']
```

That is the folder you never had to make.

Two more one-liners worth knowing:

```python
>>> dag.nodes["Japan"].descendant_count   # how many things are under Japan?
4
>>> dag.get(["Iceland"])                  # unknown names are simply empty
set()
```

That's the core of OntoDAG. Everything else in this guide is ways to do the same
three things — **put, get, remove** — from files, from the command line, from a
browser, or over the network.

---

## 4. Everyday operations in Python

### 4.1 Adding items: `put`

```python
dag.put("seat-reservation.pdf", ["Flight", "Japan"])
```

Rules of the road:

- **Parents must already exist.** `dag.put("X", ["Nope"])` raises
  `ValueError: One or more super-categories do not exist.` Add categories top-down.
- **No parents means top-level:** `dag.put("Lisbon", [])` files `Lisbon`
  directly under the root `*` — that's how you start the next trip.
- **Names are the identity.** Putting a name that already exists doesn't create a
  duplicate — it adds the new parent links to the existing item.
- **Redundant links are cleaned up automatically.** Say you add
  `dag.put("boarding-pass.png", ["Japan", "japan-outbound.pdf"])`. The `Japan` link
  is redundant — the boarding pass is already part of the trip *via* the flight it
  belongs to — so OntoDAG silently skips it:

  ```python
  >>> sorted(p.name for p in dag.nodes["boarding-pass.png"].parents)
  ['japan-outbound.pdf']
  ```

  You can never make the graph messy this way; it tidies itself. (Why it insists on
  this is explained in [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md) — it's the property the
  whole design rests on.)
- **Cycles are refused.** Categories can't be their own ancestors:

  ```python
  >>> dag.put("Flight", ["boarding-pass.png"])
  ValueError: Edge boarding-pass.png -> Flight would create a cycle.
  ```

(For the record: everywhere this guide passes a name string, an `Item` object —
`from ontodag import Item` — is accepted too; `dag.put(Item("Flight"), ...)` and
`dag.put("Flight", ...)` mean exactly the same thing. Strings are just easier.)

**The `optimized=True` flag.** Sometimes you know some general categories for an
item, and more specific ones already exist that follow from them. With
`optimized=True`, `put` files the item under the *most specific* categories your
list implies, instead of the ones you typed. Example: suppose categories `AB`
(under A and B), `BC` (under B and C), `ABC` (under AB and BC) and `CD` (under C
and D) exist, and you add:

```python
dag.put("E", ["AB", "CD"], optimized=True)
```

E ends up under `ABC` and `CD` — because anything under both `AB` and `CD` is
under A, B, C and D, and `ABC` is a more precise home that already captures three
of those. If that sounds like more thinking than you want to do: that's exactly why
the flag does it for you. When in doubt, leave it off; the default is predictable.

### 4.2 Asking questions: `get`

```python
results = dag.get(["Flight", "Japan"])
for item in results:
    print(item.name)
```

- One or more category names; the answer is everything under **all** of them,
  returned as a set of item objects — each has a `.name` and a
  `.descendant_count`.
- The categories themselves are not in the answer (asking for `Flight` + `Japan`
  returns the flight documents, not `Japan`).
- Unknown category → empty set, no error.
- An empty list raises `TypeError` — a query has to ask *something*.
- Order doesn't matter, and redundant terms are ignored: asking for
  `[Japan, japan-outbound.pdf]` is the same as asking for
  `[japan-outbound.pdf]`, since everything under the flight is already under the
  trip. You can be sloppy; the query planner sorts it out (and picks an efficient
  evaluation order for you — details in the internals doc).

**OR-queries: `get_any`.** `get` is AND; for alternatives, give `get_any` a
list of queries and it returns everything matching *at least one* of them:

```python
dag.get_any([["Flight", "Japan"], ["Hotel"]])   # (Flight AND Japan) OR Hotel
```

Same rules per branch as `get` (an unknown category empties only its own
branch), and it composes with typed values (§4.7) — the classic use is *outside
a range*, which no single AND-query can say:

```python
dag.get_any([["time(..2026-01-01)"], ["time(2026-12-31..)"]])   # before or after
```

On the command line the literal word `or` does the same job
(`odag get Flight Japan or Hotel`), and over REST it's a pipe
(`/dag/query?cat=Flight,Japan|Hotel`).

**Yes/no questions: `is_below`.** When you don't want the list, just the
answer — *does A fit within B?* — there's a direct test:

```python
dag.is_below("boarding-pass.png", "Japan")      # True
dag.is_below("Japan", "boarding-pass.png")      # False — direction matters
dag.is_below("time(2026-08-15)",
             "time(2026-06-01..2026-08-31)")    # True, from the names alone
```

It's the Boolean face of the same fits-within relation: reflexive
(`is_below("Flight", "Flight")` is True), fail-closed on unknown names (False,
never an error), and answered by walking *upward* from A with early exit —
so it's fast even when B is a huge category, and cheap over the network on
a lazy reader. With typed values it needs no graph at all: the last line
above is pure arithmetic, a pocket containment check for dimension terms.

### 4.3 Removing: `remove`

```python
dag.remove("japan-outbound.pdf")
```

What happens to its children? They are **reconnected to its parents**, so
nothing becomes orphaned and no query answer changes except those that mentioned
the removed item itself:

```python
>>> dag.put("gate-info.txt", ["japan-outbound.pdf"])
>>> dag.remove("japan-outbound.pdf")
>>> sorted(p.name for p in dag.nodes["gate-info.txt"].parents)
['Flight', 'Japan']
```

`gate-info.txt` silently moved up to where the flight used to hang — still a
flight document, still part of the trip.

### 4.4 Combining two DAGs: `merge`

```python
mine.merge(theirs)      # everything in `theirs` is now also in `mine`
```

Merging unions the two graphs: all names from both, all category relationships from
both, redundant links pruned as usual. Items with the same name are treated as the
same item (names are the identity — so agree on names before you merge!).

Merge is designed so that **order never matters**: if you merge my DAG into yours
and I merge yours into mine, we end up with identical graphs. That is what lets
several people maintain one shared ontology without a central server — the
persisted form of it is `sync`, in §8.

### 4.5 Pictures

```python
from ontodag import OntoDAGVisualizer

viz = OntoDAGVisualizer(format="png")        # also: "svg", "pdf"
viz.visualize(dag, filename="travel")        # writes travel.png
```

Requires the Graphviz system program (see Installation). The root is drawn shaded;
arrows point from general to specific.

### 4.6 Saving and loading files

OntoDAG reads and writes standard **OWL ontology** files, in two flavors:

```python
from ontodag import OWLOntology

# Human-friendly text format (Manchester syntax) — recommended:
OWLOntology.export_dag_manchester(dag, "travel.omn")
dag2 = OWLOntology.import_dag_manchester(file_name="travel.omn")

# RDF/XML (.owl), for interoperability with other ontology tools:
OWLOntology.export_dag(dag, "travel.owl")
```

`.omn` files are ordinary text you can read and even write by hand — see §7. Both
formats open in standard ontology editors like Protégé.

### 4.7 Typed values: parametric dimensions

Everything so far has sorted itself by the edges you asserted. But dates are the
one thing you always want to ask about travel documents — *what did I book for
last summer?* — and nowhere in a graph of names does it say that 15 August falls
inside June-to-August. **Parametric dimensions** add exactly that: values written
as `time(2026-08-15)` are ordinary categories whose ordering OntoDAG *computes*
from the value, so a "last summer" query matches an August flight with no edge
ever stored between them, at any date range you care to ask.

The no-ceremony path: `odag prelude` (or `ontodag.prelude.apply(dag)` in
Python) declares the everyday dimensions — `weight`, `length`, `duration`,
`time`, `geo`, `size` — in one idempotent merge, and everything below just
works. What it does is nothing special: a dimension is declared by placing
it under one of the four built-in kind categories, which you can always do
by hand (create those like any other category):

```python
dag.put("dimension", [])
dag.put("calendar-dimension", ["dimension"])  # dates, periods and ranges
dag.put("time", ["calendar-dimension"])       # time is now a dimension

# Dates are just more categories to file under.
dag.put("japan-outbound.pdf", ["Flight", "Japan", "time(2026-08-15)"])
dag.put("japan-return.pdf",   ["Flight", "Japan", "time(2026-08-29)"])
dag.put("berlin-flight.pdf",  ["Flight", "time(2026-03-02)"])
```

Now ask for a stretch of time that nobody ever created:

```python
>>> sorted(i.name for i in dag.get(["Flight", "time(2026-06-01..2026-08-31)"]))
['japan-outbound.pdf', 'japan-return.pdf']

>>> sorted(i.name for i in dag.get(["Flight", "time(2026-01-01..2026-12-31)"]))
['berlin-flight.pdf', 'japan-outbound.pdf', 'japan-return.pdf']
```

The same from the command line (**quote the parentheses** in a shell):

```console
$ odag put calendar-dimension dimension
$ odag put time calendar-dimension
$ odag put japan-outbound.pdf Flight Japan 'time(2026-08-15)'
$ odag get Flight 'time(2026-06-01..2026-08-31)'
japan-outbound.pdf
```

What to know:

- **Ranges are `lo..hi`**, either end may be open: `time(..2026-01-01)` (before),
  `time(2026-12-31..)` (after), `time(2026-06-01..2026-08-31)` (between).
  Query terms never need to exist as nodes — ask any range.
- **A day is itself a range.** `time(2026-08-15)` is stored under the canonical
  name `time(2026-08-15T00:00:00Z..2026-08-15T23:59:59Z)` — the whole day — which
  is why it falls inside a summer query. Full timestamps
  (`time(2026-08-15T14:30:00Z)`) work too, for a departure rather than a date.
  On a terminal you'll see the friendly form back (`time(2026-08-15)`); pipes
  get the exact stored bytes, and `odag canon` shows the mapping — see §5.5.
- **Whole years and months are values too**: `time(2026)` is the year,
  `time(2026-08)` the month, and they nest the way you would expect — a document
  filed under `time(2026-08-15)` is inside both. Ranges of them work as well
  (`time(2026-03..2026-08)`). This is what `calendar-dimension` buys you: under
  the plain `linear-dimension` a bare `time(2026)` is the dimensionless *number*
  2026, because there a bare integer is a count. If you declared a time dimension
  that way, the error message says so and names the fix; re-declaring the head
  under `calendar-dimension` changes no stored value.
- **Other dimensions work the same way.** Values are stored as exact rationals
  of the SI anchor unit — `weight(3000g)` is stored as `weight(3kg)`, `500g` as
  `weight(1/2kg)` — so `3kg`, `3000g` and `3.0kg` are one identity, nothing is
  ever rounded, and every exactly-defined unit works: `weight(1lb)`,
  `pressure(32psi)`, `storage(..2TB)` against tebibytes,
  `temperature(24C)` (Celsius and Fahrenheit ride the kelvin scale exactly —
  `-40C` and `-40F` are one stored name), even `length(10/33m)` (the shaku). Beyond the built-ins, **unit packs**
  add vocabulary as graph data — `odag pack crypto-core` (BTC, ETH,
  BZZ — then `price(0.01sat)` works), `odag pack fiat-iso4217` (~150
  national currencies), `odag pack crypto-majors`, `odag pack` to list — and you
  can declare your own unit with one put:
  `odag put 'unit(firkin=9igal)' unit-declaration`. Declarations merge
  and travel with the store, so readers need nothing installed. You don't
  have to memorize any of this: typing `price(5USD)` before adopting a pack
  refuses with the exact command (`odag pack fiat-iso4217`). Run `odag prelude` for the everyday
  dimensions and see the generated docs/UNIT_TABLE.md for the full listing.
- **Two more kinds**: `prefix-dimension` for hierarchical codes
  (`geo(u2ed)` is inside `geo(u2)` — geohash cells, handy for "near Tokyo"), and
  `dominance-dimension` for does-it-fit tuples
  (`size(19x23x39cm)` fits `size(20x30x40cm)` — cabin baggage, rotation free).
  `linear-dimension` is the fourth: numbers with units, which is what
  `weight(3kg)` above uses.
- **A point is not a range.** `weight(3kg)` is *not* below `weight(5kg)` —
  a 3 kg bag is not a special case of a 5 kg one. Use `weight(..5kg)`.
- **An item sits in the intersection of its parents**, so filing one thing
  under two non-overlapping values of the same dimension
  (`time(..2026-01-01)` *and* `time(2026-12-31..)`) is refused with an error. For
  a union — "weekends", a delivery region — make an ordinary category and put
  the values under *it* (`dag.put("time(2026-08-01)", ["weekend"])`, one
  edge per member).
- **Value nodes answer queries too.** A bare `dag.get(["time(2026-08-01..)"])`
  returns the matching `time(...)` categories alongside your documents — they are
  ordinary categories and they genuinely satisfy the query. Pair the date with a
  real category (`["Flight", "time(...)"]`, as above) when you want documents only.

**Guaranteed vs. possible: `get_overlapping`.** `get` on a range answers
*guaranteed* satisfaction — everything whose value certainly fits. Often you also
want the maybes: a flexible ticket valid over a week *might* cover your date. That
is a separate question (Python API only):

```python
dag.put("fixed-ticket.pdf",    ["time(2026-08-15)"])              # that day
dag.put("flexible-ticket.pdf", ["time(2026-08-14..2026-08-20)"])  # any day that week

dag.get(["time(2026-08-15..2026-08-16)"])            # fixed only — guaranteed
dag.get_overlapping("time(2026-08-15..2026-08-16)")  # both — possibly
```

Overlap can't be expressed as a category (it isn't transitive), which is why
it's its own method rather than more `get` syntax; use it to generate
candidates, then check the survivors exactly.

The full design (why the order is computed rather than stored, and what that
preserves) is in [DIMENSIONS.md](DIMENSIONS.md).

---

## 5. The command line

Everything in §4 can be done without writing any Python. The command is `odag`, and
it behaves like an ordinary Unix tool: **it works on a persistent store, prints
nothing on success, sends errors to stderr, and pipes cleanly**. If you installed
with pip you have the `odag` command; otherwise use `PYTHONPATH=src python3 -m
ontodag` from the repository root.

```
odag <command> ...

  put SUB [PARENT...]   add SUB under the PARENT categories (or the root)
  get [CAT...]          print items below all of the CATs, one per line
                        (the literal word `or` separates alternatives:
                        `get Flight Japan or Hotel` = (Flight AND Japan) OR Hotel).
                        With no CAT at all: everything (§5.6)
  count [CAT...]        how many items that query matches — one number,
                        complete, never capped
  below SUB SUP       does SUB fit within SUP? prints true/false and
                        exits 0/1 (grep-style); `?` works at the prompt
  index [--threshold N] for swarm: stores — publish cone summaries (a
                        derived index in a sibling NAME-index store) so
                        lazy readers answer broad queries in a few
                        fetches; prints the data and index roots
  remove ITEM           remove ITEM from the store
  show                  print the DAG structure
  list                  print every item name (the empty query, named)
  merge FILE            merge FILE into the store
  import FILE           replace the store with the contents of FILE
  export FILE           write the store to FILE
  visualize [--out B]   render the DAG to an image
  canon [TERM]          print TERM's canonical form — what would actually
                        be stored; with no TERM, the surface/registry
                        versions (see §5.5)
  prelude [--show]      adopt the standard dimension declarations (weight,
                        time, geo, size, ...) in one idempotent merge;
                        --show prints them without merging
  set [KEY [VALUE]]     show settings, or set one durably (store, bee_api,
                        bee_batch, bee_signer, render, limit — see §5.7)
  help                  show this help
```

Run `odag <command> --help` for the options of each.

### 5.1 The store

There is no file to create first. `odag` keeps a default store in a hidden directory
in your home — `~/.ontodag/store.od` — and every command reads and writes it. So
you can start adding things immediately, and `odag put cat` / `odag get cat` just work.

The store is a canonical, line-oriented text file (one item per line, `name
parent1 parent2 …`), so it diffs and merges cleanly in git. Point at a different
store for one command with `-f PATH`, or change the default permanently with
`set store PATH`:

```console
$ odag set store ~/work/travel.od      # writes ~/.ontodag/config; silent
$ odag set                           # show every setting
store = /home/you/work/travel.od
bee_api = http://localhost:1633
bee_batch =
bee_signer =
$ odag set store                     # show just one (no value = display, never an error)
store = /home/you/work/travel.od
```

`set KEY VALUE` changes a setting; `set KEY` on its own displays it; `set`
alone lists them all. The settings are `store` and — for the Swarm backend
below — `bee_api`, `bee_batch` and `bee_signer`.

Files ending in `.owl` or `.omn` are read and written as OWL / Manchester syntax
instead of the native format — so `odag -f travel.omn get Flight` works directly on an
ontology file, and `export`/`import` convert between them.

**Storing on Swarm.** A store can also live on [Ethereum Swarm](https://www.ethswarm.org/)
instead of a local file. It needs a few extra dependencies — install them once with
`pip install "ontodag[swarm]"`, which brings `requests` (talking to the Bee node),
`swarmfs` (picking a postage batch when `bee_batch` is left at `auto`) and
`swarm-bee` (signing feed updates). Miss them and you get a clear message saying
which. Then set the store once and it sticks:

```console
$ odag set store swarm:travel     # every later command now uses Swarm
$ odag put Flight
$ odag get Flight
```

The DAG's content is written to a Bee node (content-addressed, immutable). Where
the pointer to the *latest* version lives depends on whether you give `odag` a
signing key:

- **No key (the default).** The latest root is kept locally at
  `~/.ontodag/travel.root`, so you can start with nothing but a node. Nothing is
  publishable: to let someone else read your store you would have to pass them
  a root hash by hand.
- **With a key** (`BEE_SIGNER`, or `bee_signer` in the config) the latest root
  goes into a **Swarm feed** — an owner-signed, stable address that always
  resolves to your newest version, so others can follow the store rather than
  chase hashes. Same command, one setting.

Point `odag` at your node with the `BEE_API` and `BEE_BATCH` environment
variables, or `bee_api` / `bee_batch` lines in `~/.ontodag/config`; the batch
defaults to `auto`, which picks the usable batch with the longest TTL on the
node — it only ever *selects*, never buys, so no command spends your xBZZ
behind your back. Writes need a funded
[postage batch](https://docs.ethswarm.org/docs/develop/access-the-swarm/buy-a-stamp-batch).

**When the node is down.** Every command on a `swarm:` store opens the store
before it does anything else, and opening talks to the node: `auto` has to ask
it which batches exist, and a non-empty store has to be read back. So with Bee
stopped, even `odag get` fails — but it fails cleanly, with one line on stderr,
exit status 1, nothing written, and a reminder of the ways out:

```console
$ odag get Flight
odag: cannot reach the Bee node at http://localhost:1633, needed by store 'swarm:travel' (Cannot connect to host localhost:1633 ssl:default [Connect call failed ('127.0.0.1', 1633)])
  * start your Bee node, then run this again
  * or work locally for one command:  odag -f /home/you/.ontodag/store.od ...
  * or switch back to local storage:  odag set store /home/you/.ontodag/store.od
    (local is the default and needs no node: one text file, nothing published)
```

`odag` will not silently fall back to the local store: writing to a store other
than the configured one would let the two diverge, with nothing to say afterwards
which is authoritative. It also won't start your node for you. Switch back to a
file any time with `odag set store PATH` — and note that a `set store` setting is
saved even when the store can't be opened right now, so you can point `odag` at a
Swarm store first and start the node afterwards.

### 5.2 A complete worked session

Build the travel store from nothing — each `put` is silent on success:

```console
$ odag put Flight
$ odag put Hotel
$ odag put Japan
$ odag put japan-outbound.pdf Flight Japan
$ odag put japan-return.pdf Flight Japan
$ odag put hotel-tokyo.pdf Hotel Japan
```

Look at what you have:

```console
$ odag show
* [root] -> Flight Hotel Japan
Flight (*) -> japan-outbound.pdf japan-return.pdf
Hotel (*) -> hotel-tokyo.pdf
Japan (*) -> hotel-tokyo.pdf japan-outbound.pdf japan-return.pdf
hotel-tokyo.pdf (Hotel Japan) ->
japan-outbound.pdf (Flight Japan) ->
japan-return.pdf (Flight Japan) ->
```

(Each line lists an item, its parents in brackets, then its children. Parents
always come before their children, and items that could go in either order are
listed alphabetically — so the same content always prints the same way, whoever
built it and in whatever order. You can diff this output, and the stored file
too: it is sorted and byte-identical for equal content, which is what makes the
git habit below work.)

Ask which documents are flights for the Japan trip — one name per line, straight
to stdout:

```console
$ odag get Flight Japan
japan-outbound.pdf
japan-return.pdf
```

Alternatives use the literal word `or` between groups — everything that is a
Japan flight, *or* any hotel booking at all:

```console
$ odag get Flight Japan or Hotel
hotel-tokyo.pdf
japan-outbound.pdf
japan-return.pdf
```

And for a plain yes/no there's `below`, which also sets the exit code
(0 = true, 1 = false, like `grep`), so it slots straight into shell logic:

```console
$ odag below hotel-tokyo.pdf Japan
true
$ odag below hotel-tokyo.pdf Flight
false
$ odag below hotel-tokyo.pdf Japan && echo "it belongs to the trip"
true
it belongs to the trip
```

(At the interactive `>` prompt, `? hotel-tokyo.pdf Japan` is a synonym — no shell
there to fight over the question mark.)

File the boarding pass under the flight it belongs to, then ask for the whole
trip; nobody typed "the boarding pass is part of Japan" — being under the outbound
flight was enough:

```console
$ odag put boarding-pass.png japan-outbound.pdf
$ odag get Japan
boarding-pass.png
hotel-tokyo.pdf
japan-outbound.pdf
japan-return.pdf
```

Remove an item (children reconnect to its parents automatically), and list every
name:

```console
$ odag remove hotel-tokyo.pdf
$ odag list
Flight
Hotel
Japan
boarding-pass.png
japan-outbound.pdf
japan-return.pdf
```

Because output is plain lines, it pipes:

```console
$ odag get Japan | wc -l
3
$ odag get Japan | grep boarding
boarding-pass.png
```

### 5.3 Pipes, scripts and interactive mode

Run with no command and `odag` reads commands from standard input — one per line,
`#` comments allowed — which makes stores scriptable:

```console
$ printf 'put hotel-kyoto.pdf Hotel Japan\nget Hotel\n' | odag
hotel-kyoto.pdf
```

Run it with no command on a terminal and you get an interactive prompt instead:

```console
$ odag
Ontodag 0.10.1 - type help for help
> put insurance.pdf Japan
> get Japan
boarding-pass.png
hotel-kyoto.pdf
insurance.pdf
japan-outbound.pdf
japan-return.pdf
> quit
```

### 5.4 Converting, merging and drawing

`export` writes the current store to a file; the format follows the extension.
`import` replaces the store from a file; `merge` folds another file in (shared
category names knit the two together). All three are silent on success:

```console
$ odag export travel.owl              # native store -> OWL
$ odag export travel.omn              # -> Manchester syntax
$ odag merge lisbon.omn             # fold the next trip into the store
$ odag visualize --format svg --out travel
```

`visualize` accepts `--format png|svg|pdf` and `--out NAME` for the output name.
`put` accepts `--optimized` (see §4.1). `get`, `show` and `list` accept `-o FILE`
to write to a file instead of stdout.

Useful habits:

- The native store is line-oriented text; keep `~/.ontodag` (or a `-f` store) in a
  git repository and diffs stay readable, merges reviewable.
- Item names with parents are positional: `odag put ITEM PARENT1 PARENT2 …`. Omit the
  parents to add a top-level category.
- If a parent doesn't exist yet, the command changes nothing and reports on stderr
  with a non-zero exit code: `odag: One or more super-categories do not exist.`

### 5.5 Readable output: friendly on screen, exact in pipes

Typed values are stored in an exact canonical form — `time(2026-08-15)` is
really `time(2026-08-15T00:00:00Z..2026-08-15T23:59:59Z)`, `weight(500g)` is
`weight(1/2kg)` (a rational of the SI anchor unit) — which is what makes equal
knowledge produce equal fingerprints. You shouldn't have to *read* that, so `odag` renders friendly
spellings **on a terminal** and prints the exact canonical bytes **whenever
output goes to a pipe, a file, or `-o`** — so `odag get ... | odag` always
round-trips, and scripts never see a "pretty" name. The same store, both
ways (`--render` forces the friendly form even in a pipe; `--raw` forces
canonical even on a terminal):

```console
$ odag list            # piped: exact canonical bytes
Flight
Japan
calendar-dimension
dimension
time
time(2026-08-15T00:00:00Z..2026-08-15T23:59:59Z)
tokyo-flight
$ odag list --render    # what a terminal shows by default
Flight
Japan
calendar-dimension
dimension
time
time(2026-08-15)
tokyo-flight
```

Rendering never changes what is stored, and it only ever uses spellings the
parser accepts, so a friendly name typed back in means exactly the same
thing. `ONTODAG_SURFACE=0`/`1` sets the default (flag beats env, env beats
the terminal test), and the rule applies to output only — input always
accepts every spelling.

When you want to see precisely what a spelling means, `canon` prints the
stored form of any term, and `canon` alone reports the rendering layer's
versions:

```console
$ odag canon "time(2026-08-15)"
time(2026-08-15T00:00:00Z..2026-08-15T23:59:59Z)
$ odag canon
surface 0.1
registry 4.0
```

### 5.6 Asking for everything, and how much output you get

A query with **no categories is not an error — it is everything**. Asking for
items below all of nothing places no constraints, so nothing is excluded. That
makes these three the same question, and `list` is simply the discoverable name
for it:

```console
$ odag get
Flight
Hotel
Japan
japan-hotel.pdf
japan-outbound.pdf
$ odag list          # identical
$ odag get '*'       # identical (`*` is the root every item sits under)
```

The one thing that is still an error is a **dangling `or`** — `odag get Flight
or`. At that point the empty part is a typo, and reading it as "everything"
would silently turn a narrow query into a full dump.

When you only want the size of an answer, `count` gives it as one number. It
runs the same queries as `get` and is never truncated:

```console
$ odag count
5
$ odag count Japan
2
```

**The display cap.** Because `odag get` can now print your whole store, results
stop at 50 lines when you are typing at a terminal, with a note on stderr saying
what was held back:

```console
$ odag get -n 2
Flight
Hotel
odag: 3 more not shown (-n 0 for all, or `odag count` for the total)
```

This is a *display* decision and follows the same rule as readable output
(§5.5): **a pipe is never capped.** The query is always complete, so `odag get |
wc -l` counts every result and `odag get | odag put` still round-trips — the cap
exists to protect your screen, never to shorten an answer something else is
going to read. Use `-n N` for a different cap, `-n 0` for all of it. The
withheld note goes to stderr, so it never lands in the data even when you pass
`-n` with a pipe.

### 5.7 Settings: four ways to set them, one rule

There are six settings, and every one of them can be given in the same four
ways. The first that is present wins:

**flag → environment variable → config file → default**

| Setting | Flag | Environment | What it does |
| --- | --- | --- | --- |
| `store` | `-f PATH` | `ONTODAG_STORE` | which store to use: a path or `swarm:NAME` |
| `limit` | `-n N` | `ONTODAG_LIMIT` | max result lines (§5.6) |
| `render` | `--render` / `--raw` | `ONTODAG_SURFACE` | readable or canonical names (§5.5) |
| `bee_api` | `--bee-api URL` | `BEE_API` | Bee node endpoint (§8) |
| `bee_batch` | `--bee-batch ID` | `BEE_BATCH` | postage batch paying for Swarm writes |
| `bee_signer` | `--bee-signer KEY` | `BEE_SIGNER` | key that publishes the root to a signed feed |

The layers differ in **how long they last**, which is the useful way to choose
between them: a flag is for one command, an environment variable for one shell,
and `odag set KEY VALUE` is the durable one — it writes `~/.ontodag/config` and
applies to every later invocation. `odag set` with no arguments prints what is
currently in effect, whichever layer it came from:

```console
$ odag set
bee_api = http://localhost:1633
bee_batch =
bee_signer =
limit = auto
render = auto
store = /home/you/.ontodag/store.od
```

`auto` is a real value, not a missing one: it means *decide from whether output
is a terminal*. Setting `limit` or `render` explicitly overrides that decision
in both directions.

The flags all go **before** the command (`odag -n 5 get Japan`), where they
apply to every command in a batch or interactive session; `get`, `list` and
`show` also accept `-n` and `--render`/`--raw` after the command, for that one
command only.

---

## 6. The web app and REST API

The web app gives you the same DAG in a browser — with live pictures — plus an HTTP
API you can script against.

```bash
cd web
python3 app.py          # starts http://localhost:5000  (needs the [web] extra)
```

Open **http://localhost:5000** in any browser for the interactive UI: add items,
run queries, watch the graph redraw, import and export files. There is also a
self-contained demo of a used-car marketplace built on OntoDAG at
**http://localhost:5000/market** — categories like fuel type, body style and
price band form the DAG, and buyer searches are DAG queries.

**What the page gives you.** Two panels. The top one is the whole DAG: a text
listing, a picture that redraws after every change (click it for full size),
and buttons to start a new DAG, import a file, or export OWL / Manchester /
DOT / LaTeX. The bottom one is a query: type comma-separated categories, and
you get the matching items plus a picture of the query and its results, with
the query terms shaded differently from what they matched.

Typed values work in both boxes exactly as they do everywhere else — file
something under `weight(3kg)` and `time(2026-08-15)`, then query
`weight(..5kg)`, and the virtual term resolves without any node existing for
it; the query picture shows the term itself above what it matched, even
though no such node is stored. Union is available too, with `|` between
alternatives (`Flight,Japan|Hotel`), drawn as the two branches it is, and an
empty query box means everything.

Two limitations worth knowing, both deliberate rather than broken: the browser
UI shows **canonical** names, not the friendly spellings the CLI renders on a
terminal (so you will see the full timestamp range rather than `time(2026)`),
and the web app keeps its DAG **in server memory per session** — it is not
backed by your `odag` store and cannot use Swarm. It is a workbench and a
demo, not a second front end onto the same data.

### 6.1 Scripting it with curl

Each browser session gets its own private DAG (a session cookie keeps them apart),
so tell curl to remember cookies with `-c`/`-b`:

```console
$ curl -s -c cookies.txt -X POST http://localhost:5000/dag
{
  "message": "New OntoDAG created."
}

$ curl -s -b cookies.txt -X POST http://localhost:5000/dag/node \
    -H "Content-Type: application/json" \
    -d '{"subcategories": ["Flight", "Hotel", "Japan"]}'
{
  "message": "Item(s) inserted."
}

$ curl -s -b cookies.txt -X POST http://localhost:5000/dag/node \
    -H "Content-Type: application/json" \
    -d '{"subcategories": ["japan-outbound.pdf", "japan-return.pdf"],
         "super_categories": ["Flight", "Japan"]}'
{
  "message": "Item(s) inserted."
}
```

(`super_categories` omitted = top-level. Several `subcategories` at once is fine.)

Query — categories comma-separated in the `cat` parameter:

```console
$ curl -s -b cookies.txt "http://localhost:5000/dag/query?cat=Flight,Japan"
{
  "nodes": [
    {
      "descendant_count": 0,
      "name": "japan-return.pdf",
      "neighbors": []
    },
    {
      "descendant_count": 0,
      "name": "japan-outbound.pdf",
      "neighbors": []
    }
  ]
}
```

Remove items:

```console
$ curl -s -b cookies.txt -X DELETE http://localhost:5000/dag/node \
    -H "Content-Type: application/json" -d '{"subcategories": ["japan-return.pdf"]}'
{
  "message": "Item(s) removed."
}
```

Export your session's DAG (Manchester text arrives on stdout; also `/dag/export`
for .owl, `/dag/export/dot` and `/dag/export/tex` for Graphviz/LaTeX sources):

```console
$ curl -s -b cookies.txt http://localhost:5000/dag/export/omn
Prefix: : <urn:ontodag_…#>
…
Class: :japan-outbound.pdf
    SubClassOf: :Flight, :Japan
…
```

Import a file into the session (it merges into whatever is already there):

```console
$ curl -s -b cookies.txt -X POST http://localhost:5000/dag/import \
    -F "file=@travel.omn"
{
  "message": "File imported and DAG created."
}
```

Pictures over HTTP — the whole DAG or a query result:

```console
$ curl -s -b cookies.txt http://localhost:5000/dag/image -o dag.png
$ curl -s -b cookies.txt "http://localhost:5000/dag/query/image?cat=Flight,Japan" -o result.png
```

> **You don't need to load the page first.** Every endpoint sets up whatever
> session state it needs, so a curl-only client works from its first call.
> (Before 2026-08-02 the image and DOT/LaTeX endpoints returned a `KeyError:
> 'visualizer'` traceback unless a browser had loaded `/` in the same session.)

Endpoint summary:

| Method & path                | What it does                                   |
|------------------------------|------------------------------------------------|
| `POST /dag`                  | Start a fresh, empty DAG in your session       |
| `GET /dag`                   | The whole DAG as JSON                          |
| `POST /dag/node`             | Add item(s): `{"subcategories": [...], "super_categories": [...]}` |
| `DELETE /dag/node`           | Remove item(s): `{"subcategories": [...]}`     |
| `GET /dag/query?cat=A,B`     | Everything under all the listed categories (`\|` for OR: `cat=A,B\|C` = (A AND B) OR C). Omit `cat` for the empty query — every item (§5.6) |
| `GET /dag/below?sub=A&sup=B` | Yes/no: does A fit within B? → `{"below": true}` |
| `GET /dag/stats/queries`     | Query workload so far, most-asked first (per category-set) |
| `GET /dag/image`             | PNG of the DAG                                 |
| `GET /dag/query/image?cat=…` | PNG of a query and its results                 |
| `POST /dag/import`           | Merge an uploaded `.owl`/`.omn` file into the session |
| `GET /dag/export`            | Download as `.owl` (RDF/XML)                   |
| `GET /dag/export/omn`        | Download as Manchester syntax                  |
| `GET /dag/export/dot`, `/dag/export/tex` | Graphviz DOT / LaTeX source        |

The same `export`/`import` endpoints exist under `/dag/query/…` operating on the
result of your last query instead of the whole DAG.

> The dev server is for local, personal use. Don't expose it to the internet as-is.

---

## 7. The file format, briefly

A `.omn` (Manchester syntax) file is just the DAG written as OWL classes:

```
Class: :japan-outbound.pdf
    SubClassOf: :Flight, :Japan
```

reads as "japan-outbound.pdf is a subclass of Flight and of Japan" — exactly
OntoDAG's `put("japan-outbound.pdf", ["Flight", "Japan"])`. When OntoDAG writes the file itself you'll also see a
class named `*` (the root) and `Prefix:`/`Ontology:` header lines; when writing by
hand you can skip the root — top-level classes are attached to it automatically.

Because these are standard OWL constructs, your files open in ontology tools such
as **Protégé**, and conversely, the class hierarchy of an existing OWL ontology can
be imported into OntoDAG (`odag -f yourfile.owl show` — OntoDAG reads the
subclass-of skeleton and ignores everything else).

---

## 8. Experimental: saving your DAG to Swarm

OntoDAG can persist itself through a **content-addressed record store** — the
storage model used by [Ethereum Swarm](https://www.ethswarm.org/), a decentralized
network where data is retrieved by the fingerprint of its content. Support ships
today as `EagerOntoDAG`; here it is over an in-memory store (no network needed):

```python
from ontodag import EagerOntoDAG
from recordstore import RecordStore, MemoryBytesStore

store = RecordStore(MemoryBytesStore())
dag = EagerOntoDAG(store)

dag.put("Flight", [])
dag.put("japan-outbound.pdf", ["Flight"],
        payload="swarm-ref-of-the-scan",         # optional: content this item tags
        meta={"content-type": "application/pdf"})  # optional: free-form metadata

root = dag.commit()      # every commit returns a fingerprint of the whole DAG
```

That `root` string *is* your ontology-at-this-moment: anyone holding it (and the
store) can reconstruct exactly this DAG, and the same DAG always produces the same
root, no matter in what order it was built. Re-committing without changes returns
the identical root. A `EagerOntoDAG` constructed over a store with existing data
loads it automatically and behaves like any other OntoDAG.

To store on the real Swarm network instead of memory, the one-liner is
`recordstore.swarm_store`, which puts both halves on Swarm — the content in a Bee
node and the "latest version" pointer in a signed Swarm feed, so the store has a
stable address others can follow:

```python
from recordstore import swarm_store

store = swarm_store("my-ontology", signer=private_key_hex)   # publish
store = swarm_store("my-ontology", owner=address_hex)        # follow someone's
dag = EagerOntoDAG(store)
```

(It needs a running node and a usable postage batch; the CLI wires the same thing
up from `$BEE_API` / `$BEE_BATCH` / `$BEE_SIGNER` — see §5. For durable storage
with no Swarm at all, `recordstore.DirBytesStore` keeps the blobs in a local
directory.)

### Several writers, one ontology

Because equal knowledge has an equal root, two people editing copies of the
same ontology can *converge without a server*: each folds the other's
published version in with `sync`, and both end up holding the byte-identical
root —

```python
merged_root = my_dag.sync(their_root)   # fold theirs in, commit the union
```

`sync` is `merge` (§4.4) plus persistence: assertions union, redundant links
are re-pruned, order never matters, and syncing something you already have
changes nothing. Two things follow from "the union wins" that are worth
knowing: a removal does not survive a collaborator's concurrent re-assertion,
and typed values renormalize across writers — if you filed a ticket under
`time(2026-08-01..2026-08-31)` and your collaborator filed it under
`time(2026-08-15)`, after syncing both of you hold just the `time(2026-08-15)`
link, because the coarser one is implied (§4.7).

### Cone summaries: making broad queries cheap for readers

A lazy reader (below) pays roughly one fetch per item in the *narrowest*
cone it queries — fine for `get(["boarding-pass.png"])`, painful for
`get(["Flight", "Document"])` on a big store. A publisher can remove that
cost by shipping a small **derived index** next to the ontology: one record
per broad category stating its cone, so a reader fetches the answer instead
of walking it.

```python
from ontodag.cones import ConeIndex, build_index

index_store = RecordStore(MemoryBytesStore())     # a SEPARATE store
index_root = build_index(dag, index_store, root)  # derived from `root`

reader = LazyOntoDAG(RecordStore.at(root, store.blobs),
                     cone_index=ConeIndex(index_store, root))
```

The index never touches the ontology's own root (same knowledge, same
fingerprint, with or without an index), it is regenerable at will, and the
reader treats it as a cache with an exact fallback: if it is stale, missing a
category, or built by a different ontodag version, the reader silently walks
instead — slower, never wrong. Measured on the test fixture, a two-broad-term
query dropped from 375 fetches to 3. From the command line, `odag index`
publishes exactly this pair for a `swarm:` store (see the command table in
§5) — validated on a real node: 71 fetches down to 1 + 2.

### Querying a published DAG without downloading it

`EagerOntoDAG` loads every record when it opens, which is what makes editing and
committing straightforward — but it means opening someone's million-item
ontology downloads a million records before you can ask anything.
`LazyOntoDAG` is the other end of that trade: it fetches records *as the query
walks them*, so cost scales with the question, not with the store.

```python
from ontodag import LazyOntoDAG

dag = LazyOntoDAG(swarm_store("my-ontology", owner=address_hex))
print([item.name for item in dag.get(["Flight", "Japan"])])
print(dag.fetches)      # how many records that actually cost
```

On a 3,200-item published store a specific query touches a few dozen records.
It is **read-only by construction** — for reading, that is the right contract.
(The names describe *residency*, not storage: every variant takes any record
store, and none is tied to Swarm.)

**Editing without downloading everything** is `SparseOntoDAG`: the same
on-demand residency, with the full `put`/`remove` semantics on top.

```python
from ontodag import SparseOntoDAG
from recordstore import RecordStore

dag = SparseOntoDAG(RecordStore(blobs, root=published_root))  # writable
dag.put("boarding-pass.png", ["japan-outbound.pdf"])
new_root = dag.commit()        # stages only what actually changed
```

A write fetches just what it touches — the new item's parents, their
ancestors, whatever the tidy-graph rules need to check — and `commit()`
stages only the records that really changed: adding one item to a
447-record store costs about 7 fetches and writes about 7 records, and the
resulting root is byte-identical to what a fully-loaded editor would have
produced. Use `EagerOntoDAG` when you are editing most of a graph anyway
(or merging whole ontologies), `SparseOntoDAG` for surgical edits to big
published ones, `LazyOntoDAG` to only ask questions.

Once a store lives on Swarm, it can also be **browsed as a filesystem** with
[ontodag-fs](https://github.com/petfold/ontodag-fs): directory paths are
category queries (`/pet/dog` = everything that is a pet AND a dog), files are
classified objects, and the whole thing FUSE-mounts. Its `odag-fs` command
shares odag's store settings, so `odag set store swarm:pets` configures both.

---

## 9. AI agents and verifiable answers

### 9.1 `odag-mcp`: your store as an agent tool

Any store `odag` can open can also be served to an AI agent over MCP (the
Model Context Protocol) with the `odag-mcp` command — no extra
dependencies, and it shares `odag`'s settings, so it serves your default
store unless you point it elsewhere with `-f`. For Claude Code:

```console
$ claude mcp add odag -- odag-mcp
```

The agent gets six tools: `about` (what is this store — size, top-level
categories, declared dimensions, versions), `query`, `is_below`,
`overlapping`, `describe`, and `canon`. Every answer cites the **root** it
is true of — a fingerprint of the store's entire content — and echoes the
canonical form of what it answered, so an agent always sees what is
actually stored rather than what it typed. Friendly spellings come along
in a separate `display` field, never in place of the name.

Read-only is the default. Start the server with `odag-mcp --write` (a
`swarm:` store plus a configured `bee_signer`) and the agent also gets a
propose → confirm write flow — it is always shown exactly what would be
stored, against exactly which version, before anything changes — where
every accepted change carries a signed **provenance record** (who asserted
what, against which state), removals emit retractions, and a `review` tool
shows any claim's audit trail and whether *you* accept it under your own
trust list. Claims merge; acceptance is policy.

### 9.2 Certificates: answers a stranger can check

`is_below` answers can carry a **certificate**: a bundle of cryptographic
proofs (over the store's content-addressed records) that lets anyone
holding only the root fingerprint verify the answer — no access to your
store, no trust in you or your server. Agents request it with
`certify: true`; in Python:

```pycon
>>> from recordstore import MemoryBytesStore, RecordStore
>>> import ontodag
>>> from ontodag.certificates import prove_below, verify_below
>>> dag = ontodag.EagerOntoDAG(RecordStore(MemoryBytesStore()))
>>> for name, parents in [("dimension", []),
...                       ("linear-dimension", ["dimension"]),
...                       ("weight", ["linear-dimension"]),
...                       ("parcel", ["weight(3kg)"])]:
...     dag.put(name, parents)
>>> root = dag.commit()
>>> cert = prove_below(dag, "parcel", "weight(..5kg)")
>>> cert["result"], len(cert["proofs"])
(True, 8)
>>> # elsewhere, holding only the certificate and the root:
>>> verify_below(cert, root)
True
```

The certificate is plain JSON and survives any transport; verification
re-runs the real subsumption check over cryptographically authenticated
records, so a tampered certificate fails loudly and a wrong answer cannot
be validated. Both answers work — "parcel fits" and "parcel does not fit"
are equally provable. The design details live in `docs/CONTRACT.md` (what
any program may rely on) and `docs/AGENT_SURFACE.md` (the tool shapes).

## 10. Rules OntoDAG enforces (and why you'll be glad)

These behaviors are guarantees, not accidents. You can rely on them:

1. **No cycles, ever.** An attempt to make a category its own ancestor is refused
   with a clear error, and the graph is untouched.
2. **No redundant links, ever.** If a relationship is already implied
   (boarding-pass → Japan when boarding-pass → japan-outbound.pdf → Japan
   exists), it is not stored; if adding a link
   makes an old one redundant, the old one is dropped. Your graph is always the
   minimal, tidy version of itself.
3. **Order never matters.** Add parents in any order, merge in any order, build the
   same content by any history — you get the identical graph.
4. **Names are the identity.** The name string *is* the item: `"Flight"` here and
   `Item("Flight")` there refer to the same thing, in one DAG or across DAGs. There
   are no duplicate names and no hidden IDs.
5. **Counts are always right.** `descendant_count` is kept exactly consistent with
   the graph after every operation.
6. **Removal never orphans.** Children of a removed item reattach to its parents
   — including the computed ones: remove `time(2026-08-15)` and a ticket that
   was once explicitly under `time(2026-06-01..2026-08-31)` is under it again.
7. **One dimension, one meaning.** A dimension's values must share one unit
   family (no seconds in a mass dimension), links *between* two values of the
   same dimension are refused (their order is computed, not asserted), and
   filing an item under provably disjoint values of one dimension is refused
   (see §4.7).
8. **Typed values are exact.** No floats anywhere: rationals of SI anchors,
   scaled exactly or refused. `weight(3kg)`, `weight(3000g)` and
   `weight(3.0kg)` are byte-for-byte the same stored name.

(Each of these is enforced by a dedicated test suite — see the internals doc.)

---

## 11. Troubleshooting

**`error: externally-managed-environment` when installing**
Your distribution reserves the system Python for its own package manager. Use
pipx (command only), a virtual environment (command + library), or
`--break-system-packages` — see §2.

**pipx: `'ontodag' already seems to be installed`**
A pipx environment of that name exists already. `pipx upgrade ontodag` to move
it to the current release, `pipx install --force ontodag` to rebuild it from
scratch, or `pipx uninstall ontodag` to drop it. If `pipx list` also says
`odag (symlink missing or pointing to unexpected location)`, something else —
usually a `pip install --user` of the same package — overwrote pipx's shim;
`pipx reinstall ontodag` restores it, but decide which of the two you actually
want on your `PATH` first.

**`ModuleNotFoundError: No module named 'ontodag'`**
Run `pip install ontodag`. If you installed with pipx, that deliberately gives
you the `odag` command only, not an importable library — use a virtual
environment instead (§2). If you're working from a source checkout, either
`pip install -e .` or prefix with `PYTHONPATH=src` (from the repository root).

**`ModuleNotFoundError: No module named 'owlready2'` (or `graphviz`, `flask`)**
A dependency is missing — `pip install ontodag` for the basics,
`pip install "ontodag[web]"` for the web app.

**`graphviz.backend.execute.ExecutableNotFound: failed to execute 'dot'`**
The Graphviz *system program* isn't installed (the Python package is just a
wrapper). `sudo apt install graphviz` / `brew install graphviz`.


**`ValueError: One or more super-categories do not exist.`**
Parents must be added before children. Check spelling — names are case-sensitive.

**A query returns nothing, but I'm sure there are results**
Check the names (case matters: `flight` ≠ `Flight`). An unknown category makes the whole
answer empty, because nothing can be under a category that doesn't exist.

**A query with no categories printed my whole store**
That is what it means: no constraints, nothing excluded (§5.6). `odag count`
tells you how big the answer is without printing it.

**`odag: cannot reach the Bee node at http://localhost:1633 …`**
Your store is set to `swarm:NAME` and the node isn't running. Start Bee, or work
locally — the message lists both escapes (§5.1). Nothing was written.

**`odag: the swarm backend needs an optional dependency that is not installed`**
`pip install "ontodag[swarm]"`. Note this hits you on *every* command against a
swarm store, including reads, because the store is opened before anything else runs.

**`odag: no usable postage stamp …` or a 402 on write**
The node answered, but has no batch it can write with. Buy or top up a postage
batch; `odag` only ever *selects* one, it never spends your xBZZ. A batch that is
full rather than expired needs diluting, not renewing.

**My web DAG disappeared**
Each browser session has its own DAG, held in memory. Restarting the server or
losing the session cookie starts you fresh. Export to a file (`/dag/export/omn`)
when you want to keep something.
