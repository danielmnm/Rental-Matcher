# 0003: The Finder is not read as a source

Status: **accepted** at the close of Phase 3 (decision 0004, Nov 25 2026). Proposed Nov 19 (Phase 3, step 5: "first check
whether it can be read at all"); the owner deferred it to the end of the phase.

## What was checked

Three page loads in Claude's browser on Nov 19, nothing automated beyond that: the home page, the terms of service and the
public search page (thefinder.co.il).

- **What it is.** A paid alert service, not a listing board: "הבוט החכם שלנו סורק את כל המקורות ושולח לכם התראות" (its bot
  scans every source and sends alerts), over Telegram and WhatsApp, with a 3-day free trial. Its site claims more than 11,000
  users and 9,900 apartments added this month (its own figures, not checked). Coverage is Tel Aviv and the center: the search
  page offers Tel Aviv, Ramat Gan, Givatayim, Herzliya and Jaffa.
- **Its listings are other sites' listings.** The terms say the service "סורק באופן רציף מקורות שונים" (continuously scans
  various sources). The search page shows 100 cards with no link to the original post and no source name.
- **Its text isn't the poster's.** Many cards read as rewritten summaries in one template ("דירה בת 2 חדרים, 20 מ"ר, שכונת
  ..., מחיר: 3,000 ₪. קומה 1"); several show a rent of 0 and a size of 0.
- **Terms.** Among the user's obligations: "לא להעתיק, לשכפל או למכור את השירות" (not to copy, duplicate or sell the service).

## Decision (proposed)

No adapter for The Finder.

1. **Reading it would copy a service whose terms say not to.** The other sites restrict automated access in general; this one
   is itself the scanner, and copying its output is copying the service.
2. **It adds nothing we can stand behind.** Without the original link a card can't be checked, can't be deduplicated against the
   same flat on Yad2, Madlan or Komo (the matcher needs the address; most cards have no house number), and can't send the user
   to the real poster.
3. **Our measured accuracy wouldn't apply.** The reader is measured on posters' own words. A rewritten summary is a different
   text; facts it drops (parking, the safe room) would read as "not stated".
4. **What it might add is Facebook groups.** Those stay view-only, read from posts the user has open (Extension Plan), not
   second-hand.

## Consequences

- The schema keeps `Source.THE_FINDER`, so the decision can be reversed with an adapter only, if the service ever publishes
  links to originals or a feed it permits.
- For Phase 6 (the product question), The Finder is direct competition: the same promise (scan every site, alert in real time),
  already paid and claiming a five-figure user base. Its search page lists the filters it offers (rent, size, rooms, balcony,
  parking, safe room, furnished, no-broker) and nothing like a match score, commute time or "check this" notes.
