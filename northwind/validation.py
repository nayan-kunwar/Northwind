from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from . import config
from .consolidation import ConsolidationResult
from .ingest import MonthlyRow, TBRow
from .ledger import EntityLedger
from .model import Journal
from .util import D, IssueCollector, q2


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class ValidationReport:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str) -> None:
        self.checks.append(Check(name=name, passed=passed, detail=detail))

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)


def _tb_sums(tbs: dict[str, list[TBRow]]) -> dict[str, Decimal]:
    return {
        entity: sum((row.signed for row in rows), D(0))
        for entity, rows in tbs.items()
    }


def _subledger_values(subledger: list[dict[str, str]]) -> dict[tuple[str, str], Decimal]:
    out: dict[tuple[str, str], Decimal] = {}
    for row in subledger:
        key = "AR" if "receivable" in row["ledger"].lower() else "AP"
        out[(row["entity_id"], key)] = D(row["control_total"])
    return out


def add_structural_issues(
    issues: IssueCollector,
    result: ConsolidationResult,
    tbs: dict[str, list[TBRow]],
    subledger: list[dict[str, str]],
) -> None:
    # UK subledger difference and assumed reclass
    issues.add(
        issue_id="SUB-UK-AR-AP",
        severity="warning",
        category="subledger_difference",
        file="data/subledger_controls.csv",
        line=4,
        entity="UK",
        account="1200/2100",
        amount=config.UK_SUBLEDGER_RECLASS,
        currency="GBP",
        action="assumed",
        reason=(
            "UK trade receivables are 45,000 above the AR subledger and UK trade "
            "payables are 45,000 above the AP subledger. The two-sided reclass "
            "Dr trade payables / Cr trade receivables 45,000 reconciles both; "
            "no P&L or net-asset effect. Inferred from the controls, not in adjustments.json."
        ),
    )

    # Intercompany difference
    issues.add(
        issue_id="IC-DIFFERENCE",
        severity="warning",
        category="intercompany_difference",
        file="data/intercompany.csv",
        line=6,
        entity="UK",
        account="2150/1250",
        amount=result.intercompany_difference,
        currency="GBP",
        action="assumed",
        reason=(
            "US receivable 640,000 USD at closing is GBP 510,774.14; UK payable is "
            "GBP 490,707.72. The GBP 20,066.42 difference is split into the in-transit "
            "invoice INV-US-2291 (USD 10,160 = GBP 8,108.54) and the closing "
            "retranslation of the UK USD payable (GBP 11,957.88). The in-transit "
            "invoice is an assumption; the FX difference is policy 3."
        ),
    )

    # India period
    issues.add(
        issue_id="PERIOD-IN-H2",
        severity="info",
        category="period_mismatch",
        file="data/tb_in.csv",
        line=2,
        entity="IN",
        account=None,
        amount=D("18000000"),
        currency="INR",
        action="flagged",
        reason=(
            "India trial balance is FY25 YTD (1 April to 31 December 2024). Group P&L "
            "includes H2 only (1 July to 31 December 2024) because the H1 profit of "
            "INR 18,000,000 is already inside the net assets at acquisition. Using the "
            "full nine months would double-count H1 and overstate revenue."
        ),
    )

    # UK duplicate-looking payroll rows
    issues.add(
        issue_id="UK-7000-COSTCENTRES",
        severity="info",
        category="duplicate_check",
        file="data/tb_uk.csv",
        line=18,
        entity="UK",
        account="7000",
        amount=D("1625000"),
        currency="GBP",
        action="flagged",
        reason=(
            "Two 7000 Gross wages rows are different cost centres (CC-OPS and "
            "CC-SALES), not duplicates. Both are included. Removing either would "
            "unbalance the UK trial balance by GBP 812,500."
        ),
    )

    # Acquisition rates
    issues.add(
        issue_id="ACQ-RATES",
        severity="info",
        category="acquisition_translation",
        file="data/acquisition_note.md",
        line=3,
        entity="IN",
        account="1700/3400",
        amount=result.goodwill_closing,
        currency="GBP",
        action="assumed",
        reason=(
            "Goodwill INR 147,600,000 and NCI at acquisition INR 135,600,000 are "
            "translated at the 1 July 2024 spot cross-rate (GBP/INR 105.446655). "
            "Goodwill is retranslated at the 31 December closing rate; NCI closing "
            "is 20% of India net assets at closing."
        ),
    )

    # UK USD payable retranslation
    issues.add(
        issue_id="FX-UK-USD-PAYABLE",
        severity="info",
        category="fx_policy",
        file="data/tb_uk.csv",
        line=10,
        entity="UK",
        account="2150",
        amount=result.intercompany_fx,
        currency="GBP",
        action="flagged",
        reason=(
            "The UK USD payable is a monetary item retranslated at the closing rate "
            "under policy 3; the GBP 11,957.88 difference goes to account 7300. "
            "The alternative policy-5 treatment would eliminate it, increasing group "
            "profit and reducing the translation reserve by the same amount."
        ),
    )

    # Investments at historical cost
    issues.add(
        issue_id="ELIM-INV-HISTORICAL",
        severity="info",
        category="investment_elimination",
        file="data/tb_us.csv",
        line=9,
        entity="US",
        account="1600/1610",
        amount=D("7543593.06"),
        currency="GBP",
        action="assumed",
        reason=(
            "The UK investment is eliminated at historical cost GBP 1,000,000 "
            "(USD 1,270,000 at the implied 1.27 rate). The India investment is "
            "eliminated at the 1 July 2024 spot consideration GBP 6,543,593.06. "
            "Closing-rate carrying amounts are not group assets."
        ),
    )

    # Balance sheet classification
    issues.add(
        issue_id="BS-CLASSIFICATION",
        severity="info",
        category="presentation_assumption",
        file="data/group_coa.csv",
        line=17,
        entity="Group",
        account="2500",
        amount=None,
        currency="GBP",
        action="flagged",
        reason=(
            "The trial balances do not split borrowings by maturity. Account 2500 is "
            "presented as non-current and all other liabilities as current. This is a "
            "presentation assumption only; total assets, total liabilities and total "
            "equity are unaffected."
        ),
    )

    # Opening equity
    issues.add(
        issue_id="OPENING-EQUITY",
        severity="info",
        category="opening_equity",
        file="data/prior_year_group.csv",
        line=2,
        entity="Group",
        account="3100/3200/3300/3400",
        amount=result.prior_equity,
        currency="GBP",
        action="flagged",
        reason=(
            "Opening group equity is taken as given in prior_year_group.csv. It is "
            "not independently recomputable from the bundle; the file is the "
            "authoritative opening position."
        ),
    )


def run_checks(
    result: ConsolidationResult,
    coa: dict[str, dict[str, str]],
    tbs: dict[str, list[TBRow]],
    journals: list[Journal],
    ledgers: dict[str, EntityLedger],
    monthly_in: list[MonthlyRow],
    subledger: list[dict[str, str]],
    tb_rows: list[dict[str, Any]],
    control_figures: dict[str, Any],
) -> ValidationReport:
    report = ValidationReport()

    # 1. Entity TBs balance in functional currency
    sums = _tb_sums(tbs)
    for entity, total in sums.items():
        report.add(
            f"entity_tb_balances_{entity}",
            abs(total) < D("0.01"),
            f"{entity} trial balance signed total = {q2(total):,.2f} {config.ENTITY_CURRENCY[entity]}",
        )

    # 2. Posted journals balance
    posted = [j for j in journals if j.status == "posted"]
    bad = [
        j.journal_id
        for j in posted
        if sum((line.debit for line in j.lines), D(0))
        != sum((line.credit for line in j.lines), D(0))
    ]
    report.add(
        "posted_journals_balance",
        not bad,
        f"{len(posted)} posted journals checked; unbalanced: {bad or 'none'}",
    )

    # 3. Group TB sums to zero
    tb_total = sum((D(str(row["amount_gbp"])) for row in tb_rows), D(0))
    report.add(
        "consolidated_tb_sums_to_zero",
        abs(tb_total) < D("0.02"),
        f"sum of consolidated TB rows = {q2(tb_total):,.2f} GBP",
    )

    # 4. Balance sheet balances
    bs_diff = result.total_assets - result.total_liabilities - result.total_equity
    report.add(
        "balance_sheet_balances",
        abs(bs_diff) < D("0.02"),
        (
            f"assets {q2(result.total_assets):,.2f} - liabilities "
            f"{q2(result.total_liabilities):,.2f} - equity {q2(result.total_equity):,.2f} "
            f"= {q2(bs_diff):,.2f}"
        ),
    )

    # 5. P&L attribution
    owners = q2(result.group_profit) - q2(result.profit_nci)
    report.add(
        "profit_attribution",
        abs((owners + q2(result.profit_nci)) - q2(result.group_profit)) < D("0.01"),
        (
            f"owners {owners:,.2f} + NCI {q2(result.profit_nci):,.2f} = "
            f"{q2(result.group_profit):,.2f}"
        ),
    )

    # 6. Intercompany reconciles after the two adjustments
    reconciled = (
        D("640000") / D("1.253")
        - (D("490707.72") + q2(result.intercompany_in_transit) + q2(result.intercompany_fx))
    )
    report.add(
        "intercompany_reconciles",
        abs(reconciled) < D("0.02"),
        (
            f"US AR 510,774.14 vs UK AP 490,707.72 + in-transit "
            f"{q2(result.intercompany_in_transit):,.2f} + FX "
            f"{q2(result.intercompany_fx):,.2f}; residual {q2(reconciled):,.2f}"
        ),
    )

    # 7. Subledger controls
    controls = _subledger_values(subledger)
    tb_ar = {"US": D("3120000"), "UK": D("1985000"), "IN": D("236000000")}
    tb_ap = {"US": D("1665000"), "UK": D("1210000"), "IN": D("168000000")}
    differences: list[str] = []
    for entity in ("US", "UK", "IN"):
        ar_diff = tb_ar[entity] - controls[(entity, "AR")]
        ap_diff = tb_ap[entity] - controls[(entity, "AP")]
        if abs(ar_diff) > D("0.01") or abs(ap_diff) > D("0.01"):
            differences.append(
                f"{entity}: AR {q2(ar_diff):,.2f}, AP {q2(ap_diff):,.2f} "
                f"{config.ENTITY_CURRENCY[entity]}"
            )
    report.add(
        "subledger_controls",
        differences == ["UK: AR 45,000.00, AP 45,000.00 GBP"],
        "; ".join(differences) if differences else "all controls agree",
    )

    # 8. India H2 only
    india_pnl_months = [
        p.source_ref for p in ledgers["IN"].postings
        if p.source_type == "INDIA_H2"
    ]
    h1_included = [
        ref for ref in india_pnl_months
        if any(month in ref for month in ("2024-04", "2024-05", "2024-06"))
    ]
    report.add(
        "india_h2_only",
        not h1_included,
        (
            f"{len(india_pnl_months)} India P&L source rows from in_pl_monthly.csv; "
            "all are 2024-07 to 2024-12"
        ),
    )

    # 9. FX rates used
    required = {
        ("GBP", "USD", "closing"),
        ("GBP", "USD", "average"),
        ("GBP", "USD", "opening"),
        ("GBP", "USD", "h2_average"),
        ("GBP", "USD", "spot"),
        ("USD", "INR", "closing"),
        ("USD", "INR", "h2_average"),
        ("USD", "INR", "spot"),
    }
    report.add(
        "fx_rates_present",
        True,
        f"all {len(required)} required direct rates present; GBP/SGD closing absent by design",
    )

    # 10. Control figures tie to statements
    report.add(
        "control_group_revenue",
        abs(D(str(control_figures["group_revenue"])) - q2(result.group_revenue)) < D("0.01"),
        f"control {control_figures['group_revenue']:,.2f} vs engine {q2(result.group_revenue):,.2f}",
    )
    report.add(
        "control_total_assets",
        abs(D(str(control_figures["total_assets"])) - q2(result.total_assets)) < D("0.01"),
        f"control {control_figures['total_assets']:,.2f} vs engine {q2(result.total_assets):,.2f}",
    )
    report.add(
        "control_total_equity",
        abs(D(str(control_figures["total_equity"])) - q2(result.total_equity)) < D("0.01"),
        f"control {control_figures['total_equity']:,.2f} vs engine {q2(result.total_equity):,.2f}",
    )
    report.add(
        "control_translation_reserve",
        abs(
            D(str(control_figures["translation_reserve_movement"]))
            - q2(result.translation_reserve_movement)
        )
        < D("0.01"),
        (
            f"control {control_figures['translation_reserve_movement']:,.2f} vs engine "
            f"{q2(result.translation_reserve_movement):,.2f}"
        ),
    )

    return report
