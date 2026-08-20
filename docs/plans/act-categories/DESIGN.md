# Category-Based Access Control on Swarm: OntoDAG as a Key Graph

Status: discussion draft (August 2026). Nothing here is implemented. This
document is written to become, in whole or in parts: (a) the design record for
an OntoDAG feature, (b) a Bee feature-request issue, and (c) possibly a SWIP
for the on-Swarm key-graph format. §8 recommends which part goes where.

Companion reading: `docs/SWARM_DESIGN.md` (how OntoDAG persists on Swarm via
`recordstore`), and in the Bee repository `pkg/accesscontrol/` (the ACT
implementation this design builds on).

## 1. Problem

Swarm's Access Control Trie (ACT) grants access to encrypted content by
enumerating grantees: for each (publisher, grantee-public-key) pair, an entry
in a key-value store holds the content's *access key*, encrypted under an
ECDH-derived secret. This is exact but flat, and it scales badly in both
directions:

- **By reader**: granting a 500-person organization access to a document means
  500 KVS entries; hiring one person means touching the ACT of every document
  they should see.
- **By document**: every new document needs its own grant ceremony, even when
  its intended audience is identical to a thousand existing documents ("all
  departmental documents").

Organizations do not think in key lists. They think in categories: *company >
department > employee* on the people side, *reports > financial reports >
Q3 report* on the document side. OntoDAG already represents exactly such
category DAGs, with subsumption queries ("is x below C?") as the core
operation. This proposal makes that subsumption relation *cryptographically
enforced*: membership in a category, not presence in a list, is what decrypts.

**Division of labor with store-level encryption (added 2026-08-20).**
This design gates *content*: the claims (which document sits in which
category) remain visible as structure and manifests — §6 names the
leakage honestly. When the *structure itself* is the secret, the answer
is different and complementary: per-audience stores (overlays), because
claims within one canonical store cannot have per-reader visibility —
the canonical root hashes everything, and transitive reduction does not
survive projection (the public view of a reduced private graph is not
the reduction of the public view). The two mechanisms meet at one seam:
an encrypted overlay's blobs should take their key **from the
audience's node in this key graph**, making "a private overlay" and "a
document category with an audience bridge" one mechanism rather than
two. See `docs/plans/PROJECTIONS.md` for the layering contract this
slots into.

## 2. Construction

### 2.1 One directed graph, access = reachability

Every category node `v` (people or document) gets an independent random
symmetric key `K_v`. For every edge `u -> v` along which access should flow,
a public **rekeying token** is published:

    T(u -> v) = Enc(K_u, K_v)

Anyone holding `K_u` unwraps `K_v` and continues walking; the tokens are
one-way, so nobody walks against the arrows. The invariant of the whole
design is a single rule:

> **Tokens point in the direction access flows. A reader can decrypt a
> document iff a directed token path exists from their personal leaf to the
> document's key.**

Tokens are 32-byte-scale public data; the token set can live on Swarm next to
the OntoDAG structure itself — the tokens *are* the edges, annotated with
ciphertext.

### 2.2 The two halves have opposite key directions

```
alice ──▶ eng-dept ──▶ company          people: keys flow specific -> general
              │            │
              ▼ bridge     ▼ bridge     grant = one edge, reader-cat -> doc-cat
        eng-documents   company-docs
              │   │
              ▼   ▼                     documents: keys flow general -> specific
           doc-42  design-specs ──▶ doc-57
```

- **People DAG — upward.** More specific = fewer members. An employee derives
  the department key, the department key derives the company key; never the
  reverse. (This is the inverse of classic Akl–Taylor military-classification
  hierarchies; same machinery, edges flipped.)
- **Document DAG — downward.** A grant on a document category opens everything
  inside it: the "reports" key derives "financial-reports", which derives
  individual document keys.
- **Bridges.** A grant is a single edge from a people node to a document
  category: `T(K_eng-dept -> K_eng-documents)`.

**The design trap this rule prevents:** document categories must encode
*topic/containment*, never *audience*. If "departmental documents" were
modeled as a subcategory of "company documents", downward derivation would
hand every company-level reader the departmental documents — exactly wrong.
Audience is expressed solely by *which people-node a bridge comes from*;
"company-wide docs" and "eng-only docs" are sibling document categories with
bridges from different heights of the people DAG.

### 2.3 Why tokens, not pure KDF chains

`K_parent = KDF(K_child)` works only in trees. In a DAG a node has several
children and several parents, so its key cannot be a deterministic function of
each neighbor's key. Independent random keys plus per-edge tokens (the
Atallah–Frikken–Blanton key-assignment construction) handle arbitrary DAGs,
including OntoDAG's multiple inheritance: a person in two departments has two
outgoing paths; a document in two categories has two incoming tokens.

### 2.4 Per-document keys, wrapped

Documents are encrypted under their own fresh key (in Bee ACT terms: the ACT
access key), reachable via a token from each containing category. This allows
a document to sit in several categories, to be individually granted to one
extra person, and to be re-categorized later by republishing a 32-byte token
instead of re-encrypting the content.

### 2.5 Boolean audiences for free

- **AND**: encrypt under `KDF(K_A || K_B)` — readable only by someone who can
  derive both category keys. Pairs directly with OntoDAG intersection
  categories. **Ordering must be canonical** (concatenate in sorted
  category-name order, added 2026-08-20): `KDF(K_A || K_B)` and
  `KDF(K_B || K_A)` are different keys, so without the sort two writers
  mint divergent intersection keys — the G1 discipline applied to key
  derivation. One line in the eventual format spec, expensive to
  retrofit.
- **OR**: publish two tokens (or two ACT grantee entries).

### 2.6 Everyday operations, and their cost

| Operation | Work |
|---|---|
| Publish a document into a category | 1 fresh key, 1 token, 1 manifest entry — touches no readers |
| Hire an employee | 1 token `Enc(ECDH(org, employee_pk), K_leaf)` — touches no documents |
| Grant a reader category a document category | 1 bridge token |
| Read a document | walk up, across, down: d token unwraps (d = path length; shortcut tokens can cap this) |
| Remove an employee | rotate `K` on their leaf and all ancestors, republish affected tokens, re-wrap forward keys — see §6 |

### 2.7 Interactions with the knowledge DAG's own mutations (added 2026-08-20)

The table above covers grants; the knowledge DAG also mutates
(`put`-triggered reduction, `remove`'s contraction, `move`/`reclassify`,
`remove --cone`), and each has a key-graph consequence this document
originally predated:

- **Reduction pruning an edge is harmless.** Tokens only need *some*
  path, and reduction preserves reachability, so a stale token for a
  pruned edge grants nothing reachability didn't already grant. It can
  be garbage-collected lazily or left.
- **Contraction re-adds edges that need fresh tokens.** `remove X`
  reattaches X's children to X's parents; each reattached edge is a new
  access path that has no token until one is minted — access silently
  breaks otherwise. Any deleting operation must therefore drive token
  minting through the same seam that drives the record updates.
- **`move` retires tokens at the next epoch** (the retracted edge's
  token should stop working forward), and **cone removal deletes whole
  token sets** — both are epoch events, not merely data edits.
- **The contested set is the residual-access report.** `odag move
  --dry-run` already computes exactly what a revocation officer needs:
  members reachable in both the old and the new state via another path.
  "Remove Alice from eng-dept" answers "what can Alice still read
  through her other memberships" with the same query (`get old new`)
  and the same code. The §6 revocation story gets a working preview
  tool for free.
- **Access decisions can carry certificates.** The walk is `is_below`
  with unwrapping — ancestors(person), bridge, descendants(category) is
  the query planner's probe shape — and `is_below` already produces
  offline-verifiable Merkle certificates. A grant or denial can
  therefore be *auditably justified* against a pinned root: "provably
  entitled as of root R." Few access-control systems get that property
  this cheaply.

## 3. Mapping onto Bee's existing ACT

The pivotal implementation fact (Bee `pkg/accesscontrol/access.go`): **the ACT
access key is per-ACT, not per-reference.** `EncryptRef` reuses one access key
for every reference encrypted with that ACT. A single ACT is therefore
already a "fixed reader set + unbounded stream of documents" object; Bee just
has no notion of grantee *groups* or document *collections* around it. This
proposal supplies both without changing the crypto core:

- **One ACT per document category.** The ACT access key *is* `K_cat`. Adding
  a document is one `EncryptRef` — already supported. The encrypted
  references live in a mantaray manifest owned by the category, with a feed on
  top so the category is mutable in place. (Bee's server-side manifest
  listing endpoint makes enumerating a category a single API call.)
- **Grantees of that ACT are category keypairs, not individuals.** Each
  people-node gets a secp256k1 keypair; `AddGrantee` is called unchanged with
  the category's public key. The people-DAG token walk is what turns "I am
  Alice, holding my personal key" into "I hold the eng-dept private key", at
  which point Bee's existing `Session`/`DecryptRef` path applies verbatim.
- **Document-subcategory edges** are tokens between ACT access keys,
  `Enc(K_reports, K_financial-reports)`, stored alongside the manifests.
- **Epochs** reuse Bee's ACT history mechanism (`history.go`, timestamped
  ACT versions): a key rotation is a new history entry; old epochs stay
  decryptable for old content.

Everything above the crypto core — token graph, category manifests, feeds,
walk resolution — is plain content-addressed data read and written through
Bee's existing HTTP API.

## 4. Work split: Bee vs OntoDAG

The design goal is to keep the Bee side as close to zero as possible, and it
gets genuinely close, because of one more Bee fact: Bee's ACT endpoints use
*the node's own private key* as the session key. Category private keys are
keys a Bee node does not hold and should not hold. So server-side resolution
inside Bee is not the natural home for this even if we wanted it — the walk
belongs in the client.

### Phase 1 — MVP, zero Bee changes (all OntoDAG)

OntoDAG implements the scheme entirely client-side against a stock Bee node:

1. **Category keypair management** — mint/store secp256k1 keypairs per
   category node (org-side); personal keys stay with users.
2. **Token graph** — put/get tokens as records (via `recordstore`), plus the
   walk resolver (directed reachability with memoized unwrapping; shortcut
   tokens as an optimization).
3. **ACT-compatible crypto in Python** — reimplement the deterministic
   primitives Bee uses: secp256k1 ECDH (`coincurve`), Keccak-256
   (`eth-hash`/`pycryptodome`), and Bee's `pkg/encryption` scheme for
   access-key wrapping and reference encryption, plus the KVS lookup-key
   derivation from `access.go` (`getKeys`: keccak(ECDH.x || nonce)).
   **Cross-language test vectors generated from Bee's Go tests are a hard
   requirement** — this is the only place the two codebases must agree
   bit-for-bit.
4. **Category manifests + feeds** — the document-category listing convention;
   `recordstore` already covers the substrate.

Result: any OntoDAG client can publish into and read from category-protected
collections; the Bee node is pure storage.

### Phase 2 — Bee convenience (small, optional; the feature-request issue)

Without Bee changes, a *plain* Bee client (curl, bee-js) cannot download
category-protected content even when handed the resolved key, because Bee's
`/bzz` ACT path only derives session secrets from the node's own key. The
smallest useful Bee change:

- Accept a caller-supplied **decrypted access key** (or ECDH session secret —
  never a private key) on ACT downloads, e.g. a `Swarm-Act-Access-Key` header
  alongside the existing `Swarm-Act*` headers. OntoDAG resolves the walk,
  hands Bee the 32-byte key, Bee does what it already does.
- Estimated scope: `pkg/api` header plumbing + a small `accesscontrol`
  entry point that skips `getAccessKey`. Days of work; the review cost is
  the security discussion, not the code.

### Phase 3 — Interop spec (the SWIP)

If the scheme proves out, the durable artifact is not code but the **on-Swarm
key-graph format**: token encoding, node identifiers, manifest layout for
token sets and category listings, epoch/rotation rules, and the ACT
compatibility mapping of §3. Standardizing that lets bee-js, dashboards, and
other clients interoperate without OntoDAG. That is SWIP-shaped; the Phase 2
header is issue-shaped.

### Effort estimate (rough)

| Where | What | Estimate |
|---|---|---|
| OntoDAG | Phase 1 items 1–4 | 3–6 person-weeks (half of it crypto-compat + vectors) |
| Bee | Phase 1 | **zero** |
| Bee | Phase 2 header | ~1 week incl. tests; plus maintainer security review |
| Spec | Phase 3 SWIP draft | 1–2 weeks writing, then process time |

## 5. Does the language difference matter?

Barely, and only at one boundary. Bee is Go, OntoDAG is Python, but their
entire interaction is HTTP plus content-addressed bytes — language-invisible.
The single place the implementations must agree exactly is the deterministic
crypto of Phase 1 item 3 (ECDH-derived lookup keys, Keccak-256, Bee's
`pkg/encryption` stream construction). All primitives exist as mature Python
packages; the risk is subtle convention mismatches (byte ordering of the ECDH
x-coordinate, segment size, nonce placement), and the mitigation is
mechanical: generate test vectors from Bee's Go test suite and pin the Python
implementation to them in CI. No Go code needs to be written on the OntoDAG
side, and no Python on the Bee side.

**Spike DONE (2026-08-20, PACKS.md §14 item 3½): the conventions line up,
bit for bit.** `ontodag/experiments/act_crypto_spike.py` reimplements the
whole deterministic chain in Python (coincurve + pycryptodome) and matches
vectors generated from Bee's own packages at v2.8.1
(`experiments/act_vectors_gen.go`, run inside a bee checkout) plus Bee's own
upstream-authored 4096-byte fixed vector from `encryption_test.go`. The
conventions, now pinned rather than predicted:

- **ECDH shared secret = the x-coordinate as Go's `big.Int.Bytes()`** —
  big-endian **with leading zeros stripped**, so the secret is *sometimes 31
  bytes* (~1/256 of pairs). This is the §5-predicted trap made concrete: a
  fixed-32 encoding agrees on 255/256 key pairs and fails on the rest —
  the worst possible failure mode (works in every demo, breaks for one user
  in 256). Vector 2 is deliberately such a pair (seeds 177/100177).
- `getKeys(pub)` = `[Keccak256(x‖0x00), Keccak256(x‖0x01)]` — lookup key
  and access-key-decryption key.
- The stream cipher: per 32-byte segment,
  `segmentKey = Keccak256(Keccak256(key ‖ LE_uint32(ctr)))`, XOR, counter
  from `initCtr` (0 for ACT) incrementing per segment — note the
  **little-endian** counter, the other predicted trap. Encrypt = decrypt
  (XOR stream), verified round-trip on the access-key wrap and the 64-byte
  reference.

Phase 1's estimate loses its risk premium: the "crypto-compat + vectors"
half is now known to be transcription, not investigation.

## 6. Honest costs and limits

- **Revocation is lazy, and Swarm makes that structural.** Removing a member
  requires rotating keys along their entire upward cone and republishing
  tokens — inherent to any group-key scheme. On top of that, Swarm content is
  immutable: anything the ex-member could already decrypt remains fetchable
  forever with the keys they walked away with. Revocation is strictly
  forward-looking. Design for it explicitly (epochs via ACT history) rather
  than pretending otherwise.
- **Document-level revocation within a category** has the same shape: dropping
  a document's token only affects readers who never held the category key of
  that epoch.
- **Trust model.** Whoever mints the category keys (the org key manager) can
  read everything. This matches ACT's existing publisher-centric model — not a
  regression, but worth stating.
- **Metadata leakage.** The token graph reveals the org's category
  *structure* (node identities can be opaque hashes, but shape and degree are
  visible), and category manifests reveal document counts and growth timing.
  If "legal just gained three documents" is sensitive, padding/decoy entries
  must be part of the manifest format from the start.
- **Walk latency.** Depth-d resolution costs d fetches+unwraps. Shallow org
  DAGs make this trivial; deep ontologies want shortcut tokens (the standard
  optimization in hierarchical key-assignment schemes).

## 7. Alternatives considered

- **CP-ABE** (ciphertext-policy attribute-based encryption) expresses
  "dept=eng OR role=admin" natively without token walks. Rejected here:
  pairing-based crypto with a weak Python/Go ecosystem, larger ciphertexts,
  even harder revocation, and no reuse of Bee's existing primitives. The
  token-DAG scheme uses only symmetric crypto and the ECDH Bee already ships,
  and its trust/revocation story is the same as ACT's, lifted from
  individuals to categories.
- **HIBE** derives keys top-down (parent derives child), which is the wrong
  direction for the people half of this design.
- **Plain ACT with big grantee lists** is the status quo of §1.

## 8. Recommendation: issue vs SWIP

Do both, in order, and keep them small:

1. Build Phase 1 in OntoDAG against a stock Bee node. No permission needed
   from anyone; this also produces the evidence (and the test vectors).
2. File the **Phase 2 header as a Bee feature-request issue** — it is a
   small, self-contained API affordance whose motivation the working Phase 1
   demonstrates. It is too small to be a SWIP.
3. Draft the **Phase 3 format as a SWIP** once the format has survived real
   use — interoperability specs are exactly what SWIPs are for, and the SWIP
   then becomes the reference the Bee issue points at.

## 9. Open questions

- Where do *personal* private keys live and how do users run the resolver —
  odag CLI only, or also a light in-browser client (relevant to
  `docs/plans/BROWSER.md`)?
- Token-set storage: one manifest per node's outgoing edges vs one flat KVS —
  affects walk latency and update locality.
- Epoch granularity: rotate per-node (fine, chatty) vs per-cone (coarse,
  fewer tokens republished)?
- Should the OntoDAG *structure* store and the *key graph* be the same DAG
  instance or two aligned ones? (Same shape, different payloads; keeping them
  separate lets the public structure be replicated without the tokens.)
  §2.7 adds an argument for **aligned twin**: the knowledge DAG
  reshapes under reduction and contraction, while the key graph needs
  only reachability-preserving maintenance — coupling them would make
  every `put` a potential key ceremony.
- Padding/decoy policy for category manifests (§6) — needed in v1 of the
  format or deferrable?
