**Type:** <fix / feat / perf / refactor / docs / test / build / ci / chore / revert> · **Risk:** <low / medium / high> · **Tested on:** <OS, GPU> · **Needs:** <OS, GPU, or none>

<!-- The status line above is what a reviewer reads first: the title's type, how much could break, where you ran it and
     where it still has to run. E.g. "**Type:** fix · **Risk:** low · **Tested on:** Linux, RX 6700 XT ·
     **Needs:** Windows, any GPU".
     Open as work in progress (forge.py pr create adds "WIP: ") and mark it ready (forge.py pr ready) once every
     section and every Everyone box is done. Keep this description current, and post a comment for each new commit,
     measurement or test run: CONTRIBUTING.md, "Commits and pull requests". -->

## Why

<!-- The reason for this PR, first, in plain words a player could follow: what goes wrong or what is missing, and for
     whom. Not the implementation. Search the issue tracker (forge.py issue list, or the web page) and link every
     issue that fits: "Fixes #N" closes it on merge, "See #N" links it.
     E.g. "At 4K the pause menu's text runs off the right edge, so the last option of each row can't be read.
     Fixes #42." -->

<the reason, in plain words>

## How to reproduce

<!-- For a fix (a bug, a regression, a crash): how to see the problem on main. Delete this section for anything else
     (a feature, a refactor, docs). -->

**Seen on:** <OS, GPU, driver>
**Settings and switches:** <the menu settings and any switch that matters, or "defaults">
**Steps:** <where in the game, and what to do there>
**Expected:** <what should happen>
**Actual:** <what happens on main>

## What changed

<!-- First a short plain summary, two or three sentences: what the PR does about the Why. Then the details by area,
     naming the files and functions a reviewer should read first.
     E.g. "- menu: `menu_font_scale()` in `gpu/vk/vk_menu.cpp` scales the font with the output height". -->

<a short summary>

- <area>: <what changed, with its files and functions>

## Measurements

<!-- Start with the verdict: did it help, by how much, did it pass. When there is nothing to measure, or no reason
     to (docs only, a script with its tests), that one line is the whole section, saying why.
     Otherwise the table: the columns name what was run with its commit, "Before: main @ <hash>" and "After: this PR @
     <hash>". More columns when they're needed: "After, RX_VK_X=0: this PR @ <hash>". A Δ column is optional. A
     before column other than main needs a "Baseline:" line saying what it is and why main wasn't the comparison.
     Same PC, save, scene and settings; at least 2 interleaved runs each after a warm-up; the median. What counts for
     each kind of change: CONTRIBUTING.md, "Measurements". Paste the log lines the numbers come from. -->

**Verdict:** <did it help, by how much, did it pass>

Hardware: <OS, GPU, driver, CPU, RAM>
Scene: <the area, time of day; resolution, upscaler, frame generation, frame rate cap>
Method: <what exactly was measured, from where (FPS counter's Dev level, hookshot_log.txt, RX_VK_DRAW_STATS, a test), how long, how many runs, the median>
How to reproduce: <the save or spot, the settings and switches, the commands>

| | Before: main @ <commit> | After: this PR @ <commit> |
|---|---|---|
| <what was measured> | | |

```
<the log lines or test output the numbers come from>
```

### Flags and settings

<!-- One line first: does this PR add or change a switch (RX_*, HOS_*, HOOKSHOT_*), a menu row, an ini key or a build
     flag? If not, "None" is the whole subsection. Otherwise a row for each: its value before this PR and after it
     (the default as it ships), what it does to the game, where it helps, doesn't, or wasn't tried, and what you
     recommend ("on for everyone", "off: only for testing"). A switch ships at its recommended value:
     CONTRIBUTING.md, "Code and data conventions". Document each one: docs/development.md, "Switches for testing and
     debugging" or "The options file"; the README's option table for a menu row. -->

<None, or a one-line summary>

| Flag | What it is | Before this PR | After this PR | Effect | Helps / doesn't help / untested | Recommendation |
|---|---|---|---|---|---|---|
| <flag> | | | | | | |

## Testing

<!-- Unmistakable: what has been tested, what hasn't, and what must be before merge.
     Tested: what you ran and checked, where (OS, GPU, driver) and how: the game-free checks; in the game, the area and
     the steps; a tester's result.
     Not tested: what this PR could affect that nobody has run, and why.
     Must be tested: one item per thing that has to be checked before merge and that you can't check yourself: exactly
     where (OS, GPU, driver, or a Test Farm tag such as linux, amd, radv, windows, steamdeck), the steps for someone
     else, the result to expect, and who runs it: the Test Farm (a "@Beanstalk <what to test, in words>" comment on
     the PR) or by hand (a person, and what to look at). "None" when Tested covers everything.
     E.g. "- Windows, any GPU (I'm on Linux; this is a Windows fix): start a new file, open the pause menu at 4K,
     expecting every row to end inside the screen (Test Farm: @Beanstalk windows, the pause menu at 4K)". -->

**Tested:** <what, where and how>

**Not tested:** <what, and why>

**Must be tested:**
- <where: OS, GPU, driver, or a Test Farm tag>: <the steps>, expecting <the result> (<Test Farm: @Beanstalk ..., or by hand: what to look at>)

## Risks

<!-- What could break, and where; how to turn it off (a switch) or that reverting is enough.
     Compatibility: what a player notices after updating: saves, hookshot_options.ini, the shader and pipeline caches
     (translated again, rebuilt?), the vk ABI (MKWVK_API_VERSION), the builder's tools; or "Nothing changes". -->

**What could break:** <what, and where>

**Turning it off:** <a switch, or "revert the commit">

**Compatibility:** <what changes for a player after updating, or "Nothing changes">

## Issues

<!-- One line per issue: "Fixes #123" closes it when this merges, "See #123" links it. Delete the section when there
     is none. -->

Fixes #

## Checklist

<!-- Keep the whole Everyone list, every box ticked. From When it applies keep only the boxes that apply, ticked;
     delete the rest. -->

### Everyone

- [ ] One topic.
- [ ] The title is a Conventional Commit (`type(scope): description`) of the status line's type.
- [ ] Why gives the reason plainly and links the issues that fit (the tracker searched).
- [ ] Measurements has a verdict, or one line saying why there is nothing to measure.
- [ ] Testing names what was tested, what wasn't, and what must still be tested, where and how.
- [ ] Rebased on current `main`.
- [ ] `python -I -B tests/run_all.py` passes (any failure that also fails on `main` is named).
- [ ] No game files, dumps, build output or generated files.
- [ ] `third_party/` untouched (a new folder with a `PROVENANCE.md` instead).
- [ ] The license is OK: GPL-3.0-or-later, nothing incompatible and nothing decompiled.

### When it applies

- [ ] AI assistance recorded with `Assisted-by:` / `Co-Authored-By:` trailers.
- [ ] Numbers from the same PC, scene and settings, at least 2 interleaved runs each, the median reported.
- [ ] Switches documented (docs/development.md; the README for a menu row) and shipped at their recommended value.
- [ ] Screenshots of the same spot, captioned like the Measurements columns, for a change that shows on screen.
- [ ] A file in `docs/tested/` for each new measured run (format in `docs/tested-configurations.md`).
- [ ] `MKWVK_API_VERSION` bumped (`gpu/vk/vk_api.h`'s `MkwVkHost` or `MkwVkRenderer` changed).
- [ ] The SPIR-V headers regenerated with glslang (a shader changed).
- [ ] A game-free test added for the fix, failing on `main` and passing here.
- [ ] A check under `tests/` that reads changed source updated in this PR, not weakened.
- [ ] Host code builds on both Windows (llvm-mingw) and Linux, with UTF-8 paths.
- [ ] Docs updated.
