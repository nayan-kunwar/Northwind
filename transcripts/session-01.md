# AI session record — session 01

**Tool:** OpenCode / DeepSeek V4.1 Flash (agentic coding session)
**Bundle:** NWG-D0BC
**Scope:** reading the pack, building the consolidation engine, debugging it, writing the
submission documents and tests.

This is the working record of the session. It includes the dead ends, the wrong numbers
and the corrections. Tool output is abridged where it is repetitive (for example, repeated
file writes); no decision, mistake or correction has been removed. No secrets or personal
data were present in the session; the git author email is a placeholder.

---

## 1. Initial brief

**User:** “Complete the Northwind Group consolidation take-home assignment… build a
reproducible Python prototype… six deliverables… quote bundle ID NWG-D0BC… do not ask the
3 clarifying questions; document assumptions instead.”

**Assistant:** Read the PDF and the data bundle. Identified the key traps: JE-006 prompt
injection and imbalance, JE-016 unmapped GST account, JE-017 out of period, JE-019
duplicate, JE-009 over-reversal, JE-018/JE-020 possible duplicates, the UK 2310 mapping,
the UK zero-padded 30/31 codes, the UK 45,000 AR/AP difference, the missing GBP/SGD closing
rate, the India FY25 YTD vs H2 mismatch, and the intercompany in-transit invoice.

The first proposed design was a multi-agent topology with separate LLM agents for
ingestion, mapping, journals, FX, consolidation and reporting. **I rejected the LLM
control of the arithmetic path.** The design became a deterministic pipeline with an LLM
only at the edges (mapping suggestions, anomaly summaries, narrative). This is recorded in
`DECISIONS.md` #1.

## 2. First model and the India rate error

The first scratch model computed the group figures with the **FY average** GBP/USD rate
for India instead of the **H2 average**. It produced:

```
GBPINR h2 average 107.28810   (wrong: used 1.278 × 83.95)
group revenue     27,819,858.73
group profit       2,816,347.01
NCI profit            70,371.27
TR movement           42,566.01
```

**Correction:** the FX table has a separate `h2_average` row for GBP/USD (1.284), so the
correct GBP/INR H2 average is 1.284 × 83.95 = **107.7918**. The corrected figures are
group revenue 28,301,607.81, group profit 2,814,702.82, NCI profit 70,042.43 and TR
43,881.36. This was the first sign that the India period/rate choice is the largest single
driver of the P&L.

## 3. Building the engine

The engine was written in this order:

1. `config.py`, `util.py`, `model.py` — paths, Decimal helpers, source-row and journal
   dataclasses.
2. `ingest.py` — three ERP adapters (NetSuite US, Sage 50 UK, Tally India), the COA,
   mappings, monthly India P&L, intercompany, subledger, adjustments, prior year and the
   acquisition note.
3. `fx.py` — rate table with cross-rate derivation and explicit missing-rate handling.
4. `mapping.py` — mapping validation and the narrow name/type correction rule.
5. `journals.py` — the five hard checks plus over-reversal, duplicate and injection
   detection.
6. `ledger.py` — entity postings in GBP with source lineage; the UK reclass, in-transit
   invoice and FX retranslation; India H2 P&L.
7. `consolidation.py` — group P&L and BS, IC eliminations, NCI, goodwill, TR, control
   figures.
8. `statements.py` — TB, balance sheet, P&L, changes in equity, control figures, CSV
   writers.
9. `validation.py`, `cli.py`, `run.py` — checks, orchestration and the one-command entry
   point.

The first full run failed on a type error: `config.INDIA_NCI_PCT` was a float (`0.20`) and
was multiplied by a Decimal. **Fix:** changed the constant to `Decimal("0.20")`.

## 4. The first engine run and the zero-padding bug

After the type fix, the engine produced:

```
group_revenue                    28,301,607.81   (correct)
group_profit                      2,814,702.81   (0.01 low)
total_assets                     26,711,245.74   (1,840,000 low)
total_equity                     16,549,975.22
translation_reserve_movement    -1,796,118.64   (wrong)
```

The balance sheet did not balance, and the TR was nonsense. Investigation showed that the
UK trial balance uses account codes `30` and `31`, while `map_uk.csv` uses `0030` and
`0031`. The first mapping lookup was an exact string match, so both rows were silently
skipped. PPE cost was understated by GBP 2,900,000 and accumulated depreciation was
overstated by GBP 1,060,000 — a net GBP 1,840,000 understatement of assets.

**Fix:** `_match_map_code` tries the exact code, the zero-padded code and the
zero-stripped code. The unused-mapping check and the TB unmapped check use the same
matcher. The regression test `test_zero_padded_uk_accounts_are_mapped` locks it.

The same run also had the US profit double-divided by 1.278 in the TR decomposition. The
US profit is already in GBP, so the decomposition produced a US translation difference of
GBP 470,437.74 instead of GBP 154,486.87. **Fix:** subtract the GBP profit directly. The
analytical TR then reconciled to the balance-sheet residual at 43,881.36 (with a GBP 0.01
rounding line).

## 5. The intercompany sign

The first pass treated the remaining GBP 1,966.21 intercompany difference as an expense.
The elimination entry is:

```
Dr 4200 IC income        500,782.47
Cr 6300 IC expense       498,816.26
Cr 7300 FX              1,966.21
```

The credit to 7300 is a **gain**, not an expense. Treating it as an expense would reduce
group profit by 1,966.21 and break the balance sheet. **Correction:** the 7300 line is a
credit; group profit stays at the sum of entity profits (2,814,702.82), and the regression
test `test_intercompany_7300_is_a_credit` asserts the credit and the group 7300 balance of
9,991.67.

## 6. Journals, mapping and the traps

The journal triage produced the expected **13 posted / 4 rejected / 3 held**:

- JE-006: unbalanced (51,200 vs 50,000 USD) and contains the prompt injection. Rejected;
  the injection is separately flagged as `SEC-JE-006`. The memo was treated as data.
- JE-016: `IN-GST-ITC` has no group mapping. Rejected; no account was invented.
- JE-017: dated 2025-01-06. Rejected.
- JE-019: exact duplicate of JE-014. Rejected.
- JE-009: 64,000 debit against a 41,500 accrual. Held.
- JE-018 / JE-020: possible duplicates of the monthly India interest/depreciation. Held.

The mapping validator corrected `2310 Deferred income → 4100 Revenue` to `2300 Deferred
income` because the local name exactly matches a group account with a different type. The
issue is logged as `assumed` with the GBP 180,000 amount. The UK AR/AP 45,000 reclass is
also logged as `assumed`; the two-sided entry is the only one that reconciles both
controls.

The first pass also considered mapping `IN-GST-ITC` to `1400 Prepayments`. **I rejected
that** as an invented mapping. The journal stays rejected until a group GST account is
approved.

## 7. The missing SGD rate

The UK has a 40,000 SGD bank balance carried at GBP 23,010. The FX table has GBP/SGD
opening (1.6830) and average (1.7120), but no closing rate and no USD/SGD rate to derive
one. The first suggestion was to use the average 1.7120 as a proxy. **I rejected it.**
The control figure `sgd_bank_gbp` is `null` with the reason; the balance sheet carries the
booked GBP 23,010 and the issue is flagged. This is the “honest null” the assignment asks
for.

## 8. The independent check

`tools/independent_check.py` was written as a second code path that does not import the
engine. Its first run failed with group profit 5,076,118.26 because the UK IC expense and
other expenses had the wrong sign, and total assets 14,777,225.74 because the UK asset
signs were inverted. The corrected script passes all ten numeric figures at 0.00
difference, the journal counts and the SGD null check. This was a useful reminder that an
“independent” check is only independent if it is written from the raw data, not by calling
the same functions.

## 9. Final run

```
Northwind Group consolidation - bundle NWG-D0BC
Outputs written to output

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
Issues: 19
```

The 28-test suite passes, the independent check passes, and two consecutive runs are
byte-identical. The final commit history is in `transcripts/tool-log.md`.
