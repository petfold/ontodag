"""The surface layer, output half: readable rendering of canonical names.

Design record: docs/SURFACE_LAYER.md (§4 the round-trip law, §6 rendering,
§7 who sees which layer). This module is the opt-in `ontodag.surface` of §7:
the core never imports it (`dag.py` prints nothing and stores only canonical
names); the CLI and any other human-facing surface may.

The one law, fuzz-tested in tests/test_surface.py:

    elaborate(render(t)) == t          for every canonical term t

and the deliberate NON-law: ``render(elaborate(s)) == s`` is not promised —
the user's spelling normalizes away and is never stored (§4).

Three rules keep the law cheap to uphold (§4's 2026-08-01 sharpenings):

* **Policy picks, vocabulary defines.** Every spelling this module emits is
  one the dimensions grammar already accepts (`ontodag.dimensions` is the
  shared vocabulary, pinned by REGISTRY_VERSION). Rendering only chooses
  among admissible spellings; it never invents one.
* **Injective per context.** A range collapses to a calendar period, or a
  value to a bigger unit, only when the denotation matches *exactly* —
  the almost-a-year range stays a timestamp range.
* **Pure function of the canonical name** (plus the merged declarations
  that give the name its kind). Never of what anyone originally typed.

Like the core, rendering is interpretation-context-relative: whether
`weight(1/2000kg)` may be shown as `weight(500g)` depends on `weight` being
a declared dimension in the graph at hand — an *opaque* name that merely
looks parametric is returned unchanged, or the law above would break on it.
Pass the DAG (any OntoDAG), or pass the kind directly when you already
know it.
"""

from calendar import monthrange

from ontodag import dimensions as _dims

# Version of the surface itself, separate from dimensions.REGISTRY_VERSION:
# a rendering change is harmless (canonical data never moves), but it should
# be visible where humans compare outputs. Purely informational (§9.5) —
# never stored, never merged; `odag canon` prints it.
SURFACE_VERSION = "0.1"


# --------------------------------------------------------------------------- #
# Friendly spellings per kind (each must re-elaborate to the same canonical)
# --------------------------------------------------------------------------- #

def _friendly_value(family, value):
    """Largest unit of the family in which `value` is a whole number.
    Integers only — elaboration accepts decimals and rationals from
    humans, rendering never produces them (fewer spellings, one
    deterministic choice). A value no unit fits exactly (the shaku's
    10/33 m) keeps its canonical rational spelling."""
    if family == "count":
        return _dims._fraction_text(value)
    anchor = _dims._ANCHOR[family]
    if value == 0:
        return "0" + anchor
    best = None                      # (factor, suffix)
    for unit, (fam, scale) in _dims._UNITS.items():
        if fam != family:
            continue
        quotient = value / scale
        if quotient.denominator == 1 and \
                (best is None or scale > best[0]):
            best = (scale, unit)
    if best is None:
        return _dims._render_scalar(family, value)
    return f"{int(value / best[0])}{best[1]}"


def _collapse_lo(ts, calendar):
    """The shortest literal whose start-of-period expansion is exactly `ts`.
    Year/month literals exist only in the calendar grammar; bare dates are
    admissible in the linear grammar too (range-end sugar)."""
    if calendar and ts.endswith("-01-01T00:00:00Z"):
        return ts[:4]
    if calendar and ts.endswith("-01T00:00:00Z"):
        return ts[:7]
    if ts.endswith("T00:00:00Z"):
        return ts[:10]
    return ts


def _collapse_hi(ts, calendar):
    """The shortest literal whose end-of-period expansion is exactly `ts`."""
    if calendar and ts.endswith("-12-31T23:59:59Z"):
        return ts[:4]
    if ts.endswith("T23:59:59Z"):
        date = ts[:10]
        if calendar:
            year, month, day = int(date[:4]), int(date[5:7]), int(date[8:10])
            if day == monthrange(year, month)[1]:
                return ts[:7]
        return date
    return ts


def _friendly_time(lo, hi, calendar):
    if lo is not None and lo == hi:
        return lo  # an instant: the timestamp is already the best spelling
    lo_text = _collapse_lo(lo, calendar) if lo is not None else ""
    hi_text = _collapse_hi(hi, calendar) if hi is not None else ""
    if lo_text and lo_text == hi_text:
        return lo_text  # one whole period: time(2026), time(2026-08), a day
    return f"{lo_text}..{hi_text}"


def _friendly_linear(denotation, kind):
    family, lo, hi = denotation
    if family == _dims._TIME:
        return _friendly_time(lo, hi, calendar=(kind == _dims.KIND_CALENDAR))
    if lo is not None and lo == hi:
        return _friendly_value(family, lo)
    if lo == 0 and hi is not None:  # numeric families: 0 is unbounded-below
        lo = None
    lo_text = _friendly_value(family, lo) if lo is not None else ""
    hi_text = _friendly_value(family, hi) if hi is not None else ""
    return f"{lo_text}..{hi_text}"


def _friendly_dominance(denotation):
    family, values = denotation
    if family == "count":
        return "x".join(_dims._fraction_text(v) for v in values)
    best = None
    if any(values):  # all-zero tuples keep the anchor spelling
        for unit, (fam, scale) in _dims._UNITS.items():
            if fam == family and \
                    all((v / scale).denominator == 1 for v in values) and \
                    (best is None or scale > best[0]):
                best = (scale, unit)
    if best is None:                 # no single unit fits all components:
        return "x".join(_dims._fraction_text(v) for v in values) \
            + _dims._ANCHOR[family]  # the canonical spelling
    return "x".join(str(int(v / best[0])) for v in values) + best[1]


def _friendly_param(param, kind):
    if kind == _dims.KIND_PREFIX:
        return param  # already the friendliest admissible spelling
    if kind == _dims.KIND_DOMINANCE:
        return _friendly_dominance(_dims._parse_dominance(param))
    return _friendly_linear(_dims._denotation(param, kind), kind)


# --------------------------------------------------------------------------- #
# The public pair
# --------------------------------------------------------------------------- #

def _resolve(name, dag, kind):
    """-> (head, kind, canonical) or None (not parametric in this context)."""
    if kind is not None:
        split = _dims.split_term(name)
        if split is None:
            return None
        return split[0], kind, _dims.canonicalize(name, kind)
    if dag is None:
        return None  # no context, no interpretation: identity
    return dag._parse_parametric(name)


def elaborate(name, dag=None, kind=None):
    """The canonical name of a surface term, under the given context (a DAG
    whose declarations resolve the head's kind, or an explicit kind). Names
    that are not parametric terms in that context are their own canonical
    form. Raises ValueError for a malformed parameter of a declared head —
    the same teaching error the core would raise at put/get time."""
    resolved = _resolve(name, dag, kind)
    return resolved[2] if resolved else name


def render(name, dag=None, kind=None):
    """The friendly spelling of a canonical name, under the same context.
    Total: anything unrenderable (opaque, undeclared, malformed, or no
    context at all) is returned unchanged — output must never fail."""
    try:
        resolved = _resolve(name, dag, kind)
    except ValueError:
        return name
    if resolved is None:
        return name
    head, resolved_kind, canonical = resolved
    param = _dims.split_term(canonical)[1]
    return f"{head}({_friendly_param(param, resolved_kind)})"
