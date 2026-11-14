<!-- Open as work in progress (a "WIP: " title; forge.py pr create does it) and mark it ready (forge.py pr ready) once
     every section and every For everyone box is done. Keep this description current, and post a comment for each new
     commit, measurement or test run: CONTRIBUTING.md, "Commits and pull requests". -->

## Why

<!-- The problem or goal a player would notice, not the implementation, in one or two sentences.
     E.g. "The menu's text is cut off at 4K." -->

<why this PR is needed>

## What changed

<!-- Bullets by area, naming the files and functions a reviewer should read.
     E.g. "- menu: `menu_font_scale()` in `gpu/vk/vk_menu.cpp` scales the font with the output". -->

- <area>: <what changed>

## Flags and settings

<!-- A note for reviewers and testers: what this PR adds or changes (an environment variable such as RX_VK_*, HOS_*
     or HOOKSHOT_*, a menu row or option, an ini key, a build or command-line flag) and what you recommend: on by
     default / off by default / on after more testing, with a short reason. "None" when there is none. Document each
     one: docs/development.md, "Switches for testing and debugging" and "The options file"; the README's option table
     for a menu row. -->

| Flag | What it does | Default now | Recommendation | Helps on | Doesn't help on | Untested on |
|---|---|---|---|---|---|---|
| <flag> | | | | | | |

## Measurements

<!-- What counts for each kind of change, and what makes the two sides comparable: CONTRIBUTING.md, "Measurements".
     Name the columns "main @ <hash>" and "this PR @ <hash>", never a bare Before and After. Comparing something else
     (a flag off and on, a nightly)? Name each column exactly ("this PR @ <hash>, RX_VK_X=0"), add a line
     "Baseline: <its column>" and one on why main wasn't the comparison. A Δ column is optional: the change against
     the baseline. Rebased onto a newer main: measure again, or say why the numbers still hold. -->

main: <commit> (<date>)
this PR: <branch> @ <commit>
Hardware: <GPU, driver, CPU, RAM, OS>
Scene: <area, time of day; resolution, upscaler, frame generation, frame rate cap>
Method: <duration, number of runs, and where the numbers come from: the FPS counter's Breakdown or Dev level, hookshot_log.txt lines, RX_VK_DRAW_STATS, a test>
How to reproduce: <the save or spot, the settings and switches, the commands, so a tester can repeat the run>

| | main @ <commit> | this PR @ <commit> |
|---|---|---|
| <what was measured> | | |

```
<the log lines or test output the numbers come from>
```

## Testing

<!-- Tested: what you ran and checked, where (hardware, OS, driver) and how (the game-free checks; in the game, the
     area and steps; a test request's result), including what you checked but didn't measure.
     Not tested: what this PR could affect that nobody has run yet, and why.
     Needs other testers: one line per thing you can't test yourself (hardware, OS, driver, a handheld), with what to
     check, the result expected and its test request (scripts/test_requests.py request, docs/test-requests.md), or
     "request to open" while it is WIP; "None" if you covered everything.
     E.g. "- Steam Deck: Kokiri Forest loads without the hang, expecting no gfx timeout (T-7KQ2)". -->

**Tested:** <what was run and checked, where and how>

**Not tested:** <what this PR could affect that nobody has run yet, and why>

**Needs other testers:**
- <hardware or system>: <what to check>, expecting <the result> (<test request, or "request to open">)

## Screenshots

<!-- If it shows on screen: the same spot on both, captioned "main @ <hash>" and "this PR @ <hash>". Otherwise:
     "Nothing on screen". -->

## Risk and rollback

<!-- What could break, and where; how to turn it off (a flag), or that reverting the commit is enough.
     E.g. "Draws could go missing on AMD's RADV; RX_VK_X=0 turns it off." -->

<what could break, and how to turn it off or revert>

## Reviewer notes

<!-- Where to look first, and what is left for a follow-up on purpose. Optional. -->

## Issues

<!-- Fixes #123 closes the issue when this merges (one line per issue); See #123 links it and keeps it open. -->

Fixes #

## Checklist

<!-- Keep the whole For everyone list, ticked. From If applicable, keep only the boxes that apply to this PR, and
     tick them; delete the rest. -->

### For everyone

- [ ] One topic.
- [ ] The title is a Conventional Commit (`type(scope): description`).
- [ ] Rebased on current `main`.
- [ ] `python -I -B tests/run_all.py` run and passing (any failure that also fails on `main` is named above).
- [ ] Tested in the game, or what wasn't is named under Testing.
- [ ] Testing filled in: what was tested, what wasn't, and what needs other testers (with test requests).
- [ ] Measured: main and this PR at named commits, on the same PC, scene and settings, at least 2 interleaved runs each, the median reported.
- [ ] No game files, dumps, build output or generated files.
- [ ] `third_party/` untouched (a new folder with a `PROVENANCE.md` instead).
- [ ] The license is OK: GPL-3.0-or-later, nothing incompatible and nothing decompiled.

### If applicable

<!-- Keep only the boxes that apply to this PR, and tick them; delete the rest. Keep the whole For everyone list. -->

- [ ] AI assistance recorded with `Assisted-by:` / `Co-Authored-By:` trailers.
- [ ] Flags noted, and the switch reference updated (docs/development.md, the README).
- [ ] Screenshots for a change that shows on screen.
- [ ] A file in `docs/tested/` for each new measured run (format in `docs/tested-configurations.md`; no appended row or assembled view).
- [ ] `MKWVK_API_VERSION` bumped (`gpu/vk/vk_api.h`'s `MkwVkHost` or `MkwVkRenderer` changed).
- [ ] The SPIR-V headers regenerated with glslang (a shader changed).
- [ ] A game-free test added for the fix, failing on `main` and passing here.
- [ ] A check under `tests/` that reads changed source updated in this PR, not weakened.
- [ ] Host code builds on both Windows (llvm-mingw) and Linux, with UTF-8 paths.
- [ ] Docs updated.
