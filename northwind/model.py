from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class SourceRow:
    row_id: str
    entity: str
    group_account: str
    account_name: str
    account_type: str
    statement: str
    amount_local: Decimal
    currency: str
    amount_gbp: Decimal
    rate_type: str
    rate: Decimal | None
    source_type: str
    source_file: str
    source_line: int | None
    source_ref: str
    journal_id: str | None = None
    note: str = ""


@dataclass
class JournalLine:
    account: str
    group_account: str | None
    debit: Decimal
    credit: Decimal
    memo: str = ""


@dataclass
class Journal:
    journal_id: str
    entity: str
    date: str
    description: str
    prepared_by: str
    lines: list[JournalLine]
    source_line: int | None
    status: str = "pending"
    reasons: list[str] = field(default_factory=list)

    @property
    def signature(self) -> tuple:
        return (
            self.entity,
            self.date,
            tuple(sorted((l.account, str(l.debit), str(l.credit)) for l in self.lines)),
        )
