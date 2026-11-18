# User-guide screenshots

These images are shared by the canonical Markdown guides and hookshot.magicbean.dev. Keep one copy in this
Hookshot directory; do not duplicate the images in HookshotLauncher or the website's generated `public/` folder.
`website/src/repo-docs/assets.ts` copies the manifest's images unchanged, and `pages.ts` rewrites guide-relative
links to those public files.

## Provenance

`manifest.json` records each image's dimensions, SHA-256, capture conditions, application release and reviewed UI
source hashes. All six launcher images are UI-only captures built from Launcher nightly-52-b1d9f7a9 source
`b1d9f7a9b19fa99b91ec3e8cd24455d4703d6d25`; they replace the earlier official-AppImage and rc.3 fixture captures.
The Graphics image is recaptured from fullscreen monitor PR #1277, `54d25c79ead4d07e22cdcf5f07e481e19f90f78c`, on main `e335bd5c`.
The [fullscreen-monitor source review](source-review-fullscreen-monitor.md) records the current capture and comparison.
Its review revision is a SHA-256 of the sorted file/hash pairs in `reviewed_source.files`, so it remains verifiable
after squash merging without depending on a temporary topic commit. Earlier captures and reviews remain in repository history.
These are real maintained views rendered with synthetic state, not screenshots of a running game or a claim of
reproducible official binaries. `captured_source` records the capture inputs; `reviewed_source` records the inputs reviewed for retention.

The screenshots show Hookshot's own UI and branding with the launcher's bundled Inter fonts. The launcher
sources and their license are in [HookshotLauncher](https://git.magicbean.dev/MagicBeanDev/HookshotLauncher);
the font's notice is `App/Assets/Fonts/Inter-LICENSE.txt` there. No game assets, extracted fonts, gameplay,
save data, private paths or keys are included. The application window is captured unchanged, including its
own labels. The selected **Builds** version is release metadata, not evidence that a game was built or run.

## Capture and maintenance

1. Use a clean, pinned Launcher source checkout and the UI-only helper below, or an official release in an isolated
   temporary profile. Never point it at a real game or save. Record the source/release, capture method, scale and
   theme; record the binary hash only for an official-binary capture.
2. Open the relevant screen. Use empty or clearly synthetic UI state for file/save workflows; do not import,
   export, replace or delete real saves to obtain an illustration.
3. Capture the application window. Inspect the full image for personal paths, identifiers and private data.
   Preserve actual labels and layout; do not compose or replace UI text. Record any capture fixture explicitly.
4. Add the image and a manifest entry here. Add descriptive alt text and a version/platform caption in the
   canonical guide. Keep the written instructions usable without the image.
5. Review the recorded UI source files when their hashes change. A changed hash means the screenshot needs a
   human review, not necessarily a recapture: compare labels, controls and navigation, then update the reviewed
   source revision and hashes or replace the image. Launcher UI changes are reviewed against its separate
   repository. Do not claim a capture is current merely because its PNG hash still matches.
6. Build and check the website using `website/README.md`, then inspect the affected pages at desktop/mobile
   sizes and in light/dark themes. Ensure each image loads from the site's own assets and remains readable.

## Developer maintenance plan

The UI change author owns screenshot freshness for the controls they change. The PR reviewer checks the image,
written steps and provenance; the documentation maintainer checks the rendered guide before release. A hash match
proves that the recorded files match, not that every possible UI dependency is covered or that the instructions are
correct. Extend the source list when the UI gains a dependency or moves to another file.

| Change | Author's action | Reviewer checks |
|---|---|---|
| Hookshot menu labels, layout, defaults or available controls | Run the source review below; inspect the affected guide and recapture if it no longer matches. | Correct visible labels and navigation, platform/capability caveats and version caption. |
| Menu font, ImGui, capture backend or fixture | Rebuild the UI-only fixture and inspect its output; update capture provenance if replacing the PNG. | Only bundled redistributable fonts, real menu code, no game assets, private paths or save data. |
| Launcher screens, navigation, file/save workflow or release | Review from the candidate Launcher checkout with `--launcher-source`; open a companion Hookshot documentation PR when needed. | Windows/Linux behavior and exact action names against that release, using empty or synthetic state. |
| Implementation-only change with identical visible behavior | Retain the capture only after comparison; record the newer reviewed revision/hashes and the reason for retaining it. | Evidence that the affected controls and written steps still match; no automatic hash refresh. |

### Offline checks

From the Hookshot checkout, using only Python's standard library:

```sh
python -I -B scripts/check_guide_screenshots.py
python -I -B scripts/check_guide_screenshots.py --review-sources
python -I -B scripts/check_guide_screenshots.py --review-sources --launcher-source /path/to/HookshotLauncher
python -I -B tests/test_guide_screenshots.py
```

The default check validates PNG signature/header dimensions and SHA-256, manifest fields, and safe local paths.
`--review-sources` also compares each image's `reviewed_source.files` and optional `fixture_files` against local
files. A mismatch exits nonzero and prints `REVIEW REQUIRED` with the screenshot and source filename. Missing
Launcher source prints **NOT CHECKED**, even when local checks pass. None of these commands downloads a checkout,
builds a game, opens a save, rewrites a hash or approves a screenshot.

`captured_source` (or the launcher's original `release_target_commit` and `binary_sha256`), `captured_at`, image
hash and capture conditions describe the original capture. `reviewed_source` describes the latest human review:
its repository, revision and relevant file hashes. When a newer source still matches an old image, preserve the
original capture fields, update only the review record and explain the comparison in `review.notes` and the PR.
If replacing the image, record the new capture and review together. Keep fixture hashes current only after
reviewing the fixture's effect. Do not copy fresh hashes into the manifest merely to make a failure disappear.

### Automatic Hookshot review signal

`.forgejo/workflows/guide-screenshots.yml` defines an offline, read-only check on **every pull request** and each
push to `main`, plus manual dispatch. Checking every PR avoids path-filter gaps when a recorded dependency moves
or a shared header changes. It runs source review and the checker's regression tests; it does not build the fixture
or access game files. The ordinary game-free test runner also discovers `tests/test_guide_screenshots.py`.

This PR adds the workflow definition. Whether its status runs on fork PRs and blocks merging depends on the
repository's runner and branch-protection configuration; this PR does not change those settings. After merging,
a maintainer should verify a test PR with a changed recorded UI source fails, then require **Guide images and
local UI source review** in branch protection if the team wants an enforced merge gate. An unchecked status or
missing runner must not be described as an automatic freshness guarantee.

### Launcher counterpart: planned cross-repository integration

A Hookshot-only workflow cannot observe a Launcher-only change. This PR does **not** install a workflow in
HookshotLauncher. Until the counterpart exists, the Launcher UI/release author must run the full command with
`--launcher-source` during UI review and before a release, using the actual proposed release checkout. Record
its commit, output and any companion Hookshot docs PR in that review. `NOT CHECKED` is not completion of this step.

The proposed Launcher-side PR/release job checks out the exact candidate Launcher commit SHA (the final release
commit for a release, not a moving branch name), verifies checkout HEAD matches that expected SHA, and checks out
an explicit Hookshot docs revision. It then runs the same checker from the Hookshot checkout with the candidate path as `--launcher-source`.
It must supply that checkout (and fail if unavailable), retain the affected screenshot filenames in its output,
and link any companion docs PR. The Launcher maintainer owns installing that job and deciding whether its status
is required; the release reviewer confirms it ran against the final release commit. Keep the images in Hookshot,
not in a duplicated Launcher asset folder. No remote service, webhook or second PR is created by this change.

### Completing a refresh

Include the changed image/manifest and canonical guide text in one Hookshot docs PR. Run the offline checks above,
then the website build/check commands in `website/README.md`. Inspect desktop/mobile and light/dark output,
including image readability, alternative text and adjacent instructions. In the PR, state which UI release and
commit were compared, what was recaptured or retained, the checker result (including external checks skipped),
and the rendered pages inspected. A passing integrity check alone is not a visual review.

## UI-only settings fixture

`scripts/screenshots/menu.cpp` compiles the real `gpu/vk/vk_menu.cpp`, translation code and bundled ImGui. It calls
its drawing function with deterministic illustrative settings and renders the resulting geometry through SDL2's
software renderer. It uses bundled Libertinus fonts over a solid background. It does not initialize a game,
Vulkan device, game-font loader, saved configuration or save workflow. Hardware-specific capabilities are disabled
fixture inputs. The result is an explicitly captioned UI-only example, not a runtime screenshot or a configuration
recommendation. Differences from a live Vulkan presentation have not been validated.

On Linux, install a C++20 compiler, Python 3, pkg-config, SDL2/libpng development files and Vulkan headers, then run:

```sh
python -I scripts/screenshots/capture_menu.py \
  --source /path/to/clean/Hookshot-checkout \
  --vulkan-headers /path/to/include \
  --output /tmp/hookshot-menu-capture
```

`--vulkan-headers` must contain `vulkan/vulkan.h`; no Vulkan runtime or private game files are needed. The source
checkout must include bundled ImGui and Libertinus. This optional local capture build is separate from site builds
and the lightweight CI guard. It outputs Graphics, Audio and Controls PNGs plus `menu-capture.json`; currently only
the Graphics image is published. Inspect the output before copying a selected image into this directory.

The helper derives repository input hashes from the compiler's dependency list and rejects dirty or untracked
capture inputs. It records the source revision, fixture hashes, compiler/library versions and explicit display
state. Preserve those records in the manifest when replacing an image. Recheck the dependency set when menu code
changes: a successful old dependency hash check cannot detect an entirely new, unlisted dependency by itself.

For a matched Screen-section comparison, add `--views graphics graphics-screen`. The optional
`graphics-screen` view selects the maintained Fullscreen row by name on both revisions and fails if it is absent.
It retains the same illustrative display, defaults and software renderer; no real monitor is probed. The standard
`graphics` view stays at the first row and remains the canonical Quality-preset illustration.

## Launcher decision screens

All six `launcher-*.png` images render the pinned release's maintained Avalonia views and view models with
synthetic state. They are labelled UI-only examples. `scripts/screenshots/LauncherCapture.cs`
uses Avalonia Headless with the real Skia renderer and bundled Inter fonts. It sends no desktop input, invokes no
build or Import command, and verifies that confirmation's dry-run preview changes neither files nor directories.

From a Hookshot checkout with Python 3 and the .NET 10 SDK:

```sh
python -I scripts/screenshots/capture_launcher.py \
  --source /path/to/clean/HookshotLauncher \
  --version nightly-52-b1d9f7a9 \
  --output /tmp/hookshot-launcher-guide
```

Use `--dotnet /path/to/dotnet` when needed. The first run restores packages from NuGet; subsequent runs reuse the
cache under `/tmp/hookshot-guide-nuget`. Both the Launcher and fixture package locks are enforced. No game, save,
window server or installed Launcher is required. The temporary application build is deleted after capture.

The staged source includes and fingerprints `Directory.Build.targets`, preserving the Launcher's empty
`AvaloniaStats` target that disables Avalonia build statistics. This is separate from the .NET CLI telemetry
opt-out. Both restores explicitly use the staged `NuGet.Config`, preserving the nuget.org-only feed policy
instead of inheriting machine/user feeds. Missing tracked build configuration stops the helper.

Synthetic state uses the fixed `hookshot-guide-example` directory under the system temporary directory so the
real UI shows neutral paths. The helper exclusively creates it, refuses an existing directory, and removes only
the directory it created when capture ends. It never repaints or substitutes displayed paths in an image.

The helper builds a temporary copy of clean tracked Launcher sources. Two explicit adapters in that copy prevent
private game-file discovery and replace the host hardware probe with illustrative inputs to the real requirements
evaluator (16 GB RAM, 12 CPU threads, AVX2, 100 GB free, Vulkan 1.3, 8 GB VRAM and mesh shaders). They do not change
view markup, labels, layout or transfer logic. Tools-ready state uses the Launcher's existing screenshot helper.
The candidate channel and v3.0.0-rc.3 game build are illustrative fixture inputs, independent of the Launcher nightly
version. The synthetic build is a non-executable text marker. The confirmation's source/target slots contain only
fixture text files, following the Launcher's own test convention. The target comes from `Saves.ImportTarget`, including
its public fixed profile ID; it is not a user's account. No fixture file is a usable game save.

`launcher-capture.json` records the original source revision/hashes, the adapters, SDK, helper/lock hashes and image
hashes. Review the adapters whenever source structure changes. The manifest conservatively tracks all compiled
Launcher App/Core source and resource inputs for these images, so unrelated changes can also request review.
Keep original capture provenance separate from a later decision to retain an image.

## Screenshot placement

Each image should answer the question at the point where the reader needs it. Keep the action names and warnings
in selectable text, the platform/version or synthetic-state explanation beside the image, and a full-size link for
small screens. These placements implement the independent UI and documentation review in PR #264:

| Guide | Image | Place it beside | Reader question |
|---|---|---|---|
| Install | Welcome | Press **Build**, before later build/Play instructions | Where do I start? |
| Install | Game files | **Browse…**, drag/drop or **romfs and exefs folders** | What should I select next? |
| Settings | Graphics layout | Navigation table and shortcut note, before persistence/restart details | Where are the tabs, values and help? |
| Transfer a save | Home with Manage saves | Opening navigation instruction | How do I reach the Saves page? |
| Transfer a save | Empty Saves page | After preparation, before the import/export procedures | Which action brings saves in or sends them out? |
| Transfer a save | Import chooser | Inside emulator-import step 3, before confirmation | What if my emulator is not listed? |
| Transfer a save | Import confirmation | Inside step 4, before pressing **Import** | What will be replaced, and where is the backup? |

The two import images and their captions must stay inside their numbered list items. The site test checks that they
remain with the relevant action. The updates overview links to the transfer guide; do not duplicate this sequence
there. Additional Audio/Controls galleries are unnecessary without a specific task to teach. A Windows-only
between-build transfer image remains conditional on a validated Windows capture.

Source/image review and automated HTML/link checks do not establish mobile usability. Before marking the PR ready,
inspect desktop and 360–390px layouts, both themes, keyboard image links and browser zoom; check image/caption
adjacency, list numbering and horizontal overflow. Keep visual-review status explicit in the PR.
