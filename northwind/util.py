from __future__ import annotations

import csv
import json
import re
from decimal import Decimal, ROUND_HALF_UP, getcontext
from pathlib import Path
from typing import Any, Iterable

getcontext().prec = 28

CENT = Decimal("0.01")
ZERO = Decimal("0")


def D(value: Any) -> Decimal:
    """Parse a value as Decimal without binary-float artefacts."""
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return ZERO
    return Decimal(str(value))


def q2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def f2(value: Decimal) -> float:
    return float(q2(value))


def read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV into dicts, preserving the physical line number of each row."""
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return rows
        header = [h.strip() for h in header]
        for raw in reader:
            if not raw or all(cell.strip() == "" for cell in raw):
                continue
            row = {header[i]: raw[i].strip() if i < len(raw) else "" for i in range(len(header))}
            row["_line"] = str(reader.line_num)
            row["_file"] = str(path.relative_to(path.parent.parent)) if path.parent.name == "data" else path.name
            rows.append(row)
    return rows


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def find_json_line(path: Path, needle: str) -> int | None:
    """Return the 1-based line containing needle, for issue traceability."""
    with path.open(encoding="utf-8-sig") as handle:
        for i, line in enumerate(handle, 1):
            if needle in line:
                return i
    return None


def norm_name(value: str) -> str:
    value = value.lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def source_ref(file: str, line: int | str | None, suffix: str = "") -> str:
    base = f"{file}:{line}" if line is not None else file
    return f"{base}{suffix}"


class IssueCollector:
    """Collects every data/control problem with file, line and action taken."""

    def __init__(self) -> None:
        self._issues: list[dict[str, Any]] = []

    def add(
        self,
        *,
        issue_id: str,
        severity: str,
        category: str,
        file: str,
        line: int | None,
        entity: str | None,
        account: str | None,
        amount: Any,
        currency: str | None,
        action: str,
        reason: str,
    ) -> None:
        self._issues.append(
            {
                "id": issue_id,
                "severity": severity,
                "category": category,
                "file": file,
                "line": line,
                "entity": entity,
                "account": account,
                "amount": None if amount is None else str(q2(D(amount))),
                "currency": currency,
                "action": action,
                "reason": reason,
            }
        )

    def all(self) -> list[dict[str, Any]]:
        return sorted(self._issues, key=lambda x: (x["file"], x["line"] or 0, x["id"]))

    def write(self, path: Path, bundle_id: str) -> None:
        payload = {
            "bundle_id": bundle_id,
            "count": len(self._issues),
            "actions": {
                action: sum(1 for i in self._issues if i["action"] == action)
                for action in sorted({i["action"] for i in self._issues})
            },
            "issues": self.all(),
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def unique_ids(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
