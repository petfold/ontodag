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

# name -> (version, declaration node names). Bump a pack's version when its
# declarations change; the golden-root tests pin each version's fingerprint.
PACKS = {
    "crypto-core": (1, _CRYPTO_CORE),
    "crypto-majors": (1, _crypto_majors()),
    "stablecoins": (1, tuple(f"unit-family({c})" for c in _STABLECOINS)),
    "fiat-iso4217": (1, tuple(f"unit-family({c})" for c in _ISO4217)),
}


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
                if declaration.startswith("unit-family("):
                    spelling = declaration[len("unit-family("):-1]
                else:
                    spelling = declaration[len("unit("):].partition("=")[0]
                index.setdefault(spelling, []).append(pack)
        _SUFFIX_INDEX = {k: sorted(v) for k, v in index.items()}
    return _SUFFIX_INDEX.get(suffix, [])


def pack_dag(name) -> OntoDAG:
    """The pack as a fresh OntoDAG, ready to merge into any store."""
    try:
        _version, declarations = PACKS[name]
    except KeyError:
        raise ValueError(f"unknown pack {name!r} "
                         f"(available: {', '.join(sorted(PACKS))})") from None
    dag = OntoDAG()
    dag.put(UNIT_DECLARATION, [])
    for declaration in declarations:
        dag.put(declaration, [UNIT_DECLARATION])
    return dag


def apply(dag, name) -> None:
    """Merge pack `name` into `dag`. Idempotent (merge semantics), and the
    vocabulary then travels with the store."""
    dag.merge(pack_dag(name))
