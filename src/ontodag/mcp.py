"""odag-mcp — the read-only agent surface, spoken over MCP.

Design record: docs/AGENT_SURFACE.md (the tool inventory CONTRACT.md §2
scoped out) and SURFACE_LAYER.md §14. This is the contract's capability
list made tool-shaped: conjunctive/disjunctive query, fits-within, overlap
candidates, per-item description, canonical echo, and discoverability —
read-only by construction (writes are gated on the provenance
implementation, PROVENANCE.md).

Contract obligations implemented here:

* **Every answer cites its root** and carries the contract version and an
  extensible, namespaced ``annotations`` map (unknown namespaces are the
  reader's to ignore) — CONTRACT.md §2. A *file* store gets a root too: it
  is hydrated into an in-memory record store and committed, so even local
  stores answer with the semantic fingerprint (equal knowledge, equal
  root).
* **as-of** (§4): query tools take an optional ``as_of`` root and answer
  from that snapshot; non-monotone conclusions belong to a named root.
* **The discoverability record never lives inside the knowledge store**
  (§2): the ``about`` tool computes it on demand.
* **Canonical echo** (SURFACE_LAYER.md §14): tools echo the canonicalized
  terms they actually answered, and ``describe`` returns the rendered
  spelling as a sibling ``display`` field — never in place of the name.
* **Errors teach**: the core's ValueErrors (which name their own fix) pass
  through as tool errors verbatim.
* **The tripwire instrument**: every failed tool call is logged as a JSON
  line (stderr, plus ``$ONTODAG_MCP_LOG`` when set) — what agents try and
  cannot express is exactly the evidence DATABASE_DIRECTION.md's walls
  wait for.

The wire protocol is MCP's stdio transport: newline-delimited JSON-RPC 2.0
(initialize / tools/list / tools/call), deliberately implemented on the
stdlib alone — the repo's usual answer to an avoidable dependency. Module-
level imports stay core-only; recordstore loads lazily inside functions
(the same B1 discipline as the CLI's swarm path, checked in
tests/test_boundaries.py).
"""

import argparse
import json
import os
import sys

from ontodag import CONTRACT_VERSION
from ontodag import surface as _surface
from ontodag.dimensions import KINDS, REGISTRY_VERSION
from ontodag.__main__ import __version__, _make_backend, _resolve_store


class ToolError(ValueError):
    """A tool-level failure: reported to the agent, never a protocol error."""


def _log_failure(event):
    line = json.dumps(event, sort_keys=True)
    print(line, file=sys.stderr)
    path = os.environ.get("ONTODAG_MCP_LOG")
    if path:
        try:
            with open(path, "a") as fh:
                fh.write(line + "\n")
        except OSError:
            pass  # the log is telemetry, never load-bearing


# --------------------------------------------------------------------------- #
# The tool core (protocol-agnostic; the MCP framing wraps it)
# --------------------------------------------------------------------------- #

class AgentSurface:
    def __init__(self, spec):
        backend = _make_backend(spec)
        self.described = backend.describe()
        dag = backend.load()
        if getattr(dag, "store", None) is None:
            # A file store: hydrate into an in-memory record store so answers
            # can cite a root — the same canonical fingerprint a published
            # store would have (CONTRACT.md G1 makes it comparable across
            # parties). History is not kept, so as_of serves only this root.
            from recordstore import MemoryBytesStore, RecordStore
            from ontodag.eager import EagerOntoDAG
            eager = EagerOntoDAG(RecordStore(MemoryBytesStore()))
            eager.merge(dag)
            eager.commit()
            dag = eager
        self.dag = dag
        self.root = dag.store.root
        self._snapshots = {}

    # -- helpers ----------------------------------------------------------- #

    def _envelope(self, root, payload):
        answer = {"root": root, "contract": CONTRACT_VERSION}
        answer.update(payload)
        answer["annotations"] = {}
        return answer

    def _dag_at(self, as_of):
        """The DAG a query should run against, and the root it will cite."""
        if not as_of or as_of == self.root:
            return self.dag, self.root
        if as_of in self._snapshots:
            return self._snapshots[as_of], as_of
        from recordstore import RecordStore
        from ontodag.lazy import LazyOntoDAG
        try:
            snapshot = LazyOntoDAG(
                RecordStore.at(as_of, self.dag.store.blobs))
            # Touch one key so an unretrievable root fails here, with a
            # teaching message, instead of deep inside the first query.
            next(iter(snapshot.store.keys()), None)
        except Exception as exc:
            raise ToolError(
                f"root {as_of!r} is not retrievable from this store "
                f"(current root: {self.root}); a file-backed store keeps no "
                f"history — as_of works there only for the current root "
                f"({exc})")
        self._snapshots[as_of] = snapshot
        return snapshot, as_of

    def _refuse_certify(self, arguments):
        if arguments.get("certify"):
            raise ToolError(
                "query certificates are not available (result-soundness "
                "proofs are cone-sized; verify by re-execution at the "
                "cited root instead) — is_below DOES support "
                "certify: true, so check individual candidates with it")

    @staticmethod
    def _need(arguments, key):
        value = arguments.get(key)
        if not value or not isinstance(value, str):
            raise ToolError(f"missing required argument {key!r} (a string)")
        return value

    def _canonical_terms(self, dag, terms):
        if not isinstance(terms, list) or not terms or \
                not all(isinstance(t, str) and t for t in terms):
            raise ToolError("terms must be a non-empty list of strings")
        return [dag._canonical_name(t) for t in terms]

    # -- tools ------------------------------------------------------------- #

    def tool_about(self, arguments):
        dag = self.dag
        top = sorted(n.name for n in dag.root.neighbors)[:100]
        dimensions = {}
        for kind in sorted(KINDS):
            node = dag.nodes.get(kind)
            if node is None:
                continue
            for child in node.neighbors:
                if "(" not in child.name:
                    dimensions[child.name] = kind
        return self._envelope(self.root, {
            "store": self.described,
            "items": max(len(dag.nodes) - 1, 0),  # minus the root sentinel
            "top": top,
            "dimensions": dimensions,
            "registry_version": REGISTRY_VERSION,
            "surface_version": _surface.SURFACE_VERSION,
            "server": {"name": "odag-mcp", "version": __version__},
            "capabilities": sorted(TOOL_HANDLERS),
            "notes": "read-only; writes are gated on the provenance layer; "
                     "is_below supports certify: true (verifiable "
                     "certificates, checkable against the root alone)",
        })

    def tool_query(self, arguments):
        self._refuse_certify(arguments)
        dag, root = self._dag_at(arguments.get("as_of"))
        terms = arguments.get("terms")
        any_of = arguments.get("any_of")
        if (terms is None) == (any_of is None):
            raise ToolError(
                "pass exactly one of `terms` (a conjunction) or `any_of` "
                "(a list of conjunctions, answered as their union)")
        if terms is not None:
            echo = self._canonical_terms(dag, terms)
            result = dag.get(terms)
            payload = {"terms": echo}
        else:
            if not isinstance(any_of, list) or not any_of:
                raise ToolError("any_of must be a non-empty list of "
                                "term lists")
            echo = [self._canonical_terms(dag, q) for q in any_of]
            result = dag.get_any(any_of)
            payload = {"any_of": echo}
        items = sorted(item.name for item in result)
        payload.update({"items": items, "count": len(items)})
        return self._envelope(root, payload)

    def tool_is_below(self, arguments):
        dag, root = self._dag_at(arguments.get("as_of"))
        sub = self._need(arguments, "sub")
        sup = self._need(arguments, "sup")
        payload = {
            "sub": dag._canonical_name(sub),
            "sup": dag._canonical_name(sup),
            "result": bool(dag.is_below(sub, sup)),
        }
        if arguments.get("certify"):
            # The trustless upgrade (CONTRACT.md §7 Tier 2): recordstore
            # proofs of every record the answer depends on; anyone holding
            # the cited root checks it with
            # ontodag.certificates.verify_below(certificate, root).
            from ontodag.certificates import prove_below
            payload["certificate"] = prove_below(dag, sub, sup)
        return self._envelope(root, payload)

    def tool_overlapping(self, arguments):
        dag, root = self._dag_at(arguments.get("as_of"))
        term = self._need(arguments, "term")
        candidates = sorted(i.name for i in dag.get_overlapping(term))
        return self._envelope(root, {
            "term": dag._canonical_name(term),
            "candidates": candidates,
            "count": len(candidates),
            "note": "recall-complete candidates: anything that could "
                    "satisfy the term is here, and membership asserts only "
                    "possible coexistence — check candidates with is_below "
                    "or your own exact test (CONTRACT.md G6)",
        })

    def tool_describe(self, arguments):
        dag, root = self._dag_at(arguments.get("as_of"))
        term = self._need(arguments, "term")
        canonical = dag._canonical_name(term)
        node = dag.nodes.get(canonical)
        payload = {
            "name": canonical,
            "display": _surface.render(canonical, dag),
            "exists": node is not None,
        }
        if node is not None:
            payload["parents"] = sorted(
                p.name for p in node.parents
                if p.name != dag.root.name and dag.nodes.get(p.name) is p)
            payload["children"] = sorted(c.name for c in node.neighbors)
            payload["descendant_count"] = node.descendant_count
        return self._envelope(root, payload)

    def tool_canon(self, arguments):
        term = self._need(arguments, "term")
        return self._envelope(self.root, {
            "term": term,
            "canonical": _surface.elaborate(term, self.dag),
            "display": _surface.render(term, self.dag),
            "surface_version": _surface.SURFACE_VERSION,
            "registry_version": REGISTRY_VERSION,
        })

    def call(self, name, arguments):
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            raise ToolError(f"unknown tool {name!r} "
                            f"(available: {', '.join(sorted(TOOL_HANDLERS))})")
        return handler(self, arguments or {})


TOOL_HANDLERS = {
    "about": AgentSurface.tool_about,
    "query": AgentSurface.tool_query,
    "is_below": AgentSurface.tool_is_below,
    "overlapping": AgentSurface.tool_overlapping,
    "describe": AgentSurface.tool_describe,
    "canon": AgentSurface.tool_canon,
}

_AS_OF = {"type": "string",
          "description": "answer from this root (a snapshot) instead of "
                         "the current one; answers cite the root they used"}
_CERTIFY = {"type": "boolean",
            "description": "reserved for query (not available: verify by "
                           "re-execution at the cited root, or certify "
                           "individual candidates via is_below)"}

TOOL_SPECS = [
    {"name": "about",
     "description": "What this store is about, without downloading it: "
                    "root, size, top-level categories, declared dimensions, "
                    "versions. Read this first.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "query",
     "description": "Items below ALL given terms (`terms`), or below any of "
                    "several conjunctions (`any_of`). Terms may be virtual "
                    "parametric values like weight(..5kg). Unknown names "
                    "fail closed to an empty result. Echoes the canonical "
                    "terms it answered.",
     "inputSchema": {"type": "object", "properties": {
         "terms": {"type": "array", "items": {"type": "string"},
                   "description": "conjunction of category terms"},
         "any_of": {"type": "array",
                    "items": {"type": "array",
                              "items": {"type": "string"}},
                    "description": "union of conjunctions (DNF)"},
         "as_of": _AS_OF, "certify": _CERTIFY}}},
    {"name": "is_below",
     "description": "Does SUB fit within SUP? Fail-closed: true only with "
                    "a witness in the graph or exact dimension arithmetic; "
                    "false means not derivable. The one bounded question "
                    "you can check instead of asserting — and with "
                    "certify: true, one anyone can verify holding only "
                    "the root.",
     "inputSchema": {"type": "object",
                     "required": ["sub", "sup"],
                     "properties": {
                         "sub": {"type": "string"},
                         "sup": {"type": "string"},
                         "as_of": _AS_OF,
                         "certify": {
                             "type": "boolean",
                             "description":
                                 "attach a verifiable certificate: "
                                 "recordstore proofs of every record the "
                                 "answer depends on; check it with "
                                 "ontodag.certificates.verify_below("
                                 "certificate, root) — no store access "
                                 "needed"}}}},
    {"name": "overlapping",
     "description": "Recall-complete CANDIDATES that possibly satisfy a "
                    "parametric term (denotations overlap). Membership does "
                    "not assert satisfaction — verify candidates yourself.",
     "inputSchema": {"type": "object", "required": ["term"],
                     "properties": {"term": {"type": "string"},
                                    "as_of": _AS_OF}}},
    {"name": "describe",
     "description": "One item: canonical name, friendly display spelling, "
                    "parents, children, descendant count.",
     "inputSchema": {"type": "object", "required": ["term"],
                     "properties": {"term": {"type": "string"},
                                    "as_of": _AS_OF}}},
    {"name": "canon",
     "description": "The canonical (stored) form of any spelling — what a "
                    "put of this term would actually store. Use it to echo "
                    "before writing and to avoid re-asserting variants.",
     "inputSchema": {"type": "object", "required": ["term"],
                     "properties": {"term": {"type": "string"}}}},
]


# --------------------------------------------------------------------------- #
# MCP framing: newline-delimited JSON-RPC 2.0 over stdio
# --------------------------------------------------------------------------- #

class MCPServer:
    PROTOCOL_VERSION = "2025-03-26"

    def __init__(self, surface):
        self.surface = surface

    def handle(self, message):
        """One JSON-RPC message in, one response dict out (None for
        notifications)."""
        method = message.get("method")
        msg_id = message.get("id")
        if msg_id is None:  # a notification: never answered
            return None
        if method == "initialize":
            params = message.get("params") or {}
            return self._result(msg_id, {
                "protocolVersion": params.get("protocolVersion")
                or self.PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "odag-mcp", "version": __version__},
            })
        if method == "ping":
            return self._result(msg_id, {})
        if method == "tools/list":
            return self._result(msg_id, {"tools": TOOL_SPECS})
        if method == "tools/call":
            params = message.get("params") or {}
            name = params.get("name")
            arguments = params.get("arguments") or {}
            try:
                answer = self.surface.call(name, arguments)
            except (ToolError, ValueError, OSError) as exc:
                _log_failure({"event": "tool_error", "tool": name,
                              "arguments": arguments, "error": str(exc)})
                return self._result(msg_id, {
                    "content": [{"type": "text", "text": f"{exc}"}],
                    "isError": True,
                })
            return self._result(msg_id, {
                "content": [{"type": "text",
                             "text": json.dumps(answer, sort_keys=True)}],
                "structuredContent": answer,
                "isError": False,
            })
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601,
                          "message": f"method not found: {method}"}}

    @staticmethod
    def _result(msg_id, result):
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def serve(self, stdin=None, stdout=None):
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                response = {"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32700,
                                      "message": "parse error"}}
            else:
                response = self.handle(message)
            if response is not None:
                stdout.write(json.dumps(response, sort_keys=True) + "\n")
                stdout.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="odag-mcp",
        description="Read-only MCP server over an OntoDAG store "
                    "(stdio transport; shares odag's store settings).")
    parser.add_argument("-f", "--store", "--file", dest="store",
                        help="store path or swarm:NAME "
                             "(default: odag's configured store)")
    args = parser.parse_args(argv)
    try:
        surface = AgentSurface(_resolve_store(args.store))
    except (ValueError, OSError) as exc:
        print(f"odag-mcp: {exc}", file=sys.stderr)
        return 1
    MCPServer(surface).serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
