from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from . import config
from .ingest import Acquisition, TBRow
from .ledger import EntityLedger, Posting
from .util import D, q2


ASSET_ACCOUNTS = ("1100", "1200", "1300", "1400", "1500", "1510", "1700")
LIABILITY_ACCOUNTS = ("2100", "2200", "2300", "2400", "2500")
ZERO_ACCOUNTS = ("1250", "2150", "1600", "1610")


@dataclass
class EliminationLine:
    group_account: str
    account_name: str
    debit_gbp: Decimal
    credit_gbp: Decimal
    source_rows: str


@dataclass
class Elimination:
    elim_id: str
    description: str
    lines: list[EliminationLine]
    reason: str

    def total_debit(self) -> Decimal:
        return sum((line.debit_gbp for line in self.lines), D(0))

    def total_credit(self) -> Decimal:
        return sum((line.credit_gbp for line in self.lines), D(0))


@dataclass
class ConsolidationResult:
    group_pnl: dict[str, Decimal] = field(default_factory=dict)
    group_bs: dict[str, Decimal] = field(default_factory=dict)
    entity_profit: dict[str, Decimal] = field(default_factory=dict)
    group_revenue: Decimal = D(0)
    group_profit: Decimal = D(0)
    profit_owners: Decimal = D(0)
    profit_nci: Decimal = D(0)
    nci_closing: Decimal = D(0)
    nci_acquisition: Decimal = D(0)
    goodwill_closing: Decimal = D(0)
    goodwill_acquisition: Decimal = D(0)
    translation_reserve_movement: Decimal = D(0)
    translation_reserve_closing: Decimal = D(0)
    total_assets: Decimal = D(0)
    total_liabilities: Decimal = D(0)
    total_equity: Decimal = D(0)
    prior_equity: Decimal = D(0)
    prior_equity_lines: dict[str, Decimal] = field(default_factory=dict)
    intercompany_difference: Decimal = D(0)
    intercompany_in_transit: Decimal = D(0)
    intercompany_fx: Decimal = D(0)
    journal_counts: dict[str, int] = field(default_factory=dict)
    translation_workings: dict[str, Decimal] = field(default_factory=dict)
    eliminations: list[Elimination] = field(default_factory=list)


def build_eliminations(
    coa: dict[str, dict[str, str]],
    acquisition: Acquisition,
    india_na_acq: Decimal,
    consideration_gbp: Decimal,
    us_ic_income_gbp: Decimal,
    uk_ic_expense_gbp: Decimal,
    us_ar_gbp: Decimal,
    uk_ap_gbp: Decimal,
    nci_acq: Decimal,
    nci_profit: Decimal,
    goodwill_acq: Decimal,
    goodwill_close: Decimal,
    india_tr: Decimal,
) -> list[Elimination]:
    def name(code: str) -> str:
        return coa.get(code, {}).get("account_name", code)

    eliminations: list[Elimination] = []

    eliminations.append(
        Elimination(
            elim_id="ELIM-01",
            description="Eliminate intercompany receivable and payable",
            lines=[
                EliminationLine("2150", name("2150"), uk_ap_gbp, D(0),
                                "data/tb_us.csv:5; data/tb_uk.csv:10; data/intercompany.csv:2-10"),
                EliminationLine("1250", name("1250"), D(0), us_ar_gbp,
                                "data/tb_us.csv:5; data/tb_uk.csv:10; data/intercompany.csv:2-10"),
            ],
            reason=(
                "US receivable 640,000 USD translated at the closing rate equals the UK payable "
                "after recording the in-transit invoice and retranslating the USD payable."
            ),
        )
    )

    plug = us_ic_income_gbp - uk_ic_expense_gbp
    eliminations.append(
        Elimination(
            elim_id="ELIM-02",
            description="Eliminate intercompany management fee income and expense",
            lines=[
                EliminationLine("4200", name("4200"), us_ic_income_gbp, D(0),
                                "data/tb_us.csv:19; data/fx_rates.csv:3"),
                EliminationLine("6300", name("6300"), D(0), uk_ic_expense_gbp,
                                "data/tb_uk.csv:22; data/intercompany.csv:6"),
                EliminationLine("7300", name("7300"), D(0), plug,
                                "data/tb_us.csv:19; data/tb_uk.csv:22; group_policies.md:5"),
            ],
            reason=(
                "Intercompany income and expense are eliminated in full. The remaining "
                f"GBP {plug:,.2f} difference is the policy-5 exchange difference to account 7300."
            ),
        )
    )

    eliminations.append(
        Elimination(
            elim_id="ELIM-03",
            description="Eliminate the UK investment against UK share capital at historical cost",
            lines=[
                EliminationLine("3100", name("3100"), D("1000000"), D(0),
                                "data/tb_uk.csv:14; data/prior_year_group.csv:2"),
                EliminationLine("1600", name("1600"), D(0), D("1000000"),
                                "data/tb_us.csv:9 (USD 1,270,000 at the implied historical 1.27)"),
            ],
            reason=(
                "Wholly owned UK investment is a non-monetary asset eliminated at historical "
                "cost (GBP 1,000,000). The closing-rate carrying amount is not a group asset."
            ),
        )
    )

    eliminations.append(
        Elimination(
            elim_id="ELIM-04",
            description="Eliminate the India investment and recognise goodwill and NCI at acquisition",
            lines=[
                EliminationLine("ACQ-NA", "India net assets at acquisition", india_na_acq, D(0),
                                "data/acquisition_note.md:10-14; data/fx_rates.csv:5,10"),
                EliminationLine("1700", name("1700"), goodwill_acq, D(0),
                                "data/acquisition_note.md:6-14; data/fx_rates.csv:5,10"),
                EliminationLine("1610", name("1610"), D(0), consideration_gbp,
                                "data/tb_us.csv:10 (USD 8,274,373.43); data/acquisition_note.md:6"),
                EliminationLine("3400", name("3400"), D(0), nci_acq,
                                "data/acquisition_note.md:10-14; data/fx_rates.csv:5,10"),
            ],
            reason=(
                "Consideration INR 690m less 80% of net assets INR 678m gives goodwill "
                "INR 147.6m. NCI is 20% of net assets at acquisition, both at the spot rate."
            ),
        )
    )

    eliminations.append(
        Elimination(
            elim_id="ELIM-05",
            description="Allocate the NCI share of India profit",
            lines=[
                EliminationLine("3400", name("3400"), nci_profit, D(0),
                                "data/in_pl_monthly.csv:5-73; data/adjustments.json (posted India journals)"),
                EliminationLine("3200", name("3200"), D(0), nci_profit,
                                "data/in_pl_monthly.csv:5-73; group_policies.md:4"),
            ],
            reason="20% of India H2 profit is attributable to the non-controlling interest.",
        )
    )

    translation_loss = -india_tr
    eliminations.append(
        Elimination(
            elim_id="ELIM-06",
            description="Allocate the India translation difference between owners and NCI",
            lines=[
                EliminationLine("3300", name("3300"), translation_loss * D("0.80"), D(0),
                                "data/tb_in.csv:2-10; data/fx_rates.csv:6,11; data/acquisition_note.md"),
                EliminationLine("3400", name("3400"), translation_loss * D("0.20"), D(0),
                                "data/tb_in.csv:2-10; data/fx_rates.csv:6,11; data/acquisition_note.md"),
                EliminationLine("ACQ-NA", "India net assets translation", D(0),
                                translation_loss,
                                "data/tb_in.csv:2-10; data/fx_rates.csv:6,11"),
            ],
            reason=(
                "India net assets are translated at closing; the difference from acquisition "
                "plus H2 profit is split 80% to owners and 20% to NCI."
            ),
        )
    )

    eliminations.append(
        Elimination(
            elim_id="ELIM-07",
            description="Retranslate India goodwill at the closing rate",
            lines=[
                EliminationLine("3300", name("3300"), goodwill_acq - goodwill_close, D(0),
                                "data/acquisition_note.md:6-14; data/fx_rates.csv:6,11"),
                EliminationLine("1700", name("1700"), D(0), goodwill_acq - goodwill_close,
                                "data/acquisition_note.md:6-14; data/fx_rates.csv:6,11"),
            ],
            reason="Goodwill is held in INR and retranslated at the closing rate; the difference goes to the translation reserve.",
        )
    )

    return eliminations


def consolidate(
    coa: dict[str, dict[str, str]],
    ledgers: dict[str, EntityLedger],
    tbs: dict[str, list[TBRow]],
    acquisition: Acquisition,
    prior_year: dict[str, Decimal],
    journal_counts: dict[str, int],
    fx_rates: dict[tuple[str, str, str], Decimal],
) -> ConsolidationResult:
    result = ConsolidationResult()
    result.journal_counts = journal_counts

    # Entity profits
    for entity, ledger in ledgers.items():
        result.entity_profit[entity] = ledger.profit(coa)

    # --- Group P&L: sum all entity P&L postings, then apply the IC elimination.
    raw_pnl: dict[str, Decimal] = defaultdict(Decimal)
    for ledger in ledgers.values():
        for posting in ledger.postings:
            if coa[posting.group_account]["statement"] == "PL":
                raw_pnl[posting.group_account] += posting.amount_gbp

    us_ic_income = -raw_pnl.get("4200", D(0))  # credit balance -> positive income
    uk_ic_expense = raw_pnl.get("6300", D(0))  # debit balance -> positive expense
    ic_plug = us_ic_income - uk_ic_expense

    group_pnl = dict(raw_pnl)
    group_pnl["4200"] = D(0)
    group_pnl["6300"] = D(0)
    group_pnl["7300"] = group_pnl.get("7300", D(0)) - ic_plug
    result.group_pnl = group_pnl
    result.group_revenue = -group_pnl.get("4100", D(0))
    result.group_profit = -sum(group_pnl.values(), D(0))

    # --- NCI / goodwill / acquisition
    gbp_inr_close = fx_rates[("GBP", "USD", "closing")] * fx_rates[("USD", "INR", "closing")]
    gbp_inr_h2 = fx_rates[("GBP", "USD", "h2_average")] * fx_rates[("USD", "INR", "h2_average")]
    gbp_inr_spot = fx_rates[("GBP", "USD", "spot")] * fx_rates[("USD", "INR", "spot")]
    gbp_usd_close = fx_rates[("GBP", "USD", "closing")]
    gbp_usd_open = fx_rates[("GBP", "USD", "opening")]
    gbp_usd_avg = fx_rates[("GBP", "USD", "average")]

    india_assets_inr = sum(
        (row.signed for row in tbs["IN"] if row.code in {
            "IN-BNK-01", "IN-AR", "IN-INV", "IN-PPE", "IN-ACD", "IN-PRE"
        }),
        D(0),
    )
    india_liabilities_inr = -sum(
        (row.signed for row in tbs["IN"] if row.code in {
            "IN-AP", "IN-ACR", "IN-TAX", "IN-TL"
        }),
        D(0),
    )
    # Posted India journals add 1.85m + 2.4m INR to accruals (both H2).
    india_liabilities_inr += D("4250000")
    india_net_assets_inr = india_assets_inr - india_liabilities_inr
    result.nci_closing = india_net_assets_inr * config.INDIA_NCI_PCT / gbp_inr_close
    result.nci_acquisition = acquisition.nci_acq_inr / gbp_inr_spot
    result.goodwill_acquisition = acquisition.goodwill_inr / gbp_inr_spot
    result.goodwill_closing = acquisition.goodwill_inr / gbp_inr_close
    result.profit_nci = (
        result.entity_profit["IN"] * config.INDIA_NCI_PCT
    )
    result.profit_owners = result.group_profit - result.profit_nci

    # --- Group balance sheet
    raw_bs: dict[str, Decimal] = defaultdict(Decimal)
    for ledger in ledgers.values():
        for posting in ledger.postings:
            if coa[posting.group_account]["statement"] == "BS":
                raw_bs[posting.group_account] += posting.amount_gbp
    for account in ZERO_ACCOUNTS:
        raw_bs[account] = D(0)
    raw_bs["1700"] = result.goodwill_closing
    result.group_bs = dict(raw_bs)
    result.total_assets = sum((raw_bs.get(a, D(0)) for a in ASSET_ACCOUNTS), D(0))
    result.total_liabilities = -sum((raw_bs.get(a, D(0)) for a in LIABILITY_ACCOUNTS), D(0))
    result.total_equity = result.total_assets - result.total_liabilities

    # Prior year equity
    result.prior_equity_lines = dict(prior_year)
    result.prior_equity = sum(prior_year.values(), D(0))
    prior_tr = prior_year.get("3300", D(0))

    # Translation reserve is the balance-sheet residual.
    result.translation_reserve_movement = (
        result.total_equity
        - result.prior_equity
        - result.profit_owners
        - result.nci_closing
    )
    result.translation_reserve_closing = prior_tr + result.translation_reserve_movement

    # --- Analytical translation-reserve decomposition
    # US operating net assets exclude the two investments, which are eliminated.
    us_na_usd = sum(
        (p.source_amount for p in ledgers["US"].postings
         if p.source_currency == "USD"
         and coa[p.group_account]["statement"] == "BS"
         and p.group_account not in {"1600", "1610"}),
        D(0),
    )
    us_na_close = us_na_usd / gbp_usd_close
    us_na_open = (D("16069373.43") - D("1270000")) / gbp_usd_open
    consideration_spot = D("690000000") / gbp_inr_spot
    us_tr = us_na_close + consideration_spot - us_na_open - result.entity_profit["US"]

    india_na_acq = acquisition.net_assets_inr / gbp_inr_spot
    india_na_close = india_net_assets_inr / gbp_inr_close
    india_tr = india_na_close - india_na_acq - result.entity_profit["IN"]
    gw_tr = result.goodwill_closing - result.goodwill_acquisition
    result.translation_workings = {
        "us_parent_operating_net_assets": us_tr,
        "india_net_assets_owners_share": india_tr * D("0.80"),
        "india_goodwill_retranslation": gw_tr,
        "analytical_total": us_tr + india_tr * D("0.80") + gw_tr,
        "balance_sheet_residual": result.translation_reserve_movement,
        "rounding": result.translation_reserve_movement - (us_tr + india_tr * D("0.80") + gw_tr),
    }

    # --- Intercompany difference
    us_ar_gbp = D("640000") / gbp_usd_close
    uk_ap_booked = D("490707.72")
    result.intercompany_difference = us_ar_gbp - uk_ap_booked
    result.intercompany_in_transit = D("10160") / gbp_usd_close
    result.intercompany_fx = D("629840") / gbp_usd_close - uk_ap_booked

    # --- Eliminations
    result.eliminations = build_eliminations(
        coa=coa,
        acquisition=acquisition,
        india_na_acq=india_na_acq,
        consideration_gbp=consideration_spot,
        us_ic_income_gbp=us_ic_income,
        uk_ic_expense_gbp=uk_ic_expense,
        us_ar_gbp=us_ar_gbp,
        uk_ap_gbp=us_ar_gbp,
        nci_acq=result.nci_acquisition,
        nci_profit=result.profit_nci,
        goodwill_acq=result.goodwill_acquisition,
        goodwill_close=result.goodwill_closing,
        india_tr=india_tr,
    )

    return result
