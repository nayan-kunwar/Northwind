# Reflection

**Bundle NWG-D0BC** · one page

## What I would build differently with three months

With twelve hours I optimized for a defensible arithmetic core and a complete evidence
trail. With three months I would keep that core and build the parts that make it a
product:

1. **A mapping workbench, not a mapping file.** The hardest errors here were mapping
   errors (UK 2310 to revenue; the zero-padded 30/31 codes). At scale, mappings change
   whenever an ERP adds an account. I would build a versioned mapping store with owner,
   effective dates, confidence, a diff view and an approval workflow. The LLM would
   propose; the controller would approve once; the approval would be an auditable object.
2. **Invoice-level intercompany matching as a service.** The 20,066.42 difference was
   small enough to solve by hand. At dozens of entities it becomes a matching problem:
   invoice IDs, dates, currencies, partial payments, in-transit items, intercompany profit
   in inventory. I would build a matching engine with tolerances, a suspense account and an
   ageing dashboard for unmatched pairs.
3. **A real FX and evidence service.** The missing GBP/SGD closing rate is a warning about
   a fragile dependency. I would integrate a rate provider with a controlled fallback:
   direct rate, cross-rate, contractual rate, then `null` with an owner and an SLA. Every
   rate would carry a source, timestamp and convention, and every run would store the input
   hash, policy version, mapping version, rate snapshot and approval set in an immutable
   evidence bundle.
4. **A synthetic test harness and a review console.** The current tests are specific to
   this bundle. I would generate groups with different ownership, currencies, acquisition
   dates, intercompany patterns and broken data, and run them in CI. The console would
   give controllers a queue of exceptions with amounts, owners, evidence and a decision,
   and the next run would reuse the decision.

## Where the prototype would break at scale

- **Mapping coverage.** Thousands of accounts across dozens of charts makes the mapping
  table the bottleneck. The name/type heuristic is deliberately narrow; it needs a
  workbench and a coverage metric.
- **Intercompany combinatorics.** Three entities have three pairs; fifty have 1,225. The
  invoice match is linear, but exception handling is not. The in-transit logic here is one
  documented assumption, not a general matching engine.
- **FX coverage.** Every entity/currency/rate-type combination is a potential gap. The
  flat rate dictionary needs effective dates, fallbacks and ownership.
- **Statutory and tax layers.** The prototype consolidates management accounts. It does not
  handle local GAAP adjustments, deferred tax, transfer pricing, withholding tax or
  statutory revaluations — where real closes spend most of their time.
- **Ownership changes.** India is a clean 80% acquisition on 1 July. Production needs step
  acquisitions, disposals, NCI remeasurement and pre/post-acquisition splits.
- **Human throughput.** The engine closes in seconds; the reviewers cannot. The bottleneck
  moves to exception resolution, which is why the review console matters more than another
  agent.

## One thing the problem underestimates

The problem is framed as a consolidation exercise, but the expensive part is **proving**
the consolidation. The arithmetic is a few hundred lines. The mapping governance, the
invoice-level intercompany reconciliation, the missing-rate policy and the evidence for
every judgment are what take the time — and they are what a CFO actually signs. A system
that produces the right numbers but cannot show the source row, the rate and the approval
is not usable in a close. The most valuable thing I built is not the consolidation formula;
it is the chain from a statement line to `data/tb_uk.csv:10` or
`data/adjustments.json:102`, with the judgment recorded next to it. At scale, that chain
is the product.
