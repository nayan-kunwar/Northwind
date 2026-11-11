from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ReproducibilityTests(unittest.TestCase):
    def test_one_command_regenerates_the_control_figures(self):
        result = subprocess.run(
            [sys.executable, "run.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        control = json.loads(
            (ROOT / "output" / "control_figures_nk.json").read_text(encoding="utf-8")
        )
        expected = {
            "group_revenue": 28301607.81,
            "group_profit": 2814702.82,
            "profit_owners": 2744660.39,
            "profit_nci": 70042.43,
            "nci_closing": 1334335.55,
            "goodwill_closing": 1375815.07,
            "translation_reserve_movement": 43881.36,
            "total_assets": 28551245.74,
            "total_equity": 18389975.22,
            "intercompany_difference": 20066.42,
        }
        for key, value in expected.items():
            self.assertEqual(control[key], value, key)
        self.assertIsNone(control["sgd_bank_gbp"])
        self.assertEqual(control["journals"]["posted"], 13)
        self.assertEqual(control["journals"]["rejected"], 4)
        self.assertEqual(control["journals"]["held_for_review"], 3)

    def test_outputs_are_byte_identical_on_a_second_run(self):
        def run_and_read():
            subprocess.run(
                [sys.executable, "run.py"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            return {
                name: (ROOT / "output" / name).read_bytes()
                for name in (
                    "control_figures_nk.json",
                    "balance_sheet.json",
                    "profit_and_loss.json",
                    "changes_in_equity.json",
                    "consolidated_tb.csv",
                    "eliminations.csv",
                    "issues.json",
                )
            }

        first = run_and_read()
        second = run_and_read()
        for name in first:
            self.assertEqual(first[name], second[name], name)


if __name__ == "__main__":
    unittest.main()
