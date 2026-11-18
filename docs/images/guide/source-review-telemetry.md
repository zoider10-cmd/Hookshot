# Graphics illustration retained for the crash window and performance statistics

The canonical PNG and its version caption retain the upstream main capture from
`b2911d33405e84fdad97248b409814a40dce69cb`. No Graphics image is replaced for the telemetry change.

The change shares ten of the reviewed menu inputs: `fps_stats.h`, `vk_fps.h` and `vk_api.h` for the performance
summary's counts and `perf_info` (API 26 since the rebase onto main's `mic_test`), `vk_ui.h`, `vk_imgui.h` and `vk_menu.cpp` for the crash window drawn as
the menu is, and `vk_bug_report.h`, `vk_paths.h`, `menu_i18n.h` and `vk_menu.h` for the report's fields and paths
(three of them as main has them since the last review). It adds no menu row.

This review rendered the fixture (`scripts/screenshots/capture_menu.py`, Vulkan-Headers 1.4.309, clang) twice: from
this change, and from main 02903b04 without it. The two Graphics images differ only in the version caption (554
pixels, all inside it). The pictured rows, values, help and navigation are therefore unchanged by this change.

Against the PNG, both renders also show main's own drift since the capture: the Quality preset help names Shadow
resolution instead of memory limits, its second line no longer mentions the VRAM budget row, and the scrollbar thumb
is shorter. That is main's, for the documentation maintainer to recapture; the pictured controls and navigation still
match the written steps.

As before, the review revision is `sha256:` followed by the digest of the sorted `path=hash` lines (UTF-8, a final
newline). Captured-source hashes, the PNG hash, capture date, version and capture toolchain stay unchanged, and the
external Launcher source review is unchanged.
