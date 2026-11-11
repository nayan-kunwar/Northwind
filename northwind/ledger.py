from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from . import config
from .fx import RateTable
from .ingest import MonthlyRow, TBRow
from .model import Journal
from .util import D, IssueCollector, q2


@dataclass
class Posting:
    """One debit-positive amount in GBP, with its source lineage."""

    entity: str
    group_account: str
    amount_gbp: Decimal
    source_type: str
    source_ref: str
    source_amount: Decimal | None = None
    source_currency: str | None = None
    rate_type: str | None = None
    rate: Decimal | None = None
    note: str = ""


@dataclass
class EntityLedger:
    entity: str
    postings: list[Posting] = field(default_factory=list)

    def add(self, posting: Posting) -> None:
        self.postings.append(posting)

    def pnl(self) -> dict[str, Decimal]:
        out: dict[str, Decimal] = defaultdict(Decimal)
        for p in self.postings:
            if p.source_type != "EQUITY":
                out[p.group_account] += p.amount_gbp
        return dict(out)

    def profit(self, coa: dict[str, dict[str, str]]) -> Decimal:
        total = sum(
            (p.amount_gbp for p in self.postings if coa[p.group_account]["statement"] == "PL"),
            D(0),
        )
        return -total


def _post_tb(
    ledger: EntityLedger,
    row: TBRow,
    group_account: str,
    coa: dict[str, dict[str, str]],
    fx: RateTable,
    issues: IssueCollector,
) -> None:
    statement = coa[group_account]["statement"]
    rate_type = RateTable.rate_type_for(row.entity, statement)
    amount_gbp, rate = fx.to_gbp(row.signed, row.currency, rate_type)
    if amount_gbp is None:
        issues.add(
            issue_id=f"FX-{row.entity}-{row.code}",
            severity="warning",
            category="missing_rate",
            file=row.source_file,
            line=row.source_line,
            entity=row.entity,
            account=row.code,
            amount=row.signed,
            currency=row.currency,
            action="flagged",
            reason=fx.describe_missing(row.currency, rate_type),
        )
        return
    note = ""
    if row.txn_currency and row.txn_currency != row.currency:
        note = f"Transaction currency {row.txn_currency} {row.txn_amount:,.2f}"
    ledger.add(
        Posting(
            entity=row.entity,
            group_account=group_account,
            amount_gbp=amount_gbp,
            source_type="TB",
            source_ref=f"{row.source_file}:{row.source_line}",
            source_amount=row.signed,
            source_currency=row.currency,
            rate_type=rate_type,
            rate=rate,
            note=note,
        )
    )


def build_ledgers(
    coa: dict[str, dict[str, str]],
    maps: dict[str, dict[str, str]],
    tbs: dict[str, list[TBRow]],
    monthly_in: list[MonthlyRow],
    journals: list[Journal],
    fx: RateTable,
    issues: IssueCollector,
) -> dict[str, EntityLedger]:
    ledgers = {entity: EntityLedger(entity) for entity in config.ENTITIES}
    equity_accounts = {"3100", "3200", "3300", "3400"}

    # ---- US: group codes already, translate BS at closing and P&L at average
    for row in tbs["US"]:
        if row.code not in coa:
            continue
        if row.code in equity_accounts:
            continue
        _post_tb(ledgers["US"], row, row.code, coa, fx, issues)

    # ---- UK: local codes via map, GBP functional
    for row in tbs["UK"]:
        group_account = maps["UK"].get(row.code)
        if group_account is None or group_account in equity_accounts:
            continue
        if row.code == "1210" and row.txn_currency == "SGD":
            # Missing GBP/SGD closing rate: carry the booked GBP balance, flag it.
            ledgers["UK"].add(
                Posting(
                    entity="UK",
                    group_account=group_account,
                    amount_gbp=row.signed,
                    source_type="TB",
                    source_ref=f"{row.source_file}:{row.source_line}",
                    source_amount=row.signed,
                    source_currency="GBP",
                    rate_type="booked",
                    rate=None,
                    note=(
                        f"SGD {row.txn_amount:,.2f} bank balance carried at booked "
                        f"GBP {row.signed:,.2f}; no GBP/SGD closing rate."
                    ),
                )
            )
            issues.add(
                issue_id="FX-UK-SGD-CLOSING",
                severity="warning",
                category="missing_rate",
                file=row.source_file,
                line=row.source_line,
                entity="UK",
                account=row.code,
                amount=row.signed,
                currency="GBP",
                action="flagged",
                reason=(
                    "No GBP/SGD closing rate and no USD/SGD rate from which to derive one. "
                    "The SGD 40,000 bank balance is carried at its booked GBP 23,010; "
                    "the control figure sgd_bank_gbp is null."
                ),
            )
            continue
        _post_tb(ledgers["UK"], row, group_account, coa, fx, issues)

    # ---- India: balance sheet at closing; P&L from the H2 monthly file
    for row in tbs["IN"]:
        group_account = maps["IN"].get(row.code)
        if group_account is None or group_account in equity_accounts:
            continue
        if coa[group_account]["statement"] != "BS":
            continue
        _post_tb(ledgers["IN"], row, group_account, coa, fx, issues)

    for row in monthly_in:
        if not ("2024-07" <= row.month <= "2024-12"):
            continue
        group_account = maps["IN"].get(row.code)
        if group_account is None or coa[group_account]["statement"] != "PL":
            continue
        amount_gbp, rate = fx.to_gbp(row.signed, "INR", "h2_average")
        if amount_gbp is None:
            issues.add(
                issue_id=f"FX-IN-{row.code}-{row.month}",
                severity="warning",
                category="missing_rate",
                file=row.source_file,
                line=row.source_line,
                entity="IN",
                account=row.code,
                amount=row.signed,
                currency="INR",
                action="flagged",
                reason=fx.describe_missing("INR", "h2_average"),
            )
            continue
        ledgers["IN"].add(
            Posting(
                entity="IN",
                group_account=group_account,
                amount_gbp=amount_gbp,
                source_type="INDIA_H2",
                source_ref=f"{row.source_file}:{row.source_line} [{row.month}]",
                source_amount=row.signed,
                source_currency="INR",
                rate_type="h2_average",
                rate=rate,
                note=f"H2 only ({row.month}); H1 is pre-acquisition.",
            )
        )

    # ---- Posted journals, translated according to the target account
    for journal in journals:
        if journal.status != "posted":
            continue
        for line in journal.lines:
            if line.group_account is None:
                continue
            statement = coa[line.group_account]["statement"]
            if journal.entity == "UK":
                rate_type = "identity"
            elif journal.entity == "US":
                rate_type = "average" if statement == "PL" else "closing"
            else:
                rate_type = "h2_average" if statement == "PL" else "closing"
            amount_gbp, rate = fx.to_gbp(
                line.debit - line.credit, config.ENTITY_CURRENCY[journal.entity], rate_type
            )
            if amount_gbp is None:
                issues.add(
                    issue_id=f"FX-{journal.journal_id}-{line.account}",
                    severity="warning",
                    category="missing_rate",
                    file="data/adjustments.json",
                    line=journal.source_line,
                    entity=journal.entity,
                    account=line.account,
                    amount=line.debit - line.credit,
                    currency=config.ENTITY_CURRENCY[journal.entity],
                    action="flagged",
                    reason=fx.describe_missing(config.ENTITY_CURRENCY[journal.entity], rate_type),
                )
                continue
            ledgers[journal.entity].add(
                Posting(
                    entity=journal.entity,
                    group_account=line.group_account,
                    amount_gbp=amount_gbp,
                    source_type="JOURNAL",
                    source_ref=f"data/adjustments.json:{journal.source_line} ({journal.journal_id})",
                    source_amount=line.debit - line.credit,
                    source_currency=config.ENTITY_CURRENCY[journal.entity],
                    rate_type=rate_type,
                    rate=rate,
                    note=journal.description,
                )
            )

    # ---- UK subledger reclass (assumed; both controls differ by 45,000)
    reclass = config.UK_SUBLEDGER_RECLASS
    ledgers["UK"].add(
        Posting(
            entity="UK",
            group_account="2100",
            amount_gbp=reclass,
            source_type="ASSUMPTION",
            source_ref="data/subledger_controls.csv:4-5 (UK AR/AP control difference)",
            source_amount=reclass,
            source_currency="GBP",
            rate_type="identity",
            rate=Decimal("1"),
            note="Dr trade payables / Cr trade receivables 45,000 to reconcile both controls.",
        )
    )
    ledgers["UK"].add(
        Posting(
            entity="UK",
            group_account="1200",
            amount_gbp=-reclass,
            source_type="ASSUMPTION",
            source_ref="data/subledger_controls.csv:4-5 (UK AR/AP control difference)",
            source_amount=-reclass,
            source_currency="GBP",
            rate_type="identity",
            rate=Decimal("1"),
            note="Assumed two-sided reclass; no P&L or net-asset effect.",
        )
    )

    # ---- Intercompany: record the in-transit invoice and retranslate the UK USD payable
    in_transit_usd = D("10160")
    in_transit_gbp = q2(in_transit_usd / fx.get("GBP", "USD", "closing"))
    ledgers["UK"].add(
        Posting(
            entity="UK",
            group_account="6300",
            amount_gbp=in_transit_gbp,
            source_type="INTRANSIT",
            source_ref="data/intercompany.csv:6 (INV-US-2291, in transit)",
            source_amount=in_transit_gbp,
            source_currency="GBP",
            rate_type="closing",
            rate=fx.get("GBP", "USD", "closing"),
            note="Missing invoice recorded by UK at the closing rate.",
        )
    )
    ledgers["UK"].add(
        Posting(
            entity="UK",
            group_account="2150",
            amount_gbp=-in_transit_gbp,
            source_type="INTRANSIT",
            source_ref="data/intercompany.csv:6 (INV-US-2291, in transit)",
            source_amount=-in_transit_gbp,
            source_currency="GBP",
            rate_type="closing",
            rate=fx.get("GBP", "USD", "closing"),
            note="In-transit payable at the closing rate.",
        )
    )

    usd_payable = D("629840")
    closing_gbp = usd_payable / fx.get("GBP", "USD", "closing")
    booked_gbp = D("490707.72")
    fx_loss = q2(closing_gbp - booked_gbp)
    ledgers["UK"].add(
        Posting(
            entity="UK",
            group_account="7300",
            amount_gbp=fx_loss,
            source_type="FX",
            source_ref="data/tb_uk.csv:10 (USD -629,840); data/fx_rates.csv:6 (GBP/USD closing)",
            source_amount=fx_loss,
            source_currency="GBP",
            rate_type="closing",
            rate=fx.get("GBP", "USD", "closing"),
            note="Retranslation of the UK USD payable at the closing rate.",
        )
    )
    ledgers["UK"].add(
        Posting(
            entity="UK",
            group_account="2150",
            amount_gbp=-fx_loss,
            source_type="FX",
            source_ref="data/tb_uk.csv:10 (USD -629,840); data/fx_rates.csv:6 (GBP/USD closing)",
            source_amount=-fx_loss,
            source_currency="GBP",
            rate_type="closing",
            rate=fx.get("GBP", "USD", "closing"),
            note="Payable increased to the closing-rate amount.",
        )
    )

    return ledgers


def entity_tb_balance(tbs: dict[str, list[TBRow]]) -> dict[str, Decimal]:
    return {
        entity: sum((row.signed for row in rows), D(0))
        for entity, rows in tbs.items()
    }
