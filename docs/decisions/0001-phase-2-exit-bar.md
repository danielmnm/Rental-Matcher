# 0001: Phase 2's exit bar: from "zero wrong" to error budgets by consequence

Status: accepted, Nov 6 2026 (owner ruling: "do what works best, be transparent"). Written and committed before
the changes it motivates were measured, and before batch 14 is fetched.

## Context

Phase 2's second exit criterion was the Card test: on a fresh held-out batch, 0 wrong answers, no listing
hidden by a misreading for any must-have, and at least 95% of settled facts read on every question.

Five fresh batches were measured against it (rules frozen before each one was fetched, two blind labelers
in private folders, nothing fitted on a batch before it was measured):

| Batch | Date | Card listings | Wrong | Hidden | Settled read |
|---|---|---|---|---|---|
| 10 | Oct 30 | 253 | 12 | 3 | 97% |
| 11 | Nov 2 | 243 | 12 | 2 | 98.4% |
| 12 | Nov 3 | 270 | 12 | 4 | 97.6% |
| 13 | Nov 5 | 263 | 12 | 2 | 98.1% |

Coverage rose; wrong answers stayed flat. Each batch's misreadings were fixed, and the next batch brought
the same kinds of mistake in new words. That is the long tail of a pattern reader, and the plateau was
visible after batch 11. Two more batches were run before the question was raised. That was a mistake in
process, not a finding about the reader.

Measured on batches 10 to 13 together (1,029 card listings, frozen runs as measured;
`/tmp` script reproduced in `tests/test_bar_v2.py`):

- Wrong answers: 45 of 7,412 definite answers on the card, **0.61%** (95% CI 0.45 to 0.81%).
- Furniture alone: 28 of 442 answers, **6.3%**. Every other question together: 17 of about 6,970, **0.24%**.
- The two blind labelers give the same answer on 99.0% of facts (Cohen's kappa 0.96); they differ most on
  parking (3.1%) and furniture (3.2%).
- At 0.61%, the chance of a batch of about 1,600 answers with none wrong is about 1 in 16,000. A reader
  six times better (0.1%) would still fail "zero wrong" four times in five.
- Of the 11 listings hidden by a misreading, 3 were settled by the owner's rulings; 4 came from a bare "חדר"
  read as renting a room, 2 from "חניה בשפע" read as street parking, 1 from a unit with a garden, 1 from
  Yad2's parking box.

So "zero wrong" is not a bar a reader of free text can be expected to pass, whatever the method: it is
stricter than two careful people agree with each other.

## Decision

The bar becomes an error budget per consequence. A wrong fact that can hide a listing costs the user a
flat they never see; a wrong furniture item is a line on a card they can read for themselves.

**Card test v2**, on one fresh batch of at least 250 listings, rules frozen before fetching, two blind
labelers, measured once:

1. **Hidden: 0.** No listing hidden by a misreading, for any must-have any user could set. Unchanged, and
   made true by design: a reading inferred rather than stated is shown as a check, never used to hide.
2. **Facts that can hide or rank a listing** (every question except furniture): at most **0.5%** of the
   card's definite answers wrong overall, and at most **2%** on each question.
3. **Furniture** (never hides a listing; scoring.py has no path from furniture to "hidden"): at most **3%**
   of the card's furniture answers with a wrong item or claim. 3% is about the rate at which the two
   labelers' furniture lists differ.
4. **Coverage floor**, so abstaining can't buy precision: at least **90%** of settled facts read overall,
   and at least **85%** on every question (furniture with partial credit for a partial list).

Results are reported with 95% Wilson intervals. Earlier batches are context, not the test: they have
all been fitted on.

## What changes in the reader (v1.60), and why

- **Inferred readings become checks, so they can't hide a listing.**
  - A bare "חדר ... להשכרה/בדירה" with no word about sharing (שותף, שותפים, a shared kitchen) is a check,
    not "a room in a shared flat". 4 of the 11 hidden listings.
  - "חניה בשפע" with no word that places it is "street parking, or the building's": a floor that can't
    hide a listing from a "building parking" must-have. 2 of the 11.
- **Furniture: a lone word isn't a claim.** A closet, table or TV word in a sentence that says nothing
  else about furniture (no other item, no ריהוט/מרוהט/מאובזר) is left out of the list. Kitchen cupboards,
  storage cupboards and a "dining area" were most of furniture's wrong answers.
- Batch 13's own families, as after every measured batch: "חוץ מ" (except) like "מלבד", an equipped
  bathroom isn't appliances, "מרוהט בחלקו" is partly furnished, a unit "בבית פרטי" is a unit, "קרוב
  לחניות" isn't the flat's parking, a safe room "5 מטר מהדירה" isn't in the flat.

## Consequences

- Coverage falls where readings become checks; the floor in (4) bounds how far.
- One fresh batch (14) under this bar closes criterion 2 or doesn't. If it doesn't, the misses are
  reported as measured and the next step is decided with the owner before any further batch.
- What this does not fix: the reader still meets new wordings. The budget says how many it may miss.
