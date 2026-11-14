<!-- A sample of a good pull request description, for tests/test_check_pr_description.py and tests/test_forge_pr.py.
     The PR and its numbers are made up; the shape is the one .forgejo/pull_request_template.md asks for. -->

## Why

The pause menu's text is cut off at the right edge at 4K, so the last option of each row can't be read.

## What changed

- menu: `menu_font_scale()` in `gpu/vk/vk_menu.cpp` scales the font with the output height instead of a fixed 1080p
  size.
- menu: `RX_VK_MENU_FONT_SCALE` overrides the scale, for testing other sizes.
- tests: `tests/test_menu_font_scale.py` checks the scale at 720p, 1080p, 1440p and 4K.

## Flags and settings

| Flag | What it does | Default now | Recommendation | Helps on | Doesn't help on | Untested on |
|---|---|---|---|---|---|---|
| `RX_VK_MENU_FONT_SCALE` (new) | Sets the menu font's scale (0.5 to 3); unset follows the output height | Unset | Off by default: a testing switch | 4K and 1440p outputs | 1080p and lower (same as before) | Steam Deck |

## Measurements

main: 7afe6ae1 (2026-11-10)
this PR: fix/menu-font-4k @ 992a2420
Hardware: RX 6700 XT, Mesa 25.2 RADV, Ryzen 7 5800X, 32 GB, CachyOS
Scene: pause menu in Kokiri Forest, day; 3840x2160, DLSS off, no frame generation, 60 fps cap
Method: `tests/test_menu_font_scale.py`, and the menu's frame time from the FPS counter's Dev level, 60 s each, two interleaved runs (main, this PR, main, this PR)
How to reproduce: open the pause menu at 3840x2160 on any save; `python -I -B tests/test_menu_font_scale.py`

| | main @ 7afe6ae1 | this PR @ 992a2420 | Δ |
|---|---|---|---|
| widest row at 4K (px) | 3912 (cut off) | 3610 | -302 |
| menu frame time (run 1 / run 2) | 0.41 / 0.42 ms | 0.41 / 0.41 ms | 0 |
| test_menu_font_scale.py | 0 of 4 pass | 4 of 4 pass | +4 |

```
[menu] font scale 1.00 (fixed), widest row 3912 px > 3840     main @ 7afe6ae1
[menu] font scale 2.00 (height 2160), widest row 3610 px       this PR @ 992a2420
```

## Testing

**Tested:** on the RX 6700 XT above (CachyOS, Mesa 25.2): `tests/run_all.py`, and in the game the pause menu, the
Insert menu and the save menu at 3840x2160 and 1920x1080, every row read to its end. Tested but not measured: 1440p on
the same PC: the text fits.

**Not tested:** the title screen's menu, which uses the same font scale: nobody has opened it at 4K since the change.

**Needs other testers:**
- NVIDIA on Windows: the pause menu at 4K fits and the frame time is unchanged (T-7KQ2)
- Steam Deck: the menu at 1280x800 is no smaller than on main (T-9MZ4)

## Screenshots

main @ 7afe6ae1: the last option cut off. this PR @ 992a2420: the whole row.

## Risk and rollback

The menu could be too large on small screens if the height reads wrong; `RX_VK_MENU_FONT_SCALE=1` brings back the old
size, and reverting the commit is enough.

## Reviewer notes

Start with `menu_font_scale()`. The controller glyphs keep their size: left for a follow-up.
New measured runs are files in `docs/tested/` (format in `docs/tested-configurations.md`); the earlier table stays frozen.

## Issues

Fixes #42

## Checklist

### For everyone

- [x] One topic.
- [x] The title is a Conventional Commit (`type(scope): description`).
- [x] Rebased on current `main`.
- [x] `python -I -B tests/run_all.py` run and passing (any failure that also fails on `main` is named above).
- [x] Tested in the game, or what wasn't is named under Testing.
- [x] Testing filled in: what was tested, what wasn't, and what needs other testers (with test requests).
- [x] Measured: main and this PR at named commits, on the same PC, scene and settings, at least 2 interleaved runs each, the median reported.
- [x] No game files, dumps, build output or generated files.
- [x] `third_party/` untouched (a new folder with a `PROVENANCE.md` instead).
- [x] The license is OK: GPL-3.0-or-later, nothing incompatible and nothing decompiled.

### If applicable

- [x] Flags noted, and the switch reference updated (docs/development.md, the README).
- [x] Screenshots for a change that shows on screen.
- [x] A game-free test added for the fix, failing on `main` and passing here.
- [x] A check under `tests/` that reads changed source updated in this PR, not weakened.
- [x] Host code builds on both Windows (llvm-mingw) and Linux, with UTF-8 paths.
- [x] Docs updated.
