# 0002: Closing Phase 2 with furniture as a known limitation; judging accuracy on pooled batches from now on

Status: accepted, Nov 7 2026 (owner ruling: "yes proceed").

## Context

Batch 14 was the first fresh batch judged by Card test v2 ([0001](0001-phase-2-exit-bar.md)), with the rules frozen
at v1.60 before it was fetched. As measured:

| Check | Budget | Batch 14 | |
|---|---|---|---|
| Listings hidden by a misreading | 0 | 1 | not met |
| Wrong, facts that can hide or rank a listing | 0.5% overall, 2% per question | 3 of 1,795 (0.17%); worst question parking 1.2% | met |
| Wrong, furniture | 3% | 5 of 125 (4.0%; 95% CI 1.7 to 9.0%) | not met |
| Settled facts read | 90% overall, 85% per question | 98.1%; lowest question 90.6% | met |

Two things about the misses:

- **The hidden listing** (yzmx3b2p) says only "חניה בבניין". The card read the building's parking. the owner ruled on Nov 5,
  before batch 14 was fetched, that "בבניין" without "צמודה" or "בטאבו" is the building's and not a deeded space; the
  blind labelers also allowed deeded, which is what makes it count as hidden. The same ruling was applied to batches 11
  and 12 (lj4mlmq9, axx11t41) as adjudications.
- **Furniture's budget was judged on one batch's count, which can't carry it.** At a true rate of exactly 3%, 5 or more
  wrong in 125 answers happens about one time in three; the interval on 5 of 125 runs from 1.7% to 9.0%. A single batch
  can't tell 3% from 4%. That is a flaw in how decision 0001 set the check, not a finding about the reader.

## Decision

1. **Batch 14 stays on record as measured** (not met, two checks), in `tests/test_holdout14.py` and the README. the owner's
   standing ruling is applied to yzmx3b2p as an adjudication (`tests/eval/holdout14/adjudications.json`), and both numbers
   are reported: hidden 1 as measured, 0 with the ruling.
2. **Phase 2's second exit criterion is closed as "met for everything that can hide or rank a listing, with furniture a
   known limitation"**: 4.0% wrong on one fresh batch against a 3% budget. Furniture can't hide a listing (scoring.py has no
   path from it to "hidden"; `tests/test_bar_v2.py` checks that), so its errors cost an inaccurate chip, never a missed flat.
   On the card it stays information, not a filter.
3. **Fix forward.** The four furniture families batch 14 found become rules with permanent tests (v1.61), and the parking
   check's wording is corrected: it was written for Yad2's ticked box and read wrong for "plenty of parking by the
   building".
4. **From now on, accuracy is judged on held-out batches pooled together, with a 95% interval**, not on one batch's point
   estimate: a budget is met when the pooled rate's upper bound is within it, or flagged when the pooled point estimate is
   over it. Each new fresh batch (or real-use sample) is added to the pool after it is measured once with frozen rules.
   This applies to future phases; it doesn't rewrite batch 14's result.
5. **Furniture keeps being measured in real use** (Phase 3), against the same 3% budget, on the pooled rule above.

## Consequences

- Phase 2 ends with its limitation written down instead of a fifteenth batch chasing one percentage point on a field that
  can't hide a listing.
- The reader is still a pattern reader: it will meet new wordings. The pooled budgets and the review page are how that
  shows up, and the lessons and right-facts ratchets are how a fixed misreading stays fixed.

## Addendum (Nov 8, the owner)

Furniture is lenient for now, being the least significant part of an apartment, and **perfecting its reading is
planned later work**, not dropped: it stays measured on every batch, and a dedicated pass comes after Phase 3.
