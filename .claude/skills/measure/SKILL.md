---
name: measure
description: Measure a Hookshot change or a switch in the game against main - fps, frame time, GPU time, memory, a log line - and write the numbers up for the pull request's Measurements and docs/tested/. Use when the user asks to measure, benchmark or A/B a change or a switch, when a perf, fix or feat pull request needs its before and after, or before marking such a pull request ready.
---

# Measure a change against main

What counts, and how a Measurements section reads, is [CONTRIBUTING.md](../../../CONTRIBUTING.md#measurements); the
builds are [Testing a change against a base](../../../docs/development.md#testing-a-change-against-a-base); the run
files are [docs/tested/README.md](../../../docs/tested/README.md). This is the order to do it in, and the mistakes that
have cost the team whole sessions.

**Bases, packs, runtimes, run folders and frame dumps are built from the game: they never leave the PC.** Log lines and
screenshots are fine. A run needs the person's own game dump; with none on this PC, say so and stop.

## 1. Before the first run

- **Measure the commits the pull request will have.** Land review fixes and the rebase first: numbers from an older
  commit have to be measured again. `pack` counts uncommitted and untracked files too, so commit and keep the tree
  clean, and the hash in the table names what ran.
- **Know what holds the frame.** Run once with the profiling switches and read where the time goes before choosing what
  to measure: `RX_VK_PASS_TIMING=1` (GPU time by pass), the `vk: <n> presents, <fps> fps; a frame: ...` line,
  `vk: host time in GPU resource waits` (what the CPU waited for), `HOS_THREAD_TIMES=5` and
  [docs/cpu-profile.md](../../../docs/cpu-profile.md) for the CPU. A GPU-time saving moves no fps while the frame waits
  on a readback or the CPU: then measure it alone and together with what lifts that bound. Time a profile doesn't
  label is work nobody named, not idle time.
- **Pick the scene and the settings players use**, not ones that flatter the change: the settings the Quality preset
  Auto picks on this PC and the device's own resolution, at 100% render resolution when GPU time is the point. Two
  setups (handheld default and native, say) are two comparisons, never mixed.

## 2. Build both sides from one base

```
python -I scripts/dev_packs.py base ../base-main --romfs <romfs> --exefs <exefs> [--seed <an older game folder>]
python -I scripts/dev_packs.py pack ../base-main my-change --tree <the branch's checkout>
python -I scripts/dev_packs.py rt   ../base-main ../rt-main                (no pack: main)
python -I scripts/dev_packs.py rt   ../base-main ../rt-my-change my-change
```

- The base is the pull request's merge base (`git merge-base forge/main HEAD`), so main's column names that commit.
  Agents on one PC share a base: ask before moving it, and wait while `<base>/dev_packs.busy` exists. On an older base,
  build that merge base as a pack of its own and compare the two packs; never the change's pack against the bare older
  base, which would count every commit in between as the change's.
- Warm the base for your scenes (`dev_packs.py warm`), so neither side compiles pipelines while it is measured.
- A switch needs no build: one runtime, the switch unset against set. Check that unset logs what main logs.

## 3. Pin the settings, and check what ran

- Start every run from the same options file (`HOS_OPTIONS_FILE=<a copy kept for this>`), not the player's: a harness
  that silently picked up a lower resolution once turned a 15 fps scene into 20 and a gain into nothing.
- Frame generation off (or report the game's own fps, never the shown one); the cap off (`HOS_FPS_MAX=1000`) or stated;
  no overlays, ReShade or shader-cache tools.
- Read back from each run's `hookshot_log.txt` what it actually used (output and render size, upscaler, preset, frame
  generation, the switches it names) and write those, not what you meant to set.
- Steam's Game Mode sets `RADV_FORCE_VRS_CONFIG_FILE`, which keys every RADV pipeline differently: a cache warmed
  outside Game Mode misses, and the run compiles for many minutes. Warm and measure in the same kind of session, and
  say which.
- Profiling and counting switches (`RX_VK_PASS_TIMING`, `HOS_HLE_STATS`, `HOS_SAMPLE*`) stay out of the runs whose
  numbers you report, or are the same on both sides and said so.

## 4. Run

- The same save, spot and route each time: a scripted route through the [control bridge](../../../docs/control.md)
  (`scripts/hookshot_ctl.py`) or `HOS_INPUT_SCRIPT`, standing still or moving, the same length.
- Interleave: main, change, main, change, after a warm-up run of each. At least two runs each; more when the gap is
  small next to the spread between runs. A device that throttles (a handheld, a laptop) stays on the same power and
  clock settings for both.
- Take the median. When the runs of the two sides overlap, the verdict is "within the spread", not a gain.
- Keep the run folders and logs on the PC until the pull request is merged.

## 5. Write it up

- Measurements, as the template has it: the **Verdict:** first, then Hardware, Scene, Method, How to reproduce, and a
  table whose columns are `Before: main @ <hash>` and `After: this PR @ <hash>` (a variant: `After, RX_VK_X=0: this
  PR @ <hash>`), each run's number and the median, then the log lines the numbers come from. A before column that
  isn't main gets a `Baseline:` line.
- One file under `docs/tested/` for each measured run, named with your public handle, then
  `python -I -B tests/test_tested_configurations.py`. Commit them on their own.
- Rebased onto a newer `main` afterwards: measure again, or say in the comment why the numbers still hold.
- `python -I ../Tooling/scripts/forge.py pr update <n> --body-file <file> --comment "..."` with what was measured.

## 6. Stop and ask the person you work for

- Before using a device someone plays on, or moving a shared base.
- When a run needs eyes (flicker, a missing object) or hands (a route the bridge can't drive).
- When the numbers don't back the description's claim: report them as they are and ask what to change.
- When the hardware the change needs isn't here: the pull request's *Must be tested* names it for the Test Farm or a
  tester, and it stays WIP.
