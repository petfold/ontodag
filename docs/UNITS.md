# Units: All of SI, the Customary Units, and the Bases That Make Them Exact

Status: **accepted AND IMPLEMENTED, 2026-08-01 (registry v3 shipped the
same evening — `dimensions.py` rational anchoring, ~30 families/120+ unit
spellings, `tests/test_units.py` exactness suite, prelude v2, and the
`ontodag.migrate` replay tool). All verdicts D1–D10 accepted by Peter.** Headline: **D9 (rational
anchoring) is in** — canonical values are reduced rationals of the SI
coherent unit, bases are abolished, and with them every future class-C
migration; D1 and D4 (computed bases, quantum names) are thereby moot.
D10 splits the registry version major/minor. One deviation from the §4
table as drawn: suffixes are **slash-free** (the slash belongs to rational
values like `10/33m`), so speed reads `mps`/`kmh`/`mph`/`kn`/`fps`.
Registry v3 is the one canonical-name migration in the system's life, and
old spellings (`mg`, `mm`) remain valid *input* — so re-canonicalization
is a replay through `put` under v3, nothing more.

Read with `DIMENSIONS.md` (the computed order participates in canonical
roots — the reason exactness is non-negotiable; values are, since D9,
exact rationals of per-family SI anchors) and `SURFACE_LAYER.md` §4/§5.5 (humans see
rendered units; canonical spellings are for machines).

## 1. Principles

- **P1 — Exactness by construction, as ever.** A unit enters a family only
  with an exact rational factor to the family's base. No floats, no
  rounding, no "close enough". This is what the 1959 yard-and-pound
  agreement and the 2019 SI redefinition make possible: nearly every unit
  anyone types is an exact rational to SI.
- **P2 — The base is the family's computed common measure.** Not chosen by
  taste: the base is the rational gcd of every unit in the family (with a
  ×10³ safety margin where the suffix stays nameable), so *every* unit is
  an integer multiple by construction, verified by a test that recomputes
  it from the definition table. Peter's instinct, generalized: "move the
  unit down a few decimal places" — and where powers of ten cannot work
  (§3), down a few *factors of 127*.
- **P3 — Overflow is a non-question in Python, and bounded everywhere
  else.** Python integers are arbitrary-precision, so fineness costs only
  digits in canonical names (which humans never read — rendering picks the
  friendly unit). For exports: one bar in the pressure base is ~1.3×10¹⁴
  and an astronomical length in nm is ~10²⁵ — comfortably inside EVM's
  uint256 (~10⁷⁷); JSON carries canonical *names* as strings, so
  JavaScript's 2⁵³ limit never touches them. Err fine.
- **P4 — One family per quantity, no dimensional algebra.** The model
  never derives Pa from kg·m⁻¹·s⁻²; `pressure` is simply its own linear
  family, first-class — tyre pressure is `pressure(220kPa)` (or
  `pressure(32psi)`, same lattice, §3). Derived-ness is history, not
  structure.
- **P5 — Bases prefer SI-prefixed names; otherwise a named quantum.**
  Where the common measure is a power of ten of the SI unit, the base is
  that prefixed unit (`ug`, `nm`, `ns`, `qJ`). Where a customary unit
  forces a non-decimal measure (§3), the base gets a systematic suffix —
  the unit name + `q` (for *quantum*): `Paq`, `mpsq`. Canonical names were
  never for reading; `odag canon` and the renderer keep the human view.
- **P6 — Micro-inch is the wrong direction (worked example).** Since
  1 in = 25.4 mm exactly, a fine *metric* base covers it: 1 in = 25,400 µm
  = 25,400,000 nm. A micro-inch *base* would instead break metric
  (1 mm = 5000⁄127 µin — not an integer). Customary units ride on metric
  bases wherever their factors terminate decimally; only the §3 class
  needs computed quanta.

## 2. What stays excluded, honestly

- **Affine scales: °C and °F.** They are offsets, not multiples —
  `value × factor` cannot express them, and pretending (storing kelvin,
  rendering Celsius) would make `temperature(20)` ambiguous in exactly the
  way this system exists to prevent. Temperature ships **kelvin-only**
  (`K`, `mK`, `uK` — scalar from absolute zero); an affine-dimension kind
  is future work if anyone actually files thermostat settings.
- **Transcendental ratios: the radian.** 1° = π⁄180 rad — irrational, so
  degrees and radians cannot share an exact lattice, ever. The `angle`
  family is **degree-based** (deg, arcmin, arcsec, gradian = 0.9°,
  turn = 360° — all rational); the radian is refused with an error that
  says why. (Radian-native users can declare their own `angle-rad` head;
  the two won't compare, which is the truth.)
- **Units without fixed exact definitions**: currencies, the calorie
  zoo beyond the thermochemical 4.184 J, "cups". User-defined unit packs
  (§7) are the door for anything with an exact local definition.

## 3. The 127² discovery: why psi needs a quantum, and gets one

psi = lbf⁄in² carries **127² in its denominator** (from the inch twice):
psi = 8,896,443,230,521⁄1,290,320,000 Pa exactly. No power-of-ten base of
the pascal — however tiny — makes that an integer, so "move the decimal
point" is *mathematically unavailable* here. But P2 already generalizes
it: the pressure base is the common measure of the whole family
{Pa…, bar, atm, mmHg, psi}, computed as their rational gcd — every unit an
integer, Pa and psi in **one lattice**, so a European and an American tyre
listing compare exactly. The same mechanism covers the knot
(1852⁄3600 m/s has a 3² denominator) in the speed family, and anything
else the definition table throws at it. This is the piece hand-picked
"tiny units" could never get right, and the test recomputes it forever.

## 4. The families (proposed scope)

*(Historical: the "base" column below is the pre-D9 draft — under the
accepted D9 every family's canonical suffix is simply its SI coherent
anchor (`kg`, `m`, `Pa`, …) and the shipped spelling set is the one in
`dimensions.py._build_units`, pinned by `tests/test_units.py`. Kept for
the record of how the quantum-base design fell away.)*

Every SI base quantity, every named SI derived unit as its own family
where it names a quantity people file under, the accepted-for-use units,
and the rationally-fixed customary units. Bases marked * are computed
quanta (P5); all factors verified by the exactness test.

| family | units (canonical base first) | notes |
|---|---|---|
| mass | **ng**, ug, mg, g, kg, t; gr, oz, lb, st, cwt, long/short ton; ct | lb = 453,592,370,000 ng; grain forces ng |
| length | **nm**, um, mm, cm, m, km; mil, in, ft, yd, mi, nmi; au, ly | mil = 25,400 nm; ly = 9.4607…×10²⁴ nm (fine) |
| duration | **ns**, us, ms, s, min, h, d, wk; a (Julian, 365.25 d) | ns base finally admits sub-second values |
| time | (calendar — unchanged) | timestamps, not durations |
| area | **base\***, mm2, cm2, m2, ha, km2; in2, ft2, yd2, ac, mi2 | in² has 127²: quantum base |
| volume | **base\***, uL, mL, L, m3; in3, ft3; floz, pt, qt, gal (US & imp) | 127³ from in³: quantum base |
| speed | **base\***, mm/s, m/s, km/h; ft/s, mph, kn | knot's 3² forces the quantum |
| pressure | **Paq\***, Pa, hPa, kPa, MPa, bar, atm, mmHg, psi | §3; tyre pressure both ways |
| force | **fN**, uN, mN, N, kN; lbf | lbf terminates at 10⁻¹³ N |
| energy | **qJ** (10⁻³⁰ J), eV, J, kJ, MJ, kWh, Wh; cal, kcal; BTU | eV exact since SI-2019 |
| power | **base\***, uW, mW, W, kW, MW; hp | hp inherits lbf's tail |
| frequency | **uHz**, mHz, Hz, kHz, MHz, GHz | |
| temperature | **uK**, mK, K | kelvin-only (§2) |
| current | **pA**, nA, uA, mA, A | |
| charge | **pC**, nC, uC, mC, C, Ah, mAh | |
| voltage | **uV**, mV, V, kV | |
| resistance | **uohm**, mohm, ohm, kohm, Mohm | suffixes are ASCII |
| capacitance | **pF**, nF, uF, mF, F | |
| inductance | **nH**, uH, mH, H | |
| conductance | **uS_**, mS_, S_ | naming vs siemens/second clash: see D5 |
| magnetic flux | **nWb**, uWb, mWb, Wb | |
| flux density | **uT**, mT, T | |
| luminous intensity | **ucd**, mcd, cd | |
| luminous flux | **ulm**, mlm, lm | |
| illuminance | **ulx**, mlx, lx | |
| amount | **pmol**, nmol, umol, mmol, mol | |
| radioactivity | **Bq**, kBq, MBq | Bq is already the atom |
| absorbed dose | **uGy**, mGy, Gy | |
| dose equivalent | **uSv**, mSv, Sv | |
| catalytic activity | **nkat**, ukat, kat | |
| angle | **mas** (milliarcsecond), arcsec, arcmin, deg, grad, turn | degree-based; radian refused (§2) |
| count | (unchanged) | the dimensionless family |

Suffix grammar stays letters-only ASCII (`um` not µm, `ohm` not Ω, `L`
for litre, `2`/`3` in `m2`/`in3` need a grammar tweak — see D6).

## 5. Implementation shape (when approved)

One **definition table** of exact `Fraction` factors — the single source
of truth — from which the runtime `_UNITS` structure *and* the exactness
test are generated: the test recomputes every family's common measure and
asserts every unit is an integer multiple of the shipped base and that
every base divides its family's every unit. Adding a unit later = one
table row + the registry bump the test forces you to notice. The parser
(`_parse_scalar`) gains per-family suffix maps (today's flat dict has one
namespace; `mHz` vs `m` demands family-scoped resolution — the head's
family is known before the value parses, so this is local). Rendering
(`surface._friendly_int`) needs nothing: largest-dividing-unit already
generalizes; it gains only per-family preferred-system hints later
(policy, per §4 of `SURFACE_LAYER.md`).

## 6. Migration: one deliberate break, now

`REGISTRY_VERSION = 3`. Canonical names change for every existing mass,
length and duration value (mg→ng, mm→nm, s→ns), so equal knowledge lands
on *different roots* across registry versions — which is exactly what the
version pin is for: cone-index manifests and dimension arithmetic refuse
mismatched versions loudly, never reinterpret. Coordinated steps: bump the
registry; regenerate the prelude golden root (prelude v2 — also the moment
to add heads for the new families: `pressure`, `temperature`, `energy`,
`speed`, `area`, `volume`); provide a `scripts/migrate-registry-v3` that
loads a store under v2 semantics and rewrites values (×10³/×10⁶) under v3;
re-canonicalize the ecosystem's live stores (loopmarket's fixtures, the
published demos) in the same pass. Doing this before ontodag 0.10.0 means
the break rides a normal release; doing it in a year means migrating
strangers' data.

## 7. Graph-declared units: adding units without a release — IMPLEMENTED (registry 3.2)

Peter's structural objection (2026-08-01, late): needing an OntoDAG
*release* to add a unit is not ideal — D10 minors are cheap (additive,
interoperable, a pip upgrade), but vocabulary should be data. The fix was
already agreed in principle (`SURFACE_LAYER.md` §11: shared vocabulary
merges); here is the concrete mechanism, **queued as the next work item**:

- **A unit declaration is an ordinary node**:
  `unit(lb=45359237/100000000kg)` — a spelling, defined by an exact value
  in an already-resolvable unit (grounding, possibly through other
  declarations, in a built-in anchor) — placed under the registry-known
  node `unit-declaration`, a sibling of the kind nodes. The family is the
  defining suffix's family.
- **Resolution = built-in table ∪ declarations in the graph.** The
  interpretation context stays exactly §2's rule — merged declarations
  plus `REGISTRY_VERSION` — so determinism and G1 are untouched by
  construction, because **canonical names still carry only built-in
  anchors**: declarations extend *input and rendering* vocabulary, never
  stored spellings. No registry bump, ever.
- **A pack is a prelude**: a published ontology of declaration nodes with
  a pinned golden root, adopted by explicit merge (`odag prelude`-style;
  the mechanism already exists end to end). A brewery's kegs, typography
  points under a suffix of its choosing, a country's legacy measures,
  IOPS — one merge away, zero releases.
- **Conflicts surface loudly**: the same spelling declared with a
  different factor, or clashing with a built-in suffix, is an error at
  first parse — the conflicting-kind-declaration precedent, exactly.
- **v1 scope: units in existing families only.** Declaring new *families*
  (which allocates an anchor suffix, touching canonical spellings) needs
  its own care and waits; the ~60-family table makes this the rare case.

**Implemented the same evening (registry 3.2):** `resolve_declarations`
in `dimensions.py` (fixed-point over chained definitions, loud conflicts
and unresolvables), a self-checking declared-units cache on the DAG (no
invalidation hooks — merges, puts and removes are picked up by
construction), the `units=` plumb through every parse/containment/
intersection path and the renderer, and **new-family declaration included
in v1 after all** (`unit-family(NAME)` — safe because declarations merge
with the data, so a store's vocabulary travels inside the store; a fresh
reader parses the store's values with nothing installed — tested).
`ontodag.packs` ships three packs with pinned golden roots, adopted via
`odag pack NAME`: **crypto-majors** (the top-of-market set with
chain-canonical denominations), **stablecoins**, and **fiat-iso4217**
(~150 currencies). Certificates keep verifying over stores that carry
declarations (the walk covers the declaration nodes automatically).

**The built-in/pack sorting, reconsidered per Peter (2026-08-01, late):**
the built-in table now holds *physical and digital measurement* —
timeless, universal, churn-free (259 suffixes) — plus the stack's own
tokens (BTC, ETH, BZZ/xBZZ, DAI/xDAI: top-two by dominance and the Swarm
postage pair). Everything **market-shaped or bulk** moved to packs: the
crypto majors (rankings churn — a pack version bump beats a code
release), stablecoins, and the fiat registry. The rule of thumb: *if its
importance can change, it's a pack; if only physics can change it, it's
built in.*

## 8. What if units change in the future? (Peter's question, 2026-08-01)

Four change classes, with very different pain:

- **A — Adding a unit spelling later** (furlong joins length): *painless by
  construction*, because canonical names only ever carry the **base**
  suffix — the whole non-base vocabulary lives in elaboration/rendering,
  never in stored data. Old readers keep reading every stored name; they
  merely refuse the new spelling as *input*, loudly. No root changes.
- **B — Adding a family** (pressure appears): equally painless — new
  suffixes, no existing name touched.
- **D — A standards body redefining a unit** (hasn't happened since 1959;
  2019 made things *more* exact): stored values are base-denominated, so
  they keep meaning exactly what they meant; only the input/render mapping
  moves. Painless.
- **C — Refining a family's base** (mg→ng): the *only* painful class —
  every stored name in the family changes, hence every root. Pain and
  mitigations: the migration is **mechanical, lossless, and verifiable**
  (scaling by a positive constant preserves containment, so the DAG shape
  is untouched — it is a pure rename, `new_root = migrate(old_root)` is a
  deterministic function anyone can recompute, so a signed old→new
  **migration attestation** is checkable, not trusted); version pins keep
  the old world coherent forever (old certificates verify against old
  roots under the old registry); but cross-version stores don't compare,
  and provenance subjects naming old spellings keep their meaning only
  via their pinned basis roots. Avoidable? Mostly — but not entirely,
  and here is the proof: the Japanese **shaku is exactly 10⁄33 m** — a 3
  in the denominator, so *no decimal base can ever hold it*, and folding
  it in later would force a class-C quantum-base migration of the whole
  length family.

Which motivates the structural solution:

**D9 — anchor canonical values as reduced rationals of the SI coherent
unit, and abolish bases entirely.** Canonical spelling `n/d × unit`
(denominator 1 rendered plain): `weight(3/1000kg)`, `pressure(
8896443230521/1290320000Pa)` for one psi, `length(10/33m)` for the shaku
— any exact rational unit representable on day one, forever, with **no
common-measure computation, no quantum bases, no safety margins, and no
class-C migration ever again**. Comparisons stay exact (cross-multiply);
ordering, reduction and canonical roots are untouched in kind. This
*reverses* the integers-in-tiny-base decision of 2026-07-30 — hence a
verdict, not an edit — but honors its motive better than it did: the
motive was exactness, and rationals never round, so the "finer than the
base unit" refusal simply loses its reason to exist (a per-family
precision *warning* can survive as surface policy). Costs: slightly
uglier canonical names (nobody reads them; rendering and `canon` exist),
a modestly bigger arithmetic surface in `dimensions.py` (Fraction
compare/intersect — still exact, still float-free), and marginally more
work in future ZK circuits (a value is two integers, comparisons
cross-multiply — still integer-only). If D9 is accepted, D1 and D4
dissolve (no bases to choose), the §4 table reduces to *suffix vocabulary
+ exact definitions*, and the v3 migration becomes the **last canonical-
name migration in the system's life**.

## 9. Addendum: registry 3.1 — the exactly-fixed non-SI units
(2026-08-01, Peter's follow-up; the first D10 minor in practice)

Bits and bytes (both prefix systems — decimal kB…EB and binary KiB…EiB —
all exact integers of the bit, so `1TiB ⊑ ..2TB` is arithmetic), data
rates (`bps`/`Mbps`/`MBps`…), FLOPS…EFLOPS, and the **protocol-fixed
crypto denominations**: BTC/mBTC/sat/msat, ETH/Gwei/wei, xBZZ/PLUR (the
Swarm postage currency — very much this project's own). The boundary that
matters: denominations are exact and share a family; **exchange rates are
not fixed, so currencies never share a lattice** — `BTC` vs `ETH` refuses,
which is the truth. Being purely vocabulary-additive this is registry
"3.1": every 3.x reader interoperates (D10 working as designed — no root
changed, no store touched). Extended the same evening at Peter's request
(still 3.1, pre-release): **BZZ and xBZZ as
DISTINCT families** — corrected by Peter the same evening, and the
correction is the principle: the identity test is *definitional
arithmetic*, nothing weaker. A bridge's nominal 1:1 costs a fee, takes
time, and can fail, so it is a relation between distinct assets, never an
identity — `BZZ` vs `xBZZ` refuses, like `DAI` vs `xDAI` (both included,
separately; `PLUR` lives with `xBZZ`, the token Bee actually spends).
Likewise the major **stablecoins** (USDT, USDC,
EURC, PYUSD, GUSD, TUSD — each its OWN family: a peg is a promise, not
arithmetic, so USD vs USDC refuses), and the **ISO 4217 national fiat
set** (~150 currencies, one family per code, no named subunits — decimals
are exact rationals, `0.99USD` stores as `99/100USD`). Total: 388 unit
spellings, uniqueness asserted at import.

**Audit for further BZZ-class traps (same evening): none found.** Fiat
currencies pegged *by law* (BGN's currency board, XOF/XAF's treaty rate to
the euro) are already separate families — a law is a revocable promise,
same principle as bridges — and Torr was deliberately never shipped
(Torr = 101325⁄760 Pa ≠ mmHg: the textbook near-identity pair; pack
material for whoever needs it, under its own name). What remains are
**documented conventions**, chosen once and test-pinned, not identities at
risk: `oz` is avoirdupois (troy is pack material as `ozt`), `pt`/`gal` are
US liquid (imperial ships as `ipt`/`igal`), `hp` is mechanical
(550 ft·lbf/s), `BTU` is the IT definition, `cal` thermochemical, `a` the
Julian year, `mil` the thou (not the Scandinavian mile), `mmHg` the
conventional 133.322387415 Pa, and `PLUR` lives with `xBZZ` (the token Bee
spends) though mainnet BZZ shares the decimal structure. **Second research round (Peter's request, same evening — non-crypto
first):** kitchen measures (tsp/tbsp/cup as exact US-gallon fractions),
the oil barrel and US bushel, troy ounce (`ozt` — gold is not avoirdupois),
Torr and inHg (Torr = 101325⁄760 Pa, deliberately distinct from mmHg in
the same family — the difference is real and preserved), metric horsepower
(`PS`), **Rankine** (`Ra` = 5⁄9 K — scalar from absolute zero, so
admissible where Celsius is not), keV–TeV, therms, rpm, the speed of light
(`c`, exact by definition), curie and rem, dioptres (a new `optical-power`
family — reciprocal metres are their own quantity), fathom/chain/furlong,
pm/fm/ångström/dm, and `pct`/`ppm`/`bp`/`dz` on the dimensionless family.
Crypto: the major set beyond BTC/ETH — SOL, XRP, BNB, ADA, DOGE, TRX, TON,
LINK, AVAX, XLM, DOT, LTC, BCH, XMR, UNI, ATOM, SHIB, NEAR, SUI, HBAR —
one family each, with the chain's canonical denomination named where one
exists (lamport, drop, lovelace, sun, nanoton, planck, litoshi, stroop,
uatom, piconero, tinybar). **446 suffixes total.**

**Exclusion classes the round confirmed** (each documented, none silent):
**logarithmic scales** — decibels, pH, Richter, stellar magnitude — are
not linear quantities and would need their own kind (a wall, with the
`log-dimension` idea noted); **variable "units"** — the month (calendar
handles it), Mach (condition-dependent), the IU (substance-dependent),
fuel economy (mpg vs L/100km are *reciprocal* quantities — a trap, not a
conversion); and **π strikes again**: the parsec is 648000⁄π au, so it
joins the radian among the transcendentally excluded. Still pack material
(§7): typography points (`pt` is taken by the pint — a pack picks its own
suffix), IOPS, gross/ream, historical/local currencies, and the rest we
have not thought of yet.

## 10. Verdicts needed (the review sheet)

- **D1 — Bases by computed common measure** with ×10³ margin, SI-prefixed
  names where decimal, `<unit>q` quantum names otherwise (P2/P5)?
- **D2 — Temperature kelvin-only**, affine scales refused with a teaching
  error (§2)?
- **D3 — Angle degree-based**, radian refused (§2)?
- **D4 — psi (and area/volume/speed customary) unified into single
  families via quantum bases** (§3) — accepting non-decimal bases in
  canonical names — rather than split per system?
- **D5 — Suffix ASCII conventions**: `um`/`uK`, `ohm`, `L`; and the
  siemens clash (`S` vs seconds — proposal: siemens as `sie`)?
- **D6 — Squared/cubed suffixes** `m2`, `in3` (needs the digit-in-suffix
  grammar tweak) vs spelled forms (`sqm`)?
- **D7 — Prelude v2 head list**: which of the new families get everyday
  heads out of the box?
- **D8 — Migration timing**: registry v3 + prelude v2 + migration script
  before the next release (0.10.0), ecosystem re-canonicalized in the same
  pass?
- **D9 — Rational anchoring** (§8): canonical values as reduced rationals
  of the SI coherent unit, abolishing bases and class-C migrations
  permanently — reversing the 2026-07-30 integers decision on its own
  exactness grounds. **Recommended.** (Accepting D9 moots D1 and D4;
  temperature's anchor is the kelvin with any tininess free — Peter's µK
  preference is then a rendering choice, not a storage one.)
- **D10 — Registry versioning splits major/minor**: order-affecting
  changes (anchors, kinds, arithmetic) bump the major and refuse across
  it, as today; vocabulary-additive changes (new suffixes, new families)
  bump the minor and interoperate — old readers refuse unknown spellings
  as input, loudly, but read all stored data. Makes classes A/B/D formal
  non-events.
