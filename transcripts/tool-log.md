# Tool log

Commands run from the repository root, with their actual output. This is the evidence that
the one-command contract and the tests hold.

## Environment

```
$ python --version
Python 3.12.4

$ git --version
git version 2.42.0.windows.2
```

No third-party packages are used by the engine or the tests.

## Git history

```
$ git log --oneline
80a2ce8 fix: make the consolidated TB sum to zero and disclose presentation rounding
c513131 chore: add generated output for review
659514c data: add source bundle NWG-D0BC and assignment pack
b1ef772 docs: add architecture, validation, reflection, README and AI transcripts
1782fe3 test: lock the AI corrections with regression and reproducibility tests
81ba780 feat: deterministic consolidation engine, outputs, and tests
90a32fb chore: initialize repository
```

The history is kept, not squashed. This is the history at the time of this log; the
repository itself has the complete history.

## One-command run

```
$ python run.py
Northwind Group consolidation - bundle NWG-D0BC
Outputs written to C:\N-Nayan\Projects\Northwind_TakeHome_v2\output

  group_revenue                    28,301,607.81
  group_profit                      2,814,702.82
  profit_owners                     2,744,660.39
  profit_nci                           70,042.43
  nci_closing                       1,334,335.55
  goodwill_closing                  1,375,815.07
  translation_reserve_movement         43,881.36
  total_assets                     28,551,245.74
  total_equity                     18,389,975.22
  intercompany_difference              20,066.42
  sgd_bank_gbp                              null
  journals                       13 posted / 4 rejected / 3 held

Validation: PASS (15/15 checks)
Issues: 19 (see output/issues.json)
```

## Tests

```
$ python -m unittest discover -s tests -q
----------------------------------------------------------------------
Ran 28 tests in 0.565s

OK
```

The suite includes 12 control-figure tests, structural reconciliation tests, regression
tests for the AI corrections, and a reproducibility test that runs `python run.py` and
compares the output bytes.

## Independent recomputation

```
$ python tools/independent_check.py
figure                               independent          engine      diff  ok
group_revenue                      28,301,607.81   28,301,607.81      0.00  yes
group_profit                        2,814,702.82    2,814,702.82      0.00  yes
profit_owners                       2,744,660.39    2,744,660.39      0.00  yes
profit_nci                             70,042.43       70,042.43      0.00  yes
nci_closing                         1,334,335.55    1,334,335.55      0.00  yes
goodwill_closing                    1,375,815.07    1,375,815.07      0.00  yes
translation_reserve_movement           43,881.36       43,881.36      0.00  yes
total_assets                       28,551,245.74   28,551,245.74      0.00  yes
total_equity                       18,389,975.22   18,389,975.22      0.00  yes
intercompany_difference                20,066.42       20,066.42      0.00  yes

intercompany split: in-transit 8,108.54 FX 11,957.88 total 20,066.42
journals: {'posted': 13, 'rejected': 4, 'held_for_review': 3} engine: {'posted': 13, 'rejected': 4, 'held_for_review': 3, 'total': 20}
sgd_bank_gbp: None (reason present: True )
SGD closing rate absent: True | control is null: True
independent check: PASS
```

The independent script does not import `northwind`; it reads the raw CSVs and JSON and
recomputes the figures with a separate code path.

## Determinism

Two consecutive runs produced byte-identical files (verified with `sha256sum`). The hashes
from the final run:

```
4b6b4d6afe1cb5a8c74d20012e8879677e0322a0cb760703de5171a635dc05d9 *output/control_figures_nk.json
291914a65ef7ed6321a4eaa61efd22a7ec5e75f703efb33349ab4c31cd629558 *output/balance_sheet.json
030e52a1b2d7c46c5080f9a53eff5a639c723fb82f1abdb659bc2ffc20f32ab1 *output/profit_and_loss.json
b106be146f7731633b1a20cbe3304193593bfffaf8a025538c59f47d8aa7c56c *output/changes_in_equity.json
4ddfbc1d77bf5a192d15949be347313fd24a2b92a4819789ed7878cbfa3e9e05 *output/consolidated_tb.csv
2d4d1d4eb30ade3fccd21f23e10a1af205888a6f8a364431209b9f9e664e8df3 *output/eliminations.csv
321541d50159d4c2aea974609d670c6c6104c8a4b90078ad6b30d474789c445a *output/issues.json
```

## Output inventory

```
$ ls output
balance_sheet.json
changes_in_equity.json
consolidated_tb.csv
control_figures_nk.json
eliminations.csv
issues.json
profit_and_loss.json
validation_report.json
```

`validation_report.json` is an extra, not a required deliverable; it records the 15 coded
checks and their details so a reviewer can see the gates that passed.
