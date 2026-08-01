# The Agent Surface: OntoDAG over MCP

Status: **v1 shipped 2026-08-01 (read-only).** This is the design note
`CONTRACT.md` §2 scoped out — the concrete tool inventory and answer shapes
behind the contract's capability list. The contract stays tool-agnostic;
this document may change without a contract version bump as long as every
shape below keeps the §2 constraints.

Implementation: `src/ontodag/mcp.py` (`odag-mcp`, or `python3 -m
ontodag.mcp`; `-f STORE` overrides, otherwise it shares `odag`'s configured
store). The transport is MCP's stdio framing — newline-delimited JSON-RPC
2.0, `initialize` / `tools/list` / `tools/call` — implemented on the stdlib
alone, the repo's usual answer to an avoidable dependency. Module-level
imports stay core-only; recordstore loads lazily inside functions (checked
in `tests/test_boundaries.py`). Tests: `tests/test_mcp.py`.

## 1. The answer envelope

Every successful answer is one JSON object:

```json
{
  "root": "<the root this answer is true of>",
  "contract": "0.1",
  "...tool-specific fields...",
  "annotations": {}
}
```

- **`root` is always present** — answers are facts about roots, not about a
  mutable store (`CONTRACT.md` G2 note, §4). A *file* store gets a real one:
  it is hydrated into an in-memory record store and committed on load, so
  even a local store answers with the semantic fingerprint — two agents over
  equal local knowledge cite equal roots (G1 through the surface, tested).
- **`contract`** is `ontodag.CONTRACT_VERSION`: what the caller may assume.
- **`annotations`** is the namespaced extension map of `CONTRACT.md` §2 —
  empty in v1; unknown namespaces must be ignored; guarantee status
  (`annotations.factbond`) rides here later without reshaping anything.

## 2. The tools

| tool | in | out (beyond the envelope) |
|---|---|---|
| `about` | — | store description, item count, top-level categories (≤100), declared dimensions `{head: kind}`, registry + surface versions, server info, capability list. **Read this first** — the discoverability record. |
| `query` | `terms` (conjunction) **xor** `any_of` (list of conjunctions, answered as their union); `as_of?`, `certify?` | `items` (sorted canonical names), `count`, and the **canonical echo** of the terms actually answered |
| `is_below` | `sub`, `sup`; `as_of?`, `certify?` | `result` (fail-closed boolean), canonical echo of both sides |
| `overlapping` | `term`; `as_of?` | `candidates`, `count`, and a `note` naming the modality (G6: recall-complete candidacy, not satisfaction) |
| `describe` | `term`; `as_of?` | canonical `name`, rendered `display`, `exists`, `parents`, `children`, `descendant_count` |
| `canon` | `term` | `canonical`, `display`, surface + registry versions |

Decisions embedded there:

- **Canonical echo everywhere** (`SURFACE_LAYER.md` §14): tools echo the
  canonicalized terms they answered, and `describe`/`canon` return the
  friendly spelling as a sibling `display` field, never in place of the
  name — the web-API rule of §7 (canonical as the field, rendered beside
  it), applied to agents.
- **`show` did not become a tool.** A whole-graph dump is not agent-shaped;
  `about` + `describe` + `query` cover it in bounded pieces.
- **Unknown names fail closed** (empty results, `false`), exactly like the
  core; *malformed* parametric terms raise the core's teaching errors,
  passed through verbatim as tool errors (`isError: true`), never protocol
  errors.
- **`certify: true` is live on `is_below`** (2026-08-01): the answer gains
  a `certificate` field — recordstore proofs of every record the answer
  depends on — checkable by anyone holding the cited root with
  `ontodag.certificates.verify_below(certificate, root)`, no store access.
  Both polarities, virtual parametric terms included; the certificate pins
  the registry version and a mismatched verifier refuses. On `query` the
  parameter stays reserved (result-soundness proofs are cone-sized; the
  teaching error points at certifying individual candidates via
  `is_below`).

## 3. as-of

Query tools take `as_of: <root>`; the answer then cites that root. Backed by
`RecordStore.at(root)` + `LazyOntoDAG` — the contract's §4 mechanism. A
record-store-backed store serves any retrievable root; a file-backed store
keeps no history, so only its current root is available, and the error for
anything else teaches exactly that.

## 4. The discoverability record

Computed **on demand** by `about`, never stored — the `CONTRACT.md` §2
constraint (a summary inside the store would make the root depend on a
description of itself). If serverless thin clients ever need it, it can be
*published beside* the store, manifest-style, like cone indexes — a later
decision that changes nothing here.

## 5. The tripwire instrument

Every failed tool call is logged as a JSON line — `{event, tool, arguments,
error}` — to stderr, and appended to `$ONTODAG_MCP_LOG` when set. What
agents try and cannot express is exactly the evidence
`DATABASE_DIRECTION.md`'s walls wait for (relations, exclusion queries,
constraint pressure); collect it from day one, decide from data.

## 6. The write surface (added 2026-08-01, explicit opt-in)

`odag-mcp --write` enables four more tools — for a `swarm:NAME` store with
a configured signer (`bee_signer` / `$BEE_SIGNER`; refused otherwise, and
refused entirely for file stores, which remain `odag`'s own). The flow is
`PROVENANCE.md` §5, mechanized:

1. **`propose_put {item, supers}`** — changes nothing; returns the
   **canonical echo** (what would actually be stored), the claims to be
   asserted, `already_below` per super (the cheap "do you already have
   this?"), `missing_supers` to create first, and a **proposal token** —
   the deterministic hash of the canonicalized operation *against the
   current root*.
2. **`put {item, supers, proposal}`** — confirms. The server recomputes
   the token; if the store moved or the spelling changed since the
   proposal, the write is refused with a teaching error ("propose again").
   On success: the knowledge change commits, **one signed assertion record
   per claim** (basis = the root the author saw, shared `group` hash)
   lands in the provenance sibling store (`NAME-prov`), and the answer
   carries both new roots — the published pair.
3. **`propose_remove` / `remove`** — same shape, and the §3 **coupling
   rule is enforced**: a removal emits signed retraction records for the
   node's existence and each parent claim. The audit trail has no silent
   disappearances.

Idempotence is by design: re-confirming the same knowledge is a graph
no-op (the root does not move) while the re-assertion is deliberately a
*new* provenance record — audit information. Honest caveat: the two
commits (knowledge, then provenance) are not atomic across stores; a crash
between them loses only speech acts about a change that did land, and
re-asserting is always safe.

## 7. The review workflow (added the same day)

*Claims merge; acceptance is policy* (`SURFACE_LAYER.md` §11), as tools:

- **`review {sub, sup?, trust?}`** — available on any store with a
  provenance sibling, **read-only included**: the audit view of one claim.
  Every record about it (type, author, basis, time, group), each
  **signature-verified**; each author's *standing* computed from verified
  records only — a verified retraction is sticky per author (no trusted
  time exists, so set-based and fail-closed is the honest rule); and,
  given `trust` (a list of author addresses), the reader-side verdict:
  `accepted` iff some trusted author stands behind the claim. Forged
  records are listed (the audit hides nothing) but never count.
- **`endorse {sub, sup?}`** / **`retract {sub, sup?}`** (write mode) —
  signed speech acts about a claim, knowledge untouched: "I stand behind
  this" / "this key no longer does". Omitting `sup` means the existence
  claim.

This is the volume-safety mechanism `PROVENANCE.md` §5 required before
agent writes run at scale: what lands in the store is never what a reader
must accept — acceptance is each reader's own trust list, evaluated over
verified signatures.

## 8. Deliberately absent

- **Peer provenance adoption as a tool** (`ProvenanceStore.union` exists;
  wiring "fold these writers' stores" into the surface waits for a real
  multi-writer deployment).
- **Guarantee status** — factbond's namespace in `annotations`.
- **Query result certificates** and **cone-index serving** (see §2/§6
  notes above).
- ~~**Certificates**~~ — **landed the same day** for `is_below`
  (`ontodag.certificates`, recordstore ≥ 0.16.0; see §2). Still absent:
  `query` result certificates (cone-sized; re-execution stays the honest
  answer, per `CONTRACT.md` §7).
- **Guarantee status** — factbond's namespace in `annotations`, when that
  project has something to report.
- **Cone-index awareness** — a `LazyOntoDAG(cone_index=...)`-backed serving
  mode for published stores; pure plumbing when someone needs it.
