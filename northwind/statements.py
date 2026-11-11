from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import config
from .consolidation import ConsolidationResult
from .ledger import EntityLedger
from .util import D, q2, unique_ids


def _refs(
    ledgers: dict[str, EntityLedger],
    account: str,
    extra: tuple[str, ...] = (),
) -> list[str]:
    refs: list[str] = []
    for entity, ledger in ledgers.items():
        for posting in ledger.postings:
            if posting.group_account == account:
                refs.append(f"{posting.source_ref} [{entity}]")
    refs.extend(extra)
    return unique_ids(refs)


def _line(
    account: str,
    coa: dict[str, dict[str, str]],
    amount: Decimal,
    ledgers: dict[str, EntityLedger],
    extra: tuple[str, ...] = (),
    note: str = "",
) -> dict[str, Any]:
    return {
        "account": account,
        "name": coa.get(account, {}).get("account_name", account),
        "amount_gbp": float(q2(amount)),
        "source_rows": _refs(ledgers, account, extra),
        "note": note,
    }


def build_consolidated_tb(
    result: ConsolidationResult,
    coa: dict[str, dict[str, str]],
    ledgers: dict[str, EntityLedger],
) -> list[dict[str, Any]]:
    """Pre-closing consolidated TB, debit-positive.

    The TB includes the group P&L accounts and a memo NCI profit-allocation
    line so that it sums to zero before closing. The balance sheet JSON shows
    the post-closing equity, including the NCI closing balance.
    """
    rows: list[dict[str, Any]] = []
    for account, amount in sorted(result.group_bs.items()):
        if amount == 0 and account not in {"1250", "1600", "1610", "2150"}:
            continue
        extra: tuple[str, ...] = ()
        if account == "1250":
            extra = ("ELIM-01",)
        elif account == "2150":
            extra = ("ELIM-01",)
        elif account == "1600":
            extra = ("ELIM-03",)
        elif account == "1610":
            extra = ("ELIM-04",)
        elif account == "1700":
            extra = ("data/acquisition_note.md:6-14", "ELIM-04", "ELIM-07")
        rows.append(
            {
                "group_account": account,
                "account_name": coa[account]["account_name"],
                "account_type": coa[account]["account_type"],
                "statement": "BS",
                "amount_gbp": q2(amount),
                "debit_gbp": q2(amount) if amount >= 0 else D(0),
                "credit_gbp": q2(-amount) if amount < 0 else D(0),
                "source_rows": "; ".join(_refs(ledgers, account, extra)),
            }
        )

    for account, amount in sorted(result.group_pnl.items()):
        if amount == 0:
            continue
        extra = ("ELIM-02",) if account in {"4200", "6300", "7300"} else ()
        rows.append(
            {
                "group_account": account,
                "account_name": coa[account]["account_name"],
                "account_type": coa[account]["account_type"],
                "statement": "PL",
                "amount_gbp": q2(amount),
                "debit_gbp": q2(amount) if amount >= 0 else D(0),
                "credit_gbp": q2(-amount) if amount < 0 else D(0),
                "source_rows": "; ".join(_refs(ledgers, account, extra)),
            }
        )

    equity = {
        "3100": result.prior_equity_lines.get("3100", D(0)),
        "3200": result.prior_equity_lines.get("3200", D(0)),
        "3300": result.translation_reserve_closing,
        "3400": result.nci_closing,
        "3490": -result.profit_nci,
    }
    equity_refs = {
        "3100": ("data/prior_year_group.csv:2",),
        "3200": ("data/prior_year_group.csv:3", "profit allocation: owners"),
        "3300": (
            "data/prior_year_group.csv:4",
            "translation reserve workings",
            "ELIM-06",
            "ELIM-07",
        ),
        "3400": (
            "data/acquisition_note.md:10-14",
            "ELIM-04",
            "ELIM-05",
            "ELIM-06",
        ),
        "3490": ("NCI profit allocation memo",),
    }
    for account, amount in equity.items():
        tb_amount = q2(-amount)
        rows.append(
            {
                "group_account": account,
                "account_name": (
                    "NCI share of current-year profit (memo)"
                    if account == "3490"
                    else coa[account]["account_name"]
                ),
                "account_type": "Equity",
                "statement": "BS",
                "amount_gbp": tb_amount,
                "debit_gbp": tb_amount if tb_amount > 0 else D(0),
                "credit_gbp": -tb_amount if tb_amount < 0 else D(0),
                "source_rows": "; ".join(equity_refs[account]),
            }
        )

    # The account-level rows can differ from the full-precision total by a cent
    # because each is rounded. Add a transparent presentation rounding row so
    # the TB sums to exactly zero.
    total = sum((row["amount_gbp"] for row in rows), D(0))
    if total != 0:
        rows.append(
            {
                "group_account": "3999",
                "account_name": "Rounding (presentation)",
                "account_type": "Rounding",
                "statement": "BS",
                "amount_gbp": -total,
                "debit_gbp": -total if total < 0 else D(0),
                "credit_gbp": total if total > 0 else D(0),
                "source_rows": "rounding of presented account balances",
            }
        )

    # Order: assets, liabilities, equity, then P&L (the reader can see the
    # pre-closing TB sum to zero).
    order = {"Asset": 0, "Liability": 1, "Equity": 2, "Revenue": 3, "Expense": 4}
    rows.sort(key=lambda r: (order.get(r["account_type"], 9), r["group_account"]))
    return rows


def build_balance_sheet(
    result: ConsolidationResult,
    coa: dict[str, dict[str, str]],
    ledgers: dict[str, EntityLedger],
) -> dict[str, Any]:
    def bs_line(account: str, extra: tuple[str, ...] = ()) -> dict[str, Any]:
        amount = result.group_bs.get(account, D(0))
        # Assets keep their sign; liabilities are presented as positive amounts.
        presented = amount if coa[account]["account_type"] == "Asset" else -amount
        return _line(account, coa, presented, ledgers, extra)

    non_current_assets = [
        bs_line("1500"),
        bs_line("1510"),
        bs_line("1700", ("data/acquisition_note.md:6-14", "ELIM-04", "ELIM-07")),
    ]
    current_assets = [
        bs_line("1100"),
        bs_line("1200"),
        bs_line("1300"),
        bs_line("1400"),
    ]
    current_liabilities = [
        bs_line("2100"),
        bs_line("2200"),
        bs_line("2300"),
        bs_line("2400"),
    ]
    non_current_liabilities = [bs_line("2500")]

    total_assets = result.total_assets
    total_liabilities = result.total_liabilities

    profit_owners = q2(result.group_profit) - q2(result.profit_nci)
    retained_earnings = result.prior_equity_lines.get("3200", D(0)) + profit_owners
    owners_equity = (
        result.prior_equity_lines.get("3100", D(0))
        + retained_earnings
        + result.translation_reserve_closing
    )
    total_equity_components = owners_equity + result.nci_closing
    total_equity = q2(result.total_equity)
    rounding = total_equity - total_equity_components

    equity = {
        "share_capital": {
            "account": "3100",
            "name": coa["3100"]["account_name"],
            "amount_gbp": float(q2(result.prior_equity_lines.get("3100", D(0)))),
            "source_rows": ["data/prior_year_group.csv:2"],
        },
        "retained_earnings": {
            "account": "3200",
            "name": coa["3200"]["account_name"],
            "amount_gbp": float(q2(retained_earnings)),
            "source_rows": [
                "data/prior_year_group.csv:3",
                "profit_and_loss.json: profit attributable to owners",
            ],
        },
        "translation_reserve": {
            "account": "3300",
            "name": coa["3300"]["account_name"],
            "amount_gbp": float(q2(result.translation_reserve_closing)),
            "source_rows": [
                "data/prior_year_group.csv:4",
                "changes_in_equity.json: translation reserve movement",
            ],
        },
        "equity_attributable_to_owners": {
            "amount_gbp": float(q2(owners_equity)),
        },
        "non_controlling_interest": {
            "account": "3400",
            "name": coa["3400"]["account_name"],
            "amount_gbp": float(q2(result.nci_closing)),
            "source_rows": [
                "data/acquisition_note.md:10-14",
                "ELIM-04; ELIM-05; ELIM-06",
            ],
        },
        "rounding": {
            "amount_gbp": float(q2(rounding)),
            "note": (
                "Owners' profit is presented as the residual of rounded group profit "
                "less rounded NCI profit; the full-precision share is GBP 2,744,660.3813. "
                "This 0.01 rounding line makes the equity components add to total equity."
            ),
        },
        "total_equity": {
            "amount_gbp": float(total_equity),
        },
    }

    return {
        "bundle_id": config.BUNDLE_ID,
        "entity": "Northwind Group",
        "as_of": config.FY_END,
        "currency": config.PRESENTATION_CURRENCY,
        "basis": (
            "Consolidated, translated at the rates in fx_rates.csv; GBP rounded to 2 decimals. "
            "Totals are computed at full precision; the sum of rounded lines may differ by GBP 0.01."
        ),
        "assets": {
            "non_current": non_current_assets,
            "current": current_assets,
            "total_assets": float(q2(total_assets)),
        },
        "liabilities": {
            "current": current_liabilities,
            "non_current": non_current_liabilities,
            "total_liabilities": float(q2(total_liabilities)),
        },
        "equity": equity,
        "notes": [
            "The trial balances do not split borrowings by maturity; account 2500 is presented as non-current. All other liabilities are presented as current.",
            "The SGD bank balance is carried at its booked GBP 23,010; see issues.json FX-UK-SGD-CLOSING.",
            "Totals are computed at full precision; the sum of rounded lines may differ by GBP 0.01.",
        ],
        "checks": {
            "assets_less_liabilities": float(q2(total_assets - total_liabilities)),
            "total_equity": float(q2(total_equity)),
            "difference": float(q2(total_assets - total_liabilities - total_equity)),
            "balanced": abs(total_assets - total_liabilities - total_equity) < D("0.02"),
        },
    }


def build_profit_and_loss(
    result: ConsolidationResult,
    coa: dict[str, dict[str, str]],
    ledgers: dict[str, EntityLedger],
) -> dict[str, Any]:
    revenue_by_entity: dict[str, Decimal] = {}
    for entity, ledger in ledgers.items():
        revenue_by_entity[entity] = -sum(
            (p.amount_gbp for p in ledger.postings if p.group_account == "4100"), D(0)
        )
    revenue_lines = [
        {
            "entity": entity,
            "account": "4100",
            "name": "Revenue",
            "amount_gbp": float(q2(amount)),
            "source_rows": _refs({entity: ledgers[entity]}, "4100"),
        }
        for entity, amount in revenue_by_entity.items()
    ]
    revenue_total = sum(revenue_by_entity.values(), D(0))

    def expense_line(account: str, extra: tuple[str, ...] = ()) -> dict[str, Any]:
        return _line(account, coa, result.group_pnl.get(account, D(0)), ledgers, extra)

    cogs = expense_line("5100")
    operating = [
        expense_line("6100"),
        expense_line("6200"),
        expense_line("6400"),
        expense_line("6500"),
    ]
    finance = expense_line("7100")
    fx = expense_line("7300", ("ELIM-02",))
    tax = expense_line("8100")

    gross_profit = revenue_total - D(str(cogs["amount_gbp"]))
    operating_total = sum((D(str(line["amount_gbp"])) for line in operating), D(0))
    operating_profit = gross_profit - operating_total
    finance_total = D(str(finance["amount_gbp"])) + D(str(fx["amount_gbp"]))
    profit_before_tax = operating_profit - finance_total
    tax_total = D(str(tax["amount_gbp"]))
    profit_for_year = profit_before_tax - tax_total

    profit_total = q2(result.group_profit)
    owners = profit_total - q2(result.profit_nci)
    nci = q2(result.profit_nci)
    attribution_rounding = profit_total - (owners + nci)
    pbt_less_tax = profit_before_tax - tax_total
    pnl_rounding = profit_total - pbt_less_tax

    ic_income = -sum(
        (p.amount_gbp for p in ledgers["US"].postings if p.group_account == "4200"), D(0)
    )
    ic_expense = sum(
        (p.amount_gbp for p in ledgers["UK"].postings if p.group_account == "6300"), D(0)
    )
    ic_plug = ic_income - ic_expense

    return {
        "bundle_id": config.BUNDLE_ID,
        "entity": "Northwind Group",
        "period": f"{config.FY_START} to {config.FY_END}",
        "currency": config.PRESENTATION_CURRENCY,
        "revenue": revenue_lines,
        "revenue_total": float(q2(revenue_total)),
        "cost_of_sales": cogs,
        "gross_profit": float(q2(gross_profit)),
        "operating_expenses": operating,
        "operating_expenses_total": float(q2(operating_total)),
        "operating_profit": float(q2(operating_profit)),
        "finance_costs": finance,
        "foreign_exchange": fx,
        "profit_before_tax": float(q2(profit_before_tax)),
        "income_tax": tax,
        "rounding": float(q2(pnl_rounding)),
        "profit_for_the_year": float(profit_total),
        "attributable_to": {
            "owners_of_the_parent": float(owners),
            "non_controlling_interest": float(nci),
            "rounding": float(attribution_rounding),
        },
        "eliminated": {
            "intercompany_income": float(q2(ic_income)),
            "intercompany_expense": float(q2(ic_expense)),
            "difference_to_7300": float(q2(ic_plug)),
        },
        "notes": [
            "Revenue is external revenue only; intercompany management fee income and expense are eliminated in full.",
            "The GBP 1,966.21 remaining intercompany difference is a credit to account 7300 under group policy 5.",
            "Owners' profit is the residual of the rounded group profit less rounded NCI profit; the full-precision owners' share is GBP 2,744,660.3813.",
            "A GBP 0.01 rounding line reconciles the rounded profit-before-tax less tax to the full-precision rounded profit for the year.",
        ],
    }


def build_changes_in_equity(result: ConsolidationResult) -> dict[str, Any]:
    opening_sc = q2(result.prior_equity_lines.get("3100", D(0)))
    opening_re = q2(result.prior_equity_lines.get("3200", D(0)))
    opening_tr = q2(result.prior_equity_lines.get("3300", D(0)))
    opening_nci = q2(result.prior_equity_lines.get("3400", D(0)))
    opening_total = opening_sc + opening_re + opening_tr + opening_nci

    profit_total = q2(result.group_profit)
    profit_owners = profit_total - q2(result.profit_nci)
    profit_nci = q2(result.profit_nci)

    tr_movement = q2(result.translation_reserve_movement)
    nci_translation = q2(
        result.nci_closing - result.nci_acquisition - result.profit_nci
    )
    oci_total = tr_movement + nci_translation
    nci_acquisition = q2(result.nci_acquisition)

    closing_sc = opening_sc
    closing_re = opening_re + profit_owners
    closing_tr = opening_tr + tr_movement
    closing_nci = opening_nci + nci_acquisition + profit_nci + nci_translation
    closing_total = closing_sc + closing_re + closing_tr + closing_nci
    rounding = q2(result.total_equity) - closing_total

    return {
        "bundle_id": config.BUNDLE_ID,
        "entity": "Northwind Group",
        "period": f"{config.FY_START} to {config.FY_END}",
        "currency": config.PRESENTATION_CURRENCY,
        "opening": {
            "share_capital": float(opening_sc),
            "retained_earnings": float(opening_re),
            "translation_reserve": float(opening_tr),
            "non_controlling_interest": float(opening_nci),
            "total": float(opening_total),
            "source_rows": ["data/prior_year_group.csv:2-5"],
        },
        "profit_for_the_year": {
            "owners_of_the_parent": float(profit_owners),
            "non_controlling_interest": float(profit_nci),
            "total": float(profit_total),
        },
        "other_comprehensive_income": {
            "translation_reserve_movement": float(tr_movement),
            "nci_share_of_translation": float(nci_translation),
            "total": float(oci_total),
            "source_rows": [
                "translation reserve workings",
                "ELIM-06",
                "ELIM-07",
            ],
        },
        "transactions_with_owners": {
            "nci_recognised_on_india_acquisition": float(nci_acquisition),
            "source_rows": ["data/acquisition_note.md:10-14", "ELIM-04"],
        },
        "closing": {
            "share_capital": float(closing_sc),
            "retained_earnings": float(closing_re),
            "translation_reserve": float(closing_tr),
            "non_controlling_interest": float(closing_nci),
            "total": float(closing_total + rounding),
            "rounding": float(rounding),
        },
        "workings": {
            "us_parent_operating_net_assets": float(q2(result.translation_workings["us_parent_operating_net_assets"])),
            "india_net_assets_owners_share": float(q2(result.translation_workings["india_net_assets_owners_share"])),
            "india_goodwill_retranslation": float(q2(result.translation_workings["india_goodwill_retranslation"])),
            "analytical_total": float(q2(result.translation_workings["analytical_total"])),
            "balance_sheet_residual": float(q2(result.translation_workings["balance_sheet_residual"])),
            "rounding": float(q2(result.translation_workings["rounding"])),
        },
    }


def build_control_figures(result: ConsolidationResult) -> dict[str, Any]:
    group_profit = q2(result.group_profit)
    profit_nci = q2(result.profit_nci)
    return {
        "bundle_id": config.BUNDLE_ID,
        "currency": config.PRESENTATION_CURRENCY,
        "group_revenue": float(q2(result.group_revenue)),
        "group_profit": float(group_profit),
        "profit_owners": float(group_profit - profit_nci),
        "profit_nci": float(profit_nci),
        "nci_closing": float(q2(result.nci_closing)),
        "goodwill_closing": float(q2(result.goodwill_closing)),
        "translation_reserve_movement": float(q2(result.translation_reserve_movement)),
        "total_assets": float(q2(result.total_assets)),
        "total_equity": float(q2(result.total_equity)),
        "intercompany_difference": float(q2(result.intercompany_difference)),
        "intercompany_difference_causes": {
            "in_transit_invoice_gbp": float(q2(result.intercompany_in_transit)),
            "fx_retranslation_gbp": float(q2(result.intercompany_fx)),
            "total_gbp": float(q2(result.intercompany_in_transit + result.intercompany_fx)),
        },
        "sgd_bank_gbp": None,
        "sgd_bank_gbp_reason": (
            "No GBP/SGD closing rate and no USD/SGD rate to derive one. "
            "The SGD 40,000 bank balance is carried at its booked GBP 23,010; "
            "no closing-rate retranslation is possible without estimating a rate."
        ),
        "journals": {
            "posted": result.journal_counts["posted"],
            "rejected": result.journal_counts["rejected"],
            "held_for_review": result.journal_counts["held_for_review"],
            "total": sum(result.journal_counts.values()),
        },
    }


def write_eliminations_csv(path: Path, result: ConsolidationResult) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "elim_id",
                "description",
                "group_account",
                "account_name",
                "debit_gbp",
                "credit_gbp",
                "source_rows",
                "reason",
            ]
        )
        for elimination in result.eliminations:
            for line in elimination.lines:
                writer.writerow(
                    [
                        elimination.elim_id,
                        elimination.description,
                        line.group_account,
                        line.account_name,
                        f"{q2(line.debit_gbp):.2f}",
                        f"{q2(line.credit_gbp):.2f}",
                        line.source_rows,
                        elimination.reason,
                    ]
                )


def write_consolidated_tb_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "group_account",
                "account_name",
                "account_type",
                "statement",
                "amount_gbp",
                "debit_gbp",
                "credit_gbp",
                "source_rows",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["group_account"],
                    row["account_name"],
                    row["account_type"],
                    row["statement"],
                    f"{row['amount_gbp']:.2f}",
                    f"{row['debit_gbp']:.2f}",
                    f"{row['credit_gbp']:.2f}",
                    row["source_rows"],
                ]
            )
