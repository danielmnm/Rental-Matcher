# Rental Matcher

A rental-listing matcher for Israeli sites (Yad2, Komo, Madlan; Facebook view-only). It turns messy, duplicated listings into one clean record and ranks them by what matters to *you*, including real commute time.

## Why

Rental listings in Israel are spread across several sites, written inconsistently and often duplicated, so finding a flat that really fits takes hours of manual reading.

## How it works

- **Chrome extension + local Python helper.** Everything runs on the user's computer; no user data leaves it.
- **Site adapters** map every listing into one canonical schema (`schema/listing.schema.json`, versioned with automated migrations) with confidence-tagged signals.
- **Deterministic reading rules first**; an AI model (Gemini) handles only what code can't, and disagreements become "check this" instead of guesses.
- **Duplicate matcher** merges the same flat across sites, never merging two separate listings.
- **Scoring engine** ranks listings by the user's own preferences (importance 1-10; 10 = dealbreaker) with commute-based search (anchor address, travel mode, max time).
- The extension only reads pages the user opens; nothing is fetched automatically from sites that forbid it.

## Measured, not guessed

Accuracy is judged on the card the user sees, on held-out batches fetched after the rules were frozen, with blind labelling and error budgets written down first (see `docs/decisions/`). The duplicate matcher made 0 wrong joins out of 557 across three fresh samples.

## Layout

```
rental_matcher/   Python package: adapters, extraction rules, scoring, dedup, commute, local server
browser/          Chrome extension (content scripts, popup, tests)
schema/           listing schema + its version history
docs/decisions/   decision records (accuracy bar, phase exits, site choices)
tests/            unit and integration tests
```

## Run it

```
pip install -r requirements.txt
python -m rental_matcher.install --deps   (creates preferences/my.json from the example on first run)
python -m pytest tests
```

Your preferences file (preferences/my.json) starts as a copy of preferences/example.json, is edited from the extension, and stays local (`preferences/*.json` is git-ignored). Some evaluation tests need the raw listing samples, which are not published because they contain third parties' contact details.

## API keys

Rental Matcher uses two outside services. Each user brings their own free key; no keys ship with the code, and key files are git-ignored.

| Key | What it's for | Where to get it | Without it |
|---|---|---|---|
| Gemini | Reading free-text listings into structured fields | [Google AI Studio](https://aistudio.google.com/apikey) (free tier) | The AI reading step stops with a message saying how to add a key |
| TomTom | Traffic-aware commute times and address search | [TomTom Developer Portal](https://developer.tomtom.com/) (free tier) | Commute times are computed without live traffic |

Put each key in one of two places on the machine that runs Rental Matcher:

- an environment variable: `GEMINI_API_KEY` / `TOMTOM_API_KEY`, or
- a one-line file in the repo folder: `.gemini_key` / `.tomtom_key`

Never commit these files or paste keys into issues.

## Status

v1.68 · Phases 0-2 done (schema, reading, scoring, dedup), Phase 3 (more sites) in progress. Built by Daniel Mendel.
