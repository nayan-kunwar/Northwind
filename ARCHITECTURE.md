# Architecture — Northwind Group consolidation

**Bundle NWG-D0BC** · FY2024 · GBP · Working prototype and production design

## 1. Design stance

A consolidation is an audit artifact, not a text-generation problem. The system is built
around one rule: **every number is produced by deterministic code from identified source
rows; an LLM may suggest, explain or draft, but it never posts, calculates or overrides a
control.** The prototype is a compact version of that rule. The production topology keeps
the same rule and adds the operational pieces a real group close needs: adapters, an
evidence store, approvals, versioning and a review console.

The arithmetic core is deliberately small: about 1,500 lines of Python using only the
standard library (`decimal`, `csv`, `json`). It ingests three ERP formats, validates
mappings, triages 20 journals, translates three currencies, eliminates intercompany,
computes NCI, goodwill and the translation reserve, and writes the required outputs. The
control figures are reproduced by a second, independent script that does not import the
engine (`tools/independent_check.py`).

## 2. Production topology

```
                         ┌──────────────────────────────────────────────┐
                         │  Close Orchestrator (deterministic state     │
                         │  machine: ingest → map → journal → translate │
                         │  → eliminate → consolidate → validate →      │
                         │  publish; each state has a gate)             │
                         └───────────────┬──────────────────────────────┘
                                         │
   ┌───────────────┬─────────────────────┼─────────────────────┬───────────────┐
   │               │                     │                     │               │
┌──▼──────────┐ ┌──▼──────────┐   ┌──────▼──────┐   ┌──────────▼────┐ ┌──────▼──────┐
│ Ingestion   │ │ Canonical   │   │ Mapping     │   │ Journal       │ │ FX /        │
│ adapters    │ │ ledger +    │   │ service     │   │ triage        │ │ translation │
│ (NetSuite,  │ │ evidence    │   │ (rules +    │   │ service       │ │ service     │
│ Sage 50,    │ │ store       │   │ LLM advisor)│   │ (rules +      │ │ (determin.) │
│ Tally)      │ │ (immutable) │   │             │   │ LLM explainer)│ │             │
└─────────────┘ └─────────────┘   └─────────────┘   └───────────────┘ └─────────────┘
                                         │                     │
                         ┌───────────────▼─────────────────────▼───────────────┐
                         │ Consolidation engine (deterministic):               │
                         │ eliminations · NCI · goodwill · translation reserve │
                         └───────────────────────────┬─────────────────────────┘
                                                     │
                         ┌───────────────────────────▼─────────────────────────┐
                         │ Statement builder + validation/controls service      │
                         │ (deterministic templates, hard gates, reconciliation)│
                         └───────────────────────────┬─────────────────────────┘
                                                     │
              ┌──────────────────────────────────────┼──────────────────────────┐
              │                                      │                          │
   ┌──────────▼──────────┐              ┌────────────▼───────────┐   ┌──────────▼─────────┐
   │ Evidence / lineage  │              │ Review console         │   │ Narrative writer   │
   │ API (source refs,   │              │ (approve, hold,        │   │ (LLM, read-only,   │
   │ rates, journal IDs) │              │ override with reason)  │   │ cites evidence)    │
   └─────────────────────┘              └────────────────────────┘   └────────────────────┘
```

**Why this shape.** The orchestrator is a deterministic state machine, not an LLM
planner. Each state has a typed input, a typed output and a gate. The mapping and journal
services combine deterministic rules with an LLM *advisor*; the LLM's output is a
suggestion attached to a review item, never a posting. The consolidation and statement
services are pure functions of the canonical ledger and the approved mapping/policy set.
The evidence service is the only writer of lineage; every other service must emit source
references with its output.

**Why not a team of LLM agents?** A multi-agent LLM design would make the arithmetic
non-deterministic, hard to test and expensive to audit. It also creates a new failure mode:
agents can persuade each other. The prototype uses a single deterministic pipeline with
three narrow LLM roles. That is enough to get the benefits (mapping suggestions, anomaly
summaries, narrative) without giving up reproducibility. A 12-agent design for a
three-entity close would be over-engineering; the hard part is the data and the controls,
not the agent choreography.

## 3. Deterministic code vs LLM reasoning

| Step | Deterministic | LLM role | Why |
|---|---|---|---|
| Read ERP exports | Adapter parses fixed columns, preserves file/line | None | Parsing must be exact and reproducible |
| Map local accounts | Validator checks target exists, name/type consistency, uniqueness | Suggests candidate mappings and explains name mismatches | A wrong mapping is a judgment call; the LLM is good at fuzzy names, but a human approves |
| Journal triage | Five hard checks + semantic rules; post/reject/hold | Summarises why a journal is suspicious; drafts a review note | The decision must be rule-based; the explanation can be generated |
| FX translation | Rate table, cross-rate formula, missing-rate null | None | Arithmetic and rate selection are policy |
| Intercompany | Invoice matching, in-transit, retranslation, elimination | Explains the residual split | The split is arithmetic; the narrative is not |
| Consolidation | Eliminations, NCI, goodwill, TR | None | Must be reproducible to the cent |
| Statements | Templates, signs, totals, rounding | Drafts the commentary around the numbers | The numbers are code; the story is text |
| Validation | Hard gates, reconciliations, independent recompute | Summarises failures for the reviewer | The gate must not be persuadable |
| Audit trail | Source refs, rates, journal IDs | None | Lineage is data, not prose |

**Where the AI actually earns its place.** Three places: (1) **mapping suggestions** for
messy local charts, where the model can propose a candidate from names and descriptions
and the deterministic validator checks it; (2) **anomaly explanations**, turning a list of
failed controls into a review note that a controller can act on; (3) **narrative and
documentation**, including this document and the validation narrative. The AI does not
earn its place in arithmetic, posting, elimination or the control figures.

**Prompt-injection stance.** Text inside the data is data. The JE-006 memo is a classic
instruction attack: it asks automated reviewers to skip the balance check and hide the
entry. The engine treats the memo as a string, flags it as a security issue, and rejects
the journal because it is unbalanced. No tool call, file write or policy change is ever
driven by text in a ledger row.

## 4. Prototype data flow

```
data/*.csv, *.json, *.md
        │
        ▼
ingest.py ──► canonical TBRow / MonthlyRow / Journal / Acquisition
        │
        ▼
mapping.py ──► validated local→group maps (+ corrections, issues)
        │
        ▼
journals.py ──► posted / rejected / held (+ reasons, issues)
        │
        ▼
ledger.py ──► Posting[entity, group_account, amount_gbp, source_ref, rate]
        │        (US closing/average; UK GBP + reclass + in-transit + FX;
        │         India BS closing + H2 P&L average + journals)
        ▼
consolidation.py ──► group P&L, group BS, NCI, goodwill, TR, eliminations
        │
        ▼
statements.py ──► TB, balance sheet, P&L, changes in equity, control figures
        │
        ▼
validation.py ──► 15 coded checks + structural issues
        │
        ▼
cli.py ──► output/*.json, *.csv
```

Every `Posting` carries:

- `entity`, `group_account`, `amount_gbp` (debit-positive);
- `source_type` (`TB`, `JOURNAL`, `INDIA_H2`, `ASSUMPTION`, `INTRANSIT`, `FX`);
- `source_ref` (for example `data/tb_uk.csv:10` or
  `data/adjustments.json:102 (JE-006)`);
- `source_amount`, `source_currency`, `rate_type`, `rate`;
- a note where a judgment was applied.

The outputs inherit these references. `consolidated_tb.csv` has a `source_rows` column
per balance; `balance_sheet.json` and `profit_and_loss.json` have `source_rows` per line;
`eliminations.csv` has the source rows for each elimination; `issues.json` has file, line,
amount, currency, action and reason.

## 5. Failure modes and responses

| Failure | Detection | Response | Evidence |
|---|---|---|---|
| Wrong mapping (UK `2310 Deferred income → 4100 Revenue`) | Target exists but local name exactly matches a different group account with a different type | Correct to `2300`; log as **assumed**; disclose GBP 180,000 impact | `issues.json` `MAP-UK-2310-correction`; `DECISIONS.md` #3 |
| Trial balance does not balance | Sum of signed TB rows per entity | Block the entity; do not consolidate | `validation_report.json` `entity_tb_balances_*` |
| Journal out of balance | Debits ≠ credits | Reject; keep the imbalance in the reason | JE-006: 51,200 vs 50,000 USD |
| Journal outside FY2024 | Date compare | Reject; do not post | JE-017: 2025-01-06 |
| Duplicate journal | Same entity/date/lines/amounts as a posted journal | Reject the later one | JE-019 duplicate of JE-014 |
| Over-reversal | Debit to a credit-normal account exceeds the available balance | Hold for review | JE-009: 64,000 debit against a 41,500 accrual |
| Possible duplicate of a monthly entry | Journal description period overlaps the monthly ledger; account is systematic | Hold for review | JE-018, JE-020 |
| Unmapped account | No mapping to the group COA | Reject the journal; do not invent an account | JE-016 `IN-GST-ITC` |
| Intercompany disagreement | Invoice-level match; US AR vs UK AP | Record in-transit invoice at closing; retranslate monetary payable; split the residual | GBP 20,066.42 = 8,108.54 + 11,957.88 |
| Missing FX rate | Rate table lookup; cross-rate derivation | Return `null`, carry the booked amount, flag; never estimate | `sgd_bank_gbp: null`; `FX-UK-SGD-CLOSING` |
| Subledger difference | Control total vs TB | Post a two-sided reclass only when both sides support it; log **assumed** | UK AR/AP 45,000 |
| Acquisition period mismatch | India TB is FY25 YTD; acquisition is 1 July | Include H2 only in P&L; H1 is in acquisition net assets | `PERIOD-IN-H2` |
| Duplicate-looking TB rows | Same account code, different cost centre | Keep both; flag the check | UK 7000 CC-OPS / CC-SALES |
| Untrusted text in data | Pattern scan of memos | Treat as data; flag; never follow | `SEC-JE-006` |
| Rounding drift | Full precision internally; compare rounded totals | Add a disclosed 0.01 rounding line where components are rounded | `balance_sheet.json` equity rounding |

The general rule: **hard failures block, soft failures flag, and nothing is silently
fixed.** A correction is only made when there is deterministic evidence (a unique
name/type match, both sides of a subledger difference, an invoice-level match); otherwise
the item is held or returned as `null`.

## 6. Validation and self-correction loop

The pipeline has four gates:

1. **Ingest gate.** Every TB balances in its functional currency; every journal has an
   entity, a date, at least two lines and a debit/credit total; every FX rate has a
   convention.
2. **Mapping/journal gate.** Every TB account maps exactly once; every posted journal
   passes the five hard checks; every rejected/held journal has a reason and an issue.
3. **Consolidation gate.** Group TB sums to zero; assets = liabilities + equity; P&L
   attribution adds to group profit; intercompany reconciles after the in-transit and FX
   adjustments; NCI + owners = group equity.
4. **Publication gate.** Control figures tie to the statements; the independent
   recomputation matches; every output row has at least one source reference.

If a gate fails, the orchestrator does not publish. It writes the failure to
`validation_report.json` and `issues.json`, and a human decides whether to fix the input,
change a policy with a documented decision, or accept a flagged item. The prototype
returns a non-zero exit code when any check fails, so CI can block a bad close.

The **self-correction loop** is deliberately asymmetric: the engine can correct a mapping
only when the evidence is unambiguous; it can correct a journal only by rejecting or
holding it, never by editing it; it can correct a translation only by using a rate that
exists, never by estimating. The loop is: detect → classify (hard/soft) → apply the
narrowest safe action → record evidence → re-run the full gate. A re-run is idempotent:
the same inputs produce byte-identical outputs (verified by hashing two runs).

## 7. How an auditor traces a figure

Take `group_revenue = 28,301,607.81`:

1. Open `output/profit_and_loss.json`; the revenue section has three lines (US, UK,
   India) with `source_rows`.
2. The US line points to `data/tb_us.csv:18`; the UK line to `data/tb_uk.csv:16`; the
   India line to `data/in_pl_monthly.csv:5-10` (H2 only).
3. Open `output/consolidated_tb.csv`; account `4100` has the same total and the same
   source refs.
4. Open `output/eliminations.csv`; `ELIM-02` shows the intercompany income and expense
   eliminated, with the source rows and the GBP 1,966.21 policy-5 difference to `7300`.
5. Open `data/fx_rates.csv`; the rate types used are named in the posting (`average`,
   `closing`, `h2_average`, `spot`). The cross-rate formula is in `northwind/fx.py` and
   in policy 2.
6. Open `output/issues.json`; any judgment (mapping correction, reclass, in-transit
   invoice, missing rate) is listed with file, line, amount and action.

The chain is **statement line → consolidated TB row → posting → source file/line or
journal ID → rate/policy**. Every link is a string in the output, not a memory of the
analyst. That is what makes the figures signable.

## 8. Human-in-the-loop and production concerns

- **Approvals.** Mapping corrections, journal holds and inferred entries require a
  controller approval. The approval is stored with the issue ID, the approver and the
  timestamp; the next run reuses the approved decision instead of re-asking.
- **Versioning.** The canonical ledger is append-only. A re-run creates a new close
  version; the old version and its evidence bundle remain available. Inputs are hashed
  (the bundle ID is the natural anchor).
- **Idempotency.** Outputs are deterministic; the same input hash and policy version
  produce the same bytes. This is tested.
- **Access control.** The evidence store is read-only for analysts; the posting service is
  write-only through approved journals; the LLM has no write credentials.
- **Scale.** At thousands of accounts and dozens of entities, the bottlenecks are mapping
  coverage, intercompany matching and FX rate coverage, not arithmetic. The design uses
  per-entity adapters, a canonical account map, invoice-level matching and a rate table
  with explicit missing-rate behavior. The consolidation itself is a linear pass over
  postings plus elimination rules.
- **What the prototype does not include.** A database, a UI, authentication, multi-user
  approvals, a scheduler, a full audit log service, and a production-grade ERP connector.
  The prototype is the arithmetic and evidence core that those pieces would wrap.

## 9. Limits and deliberate choices

- **No estimate for missing rates.** The SGD bank is carried at book value and the control
  figure is `null`. This is less satisfying than a number, but it is the only defensible
  answer from the inputs.
- **No invented GST account.** JE-016 is rejected rather than mapped to a plausible but
  unsupported group account.
- **No silent journal edits.** JE-006 is rejected, not repaired; JE-009/018/020 are held,
  not posted. The engine never changes a journal to make it balance.
- **Historical-cost investment elimination.** The UK and India investments are eliminated
  at historical cost, not at the closing-rate carrying amount; the closing-rate difference
  is not a group asset. This is documented in `DECISIONS.md` and `issues.json`.
- **One-command reproducibility.** `python run.py` is the contract. The tests and the
  independent check are the evidence that the contract holds.

## 10. Why this is the right amount of AI

The prototype uses AI where the input is fuzzy and the output is a suggestion: mapping
candidates, anomaly narratives, documentation and adversarial review. It does not use AI
where the input is a ledger and the output is a signed number. That boundary is the
architecture. It keeps the system fast, cheap and testable, and it keeps the auditor's
question — “show me the source row” — answerable for every figure.
