"""is_below certificates: third-party-verifiable subsumption answers.

CONTRACT.md §7 Tier 2, built on recordstore ≥ 0.16.0's trie proofs. A
certificate makes ``is_below(sub, sup) at root R`` checkable by anyone
holding only the root — no store, no network, no trust in the prover.

The design is *re-execution over authenticated fragments*, which keeps the
subsumption semantics single-sourced instead of re-implemented in a
verifier that could drift:

* **Proving**: run the real ``is_below`` on a fresh ``LazyOntoDAG`` over a
  recording wrapper of the committed snapshot. Laziness means the walk
  touches exactly the records the answer *depends on* — the witness path
  upward for a positive answer, the (shallow) combined ancestor cone plus
  the dimension declarations and anchor stars for a negative one. Then
  attach a recordstore proof for every touched key: inclusion proofs for
  records read, **absence proofs for keys probed and missing** (the
  canonical trie makes those first-class, which is what makes the negative
  polarity certifiable at all).
* **Verifying**: check every proof against the root (pure hash-chain
  recomputation, ``recordstore.verify_proof``), assemble the verified
  records into a strict fragment store — present keys serve their proven
  records, proven-absent keys raise ``KeyError`` exactly like a real store,
  and any key the walk needs but the certificate does not cover fails the
  verification — then re-run the real ``is_below`` over it and compare
  with the claim. If the walk completes, its answer over the fragment
  equals its answer over the full store, because it consumed only
  authenticated data.

One subtlety decides the certificate's size: a walk's *access order* can
differ across processes (set iteration under hash randomization), so a
certificate covering only one recorded run might strand a verifier whose
walk explores a different-but-equally-valid path first. The prover
therefore also collects the **order-invariant dependency closure** — the
full combined upward closure of both terms, plus the head records, anchor
stars and kind chains any interpretation could consult — which is a
superset of every possible walk's needs. Both polarities consequently cost
the (shallow) ancestor cone rather than a minimal witness path: the price
of order-independent verifiability, bounded by exactly the argument that
made negative certificates cheap in the first place. If the closure logic
ever under-covers, verification fails loudly; it can never validate a
wrong answer.

The certificate pins ``REGISTRY_VERSION``: the combined order is computed
by the dimensions interpreter, so a verifier on a different registry
refuses rather than misinterprets (`CONTRACT.md` L2 — the same discipline
cone-index manifests follow). Envelope per the agreed certificate policy:
self-describing, JSON-ready, raw bytes inside the recordstore proofs,
format versioned by name.

Module-level imports stay core-only (B1 discipline, checked in
tests/test_boundaries.py); recordstore loads lazily inside the functions.
"""

import copy

from ontodag import dimensions as _dims
from ontodag.dag import _name_of
from ontodag.dimensions import REGISTRY_VERSION

CERTIFICATE_FORMAT = "ontodag-is-below-certificate"


class CertificateError(Exception):
    """The certificate does not verify against the given root."""


class _RecordingStore:
    """Wraps a record store, remembering every key the walk asks for —
    including the misses, which become absence proofs."""

    def __init__(self, inner):
        self._inner = inner
        self.accessed = set()

    def get(self, key):
        self.accessed.add(key)
        return self._inner.get(key)


class _VerifiedFragment:
    """A record store made of proof-verified records only. Proven-absent
    keys behave exactly like a real store's misses (KeyError → the walk
    fails closed); keys the certificate does not cover are a verification
    failure, never a silent wrong answer."""

    def __init__(self, present, absent):
        self._present = present
        self._absent = absent

    def get(self, key):
        if key in self._present:
            return copy.deepcopy(self._present[key])
        if key in self._absent:
            raise KeyError(key)
        raise CertificateError(
            f"certificate does not cover record {key!r}, which the walk "
            f"needs — incomplete or mismatched certificate")


def _walk(store, sub, sup):
    """The re-runnable question: the real is_below over a lazy reader."""
    from ontodag.lazy import LazyOntoDAG
    lazy = LazyOntoDAG(store)
    return bool(lazy.is_below(sub, sup)), lazy


def _cover(lazy, seeds):
    """Touch, through `lazy`, the order-invariant dependency closure of
    `seeds`: every combined-order ancestor (asserted parents plus present
    same-head containers), every head record and kind chain consulted for
    interpretation, and the probes for the seeds themselves. Everything a
    differently-ordered walk could ask for lands in the recorder."""
    pending = list(seeds)
    visited = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        try:
            parsed = lazy._parse_parametric(name)
        except ValueError:
            parsed = None      # malformed for its kind: the probe happened
        nxt = set()
        if parsed is not None:
            head, kind, canonical = parsed
            nxt.add(head)
            if canonical != name:
                nxt.add(canonical)
            name = canonical
            for value, vkind in lazy._star(head):
                if value.name != canonical and \
                        _dims.contains(value.name, canonical, vkind):
                    nxt.add(value.name)
        node = lazy.nodes.get(name)
        if node is not None:
            nxt.update(parent.name for parent in node.parents)
        pending.extend(n for n in nxt if n not in visited)


def prove_below(dag_or_store, sub, sup):
    """A verifiable certificate for ``is_below(sub, sup)`` against the
    committed root of `dag_or_store` (an Eager/Lazy/Sparse OntoDAG over a
    RecordStore, or the RecordStore itself). JSON-ready; check it with
    ``verify_below(cert, root)``. Self-verified before being returned."""
    from recordstore import RecordStore
    store = getattr(dag_or_store, "store", None) or dag_or_store
    root = store.root
    snapshot = RecordStore.at(root, store.blobs)
    sub, sup = _name_of(sub), _name_of(sup)
    recorder = _RecordingStore(snapshot)
    result, lazy = _walk(recorder, sub, sup)
    _cover(lazy, [sub, sup])
    certificate = {
        "format": CERTIFICATE_FORMAT,
        "version": 1,
        "root": root,
        "registry_version": REGISTRY_VERSION,
        "sub": sub,
        "sup": sup,
        "result": result,
        "proofs": [snapshot.prove(key)
                   for key in sorted(recorder.accessed)],
    }
    verify_below(certificate, root)   # never hand out a broken certificate
    return certificate


def verify_below(certificate, root):
    """Check `certificate` against `root` — the reference the *verifier*
    trusts — and return the proven boolean. Pure: no store access; every
    record the re-run consumes is authenticated by its carried proof.
    Raises ``CertificateError`` on any mismatch, including a registry
    version other than this interpreter's (refuse, never misinterpret)."""
    from recordstore import ABSENT, ProofError, verify_proof
    if not isinstance(certificate, dict) or \
            certificate.get("format") != CERTIFICATE_FORMAT:
        raise CertificateError(f"not a {CERTIFICATE_FORMAT} envelope")
    if certificate.get("version") != 1:
        raise CertificateError(
            f"unsupported certificate version "
            f"{certificate.get('version')!r}")
    if certificate.get("root") != root:
        raise CertificateError(
            f"certificate is about root {certificate.get('root')!r}, "
            f"not {root!r}")
    if certificate.get("registry_version") != REGISTRY_VERSION:
        raise CertificateError(
            f"certificate was produced under dimensions registry "
            f"v{certificate.get('registry_version')!r}; this verifier "
            f"runs v{REGISTRY_VERSION} — refusing rather than "
            f"misinterpreting the computed order")
    sub, sup = certificate.get("sub"), certificate.get("sup")
    if not isinstance(sub, str) or not isinstance(sup, str):
        raise CertificateError("certificate carries no sub/sup claim")

    present, absent = {}, set()
    proofs = certificate.get("proofs")
    if not isinstance(proofs, list):
        raise CertificateError("certificate carries no proofs")
    for proof in proofs:
        try:
            value = verify_proof(proof, root)
        except ProofError as exc:
            raise CertificateError(f"record proof failed: {exc}") from None
        if value is ABSENT:
            absent.add(proof["key"])
        else:
            present[proof["key"]] = value

    result, _ = _walk(_VerifiedFragment(present, absent), sub, sup)
    if result != bool(certificate.get("result")):
        raise CertificateError(
            "the certificate's claim contradicts its own records")
    return result
