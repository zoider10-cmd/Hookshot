# Graphics guide image: merge-target source review

Retain `settings-graphics.png` after comparing its original source
`f7f4ca5741d89e8f1e608ead1609ff5ea3ad1250` (menu from the `0815d98` baseline)
with main `cf605c85bbaeaaa78176b933b3bc1a3366e13a78`, integrated into PR #264.
The existing PNG was visually inspected alongside the source changes and its
placement in `docs/graphics-and-controls.md`.

The picture illustrates the first Graphics view with Quality preset selected:
Custom, 16:9, 2048x1152 (reduced), Docked, Game's own upscaler, Auto (dynamic)
render resolution, 0% sharpness, and frame generation/pacing off. Its quality
help, tab navigation and keyboard footer still match the reviewed source.
These are fixture example values, not a first-run recommendation.

All nine changed files in the recorded dependency set were reviewed:

| Source | Change and effect on this picture |
|---|---|
| `gpu/vk/vk_menu.cpp` | Adds the **Intel shader compiles** row, hints, environment override and accessor. The row belongs to **Debug**, and `intel_compiler_row()` only enables it on Windows with Intel graphics. It does not change the pictured Graphics rows, their values, selected help or navigation. |
| `gpu/vk/vk_menu.h` | Adds `Options::intel_compiles = 0`. The fixture accesses members by name; pictured option defaults are unchanged. |
| `gpu/vk/vk_paths.h` | Adds `game_folder_path`, `game_sub_path`, `cache_path` and `log_path`: generated caches/logs now have dedicated subfolders. No path is shown in the picture. The guide's `hookshot_options.ini` location remains the game folder; the existing `game_module_path` rule is unchanged. The drawing fixture does not initialize persistence or resolve game directories. |
| `gpu/vk/pipeline_share.h` | Changes the missing-pipeline-list error to say **cache folder**. That error is not displayed in the pictured Graphics view. |
| `gpu/vk/vk_bug_report.h` | Clarifies in an input comment that logs live under `logs/`; report folders remain under the game folder. No pictured control or text changes. |
| `gpu/vk/vk_draw.h` | Adds guarded driver compilation and fault-tracking declarations; no menu drawing changes. |
| `gpu/vk/vk_internal.h` | Adds the Windows Intel compiler gate and sparse-memory interfaces. Neither driver compilation nor sparse allocation is executed by the UI-only drawing fixture. |
| `gpu/vk/vk_recorder.h` | Adds recorder own-slot/idle-wait behavior and a free-memory boundary. These affect command recording, which the fixture does not initialize. The added `hookshot_env.h` include already belongs to the recorded dependency set. |
| `gpu/vk/vk_work.h` | Adds a `vmaFreeMemory` recorder boundary for sparse mirrors; no UI drawing or text changes. |

The remaining recorded inputs, including translations, fonts and ImGui, are
unchanged. The capture fixture files are unchanged. The changed include directives
add only a system `<string>` header and the already recorded `hookshot_env.h`;
this review found no new repository dependency to add to the record.

Keep the PNG hash, capture date, `captured_source`, toolchain and pictured version
banner unchanged: they describe the original capture. Only `reviewed_source`
and the review explanation advance. Replacing the picture merely to show a newer
version banner would not improve this guide's illustration.

## Validation scope

On the combined PR/main tree, the old record reproduced **nine REVIEW REQUIRED
failures**. After the review, the source guard passed for all seven images against
that same combined tree, including the separate pinned Launcher rc.3 checkout
`028ad66d343db0502acdcc005609a31ea890ef79`. All 14 screenshot guard and four capture
isolation/policy tests passed. This distinguishes the review from a green check of the old PR
head alone. Future main changes to recorded inputs still require another review.

This is a source-and-existing-image review, not a fresh capture or a live-game
comparison. A fixture rebuild was attempted but could not start because Vulkan
headers were unavailable. Windows/Intel rendering and responsive browser layout
were not checked in this follow-up; the existing browser review request remains
separate.
