# The documentation map

Each document has one job (the Diátaxis split: tutorial / how-to /
reference / explanation, plus design records and plans). If you're about
to add a section somewhere, check it isn't another document's job.

## Using OntoDAG

| document | job |
|---|---|
| [USER_GUIDE.md](USER_GUIDE.md) | **Tutorial + how-to.** Narrative, executed snippets. Start here. |
| [REFERENCE.md](REFERENCE.md) | **Reference.** Every command, setting, kind, endpoint, tool — compact, definition-first. Tables pinned to the code by `tests/test_reference.py`. |
| [HOW_IT_WORKS.md](HOW_IT_WORKS.md) | **Explanation.** The ideas — canonical form, cones, merge — and why. |
| [UNIT_TABLE.md](UNIT_TABLE.md) | **Generated reference.** Every unit spelling, built-in and per pack. |

## Design records (describe what is built and agreed)

| document | job |
|---|---|
| [CONTRACT.md](CONTRACT.md) | Normative guarantees G1–G6, as-of semantics, what a higher layer may assume. Agreed at 0.1; amendments are deliberate. |
| [PROVENANCE.md](PROVENANCE.md) | Attribution: signed claim-grain records in a parallel store. Agreed. |
| [AGENT_SURFACE.md](AGENT_SURFACE.md) | The MCP surface: tools, envelope, write gating, review. |
| [DIMENSIONS.md](DIMENSIONS.md) | Parametric values: computed order, kinds, anchors. |
| [UNITS.md](UNITS.md) | The unit registry: rational anchoring, families, packs, registry versioning. |
| [SWARM_DESIGN.md](SWARM_DESIGN.md) | Persistence architecture: recordstore, the node schema, multi-writer merge. |
| [recordstore-interface.md](recordstore-interface.md) | Consumer-side view of the `recordstore` dependency (what OntoDAG uses, with floor notes). The full, current API is upstream's test-pinned [recordstore REFERENCE.md](https://github.com/petfold/recordstore/blob/main/docs/REFERENCE.md) (likewise [swarmfs's](https://github.com/petfold/swarmfs/blob/main/docs/REFERENCE.md)). |

## [plans/](plans/) — future features and directions

Discussion drafts and direction papers. **Nothing in `plans/` is
shipped**; treat clauses there as proposed until a design record or the
code says otherwise. Currently: BINDING (roles, bundles, multiplicity),
EVOLUTION (how an ontology changes; the top ontology), PACKS (published
ontologies and trust), SURFACE_LAYER (the human layer), WEB_UI (a simpler
web interface: browsing, a console, and a demo site — stages 1-4 built on
the `web-ui` branch), ROADMAP,
DATABASE_DIRECTION (what OntoDAG refuses to become, with tripwires),
BROWSER (Pyodide), SEMANTIC_CODES, MERKLE_NOTES,
PHILOSOPHICAL_LANGUAGES, SWARM_DESIGN_update (POT/beeson proposal).
