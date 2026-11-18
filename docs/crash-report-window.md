# Report automatically or manually: the crash window

The window the game shows after a crash ([development.md](development.md#the-window-after-a-crash),
`host/hos_crash_dialog.c`) offers two ways to report it:

- **Report manually** (main's **Report**): a text report on the clipboard and Hookshot's issue form opened in
  the browser, prefilled, for the player to paste it into and send themselves. Nothing is sent by the game.
- **Report automatically**: the same crash, as a short structured report the player is shown in full, sent only when
  they press it. It goes to Hookshot-api's telemetry service, which posts it on
  [#81](https://git.magicbean.dev/MagicBeanDev/Hookshot/issues/81) (one comment per crash, its repeats counted there)
  and counts it for Grafana. This is the in-game half of #81.

## What the player sees

One window, on Windows and Linux alike, drawn as the Insert menu (F1) is: its banner, its fonts (Libertinus, compiled
in), its gold buttons (`gpu/vk/vk_crash_window.cpp`, with `gpu/vk/vk_ui.h`'s drawing). It goes from page to page:

1. What happened and when, and why: **Report automatically** first, then **Report manually**, **Open the log folder**,
   **Close**. Report automatically is there only for a crash record (an unclean end has no crash to report), when
   `hookshot_version.txt` has the addresses (below), and until the report has been sent.
2. **Send to the team**: what Report automatically would send, and nothing else: the version, whether it is a release
   build, the system, the renderer, the graphics card, the CPU and RAM, the map, how many settings and how many changed,
   the crash's first lines, and how many log lines go with it; **Show all of it** opens the report itself, every field as
   it is sent (`bug-reports/pending/sending-<record>.json`). **Send** and **Cancel**.
3. Then **Sent** (with **Open it**: the report's comment on the crash issue) or **Not sent** and why (the server busy or
   not reached, with **Try again**; or the report refused). Report manually and the log folder stay to be had.

Tab and the arrows pick a button, Enter presses it, Escape is the last; the wheel and Page Up and Down scroll a page
longer than the window. A press is the player's, not input left over from the game: a key repeat presses nothing, nor
a key or click in a page's first 0.4 s (a key down then counts only once it has been let go), so Space or Enter held
or mashed as the game died, or pressed while the page before was sending, never presses a button.

Without the window (no SDL renderer, or a `hookshot_vk` without `mkwvk_crash_page`), SDL's message box says the same,
and on Windows without SDL, Windows' own.

**Send crash reports automatically.** A player who ticks it in the launcher's Settings has a `hookshot_crash.ini` in
each game folder with the line `send=1` (`hos_crash_auto_send`). The helper then makes the same report as Report
automatically and posts it the same way, with no window at all, and adds the answer at the end of the crashed run's log
(`[hos crash] sent on its own (hookshot_crash.ini): <the link, or why not>`; the game has ended, so the helper writes it
there itself). A report sent so keeps a copy of what went, as it went, beside its answer in `bug-reports/sent/` (`crash-<when>.json` for the record
`crash-<when>.txt`). A report
that can't be sent (the server busy or not reached, or the report refused) shows the window as it would have, Report
automatically still offered. Off, or with no file, the window asks.

A report that was sent leaves its answer in `bug-reports/sent/<record>`, so Report automatically is not offered for it
again. The report's own files in `bug-reports/pending/sending-*` are removed once the window is done.

## How it fits together

The game sends its report itself: no launcher and no Python is needed.

| Part | What it does |
|---|---|
| `host/hos_crash_dialog.c` | the helper: it waits for the game, decides what the window says, builds the report from the run's log (`build_report`), and posts it with the system's `curl` (`post_report`: over https only, to the stamp's address, no redirect followed, at most 30 s; `--disable` first, so no `.curlrc` or `_curlrc` of the player's changes that; on Linux without the game's `LD_LIBRARY_PATH` and `LD_PRELOAD`, so it loads the system's own libraries; Windows 10 and 11 have `curl.exe` in System32). The pages go to the window through `mkwvk_crash_page`. What decides (the addresses, whether to offer it, the report's lines, the answer) is in `host/hos_crash_dialog.h` |
| `gpu/vk/vk_crash_window.cpp` | the window, in `hookshot_vk` (which has Dear ImGui and the fonts already): SDL's renderer, through the SDL the helper loaded (SDL3 or SDL2, by name), never Vulkan, as the crash may have been the GPU's: its software renderer, the pixels in memory. On X11, XWayland on a Wayland desktop, as SDL's Wayland driver has no software renderer without the GPU; Wayland only where X11 can't be had (and then SDL's message box), and `SDL_VIDEO_DRIVER` still chooses. `gpu/vk/crash_window_api.h` is what the helper calls |
| `nx2/make_game.py` | writes `crash_reports=` and `crash_issue=` into `hookshot_version.txt` from `nx2/addresses.ini`, in a build from packaged tools (the launcher's: a tag in their `VERSION` or `version.txt`); a build from a checkout has no `hookshot_version.txt`, and either address left out there, the window has no Report automatically. Also `source=`, for the release flag (below) |
| `hookshot_crash.ini` | in the game folder, written by the launcher: `send=1` for Send crash reports automatically (above) |
| `nx2/addresses.ini` | `crash_reports` (Hookshot-api's `https://data-services.magicbean.dev/telemetry/crash`) and `crash_issue` (#81, where Open it may go: only that issue or one of its comments) |

The report is made from what is on disk, never from the crashed process:

- the crash record (`bug-reports/pending/crash-<UTC>.txt`, `host/hos_crash_record.c`): its `run_id` names the run;
- that run's log, the helper's own (the game gave it its path);
- `hookshot_options.ini`: the run's (the game gave the helper its path: in the user folder when the launcher gave
  `--user`), else the game folder's, as a build from before kept it;
- `hookshot_defaults.ini`, and `hookshot_version.txt`'s `source=`.

The game logs what the report needs at startup, worded as the Insert menu's Bug report words it: `report: renderer`
(the back end that started, `host/rx_backend.c`), and from the renderer (`gpu/vk/vk_main.cpp`) `report: gpu`,
`report: cpu` (with the RAM) and `report: os`.

## Out of memory (Linux)

The kernel's out-of-memory killer ends the game with SIGKILL, so no crash handler runs: the end is unclean. systemd then
stops the scope the game ran in (`DefaultOOMPolicy=stop`), and everything in it with it, which on its own would take the
crash window's helper too: the player would see nothing. So `host/hos_crash_dialog.c`'s helper:

- reads the game's cgroup's `memory.events` (`oom_kill`, the processes any OOM killer took there) when it starts, and
  again the moment the game ends: when it grew, it writes `oom_kill: yes` into the run's unclean record, and the window
  says the PC ran out of memory;
- moves itself into a scope of its own (`hookshot-crash-<pid>.scope`, the user manager's `StartTransientUnit` through
  `busctl`) before it waits, so stopping the game's scope leaves it running. A Flatpak keeps its processes in its own
  scope, so there it can't;
- holds SIGTERM back from the wait until the record is written, so a stop of the scope it is still in comes after;
- lists an out-of-memory end as shown only once its window is done. A helper that systemd stopped with the game leaves it
  unlisted, and the next start shows it (`hos_crash_show_at_start`: crash records and out-of-memory ends, never another
  unclean end).

Tested in the game with `systemd-run --user --scope -p MemoryMax=1200M -p MemorySwapMax=0 -p OOMPolicy=stop`: the window
right after the kill, and, with `busctl` out of reach (as in a Flatpak), at the next start.

## What a report holds, and what it never holds

The fields are the ones the relay takes (Hookshot-api's `telemetry/crash/report.go`), each capped there:

| Field | From |
|---|---|
| `version` | the log's first line, `hookshot <version> (source <fingerprint>)`; letters, digits and `.+_-`, 40 at most |
| `release` | [below](#the-release-flag) |
| `os`, `cpu`, `gpu`, `renderer` | the log's `report:` lines; `os` and `cpu` from this PC when the renderer never started |
| `map` | the last `map:` line before the crash; before any, "Preparing shaders" (from the shaders' first progress line to "the shaders took") or "Title and intro", the names the performance summary uses |
| `options` | every setting in `hookshot_options.ini`, defaults included, the changed ones first, as `key=value` lines (4000 characters at most); without an options file yet, the defaults file's |
| `crash` | the `CRASH:` lines: the exception, the host backtrace, the thread, the guest backtrace (80 at most); a place in a library is its module's name, not its path |
| `log_tail` | the 150 log lines before the first `CRASH:` line, 300 characters each at most |

**Never sent:**

- the register rows (`CRASH:   x0 …`) and the memory rows (`CRASH: [x0+0x000] …`): they hold the game's memory, and
  nothing made from the game leaves the PC (CONTRIBUTING.md);
- from `hookshot_options.ini`: the key and pad bindings, the microphone's name, the hardware hashes (`auto_for`,
  `auto_tuned`) and any line the game doesn't write itself;
- the names of the player's audio devices in the log;
- game files, saves, keys, `work/`, minidumps;
- the user's name and home: `/home/<name>`, `/Users/<name>`, `C:\Users\<name>` and Wine's `Z:\home\<name>` become `~`
  and `%USERPROFILE%`, and the user's name elsewhere, as a word of its own (three letters or more), `<user>`. The relay
  does it again, as a second line of defence.

### The release flag

`release` is true when the version is a channel's (`X.Y.Z`, `X.Y.Z-rc.N`, `nightly-N-<hex>`:
[versioning.md](versioning.md)) and the log's fingerprint is `hookshot_version.txt`'s `source=`. `make_game.py` writes
`source=` only for packaged tools (their version comes from their `VERSION` or `version.txt`; a checkout has neither),
with the fingerprint of the sources it built from. So a build from a checkout, or a log from another build of the
folder, is not a release.

It says the build came from a release's tools, not that nobody edited them: the fingerprint is taken when the game is
built. Stamping it when the tools are packaged, in the signed `VERSION`, would close that, and is left for later. Either
way it is a label for sorting, not a proof: anyone can post `"release": true` by hand. The relay heads a report that
isn't from a release `[not a release]`.

## Tests (no game needed)

- `tests/test_crash_dialog.py`: the addresses from the stamp, when Send is offered, the report's lines (modules without
  their folders, the memory rows left out, the home folder, the user and the devices taken out, a character never cut in
  two), the answer's words and link; and a real run of the helper after a crash with a stand-in for curl: the report
  posted to the stamp's address, its fields, the page that shows it, Show all of it, Send, Open it, then the window
  without Send; a busy server with Try again, a refusal without it, and no Send without the addresses.
- The window's look: the pages drawn offscreen (`SDL_VIDEO_DRIVER=offscreen`) through SDL3 and SDL2, as the pull
  request's screenshots show them.
- In the game, 2026-11-16: a build of this branch from the game files, `HOS_CRASH_TEST=15` on KDE Plasma (Wayland, NVIDIA,
  the system's SDL3): the window over XWayland, Report automatically then Send, Hookshot-api's answer 201 and its comment
  on issue 81, `hookshot_crashes_total` and `hookshot_crash_reports_total{result="new"}` in Prometheus. Before the X11
  choice the same run fell back to SDL's message box ("Window framebuffer support not available").
