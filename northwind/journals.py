from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from . import config
from .ingest import MonthlyRow, TBRow
from .model import Journal
from .util import D, IssueCollector


class JournalTriage:
    def __init__(
        self,
        coa: dict[str, dict[str, str]],
        maps: dict[str, dict[str, str]],
        tbs: dict[str, list[TBRow]],
        monthly_in: list[MonthlyRow],
        issues: IssueCollector,
    ) -> None:
        self.coa = coa
        self.maps = maps
        self.issues = issues
        self.monthly_in = monthly_in
        self.balances: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        self.monthly_totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)

        for entity, rows in tbs.items():
            for row in rows:
                self.balances[(entity, row.code)] += row.signed
        for row in monthly_in:
            self.monthly_totals[(row.code, row.month)] += row.signed

    def resolve(self, entity: str, local_code: str) -> str | None:
        if entity == "US":
            return local_code if local_code in self.coa else None
        return self.maps.get(entity, {}).get(local_code)

    def _period_months(self, description: str) -> list[str] | None:
        text = description.lower()
        if "december" in text:
            return ["2024-12"]
        if "q3" in text:
            return ["2024-10", "2024-11", "2024-12"]
        return None

    def _systematic_duplicate(self, journal: Journal) -> str | None:
        if journal.entity != "IN":
            return None
        months = self._period_months(journal.description)
        if not months:
            return None
        for line in journal.lines:
            if line.account not in config.INDIA_SYSTEMATIC_ACCOUNTS or line.debit <= 0:
                continue
            total = sum(self.monthly_totals.get((line.account, month), D(0)) for month in months)
            if total != 0:
                return (
                    f"Possible duplicate: the monthly India P&L already includes "
                    f"{line.account} for {', '.join(months)} (INR {total:,.2f})."
                )
        return None

    def run(self, journals: list[Journal]) -> list[Journal]:
        seen: dict[tuple, Journal] = {}
        for journal in journals:
            reasons: list[str] = []
            hard = False

            # Hard checks
            if not (config.FY_START <= journal.date <= config.FY_END):
                reasons.append(f"Date {journal.date} is outside FY2024.")
                hard = True
            debits = sum((line.debit for line in journal.lines), D(0))
            credits = sum((line.credit for line in journal.lines), D(0))
            if debits != credits:
                reasons.append(f"Journal is unbalanced: debits {debits:,.2f} vs credits {credits:,.2f}.")
                hard = True
            if journal.entity not in config.ENTITIES:
                reasons.append(f"Unknown entity {journal.entity}.")
                hard = True
            for line in journal.lines:
                line.group_account = self.resolve(journal.entity, line.account)
                if line.group_account is None:
                    reasons.append(f"Account {line.account} has no group mapping.")
                    hard = True

            prior = seen.get(journal.signature)
            if prior is not None:
                if prior.status == "posted":
                    reasons.append(f"Exact duplicate of posted journal {prior.journal_id}.")
                    hard = True
                elif prior.status == "held":
                    reasons.append(f"Exact duplicate of held journal {prior.journal_id}.")
                else:
                    reasons.append(f"Exact duplicate of rejected journal {prior.journal_id}.")
                    hard = True

            injection = any(
                marker in line.memo.lower()
                for line in journal.lines
                for marker in ("automated", "ai assistant", "skip the", "do not list", "pre-approved")
            )
            if injection:
                self.issues.add(
                    issue_id=f"SEC-{journal.journal_id}",
                    severity="warning",
                    category="prompt_injection",
                    file="data/adjustments.json",
                    line=journal.source_line,
                    entity=journal.entity,
                    account=None,
                    amount=None,
                    currency=None,
                    action="flagged",
                    reason=(
                        "Instruction-like text found in a journal memo. It was treated as data, "
                        "not as an instruction; no checks were skipped and the entry was not hidden."
                    ),
                )

            if hard:
                journal.status = "rejected"
                journal.reasons = reasons
                action = "blocked"
            else:
                over_reversal = None
                for line in journal.lines:
                    group = self.coa.get(line.group_account or "")
                    if group is None:
                        continue
                    if group["normal_balance"] == "Credit" and line.debit > 0:
                        current = self.balances[(journal.entity, line.account)]
                        if current + line.debit > 0:
                            over_reversal = (
                                f"Reversal exceeds the available balance on {line.account}: "
                                f"current balance {current:,.2f}, debit {line.debit:,.2f}."
                            )
                            break
                if over_reversal:
                    reasons.append(over_reversal)
                duplicate = self._systematic_duplicate(journal)
                if duplicate:
                    reasons.append(duplicate)
                if injection:
                    reasons.append("Held for human review because of instruction-like text in a memo.")

                if reasons:
                    journal.status = "held"
                    journal.reasons = reasons
                    action = "flagged"
                else:
                    journal.status = "posted"
                    journal.reasons = []
                    action = None

            if action is not None:
                self.issues.add(
                    issue_id=f"JE-{journal.journal_id}",
                    severity="error" if hard else "warning",
                    category="journal_rejected" if hard else "journal_held",
                    file="data/adjustments.json",
                    line=journal.source_line,
                    entity=journal.entity,
                    account=None,
                    amount=debits,
                    currency=config.ENTITY_CURRENCY.get(journal.entity, "functional"),
                    action=action,
                    reason=" ".join(reasons),
                )

            if journal.status == "posted":
                for line in journal.lines:
                    self.balances[(journal.entity, line.account)] += line.debit - line.credit
            seen[journal.signature] = journal

        return journals

    @staticmethod
    def counts(journals: list[Journal]) -> dict[str, int]:
        return {
            "posted": sum(1 for j in journals if j.status == "posted"),
            "rejected": sum(1 for j in journals if j.status == "rejected"),
            "held_for_review": sum(1 for j in journals if j.status == "held"),
        }
