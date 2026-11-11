from __future__ import annotations

import unittest
from decimal import Decimal

from northwind import config, consolidation, ingest, journals, ledger, mapping, statements, validation
from northwind.fx import RateTable
from northwind.util import D, IssueCollector, q2


def build_model():
    coa = ingest.load_coa()
    tbs = {entity: ingest.load_tb(entity) for entity in config.ENTITIES}
    raw_maps = ingest.load_maps()
    monthly_in = ingest.load_monthly_in()
    subledger = ingest.load_subledger()
    prior_year = ingest.load_prior_year()
    acquisition = ingest.load_acquisition()
    rate_table = RateTable(ingest.load_fx_rows())
    issues = IssueCollector()

    mapping_result = mapping.build_maps(coa, raw_maps, tbs, issues)
    journal_rows = ingest.load_adjustments()
    triage = journals.JournalTriage(coa, mapping_result.maps, tbs, monthly_in, issues)
    triage.run(journal_rows)
    counts = journals.JournalTriage.counts(journal_rows)

    ledgers = ledger.build_ledgers(
        coa, mapping_result.maps, tbs, monthly_in, journal_rows, rate_table, issues
    )
    result = consolidation.consolidate(
        coa, ledgers, tbs, acquisition, prior_year, counts, rate_table.rates
    )
    validation.add_structural_issues(issues, result, tbs, subledger)
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
    return {
        "result": result,
        "coa": coa,
        "tbs": tbs,
        "journals": journal_rows,
        "ledgers": ledgers,
        "subledger": subledger,
        "monthly_in": monthly_in,
        "control": control_figures,
        "tb_rows": tb_rows,
        "report": report,
        "issues": issues,
    }


class ControlFigureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = build_model()
        cls.result = cls.model["result"]
        cls.control = cls.model["control"]

    def assert_money(self, actual, expected):
        self.assertEqual(q2(D(str(actual))), D(str(expected)))

    def test_group_revenue(self):
        self.assert_money(self.control["group_revenue"], "28301607.81")

    def test_group_profit(self):
        self.assert_money(self.control["group_profit"], "2814702.82")

    def test_profit_owners(self):
        self.assert_money(self.control["profit_owners"], "2744660.39")

    def test_profit_nci(self):
        self.assert_money(self.control["profit_nci"], "70042.43")

    def test_nci_closing(self):
        self.assert_money(self.control["nci_closing"], "1334335.55")

    def test_goodwill_closing(self):
        self.assert_money(self.control["goodwill_closing"], "1375815.07")

    def test_translation_reserve_movement(self):
        self.assert_money(self.control["translation_reserve_movement"], "43881.36")

    def test_total_assets(self):
        self.assert_money(self.control["total_assets"], "28551245.74")

    def test_total_equity(self):
        self.assert_money(self.control["total_equity"], "18389975.22")

    def test_intercompany_difference(self):
        self.assert_money(self.control["intercompany_difference"], "20066.42")
        causes = self.control["intercompany_difference_causes"]
        self.assert_money(causes["in_transit_invoice_gbp"], "8108.54")
        self.assert_money(causes["fx_retranslation_gbp"], "11957.88")
        self.assert_money(causes["total_gbp"], "20066.42")

    def test_sgd_is_null_with_reason(self):
        self.assertIsNone(self.control["sgd_bank_gbp"])
        self.assertIn("No GBP/SGD closing rate", self.control["sgd_bank_gbp_reason"])

    def test_journal_counts(self):
        self.assertEqual(self.control["journals"]["posted"], 13)
        self.assertEqual(self.control["journals"]["rejected"], 4)
        self.assertEqual(self.control["journals"]["held_for_review"], 3)
        self.assertEqual(self.control["journals"]["total"], 20)


class StructuralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = build_model()
        cls.result = cls.model["result"]

    def test_all_validation_checks_pass(self):
        self.assertTrue(
            self.model["report"].all_passed,
            [
                (c.name, c.detail)
                for c in self.model["report"].checks
                if not c.passed
            ],
        )

    def test_eliminations_balance(self):
        for elimination in self.result.eliminations:
            self.assertEqual(
                q2(elimination.total_debit()),
                q2(elimination.total_credit()),
                elimination.elim_id,
            )

    def test_consolidated_tb_balances(self):
        total = sum((D(str(row["amount_gbp"])) for row in self.model["tb_rows"]), D(0))
        self.assertLess(abs(total), D("0.02"))

    def test_every_tb_row_has_source_rows(self):
        for row in self.model["tb_rows"]:
            self.assertTrue(row["source_rows"].strip(), row["group_account"])

    def test_balance_sheet_balances(self):
        bs = statements.build_balance_sheet(
            self.result, self.model["coa"], self.model["ledgers"]
        )
        self.assertTrue(bs["checks"]["balanced"])
        self.assertEqual(bs["checks"]["difference"], 0.0)

    def test_pnl_attribution_adds_up(self):
        pl = statements.build_profit_and_loss(
            self.result, self.model["coa"], self.model["ledgers"]
        )
        attribution = pl["attributable_to"]
        self.assertEqual(
            round(
                attribution["owners_of_the_parent"]
                + attribution["non_controlling_interest"],
                2,
            ),
            pl["profit_for_the_year"],
        )

    def test_changes_in_equity_reconciles(self):
        equity = statements.build_changes_in_equity(self.result)
        opening = equity["opening"]["total"]
        profit = equity["profit_for_the_year"]["total"]
        oci = equity["other_comprehensive_income"]["total"]
        nci = equity["transactions_with_owners"]["nci_recognised_on_india_acquisition"]
        closing = equity["closing"]["total"]
        rounding = equity["closing"]["rounding"]
        self.assertEqual(round(opening + profit + oci + nci + rounding, 2), closing)

    def test_india_h2_only(self):
        refs = [
            p.source_ref
            for p in self.model["ledgers"]["IN"].postings
            if p.source_type == "INDIA_H2"
        ]
        self.assertTrue(refs)
        self.assertFalse(
            any(
                month in ref
                for ref in refs
                for month in ("2024-04", "2024-05", "2024-06")
            )
        )


if __name__ == "__main__":
    unittest.main()
