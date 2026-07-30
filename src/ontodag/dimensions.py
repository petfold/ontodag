"""Parametric items ("dimension lattices"): grammar, registry, canonicalizer,
and the containment/intersection arithmetic. Design record: docs/DIMENSIONS.md.

Pure stdlib and graph-free (B1): callers resolve a head's *kind* from the DAG
(an ancestor walk to a registry kind node) and pass it into every function
here. Only exact, platform-independent arithmetic is permitted in this module
— integers in per-family base units, strings, and fixed-format ISO-8601 UTC
timestamps compared lexicographically — because the computed order
participates in transitive reduction and therefore in canonical roots
(determinism doctrine, DIMENSIONS.md §3). No floats, ever.

A parametric term denotes a *set of values*; the computed order between two
same-head terms is containment of denotations (`contains`), i.e. the same
extension-inclusion order the DAG's asserted edges have always meant.
"""

import re
from datetime import datetime
from fractions import Fraction

# Bump when the kind set, unit table, or comparison semantics change: the
# computed order participates in canonical reduction, so two writers must
# agree on this version to reproduce each other's roots (DIMENSIONS.md §10).
REGISTRY_VERSION = 1

# Reserved node names the registry recognizes, the way the codebase already
# recognizes "*". A dimension head is declared by asserting it under exactly
# one kind node (directly or via ancestors): weight -> linear-dimension.
DIMENSION_ROOT = "dimension"
KIND_LINEAR = "linear-dimension"
KIND_PREFIX = "prefix-dimension"
KIND_DOMINANCE = "dominance-dimension"
KINDS = frozenset({KIND_LINEAR, KIND_PREFIX, KIND_DOMINANCE})

# suffix -> (family, exact scale factor to the family's base unit).
# Base units are deliberately tiny so every value is an integer (the
# bank/crypto move, agreed 2026-07-30); rendering friendly units is UI work.
_UNITS = {
    "mg": ("mass", 1), "g": ("mass", 10**3),
    "kg": ("mass", 10**6), "t": ("mass", 10**9),
    "mm": ("length", 1), "cm": ("length", 10),
    "m": ("length", 10**3), "km": ("length", 10**6),
    "s": ("duration", 1), "min": ("duration", 60),
    "h": ("duration", 3600), "d": ("duration", 86400),
    "": ("count", 1),
}
_BASE_UNIT = {"mass": "mg", "length": "mm", "duration": "s", "count": ""}
_TIME = "time"  # the one non-integer linear value space (ISO-8601 UTC)

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NUM_RE = re.compile(r"^(\d+(?:\.\d+)?)([a-z]*)$")
_PREFIX_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._\-]*$")


def split_term(name):
    """Purely syntactic split of `head(param)` -> (head, param), else None.

    Whether the name is actually parametric is the caller's decision (the
    parse trigger: the head must resolve to a declared dimension). Names that
    merely look term-shaped stay opaque atoms — full backward compatibility.
    """
    if not isinstance(name, str) or not name.endswith(")"):
        return None
    idx = name.find("(")
    if idx <= 0:
        return None
    head, param = name[:idx], name[idx + 1:-1]
    # v1 kinds are flat: no nested terms, no empty parameter.
    if not param or "(" in param or ")" in param:
        return None
    return head, param


# ---- value parsing (exact; every error is a ValueError with the offender) --

def _parse_timestamp(text):
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ValueError(f"invalid UTC timestamp {text!r} "
                         "(expected YYYY-MM-DDTHH:MM:SSZ)")
    return text


def _parse_scalar(text):
    """One linear value -> (family, value). Integers land in base units
    exactly or raise; timestamps stay strings (lexicographic = chronological).
    """
    if _TS_RE.match(text):
        return _TIME, _parse_timestamp(text)
    match = _NUM_RE.match(text)
    if not match:
        raise ValueError(f"invalid value {text!r}")
    number, unit = match.groups()
    if unit not in _UNITS:
        raise ValueError(f"unknown unit {unit!r} in {text!r}")
    family, factor = _UNITS[unit]
    scaled = Fraction(number) * factor
    if scaled.denominator != 1:
        raise ValueError(
            f"{text!r} is finer than the base unit "
            f"({_BASE_UNIT[family] or 'integer'}) — no silent rounding")
    return family, int(scaled)


def _parse_end(text, side):
    """A range end: bare dates expand deterministically (start -> first
    second, end -> last second of the day) — boundary sugar, DIMENSIONS.md §4.
    """
    if _DATE_RE.match(text):
        try:
            datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"invalid date {text!r}")
        suffix = "T00:00:00Z" if side == "lo" else "T23:59:59Z"
        return _TIME, text + suffix
    return _parse_scalar(text)


def _parse_linear(param):
    """-> (family, lo, hi); closed interval; None = unbounded. Integer
    families have no negative values (the grammar admits none), so an
    unbounded lower end IS 0 and is normalized to it — `number(..0)` and
    `number(0)` must be one canonical name (one denotation, one identity).
    Only the time family is genuinely unbounded below."""
    if ".." in param:
        parts = param.split("..")
        if len(parts) != 2:
            raise ValueError(f"malformed range {param!r}")
        lo_text, hi_text = parts
        if not lo_text and not hi_text:
            raise ValueError(f"range {param!r} needs at least one end")
        lo = _parse_end(lo_text, "lo") if lo_text else None
        hi = _parse_end(hi_text, "hi") if hi_text else None
        if lo and hi:
            if lo[0] != hi[0]:
                raise ValueError(
                    f"range ends of {param!r} mix families {lo[0]}/{hi[0]}")
            if lo[1] > hi[1]:
                raise ValueError(f"empty range {param!r} (lo > hi)")
        family = (lo or hi)[0]
        lo_value = lo[1] if lo else (None if family == _TIME else 0)
        return family, lo_value, hi[1] if hi else None
    if _DATE_RE.match(param):  # bare date = the whole day, as an interval
        lo = _parse_end(param, "lo")
        hi = _parse_end(param, "hi")
        return _TIME, lo[1], hi[1]
    family, value = _parse_scalar(param)
    return family, value, value  # a point is a degenerate interval


def _parse_dominance(param):
    """-> (family, tuple sorted descending). Units propagate right-to-left
    (`390x230x190mm`: the trailing unit covers unitless components); no unit
    anywhere means the dimensionless count family."""
    parts = param.split("x")
    if len(parts) < 2:
        raise ValueError(f"dominance tuple {param!r} needs at least "
                         "two components")
    values, families = [None] * len(parts), [None] * len(parts)
    carried_unit = ""
    for i in range(len(parts) - 1, -1, -1):
        match = _NUM_RE.match(parts[i])
        if not match:
            raise ValueError(f"invalid component {parts[i]!r} in {param!r}")
        number, unit = match.groups()
        if unit:
            carried_unit = unit
        families[i], values[i] = _parse_scalar(number + carried_unit)
    if len(set(families)) != 1:
        raise ValueError(f"components of {param!r} mix unit families")
    return families[0], tuple(sorted(values, reverse=True))


def _parse_prefix(param):
    if ".." in param or not _PREFIX_RE.match(param):
        raise ValueError(f"invalid prefix value {param!r}")
    return param


# ---- rendering (the canonical form; names are the identity) ----------------

def _render_scalar(family, value):
    return value if family == _TIME else f"{value}{_BASE_UNIT[family]}"


def _render_linear(family, lo, hi):
    if lo is not None and lo == hi:
        return _render_scalar(family, lo)
    # Integer families: lo == 0 means unbounded-below and renders as the
    # `..hi` form — except when hi is also unbounded, where `0..` keeps the
    # rendering parseable (a bare `..` is invalid).
    if family != _TIME and lo == 0 and hi is not None:
        lo = None
    lo_text = _render_scalar(family, lo) if lo is not None else ""
    hi_text = _render_scalar(family, hi) if hi is not None else ""
    return f"{lo_text}..{hi_text}"


def _denotation(param, kind):
    if kind == KIND_LINEAR:
        return _parse_linear(param)
    if kind == KIND_DOMINANCE:
        return _parse_dominance(param)
    if kind == KIND_PREFIX:
        return _parse_prefix(param)
    raise ValueError(f"unknown dimension kind {kind!r}")


def _render(denotation, kind):
    if kind == KIND_LINEAR:
        return _render_linear(*denotation)
    if kind == KIND_DOMINANCE:
        family, values = denotation
        suffix = "" if family == "count" else _BASE_UNIT[family]
        return "x".join(str(v) for v in values) + suffix
    return denotation  # prefix: the validated string is canonical


def canonicalize(name, kind):
    """The canonical name of a parametric term (identity string). Raises
    ValueError when the parameter is malformed for the head's kind."""
    split = split_term(name)
    if split is None:
        raise ValueError(f"{name!r} is not a parametric term")
    head, param = split
    return f"{head}({_render(_denotation(param, kind), kind)})"


def space_of(name, kind):
    """Value-space tag for put-time consistency checks: every value of one
    head must share it (one family, one arity)."""
    denotation = _denotation(split_term(name)[1], kind)
    if kind == KIND_LINEAR:
        return f"linear:{denotation[0]}"
    if kind == KIND_DOMINANCE:
        return f"dominance:{denotation[0]}:{len(denotation[1])}"
    return "prefix"


def _same_head(a, b):
    head_a, param_a = split_term(a)
    head_b, param_b = split_term(b)
    if head_a != head_b:
        raise ValueError(f"cannot compare across heads: {a!r} vs {b!r}")
    return head_a, param_a, param_b


def contains(outer, inner, kind):
    """denotation(inner) ⊆ denotation(outer)? Both must share the head.
    Reflexive; distinct canonical names are therefore strictly ordered or
    incomparable, never mutually contained (that is what keeps the combined
    relation a partial order — DIMENSIONS.md §11, I1)."""
    _, param_outer, param_inner = _same_head(outer, inner)
    if kind == KIND_LINEAR:
        fam_o, lo_o, hi_o = _parse_linear(param_outer)
        fam_i, lo_i, hi_i = _parse_linear(param_inner)
        if fam_o != fam_i:
            raise ValueError(
                f"unit families differ: {outer!r} ({fam_o}) vs "
                f"{inner!r} ({fam_i})")
        lo_ok = lo_o is None or (lo_i is not None and lo_i >= lo_o)
        hi_ok = hi_o is None or (hi_i is not None and hi_i <= hi_o)
        return lo_ok and hi_ok
    if kind == KIND_DOMINANCE:
        fam_o, values_o = _parse_dominance(param_outer)
        fam_i, values_i = _parse_dominance(param_inner)
        if fam_o != fam_i or len(values_o) != len(values_i):
            raise ValueError(
                f"incompatible dominance spaces: {outer!r} vs {inner!r}")
        return all(o >= i for o, i in zip(values_o, values_i))
    if kind == KIND_PREFIX:
        return _parse_prefix(param_inner).startswith(
            _parse_prefix(param_outer))
    raise ValueError(f"unknown dimension kind {kind!r}")


def intersect(a, b, kind):
    """Canonical name of denotation(a) ∩ denotation(b), or None when the
    intersection is provably empty. Within a dimension meets are exact —
    the planner pre-intersects same-head query terms with this, and the
    disjoint-parents guard raises on None (DIMENSIONS.md §8, §9)."""
    head, param_a, param_b = _same_head(a, b)
    if kind == KIND_LINEAR:
        fam_a, lo_a, hi_a = _parse_linear(param_a)
        fam_b, lo_b, hi_b = _parse_linear(param_b)
        if fam_a != fam_b:
            raise ValueError(
                f"unit families differ: {a!r} ({fam_a}) vs {b!r} ({fam_b})")
        lo = lo_a if lo_b is None else lo_b if lo_a is None else max(lo_a, lo_b)
        hi = hi_a if hi_b is None else hi_b if hi_a is None else min(hi_a, hi_b)
        if lo is not None and hi is not None and lo > hi:
            return None
        return f"{head}({_render_linear(fam_a, lo, hi)})"
    if kind == KIND_DOMINANCE:
        fam_a, values_a = _parse_dominance(param_a)
        fam_b, values_b = _parse_dominance(param_b)
        if fam_a != fam_b or len(values_a) != len(values_b):
            raise ValueError(
                f"incompatible dominance spaces: {a!r} vs {b!r}")
        meet = tuple(min(x, y) for x, y in zip(values_a, values_b))
        return f"{head}({_render((fam_a, meet), kind)})"
    if kind == KIND_PREFIX:
        value_a = _parse_prefix(param_a)
        value_b = _parse_prefix(param_b)
        if value_a.startswith(value_b):
            return f"{head}({value_a})"
        if value_b.startswith(value_a):
            return f"{head}({value_b})"
        return None
    raise ValueError(f"unknown dimension kind {kind!r}")
