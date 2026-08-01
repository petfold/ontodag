# The Unit Table (generated — do not edit)

Registry **3.2**. Built-in suffixes: **247** —
physical and digital measurement only (PACKS.md Q10): anything
market-shaped lives in packs, listed at the bottom. Factors are exact
rationals of each family's anchor (bold). Regenerate with the snippet
in the commit that produced this file.

| family | anchor | suffixes (ascending) |
|---|---|---|
| absorbed-dose | `Gy` | uGy, mGy, **Gy** |
| amount | `mol` | pmol, nmol, umol, mmol, **mol** |
| angle | `deg` | mas, arcsec, arcmin, grad, **deg**, turn |
| area | `m2` | mm2, cm2, in2, ft2, yd2, **m2**, ac, ha, km2, mi2 |
| capacitance | `F` | pF, nF, uF, mF, **F** |
| catalytic-activity | `kat` | nkat, ukat, **kat** |
| charge | `C` | pC, nC, uC, mC, **C**, mAh, Ah |
| compute-rate | `FLOPS` | **FLOPS**, MFLOPS, GFLOPS, TFLOPS, PFLOPS, EFLOPS |
| conductance | `sie` | usie, msie, **sie** |
| count | `(bare number)` | ppm, bp, pct, **(bare)**, dz |
| current | `A` | pA, nA, uA, mA, **A**, kA |
| data-rate | `bps` | **bps**, Bps, kbps, kBps, Mbps, MBps, Gbps, GBps, Tbps |
| dose-equivalent | `Sv` | uSv, mSv, rem, **Sv** |
| duration | `s` | ns, us, ms, **s**, min, h, d, wk, a |
| energy | `J` | eV, keV, MeV, GeV, TeV, **J**, cal, kJ, BTU, Wh, kcal, MJ, kWh, thm, GJ |
| flux-density | `T` | uT, mT, **T** |
| force | `N` | uN, mN, **N**, lbf, kN |
| frequency | `Hz` | uHz, mHz, rpm, **Hz**, kHz, MHz, GHz |
| illuminance | `lx` | ulx, mlx, **lx** |
| inductance | `H` | nH, uH, mH, **H** |
| information | `bit` | b, **bit**, B, kbit, kB, KiB, Mbit, MB, MiB, Gbit, GB, GiB, Tbit, TB, TiB, PB, PiB, EB, EiB |
| length | `m` | fm, pm, angstrom, nm, um, mil, mm, cm, in, dm, ft, yd, **m**, ftm, ch, fur, km, mi, nmi, au, ly |
| luminous-flux | `lm` | ulm, mlm, **lm** |
| luminous-intensity | `cd` | ucd, mcd, **cd** |
| magnetic-flux | `Wb` | nWb, uWb, mWb, **Wb** |
| mass | `kg` | ng, ug, mg, gr, ct, g, oz, ozt, lb, **kg**, st, cwt, ust, t, lt |
| optical-power | `dpt` | **dpt** |
| power | `W` | uW, mW, **W**, PS, hp, kW, MW, GW |
| pressure | `Pa` | **Pa**, hPa, mbar, Torr, mmHg, kPa, inHg, psi, bar, atm, MPa |
| radioactivity | `Bq` | **Bq**, kBq, MBq, GBq, Ci |
| resistance | `ohm` | uohm, mohm, **ohm**, kohm, Mohm |
| speed | `mps` | kmh, fps, mph, kn, **mps**, c |
| temperature | `K` | uK, mK, Ra, **K** |
| voltage | `V` | uV, mV, **V**, kV, MV |
| volume | `m3` | uL, mL, tsp, tbsp, in3, ifloz, floz, cup, pt, ipt, qt, L, iqt, gal, igal, ft3, bu, bbl, **m3** |

## The packs (adopt with `odag pack NAME`)

### crypto-core v1 — 6 families, 6 named subunits

`BTC`, `ETH`, `BZZ`, `xBZZ`, `DAI`, `xDAI`

Subunits: `mBTC=1/1000BTC`, `sat=1/100000000BTC`, `msat=1/100000000000BTC`, `Gwei=1/1000000000ETH`, `wei=1/1000000000000000000ETH`, `PLUR=1/10000000000000000xBZZ`

### crypto-majors v1 — 20 families, 11 named subunits

`SOL`, `XRP`, `BNB`, `DOGE`, `LINK`, `AVAX`, `BCH`, `UNI`, `SHIB`, `NEAR`, `SUI`, `ADA`, `TRX`, `TON`, `DOT`, `LTC`, `XLM`, `ATOM`, `XMR`, `HBAR`

Subunits: `lamport=1/1000000000SOL`, `drop=1/1000000XRP`, `lovelace=1/1000000ADA`, `sun=1/1000000TRX`, `nanoton=1/1000000000TON`, `planck=1/10000000000DOT`, `litoshi=1/100000000LTC`, `stroop=1/10000000XLM`, `uatom=1/1000000ATOM`, `piconero=1/1000000000000XMR`, `tinybar=1/100000000HBAR`

### fiat-iso4217 v1 — 154 families, 0 named subunits

`AED`, `AFN`, `ALL`, `AMD`, `ANG`, `AOA`, `ARS`, `AUD`, `AWG`, `AZN`, `BAM`, `BBD`, `BDT`, `BGN`, `BHD`, `BIF`, `BMD`, `BND`, `BOB`, `BRL`, `BSD`, `BTN`, `BWP`, `BYN`, `BZD`, `CAD`, `CDF`, `CHF`, `CLP`, `CNY`, `COP`, `CRC`, `CUP`, `CVE`, `CZK`, `DJF`, `DKK`, `DOP`, `DZD`, `EGP`, `ERN`, `ETB`, `EUR`, `FJD`, `FKP`, `GBP`, `GEL`, `GHS`, `GIP`, `GMD`, `GNF`, `GTQ`, `GYD`, `HKD`, `HNL`, `HTG`, `HUF`, `IDR`, `ILS`, `INR`, `IQD`, `IRR`, `ISK`, `JMD`, `JOD`, `JPY`, `KES`, `KGS`, `KHR`, `KMF`, `KPW`, `KRW`, `KWD`, `KYD`, `KZT`, `LAK`, `LBP`, `LKR`, `LRD`, `LSL`, `LYD`, `MAD`, `MDL`, `MGA`, `MKD`, `MMK`, `MNT`, `MOP`, `MRU`, `MUR`, `MVR`, `MWK`, `MXN`, `MYR`, `MZN`, `NAD`, `NGN`, `NIO`, `NOK`, `NPR`, `NZD`, `OMR`, `PAB`, `PEN`, `PGK`, `PHP`, `PKR`, `PLN`, `PYG`, `QAR`, `RON`, `RSD`, `RUB`, `RWF`, `SAR`, `SBD`, `SCR`, `SDG`, `SEK`, `SGD`, `SHP`, `SLE`, `SOS`, `SRD`, `SSP`, `STN`, `SYP`, `SZL`, `THB`, `TJS`, `TMT`, `TND`, `TOP`, `TRY`, `TTD`, `TWD`, `TZS`, `UAH`, `UGX`, `USD`, `UYU`, `UZS`, `VES`, `VND`, `VUV`, `WST`, `XAF`, `XCD`, `XOF`, `XPF`, `YER`, `ZAR`, `ZMW`, `ZWG`

### stablecoins v1 — 6 families, 0 named subunits

`USDT`, `USDC`, `EURC`, `PYUSD`, `GUSD`, `TUSD`

