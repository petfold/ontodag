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
import time

from ontodag import CONTRACT_VERSION
from ontodag import surface as _surface
from ontodag.dimensions import KINDS, REGISTRY_VERSION
from ontodag.__main__ import (__version__, _make_backend, _read_config,
                              _resolve_store)


def _utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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
    def __init__(self, spec, backend=None, signer=None, writable=False,
                 verifier=None):
        backend = backend or _make_backend(spec)
        self._backend = backend
        self._verifier = verifier   # signature-check seam (tests inject)
        self._has_provenance = hasattr(backend, "provenance_record_store")
        self.described = backend.describe()
        dag = backend.load()
        if getattr(dag, "store", None) is None:
            # A file store: hydrate into an in-memory record store so answers
            # can cite a root — the same canonical fingerprint a published
            # store would have (CONTRACT.md G1 makes it comparable across
            # parties). History is not kept, so as_of serves only this root.
            from ontodag._extras import require
            _rs = require("recordstore", "store", "the agent surface",
                          hint="(odag-mcp cites a root with every answer, so even"
                               " a file store is hydrated into a record store to"
                               " get one)")
            MemoryBytesStore, RecordStore = _rs.MemoryBytesStore, _rs.RecordStore
            from ontodag.eager import EagerOntoDAG
            eager = EagerOntoDAG(RecordStore(MemoryBytesStore()))
            eager.merge(dag)
            eager.commit()
            dag = eager
        self.dag = dag
        self.root = dag.store.root
        self._snapshots = {}
        # The write surface (PROVENANCE.md §5): explicit opt-in, a
        # record-store-backed store with a provenance sibling, and a signer
        # — every write is a signed speech act beside a knowledge change.
        self.writable = bool(writable)
        self._signer = signer
        if self.writable:
            if not hasattr(backend, "provenance_record_store"):
                raise ValueError(
                    "the write surface needs a record-store-backed store "
                    "(swarm:NAME) with a provenance sibling; file stores "
                    "are odag's own — use `odag put` for local files")
            if self._signer is None:
                key = (os.environ.get("BEE_SIGNER")
                       or _read_config().get("bee_signer") or "")
                if not key:
                    raise ValueError(
                        "writes are signed speech acts — configure a "
                        "signer first: `odag set bee_signer <32-byte hex "
                        "key>` or $BEE_SIGNER")
                from ontodag.provenance import KeySigner
                self._signer = KeySigner(key)

    # -- helpers ----------------------------------------------------------- #

    def _require_writable(self):
        if not self.writable:
            raise ToolError(
                "this server is read-only; writes need `odag-mcp --write` "
                "(a swarm:NAME store plus a configured signer) — "
                "docs/AGENT_SURFACE.md")

    def _require_provenance(self):
        if not self._has_provenance:
            raise ToolError(
                "this store has no provenance sibling — review needs a "
                "record-store-backed store (swarm:NAME); file stores carry "
                "no attribution")

    def _provenance(self):
        # NOT cached: a local-first provenance store holds a writer lock,
        # and the MCP server is long-running — open a transient window per
        # use so odag can write provenance while the server is up. Callers
        # close via _close_provenance (or the context of one request).
        from ontodag.provenance import ProvenanceStore
        return ProvenanceStore(
            self._backend.provenance_record_store(),
            signer=self._signer)

    @staticmethod
    def _close_provenance(prov):
        close = getattr(getattr(prov, "_store", None), "close", None)
        if close is not None:
            close()

    def _verify(self, record):
        """True/False per the signature, or None when no verifier is
        available (the `bee` package absent and none injected)."""
        if self._verifier is not None:
            return bool(self._verifier(record))
        try:
            from ontodag.provenance import verify_record
            return bool(verify_record(record))
        except ImportError:
            return None

    def _subject_from(self, dag, arguments):
        """{sub, sup?} → a claim subject, canonicalized. No sup (or '*')
        means the existence claim."""
        from ontodag.provenance import below_subject, exists_subject
        sub = dag._canonical_name(self._need(arguments, "sub"))
        sup = arguments.get("sup")
        if sup in (None, "", "*"):
            return exists_subject(sub)
        if not isinstance(sup, str):
            raise ToolError("sup must be a string")
        return below_subject(sub, dag._canonical_name(sup))

    def _canonical_supers(self, dag, supers):
        if supers is None:
            return []
        if not isinstance(supers, list) or \
                not all(isinstance(s, str) and s for s in supers):
            raise ToolError("supers must be a list of strings")
        return [dag._canonical_name(s) for s in supers]

    @staticmethod
    def _claims_for_put(item_c, supers_c):
        from ontodag.provenance import below_subject, exists_subject
        if supers_c:
            return [below_subject(item_c, s) for s in supers_c]
        return [exists_subject(item_c)]

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
        from ontodag._extras import require
        RecordStore = require("recordstore", "store",
                              "as-of queries").RecordStore
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

    def _canonical_terms(self, dag, terms, allow_empty=False):
        if not isinstance(terms, list) or (not terms and not allow_empty) or \
                not all(isinstance(t, str) and t for t in terms):
            what = "a list of strings" if allow_empty \
                else "a non-empty list of strings"
            raise ToolError(f"terms must be {what}")
        return [dag._canonical_name(t) for t in terms]

    @staticmethod
    def _limit(arguments):
        """An agent's result cap: explicit, or absent. There is deliberately
        no default — a silently truncated answer is a wrong answer to a
        caller that reasons from it, so completeness is what you get unless
        you asked otherwise, and when you do ask, the answer says so."""
        limit = arguments.get("limit")
        if limit is None:
            return None
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ToolError("limit must be a non-negative integer "
                            "(omit it, or 0, for the complete answer)")
        return limit or None

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
            "capabilities": sorted(TOOL_HANDLERS)
            + (sorted(REVIEW_TOOL_HANDLERS) if self._has_provenance else [])
            + (sorted(WRITE_TOOL_HANDLERS) if self.writable else []),
            "author": self._signer.address if self._signer else None,
            "notes": ("writable: propose_put/put and propose_remove/remove "
                      "follow propose → canonical echo → confirm; every "
                      "write publishes a signed provenance record beside "
                      "the knowledge change; "
                      if self.writable else
                      "read-only (start with --write for the write "
                      "surface); ")
                     + "is_below supports certify: true (verifiable "
                       "certificates, checkable against the root alone)",
        })

    def tool_query(self, arguments):
        self._refuse_certify(arguments)
        dag, root = self._dag_at(arguments.get("as_of"))
        terms = arguments.get("terms")
        any_of = arguments.get("any_of")
        if terms is not None and any_of is not None:
            raise ToolError(
                "pass at most one of `terms` (a conjunction) or `any_of` "
                "(a list of conjunctions, answered as their union)")
        if any_of is None:
            # No terms at all — including neither argument — is the empty
            # query: an intersection of no constraints, so every item.
            terms = [] if terms is None else terms
            echo = self._canonical_terms(dag, terms, allow_empty=True)
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
        # `count` is always the size of the complete answer, `items` may be a
        # prefix of it — so a caller can always tell what it is holding.
        payload.update({"items": items, "count": len(items),
                        "truncated": False})
        limit = self._limit(arguments)
        if limit is not None and len(items) > limit:
            payload.update({"items": items[:limit], "truncated": True})
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

    # -- the write surface (PROVENANCE.md §5: propose → echo → confirm) ---- #

    def tool_propose_put(self, arguments):
        self._require_writable()
        from ontodag.provenance import operation_group
        item = self._need(arguments, "item")
        dag = self.dag
        item_c = dag._canonical_name(item)
        supers_c = self._canonical_supers(dag, arguments.get("supers"))
        basis = self.root
        claims = self._claims_for_put(item_c, supers_c)
        missing = sorted({
            s for s in supers_c
            if dag.nodes.get(s) is None and dag._parse_parametric(s) is None})
        payload = {
            "op": "put",
            "item": item_c,                       # the canonical echo:
            "supers": supers_c,                   # what would be STORED
            "claims": claims,
            "already_below": {s: bool(dag.is_below(item_c, s))
                              for s in supers_c},
            "missing_supers": missing,            # create these first
            "basis": basis,
            "proposal": operation_group("put", item_c, supers_c, basis),
            "next": "confirm by calling put with the same item/supers and "
                    "this proposal",
        }
        return self._envelope(self.root, payload)

    def tool_put(self, arguments):
        self._require_writable()
        from ontodag.provenance import operation_group
        item = self._need(arguments, "item")
        proposal = self._need(arguments, "proposal")
        dag = self.dag
        item_c = dag._canonical_name(item)
        supers_c = self._canonical_supers(dag, arguments.get("supers"))
        basis = self.root
        if proposal != operation_group("put", item_c, supers_c, basis):
            raise ToolError(
                f"proposal does not match this operation against the "
                f"current root {basis} — the store moved or the spelling "
                f"changed; call propose_put again and confirm what it "
                f"echoes")
        dag.put(item_c, supers_c)      # the core validates; errors teach
        new_root = dag.commit()
        prov = self._provenance()
        try:
            stamp = _utc_now()
            claims = self._claims_for_put(item_c, supers_c)
            for claim in claims:
                prov.assert_claim(claim, basis=basis, time=stamp,
                                  group=proposal)
            provenance_root = prov.commit()
        finally:
            self._close_provenance(prov)
        self.root = new_root
        return self._envelope(new_root, {
            "op": "put", "item": item_c, "supers": supers_c,
            "records": len(claims), "author": prov.author,
            "basis": basis, "provenance_root": provenance_root,
        })

    def tool_propose_remove(self, arguments):
        self._require_writable()
        from ontodag.provenance import (below_subject, exists_subject,
                                        operation_group)
        item = self._need(arguments, "item")
        dag = self.dag
        item_c = dag._canonical_name(item)
        node = dag.nodes.get(item_c)
        if node is None:
            raise ToolError(f"{item_c!r} is not in the store — nothing to "
                            f"remove (removals are proposed against what "
                            f"exists)")
        parents = sorted(p.name for p in node.parents
                         if p.name != dag.root.name
                         and dag.nodes.get(p.name) is p)
        claims = [below_subject(item_c, p) for p in parents]
        claims.append(exists_subject(item_c))
        basis = self.root
        payload = {
            "op": "remove",
            "item": item_c,
            "retracts": claims,        # the speech acts a confirm will emit
            "basis": basis,
            "proposal": operation_group("remove", item_c, [], basis),
            "next": "confirm by calling remove with the same item and this "
                    "proposal",
        }
        return self._envelope(self.root, payload)

    def tool_remove(self, arguments):
        self._require_writable()
        from ontodag.provenance import (below_subject, exists_subject,
                                        operation_group)
        item = self._need(arguments, "item")
        proposal = self._need(arguments, "proposal")
        dag = self.dag
        item_c = dag._canonical_name(item)
        basis = self.root
        if proposal != operation_group("remove", item_c, [], basis):
            raise ToolError(
                f"proposal does not match this removal against the current "
                f"root {basis} — the store moved; call propose_remove again")
        node = dag.nodes.get(item_c)
        if node is None:
            raise ToolError(f"{item_c!r} is not in the store")
        parents = sorted(p.name for p in node.parents
                         if p.name != dag.root.name
                         and dag.nodes.get(p.name) is p)
        dag.remove(item_c)
        new_root = dag.commit()
        # The coupling rule (PROVENANCE.md §3): on the agent surface a
        # knowledge-level remove MUST emit its retraction records — the
        # audit trail never has silent disappearances.
        prov = self._provenance()
        try:
            stamp = _utc_now()
            claims = [below_subject(item_c, p) for p in parents]
            claims.append(exists_subject(item_c))
            for claim in claims:
                prov.retract(claim, basis=basis, time=stamp, group=proposal)
            provenance_root = prov.commit()
        finally:
            self._close_provenance(prov)
        self.root = new_root
        return self._envelope(new_root, {
            "op": "remove", "item": item_c, "records": len(claims),
            "author": prov.author, "basis": basis,
            "provenance_root": provenance_root,
        })

    # -- the review workflow (claims merge, acceptance is policy) ---------- #

    def tool_review(self, arguments):
        self._require_provenance()
        dag = self.dag
        subject = self._subject_from(dag, arguments)
        trust = arguments.get("trust") or []
        if not isinstance(trust, list) or \
                not all(isinstance(a, str) for a in trust):
            raise ToolError("trust must be a list of author addresses")
        records, acts = [], {}
        verification = "available"
        prov = self._provenance()
        try:
            prov_records = list(prov.records(subject))
        finally:
            self._close_provenance(prov)
        for record in prov_records:
            verified = self._verify(record)
            if verified is None:
                verification = "unavailable"
            records.append({
                "type": record["type"], "author": record["author"],
                "basis": record.get("basis"), "time": record.get("time"),
                "group": record.get("group"), "verified": verified,
            })
            if verified:   # only verified speech acts count toward standing
                acts.setdefault(record["author"], set()).add(record["type"])
        # Per-author stance, set-based (no trusted time exists): a verified
        # retraction is sticky — conservative, fail-closed.
        standing = {author: ("retracted" if "retraction" in types
                             else "stands")
                    for author, types in sorted(acts.items())
                    if types & {"assertion", "endorsement", "retraction"}}
        payload = {"subject": subject, "records": records,
                   "standing": standing, "verification": verification}
        if trust:
            accepted_by = sorted(a for a in trust
                                 if standing.get(a) == "stands")
            payload["trust"] = trust
            payload["accepted"] = bool(accepted_by)
            payload["accepted_by"] = accepted_by
        return self._envelope(self.root, payload)

    def tool_endorse(self, arguments):
        self._require_writable()
        subject = self._subject_from(self.dag, arguments)
        prov = self._provenance()
        try:
            prov.endorse(subject, basis=self.root, time=_utc_now())
            provenance_root = prov.commit()
        finally:
            self._close_provenance(prov)
        return self._envelope(self.root, {
            "op": "endorse", "subject": subject, "author": prov.author,
            "provenance_root": provenance_root,
        })

    def tool_retract(self, arguments):
        self._require_writable()
        subject = self._subject_from(self.dag, arguments)
        prov = self._provenance()
        try:
            prov.retract(subject, basis=self.root, time=_utc_now())
            provenance_root = prov.commit()
        finally:
            self._close_provenance(prov)
        return self._envelope(self.root, {
            "op": "retract", "subject": subject, "author": prov.author,
            "provenance_root": provenance_root,
            "note": "a retraction is a speech act — the knowledge itself "
                    "is untouched (use propose_remove/remove for that)",
        })

    def tool_specs(self):
        specs = list(TOOL_SPECS)
        if self._has_provenance:
            specs += REVIEW_TOOL_SPECS
        if self.writable:
            specs += WRITE_TOOL_SPECS
        return specs

    def call(self, name, arguments):
        handler = TOOL_HANDLERS.get(name) \
            or REVIEW_TOOL_HANDLERS.get(name) \
            or WRITE_TOOL_HANDLERS.get(name)
        if handler is None:
            available = sorted(TOOL_HANDLERS) \
                + (sorted(REVIEW_TOOL_HANDLERS) if self._has_provenance
                   else []) \
                + (sorted(WRITE_TOOL_HANDLERS) if self.writable else [])
            raise ToolError(f"unknown tool {name!r} "
                            f"(available: {', '.join(available)})")
        return handler(self, arguments or {})


TOOL_HANDLERS = {
    "about": AgentSurface.tool_about,
    "query": AgentSurface.tool_query,
    "is_below": AgentSurface.tool_is_below,
    "overlapping": AgentSurface.tool_overlapping,
    "describe": AgentSurface.tool_describe,
    "canon": AgentSurface.tool_canon,
}

REVIEW_TOOL_HANDLERS = {
    "review": AgentSurface.tool_review,
}

WRITE_TOOL_HANDLERS = {
    "propose_put": AgentSurface.tool_propose_put,
    "put": AgentSurface.tool_put,
    "propose_remove": AgentSurface.tool_propose_remove,
    "remove": AgentSurface.tool_remove,
    "endorse": AgentSurface.tool_endorse,
    "retract": AgentSurface.tool_retract,
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
                    "fail closed to an empty result. With no terms at all "
                    "the query is unconstrained and returns every item. "
                    "Echoes the canonical terms it answered. `count` is "
                    "always the size of the complete answer; `items` is a "
                    "prefix of it when `truncated` is true.",
     "inputSchema": {"type": "object", "properties": {
         "terms": {"type": "array", "items": {"type": "string"},
                   "description": "conjunction of category terms "
                                  "(omit or empty for everything)"},
         "any_of": {"type": "array",
                    "items": {"type": "array",
                              "items": {"type": "string"}},
                    "description": "union of conjunctions (DNF)"},
         "limit": {"type": "integer", "minimum": 0,
                   "description": "at most this many items; the answer "
                                  "still reports the full count and sets "
                                  "truncated. Omit for the complete answer "
                                  "— there is no default cap."},
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

_SUPERS = {"type": "array", "items": {"type": "string"},
           "description": "the supercategories (empty/omitted = top level)"}

_CLAIM_ARGS = {
    "sub": {"type": "string", "description": "the claim's subject term"},
    "sup": {"type": "string",
            "description": "the claim's supercategory; omit (or '*') for "
                           "the existence claim"},
}

REVIEW_TOOL_SPECS = [
    {"name": "review",
     "description": "The audit view of one claim: every provenance record "
                    "about it (assertions, endorsements, retractions, per "
                    "author, signature-verified), each author's standing "
                    "(a verified retraction is sticky), and — given "
                    "`trust`, a list of author addresses — whether the "
                    "claim is ACCEPTED under your policy. Claims merge; "
                    "acceptance is yours.",
     "inputSchema": {"type": "object", "required": ["sub"],
                     "properties": {**_CLAIM_ARGS,
                                    "trust": {"type": "array",
                                              "items": {"type": "string"}}}}},
]

WRITE_TOOL_SPECS = [
    {"name": "propose_put",
     "description": "Step 1 of a write: see exactly what would be stored — "
                    "canonical item and supers, the claims to be asserted, "
                    "whether they already hold, any missing supers — plus "
                    "the proposal token to confirm with. Changes nothing.",
     "inputSchema": {"type": "object", "required": ["item"],
                     "properties": {"item": {"type": "string"},
                                    "supers": _SUPERS}}},
    {"name": "put",
     "description": "Step 2: confirm a proposed put. The proposal must "
                    "match the same operation against the current root "
                    "(if the store moved, propose again). Writes the "
                    "knowledge change AND signed assertion records to the "
                    "provenance store; answers with both new roots.",
     "inputSchema": {"type": "object", "required": ["item", "proposal"],
                     "properties": {"item": {"type": "string"},
                                    "supers": _SUPERS,
                                    "proposal": {"type": "string"}}}},
    {"name": "propose_remove",
     "description": "Step 1 of a removal: see what would be removed and "
                    "the retraction records a confirm will emit. Changes "
                    "nothing.",
     "inputSchema": {"type": "object", "required": ["item"],
                     "properties": {"item": {"type": "string"}}}},
    {"name": "remove",
     "description": "Step 2: confirm a proposed removal. Removes the item "
                    "AND emits signed retraction records (the audit trail "
                    "has no silent disappearances).",
     "inputSchema": {"type": "object", "required": ["item", "proposal"],
                     "properties": {"item": {"type": "string"},
                                    "proposal": {"type": "string"}}}},
    {"name": "endorse",
     "description": "Sign your endorsement of a claim (sub ⊑ sup, or the "
                    "existence claim without sup) — 'I stand behind this' "
                    "— into the provenance store. Touches no knowledge.",
     "inputSchema": {"type": "object", "required": ["sub"],
                     "properties": _CLAIM_ARGS}},
    {"name": "retract",
     "description": "Sign a retraction of a claim: 'this key no longer "
                    "stands behind it'. A speech act — the knowledge is "
                    "untouched (use propose_remove/remove for that); your "
                    "standing on the claim becomes 'retracted' in review.",
     "inputSchema": {"type": "object", "required": ["sub"],
                     "properties": _CLAIM_ARGS}},
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
            return self._result(msg_id,
                                {"tools": self.surface.tool_specs()})
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
    parser.add_argument("--write", action="store_true",
                        help="enable the write surface (needs a swarm:NAME "
                             "store and a configured bee_signer): "
                             "propose_put/put, propose_remove/remove — "
                             "every write pairs a signed provenance record "
                             "with the knowledge change")
    args = parser.parse_args(argv)
    try:
        surface = AgentSurface(_resolve_store(args.store),
                               writable=args.write)
    except (ValueError, OSError, ImportError) as exc:
        # ImportError included so a missing extra reads as one line of
        # instruction, like every other startup failure here, rather than a
        # traceback an agent operator has to parse.
        print(f"odag-mcp: {exc}", file=sys.stderr)
        return 1
    MCPServer(surface).serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
