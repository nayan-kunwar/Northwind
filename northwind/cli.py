from __future__ import annotations

import json
import sys
from pathlib import Path

from . import config, consolidation, ingest, journals, ledger, mapping, statements, validation
from .fx import RateTable
from .util import IssueCollector, q2


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    config.OUTPUT.mkdir(parents=True, exist_ok=True)
    issues = IssueCollector()

    entities = ingest.load_entities()
    coa = ingest.load_coa()
    tbs = {entity: ingest.load_tb(entity) for entity in config.ENTITIES}
    raw_maps = ingest.load_maps()
    monthly_in = ingest.load_monthly_in()
    intercompany = ingest.load_intercompany()
    subledger = ingest.load_subledger()
    prior_year = ingest.load_prior_year()
    acquisition = ingest.load_acquisition()
    rate_table = RateTable(ingest.load_fx_rows())

    mapping_result = mapping.build_maps(coa, raw_maps, tbs, issues)
    journal_rows = ingest.load_adjustments()
    triage = journals.JournalTriage(
        coa, mapping_result.maps, tbs, monthly_in, issues
    )
    triage.run(journal_rows)
    counts = journals.JournalTriage.counts(journal_rows)

    ledgers = ledger.build_ledgers(
        coa,
        mapping_result.maps,
        tbs,
        monthly_in,
        journal_rows,
        rate_table,
        issues,
    )

    result = consolidation.consolidate(
        coa,
        ledgers,
        tbs,
        acquisition,
        prior_year,
        counts,
        rate_table.rates,
    )

    validation.add_structural_issues(issues, result, tbs, subledger)

    balance_sheet = statements.build_balance_sheet(result, coa, ledgers)
    profit_and_loss = statements.build_profit_and_loss(result, coa, ledgers)
    changes_in_equity = statements.build_changes_in_equity(result)
    control_figures = statements.build_control_figures(result)
    tb_rows = statements.build_consolidated_tb(result, coa, ledgers)

    report = validation.run_checks(
        result=result,
        coa=coa,
        tbs=tbs,
        journals=journal_rows,
        ledgers=ledgers,
        monthly_in=monthly_in,
        subledger=subledger,
        tb_rows=tb_rows,
        control_figures=control_figures,
    )

    _write_json(config.OUTPUT / "balance_sheet.json", balance_sheet)
    _write_json(config.OUTPUT / "profit_and_loss.json", profit_and_loss)
    _write_json(config.OUTPUT / "changes_in_equity.json", changes_in_equity)
    _write_json(config.OUTPUT / "control_figures_nk.json", control_figures)
    statements.write_eliminations_csv(config.OUTPUT / "eliminations.csv", result)
    statements.write_consolidated_tb_csv(config.OUTPUT / "consolidated_tb.csv", tb_rows)
    issues.write(config.OUTPUT / "issues.json", config.BUNDLE_ID)
    _write_json(
        config.OUTPUT / "validation_report.json",
        {
            "bundle_id": config.BUNDLE_ID,
            "all_passed": report.all_passed,
            "checks": [
                {"check": c.name, "passed": c.passed, "detail": c.detail}
                for c in report.checks
            ],
        },
    )

    print(f"Northwind Group consolidation - bundle {config.BUNDLE_ID}")
    print(f"Outputs written to {config.OUTPUT}")
    print("")
    print(f"  group_revenue                  {control_figures['group_revenue']:>15,.2f}")
    print(f"  group_profit                   {control_figures['group_profit']:>15,.2f}")
    print(f"  profit_owners                  {control_figures['profit_owners']:>15,.2f}")
    print(f"  profit_nci                     {control_figures['profit_nci']:>15,.2f}")
    print(f"  nci_closing                    {control_figures['nci_closing']:>15,.2f}")
    print(f"  goodwill_closing               {control_figures['goodwill_closing']:>15,.2f}")
    print(f"  translation_reserve_movement   {control_figures['translation_reserve_movement']:>15,.2f}")
    print(f"  total_assets                   {control_figures['total_assets']:>15,.2f}")
    print(f"  total_equity                   {control_figures['total_equity']:>15,.2f}")
    print(f"  intercompany_difference        {control_figures['intercompany_difference']:>15,.2f}")
    print(f"  sgd_bank_gbp                   {'null':>15}")
    print(
        f"  journals                       {counts['posted']} posted / "
        f"{counts['rejected']} rejected / {counts['held_for_review']} held"
    )
    print("")
    print(f"Validation: {'PASS' if report.all_passed else 'FAIL'} "
          f"({sum(1 for c in report.checks if c.passed)}/{len(report.checks)} checks)")
    for check in report.checks:
        if not check.passed:
            print(f"  FAIL {check.name}: {check.detail}")
    print(f"Issues: {len(issues.all())} (see output/issues.json)")

    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
