# The Accidental Operating System

*Draft blog post, 2026-08-20. Working title; alternatives at the end.*

---

We didn't set out to build an operating system. We set out to build small
things, each with a one-line job: a category lattice with a canonical
form ([OntoDAG](https://github.com/petfold/ontodag)), a versioned record
store over content-addressed storage
([recordstore](https://github.com/petfold/recordstore)), a filesystem
where directories are queries
([ontodag-fs](https://github.com/petfold/ontodag-fs)), a catalog that
knows which backup drive holds which file (datacat), and a middleware
that treats every chat, inbox and feed as one kind of thing
([ucomm](https://github.com/petfold/ucomm)).

Then we drew the diagram, and laughed, because we had seen it before —
in every operating systems textbook:

| classic OS layer | this stack |
|---|---|
| block device | recordstore over Swarm (content-addressed, versioned) |
| filesystem | ontodag-fs (directories are queries; one file, several true names) |
| namespace | OntoDAG (the category lattice itself) |
| volume manager | datacat (which media hold which bytes; redundancy as a report) |
| IPC & notifications | ucomm (channels, envelopes, one inbox) |
| scheduler | ucomm's attention layer (the scarcest resource is you) |
| standard library | the prelude and packs (shared vocabulary, adopted by merge) |
| users & keys | SwarmID (arriving from the ecosystem, not from us) |

An operating system for machines manages compute, memory and devices.
This one manages the other scarce resources of a person's life: **what
you know, what you keep, and what gets your attention.**

## Not a product — a set of conventions

Unix was never a monolith either. What made it an operating system was
a small set of conventions — everything is a file, programs compose
through pipes, text is the universal interface — that let independently
written tools behave like one system.

The equivalent conventions here fit on an index card:

1. **A path is a query.** Categories form a multi-parent lattice, not a
   tree; a thing lives under every path it belongs to, and browsing is
   querying.
2. **Equal knowledge has equal bytes.** The lattice is kept in a
   canonical form (the transitive reduction of a DAG is unique), so the
   same facts produce the same content hash whoever writes them, in
   whatever order. Two replicas that know the same things *are* the
   same bytes — which makes merge a fold instead of a negotiation.
3. **Everything is regenerable except the human layer.** Machine-derived
   facts (file types, senders, dates, what's on which drive) live in a
   disposable projection, rebuilt from sources, never synced. The one
   irreplaceable artifact is the small lattice of judgments a human
   actually made. Back that up like your keys; delete everything else
   without fear.
4. **Everything a sender declares is advisory.** Priorities, urgency,
   claims — signed, but advisory. The receiver's local policy is the
   only authority over the receiver's attention.

Convention 3 is where this quietly inverts the classic OS. A kernel
trusts its device drivers; corruption anywhere is corruption
everywhere. Here the trust map is drawn once: sources of truth at the
edges, regenerable projections in the middle, and a single human layer
whose loss would actually hurt. The system's most important design
document is essentially a statement of *what is allowed to be lost*.

## The graveyard, and why now

The idea is old and the graveyard is well kept. Vannevar Bush's memex
(1945). Gifford's Semantic File System (1991), which ontodag-fs openly
descends from. The Semantic Desktop wave of the 2000s — Nepomuk,
Haystack, Chandler — which burned bright inside KDE and MIT and then
went out.

They didn't fail because the idea was wrong. They failed on three
missing pieces:

- **No convergence rule.** Two machines, two half-organized copies, no
  principled way to reconcile them. Canonical form plus a commutative,
  idempotent merge is the piece that makes "my laptop and my desktop
  both edited the lattice" a non-event rather than a research problem.
- **No availability story.** A semantic desktop died with its disk.
  Content-addressed storage with *purchasable* persistence — Swarm's
  postage stamps — turns "will this outlive my hardware" from a hope
  into a line item.
- **No identity story.** Every app grew its own accounts. A
  node-independent identity — a master key deriving per-app keys and
  personas, with identity state persisted on the network — is exactly
  what the SwarmID work in this ecosystem is building, and this stack's
  seams are deliberately shaped so such a key drops in as the signer.

And one piece that is genuinely new: **agents.** Software that reads
and writes knowledge faster than anyone can review it doesn't need
another opaque memory — it needs knowledge that is canonical,
addressable, verifiable and attributable, where an answer carries the
root it was computed from and a proof you can check offline. That is
not a nice-to-have on top of the personal OS; it may be the reason it
finally gets built.

## Should it be called SwarmOS?

Tempting, and we're arguing against it. Partly manners — Swarm is the
Foundation's name, and Docker got there too — but mostly accuracy: the
proudest property of this stack is that **it does not need the
network to be useful.** Everything works on a bare laptop against a
local store; Swarm is where it goes when you want the properties only a
network can sell you — availability that survives your hardware,
publication, and other people. Naming the whole thing after its network
layer would misstate the design exactly where the design is most
deliberate.

So, descriptively: a **semantic operating system** — one whose network
layer is Swarm, whose identity layer is heading toward SwarmID, and
whose kernel is a set of conventions about knowledge rather than a
binary. If the family ever needs a proper name, it should attach to the
conventions, not the network. (We note, with solarpunk-appropriate
bee-adjacency, that the place a swarm settles and stores what it
gathers is called a *hive*. Suggestions welcome.)

## What exists, what's missing

Existing today, each independently useful: the lattice and its CLI,
the record store with history and offline-verifiable proofs, the
mountable semantic filesystem, the placement catalog, the channel
kernel and attention engine, and a written contract for how machine
layers and the human layer coexist.

Missing, in decreasing order of urgency: identity (arriving via the
ecosystem), a supervisor (the daemon that keeps projections fresh and
scans scheduled — today you type the commands), and a shell (one
front end over the lattice, the files, the messages and the danger
lists — today there are four). The discipline of the whole project
applies to its gaps too: **build them when usage earns them,** not
because the diagram has empty boxes.

The diagram, though, is no longer a joke.

---

*Title alternatives: "An Operating System for What You Know" ·
"A Semantic Operating System (Accidentally)" · "The Hive: Notes Toward
a Personal Semantic OS". Author: Peter Földiák. Target: solarpunk.buzz
blog; trim the table for the newsletter version.*
