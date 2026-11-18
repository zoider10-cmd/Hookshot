<!-- A sample of a good pull request description, for tests/test_check_pr_description.py and tests/test_forge_pr.py.
     The PR and its numbers are made up; the shape is the one .forgejo/pull_request_template.md asks for. -->
**Type:** fix · **Risk:** low · **Tested on:** Linux, RX 6700 XT · **Needs:** Windows, NVIDIA; Steam Deck

## Why

At 4K the pause menu's text runs off the right edge of the screen, so the last option of each row can't be read.
Fixes #42.

## How to reproduce

**Seen on:** CachyOS, RX 6700 XT, Mesa 25.2 RADV
**Settings and switches:** 3840x2160, defaults otherwise
**Steps:** load any save, press Start for the pause menu
**Expected:** every row ends inside the screen
**Actual:** the last option of each row is cut off at the right edge

## What changed

The menu's font now grows with the screen's height instead of staying at its 1080p size, so it fits at any
resolution. A switch overrides the size for testing.

- menu: `menu_font_scale()` in `gpu/vk/vk_menu.cpp` scales the font with the output height instead of a fixed 1080p
  size.
- menu: `RX_VK_MENU_FONT_SCALE` overrides the scale, for testing other sizes.
- tests: `tests/test_menu_font_scale.py` checks the scale at 720p, 1080p, 1440p and 4K.

## Measurements

**Verdict:** fixed: the widest row is 302 px narrower at 4K and fits; the menu's frame time is unchanged; the new
test passes here and fails on main.

Hardware: CachyOS, RX 6700 XT, Mesa 25.2 RADV, Ryzen 7 5800X, 32 GB
Scene: pause menu in Kokiri Forest, day; 3840x2160, DLSS off, no frame generation, 60 fps cap
Method: `tests/test_menu_font_scale.py`, and the menu's frame time from the FPS counter's Dev level, 60 s each, two interleaved runs (main, this PR, main, this PR), the median
How to reproduce: open the pause menu at 3840x2160 on any save; `python -I -B tests/test_menu_font_scale.py`

| | Before: main @ 7afe6ae1 | After: this PR @ 992a2420 | Δ |
|---|---|---|---|
| widest row at 4K (px) | 3912 (cut off) | 3610 | -302 |
| menu frame time (run 1 / run 2) | 0.41 / 0.42 ms | 0.41 / 0.41 ms | 0 |
| test_menu_font_scale.py | 0 of 4 pass | 4 of 4 pass | +4 |

```
[menu] font scale 1.00 (fixed), widest row 3912 px > 3840     main @ 7afe6ae1
[menu] font scale 2.00 (height 2160), widest row 3610 px       this PR @ 992a2420
```

Screenshots: main @ 7afe6ae1, the last option cut off; this PR @ 992a2420, the whole row.

### Flags and settings

One new switch, for testing only.

| Flag | What it is | Before this PR | After this PR | Effect | Helps / doesn't help / untested | Recommendation |
|---|---|---|---|---|---|---|
| `RX_VK_MENU_FONT_SCALE` (new) | The menu font's scale (0.5 to 3) | - (no such switch) | Unset: the scale follows the output height | Sets the menu's text size by hand | Helps: testing sizes. Untested: Steam Deck | Leave unset: a testing switch |

## Testing

**Tested:** on the RX 6700 XT above (CachyOS, Mesa 25.2): `tests/run_all.py`, and in the game the pause menu, the
Insert menu and the save menu at 3840x2160 and 1920x1080, every row read to its end. Tested but not measured: 1440p on
the same PC: the text fits.

**Not tested:** the title screen's menu, which uses the same font scale: nobody has opened it at 4K since the change.

**Must be tested:**
- Windows, NVIDIA, any recent driver: open the pause menu at 3840x2160, expecting every row inside the screen and the
  frame time unchanged (by hand: read each row's end, and the FPS counter's Dev level)
- Steam Deck, SteamOS (steamdeck): open the pause menu at 1280x800, expecting the text no smaller than on main
  (Test Farm: @Beanstalk steamdeck, the pause menu's text size against main)

## Risks

**What could break:** the menu could be too large on small screens if the height reads wrong.

**Turning it off:** `RX_VK_MENU_FONT_SCALE=1` brings back the old size; reverting the commit is enough.

**Compatibility:** nothing changes for players after updating: saves, `hookshot_options.ini` and the caches are
untouched.

## Issues

Fixes #42

## Checklist

### Everyone

- [x] One topic.
- [x] The title is a Conventional Commit (`type(scope): description`) of the status line's type.
- [x] Why gives the reason plainly and links the issues that fit (the tracker searched).
- [x] Measurements has a verdict, or one line saying why there is nothing to measure.
- [x] Testing names what was tested, what wasn't, and what must still be tested, where and how.
- [x] Rebased on current `main`.
- [x] `python -I -B tests/run_all.py` passes (any failure that also fails on `main` is named).
- [x] No game files, dumps, build output or generated files.
- [x] `third_party/` untouched (a new folder with a `PROVENANCE.md` instead).
- [x] The license is OK: GPL-3.0-or-later, nothing incompatible and nothing decompiled.

### When it applies

- [x] Numbers from the same PC, scene and settings, at least 2 interleaved runs each, the median reported.
- [x] Switches documented (docs/development.md; the README for a menu row) and shipped at their recommended value.
- [x] Screenshots of the same spot, captioned like the Measurements columns, for a change that shows on screen.
- [x] A game-free test added for the fix, failing on `main` and passing here.
- [x] A check under `tests/` that reads changed source updated in this PR, not weakened.
- [x] Host code builds on both Windows (llvm-mingw) and Linux, with UTF-8 paths.
- [x] Docs updated.
