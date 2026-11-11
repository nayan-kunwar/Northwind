from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from . import config
from .model import Journal, JournalLine
from .util import D, find_json_line, read_csv, read_json


@dataclass
class TBRow:
    entity: str
    code: str
    name: str
    signed: Decimal
    currency: str
    source_file: str
    source_line: int
    txn_currency: str = ""
    txn_amount: Decimal | None = None


@dataclass
class MonthlyRow:
    code: str
    name: str
    month: str
    signed: Decimal
    source_file: str
    source_line: int


@dataclass
class MapRow:
    local_code: str
    local_name: str
    group_code: str
    source_file: str
    source_line: int


@dataclass
class Acquisition:
    consideration_inr: Decimal
    interest_pct: Decimal
    share_capital_inr: Decimal
    reserves_inr: Decimal
    h1_profit_inr: Decimal
    net_assets_inr: Decimal

    @property
    def goodwill_inr(self) -> Decimal:
        return self.consideration_inr - self.interest_pct * self.net_assets_inr

    @property
    def nci_acq_inr(self) -> Decimal:
        return (Decimal("1") - self.interest_pct) * self.net_assets_inr


def load_entities() -> dict[str, dict[str, str]]:
    return {row["entity_id"]: row for row in read_csv(config.DATA / "entities.csv")}


def load_coa() -> dict[str, dict[str, str]]:
    return {row["account_code"]: row for row in read_csv(config.DATA / "group_coa.csv")}


def load_fx_rows() -> list[dict[str, str]]:
    return read_csv(config.DATA / "fx_rates.csv")


def load_tb(entity: str) -> list[TBRow]:
    path = config.DATA / config.ENTITY_FILES[entity]
    rows: list[TBRow] = []
    if entity == "US":
        for row in read_csv(path):
            rows.append(
                TBRow(
                    entity=entity,
                    code=row["account_code"],
                    name=row["account_name"],
                    signed=D(row["debit"]) - D(row["credit"]),
                    currency="USD",
                    source_file=f"data/{path.name}",
                    source_line=int(row["_line"]),
                )
            )
    elif entity == "UK":
        for row in read_csv(path):
            rows.append(
                TBRow(
                    entity=entity,
                    code=row["nominal_code"],
                    name=row["description"],
                    signed=D(row["balance"]),
                    currency="GBP",
                    source_file=f"data/{path.name}",
                    source_line=int(row["_line"]),
                    txn_currency=row.get("txn_currency", ""),
                    txn_amount=D(row["txn_amount"]) if row.get("txn_amount") else None,
                )
            )
    elif entity == "IN":
        for row in read_csv(path):
            sign = Decimal("1") if row["dr_cr"] == "Dr" else Decimal("-1")
            rows.append(
                TBRow(
                    entity=entity,
                    code=row["ledger_code"],
                    name=row["ledger_name"],
                    signed=sign * D(row["amount"]),
                    currency="INR",
                    source_file=f"data/{path.name}",
                    source_line=int(row["_line"]),
                )
            )
    else:
        raise ValueError(entity)
    return rows


def load_maps() -> dict[str, dict[str, MapRow]]:
    result: dict[str, dict[str, MapRow]] = {}
    for entity, filename in (("UK", "map_uk.csv"), ("IN", "map_in.csv")):
        path = config.DATA / filename
        result[entity] = {}
        for row in read_csv(path):
            result[entity][row["local_code"]] = MapRow(
                local_code=row["local_code"],
                local_name=row["local_name"],
                group_code=row["group_code"],
                source_file=f"data/{filename}",
                source_line=int(row["_line"]),
            )
    return result


def load_monthly_in() -> list[MonthlyRow]:
    path = config.DATA / "in_pl_monthly.csv"
    rows: list[MonthlyRow] = []
    for row in read_csv(path):
        sign = Decimal("1") if row["dr_cr"] == "Dr" else Decimal("-1")
        rows.append(
            MonthlyRow(
                code=row["ledger_code"],
                name=row["ledger_name"],
                month=row["month"],
                signed=sign * D(row["amount"]),
                source_file=f"data/{path.name}",
                source_line=int(row["_line"]),
            )
        )
    return rows


def load_intercompany() -> list[dict[str, str]]:
    return read_csv(config.DATA / "intercompany.csv")


def load_subledger() -> list[dict[str, str]]:
    return read_csv(config.DATA / "subledger_controls.csv")


def load_adjustments() -> list[Journal]:
    path = config.DATA / "adjustments.json"
    payload = read_json(path)
    journals: list[Journal] = []
    for entry in payload["entries"]:
        journal_id = entry["id"]
        line_no = find_json_line(path, f'"id": "{journal_id}"')
        lines = [
            JournalLine(
                account=line["account"],
                group_account=None,
                debit=D(line.get("debit", "0")),
                credit=D(line.get("credit", "0")),
                memo=line.get("memo", ""),
            )
            for line in entry["lines"]
        ]
        journals.append(
            Journal(
                journal_id=journal_id,
                entity=entry["entity"],
                date=entry["date"],
                description=entry.get("description", ""),
                prepared_by=entry.get("prepared_by", ""),
                lines=lines,
                source_line=line_no,
            )
        )
    return journals


def load_prior_year() -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for row in read_csv(config.DATA / "prior_year_group.csv"):
        result[row["group_account"]] = D(row["amount_gbp"])
    return result


def load_acquisition() -> Acquisition:
    path = config.DATA / "acquisition_note.md"
    text = path.read_text(encoding="utf-8")

    def amount(pattern: str) -> Decimal:
        match = re.search(pattern, text)
        if not match:
            raise ValueError(f"Could not parse acquisition note: {pattern}")
        return D(match.group(1).replace(",", ""))

    consideration = amount(r"Consideration:\*\*\s*INR\s*([\d,]+)")
    interest = D(re.search(r"Interest acquired:\*\*\s*(\d+)%", text).group(1)) / Decimal("100")
    share_capital = amount(r"\|\s*Equity share capital\s*\|\s*([\d,]+)\s*\|")
    reserves = amount(r"\|\s*Reserves and surplus at 1 April 2024\s*\|\s*([\d,]+)\s*\|")
    h1_profit = amount(r"\|\s*Profit for 1 April to 30 June 2024\s*\|\s*([\d,]+)\s*\|")
    net_assets = amount(r"\|\s*\*\*Net assets at completion\*\*\s*\|\s*\*\*([\d,]+)\*\*\s*\|")
    if share_capital + reserves + h1_profit != net_assets:
        raise ValueError("Acquisition note does not add up")
    return Acquisition(
        consideration_inr=consideration,
        interest_pct=interest,
        share_capital_inr=share_capital,
        reserves_inr=reserves,
        h1_profit_inr=h1_profit,
        net_assets_inr=net_assets,
    )
