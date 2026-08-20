# The Accidental Operating System

*Draft blog post, 2026-08-20 (rev 2). Working title; alternatives at the
end.*

---

We didn't set out to build an operating system. We set out to build small
things, each with a one-line job: a category lattice with a canonical
form ([OntoDAG](https://github.com/petfold/ontodag)), a versioned record
store over content-addressed storage
([recordstore](https://github.com/petfold/recordstore)), a filesystem
where directories are queries
([ontodag-fs](https://github.com/petfold/ontodag-fs)), a catalog that
knows which backup drive holds which file (shelfmark, and its `datacat`
tool), and a middleware that treats every chat, inbox and feed as one
kind of thing ([ucomm](https://github.com/petfold/ucomm)).

Then we drew the diagram, and laughed, because we had seen it before —
in every operating systems textbook:

| classic OS layer | this stack |
|---|---|
| block device | recordstore over Swarm (content-addressed, versioned) |
| filesystem | ontodag-fs (directories are queries; one file, several true names) |
| namespace | OntoDAG (the category lattice itself) |
| volume manager | shelfmark/datacat (which media hold which bytes; redundancy as a report) |
| IPC & notifications | ucomm (channels, envelopes, one inbox) |
| scheduler | ucomm's attention layer (the scarcest resource is you) |
| standard library | the prelude and packs (shared vocabulary, adopted by merge) |
| users & keys | node-independent identity (arriving from the ecosystem, not from us) |

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
   querying. `web-study.md` is both a spider thing and a document, so it
   is at `/animal/spider/document/`, `/document/spider/`, and every
   reordering — one object, several true names, no copies, no symlinks.
   Paths can even carry typed constraints: `/parcel/weight(..5kg)/` is a
   directory that exists for any well-formed bound without anyone
   creating it, computed exactly, in rational arithmetic, nothing
   rounded.
2. **Equal knowledge has equal bytes.** The lattice is kept in a
   canonical form (the transitive reduction of a DAG is unique), so the
   same facts produce the same content hash whoever writes them, in
   whatever order, on whatever machine. Two replicas that know the same
   things *are* the same bytes. Everything else falls out of that one
   property: deduplication is free, difference is computable, merge is
   a commutative, idempotent fold instead of a negotiation, and an
   answer can carry the root it was computed from together with a
   Merkle proof a stranger can verify offline.
3. **Everything is regenerable except the human layer.** Machine-derived
   facts — file types, senders, dates, what's on which drive — live in a
   disposable projection under a reserved namespace, rebuilt from
   sources by re-scanning, never synced, never hand-edited. The one
   irreplaceable artifact is the small lattice of judgments a human
   actually made: *this address is Alice, Alice is a friend, these
   photos are the ones that matter.* Back that up like your keys; delete
   everything else without fear. A mistaken machine fact costs a rescan;
   a mistaken human judgment costs an edit; neither ever costs an
   archaeology session.
4. **Everything a sender declares is advisory.** Priorities, urgency,
   importance — signed, auditable, and advisory. The receiver's local
   policy engine is the only authority over the receiver's attention.
   Apps become views and policy defaults, not silos; the inbox becomes
   one, and it answers to you.

Convention 3 is where this quietly inverts the classic OS. A kernel
trusts its device drivers; corruption anywhere is corruption
everywhere. Here the trust map is drawn once: sources of truth at the
edges, regenerable projections in the middle, and a single human layer
whose loss would actually hurt. The system's most important design
document is essentially a statement of *what is allowed to be lost.*

## What you keep, and where

The same discipline extends from facts to bytes. Not everything you
know about deserves a local copy: the decision is a function of two
axes — *how confident are you it will still be reachable elsewhere,*
and *how much would you need it with the network gone.* That gives four
retention classes rather than one anxious "back up everything":

- **original** — exists nowhere else; irreplaceable; local plus counted
  backup copies, and the catalog's redundancy report tells you when the
  count is short;
- **offline-essential** — re-fetchable in principle, but you want it
  when the network isn't there, or you don't trust the source to
  outlive its usefulness;
- **linked** — reachable on the internet and not essential offline: keep
  the reference and enough metadata that a dead link degrades into a
  search rather than a void;
- **live** — dynamically changing (weather, prices): keep no bytes at
  all, keep the *source*, and mint a dated snapshot only as a
  deliberate act.

Because retention classes are just categories, policy composes by
subsumption — one edge saying "family photos are originals" covers
every photo, past and future, and changing your mind is moving one
edge. Refreshing a linked copy is a conditional request (one round
trip, no body, if nothing changed); and content-addressed storage skips
the question entirely, since an immutable reference *cannot* change and
its availability is purchased rather than hoped for.

## The graveyard, and why now

The idea is old and the graveyard is well kept. Vannevar Bush's memex
(1945). Gifford's Semantic File System (1991), which ontodag-fs openly
descends from. The Semantic Desktop wave of the 2000s — Nepomuk inside
KDE, Haystack and Chandler out of MIT and OSAF — which burned bright,
absorbed real institutional effort, and went out.

They didn't fail because the idea was wrong. They failed on three
missing pieces:

- **No convergence rule.** Two machines, two half-organized copies, and
  no principled way to reconcile them — so the systems stayed
  single-machine, and a single-machine knowledge system dies of
  loneliness. Canonical form plus a commutative, idempotent merge makes
  "my laptop and my desktop both edited the lattice" a non-event rather
  than a research problem.
- **No availability story.** A semantic desktop died with its disk, and
  mirroring it meant running servers. Content-addressed storage with
  *purchasable* persistence — Swarm's postage stamps — turns "will this
  outlive my hardware" from a hope into a line item.
- **No identity story.** Every application grew its own accounts, so
  nothing composed across them. A node-independent identity — one
  master key deriving per-application keys and personas, with identity
  state persisted on the network rather than on one device — is being
  built in the Swarm ecosystem right now, and this stack's signing
  seams are deliberately shaped so such a key drops in without a schema
  change.

And one piece that is genuinely new rather than repaired: **agents.**
The semantic desktop assumed a patient human doing the reading and the
filing. Software now reads and writes knowledge faster than any human
can review it — which makes the desktop-era architecture worse, but
makes this one better, because what agents need is precisely what a
model's own memory is not: knowledge that is **canonical** (same facts,
same bytes), **addressable** (an answer cites the exact state it was
computed from), **verifiable** (subsumption answers ship with offline-
checkable certificates), and **attributable** (every claim signed by
its author, retractable, reviewable, with per-author standing). The
personal semantic OS may finally get built not because humans changed,
but because their software did.

## What exists, what's missing

Existing today, each independently useful and none requiring the
others: the lattice with its CLI and web console (typed values, unions,
excerpts and claim-grain diffs for mailing someone part of what you
know, history with undo); the record store with snapshots at any past
root and offline-verifiable proofs; the mountable semantic filesystem;
the placement catalog with its redundancy danger lists; the channel
kernel and attention engine with an IMAP bridge already feeding real
inboxes into it; and a written contract for how the machine layers and
the human layer coexist without corrupting each other.

Missing, in decreasing order of urgency: **identity** (arriving from
the ecosystem, as above); a **supervisor** — the daemon that keeps
projections fresh, scans media when they mount, and retries
publication, where today you type the commands; and a **shell** — one
front end over the lattice, the files, the messages and the danger
lists, where today there are four. The discipline of the whole project
applies to its gaps too: **build them when usage earns them,** not
because the diagram has empty boxes.

The diagram, though, is no longer a joke.

---

*Title alternatives: "An Operating System for What You Know" ·
"A Semantic Operating System (Accidentally)". Author: Peter Földiák.
Target: solarpunk.buzz blog; trim the table and the retention section
for the newsletter version.*
