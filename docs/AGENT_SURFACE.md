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
- **`certify` is reserved, and says so**: requesting it returns a teaching
  error naming what to do meanwhile (verify by re-execution at the cited
  root) and what will provide it (recordstore `prove`/`verify`,
  `CONTRACT.md` §7 Tier 2). The parameter exists now so shapes don't churn
  when certificates land.

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

## 6. Deliberately absent from v1

- **Writes** — gated on the provenance layer (`PROVENANCE.md`): the write
  path is propose → canonical echo → confirm, with signed assertion records
  beside every knowledge change and remove coupled to retraction. None of
  that exists yet, so neither does a write tool.
- **Certificates** — arrive with recordstore `prove`/`verify`, then
  `is_below` certificate envelopes (`CONTRACT.md` §7 Tier 2 policy: raw
  blobs, hash-chain verification, format-name versioning, opt-in).
- **Guarantee status** — factbond's namespace in `annotations`, when that
  project has something to report.
- **Cone-index awareness** — a `LazyOntoDAG(cone_index=...)`-backed serving
  mode for published stores; pure plumbing when someone needs it.
