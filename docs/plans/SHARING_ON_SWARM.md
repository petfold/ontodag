# Sharing and Receiving on Swarm, Without Servers

Status: plan and discussion draft (2026-09-25). Phase 1 and a first
Phase 2 run are built, unreleased, on OntoDAG's `swarm-sharing` branch
(§13). The rest is a plan. It asks how the sharing and receiving of
[SHARING.md](SHARING.md) and [WALLS_AND_INBOXES.md](WALLS_AND_INBOXES.md)
can run on Swarm with no server at all:

- **Identity and each user's data:** dappdata or Swarm ID.
- **Who may read what:** enforced by keys, extending ACT as sketched in
  [act-categories/DESIGN.md](act-categories/DESIGN.md) ("ACT" below).
- **Delivery and attention:** ucomm.

categor.io, the server version, is the reference for what the functions
are.

§11 lists the decisions that need discussion, each with a leaning.

## 0. The answer, first

**Yes, it works, and in one respect Swarm suits it better than a server
does.** On Swarm every write is single-owner and readers pull. That's
already the shape of this design:

- the author files things in their own store, and only the author writes
  there;
- readers fetch what they may see and merge it on their own side;
- consent needs no enforcement: nothing arrives that the reader didn't
  fetch.

**What changes is when "who sees what" is decided.** A server decides at
read time, by computing reach. On Swarm the author decides at write time,
by what they encrypt to whom. The same rule works for both: the keys
reproduce reach exactly (§4, checked).

**The DAG is handled**, and so is removing an edge (§4.3, checked):
- **Keys in a DAG:** keys can't be derived down a DAG the way they can down
  a tree, so every node gets its own key, and every edge a published token
  (ACT §2.3).
- **Removing an edge:** after each edit, the nodes `sharing.losses` reports
  lost get new keys. Doing that lazily, only before something new is
  wrapped under a lost node, makes the cost follow future writes rather
  than group size.
- **One thing to fix on the way:** today's `KeyGraph.revoke` skips lost
  nodes without children. The spike shows that leaks new keys once such a
  node gains one.

**The weak spots are real, and mostly Swarm's rather than this design's:**
- telling someone that something arrived (requests, push) needs a full
  node or a relay;
- structure stays visible: sizes, timing and the shape of the key graph;
- revocation is forward-only;
- polling many authors is slow, because asking for an update that doesn't
  exist yet costs a whole retrieval attempt;
- group keys held by organisations, and two devices writing at once, need
  care.

**Recommendation.** Use this model for *publication to structured
audiences*: walls, shared folders, an organisation's documents, public
posts. For private conversation, where forward secrecy matters, use
ucomm's ratchet channels (double ratchet, MLS; ucomm DESIGN §8). Put both
behind the same inbox and the same consent (§9).

## 1. What the server did, and what replaces it

| categor.io function | On the server | On Swarm |
|---|---|---|
| **account, login** | SQL, password | an identity key from dappdata or Swarm ID (§2) |
| **your store** | an `rs:` store on the server's disk | your own `swarm:` store, encrypted, owned by a key derived from your identity, on your postage batch (§3) |
| **public vocabulary** | one in-memory copy | the packs, already published on Swarm by fingerprint, read lazily (BROWSER.md) |
| **sharing** (reach at read time) | the server computes reach per request | the author publishes a *key plan* derived from reach: tokens and grantee entries, plus encrypted records (§4) |
| **accepting a sender** | an edge in your store | the same edge; your client decides what to fetch |
| **requests** (a first share from a stranger) | the server finds everyone who shares with you | a small signed notice at your rendezvous point (ucomm DESIGN §6), under ucomm's spam economics, or out of band (§5) |
| **blocking** | an edge under `blocked` | the same; your client stops fetching and drops their notices |
| **request settings per address** | `hide-requests` under an address | attention policy per persona key (ucomm) |
| **addresses** | `name@categor.io` | public keys, with petnames; personas are separate keys (§2) |
| **refusing unknown addresses** (categor.io DESIGN §10) | registration snapshots | **not needed**: grants go to keys that exist, so nothing waits for a name to be claimed |
| **never reusing an address** | a SQL table | not needed for keys. An ENS name can change hands, so resolve it to a key when sharing, and grant to the key |
| **"this stops people seeing things"** | `losses` before an edit | the same function, client-side, which also decides which keys to rotate (§4.3) |
| **walls, inboxes** | pages over the stores | one log per author, a Swarm feed, each post under its own keys; readers poll (§5, §6) |
| **pictures, console** | server-rendered | in the client (OntoDAG runs in a browser, BROWSER.md) |
| **backups** | a nightly cron job | content persists while stamps are paid; the user exports as they like |

## 2. Identity

Two kinds of key are needed, and dappdata so far has only the first:

- **Storage keys**, per app: dappdata's folder, feed owner and encryption
  key, all derived from one wallet signature (or a passkey), with nothing
  stored.
- **A sharing identity**: a long-lived public key that others encrypt to
  (the ECDH in grantee entries) and whose signatures they check. **It has
  to be the same key in every client of this protocol.** If
  categor.io-on-Swarm and ucomm derived different keys, a user would be two
  people.

dappdata has the pieces, but not yet the answer (S1):
- `deriveKey(purpose)` (D17) already names ACT grantees as a use, but its
  keys are bound to the app (D16), so two apps get two keys.
- D16's *declared* app identity, or a reserved one like the
  `dappdata:directory` that D7 proposes, would give every client the same
  key. A phishing site can declare it too (dappdata T14). The wallet's line
  showing which site asks is then the only defence.

Around it:

- **Personas** are separate sharing keys, unlinkable unless the user links
  them. They're categor.io's addresses tied to a category (`ada+work`), and
  ucomm's personas (ROADMAP R-10). ACT allows one grantee entry per
  author–reader pair (§4.1), which is one more reason a persona must be its
  own key.
- **A profile record** at a feed derived from the key: a display name,
  optionally an ENS name, and where this identity's wall and rendezvous
  point are. It's ucomm's contact card, published.
- **Finding someone's key** works through contact cards (out of band, a QR
  code), ENS text records, or a Swarm ID directory. Never through a global
  list (S3): categor.io's rule that addresses are never listed carries
  over.
- **Devices.** Signing can be delegated to device subkeys by certificate
  (ucomm DESIGN §7, format K-7). Decrypting can't be delegated cheaply:
  shares are wrapped for one public key, so every device that reads needs
  its private key, unless authors grant to each device separately.
- **Losing the key loses the identity** (dappdata T4). A reader loses every
  share made to them; an author loses the ability to update what they
  published. So dappdata's D28 matters more for a sharing identity than for
  a private folder: it puts one folder behind several unlock keys, by
  wrapping a random seed.
- **Changing a key** is the same as losing one, seen from the author: grant
  to the new key, and treat the old one as having lost everything it
  reached (§4.3).

## 3. Your store, on Swarm

- **Your whole store is private.** It's an OntoDAG `swarm:` store. Its
  records sit in a content-addressed trie with the head in a signed feed,
  encrypted at rest with deterministic AES-SIV (the `store_key` setting,
  `ontodag.encstore`). Deterministic encryption keeps equal content at
  equal roots, so two devices converge.
  - The key material comes from a dappdata sub-key (D17).
  - The batch is the user's own, stamped client-side (dappdata D12, D19).
  - Nobody but the user can read it. What others see is only what §4
    publishes.
- **The author's keys** live in the same private store: every node key of
  §4, and the rotation state. Losing them isn't losing the identity. The
  author re-keys everything and republishes, and readers walk again.
- **Two devices writing at once.**
  - dappdata's D6 and T18 apply: on mainnet another device can miss a
    write for a second or two.
  - OntoDAG's `sync` converges (contract G5), but it is grow-only today: a
    removal loses to a concurrent *holder* (SWARM_DESIGN.md; tombstones or
    observed-remove are still undecided).
  - For sharing, that means an unshare made on one device can come back
    when another device syncs (S14).
- **The public vocabulary** is read, never copied, as on categor.io. The
  store keeps the public ancestors of the names it uses, so exports and
  views work.

## 4. Sharing: from reach to keys

### 4.1 The key plan, as a function of the store

For a store S and its principals (each principal node is one reader's
key), the author publishes:

1. **A grantee entry per principal**, Bee-ACT-shaped:
   - found at `Keccak(ECDH_x ‖ 0)` between author and reader;
   - holding the principal node's key, wrapped under `Keccak(ECDH_x ‖ 1)`
     (`ontodag.act`, pinned bit for bit to Bee v2.8.1).
2. **A token per edge of the combined order below the principals.** For
   every node u that is a principal, or in some principal's reach, and every
   child c of u:
   - the children count **asserted edges and computed hops** between
     present typed values;
   - the token is `T(u → c) = wrap(K_u, c, K_c)`.

**Checked** (`experiments/keyplan_spike.py`, §12): 200 random stores and
5,866 random edits, including typed values, nested groups, unfiling and
removal, under each of the four rules of §4.3. After every edit, a reader
derives the key of node x **exactly when** `x ∈ reach(S, [p]) ∪ {p}`.
**Not a single mismatch.** So SHARING.md's proposed G7 and the keys are one
definition with two enforcements.

This settles several open questions at once:

- **SHARING Q4** asks whether the token plan is a pure function of (store,
  principals). It is: which tokens exist, and between which nodes. The key
  *values* aren't, and can't be. Revocation needs fresh keys, so the
  rotation state is the author's history, kept in their private store
  (§3).
- **One direction, no separate halves.** ACT's people half (keys flowing
  up) and document half (flowing down) become one orientation: from the
  principal down through its groups to the content (SHARING §3).
- **No aligned twin to maintain** (ACT §9).
  - Today's `KeyGraph.align` mints tokens along asserted edges from
    declared people and document cones. The plan replaces it.
  - The plan is still stored beside the store, but it's re-derived at every
    commit and never maintained by hand.
  - ACT §9 feared that coupling the two would make every `put` a key
    ceremony. It doesn't: a `put` mints only its new tokens, and only a
    loss rotates, lazily (§4.3).
- **Redundant grants can't disagree with access** (SHARING Q2). The plan
  is derived from the reduced store, so a pruned direct grant has no token
  either.
- **Time buckets need no extra nodes** (WALLS_AND_INBOXES Q4, ACT §2.8).
  Both asked for explicit bucket nodes or epoch keys, because computed
  containment has no asserted edges to carry tokens. Tokens can follow the
  computed hops instead:
  - "all my 2026 posts, for X" is one edge, `posted(2026) ⊑ x`;
  - each new post's time value gets its token from `posted(2026)` when it
    first appears.

### 4.2 What is encrypted, with which key

**Every node has two kinds of key:**

- **A derivation key** K_v, random. It wraps the keys of v's children (the
  tokens) and v's data keys, and it's the key that rotates when someone
  loses v.
- **Data keys**, random, one per version of v's content (text, files),
  wrapped under K_v.
  - They never rotate: a new version gets a new data key. So rotating K_v
    re-wraps a 32-byte key and **never re-encrypts a file**.
  - Old versions stay readable to whoever already had them. That's
    forward-only revocation, stated plainly.
  - On Bee, a data key can play the ACT access key's part in a download
    (ACT §3, Phase 2).

Today one key does both jobs: content goes under `store_key_for(K_v)`.
That's why `KeyGraph.revoke` leaves nodes without children alone: rotating
them would mean re-encrypting their content. With two keys, rotating any
node is cheap, and §4.3 shows it's needed.

**Each node's record** holds its name and its own content (text, typed
value, and references with their data keys), encrypted under K_v.
- It never names private parents or children: **the edges are the tokens
  themselves**.
- So a reader who walks the tokens sees exactly the edges between nodes it
  reaches. That's SHARING §2.1's faithful piece of the store, with nothing
  outside it named.
- A record does name its typed-value parents, such as its `posted(...)`
  time. They are the cut parents a host may show "by another right"
  (SHARING §2.1), and without them a reader couldn't order a wall.
  Public-vocabulary parents, which categor.io shows, could be named the
  same way by a host that knows which parents are public.

Two choices remain (S5):
- **Where tokens live.**
  - Today each token is its own record, `act/t/<u>/<v>`, so anyone can
    count edges.
  - Kept inside each node's encrypted record, they'd hide the shape from
    outsiders. The price is rewriting the record whenever one of its edges
    changes: a busy audience node would rewrite a growing list with every
    post.
- **Records per node, or one excerpt store per audience**, encrypted under
  the audience's key. An excerpt is simpler to read, but rotating means
  re-encrypting all of it. Leaning: records per node, whose cost stays
  local.

**Everyone** is the principal whose key is published in the clear, so its
cone is public through the same mechanism, with no special case. The other
option is to leave its records unencrypted (S7). Either way, whatever was
published under it stays public.

### 4.3 Removing an edge, in a DAG

**Why trees are easy.** In a tree a child's key can be derived from its
parent's, `K_c = H(K_parent, c)`, with no tokens at all. Rotating a subtree
is one new root key, and everything below follows.

**In a DAG that fails**: a node with two parents can't be a function of
each parent's key. So every node has an independent key, and each edge a
public token. That's the Atallah–Frikken–Blanton construction ACT §2.3
chose, and `ontodag.act` implements it.

- **Adding an edge** costs one token.
- **Removing an edge** is the hard part. Deleting the token isn't enough,
  though it's all `KeyGraph.unlink` does today: anyone who walked the edge
  may have kept every key below it.

**Which keys, and when.** After each commit, `sharing.losses(before,
after, principals)` names the nodes some principal lost. Four rules for
rotating them ran on the same 200 random stores and the same 5,866 random
edits:

| Rule | Rotations per edit | Edits after which a reader could derive a key minted after it lost access |
|---|---|---|
| **eager**: rotate every lost node, at once | 0.57 | **0** |
| **internal**: rotate only lost nodes that have children (what `KeyGraph.revoke` does) | 0.24 | 417: a node without children today can gain one tomorrow |
| **lazy**: rotate a lost node only before something new is wrapped under it, **then upward to a fixpoint** | 0.09 | **0** |
| **lazy, without the fixpoint** | 0.07 | 393: rotating a node re-wraps its new key under its parents, which may be lost and unrotated too |

"A key minted after it lost access" is the property that matters. A
reader keeps what it had (forward-only), and must never get anything new.

Eager promises more: after every edit, no current key outside a reader's
reach is derivable at all. Lazy gives that up on purpose. After 5,419 of
the 5,866 edits, some reader still held the current key of a node it had
lost, with nothing new under that key.

**The cost, on one group.** The group has 50 members and 1,000 items in
folders, some with two parents. One member leaves, then two posts arrive:

| | eager | lazy |
|---|---|---|
| the member leaves | 1,001 rotations; 1,143 of 1,193 records rewritten | no rotations; 1 record (the leaver's token) |
| the next post, in the group | 1 record | 1 rotation, 119 records |
| a post in a folder six levels down | 1 record | 9 rotations (the folder and the 8 lost folders above it), 496 records |

- **Under both rules** the other 49 members derive exactly their reach, the
  member who left derives neither new post, and nothing touches file
  content.
- **With lazy**, the 991 lost nodes still unrotated cost nothing until
  someone writes under them.

**Changes to a node's own record** also trigger a lazy rotation in the real
implementation: a new version or a rename wraps something new under its
key too.

**Other edits:**
- **Removing a node** (`remove`) contracts it: its children reattach to its
  parents, so only the node itself is lost, and nothing below it rotates.
  ACT §2.7 warned that the reattached edges need tokens; the derived plan
  mints them without being told.
- **Moving** is an addition plus a removal.
- **Removing a person** removes their principal node, so everything they
  reached is lost. It's the same rule, though the spike doesn't exercise it.

**When to rotate is a policy** (S6):
- at once (eager);
- before the next write under a lost node (lazy, the leaning);
- at most once per period, which saves cost and hides exact timing, but
  leaves a window for new content.

**Lazy also helps privacy.** Token records carry their epoch in the clear,
so a rotation is visible to anyone. Under lazy it shows at the next write,
not at the moment of the removal.

### 4.4 What an observer learns

Anyone can see:
- **the shape of the author's key graph**: token counts, fan-out, depth
  (unless tokens move into records, S5);
- **how many grantee entries** there are, which is roughly how many people
  the author shares with;
- **record sizes, and when things change**, including rotations, from the
  epochs.

Nobody can see:
- **names, content, or who the readers are.** Grantee entries sit at
  ECDH-derived lookup keys that only the author and that reader can
  compute, so readers can't enumerate each other.

**One fix is needed first.** `ontodag.act.node_id` is `sha256(public
domain ‖ name)`, a default the ACT Phase 1 notes left open to revision.
Anyone can compute an id from a guessed name, and that turns the visible
shape into answers:
- grantee entries record their principal's id, so anyone can test "does
  this author share with `ada@categor.io`?";
- a reader who holds `employee-information` sees a token into it from a
  node it can't open. It can test whether that node is `merger-plans`, the
  parent SHARING §2 promises stays closed.

Node ids should be **keyed with an author secret** (an HMAC). Readers learn
the ids they need from the tokens they walk anyway (S4). Padding and decoy
entries (ACT §6, §9) would hide sizes and timing further (S8).

## 5. Receiving: consent, requests, the inbox

- **Following** someone means adding their identity to your own store, as
  on categor.io. Your client then:
  1. finds your grantee entry in their key plan, by the ECDH lookup (no
     listing needed);
  2. walks the tokens;
  3. decrypts the records it reaches, and polls their wall.

  Nobody has to tell you what's shared with you: you can check any author
  you know of.
- **The first walk costs about one round trip per level** of the author's
  key graph, if each level is fetched as one batch: the frontier batching
  that BROWSER.md §4 simulated for queries. Later walks fetch only what
  changed. Two changes are needed for Swarm (Phase 1):
  - today's `Resolver` lists every token in the store before walking. On
    Swarm it should list `act/t/<u>/` for each node it holds, so a walk
    costs its reach, not the author's whole graph;
  - deep graphs want shortcut tokens (ACT §6), which cost more tokens and
    more rotations.
- **Requests from strangers** need a way to reach you. That's ucomm's
  unsolicited first contact: an open GSOC mailbox per identity (ucomm
  DESIGN §6), where a small signed notice ("*acme* shared 3 things with
  you") arrives. ucomm's spam economics apply there: postage floor,
  attention bonds, ceilings.
  - **The honest limit:** listening on a GSOC mailbox needs a full node,
    yours or a relay's, and the relay sees traffic metadata (ucomm DESIGN
    §5).
  - Out of band always works: a link, a QR code.
  - Following someone needs no mailbox at all (S11).
- **Consent needs no enforcement.** Nothing arrives that your client
  didn't fetch. Blocking means not fetching, and dropping their notices.
  Per-persona request settings become attention policy.
- **The inbox is ucomm's universal inbox:**
  - your followed authors;
  - a poll of their walls;
  - the attention engine grading what's new.

**Polling is the cost to watch.** On Swarm, asking for an update that
doesn't exist yet costs a whole retrieval attempt (dappdata T18: 3.6–9 s,
or its 2 s bound). Every poll of a quiet author is such a miss. So,
applying T18's bound, 200 follows polled 20 at a time cost about 20 s a
round when nothing is new. The responses (S10):
- one feed per author, not one per audience (S9);
- quiet authors polled less often;
- push hints through a relay where there is one, never required (ucomm
  invariant 7).

ucomm's W-Q2 asks the related question: does a new post need a
control-plane event at all, or is the log update the signal?

## 6. Walls

- **Every post already has its own keys.** It's a node, filed under its
  audiences, so the key plan gives it a derivation key and a data key,
  reachable from each of them. That's ACT §2.4's per-document keys, with no
  separate mechanism.
- **A wall is one log per author**, a sequential Swarm feed of post
  entries. That's ucomm's wall channel (its WALLS_AND_INBOXES §2), and the
  joint design's leaning (WALLS_AND_INBOXES Q1, ucomm W-Q1).
  - An entry carries the post's id, the tokens into it from its audiences,
    and the encrypted post. A reader opens the entries it has a key for.
  - The feed index fixes the order, which the author can't rewrite once
    readers have seen it. `posted` is the author's claim, for display
    (WALLS_AND_INBOXES Q2).
  - Anyone who can read the log sees how often the author posts, and how
    many audiences each post has; with keyed ids, not which ones.
- **An audience whose activity is itself sensitive** can have a separate
  log at a feed only that audience can find.
  - Its topic is derived from the audience's key and announced inside the
    audience node's record, and rotating that key moves the log too.
  - That answers W-Q1's objection, that the channels which exist reveal the
    audiences. The cost is one more poll per such audience (S9).
- **Replies** refer to someone else's post.
  - On Swarm a post already has a global name: its author's key plus its
    log position. That's the cross-store name that SHARING Q5 and
    WALLS_AND_INBOXES Q5 and Q7 lack, one level below OntoDAG names (S15).
  - What a reader who can't see the original sees is ucomm's W-Q4.
- **Chats** are better as ratchet channels (§0), for forward secrecy.
  "Two walls addressed to each other" stays the model; the encryption
  underneath differs.

## 7. Groups that belong to organisations

This is where Swarm goes beyond the server. **A group can be its own
principal, with a keypair**, as ACT §3 already gives every people node.

- **Membership.** Acme's store holds the group `employees`, with its
  members filed above it. The group's keypair is derived from its
  derivation key, so every member who reaches the group holds its private
  key.
- **Sharing across stores.** Anyone else can then share with "Acme's
  employees" by granting to the group's *public* key, in their own store,
  **without knowing who the members are**.
  - Members get in through Acme's key plan.
  - On categor.io, a group belonged to one store; here it can be used from
    any store.
- **The cost is rotation across stores.** When a member leaves, Acme must
  rotate the group's keypair at once. Lazy rotation doesn't apply, because
  Acme can't see when someone else wraps something new for the group.
  Everyone who granted to the old public key must then re-grant to the new
  one, and rotate what the old key reached, as for any changed key (§2).
  That needs:
  - a feed with the group's current public key, by epoch;
  - clients that re-grant when it changes;
  - honesty about the window in between (S13).
- **Trust.** Whoever holds the group key reads everything shared with the
  group (ACT §6's trust model): every member, and Acme's admins. Sharing
  with an organisation's group means trusting it with who's a member.
- **Custody.** An organisation's keys are held by several admins. Two
  options:
  - dappdata's D28 (one seed, several unlock keys) for the organisation's
    identity;
  - delegated sub-stores: a department's own store and key plan, nested
    under the organisation's by a token.

## 8. Clients and runtime

- **Browser:**
  - **OntoDAG** runs under Pyodide, with canonical roots byte-identical to
    native ones (BROWSER.md). Reading a store lazily from Swarm is designed
    and simulated there, at about 12 round trips for a first query and 4–5
    after it, but it hasn't run against a node.
  - **dappdata** is TypeScript, and it's where identity and storage live.
  - **The key-plan crypto** (Keccak, secp256k1, Bee's stream cipher) has
    pinned vectors already. So a TypeScript port on noble's libraries is
    transcription, as the Python one was (ACT §5).
  - **Or none at all, for the reader:** the key plan already runs under
    Pyodide. Pyodide has pycryptodome, and `ontodag.act` falls back to a
    pure-Python secp256k1 where coincurve is missing (§13).
  - The open question is how much of the reader belongs in TypeScript and
    how much in Pyodide (S15).
- **Command line and desktop:** Python end to end (`odag` with the `swarm`
  and `act` extras), and ucomm's daemon.
- **categor.io** becomes one client among several: a hosted page that holds
  no keys. It could stay a bridge for people who'd rather not manage keys,
  with stores that move to Swarm when their owners want (S16).

## 9. Is it a good way to communicate on Swarm?

**Where it's strong:**

- **Single-owner writes, readers merge.** There's no shared write state,
  which matches what Swarm's feeds and single-owner chunks offer.
- **Audiences with structure, at constant cost per change.** A new member
  costs one grantee entry and one token, and a new share one token,
  whatever the group's size. That solves the flat-list problem of ACT §1.
- **Receivers are hidden from each other** by construction; only their
  number shows (§4.4).
- **Consent is free.** Pull-only means nothing forces its way in, and the
  attention layer decides what's worth showing.
- **Grants are auditable.** The author can justify any grant or denial
  against a pinned root with OntoDAG's `is_below` certificates (ACT §2.7,
  SHARING §4.2).
- **Cost doubles as spam defence.** Every author pays postage for their
  own writes.

**Where it's weak, and whose weakness it is:**

| Weakness | Whose | Mitigation |
|---|---|---|
| push and requests need a full node or a relay | Swarm's, structurally (ucomm DESIGN §5) | polling always works; a relay is optional |
| structure, sizes and timing are visible | ACT's and Swarm's | keyed node ids (S4), tokens inside records (S5), padding (S8), lazy rotation |
| revocation is forward-only | inherent to immutable storage | say so plainly; lazy rotation keeps it cheap |
| polling is slow, because every miss costs a retrieval | Swarm's retrieval | one feed per author, adaptive polling, optional push |
| no forward secrecy for publication keys | this design's | ratchets for conversations (§0) |
| a group used across stores means rotation across stores | this design's | epoch feeds, automatic re-grants (§7) |
| two devices writing at once, and removals that come back | shared with dappdata and OntoDAG's sync | unshare from one writer until tombstones are decided (S14) |

**Against the alternatives:**
- **Plain ACT** is flat lists, fine for a few readers.
- **MLS** gives groups forward secrecy and cheap removal, but no hierarchy
  and no shared categories: it suits conversations.
- **Nostr and ActivityPub** put relays or servers in the path. They see at
  least the traffic, and an ActivityPub server holds its users' posts in
  the clear.

**Verdict:** it's a good way to publish to audiences on Swarm, and honest
about its limits. Pair it with ratchets for conversation, and don't make
the push path a requirement.

## 10. The plan

Each phase ends at a gate that can be checked.

| Phase | Work | Gate |
|---|---|---|
| **0: Decide** | the §11 topics, with Peter; the spike's properties become tests | the leanings accepted, amended or refused |
| **1: Key plan in OntoDAG** (local stores only) | `act.plan(store, principals)` from reach, computed hops included, replacing `align`; lazy rotation from `losses` with the upward fixpoint, replacing `revoke`'s rule; derivation and data keys; keyed node ids; per-node records; the `Resolver` listing per node | the spike's properties as tests; a differential test: the same stores give categor.io's server views and the key-derived views, equal |
| **2: On Swarm, one author, command line** | publish a plan and records to a `swarm:` store; `odag` reads a friend's shares with its own key | walk round trips, polling misses and postage measured on mainnet; the 1,000-item group's removal measured there |
| **3: Identity** | a sharing identity and persona keys with dappdata (S1), and with Swarm ID if D24's shared spec lands; contact cards | one wallet opens the same sharing identity in two clients |
| **4: Browser reader** | Pyodide OntoDAG plus TypeScript key-plan crypto; the public vocabulary read lazily | a browser shows a friend's shares with no server |
| **5: Walls and inboxes** | one log per author; ucomm inbox polling and attention; `posted` (WALLS_AND_INBOXES Q3) | 200 follows polled within a stated budget |
| **6: Requests and push** | a GSOC mailbox or relay behind ucomm's `Rendezvous` interface; spam economics | requests work with the relay off (out of band) and on |
| **7: Groups across stores** | group principals with keypairs; epoch feeds; automatic re-grants; custody (D28) | after a member leaves Acme, a third party's next post to "Acme's employees" doesn't reach them |
| **8: Specify** | a SWIP for the key-plan format (ACT Phase 3); the Bee header for caller-supplied keys, if plain Bee clients need it (ACT Phase 2) | the format read by a second implementation |

## 11. Discussion topics

Each has options and a leaning; none is decided.

**Identity and principals**

- **S1 — A sharing identity's scope.**
  - Per app (dappdata's default, D16), one key for every client of the
    protocol (a declared or reserved app identity: D16, D7), or per
    persona?
  - And does every device hold the decryption key, or do authors grant per
    device?
  - *Leaning:* one key per persona, under a reserved protocol identity,
    held by each of the user's devices. Phishing resistance then rests on
    the wallet showing which site asks, as dappdata T14 accepts.
- **S2 — Principals on Swarm** (SHARING Q1, from Swarm's side). A
  principal must be bound to a public key. So the author's store has to say
  which names are principals, and with which key: Q1's option (b), a
  declaration, with a key attached. Q1 is Peter's to decide; this is what
  Swarm adds to it.
- **S3 — How people find each other's keys.** Contact cards, ENS text
  records, a Swarm ID directory, QR codes. *Leaning:* contact cards first,
  ENS optional, never a global list.

**The key plan**

- **S4 — Node ids.** Unkeyed sha256 (today, guessable: §4.4), or keyed by
  an author secret. *Leaning:* keyed. It's a small change, and it removes a
  real leak.
- **S5 — Where structure lives.** Tokens as their own records (today;
  shape visible) or inside each node's encrypted record (shape hidden;
  busy nodes rewrite long lists). Records per node, or an excerpt per
  audience (§4.2; ACT §9's token-set storage question). *Leaning:* records
  per node, and tokens as their own records for now; measure the other
  option in Phase 2.
- **S6 — When to rotate.** Eager, lazy with the upward fixpoint, or once
  per period. *Leaning:* lazy, with a "rotate now" for urgent removals.
  Group principals that other stores use always rotate at once (§7).
- **S7 — Public content.** A published key (one mechanism for everything),
  or unencrypted records (cheaper to read). *Leaning:* unencrypted records
  for `everyone`: it's public anyway, and readers shouldn't pay for
  decryption.
- **S8 — Padding.** Do padding and decoys go into v1 of the format (ACT
  §9), or later?

**Delivery**

- **S9 — Walls.** One log per author (the joint design's leaning), a log
  per audience, or both (§6). *Leaning:* one per author, plus a hidden log
  for any audience whose activity is itself sensitive.
- **S10 — Polling at scale.** How often to poll, how many polls in flight,
  and whether a new post needs its own signal (ucomm W-Q2). *Leaning:* one
  feed per author, adaptive intervals, optional hints.
- **S11 — Requests from strangers.** A GSOC mailbox (needs a full node or a
  relay), out of band only, or both. *Leaning:* both, with the mailbox
  optional.
- **S12 — Conversations.** Ratchets (ucomm chat, MLS) or walls to one
  person. *Leaning:* ratchets, under the same inbox and consent.

**Organisations and devices**

- **S13 — Groups across stores.**
  - Offer group principals at all, given rotation across stores?
  - What format does the epoch feed take?
  - How quickly must re-grants follow?
  - *Leaning:* offer them; they're the main thing a server couldn't do.
- **S14 — Two devices, and removals that come back.** OntoDAG's sync is
  grow-only, so an unshare on one device can return with another's sync
  (§3). Three responses:
  - unshare from one writer only;
  - show the author what a sync would re-share, before the plan is
    published;
  - settle tombstones in OntoDAG first.

  *Leaning:* the first two now. The third is OntoDAG's open decision
  (SWARM_DESIGN.md), and this is one more reason to make it.

**Platform**

- **S15 — Runtime and names.** How much of the reader goes to TypeScript,
  and how much to Pyodide? And how do OntoDAG names map to Swarm addresses
  for replies and cross-store references (SHARING Q5, WALLS_AND_INBOXES Q5
  and Q7)?
- **S16 — categor.io's role.** A hosted client with no keys, a bridge, or
  retired. *Leaning:* a hosted client and bridge, with stores exportable to
  Swarm.
- **S17 — Costs and who pays.** Each author pays for their own writes and
  rotations; readers pay nothing but bandwidth. Is lazy rotation's low
  steady cost enough, or are quotas needed?
- **S18 — Bee's own ACT storage.** Keep grantee entries in OntoDAG's
  record store (canonical roots, epochs as versions), or in Bee's ACT
  key-value store and history? *Leaning:* OntoDAG's store for now. Keep
  the entries format-compatible, so a Bee-native path stays open (ACT
  Phase 2).

## 12. What was checked, and how

`experiments/keyplan_spike.py`, against OntoDAG 0.28 and `ontodag.act`,
with an in-memory record store. `python experiments/keyplan_spike.py`
reproduces every number above, in under two minutes on 8 cores.

- **Stores:** 200 random stores (seeds 0–199). Each has:
  - three readers, and two groups, sometimes nested;
  - fourteen items;
  - usually a share of `posted(2026)`, with posts at times inside it.
- **Edits:** up to 30 random edits each (5,866 in all): filing, unfiling,
  and removing nodes. The store and its edits come from one random
  generator and the keys from another, so every rule saw the same edits.
- **Correctness:** after every edit, under every rule, each reader
  derived exactly its reach, typed values included. **No mismatches.**
- **Revocation:** after every edit, the spike checked a reader that kept
  every key it ever derived, against both properties of §4.3.
- **One large group:** the second table of §4.3.

Earlier runs of the spike, whose edits also drew on the key randomness,
agree: 6,768 edits under eager and 7,318 under lazy, with no mismatches and
no new keys exposed.

What the spike doesn't check:
- anything on a real Swarm network (§13 has the first run);
- identity (Phase 3);
- the real per-node records and data keys (the spike models tokens and
  grantee entries only; `ontodag.keyplan` has them, §13);
- removing a principal, or a principal changing its key (tested on
  `keyplan`, §13);
- costs at scale.

## 13. Built so far (2026-09-25)

Everything here is on OntoDAG's `swarm-sharing` branch, unreleased.

**Phase 1: `ontodag.keyplan`.** `Publisher` and `Reader` as §4 describes,
with these leanings taken:
- the plan is derived from reach at every publication, computed hops
  included (`plan()`), in place of `KeyGraph.align`;
- node ids are keyed (S4);
- each node has a rotating derivation key, and each content version its
  own data key (§4.2);
- a record per node names the node and its typed-value parents, never its
  private parents or children, and tokens stay as their own records for
  now (S5);
- rotation is lazy, with the upward fixpoint, and record changes count as
  something new; `eager=True` rotates everything stale at once (S6);
- a removed or re-keyed principal loses everything it reached;
- `everyone` is a principal with a published key, so one mechanism covers
  public content too (S7's first option, for now);
- a reader lists only its own nodes' tokens, and reads each level of the
  walk concurrently over a `RecordStore`.

**Walls come with it:**
- `sharing.timeline` (WALLS_AND_INBOXES build order item 1);
- `Received.timeline()`, equal to the server's timeline for each reader;
- `receive(public=True)`, which adds the author's public posts;
- `keyplan.inbox()`, which merges several authors' walls.

**Tests.** `tests/test_keyplan.py` has 18, `tests/test_sharing.py` 3 more,
and `tests/test_act.py` 2 more. They cover:
- exact reach and exact edges;
- timelines equal to the server's;
- lazy and eager revocation;
- re-keyed and removed principals;
- the pure-Python curve against coincurve and Bee's vectors;
- a random-store property test: a reader that kept every key it ever held
  opens only record versions it was once entitled to.

That last test fails under both deliberate mutations: no fixpoint, and
record changes ignored.

**At scale, in memory** (50 members, 1,000 items):
- 2,345 records published in 1.0 s;
- a member reads their 1,002 names in 0.7 s;
- a member leaving rotates nothing and deletes one record;
- the next post rotates the group, writing 121 records.

**In a browser's Python.** `demo/pyodide/keyplan.mjs` runs publish, read,
revoke and post under Pyodide 0.27.7.
- Pyodide has pycryptodome but not coincurve. So `ontodag.act` falls back
  to a pure-Python secp256k1, which is pinned to coincurve and to Bee's
  vectors by the tests, and is not constant-time.
- Everything checked out, in 0.5 s after a 7 s install.

**On Swarm mainnet** (`experiments/keyplan_swarm.py`; a light node, Bee
2.8.2, and a one-day batch bought for it; results in
`experiments/keyplan_swarm_2026-09-25.json`). Ada's store has 120 items in
folders shared with a group of two, a share of all her 2026 posts with Bob,
and a public post:

| | one key at a time | 16 workers per level |
|---|---|---|
| first publication | 272 records, 641 chunks, 25 s | the same, 26–27 s |
| Bob's first read (130 names), through our node | 106 s | 25–27 s |
| the same, through the public gateway, which never held the data | 70 s | 16–17 s |
| Carol leaves the group | nothing rotated: 1 record deleted, 1.5–1.9 s | the same |
| Ada posts in the group | `friends` rotated: 41 records, 6–7 s | the same |

- **Every read equalled `sharing.reach`** for its reader, and a stranger
  got nothing.
- **Carol**, holding every key she had ever had, couldn't open the post
  made after she left; Bob read it.
- **Bob's inbox:** a second author, Dan, published to his own feed. Bob's
  inbox read both walls from Swarm and merged them in `posted` order,
  public posts included (six posts from the two walls, Dan's public one included, in 17.5 s).
- **Opening a feed cost 1–10 s** before any record was fetched, on every
  read (1.2 s through the gateway). That's a Swarm feed lookup, the cost of
  a miss in dappdata's T18. Readers that remember the last root and index
  could skip most of it (S10).
- **Cold reads are round-trip bound.** 130 names took 400–500 fetches of
  trie nodes and records. Reading each level concurrently made the first
  read about 4× faster. Fewer, bigger records (tokens inside records, S5)
  would cut the count itself.

**Bee needs no change for this.** Its ACT (`pkg/accesscontrol`) works like
this:
- it keeps one access key per ACT;
- revoking a grantee creates a new ACT with a new key and re-adds every
  remaining grantee;
- downloads always use the node's own key.

So the walk belongs in the client, as ACT §4 said. The optional header of
ACT Phase 2 would matter only if content were stored as Bee ACT
references, which `keyplan` doesn't do.

**Not built yet:**
- a CLI;
- identity (Phase 3; dappdata's D29 is proposed);
- a browser page reading from a node (Phase 4's Swarm half);
- requests and push (Phase 6);
- groups across stores (Phase 7);
- S5's other record layout;
- a fix for `KeyGraph.revoke` itself.
