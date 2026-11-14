# Hookshot progress feed

The public source is `MagicBeanDev/Hookshot` on MagicBean's Forgejo instance.
The collector uses its `/api/v1/repos/MagicBeanDev/Hookshot` API and follows only
same-endpoint pagination links. It includes all open issues and pull requests,
closed items updated within 90 days, up to 20 published releases and the latest
stable release. No stable release is represented explicitly, without borrowing
another project's releases. Previous repository curation is not reused.

## Collection and hosting

The site's build collects the feed (`src/lib/progress-feed.mjs`, `buildFeed()`), once per build, and publishes it as
`/progress-feed.json` (`src/pages/progress-feed.json.ts`) and in the front page's release and activity panels. Nothing
is committed and no server runs: the data is as fresh as the last build, and the website workflow rebuilds it every
hour. Each API request allows 30 seconds (including its JSON body) and up to three attempts for timeouts, temporary
network errors, HTTP 408/429 and HTTP 500/502/503/504. Retries wait 1 then 2 seconds, or a longer `Retry-After` up to
30 seconds. Authentication errors, invalid JSON, private sources and unsafe pagination fail without retries.

If collection fails, a local build can still render the unavailable-data fallback. `npm run check` rejects that
fallback or any malformed feed before publication. Both the Website workflow and `npm run deploy` run this check
before uploading a deployment, leaving the existing deployed site in place if it fails. Collection fails as a whole
if any required page fails or a pagination limit is hit; partial results are never published. Check the collection
log for the endpoint, failure and attempt count, then rebuild after recovery. No extra API permission is required.

`FORGEJO_TOKEN` is optional and build-only: it is never sent to browsers or written to the feed. The collector rejects
private repositories and redirects. Public collection needs no account token. The progress board refetches
`/progress-feed.json` every five minutes while visible, which picks up a newer build.

## Editorial maintenance

Keys in `progress-curation.json` use `issue:123`, `pull:456` or `release:789` (the release ID, not tag).
Each entry needs `title`, `summary`, `reviewedAt` (ISO date), `sourceUpdatedAt` (exact API timestamp), and `sources`
(public URLs under `https://git.magicbean.dev/MagicBeanDev/Hookshot/`). Optional `platforms` contains `Windows`, `Linux`,
`Steam Deck`, or `Other`; optional `area` is `Graphics`, `Performance`, `Controls`, `Audio`, `Setup`, or
`Documentation`, `Crashes or startup`, or `Sound, controls or saves`; optional `workaround` is plain text.
Optional `impact` is `Crashes`, `Save integrity`, `Cannot start`, or `Blocked progression`; it enables the reviewed
serious-issue highlight only when the report explicitly matches the current stable version. Do not add speculative fixes, dates or progress percentages.
Review timestamps appear with curated advice. If a source's update timestamp changes the entry falls back to
the original title and neutral status explanation. The collector rejects malformed editorial entries.

Only metadata, labels, selected report-form version/category values and reviewed prose are published. Issue/PR bodies, comments, attachments, author accounts
and downloaded assets are excluded. Text is rendered with textContent, never interpreted as HTML/Markdown.
Links are constructed from the fixed public upstream repository and validated again in the browser.

## Modules for future updates

| Module | Source | Purpose |
|---|---|---|
| Development at a glance | `src/components/ProgressOverview.astro`, `src/lib/progress-overview.mjs` | Explain open reports, review proposals, recent merges and stable releases. |
| Current version watch | `src/lib/progress-watch.mjs` | Match exact report versions, group reported areas and separate other/unknown versions. |
| Searchable work | `src/components/ProgressBoard.astro`, `src/lib/progress-board.ts`, `src/lib/progress.mjs` | Search, filters, progressive results, freshness and plain-language status explanations. |
| Reviewed highlights | `progress-curation.json` | Sourced summaries, platform tags and serious reported impacts, invalidated by source changes. |
| Help and status guide | `src/content/docs/progress.mdx` | Explain what the data means and link players to practical help. |
| Feed | `src/lib/progress-feed.mjs`, `src/pages/progress-feed.json.ts` | Collect public data at build time, following verified cursor links. |

The overview is descriptive, not a roadmap commitment. No module treats counts as unique bugs, developer speed,
completion percentages or affected-player totals. The current-version watch intentionally misses unstructured
reports and reports updated only in comments; source links remain essential. Editorial summaries are reviewed
against reports, not claims of independent reproduction.

Issue-search links (including front-page queries) move the complete search panel
ahead of the development overview and version watch, then focus and position the
input after layout. Feed updates stay below search and cannot push it down the page.
Opening Progress normally retains its overview-first order; background refreshes
do not repeat the focus/scroll action.

## Validation

Run `npm run build:preview` to build, check links and source guards, and run the
website tests. Tests cover normalization, pagination, unsafe source URLs, private
repositories, curation expiry, cache failures, version matching, search and filters.
A source/build check does not replace desktop/mobile, keyboard or theme review.
