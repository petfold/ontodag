"""The surface layer: readable rendering of canonical names, and the
relative times a person or an agent types (question 31).

Design record: docs/plans/SURFACE_LAYER.md (§4 the round-trip law, §6 rendering,
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
`mass(1/2kg)` may be shown as `mass(500g)` depends on `mass` being
a declared dimension in the graph at hand — an *opaque* name that merely
looks parametric is returned unchanged, or the law above would break on it.
Pass the DAG (any OntoDAG), or pass the kind directly when you already
know it.
"""

import re
from calendar import monthrange
from datetime import datetime, timezone

from ontodag import dimensions as _dims

# Version of the surface itself, separate from dimensions.REGISTRY_VERSION:
# a rendering change is harmless (canonical data never moves), but it should
# be visible where humans compare outputs. Purely informational (§9.5) —
# never stored, never merged; `odag canon` prints it.
SURFACE_VERSION = "0.2"


# --------------------------------------------------------------------------- #
# Friendly spellings per kind (each must re-elaborate to the same canonical)
# --------------------------------------------------------------------------- #

def _friendly_value(family, value, units=None):
    """Largest unit of the family in which `value` is a whole number.
    Integers only — elaboration accepts decimals and rationals from
    humans, rendering never produces them (fewer spellings, one
    deterministic choice). A value no unit fits exactly (the shaku's
    10/33 m) keeps its canonical rational spelling."""
    if family == "count":
        return _dims._fraction_text(value)
    anchor = _dims._ANCHOR.get(family, family)
    if value == 0:
        return "0" + anchor
    best = None                      # (factor, suffix)
    candidates = dict(_dims._UNITS)
    if units:
        candidates.update(units)     # graph-declared vocabulary renders too
    for unit, (fam, scale) in candidates.items():
        if fam != family:
            continue
        quotient = value / scale
        if quotient.denominator == 1 and \
                (best is None or scale > best[0]):
            best = (scale, unit, _dims.Fraction(0))
    # Affine spellings (C/F) compete in the same largest-factor contest —
    # 24C must beat 297150mK — losing plain-unit ties (300K stays 300K;
    # a whole-kelvin point is never also whole in C or F, so ties don't
    # actually arise for temperature). Sign is allowed: -18C.
    for unit in _dims._RENDER_AFFINE:
        fam, factor, offset = _dims._AFFINE[unit]
        if fam != family:
            continue
        quotient = (value - offset) / factor
        if quotient.denominator == 1 and \
                (best is None or factor > best[0]):
            best = (factor, unit, offset)
    if best is None:
        return _dims._render_scalar(family, value)
    return f"{int((value - best[2]) / best[0])}{best[1]}"


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


def _friendly_linear(denotation, kind, units=None):
    family, lo, hi = denotation
    if family == _dims._TIME:
        return _friendly_time(lo, hi, calendar=(kind == _dims.KIND_CALENDAR))
    if lo is not None and lo == hi:
        return _friendly_value(family, lo, units)
    if lo == 0 and hi is not None:  # numeric families: 0 is unbounded-below
        lo = None
    lo_text = _friendly_value(family, lo, units) if lo is not None else ""
    hi_text = _friendly_value(family, hi, units) if hi is not None else ""
    return f"{lo_text}..{hi_text}"


def _friendly_dominance(denotation, units=None):
    family, values = denotation
    if family == "count":
        return "x".join(_dims._fraction_text(v) for v in values)
    best = None
    candidates = dict(_dims._UNITS)
    if units:
        candidates.update(units)
    if any(values):  # all-zero tuples keep the anchor spelling
        for unit, (fam, scale) in candidates.items():
            if fam == family and \
                    all((v / scale).denominator == 1 for v in values) and \
                    (best is None or scale > best[0]):
                best = (scale, unit)
    if best is None:                 # no single unit fits all components:
        return "x".join(_dims._fraction_text(v) for v in values) \
            + _dims._ANCHOR.get(family, family)  # the canonical spelling
    return "x".join(str(int(v / best[0])) for v in values) + best[1]


def _friendly_rect(param):
    """A rectangle with an axis whose extent is exactly a written precision
    shows that axis as the position: `48.85835..48.85845` reads `48.8584`,
    which elaborates back to it."""
    split = _dims.split_term(param)
    if split is not None:
        return f"{split[0]}({_friendly_rect(split[1])})"
    south, north, west, width = _dims._parse_rect(param)
    lat, lon = param.split(",")

    def position(centre, extent):
        if not 0 < extent <= 1:
            return None
        places = 0
        while extent * 10 ** places < 1:
            places += 1
        if extent * 10 ** places != 1 or (centre * 10 ** places).denominator != 1:
            return None
        text = _dims._decimal_text(centre)
        if places:
            whole, _, frac = text.partition(".")
            text = f"{whole}.{frac.ljust(places, '0')}"
        return text
    lat_text = position((south + north) / 2, north - south) or lat
    lon_text = None
    if width < 360:
        lon_text = position(_dims._norm_longitude(west + width / 2), width)
    return f"{lat_text},{lon_text or lon}"


def _friendly_param(param, kind, units=None):
    if kind == _dims.KIND_PREFIX or kind in _dims.GRAPH_ORDERED:
        return param  # already the friendliest admissible spelling
    if kind == _dims.KIND_RECT:
        return _friendly_rect(param)
    if kind == _dims.KIND_COUNT:
        # Bare whole numbers are already the friendliest spelling — never
        # `2dz` for 24: dozens are an input courtesy, not a display unit.
        return _dims._render(_dims._denotation(param, kind, units), kind)
    if kind == _dims.KIND_DOMINANCE:
        return _friendly_dominance(_dims._parse_dominance(param, units),
                                   units)
    return _friendly_linear(_dims._denotation(param, kind, units), kind,
                            units)


# --------------------------------------------------------------------------- #
# Relative times: the input half (question 31)
# --------------------------------------------------------------------------- #

# `now`, `today`, `tomorrow` or an offset from now in ontodag's duration
# units, at either end of a calendar value. They are read here, where a
# person or an agent types, against a clock the caller passes; the core and
# every replay never see one, so a stored name, a file and a merge stay a
# function of their content.
_RELATIVE_SIDE = _dims._RELATIVE_TIME_RE
_RELATIVE_ANYWHERE = re.compile(
    r"(?<![\w-])(?:now|today|tomorrow)(?![\w-])|(?:\(|\.\.)[+-]\d")
# A term whose parameter holds no term: a calendar value never does.
_INNERMOST = re.compile(r"([^\s()]+)\(([^()]*)\)")
_DAY = 86_400


def _timestamp(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _offset(text):
    """Whole seconds of the offset `+7d` or `-90min`, read by the duration
    arithmetic in ontodag's units."""
    body = text[1:]
    try:
        family, value = _dims._parse_scalar(body)
    except ValueError:
        family, value = None, None
    if family == "length" and body.endswith("m"):
        raise ValueError(f"{text} is metres in ontodag; an offset from now "
                         f"is a duration: write {text}in")
    if family is None and body.endswith("w"):
        raise ValueError(f"{text}: ontodag has no unit w (W is watts); a "
                         f"week is wk: write {text}k")
    if family != "duration":
        raise ValueError(f"{text}: an offset from now is a duration in "
                         f"ontodag's units s, min, h, d or wk "
                         f"(+7d, -2h, +90min, +1wk)")
    if value.denominator != 1:
        raise ValueError(f"{text}: time is kept to the second, and this "
                         f"offset is not a whole number of seconds")
    return int(value)


def _relative_side(text, now, side):
    """One end of a calendar value at the clock `now`, in unix seconds:
    `today` and `tomorrow` are UTC dates, `now` and an offset an instant;
    an instant closing a range is the second before it, so `now..+2h` is
    two hours of seconds. Any other text is returned as it is."""
    if text in ("today", "tomorrow"):
        day = now - now % _DAY + (_DAY if text == "tomorrow" else 0)
        return _timestamp(day)[:10]
    if text == "now":
        at = now
    elif text[:1] in "+-" and _RELATIVE_SIDE.match(text):
        at = now + _offset(text) * (1 if text[0] == "+" else -1)
    else:
        return text
    return _timestamp(at - 1 if side == "hi" else at)


def has_relative(name):
    """Could `name` hold a relative time? A cheap test on the spelling."""
    return bool(_RELATIVE_ANYWHERE.search(name))


def relative_calendar(param, now):
    """The absolute calendar parameter the relative one `param` spells at
    `now` (unix seconds): `today..+7d` at 2026-10-11T09:46:05Z is
    `2026-10-11..2026-10-18T09:46:04Z`. `..` keeps its meaning, an open end:
    `..+90d` is everything up to 90 days from now."""
    if ".." not in param:
        return _relative_side(param, now, "at")
    lo, _, hi = param.partition("..")
    return (f"{_relative_side(lo, now, 'lo') if lo else ''}.."
            f"{_relative_side(hi, now, 'hi') if hi else ''}")


def absolute(name, dag=None, now=None, kind=None):
    """`name` with each relative time in a calendar value replaced by the
    absolute value it spells at `now` (unix seconds). A calendar value is the
    parameter of a head of the calendar kind in `dag` — a role of `time`
    included — or of the outermost head when `kind` says it is one. Without
    a clock, or with nothing relative in it, `name` is returned as it is."""
    if now is None or not has_relative(name):
        return name
    outer = _dims.split_term(name)

    def calendar(head):
        if kind is not None:
            return kind == _dims.KIND_CALENDAR and outer is not None \
                and head == outer[0]
        return dag is not None and \
            dag._dimension_of(head)[0] == _dims.KIND_CALENDAR

    def one(match):
        head, param = match.group(1), match.group(2)
        if not any(_RELATIVE_SIDE.match(side) for side in param.split("..")) \
                or not calendar(head):
            return match.group(0)
        return f"{head}({relative_calendar(param, now)})"
    return _INNERMOST.sub(one, name)


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
    return dag.parse_term(name)


def elaborate(name, dag=None, kind=None, now=None):
    """The canonical name of a surface term, under the given context (a DAG
    whose declarations resolve the head's kind, or an explicit kind). Names
    that are not parametric terms in that context are their own canonical
    form. Raises ValueError for a malformed parameter of a declared head —
    the same teaching error the core would raise at put/get time. With a
    clock, `now` in unix seconds, relative times in calendar values are read
    first (`absolute`); without one they are refused, as the core does."""
    name = absolute(name, dag, now, kind)
    resolved = _resolve(name, dag, kind)
    return resolved[2] if resolved else name


def render(name, dag=None, kind=None):
    """The friendly spelling of a canonical name, under the same context.
    Total: anything unrenderable (opaque, undeclared, malformed, or no
    context at all) is returned unchanged — output must never fail."""
    try:
        resolved = _resolve(name, dag, kind)
        if resolved is None:
            return name
        head, resolved_kind, canonical = resolved
        param = _dims.split_term(canonical)[1]
        if dag is not None and dag._param_node(head, param) is not None:
            return canonical   # a role naming a node: the name is the display
        units = dag._declared_units() if dag is not None else None
        return f"{head}({_friendly_param(param, resolved_kind, units)})"
    except ValueError:
        return name
