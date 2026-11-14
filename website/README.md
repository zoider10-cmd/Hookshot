# Hookshot website preview

Astro/Starlight front page and player documentation for Hookshot by Team MagicBean.
The game build is independent of this directory. This branch adds source only: there
is no automatic deployment or publishing workflow.

## Local preview

Use Node 22.23.4 or newer with the pinned lockfile. From `website/`:

```sh
npm ci
npm run build:preview
npm run preview -- --host 127.0.0.1 --port 4321
```

Open http://127.0.0.1:4321/. `npm run dev` provides live editing.
The project base is `/`, for its own domain (hookshot.magicbean.dev).
`DOCS_SITE_URL` sets the canonical HTTPS origin; its default is `https://magicbean.dev`,
which is metadata, not an enabled deployment or a claim that this site is hosted there.

`npm run build:preview` builds and checks with edit links to this fork's
`docs/hookshot-website` branch. Normal `npm run build` and `npm run check` also accept
`DOCS_SOURCE_REPOSITORY` and `DOCS_SOURCE_BRANCH` for another Forgejo fork/branch.
Project and issue links use https://git.magicbean.dev/MagicBeanDev/Hookshot.

## Design and interaction

The front page has Guides, Help, Development, Team and About navigation, site search, light/dark
controls, and team credits. The main Grappling Hook Bean becomes the Glowing Fairy
Bean after three clicks, taps or keyboard button activations. Reload resets it.
A failed image load keeps the original artwork and allows a retry.
The hero artwork gently bobs over six seconds, matching the main MagicBean homepage.
Hovering or focusing the bean pauses it; reduced-motion preferences disable the sway.
The button and focus outline stay stationary, including after the fairy swap.

The homepage's bean punchline changes once per page load from ten short lines.
Session storage prevents an immediate repeat across reloads in the same tab when
available. Blocked storage still allows a random line; no JavaScript keeps the
original “Slightly emotional beans.” There is no timed rotation or animation.

At narrower widths the main links use an Explore Hookshot disclosure, including a
no-JavaScript fallback. With JavaScript, Escape, an outside click or choosing a link
closes it. Shared-memory GPUs have a separate checker choice; their memory remains
a caution rather than being compared to dedicated VRAM. GPU changes update the
automatic choice until the user chooses a memory type themselves; Reset restores it.

The team logo, Hookshot icon and supplied bean illustrations are copied unchanged
from `../assets/branding/`; their provenance is recorded there. The upstream README's
own `../assets/hookshot.png` is preserved separately.

Body text and controls use self-hosted Atkinson Hyperlegible Next, weights 200–800,
upright and italic. Libertinus Serif Semibold remains for large headings; code stays
monospace. Libertinus is served as full-character WOFF2 files to reduce font downloads;
the original TTFs remain alongside them. `src/assets/fonts/libertinus/WOFF2-PROVENANCE.json`
records the encoder, source hashes and reproduction command. No encoder is required
for normal website builds. Font provenance and original notices are retained in
`src/assets/fonts/` and `public/fonts/`. No external font service or game-extracted
fonts are used.

## Team page

The team page (`/about/team/`) lists the people with the most commits in Hookshot (Hookshot's history included),
collected from Forgejo when the site is built (`src/lib/contributors.ts`). There is nothing to add by hand: a merged
change puts you there at the next build.

## Content and source guards

`content-sources.ts` lists the imported pages, each site path with the file it is made from. Edit their original files in `docs/`,
`README.md` or `CONTRIBUTING.md`, not `src/content/docs/generated/`. Content preparation
copies only the explicitly selected pages and artwork. Other relative references
link to the team's Forgejo source tree; website instructions link to this fork branch. New internal documents are not automatically
published.

The System requirements page (`src/content/docs/compatibility.mdx`) is a copy of the root README's "What you need":
when one changes, change the other to match.

The progress board and the front page's release and activity panels are collected from Forgejo when the site is
built; see `PROGRESS.md`.

The reference manual, contributor guide and saves guide are generated directly from
`README.md`, `CONTRIBUTING.md` and `docs/saves.md`. They have one maintained source;
the generated copies are ignored by Git and rebuilt automatically. Historical
acknowledgements and literal migration commands are preserved, not rebranded.

The manual's presentation transform puts installation first, adds platform shortcuts
and folds advanced reference sections into native disclosures. It preserves the
source text and heading anchors; linked sections open automatically. Expand/collapse
controls and print handling keep the full reference accessible. The getting-started
guide uses cards while retaining its original source in `docs/`.

The manual renders the README's minimum/recommended specs table; the System requirements page has its own copy
(see above). Requirements without a published minimum or separate recommended tier are labelled explicitly; the table
does not establish performance targets or replace GPU-status caveats.

Save and update guides use Easy beans for everyday launcher steps and Advanced beans
for optional reference details. Their canonical sources remain `docs/saves.md` and
`docs/updates-and-saves.md`; generated cards and disclosures preserve existing anchors.

The graphics guide imports choices and defaults from the README's in-game menu table
at build time. Section names and order come from `gpu/vk/vk_menu.cpp`; mismatched,
missing or malformed rows stop the build. No network request or running game is needed.
Edit those original sources, not the generated cards. Restart badges reflect explicit
README annotations; absence of a badge is not a promise about every build or mode.
Search and section filters enhance native disclosures; without JavaScript every card
remains available. Setting links clear filters and printing includes the whole catalogue.

The tested-configurations catalogue (`/tested-configurations/`) is assembled by the same repository-doc loader from
`docs/tested-configurations.md` and the new run files under `docs/tested/`. The earlier rows stay on the source page,
in their original order; only new runs are fragments. Assembly reads local files and uses the existing Markdown
pipeline, with no generated source page, extra package or network request. Development watches fragment additions,
edits and removals. The site's existing neutral-prose policy changes displayed wording only, not links, inline code or
the source records; the source page remains available on Forgejo.

Common issues uses seven symptom cards with short checklists and a nested “Still stuck?”
disclosure for reporting details, issue search and Discord. The steps and links remain
in `docs/common-issues.md`; `format-common-issues.mjs` supplies presentation labels only.
Existing topic anchors open their cards through the shared manual navigation. Native
disclosures work without JavaScript, and the shared print handling expands every card.

## Validation and limits

Public pages use neutral game and console wording. Imported menu descriptions and activity text pass through
`src/lib/public-copy.ts` before publication; source records and links remain intact. `npm run check` rejects the
listed game-brand terms in generated page prose and the public progress feed. Literal commands, required save
paths, technical product names and third-party attribution are preserved. Update public wording and its tests if
an upstream description introduces a new term; never rename a real file path or runtime setting to hide it.

`npm run check` verifies generated routes, links, anchors, edit destinations, artwork
bytes, search output, source guards and the website's test suite. `build:preview`
runs both the build and checks. These do not build or launch the game.

Browser access was unavailable during implementation. Rendered desktop/mobile,
keyboard, and light/dark visual checks remain outstanding. Generated HTML and the
compiled Easter-egg script were checked separately; those are not browser checks.

## Download links

`worker/index.ts` answers `/download` on hookshot.magicbean.dev (everything else is the built site): permanent links to
the newest [Hookshot Launcher](https://git.magicbean.dev/MagicBeanDev/HookshotLauncher/releases), for READMEs, release
notes and chat. Forgejo's `/releases/latest` covers stable only; these cover each channel.

| Link | Goes to |
|---|---|
| `/download` | a page: the launcher for the visitor's system (by its User-Agent), from the best channel there is, and every channel |
| `/download/launcher/<os>` | that file of the best channel there is: stable, else rc, else nightly |
| `/download/launcher/<channel>` | the newest release page of `stable`, `rc` or `nightly` |
| `/download/launcher/<channel>/<os>` | that file of the channel's newest release, such as `/download/launcher/stable/windows` |

`<os>` is `windows` (`…-windows-x64-setup.exe`), `windows-portable` (`…-windows-x64-portable.zip`) or `linux`
(`…-x86_64.AppImage`). A link is a `302` to the file on git.magicbean.dev; a channel or file that isn't there is a `404`
page that says so and names the newest launcher there is. The channels follow the launcher's own rules
(`Core/ReleaseManifest.cs`, `scripts/release.py newest`), and the release list is kept 60 seconds.
`npx wrangler dev` (after `npm run build`) serves the site with the Worker; `tests/download.test.ts` checks the channel
rules.
