"""Parametric items ("dimension lattices"): grammar, registry, canonicalizer,
and the containment/intersection arithmetic. Design records:
docs/DIMENSIONS.md (the model) and docs/UNITS.md (the unit system,
registry v3, all verdicts accepted 2026-08-01).

Pure stdlib and graph-free (B1): callers resolve a head's *kind* from the DAG
(an ancestor walk to a registry kind node) and pass it into every function
here. Only exact, platform-independent arithmetic is permitted in this module
— **reduced rationals anchored at the SI coherent unit** (UNITS.md D9),
strings, and fixed-format ISO-8601 UTC timestamps compared lexicographically
— because the computed order participates in transitive reduction and
therefore in canonical roots (determinism doctrine, DIMENSIONS.md §3).
No floats, ever.

Rational anchoring, in one line: a canonical scalar is ``n[/d]<anchor>``
with n/d in lowest terms — ``weight(3kg)``, ``weight(1/2kg)`` for 500 g,
``length(10/33m)`` for the shaku — so *any* unit with an exact rational
definition is representable, forever, and no base ever needs refining
(UNITS.md §8). Non-anchor unit spellings (``g``, ``psi``, ``mph``…) are
input/render vocabulary only: they never appear in stored names, which is
what makes adding units later a non-event (D10).

A parametric term denotes a *set of values*; the computed order between two
same-head terms is containment of denotations (`contains`), i.e. the same
extension-inclusion order the DAG's asserted edges have always meant.
"""

import re
from calendar import monthrange
from datetime import datetime
from fractions import Fraction

# The registry version, MAJOR.MINOR (UNITS.md D10): order-affecting changes
# (anchors, kinds, arithmetic) bump the major and refuse across it;
# vocabulary-additive changes (new unit spellings, new families) bump the
# minor and interoperate — stored names carry only anchor suffixes, so old
# readers read everything and merely refuse unknown spellings as input.
# History: 1 (dimension lattices), 2 (+KIND_CALENDAR),
# 3.0 (2026-08-01: rational anchoring, the full SI + customary unit table),
# 3.1 (2026-08-01: information/data-rate/compute-rate families and the
#      protocol-fixed crypto denominations — the first D10 minor: purely
#      vocabulary-additive, interoperable with every 3.x reader),
# 3.2 (2026-08-01: GRAPH-DECLARED UNITS — `unit(spelling=value)` and
#      `unit-family(NAME)` nodes under the registry node `unit-declaration`
#      extend the vocabulary as DATA (UNITS.md §7); the built-in table
#      slims to physical/digital measurement + the stack's own tokens, and
#      currencies move to shipped packs adopted by merge),
# 4.0 (2026-08-01: AFFINE TEMPERATURES, and bare C/F go to them — Peter:
#      "if I type 24C it should be Celsius rather than Coulomb". `24C`,
#      `-40F`, `0C..100C` parse exactly onto the kelvin scale (offsets are
#      rationals). The bare coulomb and farad are spelled out (`coulomb`,
#      `farad` — now the anchors); every prefixed form (mC, uF, mAh...)
#      is untouched, and those are what charge/capacitance actually use.
#      MAJOR because two canonical anchors change and bare C/F change
#      meaning: a 3.x store carrying bare-C/F values must rewrite them to
#      coulomb/farad spellings before an ontodag.migrate replay).
REGISTRY_VERSION = "4.0"


def registry_compatible(version, other=None):
    """Same major = identical canonical-name arithmetic (D10)."""
    other = REGISTRY_VERSION if other is None else other
    return str(version).split(".")[0] == str(other).split(".")[0]


# Reserved node names the registry recognizes, the way the codebase already
# recognizes "*". A dimension head is declared by asserting it under exactly
# one kind node (directly or via ancestors): weight -> linear-dimension.
DIMENSION_ROOT = "dimension"
UNIT_DECLARATION = "unit-declaration"  # unit(...)/unit-family(...) parent
KIND_LINEAR = "linear-dimension"
KIND_PREFIX = "prefix-dimension"
KIND_DOMINANCE = "dominance-dimension"
# Calendar is linear with a calendar-only parameter grammar. It exists as its
# own kind for one reason: in a linear dimension a bare integer is a
# dimensionless *count* (`number(5)`), so `time(2026)` there can only mean the
# number 2026 -- which then refuses to compare with any real date. Parsing is
# deliberately context-free on the name, so the year reading cannot depend on
# what else happens to be in the graph; the declared kind is the one piece of
# context a term already carries, and it is where the calendar grammar belongs.
# Values canonicalize identically to a linear time dimension (same space tag),
# so a store that declared `time -> linear-dimension` can be re-declared under
# this kind without a single stored name changing.
KIND_CALENDAR = "calendar-dimension"
KINDS = frozenset({KIND_LINEAR, KIND_PREFIX, KIND_DOMINANCE, KIND_CALENDAR})
_LINEARISH = frozenset({KIND_LINEAR, KIND_CALENDAR})


# --------------------------------------------------------------------------- #
# The unit table (docs/UNITS.md §4, accepted 2026-08-01)
#
# family -> (anchor suffix, {suffix: exact Fraction factor to the anchor}).
# Anchors are the SI coherent units; every factor is exact by definition
# (the 1959 yard-and-pound agreement, the 2019 SI redefinition, and the
# international definitions of the rest). Suffixes are ASCII, case-
# sensitive, slash-free (the slash belongs to rational values), and unique
# across ALL families — the suffix alone determines the family (verified at
# import below, and unit-by-unit in tests/test_units.py).
# Honest exclusions (UNITS.md §2): Celsius/Fahrenheit (affine — temperature
# is kelvin-anchored) and the radian (pi/180 is irrational — the angle
# family is degree-anchored).
# --------------------------------------------------------------------------- #

def _build_units():
    F = Fraction
    lb = F("0.45359237")                    # kg, exact since 1959
    inch = F("0.0254")                      # m, exact since 1959
    ft, yd, mi = 12 * inch, 36 * inch, 63360 * inch
    lbf = lb * F("9.80665")                 # N (standard gravity, exact)
    gal = 231 * inch**3                     # m3, US gallon (exact)
    igal = F("0.00454609")                  # m3, imperial gallon (exact)
    eV = F("1.602176634") / 10**19          # J, exact since SI-2019
    families = {
        "mass": ("kg", {
            "ng": F(1, 10**12), "ug": F(1, 10**9), "mg": F(1, 10**6),
            "g": F(1, 1000), "kg": F(1), "t": F(1000),
            "gr": lb / 7000, "oz": lb / 16, "lb": lb, "st": 14 * lb,
            "cwt": 112 * lb, "ust": 2000 * lb, "lt": 2240 * lb,
            "ct": F(1, 5000), "ozt": F("0.0311034768")}),
        "length": ("m", {
            "nm": F(1, 10**9), "um": F(1, 10**6), "mm": F(1, 1000),
            "cm": F(1, 100), "m": F(1), "km": F(1000),
            "mil": inch / 1000, "in": inch, "ft": ft, "yd": yd, "mi": mi,
            "nmi": F(1852), "au": F(149597870700),
            "ly": F(9460730472580800),
            "pm": F(1, 10**12), "fm": F(1, 10**15),
            "angstrom": F(1, 10**10), "dm": F(1, 10),
            "ftm": 72 * inch, "ch": 792 * inch, "fur": 7920 * inch}),
        "duration": ("s", {
            "ns": F(1, 10**9), "us": F(1, 10**6), "ms": F(1, 1000),
            "s": F(1), "min": F(60), "h": F(3600), "d": F(86400),
            "wk": F(604800), "a": F(31557600)}),
        "area": ("m2", {
            "mm2": F(1, 10**6), "cm2": F(1, 10**4), "m2": F(1),
            "ha": F(10**4), "km2": F(10**6),
            "in2": inch**2, "ft2": ft**2, "yd2": yd**2,
            "ac": 43560 * ft**2, "mi2": mi**2}),
        "volume": ("m3", {
            "uL": F(1, 10**9), "mL": F(1, 10**6), "L": F(1, 1000),
            "m3": F(1), "in3": inch**3, "ft3": ft**3,
            "floz": gal / 128, "pt": gal / 8, "qt": gal / 4, "gal": gal,
            "ifloz": igal / 160, "ipt": igal / 8, "iqt": igal / 4,
            "igal": igal,
            "tsp": gal / 768, "tbsp": gal / 256, "cup": gal / 16,
            "bbl": 42 * gal,                    # oil barrel
            "bu": 2150 * inch**3 + F(42, 100) * inch**3}),  # US bushel
        "speed": ("mps", {
            "mps": F(1), "kmh": F(1000, 3600), "mph": mi / 3600,
            "kn": F(1852, 3600), "fps": ft,
            "c": F(299792458)}),                # exact by definition
        "pressure": ("Pa", {
            "Pa": F(1), "hPa": F(100), "kPa": F(1000), "MPa": F(10**6),
            "mbar": F(100), "bar": F(10**5), "atm": F(101325),
            "mmHg": F("133.322387415"), "psi": lbf / inch**2,
            "Torr": F(101325, 760),             # NOT mmHg — close, distinct
            "inHg": F("25.4") * F("133.322387415")}),
        "force": ("N", {
            "uN": F(1, 10**6), "mN": F(1, 1000), "N": F(1), "kN": F(1000),
            "lbf": lbf}),
        "energy": ("J", {
            "eV": eV, "J": F(1), "kJ": F(1000), "MJ": F(10**6),
            "GJ": F(10**9), "Wh": F(3600), "kWh": F(3600000),
            "cal": F("4.184"), "kcal": F(4184),
            "BTU": F("1055.05585262"), "thm": F("105505585.262"),
            "keV": eV * 10**3, "MeV": eV * 10**6, "GeV": eV * 10**9,
            "TeV": eV * 10**12}),
        "power": ("W", {
            "uW": F(1, 10**6), "mW": F(1, 1000), "W": F(1), "kW": F(1000),
            "MW": F(10**6), "GW": F(10**9), "hp": 550 * ft * lbf,
            "PS": F("735.49875")}),             # metric horsepower
        "frequency": ("Hz", {
            "uHz": F(1, 10**6), "mHz": F(1, 1000), "Hz": F(1),
            "kHz": F(1000), "MHz": F(10**6), "GHz": F(10**9),
            "rpm": F(1, 60)}),
        "temperature": ("K", {
            "uK": F(1, 10**6), "mK": F(1, 1000), "K": F(1),
            "Ra": F(5, 9)}),   # Rankine: scalar from absolute zero, exact
        "current": ("A", {
            "pA": F(1, 10**12), "nA": F(1, 10**9), "uA": F(1, 10**6),
            "mA": F(1, 1000), "A": F(1), "kA": F(1000)}),
        "charge": ("coulomb", {
            "pC": F(1, 10**12), "nC": F(1, 10**9), "uC": F(1, 10**6),
            "mC": F(1, 1000), "coulomb": F(1),
            "mAh": F("3.6"), "Ah": F(3600)}),
        "voltage": ("V", {
            "uV": F(1, 10**6), "mV": F(1, 1000), "V": F(1), "kV": F(1000),
            "MV": F(10**6)}),
        "resistance": ("ohm", {
            "uohm": F(1, 10**6), "mohm": F(1, 1000), "ohm": F(1),
            "kohm": F(1000), "Mohm": F(10**6)}),
        "capacitance": ("farad", {
            "pF": F(1, 10**12), "nF": F(1, 10**9), "uF": F(1, 10**6),
            "mF": F(1, 1000), "farad": F(1)}),
        "inductance": ("H", {
            "nH": F(1, 10**9), "uH": F(1, 10**6), "mH": F(1, 1000),
            "H": F(1)}),
        "conductance": ("sie", {          # siemens; "S" would clash with s
            "usie": F(1, 10**6), "msie": F(1, 1000), "sie": F(1)}),
        "magnetic-flux": ("Wb", {
            "nWb": F(1, 10**9), "uWb": F(1, 10**6), "mWb": F(1, 1000),
            "Wb": F(1)}),
        "flux-density": ("T", {
            "uT": F(1, 10**6), "mT": F(1, 1000), "T": F(1)}),
        "luminous-intensity": ("cd", {
            "ucd": F(1, 10**6), "mcd": F(1, 1000), "cd": F(1)}),
        "luminous-flux": ("lm", {
            "ulm": F(1, 10**6), "mlm": F(1, 1000), "lm": F(1)}),
        "illuminance": ("lx", {
            "ulx": F(1, 10**6), "mlx": F(1, 1000), "lx": F(1)}),
        "amount": ("mol", {
            "pmol": F(1, 10**12), "nmol": F(1, 10**9),
            "umol": F(1, 10**6), "mmol": F(1, 1000), "mol": F(1)}),
        "radioactivity": ("Bq", {
            "Bq": F(1), "kBq": F(1000), "MBq": F(10**6), "GBq": F(10**9),
            "Ci": F(37000000000)}),             # curie, exact
        "absorbed-dose": ("Gy", {
            "uGy": F(1, 10**6), "mGy": F(1, 1000), "Gy": F(1)}),
        "dose-equivalent": ("Sv", {
            "uSv": F(1, 10**6), "mSv": F(1, 1000), "Sv": F(1),
            "rem": F(1, 100)}),
        "optical-power": ("dpt", {              # dioptres (reciprocal
            "dpt": F(1)}),                      # metres: its own quantity)
        "catalytic-activity": ("kat", {
            "nkat": F(1, 10**9), "ukat": F(1, 10**6), "kat": F(1)}),
        "angle": ("deg", {                # degree-anchored; radian excluded
            "mas": F(1, 3600000), "arcsec": F(1, 3600),
            "arcmin": F(1, 60), "deg": F(1), "grad": F(9, 10),
            "turn": F(360)}),
        # -- non-SI but exactly fixed (3.1) ------------------------------ #
        "information": ("bit", {
            "b": F(1), "bit": F(1), "B": F(8),
            "kbit": F(10**3), "Mbit": F(10**6), "Gbit": F(10**9),
            "Tbit": F(10**12),
            "kB": F(8) * 10**3, "MB": F(8) * 10**6, "GB": F(8) * 10**9,
            "TB": F(8) * 10**12, "PB": F(8) * 10**15, "EB": F(8) * 10**18,
            "KiB": F(8) * 2**10, "MiB": F(8) * 2**20, "GiB": F(8) * 2**30,
            "TiB": F(8) * 2**40, "PiB": F(8) * 2**50, "EiB": F(8) * 2**60}),
        "data-rate": ("bps", {
            "bps": F(1), "kbps": F(10**3), "Mbps": F(10**6),
            "Gbps": F(10**9), "Tbps": F(10**12),
            "Bps": F(8), "kBps": F(8) * 10**3, "MBps": F(8) * 10**6,
            "GBps": F(8) * 10**9}),
        "compute-rate": ("FLOPS", {
            "FLOPS": F(1), "MFLOPS": F(10**6), "GFLOPS": F(10**9),
            "TFLOPS": F(10**12), "PFLOPS": F(10**15),
            "EFLOPS": F(10**18)}),
        # No currencies here at all (UNITS.md / PACKS.md Q10, accepted):
        # the built-in table holds only what PHYSICS fixes — anything
        # market-shaped, even BTC, lives in packs, so no market suffix is
        # ever hard-claimed for a registry major. The stack's own tokens
        # (BTC/ETH/BZZ/xBZZ/DAI/xDAI) ship in the `crypto-core` pack.
    }

    # (Stablecoins and national fiat currencies moved to shipped PACKS —
    # graph-declared vocabulary adopted by merge, ontodag.packs — 3.2.)
    families["count"] = ("", {"": F(1), "pct": F(1, 100),
                          "ppm": F(1, 10**6), "bp": F(1, 10**4),
                          "dz": F(12)})
    anchors, suffixes = {}, {}
    for family, (anchor, units) in families.items():
        if units[anchor] != 1:
            raise AssertionError(f"anchor {anchor!r} of {family} must be 1")
        anchors[family] = anchor
        for suffix, factor in units.items():
            if suffix in suffixes:
                raise AssertionError(f"suffix {suffix!r} claimed twice")
            if factor <= 0:
                raise AssertionError(f"non-positive factor for {suffix!r}")
            suffixes[suffix] = (family, factor)
    return anchors, suffixes


_ANCHOR, _UNITS = _build_units()

# Affine units (2026-08-01, Peter: "we need Celsius", and "if I type 24C
# it should be Celsius rather than Coulomb"): K = n·factor + offset, exact
# rationals. The old §2 exclusion is retracted in part — the blocker was
# the (family, factor) model, not determinism: with an explicit suffix the
# map is exact and unambiguous. Bare `C` and `F` mean the temperatures —
# context-free, per Peter's rule — which is why the bare coulomb and farad
# are spelled out above (prefixed forms, the ones those families actually
# use, are untouched). `degC`/`degF` stay as input aliases (the SI ASCII
# fallback); rendering emits `C`/`F`. Affine spellings denote ABSOLUTE
# temperature points; a temperature *difference* is a different quantity
# and stays kelvin-only. Built-in-only (graph declarations remain
# factor-only), and _RENDER_AFFINE lists the render-preferred spellings.
_AFFINE = {
    "C": ("temperature", Fraction(1), Fraction("273.15")),
    "degC": ("temperature", Fraction(1), Fraction("273.15")),
    "F": ("temperature", Fraction(5, 9), Fraction(45967, 180)),
    "degF": ("temperature", Fraction(5, 9), Fraction(45967, 180)),
}
_RENDER_AFFINE = ("C", "F")
_TIME = "time"  # the one non-numeric linear value space (ISO-8601 UTC)

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_YEAR_RE = re.compile(r"^\d{4}$")
# A value is an integer, a decimal, or a rational n/d — then a unit suffix
# (letters first, digits allowed after: m2, in3). The slash belongs to the
# value, which is why suffixes are slash-free (UNITS.md).
_NUM_RE = re.compile(r"^(-?\d+(?:\.\d+)?|-?\d+/\d+)([A-Za-z][A-Za-z0-9]*)?$")
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


def _lookup(suffix, units):
    """Suffix resolution: the built-in table, then graph declarations
    (UNITS.md §7 — conflicts were already refused at resolve time)."""
    hit = _UNITS.get(suffix)
    if hit is None and units:
        hit = units.get(suffix)
    return hit


def _parse_scalar(text, units=None):
    """One linear value -> (family, value). Numeric values become exact
    Fractions of the family's anchor unit — integers, decimals and
    rationals (`10/33m`) all land exactly, so nothing is ever rounded or
    refused for precision (UNITS.md D9); timestamps stay strings
    (lexicographic = chronological).
    """
    if _TS_RE.match(text):
        return _TIME, _parse_timestamp(text)
    match = _NUM_RE.match(text)
    if not match:
        raise ValueError(f"invalid value {text!r}")
    number, unit = match.groups()
    unit = unit or ""
    affine = _AFFINE.get(unit)
    if affine is not None:
        family, factor, offset = affine
        try:
            value = Fraction(number) * factor + offset
        except ZeroDivisionError:
            raise ValueError(f"zero denominator in {text!r}") from None
        if value < 0:
            raise ValueError(
                f"{text!r} is below absolute zero ({-offset/factor} "
                f"{unit} at the coldest)")
        return family, value
    hit = _lookup(unit, units)
    if hit is None:
        raise ValueError(
            f"unknown unit {unit!r} in {text!r} — not in the built-in "
            f"table or this graph's unit declarations"
            f"{_pack_hint([unit])}")
    family, factor = hit
    try:
        value = Fraction(number) * factor
    except ZeroDivisionError:
        raise ValueError(f"zero denominator in {text!r}") from None
    if value < 0:
        raise ValueError(
            f"negative quantity {text!r} — the grammar admits negatives "
            f"only for affine temperature spellings (C/degC, F/degF)")
    return family, value


def _parse_end(text, side, units=None):
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
    return _parse_scalar(text, units)


def _parse_linear(param, units=None):
    """-> (family, lo, hi); closed interval; None = unbounded. Numeric
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
        lo = _parse_end(lo_text, "lo", units) if lo_text else None
        hi = _parse_end(hi_text, "hi", units) if hi_text else None
        if lo and hi:
            if lo[0] != hi[0]:
                raise ValueError(
                    f"range ends of {param!r} mix families {lo[0]}/{hi[0]}")
            if lo[1] > hi[1]:
                raise ValueError(f"empty range {param!r} (lo > hi)")
        family = (lo or hi)[0]
        lo_value = lo[1] if lo else (None if family == _TIME else Fraction(0))
        return family, lo_value, hi[1] if hi else None
    if _DATE_RE.match(param):  # bare date = the whole day, as an interval
        lo = _parse_end(param, "lo", units)
        hi = _parse_end(param, "hi", units)
        return _TIME, lo[1], hi[1]
    family, value = _parse_scalar(param, units)
    return family, value, value  # a point is a degenerate interval


def _calendar_end(text, side):
    """One calendar literal -> the instant at `side` of the interval it names.

    Reduced precision denotes the whole period, which is the same rule the
    linear grammar already applies to a bare date: `2026` is the year,
    `2026-08` the month, `2026-08-15` the day, and a full timestamp is the
    instant itself. So a document filed under `time(2026-08-15)` sits inside
    `time(2026)` by arithmetic, with no edge between them.
    """
    if _TS_RE.match(text):
        return _parse_timestamp(text)
    if _DATE_RE.match(text):
        try:
            datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"invalid date {text!r}")
        return text + ("T00:00:00Z" if side == "lo" else "T23:59:59Z")
    if _MONTH_RE.match(text):
        year, month = int(text[:4]), int(text[5:])
        if not 1 <= month <= 12:
            raise ValueError(f"invalid month {text!r} (expected YYYY-MM)")
        if side == "lo":
            return f"{text}-01T00:00:00Z"
        return f"{text}-{monthrange(year, month)[1]:02d}T23:59:59Z"
    if _YEAR_RE.match(text):
        return f"{text}-01-01T00:00:00Z" if side == "lo" \
            else f"{text}-12-31T23:59:59Z"
    raise ValueError(
        f"invalid calendar value {text!r} — expected YYYY, YYYY-MM, "
        "YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ")


def _parse_calendar(param):
    """-> (time family, lo, hi); closed interval of instants, None = open.

    Same shape as `_parse_linear` so everything downstream (containment,
    meet, rendering, the space tag) is shared — only the literal grammar
    differs, and here every literal is a calendar period.
    """
    if ".." in param:
        parts = param.split("..")
        if len(parts) != 2:
            raise ValueError(f"malformed range {param!r}")
        lo_text, hi_text = parts
        if not lo_text and not hi_text:
            raise ValueError(f"range {param!r} needs at least one end")
        lo = _calendar_end(lo_text, "lo") if lo_text else None
        hi = _calendar_end(hi_text, "hi") if hi_text else None
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"empty range {param!r} (lo > hi)")
        return _TIME, lo, hi
    return _TIME, _calendar_end(param, "lo"), _calendar_end(param, "hi")


def _parse_dominance(param, units=None):
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
        families[i], values[i] = _parse_scalar(number + carried_unit, units)
    if len(set(families)) != 1:
        raise ValueError(f"components of {param!r} mix unit families")
    return families[0], tuple(sorted(values, reverse=True))


def _parse_prefix(param):
    if ".." in param or not _PREFIX_RE.match(param):
        raise ValueError(f"invalid prefix value {param!r}")
    return param


# ---- rendering (the canonical form; names are the identity) ----------------

def _fraction_text(value):
    value = Fraction(value)
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _render_scalar(family, value):
    """Canonical spelling: a reduced rational plus the anchor suffix —
    `3kg`, `1/2kg`, `10/33m` (UNITS.md D9). A graph-declared family's
    anchor IS its name (`unit-family(SOL)` → suffix `SOL`)."""
    if family == _TIME:
        return value
    return f"{_fraction_text(value)}{_ANCHOR.get(family, family)}"


def _render_linear(family, lo, hi):
    if lo is not None and lo == hi:
        return _render_scalar(family, lo)
    # Numeric families: lo == 0 means unbounded-below and renders as the
    # `..hi` form — except when hi is also unbounded, where `0..` keeps the
    # rendering parseable (a bare `..` is invalid).
    if family != _TIME and lo == 0 and hi is not None:
        lo = None
    lo_text = _render_scalar(family, lo) if lo is not None else ""
    hi_text = _render_scalar(family, hi) if hi is not None else ""
    return f"{lo_text}..{hi_text}"


def _denotation(param, kind, units=None):
    if kind == KIND_CALENDAR:
        return _parse_calendar(param)
    if kind == KIND_LINEAR:
        return _parse_linear(param, units)
    if kind == KIND_DOMINANCE:
        return _parse_dominance(param, units)
    if kind == KIND_PREFIX:
        return _parse_prefix(param)
    raise ValueError(f"unknown dimension kind {kind!r}")


def _render(denotation, kind):
    if kind in _LINEARISH:
        return _render_linear(*denotation)
    if kind == KIND_DOMINANCE:
        family, values = denotation
        suffix = _ANCHOR.get(family, family)
        return "x".join(_fraction_text(v) for v in values) + suffix
    return denotation  # prefix: the validated string is canonical


def canonicalize(name, kind, units=None):
    """The canonical name of a parametric term (identity string). Raises
    ValueError when the parameter is malformed for the head's kind.
    `units` extends the suffix vocabulary with graph declarations
    (UNITS.md §7); canonical output always uses anchor suffixes."""
    split = split_term(name)
    if split is None:
        raise ValueError(f"{name!r} is not a parametric term")
    head, param = split
    return f"{head}({_render(_denotation(param, kind, units), kind)})"


def space_of(name, kind, units=None):
    """Value-space tag for put-time consistency checks: every value of one
    head must share it (one family, one arity)."""
    denotation = _denotation(split_term(name)[1], kind, units)
    if kind in _LINEARISH:
        # Calendar shares linear's tag on purpose: the two describe the same
        # value space, so re-declaring a time dimension from one to the other
        # leaves every stored value and every canonical name untouched.
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


def _family_mismatch(a, fam_a, b, fam_b):
    """The families-differ message, with the one hint worth giving.

    A bare `time(2026)` in a *linear* dimension is the count 2026, not the
    year, so it refuses to compare with any real date. That reads as a
    baffling unit error unless we say what to do about it.
    """
    message = (f"unit families differ: {a!r} ({fam_a}) vs {b!r} ({fam_b})")
    counted, timed = ((a, b) if fam_a == "count" else (b, a)) \
        if {fam_a, fam_b} == {"count", _TIME} else (None, None)
    if counted is not None and _YEAR_RE.match(split_term(counted)[1]):
        message += (
            f" — {counted!r} is the number, not the year. Declare the head "
            f"under {KIND_CALENDAR!r} to read bare years and months as "
            f"calendar periods, or write the range out "
            f"(e.g. '2026-01-01..2026-12-31')")
    return message


def contains(outer, inner, kind, units=None):
    """denotation(inner) ⊆ denotation(outer)? Both must share the head.
    Reflexive; distinct canonical names are therefore strictly ordered or
    incomparable, never mutually contained (that is what keeps the combined
    relation a partial order — DIMENSIONS.md §11, I1)."""
    _, param_outer, param_inner = _same_head(outer, inner)
    if kind in _LINEARISH:
        fam_o, lo_o, hi_o = _denotation(param_outer, kind, units)
        fam_i, lo_i, hi_i = _denotation(param_inner, kind, units)
        if fam_o != fam_i:
            raise ValueError(_family_mismatch(outer, fam_o, inner, fam_i))
        lo_ok = lo_o is None or (lo_i is not None and lo_i >= lo_o)
        hi_ok = hi_o is None or (hi_i is not None and hi_i <= hi_o)
        return lo_ok and hi_ok
    if kind == KIND_DOMINANCE:
        fam_o, values_o = _parse_dominance(param_outer, units)
        fam_i, values_i = _parse_dominance(param_inner, units)
        if fam_o != fam_i or len(values_o) != len(values_i):
            raise ValueError(
                f"incompatible dominance spaces: {outer!r} vs {inner!r}")
        return all(o >= i for o, i in zip(values_o, values_i))
    if kind == KIND_PREFIX:
        return _parse_prefix(param_inner).startswith(
            _parse_prefix(param_outer))
    raise ValueError(f"unknown dimension kind {kind!r}")


def intersect(a, b, kind, units=None):
    """Canonical name of denotation(a) ∩ denotation(b), or None when the
    intersection is provably empty. Within a dimension meets are exact —
    the planner pre-intersects same-head query terms with this, and the
    disjoint-parents guard raises on None (DIMENSIONS.md §8, §9)."""
    head, param_a, param_b = _same_head(a, b)
    if kind in _LINEARISH:
        fam_a, lo_a, hi_a = _denotation(param_a, kind, units)
        fam_b, lo_b, hi_b = _denotation(param_b, kind, units)
        if fam_a != fam_b:
            raise ValueError(_family_mismatch(a, fam_a, b, fam_b))
        lo = lo_a if lo_b is None else lo_b if lo_a is None else max(lo_a, lo_b)
        hi = hi_a if hi_b is None else hi_b if hi_a is None else min(hi_a, hi_b)
        if lo is not None and hi is not None and lo > hi:
            return None
        return f"{head}({_render_linear(fam_a, lo, hi)})"
    if kind == KIND_DOMINANCE:
        fam_a, values_a = _parse_dominance(param_a, units)
        fam_b, values_b = _parse_dominance(param_b, units)
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


# --------------------------------------------------------------------------- #
# Graph-declared units (UNITS.md §7, 3.2): vocabulary as data
#
# A node `unit(SPELLING=VALUE)` under the registry node `unit-declaration`
# declares SPELLING to mean exactly VALUE (a number in an already-resolvable
# unit — chains allowed); `unit-family(NAME)` declares a new family whose
# anchor suffix is NAME itself. Declarations are ordinary graph content, so
# they MERGE — a "unit pack" is just a published ontology of declaration
# nodes, and a store's vocabulary travels inside the store. Canonical names
# for built-in families keep built-in anchors; a declared family's anchor
# is its own name, part of the merged interpretation context exactly as
# CONTRACT.md G1's relativity clause allows. Conflicts (a spelling defined
# twice with different meanings, or clashing with the built-in table) and
# unresolvable definitions are refused LOUDLY at first parametric use —
# the conflicting-kind-declaration precedent.
# --------------------------------------------------------------------------- #

_SUFFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


def _pack_hint(suffixes):
    """The actionable tail of an unknown-unit error: name the shipped pack
    that defines the spelling when one does (`USD` -> fiat-iso4217,
    `sat` -> crypto-core), the generic declaration recipe otherwise.
    Lazy import — packs sits above this module, and only error paths
    ever come here."""
    from ontodag import packs as _packs
    by_pack = {}
    for suffix in suffixes:
        for pack in _packs.packs_defining(suffix):
            by_pack.setdefault(pack, []).append(suffix)
    if by_pack:
        offers = "; ".join(
            f"{', '.join(map(repr, sorted(found)))} is in the "
            f"{pack!r} pack — adopt it with: odag pack {pack}"
            for pack, found in sorted(by_pack.items()))
        return f" ({offers}; vocabulary then travels with the store)"
    one = sorted(suffixes)[0]
    return (f" (merge the pack that defines it, or declare it: "
            f"put 'unit({one}=<value><unit>)' unit-declaration)")


def resolve_declarations(names):
    """Parse a set of declaration-node names into an extra-units map
    ``{suffix: (family, factor)}``. Pure; raises ValueError with a
    teaching message on malformed, conflicting, or unresolvable
    declarations. Non-declaration names are ignored (the caller passes
    every child of `unit-declaration`; stray nodes are someone's
    business, not an error here)."""
    extra = {}

    def register(spelling, value, raw):
        clash = (_UNITS.get(spelling) or extra.get(spelling)
                 or _AFFINE.get(spelling))
        if clash is not None and clash != value:
            raise ValueError(
                f"conflicting unit declaration {raw!r}: {spelling!r} "
                f"already means {clash!r} — two merged vocabularies "
                f"disagree; remove one side")
        extra[spelling] = value

    pending = []
    for raw in sorted(n for n in names if isinstance(n, str)):
        split = split_term(raw)
        if split is None:
            continue
        head, param = split
        if head == "unit-family":
            if not _SUFFIX_RE.match(param):
                raise ValueError(
                    f"invalid unit-family declaration {raw!r}: the name "
                    f"must be letters then letters/digits (it becomes the "
                    f"anchor suffix)")
            register(param, (param, Fraction(1)), raw)
        elif head == "unit":
            spelling, eq, definition = param.partition("=")
            if not eq or not _SUFFIX_RE.match(spelling):
                raise ValueError(
                    f"invalid unit declaration {raw!r}: expected "
                    f"unit(SPELLING=<number><unit>)")
            match = _NUM_RE.match(definition)
            if not match or not match.group(2):
                raise ValueError(
                    f"invalid unit declaration {raw!r}: the definition "
                    f"must be an exact number in a named unit")
            pending.append((spelling, match.group(1), match.group(2), raw))

    while pending:                      # chains resolve to a fixed point
        rest, progress = [], False
        for spelling, number, base, raw in pending:
            source = _UNITS.get(base) or extra.get(base)
            if source is None:
                rest.append((spelling, number, base, raw))
                continue
            family, base_factor = source
            factor = Fraction(number) * base_factor
            if factor <= 0:
                raise ValueError(f"non-positive factor in {raw!r}")
            register(spelling, (family, factor), raw)
            progress = True
        if not progress:
            missing = sorted({base for _, _, base, _ in rest})
            raise ValueError(
                f"unresolvable unit declarations "
                f"{sorted(r for *_, r in rest)!r}: unknown base unit(s) "
                f"{missing!r}{_pack_hint(missing)}")
        pending = rest
    return extra
