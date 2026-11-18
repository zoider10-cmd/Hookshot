---
name: port-survey
description: Check the other ports of the same game (HeyListen, ProjectReLink, Longshot, Reborn, Triforce, Fritchii, LICHII, upstream Mako) for updates, read what they changed, rank what is worth bringing over, port it one change at a time, and keep a change only when the Market A/B on this PC says it is no worse and the randomizer still works. Use when the owner asks to survey or merge from other ports, when the weekly update check finds a port moved, or when a new port is named.
---

# Bringing the best of the other ports into this build

The goal is the best build of the game for every kind of PC, never at the cost of the owner's (AMD RX 9070 XT,
Windows 11). Read only from the other ports; port the ideas here, one change at a time, each measured.

**Rules, before anything** (AGENTS.md and the owner's word):
- **Their code is read, never run.** Clone without checkout (`git clone --no-checkout --filter=blob:none`) into the
  scratchpad, read with `git show`/`git diff`. Build, run or install nothing from them; download no release, key or
  firmware.
- **License:** a port's code is copied only when its license is GPL-3.0-or-later compatible (all the forks so far
  are). The commit names where the idea came from (`(HeyListen 504f8362)`).
- **Merge only when the owner says.** The weekly check reports; it changes nothing. Upstream Mako is report only.
- **Never while the owner plays** (`tasklist`: hookshot.exe or the launcher): no bench, no install.
- **Nothing made from the game leaves the PC.** Commit locally; push to `origin` only when asked; never to `forge`.

## 1. What moved

```bash
py -I .claude/skills/port-survey/scripts/check_updates.py                 # one line per port: unchanged / NEW since <commit>
py -I .claude/skills/port-survey/scripts/check_updates.py --write share/port-survey/updates.md
py -I .claude/skills/port-survey/scripts/check_updates.py --mark HeyListen 504f8362   # after a survey
```

`sources.json` lists each port: link, kind (fork / emulator / upstream), license, how its history relates to ours
(`base`), and the commit last surveyed. A new port: add a row (ask the owner for the link if unknown).

## 2. Read what changed

For a fork, diff only what is new since `surveyed` (or since the shared Hookshot commit the first time: `base` says
how). Split the work by area and give each area to a read-only agent with a brief (the HeyListen pass's brief and
results are in `share/port-survey/`): frame work (replay, copies), stutter/textures/VRAM, the lift and native code,
fixes/settings/features. Each candidate gets: what it does, the port's commits, the gain they measured and on what
hardware, whether we already have it (many changes are picks from Longshot or Hookshot that we hold), hardware
dependence (NVIDIA-only, PCIe width, VRAM, Linux), port size, whether it touches the randomizer, risk, and a rank.

The ranked list goes to `share/port-survey/<port>-<date>.md`: taken, tried and dropped (with numbers), waiting, skipped.

## 3. Port one change

- One change per commit, on the working branch, the source named in the message. A switch for it (`HL_*`, `RX_VK_*`)
  is kept when the port had one, so it can be turned off without a rebuild.
- **Other kinds of PCs:** a change that helps hardware this PC isn't (NVIDIA, Intel, low VRAM, a narrow PCIe link,
  Steam Deck) and can't be measured here goes in only behind detection or a switch, with today's behaviour as the
  default where it can't be shown harmless. The hardware tiers in `docs/workflow.md` must not break.
- **The randomizer stays safe** (step 5).

## 4. The gate: the Market A/B on this PC

```bash
bash .claude/skills/port-survey/scripts/bench.sh <name> base <variant> [reps=3] [seconds=150]
```

- `F:/Games/perf-ab/variants/<name>/` holds a variant's `hookshot.exe` and/or `hookshot_vk.dll`; `base` is the
  installed build. A renderer-only change: `F:/Games/perf-ab/buildmain.sh <label>` builds the DLL alone. A host or
  lift change needs the whole build (`rebuild.sh` of the rando-test skill, then copy the exe from the game folder,
  and put the installed one back if it is not kept).
- The test copy of the game (`F:/Games/perf-ab/game`) loads its newest save, teleports to the Market's fountain by
  day and walks, uncapped, headless; A and B interleave.
- `gate.py` prints each run (mean fps, 1% low, worst frame) and the verdict: **FAIL** when the mean or the 1% low
  drops by more than the noise (the larger spread of either side's runs, at least 2%: an A/A of one build spread 67-73 fps, so a speed change needs 5 reps or more), PASS when one rises past it, NOISE when
  neither. FAIL is dropped; NOISE is kept only for a fix or a feature, not for a speed change.
- Picture: look at the runs' `shots/` side by side (rando-test's grid.py); a change that alters the picture is a
  question for the owner.
- A switch's measured result goes into the findings file with the runs' names.

## 5. The randomizer stays safe

```bash
bash .claude/skills/port-survey/scripts/rando_guard.sh <commit before the port> <label>
```

- It lists the touched files the randomizer owns or leans on (lift patches, `host/oot_*`, `hos_main.c`, `control.c`,
  the seed tool, the launcher, the menu): read each hunk; a port must not change what a lift patch anchors on or what
  the seed tool writes. A port that rewrites the lift (`nx2/`) needs `rebuild.sh` to apply every patch (its log counts
  them) and an in-game check.
- It runs every game-free check and compares the failing list with the one before the port: a new failure stops the
  port; the randomizer's checks (`tests/test_rando_*`) must pass as before.
- In the game: one headless run of the rando-test skill on a shop save (an item bought, the shelf shown) and a
  teleport, after any host or lift port.

## 6. Report

The owner reads `share/port-survey/<port>-<date>.md`: what was taken with its numbers, what was dropped and why, and
what waits for them (a decision, a setting to choose, a run on other hardware). Note the commits in `share/verify-list.md`
for what they should see in play. Then `check_updates.py --mark` the port.

## Weekly check

A scheduled task runs `check_updates.py --write share/port-survey/updates.md` once a week and tells the owner which
ports moved. It merges nothing.
