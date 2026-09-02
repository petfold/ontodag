"""Shipped unit packs: graph-declared vocabulary, adopted by merge.

UNITS.md §7, implemented (registry 3.2): a pack is an ordinary small
ontology of `unit-family(NAME)` / `unit(SPELLING=VALUE)` declaration nodes
under the registry node `unit-declaration`. Adopting one is an explicit,
idempotent merge (`odag pack NAME`, or `ontodag.packs.apply(dag, name)`),
exactly like the prelude — versioned, fingerprinted (golden roots in
tests/test_packs.py), and **carried inside the store**: a store's
vocabulary travels with its data, so any reader of the store can parse its
values without installing anything.

What ships as a pack vs the built-in table: the table holds physical and
digital *measurement* (timeless, universal) plus the stack's own tokens
(BTC, ETH, BZZ/xBZZ, DAI/xDAI); packs hold **market-shaped and bulk
vocabularies** — the crypto majors (rankings churn; a pack updates without
an OntoDAG release), stablecoins, and the ISO-4217 fiat registry. Each
currency is one family (exchange rates and pegs are never arithmetic);
denominations are declared where a protocol fixes them.
"""

from ontodag.core_ontology import CORE, CORE_VERSION
from ontodag.prelude import DECLARATIONS as _PRELUDE, PRELUDE_VERSION as _PRELUDE_VERSION
from ontodag.dag import OntoDAG
from ontodag.dimensions import UNIT_DECLARATION


def _crypto_majors():
    coins = {
        "SOL": {"lamport": "1/1000000000"},
        "XRP": {"drop": "1/1000000"},
        "BNB": {}, "DOGE": {}, "LINK": {}, "AVAX": {}, "BCH": {},
        "UNI": {}, "SHIB": {}, "NEAR": {}, "SUI": {},
        "ADA": {"lovelace": "1/1000000"},
        "TRX": {"sun": "1/1000000"},
        "TON": {"nanoton": "1/1000000000"},
        "DOT": {"planck": "1/10000000000"},
        "LTC": {"litoshi": "1/100000000"},
        "XLM": {"stroop": "1/10000000"},
        "ATOM": {"uatom": "1/1000000"},
        "XMR": {"piconero": "1/1000000000000"},
        "HBAR": {"tinybar": "1/100000000"},
    }
    declarations = []
    for coin, subunits in coins.items():
        declarations.append(f"unit-family({coin})")
        for spelling, fraction in subunits.items():
            declarations.append(f"unit({spelling}={fraction}{coin})")
    return tuple(declarations)


_STABLECOINS = ("USDT", "USDC", "EURC", "PYUSD", "GUSD", "TUSD",
                "LUSD")

_ISO4217 = (
    "AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF "
    "BMD BND BOB BRL BSD BTN BWP BYN BZD CAD CDF CHF CLP CNY COP CRC "
    "CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS "
    "GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD "
    "JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL "
    "LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR MZN NAD "
    "NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD "
    "RUB RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SYP SZL "
    "THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VES VND "
    "VUV WST XAF XCD XOF XPF YER ZAR ZMW ZWG").split()

# The stack's own tokens (PACKS.md Q10, accepted 2026-08-01: built-in =
# what physics fixes, so even these are a pack — one merge before `sat`
# works). Each asset its own family; bridges are promises, not identities
# (BZZ vs xBZZ refuses, DAI vs xDAI refuses); denominations are
# protocol-fixed.
_CRYPTO_CORE = (
    "unit-family(BTC)",
    "unit(mBTC=1/1000BTC)",
    "unit(sat=1/100000000BTC)",
    "unit(msat=1/100000000000BTC)",
    "unit-family(ETH)",
    "unit(Gwei=1/1000000000ETH)",
    "unit(wei=1/1000000000000000000ETH)",
    "unit-family(BZZ)",                      # Ethereum mainnet token
    "unit-family(xBZZ)",                     # the Gnosis token Bee spends
    "unit(PLUR=1/10000000000000000xBZZ)",    # postage is PLUR of xBZZ
    "unit-family(DAI)",
    "unit-family(xDAI)",                     # Gnosis Chain's native coin
)

# name -> (version, entries). An entry is either a unit-declaration spelling
# (a str: `unit-family(BTC)`, filed under `unit-declaration`) or a plain
# category, `(name, parents)` — the shape `core` uses (core_ontology.py).
# Bump a pack's version when its entries change; the golden-root tests pin
# each version's fingerprint.
PACKS = {
    # pack zero: the pack that carries the interpreter's five reflection names
    # (`dimension`, `linear-dimension`, ...) — special only in that the code
    # dereferences those names; mechanically a pack like the others.
    "prelude": (_PRELUDE_VERSION, _PRELUDE),
    "core": (CORE_VERSION, CORE),
    "crypto-core": (1, _CRYPTO_CORE),
    "crypto-majors": (1, _crypto_majors()),
    "stablecoins": (1, tuple(f"unit-family({c})" for c in _STABLECOINS)),
    "fiat-iso4217": (1, tuple(f"unit-family({c})" for c in _ISO4217)),
}


def pack_entries(name):
    """The pack as `(node, parents)` pairs, whichever shape it is written in:
    a unit declaration becomes `(spelling, (unit-declaration,))`."""
    try:
        _version, entries = PACKS[name]
    except KeyError:
        raise ValueError(f"unknown pack {name!r} "
                         f"(available: {', '.join(sorted(PACKS))})") from None
    return [(e, (UNIT_DECLARATION,)) if isinstance(e, str) else (e[0], tuple(e[1]))
            for e in entries]


def is_unit_pack(name):
    """True when every entry is a unit declaration (the packs UNIT_TABLE.md
    lists); `core` is not one."""
    return all(isinstance(e, str) for e in PACKS[name][1])


def describe(name):
    """`12 declarations` or `181 categories` — for listings."""
    if is_unit_pack(name):
        return f"{len(PACKS[name][1])} declarations"
    # count what the pack introduces: an edge hung on a prelude node (core's
    # `linear-dimension ⊑ attribute`) adds a claim, not a category
    prelude_names = {n for n, _ in _PRELUDE} if name != "prelude" else set()
    return f"{sum(1 for e in PACKS[name][1] if e[0] not in prelude_names)} categories"


_SUFFIX_INDEX = None


def packs_defining(suffix):
    """Sorted names of shipped packs whose declarations define `suffix` —
    the lookup behind the teaching error for units that are one merge
    away (`5USD` before `odag pack fiat-iso4217`)."""
    global _SUFFIX_INDEX
    if _SUFFIX_INDEX is None:
        index = {}
        for pack, (_version, declarations) in PACKS.items():
            for declaration in declarations:
                if not isinstance(declaration, str):
                    continue        # a plain category defines no unit
                if declaration.startswith("unit-family("):
                    spelling = declaration[len("unit-family("):-1]
                else:
                    spelling = declaration[len("unit("):].partition("=")[0]
                index.setdefault(spelling, []).append(pack)
        _SUFFIX_INDEX = {k: sorted(v) for k, v in index.items()}
    return _SUFFIX_INDEX.get(suffix, [])


def packs_declaring_node(name):
    """Sorted names of shipped packs whose DAG contains a node called
    `name` — the lookup behind the missing-supercategory teaching error
    (PACKS.md §14, the name-level generalization of `packs_defining`).

    Deliberately exact: it answers "would this name exist after adopting
    the pack", never "does the pack mention something similar". For the
    unit packs it fires only on `unit-declaration` and the declaration
    spellings themselves (`unit(BTC=…)`) — hinting `odag pack crypto-core`
    at someone who wrote `put x BTC` would not make `BTC` a node, and a
    teaching error must never teach a falsehood. Since `core` (2026-09-02)
    it fires for real categories: `put report.pdf invoice` before adoption
    says which pack brings `invoice`."""
    matches = [pack for pack in PACKS
               if (name == UNIT_DECLARATION and is_unit_pack(pack))
               or any(node == name for node, _parents in pack_entries(pack))]
    return sorted(matches)


def presumes_prelude(name) -> bool:
    """Does pack `name` hang anything from a prelude node?"""
    prelude_names = {n for n, _ in pack_entries("prelude")}
    return any(n in prelude_names or any(p in prelude_names for p in parents)
               for n, parents in pack_entries(name))


def pack_dag(name) -> OntoDAG:
    """The pack as a fresh OntoDAG, ready to merge into any store."""
    entries = pack_entries(name)
    dag = OntoDAG()
    if is_unit_pack(name):
        dag.put(UNIT_DECLARATION, [])
    if name != "prelude" and presumes_prelude(name):
        # Dependencies ship as closure: a pack whose parents name the
        # prelude's nodes (core: `linear-dimension ⊑ attribute`; a science
        # pack declaring `force ⊑ linear-dimension`) gets pack zero first.
        for node, parents in pack_entries("prelude"):
            dag.put(node, list(parents)) if node not in dag.nodes else None
        for node, parents in pack_entries("prelude"):
            if parents:
                dag.put(node, list(parents))
    # Order-free by I3 — but a parent must exist before its child is put,
    # and `core` is written by branch, not topologically; so create every
    # node first, then the edges (put on an existing node adds edges).
    for node, _parents in entries:
        if node not in dag.nodes:
            dag.put(node, [])
    for node, parents in entries:
        if parents:
            dag.put(node, list(parents))
    return dag


def apply(dag, name) -> None:
    """Merge pack `name` into `dag`. Idempotent (merge semantics), and the
    vocabulary then travels with the store."""
    dag.merge(pack_dag(name))
