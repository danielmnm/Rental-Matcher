# 0004: Phase 3 closes with known limitations

Status: decided by the owner, Nov 25 2026.

## Context

Phase 3 ("more sites, any area") was timeboxed at 2 to 3 days, about four working sessions, with a stop rule: a measure that
stalls across two rounds goes to the owner before a third. It ran from Nov 7 to Nov 25. The stop rule should have fired after Komo's
second round (Nov 9); Komo went on to rounds 3 and 4 instead. An independent critic review (Nov 25) said so, and recommended
closing the phase the way decision 0002 closed Phase 2.

Where each step stood:

| Step | Result |
|---|---|
| 1. Any area by settings | Done: a new city and commute destination by settings alone |
| 2. Komo card accuracy | 0 listings hidden by a misreading in batch 4; wrong on facts that can hide or rank 0.35% to 0.62% pooled over four fresh batches (0.62% as counted; 0.35% with the owner's view of the 8 batch-4 texts), budget 0.5%: not shown |
| 3. Duplicates across sites | Met: 0 wrong joins of 557 (95% upper bound 0.68%, budget 1%); about 90% of twins joined (budget 80%) |
| 4. Madlan | 41 of 98 sample pages read before Madlan's bot check came after every 1 or 2 pages |
| 5. The Finder | Decision 0003, proposed and deferred to now |
| 6. Facebook, view-only | Built (v1.66), not measured |

## Decision

Close Phase 3 now (path A). Concretely:

- **Komo** is recorded as: no listing hidden by a misreading; 0.35% to 0.62% wrong on ranking facts, under 0.5% not shown. A
  known limitation, like furniture in decision 0002. Batch 4's three parking misreadings are fixed (v1.68). Its two shared flats
  read as whole stay as they are: the rule they came through (a bedroom count means a whole place) is right 342 times in 347, and
  the phrasings that would have caught them were either too rare to trust or wrong far more often than right ("ל-3 שותפים" means
  a whole flat for roommates 7 times in 9). A price-per-room check in Phase 5 is the safety net for them.
- **Madlan** is reported from its 41 pages: the card against what each page displayed. Its adapter read several of Madlan's
  field names wrong; fixed in v1.68 and checked on the same pages (in-sample, said so).
- **The Finder**: decision 0003 is accepted. No adapter.
- **Facebook** is measured through real use, when real posts are kept.
- **Labeling**: the owner's "דירה ..." ruling goes into the labeling guide, so the next labeled set doesn't re-break the same
  convention (103 of batch 4's 108 "wrong" answers were that).

## \* What path B would have bought

More Komo batches would narrow Komo's range: about 6,000 graded facts (3 or 4 more fresh batches) to show it under 0.5%, if it is.
the owner opening about 60 more Madlan pages by hand would narrow Madlan's range. Both can be done later. They improve how well the
numbers are known, not what the product does, and nothing about the product's principles depends on them now. They are left as
optional work, not open obligations.

## Consequences

- Phase 4 starts. Work goes to what the product and the portfolio need: a readable front page for the repo, the commute search
  (the product's differentiator) and an installable demo.
- The stop rule stands for later phases, and is applied: a measure that stalls across two rounds goes to the owner before a third.
