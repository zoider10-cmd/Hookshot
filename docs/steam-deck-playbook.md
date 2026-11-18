# Playing on the Steam Deck

Hookshot runs on the Steam Deck LCD and OLED (the same GPU in both). This page is what
a Deck player should know that the [install guide](getting-started.md) does not say:
what the build costs on handheld hardware, which settings this machine picks and why
that is right, and the two switches that measurably help on Deck.

**We do not host, store, or distribute game files, ROMs, game dumps, or decryption keys.**

## Installing

The Linux launcher works in Desktop mode: download the `.AppImage`, enable
**Allow executing file as program** in its Properties, and build from your own dump as
usual. Building on the Deck's own CPU takes well over the ~15 minutes a 12-core desktop
needs: budget overnight, and keep the Deck plugged in and awake (Desktop mode, display
timeout off, or `systemd-inhibit` from a terminal). If you can build on a desktop PC,
build there and copy the finished runtime and its cache over; the runtime folder moves
whole, and the shader cache moving with it means the first Deck launch is not slow.

The runtime and its pipeline cache together want roughly 15 GB free, and building wants
the same ~60 GB as any Linux PC. An SD card works but every hitch gets worse: the
pipeline cache is ~9 GB of small files, and load-in stutters are visibly worse on SD
than on the internal drive (issue #386 describes the difference). Where you have the
choice, keep the runtime on the internal drive.

The first launch per build prepares shaders and takes a few minutes of live progress.
That is expected; it happens once per build, not once per save.

## Settings: leave them on Auto

Auto (this PC) on a Deck picks the Low quality preset, the game's own resolution, and
**FSR 3.1** as the upscaler, with the 60 fps cap and frame pacing on. Measured A/B on a
Deck LCD says this is close to right, and a few specific alternatives are worse:

- **Do not switch to FSR 4.** FSR 4's upscaler is a small ML model; the Deck's GPU
  (RDNA2) has no AI accelerators, so it runs as ordinary shaders. On Deck LCD it measured
  15.7 fps against 20.6 fps with FSR 3.1 on the same save and protocol.
- **Do not turn Threaded rendering on.** On Deck it measured parity to worse (the menu's
  On is the `RX_VK_ASYNC=1` path; async alone washed out, and threading the recorder
  cost about 14%). It helps at high frame rates on desktop GPUs, not at 1 GHz here.
- Keep the **cap at 60** and frame pacing **on**; that matches what the game's own
  scripts expect (see [graphics and controls](graphics-and-controls.md)).

What you can expect from the shipped defaults, at the worst outdoor save we have
(loading into the starting village's benchmark save, then standing still, spinning the
camera, and running forward), Deck LCD, runtime on an SD card, with the two switches
below on: at the GPU's normal `auto` clock, about 21 fps standing and spinning.
Pinning the clock (see below) raises that to 24 on last week's main and to 30.9 idle
/ 27.6 spinning on today's main (row run03 of the tested catalogue; SD, the worse
storage case). Indoor and dungeon areas run higher — a nine-save sweep put them at
33-36 idle — and most outdoor areas are better than this worst case. Two rough spots
are being worked on: camera spins in the castle town cost about 30% (#750), and loading
into a busy outdoor save takes a minute or two of stutter while the world streams in
(see below).

## Two switches that help on Deck

Create a `hookshot_env.txt` next to the launcher's runtime (the launcher writes it; see
[Report slow performance](performance-report.md) for the file's format — it takes
`NAME=value` lines, not shell syntax). These two are the Deck wins we measured:

```
RX_VK_READBACK_LATE=newest
HOS_SHORT_SLEEP_TIMER=1
```

- `RX_VK_READBACK_LATE=newest` stops the host from waiting on the GPU before reading
  back small game textures. #238's Deck measurements (OLED, clock pinned) put it at
  about +20%: the main outdoor area 21.9 to 26.4 fps, the heavy view 24.3 to 30.3 fps. Our Deck
  LCD arms (issue #716) all ran with it on. It is merged (#238) but off by default while
  its desktop A/B settles; on Deck, it wins.
- `HOS_SHORT_SLEEP_TIMER=1` makes the host's waits resolve on a finer timer. On Deck it
  is worth a few percent and shortens the game's reaction to input.

Both are safe to keep together; they do not stack multiplicatively with each other's
cousin fixes, but neither is wasted alone. If a scene still hitches, [the performance
report page](performance-report.md) says which switches measure it, and the team can
read the result.

## Loading into a save takes a minute — and one clock pin helps

The Deck's auto GPU clock is the biggest single variable when loading into an existing
outdoor save: the loader spins up work faster than the clock ramps, and you get 5-20 fps
stalls for the first minute or so. Pinned clocks shorten it and raise steady fps about
10% (23.8-24.4 idle measured against 21.3-21.7 at auto on the same runtime and
protocol). To set it in Desktop mode, in a terminal:

```
echo high | sudo tee /sys/class/drm/card0/device/power_dpm_force_performance_level
```

It lasts until the next boot. CPU governor tuning adds little on top of the GPU pin.
The game now does part of this itself (#716): while it runs, it holds the GPU at amdgpu's
peak power state, 1300 MHz, unless a level was chosen by hand (`RX_VK_GPU_CLOCK=0` turns
that off). The pin above, or Steam's GPU clock slider at 1600 MHz, still reaches higher,
and the game leaves such a level alone.

Do not leave the level pinned if the Deck is in a bag or a child is playing: `high` keeps the fan up and costs battery; `auto` is the sane default and this
line returns it:

```
echo auto | sudo tee /sys/class/drm/card0/device/power_dpm_force_performance_level
```

## What is known on Deck specifically

- Intro movies: on Deck LCD at stock clocks with a build that has the merged pacing
  fix (#488), the opening movie loses very few pictures — 30 and 256 skipped (one
  arm), 31 and 94 (another), each out of an 1,800-picture movie. Before the fixes,
  issue #73's Deck evidence recorded 1,055 skipped out of the whole 5,947-picture
  intro at the 60 cap (different settings; the direction is unambiguous, the size is
  not a clean single-change number). Occasional drops remain; see #73.
- Camera spins in the castle town cost about 30% (#750). The mechanism (a game texture written
  by the GPU being re-uploaded every frame) is identified; the fix is open.
- SD-card installs stutter more at load-in than internal-drive installs (#386).
- The Deck LCD and OLED measurements on this page are from the LCD (Jupiter, Vangogh);
  the OLED has the same GPU with faster memory, so its numbers should be the same or
  better, not worse.
