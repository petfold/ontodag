# Projections: Sources of Truth, Derived Layers, and Where Content Lives

Status: **discussion draft, 2026-08-20 (from the auto-categorization
discussion with Peter).** This document states ONE rule that three repos
currently state separately — datacat's projection contract (shelfmark
README, marked *agreed* there), ucomm's truth-vs-projection discipline
(RECOMMENDATION.md §3), and this repo's asserted/derived roadmap item
(SWARM_DESIGN.md §8) — so that it is written once, at the meet point.
Sections are marked **agreed** (already the working contract of a sister
repo), **shipped** (existing ontodag machinery this leans on), or
**proposed** (new here, to be argued with). §10 collects the open
questions.

## 1. The problem this solves

Organising personal information (files, email, messages, links) at
realistic volume cannot be manual. The easy automation — file types,
dates, email headers, senders, media types of attachments — is
*transcription* of structure the objects already carry, not judgment.
The design question is where transcribed facts live relative to the
human-curated ontology, such that:

- re-running a scanner is always safe (idempotent),
- a mistaken or obsolete machine fact costs nothing to fix (regenerate),
- the mutable world (files move, mailboxes get pruned) never collides
  with the merge algebra's retraction wall,
- and the human layer — the only irreplaceable data — stays small,
  synced, and reviewable.

The answer all three repos converged on independently: **layer by
epistemic status, and never sync what a machine can regenerate.**

## 2. The three layers

1. **Sources of truth.** Authoritative, original data, each with an
   owner and a home: the filesystem and backup media themselves
   (observed by datacat), message logs and their envelopes (ucomm),
   contact books, and the human layer of the DAG itself. Every source
   of truth is either append-only or edited in place by its owner.

2. **Projections.** Machine-derived views of a source, held in the DAG
   under a reserved namespace (`sys:` in datacat's contract). A
   projection is a **regenerable cache**: local to a device, rebuilt by
   full re-ingestion from its source, never hand-edited, never synced,
   never merged into anyone else's store, and disposable at the cost of
   convenience only. Examples: `sys:on:<medium>`, `sys:type:<ext>`,
   `sys:backup:<n>` (datacat); author/channel/time/media facets of
   messages (ucomm, projection module not yet built); later, learned
   concept DAGs (mdl-fca — the same rule, ucomm R-9).

3. **The human layer.** Interpretation: the curated lattice *above* the
   projection vocabulary (`alice@acme.com ⊑ Alice ⊑ Acme ⊑ work`),
   retention policy (§7), identity links the user asserts. This is the
   only layer that persists, syncs, merges, and deserves provenance and
   review. It is the irreplaceable original — back it up like a key
   vault.

The force of the split: classification lives in the graph, not in
extractor rules. A projection asserts only leaf-level facts; "this
email is work" is a cone query through human-layer edges, so
reclassification (`odag move`) is retroactive over the whole corpus
with no re-tagging pass, and the "rules" merge, review, and explain
themselves like any other edges.

## 3. The projection rules (agreed — datacat's contract, generalized)

- **Namespace.** Every projected category sits under a reserved prefix
  (currently `sys:`; one removable node per projection source under
  it). Nothing outside the namespace is ever touched by ingestion.
- **Idempotent full rebuild.** Ingestion drops the namespace layer and
  re-ingests the whole stream. No incremental diffing: *staleness is
  the only permitted failure mode, drift is not.*
- **Local, never synced.** The projection is rebuilt on each device
  from the (synced) source of facts — datacat's SQLite, ucomm's logs —
  not synced itself. Merge, provenance, certificates and the retraction
  wall therefore never see it.
- **Items are shared; memberships are layered.** Item nodes
  (hash-identified, §6) are referenced by both layers; a rebuild drops
  projected *memberships*, not the items the human layer has touched.
- **Observer, not authority.** A projector only reads its source. It
  never writes to the data, never sits in the sync or backup path.

Consequences worth stating: the mutable-world problem dissolves at this
tier (a moved file is a rescan, not a retraction); review is not owed
(re-running the transducer *is* verification); and the provenance
machinery (signed writers, review workflow, the asserted/derived flag)
stays reserved for the layers that need attribution — human edits and,
later, inference-tier claims from non-deterministic taggers.

## 4. The ingest contract (agreed wire format; adapter owed)

The wire format is datacat's, adopted as the family standard: JSON
lines, one item per line —

    {"item": "<name>", "supercategories": ["sys:...", "sys:..."]}

— which is `put(item, supercategories)` verbatim. Any source-side
projector (datacat's `project-ontodag`, ucomm's future envelope
projector) emits this; one ontodag-side ingester consumes it:

1. drop the projection's namespace layer (§5),
2. ensure the namespace scaffold exists,
3. `put` every line (creating missing `sys:` categories under their
   scaffold parent).

shelfmark's `ontodag_ingest.py` is a pre-API template of exactly this;
adapting it to the real API (and deciding where the adapted version
lives — see §9) is owed work.

## 5. The drop and the join (ontodag's two obligations)

**The drop (shipped, fit to be verified).** "Remove the namespace
layer" is `remove_cone` / `odag remove --cone sys:<source>` almost by
definition: the survival rule (a cone member is deleted iff the root
can no longer reach it once the targets are gone) means pure cache
entries fall away while any item also held by a human-layer category
survives, detached from the projected memberships only. What must be
checked rather than assumed: items whose *only* parents were projected
categories should survive the drop too if the human layer references
them at all, and should disappear if nothing does — which is exactly
the survival rule, but the golden test is owed.

**The join (proposed — the one new seam).** Unified queries like
`get(photo, vienna, sys:on:drive-budapest)` need both layers in one DAG
instance. The mechanism exists — load the human store, `merge` the
projection in memory, query — but today "never commit the merged state
back" is only a discipline, and a discipline is exactly how a `sys:`
fact would one day leak into the synced store. Proposed: a composed
**overlay view** — a read-query surface over (human store ∪ N local
projections) where mutations route to the human store alone, and
`commit` on the composed object is either refused or explicitly scoped.
Shape open (§10.5): a view class, or a Session-level notion of
overlay stores in the CLI/fs mount.

## 6. Identity (agreed per source; two residues)

- **Files: content hash** (`sha256:…`), paths and media as attributes —
  datacat's decision, adopted. Dedup is free; a copy is one item.
- **Messages: the event/envelope hash** (ucomm), with `Message-ID` as
  the bridged-email anchor. Immutable objects, stable names.
- **People: contact claims**, owned by ucomm's contact layer (bridged
  authorship explicitly weaker than native signatures). The DAG holds
  the *consequences* as edges (`mailto:alice@… ⊑ Alice`,
  `signal:alice.42 ⊑ Alice`), so anything filed under either identifier
  is under Alice by subsumption. Whether those edges are projected from
  the contact source or native to the human layer: open (§10.2).

Residues: an *edited* file is a new hash, and whether human categories
carry forward is an interpretation question no projection can answer
(§10.3); and link-shaped items (§7) need a naming rule (§10.4).

## 7. Retention: where the content lives (proposed, 2026-08-20)

Categorization says what an item *is*; retention says where its bytes
should live. These are different questions, and Peter's criterion for
the second is a two-axis decision:

> Don't back up what you can expect to reach from the internet — unless
> it is important data you need when offline or when SHTF.

i.e. **keep-locally = f(expected availability elsewhere, importance
when disconnected)**. Proposed retention classes, strongest first:

| class | meaning | bytes live |
|---|---|---|
| `original` | exists nowhere else; irreplaceable | local + N backup copies (3-2-1) |
| `offline-essential` | re-fetchable in principle, but needed without the network, or too important to bet on the source | local copy kept, refreshed opportunistically |
| `linked` | reachable on the internet; not essential offline | reference only (URL or Swarm ref) + enough metadata to re-find it if the link dies (title, author, hash if known) — a dead link degrades to a search, not a void |
| `live` | dynamically changing (weather, prices, feeds) | no bytes at all: the item is a **source**, holding a fetch recipe/endpoint. Snapshotting is a separate deliberate act that mints a new *dated* item (the monotone escape hatch: transitions as dated additions) |

Design points:

- **Classes are categories, so policy composes by subsumption.**
  `family-photos ⊑ original`, `reference-manuals ⊑ offline-essential`:
  one edge covers a whole cone, items inherit, and changing your mind
  is `odag move`. An item reachable from two classes takes the
  **strongest** — demands compose by max, which is monotone and
  therefore merge-safe (unlike exclusive statuses, which the `move`
  work showed cannot inherit).
- **Facts and norms stay in different layers.** Projections report
  where copies *are* (`sys:on:*`, `sys:backup:n` — facts, regenerable);
  retention classes say where copies *should be* (human intent, synced).
  The enforcement report is their join: datacat's `redundancy` /
  `only-on` danger lists, filtered by required class — "items whose
  class demands N copies and have fewer" becomes a query instead of a
  policy hardcoded in the scanner.
- **Swarm is a third availability class**, between local and web-link:
  a content-addressed ref whose availability is *purchased* (postage)
  rather than hoped for. A pinned/stamped Swarm copy can count toward
  a class's copy requirement in the redundancy join; an unpaid ref
  should not.
- **Refresh is probe-then-verify (added 2026-08-20).** HTTP has no
  "send me the hash" verb, but conditional GET is the cheaper thing
  that achieves the same goal: store per-copy validators beside the
  local bytes — `(url, etag, last-modified, sha256-of-fetched,
  fetched-at)` — and refresh with `If-None-Match`; a `304 Not Modified`
  costs one round trip and no body, and the local copy stands. On a
  `200`, hash the new body and let content identity decide (an ETag
  that revalidated spuriously — recompression, mtime churn — dedups to
  the same item anyway). The two validators have different jobs: the
  **ETag is the server's cheap change probe**, the **sha256 is the
  truth**. Where a real hash is offered out of band, prefer it
  (RFC 9530 `Repr-Digest`, S3/GitHub/apt checksums, `git ls-remote`).
  Content-addressed links skip the dance entirely: an immutable Swarm
  ref *cannot* change, and a feed lookup is natively the hash-only
  request — it returns just the current ref, and content is fetched
  only on difference.
- **ucomm alignment.** A channel's Genesis `persistence` parameter
  (PERMANENT / EPHEMERAL / ARCHIVAL_OPTIONAL) is the sender-side
  declaration of the same axis; receiver sovereignty means the
  receiver's retention classes decide what is actually archived —
  consistent with everything else in that design being advisory.

## 8. Vocabulary (gated on PACKS.md)

The shared facet vocabulary the projections emit — **who** (identifier),
**when** (time), **what kind** (type), **where** (container: medium,
folder, mailbox, thread) — plus a MIME hierarchy and the retention
classes of §7 are pack-shaped: stable, externally standardized or
prelude-tier, conflict-detectable. datacat's flat `sys:type:<ext>` is
the immediate beneficiary of a MIME *hierarchy*
(`sys:type:jpg ⊑ image ⊑ media`) — a small, concrete demonstration of
what the DAG side adds over the SQLite side. All of this waits for the
PACKS.md discussion; nothing here jumps that gate.

## 9. Division of labor

| repo | owns | owed |
|---|---|---|
| **shelfmark/datacat** | filesystem + backup scanning, SQLite source of facts, `project-ontodag` (exists) | retention-aware redundancy join (§7); v0.3 "OntoDAG join live" consumes §5's overlay view |
| **ucomm** | protocol bridges (IMAP done), envelope schema, contact/identity claims, later mdl-fca (R-9) | the plain envelope→facts projector (analog of `project-ontodag`, same wire format; its dashboard is the in-house precedent for "projection, recomputed, never persisted") |
| **ontodag** | the human layer; merge/query/move machinery (all shipped) | the overlay-view seam (§5), the cone-drop golden test (§5), the adapted ingester (§4), vocabulary packs (§8, gated), and keeping this contract current |
| **ontodag-fs** | browsing the joined view; its parked "transducer analog" roadmap line points here | nothing until the overlay view exists |

No new sister repo: adapters live with the sources they read; the
shared piece is this contract, not a package.

## 10. Open questions

1. **Rebuild cost at scale.** Idempotent full rebuild of 10⁵–10⁶
   memberships into a per-device overlay: how long, how often, and is
   in-memory merge at that size acceptable? A measurement, not a
   debate — and it decides whether "full rebuild, no diffing" survives
   a real corpus or needs a compiled/serialized overlay cache.
2. **Contact projection.** ucomm's contact book is itself a human-
   curated source of truth. Are identity edges projected from it
   (regenerable, but then not human-editable in the DAG) or native to
   the human layer (editable, but then two homes for one fact)? The
   general rule "every fact has exactly one home" wants this decided
   once.
3. **The edited-file residue.** Content-hash identity makes an edited
   document a new item. Do human categories carry forward, and by what
   act? (A `version-of`-shaped link brushes the relations wall;
   re-filing by hand is honest but tedious; datacat inherits the same
   gap in `whereis`.)
4. **Names for link and live items.** A URL is a location, not an
   identity. Content hash when known; else the URL; live sources
   perhaps named by a recipe hash — none of this is settled, and G1
   cares. Whatever is decided, refresh validators (ETag,
   Last-Modified, fetch time — §7) are attributes of a *copy*, never
   part of the name: they are one server's transient word, not
   identity.
5. **The overlay seam's shape.** A view class in the core? A Session-
   level overlay list in the CLI? An fs-mount concern? Where refusal
   of `commit` lives determines who can get it wrong.
6. **Retention vocabulary tier.** Prelude-tier (everyone needs it) or
   pack-tier (opinions differ)? And are four classes right, or is the
   copy-count a parametric dimension (`copies(3..)`) rather than named
   classes?
7. **Snapshot semantics for live sources.** Who mints the dated
   snapshot item, and under what name, when a user *does* want
   yesterday's weather kept?
8. **Inference tier hooks.** When content analysis arrives (a different
   trust tier: non-deterministic), do its outputs enter as a projection
   (regenerable, unreviewed) or as signed assertions (reviewable,
   permanent)? The FCA paper's attribute-exploration idea (D6) argues
   the latter can be made affordable; the former is available today.
