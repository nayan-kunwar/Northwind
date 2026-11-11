from __future__ import annotations

from dataclasses import dataclass, field

from .ingest import MapRow, TBRow
from .util import IssueCollector, norm_name


@dataclass
class MappingResult:
    maps: dict[str, dict[str, str]] = field(default_factory=dict)
    corrections: list[dict[str, str]] = field(default_factory=list)


def _match_map_code(mapping: dict[str, MapRow], code: str) -> str | None:
    """Match ERP codes that differ only by zero padding (e.g. 30 vs 0030)."""
    if code in mapping:
        return code
    for candidate in (code.zfill(4), code.lstrip("0") or "0"):
        if candidate in mapping:
            return candidate
    return None


def build_maps(
    coa: dict[str, dict[str, str]],
    raw_maps: dict[str, dict[str, MapRow]],
    tbs: dict[str, list[TBRow]],
    issues: IssueCollector,
) -> MappingResult:
    """Validate local-to-group mappings.

    The correction rule is deliberately narrow: a local account is re-mapped only
    when its name is an exact (normalised) match for a group account and the
    supplied target has a different account type. This catches the UK deferred
    income -> revenue error without guessing at genuinely ambiguous mappings.
    """
    result = MappingResult()
    group_by_name: dict[str, str] = {}
    for code, row in coa.items():
        group_by_name.setdefault(norm_name(row["account_name"]), code)

    for entity in ("US", "UK", "IN"):
        result.maps[entity] = {}
        if entity == "US":
            for row in tbs[entity]:
                if row.code not in coa:
                    issues.add(
                        issue_id=f"MAP-{entity}-{row.code}",
                        severity="error",
                        category="unmapped_account",
                        file=row.source_file,
                        line=row.source_line,
                        entity=entity,
                        account=row.code,
                        amount=row.signed,
                        currency=row.currency,
                        action="blocked",
                        reason=f"US account {row.code} is not in the group chart of accounts.",
                    )
                    continue
                result.maps[entity][row.code] = row.code
            continue

        tb_codes = {row.code for row in tbs[entity]}
        for local_code, mapping in raw_maps[entity].items():
            group_code = mapping.group_code
            if group_code not in coa:
                issues.add(
                    issue_id=f"MAP-{entity}-{local_code}-missing",
                    severity="error",
                    category="invalid_mapping_target",
                    file=mapping.source_file,
                    line=mapping.source_line,
                    entity=entity,
                    account=local_code,
                    amount=None,
                    currency=None,
                    action="blocked",
                    reason=f"Mapping target {group_code} does not exist in the group chart of accounts.",
                )
                continue

            resolved = group_code
            exact = group_by_name.get(norm_name(mapping.local_name))
            if (
                exact is not None
                and exact != group_code
                and coa[exact]["account_type"] != coa[group_code]["account_type"]
            ):
                resolved = exact
                result.corrections.append(
                    {
                        "entity": entity,
                        "local_code": local_code,
                        "local_name": mapping.local_name,
                        "mapped_to": group_code,
                        "corrected_to": exact,
                    }
                )
                tb_row = next(
                    (
                        row
                        for row in tbs[entity]
                        if row.code == local_code or row.code.zfill(4) == local_code
                    ),
                    None,
                )
                issues.add(
                    issue_id=f"MAP-{entity}-{local_code}-correction",
                    severity="warning",
                    category="wrong_mapping",
                    file=mapping.source_file,
                    line=mapping.source_line,
                    entity=entity,
                    account=local_code,
                    amount=abs(tb_row.signed) if tb_row is not None else None,
                    currency=tb_row.currency if tb_row is not None else None,
                    action="assumed",
                    reason=(
                        f"Local account '{mapping.local_name}' is mapped to {group_code} "
                        f"({coa[group_code]['account_name']}, {coa[group_code]['account_type']}) "
                        f"but the group chart has {exact} ({coa[exact]['account_name']}, "
                        f"{coa[exact]['account_type']}). Corrected to {exact}."
                    ),
                )
            result.maps[entity][local_code] = resolved

        used: set[str] = set()
        for row in tbs[entity]:
            matched = _match_map_code(raw_maps[entity], row.code)
            if matched is None:
                issues.add(
                    issue_id=f"MAP-{entity}-{row.code}-unmapped",
                    severity="error",
                    category="unmapped_account",
                    file=row.source_file,
                    line=row.source_line,
                    entity=entity,
                    account=row.code,
                    amount=row.signed,
                    currency=row.currency,
                    action="blocked",
                    reason=f"Local account {row.code} has no mapping to the group chart of accounts.",
                )
                continue
            used.add(matched)
            result.maps[entity][row.code] = result.maps[entity][matched]

        for local_code, mapping in raw_maps[entity].items():
            if local_code not in used:
                issues.add(
                    issue_id=f"MAP-{entity}-{local_code}-unused",
                    severity="info",
                    category="unused_mapping",
                    file=mapping.source_file,
                    line=mapping.source_line,
                    entity=entity,
                    account=local_code,
                    amount=None,
                    currency=None,
                    action="flagged",
                    reason=f"Mapping for local account {local_code} is not used by the trial balance.",
                )
    return result
