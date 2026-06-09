# Future ideas

Features that would be useful to add but haven't been implemented yet.
Roughly ordered by implementation effort.

## Tier 1: Trivial (single API field or ~20 lines)

- **Short description present** — check for `{{Short description|...}}` in wikitext.
  Missing short description on a new article is a MOS violation that NPP reviewers
  commonly flag.
- **Wikidata item linked** — check `prop=pageprops` for `wikibase_item` key. A page
  with no Wikidata item is disconnected from the knowledge graph.
- **Page image available** — check `prop=pageimages` for a `thumbnail` key. Missing
  image on a subject that should have one (person, place, film) can indicate a rushed
  or low-effort article.
- **Creator's account age** — `list=users&usprop=registration` gives the account
  creation date. A 3-hour-old account creating an article is very different from
  a 10-year-old account.
- **Creator's article creation count** — `list=usercontribs&ucnamespace=0&ucdir=newer`
  filtered to `new` type gives the user's prior article count. First-time creator vs
  experienced article writer is a strong signal.

## Tier 2: Easy (one extra API query)

- **Copyvio probability** — use Earwig's Copyvio Detector API
  (`https://copyvios.toolforge.org/api`). Returns a confidence percentage. Very
  high-value signal for NPP.
- **Autopatrolled status** — check if the creator is on the autopatrolled list
  (`list=users&usprop=groups`). Autopatrolled users' pages are trusted and can
  be skipped entirely.
- **CSD criteria matching** — scan the page for common CSD triggers: copyright
  violations (G12), promotional/spam language (G11), attack content (G10), patent
  nonsense (G1), no content (A3), no indication of significance (A7).
- **AfD history of similar titles** — check logevents for similar title patterns
  (e.g. if "Foo Corp" was deleted, also check "Foo Corporation", "Foo Corp Inc").

## Tier 3: Medium (new external API or more complex logic)

- **Creator warning history** — check the creator's talk page for maintenance
  templates (`{{uw-*}}`, `{{subst:}}` warnings). A user with multiple CSD/AfD
  warnings is a stronger signal.
- **Interlanguage links** — check if the article is a translation (via
  `prop=langlinks`). Translations from other wikis may have different quality
  baselines and attribution requirements.
- **Machine-translation detection** — use the Lift Wing model for language
  identification or a heuristic (e.g. character n-gram analysis) to flag possible
  machine-translated articles.
- **Stub threshold for size** — an optional `--min-size` flag to filter out pages
  below a byte threshold, since very small pages are a known problem category.

## Tier 4: Larger features

- **Review priority score** — combine multiple signals (no URL refs + new creator +
  no infobox + predicted Stub + no categories) into a single numeric priority score
  that sorts the output. Higher score = more urgent review.
- **Diff-based analysis** — compare the current revision to its predecessor
  (for pages that have been edited since creation). New content added without URLs
  is a different signal than a single creator who never included any.
- **Interactive filtering** — instead of a one-shot CLI, run a dashboard (via
  `fzf`, `rich`, or web) where the reviewer can filter, sort, and drill into pages
  interactively.
- **Batch wikitext download** — an `--export-wikitext` flag that saves the raw
  wikitext for all matched pages to local files, so reviewers can inspect them
  offline or grep for specific patterns.
- **Scheduled runs** — a cron-friendly `--notify` flag that runs daily and sends
  a summary (new matches since last run) via email, webhook, or Wikipedia talk
  page.

## Unsortable / niche

- **Detect references to Wikipedia itself** — scan for interwiki links to other
  Wikipedia articles inside `<ref>` tags (a misuse of the reference system).
- **Reference format consistency** — flag pages that mix different citation styles
  (e.g. numbered footnotes with author-date short refs).
- **BLP auto-flag** — if the article is categorized as a biography of a living
  person but has zero URL references, flag it at the highest priority (BLP policy
  requires verifiable sources).
- **Source reliability hints** — cross-reference URLs against the NPP Source Guide
  (WP:NPPSG) to highlight known unreliable sources.
