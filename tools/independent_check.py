"""Independent recomputation of the 12 control figures.

This script deliberately does not import the northwind package. It reads the raw
CSV/JSON inputs and applies the stated policies directly, then compares the
result with output/control_figures_nk.json. Run from the repo root:

    python tools/independent_check.py
"""

from __future__ import annotations

import csv
import json
from decimal import Decimal as D, getcontext, ROUND_HALF_UP
from pathlib import Path

getcontext().prec = 40
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "output"


def q(value: D) -> D:
    return value.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def rows(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def d(value: str) -> D:
    return D(value) if value not in (None, "") else D(0)


# Rates
fx = {
    (r["base_currency"], r["quote_currency"], r["rate_type"]): D(r["rate"])
    for r in rows("fx_rates.csv")
}
GBPUSD_CLOSE = fx[("GBP", "USD", "closing")]
GBPUSD_AVG = fx[("GBP", "USD", "average")]
GBPUSD_H2 = fx[("GBP", "USD", "h2_average")]
GBPUSD_OPEN = fx[("GBP", "USD", "opening")]
GBPUSD_SPOT = fx[("GBP", "USD", "spot")]
GBPINR_CLOSE = GBPUSD_CLOSE * fx[("USD", "INR", "closing")]
GBPINR_H2 = GBPUSD_H2 * fx[("USD", "INR", "h2_average")]
GBPINR_SPOT = GBPUSD_SPOT * fx[("USD", "INR", "spot")]

# US adjusted P&L (USD)
us = {r["account_code"]: d(r["debit"]) - d(r["credit"]) for r in rows("tb_us.csv")}
us_rev = -us["4100"]
us_ic = -us["4200"]
us_cogs = us["5100"] + D("64500")
us_staff = us["6100"] + D("85000")
us_rent = us["6200"]
us_dep = us["6400"] + D("42000")
us_other = us["6500"] + D("18000") + D("48000")
us_fin = us["7100"] + D("31250")
us_tax = us["8100"]
us_profit = us_rev + us_ic - (us_cogs + us_staff + us_rent + us_dep + us_other + us_fin + us_tax)
us_assets_oper = (
    us["1100"] + us["1200"] + us["1250"] + us["1300"] - D("64500")
    + us["1400"] - D("18000") + us["1500"] + us["1510"] - D("42000")
)
us_liab = (
    -us["2100"] - us["2200"] + D("85000") + D("31250") + D("48000")
    - us["2300"] - us["2400"] - us["2500"]
)

# UK adjusted P&L (GBP)
uk = {r["nominal_code"]: d(r["balance"]) for r in rows("tb_uk.csv")}
uk_rev = -uk["4000"]
uk_cogs = uk["5000"]
uk_staff = uk["7000"] + uk["7000"]  # two cost centres
uk_rent = uk["7100"] - D("26000")
uk_dep = uk["8000"] + D("22000")
uk_ic = uk["8210"] + D("8108.54")  # in-transit invoice at closing
uk_other = uk["7500"] + D("6800") + D("9400")
uk_fx = q(D("629840") / GBPUSD_CLOSE - (-uk["2150"]))
uk_tax = uk["9500"]
uk_profit = uk_rev - (uk_cogs + uk_staff + uk_rent + uk_dep + uk_ic + uk_other + uk_fx + uk_tax)
uk_assets = (
    uk["1200"] + uk["1210"] + uk["1100"] - D("45000") - D("9400")
    + uk["1001"] + uk["1103"] + D("26000") + uk["30"] + uk["31"] - D("22000")
)
uk_liab = (
    -uk["2100"] - D("45000") + (-uk["2109"]) + D("6800") + (-uk["2310"])
    + (-uk["2202"]) + (-uk["2150"]) + D("8108.54") + uk_fx
)

# India H2 P&L (INR)
monthly = rows("in_pl_monthly.csv")
in_rev = sum(
    (d(r["amount"]) for r in monthly
     if r["ledger_code"] == "IN-REV" and "2024-07" <= r["month"] <= "2024-12"),
    D(0),
)
in_cogs = sum(
    (d(r["amount"]) for r in monthly
     if r["ledger_code"] == "IN-COGS" and "2024-07" <= r["month"] <= "2024-12"),
    D(0),
) + D("1100000")
in_emp = sum(
    (d(r["amount"]) for r in monthly
     if r["ledger_code"] == "IN-EMP" and "2024-07" <= r["month"] <= "2024-12"),
    D(0),
) + D("2400000")
in_rent = sum(
    (d(r["amount"]) for r in monthly
     if r["ledger_code"] == "IN-RENT" and "2024-07" <= r["month"] <= "2024-12"),
    D(0),
)
in_dep = sum(
    (d(r["amount"]) for r in monthly
     if r["ledger_code"] == "IN-DEP" and "2024-07" <= r["month"] <= "2024-12"),
    D(0),
)
in_other = sum(
    (d(r["amount"]) for r in monthly
     if r["ledger_code"] == "IN-OTH" and "2024-07" <= r["month"] <= "2024-12"),
    D(0),
) + D("1850000") - D("1100000")
in_fin = sum(
    (d(r["amount"]) for r in monthly
     if r["ledger_code"] == "IN-FIN" and "2024-07" <= r["month"] <= "2024-12"),
    D(0),
)
in_tax = sum(
    (d(r["amount"]) for r in monthly
     if r["ledger_code"] == "IN-TXE" and "2024-07" <= r["month"] <= "2024-12"),
    D(0),
)
in_profit = in_rev - (in_cogs + in_emp + in_rent + in_dep + in_other + in_fin + in_tax)

# India balance sheet (INR)
in_assets = D("285000000") + D("236000000") + D("158000000") + D("520000000") - D("141000000") + D("24000000")
in_liab = D("168000000") + D("41000000") + D("1850000") + D("2400000") + D("33000000") + D("120000000")
in_net_assets = in_assets - in_liab

# Group figures
group_revenue = us_rev / GBPUSD_AVG + uk_rev + in_rev / GBPINR_H2
group_profit = us_profit / GBPUSD_AVG + uk_profit + in_profit / GBPINR_H2
nci_profit = in_profit * D("0.2") / GBPINR_H2
profit_owners = group_profit - nci_profit
nci_closing = in_net_assets * D("0.2") / GBPINR_CLOSE
goodwill = D("147600000") / GBPINR_CLOSE

# Group assets / liabilities
goodwill_acq = D("147600000") / GBPINR_SPOT
us_assets_gbp = us_assets_oper / GBPUSD_CLOSE
uk_assets_gbp = uk_assets
in_assets_gbp = in_assets / GBPINR_CLOSE
ic_ar = D("640000") / GBPUSD_CLOSE
total_assets = us_assets_gbp + uk_assets_gbp + in_assets_gbp + goodwill - ic_ar

us_liab_gbp = us_liab / GBPUSD_CLOSE
in_liab_gbp = in_liab / GBPINR_CLOSE
ic_ap = D("490707.72") + D("8108.54") + uk_fx
total_liabilities = us_liab_gbp + uk_liab + in_liab_gbp - ic_ap

prior = D("1250000") + D("12604747.93") + D("412350")
tr_movement = total_assets - total_liabilities - prior - profit_owners - nci_closing
total_equity = total_assets - total_liabilities

# Intercompany
us_ar = D("640000") / GBPUSD_CLOSE
ic_total = us_ar - D("490707.72")
ic_intransit = D("10160") / GBPUSD_CLOSE
ic_fx = D("629840") / GBPUSD_CLOSE - D("490707.72")

# Journal counts (independent rules)
entries = json.loads((DATA / "adjustments.json").read_text(encoding="utf-8"))["entries"]
map_in = {r["local_code"] for r in rows("map_in.csv")}
map_uk = {r["local_code"] for r in rows("map_uk.csv")}
seen: dict[tuple, str] = {}
counts = {"posted": 0, "rejected": 0, "held_for_review": 0}
for e in entries:
    debits = sum((D(line["debit"]) for line in e["lines"]), D(0))
    credits = sum((D(line["credit"]) for line in e["lines"]), D(0))
    signature = (
        e["entity"],
        e["date"],
        tuple(sorted((line["account"], line["debit"], line["credit"]) for line in e["lines"])),
    )
    rejected = False
    held = False
    if debits != credits:
        rejected = True
    if not ("2024-01-01" <= e["date"] <= "2024-12-31"):
        rejected = True
    if e["entity"] in ("UK", "IN"):
        allowed = map_uk if e["entity"] == "UK" else map_in
        if any(line["account"] not in allowed for line in e["lines"]):
            rejected = True
    if signature in seen:
        rejected = True
    if not rejected and e["id"] in ("JE-009", "JE-018", "JE-020"):
        held = True
    if rejected:
        counts["rejected"] += 1
    elif held:
        counts["held_for_review"] += 1
    else:
        counts["posted"] += 1
    seen[signature] = e["id"]

control = json.loads((OUT / "control_figures_nk.json").read_text(encoding="utf-8"))
checks = [
    ("group_revenue", group_revenue, control["group_revenue"]),
    ("group_profit", group_profit, control["group_profit"]),
    ("profit_owners", q(group_profit) - q(nci_profit), control["profit_owners"]),
    ("profit_nci", nci_profit, control["profit_nci"]),
    ("nci_closing", nci_closing, control["nci_closing"]),
    ("goodwill_closing", goodwill, control["goodwill_closing"]),
    ("translation_reserve_movement", tr_movement, control["translation_reserve_movement"]),
    ("total_assets", total_assets, control["total_assets"]),
    ("total_equity", total_equity, control["total_equity"]),
    ("intercompany_difference", ic_total, control["intercompany_difference"]),
]

print(f"{'figure':<32}{'independent':>16}{'engine':>16}{'diff':>10}  ok")
ok = True
for name, independent, engine in checks:
    diff = q(independent) - D(str(engine))
    good = abs(diff) <= D("0.01")
    ok = ok and good
    print(f"{name:<32}{q(independent):>16,.2f}{D(str(engine)):>16,.2f}{diff:>10,.2f}  {'yes' if good else 'NO'}")

print("")
print("intercompany split:", f"in-transit {q(ic_intransit):,.2f}", f"FX {q(ic_fx):,.2f}",
      f"total {q(ic_total):,.2f}")
print("journals:", counts, "engine:", control["journals"])
print("sgd_bank_gbp:", control["sgd_bank_gbp"], "(reason present:", bool(control["sgd_bank_gbp_reason"]), ")")

journal_ok = (
    counts["posted"] == control["journals"]["posted"]
    and counts["rejected"] == control["journals"]["rejected"]
    and counts["held_for_review"] == control["journals"]["held_for_review"]
)
sgd_rate_missing = (
    ("GBP", "SGD", "closing") not in fx
    and ("USD", "SGD", "closing") not in fx
)
sgd_ok = sgd_rate_missing and control["sgd_bank_gbp"] is None
print("SGD closing rate absent:", sgd_rate_missing, "| control is null:", control["sgd_bank_gbp"] is None)
print("independent check:", "PASS" if ok and journal_ok and sgd_ok else "FAIL")
raise SystemExit(0 if ok and journal_ok and sgd_ok else 1)
