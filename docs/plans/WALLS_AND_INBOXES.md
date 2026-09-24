# Walls and Inboxes: Posting to an Audience, Reading What Arrives

Status: discussion draft (2026-09-24). **Nothing here is implemented.** This
is the canonical statement of a design shared by three projects, each of
which carries its own fold of it:

- **OntoDAG** (this note): what a post is, who it is for, when, and what it
  is about. Builds on [SHARING.md](SHARING.md).
- **ucomm** (`docs/WALLS_AND_INBOXES.md` there): how posts reach readers, and
  whether they deserve attention.
- **categor.io** (`docs/DESIGN.md` §14 there): the site's walls and inboxes.
- **ACT** ([act-categories/DESIGN.md](act-categories/DESIGN.md) §2.8):
  enforcing the same audiences with keys on Swarm.

Definitions live here; the folds refer back rather than restate them.

## 1. Words

| Here | Means | ActivityPub | Elsewhere |
|---|---|---|---|
| **wall** | an author's posts, in the order they were posted | *outbox* | "profile", "user timeline" (X), "wall" (early Facebook) |
| **post** | one item on a wall, with a time and an audience | *activity* / *object* | post, status, toot |
| **audience** | who a post is for: one person, a group, or everyone | `to` / `cc` | privacy setting |
| **inbox** | what a reader sees: the walls they follow, merged | *inbox* | "home timeline" (Mastodon), "news feed" (Facebook) |
| **chat** | two walls addressed to each other, read together | — | direct messages |
| **reply** | a post on your own wall that refers to someone else's | `inReplyTo` | reply, quote |

**Not "feed".** On Swarm a *feed* is one owner's sequence of updates under a
topic: something its owner publishes, not something anyone receives.
ucomm keeps author logs as Swarm feeds, and a wall is naturally *published
as* one. So the reader's side is called the inbox here, as in ActivityPub
and in ucomm's "universal inbox", and "feed" means only the Swarm thing.

The author decides a post's audience; the reader decides their inbox. Those
are the two halves of SHARING.md's rule (sharing, and accepting), carried
into time.

## 2. The model

**A post is an item in its author's store**, filed under

1. **its audience** — one or more principals or groups, exactly as sharing
   works (SHARING.md §2): `ada@…` for one person, `friends` (filed under
   several people) for a group, `everyone` for all readers; and
2. **its publish time** — a value of `posted`, declared once as a *role* of
   `time` (`posted ⊑ time`; DIMENSIONS.md §14).

Then:

- **A's wall, as R sees it** = the posts in reach(A, R's principals ∪
  {`everyone`}), ordered by their `posted` value.
- **R's inbox** = the union of the walls of the authors R follows, ordered by
  `posted`, then filtered and ranked on R's side (§5).
- **A chat** is two walls addressed to each other: R's inbox restricted to
  one author, together with R's own posts to them.

What follows from the sharing rule, unchanged:

- **Receivers don't learn other receivers.** Principals sit *above* the
  groups they are in, and a reader sees only what is below them. An author
  who wants readers to know the audience says so in the post.
- **Audiences nest.** `friends ⊑ close-friends` gives close friends every
  post friends get; nobody outside close-friends sees theirs.
- **Classifying stays private.** Filing a post under the public `dog`
  publishes nothing (it is not below any reader); filing it under
  `everyone` does.
- **Everyone** is one reserved principal that every reader holds,
  including visitors without an account. It is the only way something
  becomes public, and a deliberate one.

**About-time and publish-time are independent.** A post of August's trip
photos, posted today, is filed under `time(2026-08)` and
`posted(2026-09-24T10:00:00Z)`; asking for `time(2026-08)` finds it, and
asking for `posted(2026-09)` finds it, and neither question finds the other
kind of date. (Checked in OntoDAG 0.28: role values are below the head
`time` structurally, but outside `time`'s own value cones.)

### 2.1 A worked example (run in OntoDAG 0.28)

```
# the author's store
posted time                                     # posted is a role of time
friends ada@x                                   # a group of one, for now
trip-photos friends posted(2026-09-24T10:00:00Z) time(2026-08)
hello-world everyone posted(2026-09-20T08:30:00Z)
note-to-ada ada@x posted(2026-09-24T12:15:00Z)
```

Ordered by `posted`, within `reach(store, principals)`:

| Reader's principals | Their view of the wall |
|---|---|
| `ada@x`, `everyone` | hello-world, trip-photos, note-to-ada |
| `everyone` (a stranger) | hello-world |

`get posted(2026-09)` finds all three posts; `get time(2026-08)` finds
only trip-photos.

## 3. Three layers

| Layer | Answers | Who |
|---|---|---|
| **Structure** | what a post is for, when it was posted, what it is about | OntoDAG: reach, `posted`, concepts — per store, pure |
| **Enforcement** | who can actually read it | a server that computes reach (categor.io), or keys (ACT categories, §6) |
| **Delivery and attention** | how new posts reach readers; whether they interrupt | ucomm: per-author logs, hints or polling, the attention engine, the universal inbox |

The same stores serve all three. A host like categor.io is one way to
provide enforcement and delivery; Swarm plus ucomm is another; they can
coexist over the same content.

## 4. In ucomm's terms (summary; its fold has the detail)

- **A wall is one author's log**, published as a Swarm feed, in a
  *social*-profile channel (DESIGN.md §4 there: 1:N plus a reply graph,
  per-author ordering, a single broadcaster, permanent). The audience
  varies per post, so it is carried by per-post keys (§6), not by a
  channel per audience.
- **The inbox is ucomm's universal inbox**: the channel directory lists
  the walls a reader follows, and "a follow is a standing acceptance of a
  channel at a low priority ceiling" (ucomm's own definition).
- **A reply** is an envelope whose causal references cross channels, as
  ucomm already allows.
- **ucomm envelopes carry no clock time** (per-author sequence numbers and
  causal references only). The publish time is the post's `posted` value,
  in the payload or its projection, not a new kernel field.

## 5. The reader decides

Everything about an inbox beyond "which posts may I see" is the reader's:

- **Whom to follow**: accepting an author (categor.io: filing their address
  in your store; ucomm: a directory entry).
- **What interrupts**: ucomm's attention engine grades each new post
  (importance, urgency, ceilings, offsets); categor.io today only
  shows or hides requests.
- **What to see**: filters by concept (`get dog posted(2026-09)`), by
  author, by audience.
- **Trust in times**: `posted` is the author's claim, advisory like every
  sender claim in ucomm. Within one author the order is also fixed by their
  store's history (or log sequence), which others hold copies of; an inbox
  may sort by either.

## 6. ACT: document categories and recipient categories

The extension of Swarm ACT sketched in act-categories/DESIGN.md gets its
two halves from walls directly:

- **Recipient categories** are the audiences: principals and the groups
  filed under them, nested.
- **Document categories** are the author's own categories and posts,
  including their topics (public vocabulary) and times.
- **A bridge** is filing a post, or a category of posts, under an audience.
  The token plan is derived from reach (SHARING.md §3).
- **Revocation is forward-only**: a reader removed from an audience keeps
  what they already had and misses what comes after. It is the same as
  unfollowing anywhere, and should be said as plainly (ACT §6; ucomm
  DESIGN.md §8).
- **Time as a document category** is where it gets interesting: "my posts
  from 2026, for X" is one bridge to `posted(2026)`. But containment
  between typed values is *computed*, with no asserted edges to put tokens
  on. Either time buckets become explicit nodes with asserted edges
  (`posted(2026-09)` under `posted(2026)`), or each epoch gets its own key.
  Open (Q4).
- **What stays visible on Swarm**: that a post exists, its size and when it
  was written. Content is gated; structure is not (ACT §6).

## 7. What each repository would build

- **OntoDAG**:
  - `everyone` and principal declaration (SHARING.md Q1: `everyone`
    is the second reserved name, and settles the declaration's shape);
  - `posted`, declared where stores can adopt it (Q3);
  - a helper returning a wall or an inbox as `(posted value, name)` pairs in
    order: `sharing.timeline(dag, principals)`, over the same reach.
- **categor.io**:
  - a post box with an audience picker (one person, a group, everyone);
  - a wall page per account, and an inbox page per reader;
  - `everyone` posts readable by visitors;
  - counts of what is new.
- **ucomm**:
  - a wall channel (the social profile's conformance suite);
  - per-post payload keys from the category key graph;
  - an inbox timeline (the dashboard sorted by publish time);
  - posts in the envelope → facts projector;
  - a bridge to categor.io.
- **ACT**:
  - the token plan from reach;
  - time buckets or epoch keys (Q4).

## 8. Open questions

- **Q1 — Audience per post or per wall channel in ucomm?** Per-post keys
  keep one log per author and let every post pick its audience; a channel
  per audience is simpler but multiplies channels, and a reader could
  infer audiences from which channels exist.
- **Q2 — Which time orders an inbox?** The author's `posted` claim, the
  store's history, or both (claim for display, history for order)?
- **Q3 — Where is `posted` declared?** In the prelude (a registry change
  with new golden roots), or in a small pack of its own that social stores
  adopt?
- **Q4 — Time buckets for ACT** (§6): explicit bucket nodes, or epoch keys?
- **Q5 — Replies and threads** refer to someone else's post, which needs
  names that survive between stores (SHARING.md Q5).
- **Q6 — Public posts and spam.** Walls are pulled, never pushed. Whether
  a post reaches anyone's attention is decided by the reader's side
  (ucomm's postage floor, bonds, ceilings), so `everyone` does not open an
  attention channel by itself.
- **Q7 — Post identity.** Names are identity in OntoDAG; two authors'
  `hello-world` are different posts. A merged inbox qualifies each post by
  its author, as categor.io already does for shared items. Referring to one
  is Q5 again.

## 9. Build order (proposed)

1. `posted` and `sharing.timeline` in OntoDAG, with `everyone` as a
   caller-named principal until SHARING Q1 is settled.
2. categor.io: posting, walls and inboxes on the site (server-enforced).
3. ucomm: the wall channel and the inbox timeline, poll-only first (ucomm
   invariant 7), with categor.io bridged in.
4. ACT: per-post keys from reach; time buckets (Q4).
