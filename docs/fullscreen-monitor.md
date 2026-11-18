# Fullscreen monitor selection

## Behavior

Graphics → Screen → Fullscreen monitor selects the destination for borderless fullscreen.
Auto (current monitor) keeps the existing behavior. A named choice is saved by identity, independently
of the order of the monitor list. The transient menu ordinal is not saved.

Changing the choice while windowed sets the destination for the next fullscreen transition. Changing
it while fullscreen requests a move immediately. Returning to windowed mode restores the placement
saved when fullscreen began. F11, Alt+Enter and the Fullscreen row use the same host transition.

An unavailable saved choice remains selected and marked unavailable. The window uses a connected
screen temporarily. Reconnecting the selected screen makes it eligible again. Duplicate or ambiguous
identities must not silently resolve to an arbitrary display.

The selection is an output preference, not a graphics-card choice or an exclusive display-mode switch.
Explicit Output resolution settings keep their existing application/restart rules. Monitor-dependent
native size, aspect hints and mode lists must be refreshed when the actual display changes, including
a move between displays with equal dimensions.

## Threading and interface

The host publishes copied monitor metadata for the renderer. Menu callbacks read that snapshot and
queue a preference; the window-owning thread performs platform window operations. Monitor handles,
SDL display indexes and SDL session IDs are not persisted.

`MkwVkMonitor` contains an opaque preference ID, a UTF-8 label, desktop pixel dimensions, and flags for
the actual current and primary displays. Three callbacks are appended to `MkwVkHost`: `monitor_count`,
`monitor_info` and `monitor_select`, after the existing version-28 `out_of_memory` callback. The interface
version changes from 28 to 29. Other branches that
extend the same ABI require explicit reconciliation before integration.

## Platform qualification

Windows uses native monitor enumeration and display identities. Display labels prefer the friendly
name returned by `DisplayConfigGetDeviceInfo`, matched by monitor interface path. Missing names or
failed queries fall back to the monitor driver's description. Labels do not determine saved identity.
Linux goes through the existing SDL2/SDL3 abstraction. `SDL_GetDisplayName` already supplies friendly
labels: SDL's Wayland backend prefers compositor output descriptions, while X11 obtains monitor model
names from EDID when available. No separate DRM/EDID lookup is used by the selector, and the saved Linux
identity format is unchanged. A Linux backend-qualified unique display name can survive enumeration changes,
but is not a universal hardware serial number: renaming an output, switching SDL backends, or exposing
indistinguishable displays can make a saved choice unavailable. Such cases require safe fallback.
Outputs with indistinguishable SDL names, or runtime tokens outside SDL's centered-display encoding,
are retained as metadata but are not offered as named choices. Saved Linux choices are specific to
the SDL major version and video backend that provided their names.

Wayland fullscreen targeting must use SDL's display-targeting behavior rather than assuming ordinary
desktop coordinates can move a toplevel window. Compositor requests may be asynchronous or refused;
the published current-display state must describe the observed result.
Restoring a windowed position on Wayland is likewise subject to the compositor's placement policy.
The SDL3 pending-position behavior used for fullscreen targeting was checked against the official
[SDL 3.2.0 implementation](https://github.com/libsdl-org/SDL/blob/release-3.2.0/src/video/SDL_video.c);
that source review does not establish runtime behavior on a particular compositor.

## Review and validation status

On 2026-11-16, the two monitor fixtures and 17 affected checks passed on Windows with LLVM 23.1.5
and laptop Linux with LLVM 23.1.6. The fixtures compile the production policy/menu/transition code
against synthetic window and SDL APIs; they do not open a real game window. Linux ran the UTF-8
check's source assertions and skipped its Windows PE executable probe because no Windows cross
compiler was configured. That executable probe passed on Windows.

The checks exposed and resolved unsorted translation entries and incomplete keyboard-fixture
declarations. No game build, real monitor transition, compositor interaction or gameplay was exercised.
Platform behavior described above remains the intended runtime contract until observed in play-tests.

The full game-free suites subsequently ran on both hosts and every failure was compared with clean
upstream main `623a0ca3`. The initial runs reported 39 Windows and 32 Linux failures. Additional
selector-related fixture declarations and the README row were corrected; the existing settings-key
ownership check also required each owned monitor key to be expressed separately. Applicable affected
reruns passed: 21 checks on Windows and 23 on Linux. An unchanged Windows portable-setup failure
passed on rerun. The remaining 29 Windows and 21 Linux failed checks also fail on pinned main;
the overall suites are therefore not green. Default full-suite skips were 44 Windows and 17 Linux.
Baseline failures, including stale CRT fixtures, still limit coverage of their blocked paths.

Subsequent full host builds passed on Windows (RTX 3080) and laptop Linux (RTX 5090 Laptop GPU).
The paired host/renderer modules passed static inspection and Most shader preparation on each host.
The owner confirmed Auto/named-display selection and entering/exiting fullscreen on the laptop's
single-display Linux setup. On the four-display Windows setup, the owner confirmed friendly names
for all connected displays and correct named fullscreen targeting. The Windows friendly-name
follow-up was incrementally built and play-tested; its prepared caches remained compatible.
These observations do not establish Linux multi-display behavior or hotplug/restart coverage.

The added naming fixtures pass on both Windows and Linux. The Windows fixture fails its label
assertion on the exact pre-fix monitor source and passes all twelve scenarios after the fix; the
helper also passes a syntax check against real Windows headers. This is a pre-fix topic control,
not an upstream-main control. SDL2/3 naming tests preserve UTF-8 labels and backend-qualified IDs.

PR preparation on 2026-11-16 compared upstream `a413bf1c470e9dd9af172ed85e6a19fff9f035d2`
with the branch base. Eleven upstream commits affect seven overlapping files. A scratch three-way
merge found one conflict, in translation table entry counts; it did not alter this branch. The other
six overlapping files merged textually, which does not establish semantic compatibility. The
branch was still based on `ac778751`; the full-suite evidence above is against `623a0ca3`.

The branch was subsequently refreshed onto `17394b71111f8b7d9d6ecc65f430175145394743` without
committing the feature. The replay preserved the new atomic-settings implementation, telemetry
callback and frame-generation/HUD changes. Translation counts were recalculated from the combined
tables. That historical snapshot's monitor callbacks followed version-26 `perf_info` and required ABI 27.

Affected checks on that source: Windows 30 pass and five failures also reproduced on clean main;
two declared POSIX-only checks were excluded from the final Windows selection. Linux 33 pass and
four failures also reproduced on clean main. Both platforms fail the existing frame-generation
preset, rumble and upscaler fixtures for a missing `framegen_by_dlss_offered` stand-in, plus the
HUD-layout placing fixture. Windows additionally fails the telemetry relay reconnect scenario,
with the same result on main. No failing production/test code outside the monitor change was
altered to hide these failures. The monitor, naming, translation, ABI, atomic-settings and core
audio checks pass. This was an affected selection, not another full-suite run or host build.

The next eight upstream commits were replayed cleanly onto `e335bd5cb3f0b95cedbfa00ccc407621d333fabb`.
Affected checks including incoming audio speaker masks, memory allocation, shadow slots, image pools,
sparse/readback paths and compiler diagnostics reported 45 passes and five matching-main failures on
Windows (two declared platform exclusions), and 48 passes and four matching-main failures on Linux.
No topic-only failure was observed. The eight commits leave the monitor implementation and ABI unchanged;
both measurement variants must include them because several change rendering performance.

Full game-free suites then ran against that same `17394b71` base: Windows 626 passed, 37 failed,
45 skipped (708 checks, 433.71 seconds); Linux 663 passed, 28 failed, 17 skipped (708 checks,
374.32 seconds). Every failure was rerun on clean matching main and also failed there. All four
monitor/naming fixtures and the updated ABI/audio/mic/translation checks passed on both hosts.
Two checks initially blocked by shared Tooling discovery passed on both topic and main when the
existing Tooling path was selected explicitly. After those bounded setup reruns, 35 Windows and
26 Linux baseline failures remain. The original full-run totals are unchanged; no new full run or
host build is implied by the reruns. Current test records name the source and evidence scope.

Before publication/readiness, complete:

- Recheck upstream movement before publication; the pinned `17394b71` refresh and affected checks are complete.
- Reassess the pinned full-suite controls only where subsequent upstream/source changes invalidate them.
- Saved identity across reordered enumeration, missing/reconnected outputs, duplicate names and restart.
- Startup fullscreen, F11/Alt+Enter, windowed preference changes and moves while already fullscreen.
- Restoration of the original windowed placement; negative coordinates and mixed DPI on Windows.
- SDL2 and SDL3 targeting, including Wayland and X11 where available, with refusal handled safely.
- Native-size/aspect/mode refresh after switching between both different-size and same-size monitors.
- Existing audio/microphone controls and explicit output-resolution behavior remain intact.
- Same-spot before/after screenshots, guide-image source review, and the feature's on/off performance
  evidence required by CONTRIBUTING.md. No controlled feature measurements have been taken yet.

The monitor selection itself requires no shader-cache invalidation or shader preparation. A later build
may still require preparation for unrelated source changes under the normal cache compatibility rules.

### Current rebase and review

The branch is rebased onto main `f88e6e3a`. ABI 29 preserves the upstream `perf_info`,
`main_thread_times` and `out_of_memory` order, then appends the monitor callbacks; initializer and compiled offset checks enforce that order.
Independent review found and corrected SDL2's unchanged-fullscreen-flags no-op during monitor retargeting:
the host now leaves fullscreen before positioning and re-entering, retaining the original windowed placement
through retargets and failed re-entry. The fixture models SDL2's no-op semantics and tests failed leave,
failed re-entry/retry, and restoration with changing observed positions. No game rebuild or launch is part
of this rebase validation. Earlier screenshots, host builds and measurements retain their original revisions;
they are not represented as new runtime evidence for this source.
