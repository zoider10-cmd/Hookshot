# Fullscreen monitor guide-image review

The canonical first-view Graphics illustration is recaptured from clean fullscreen-monitor topic
`54d25c79ead4d07e22cdcf5f07e481e19f90f78c`, based on main `e335bd5cb3f0b95cedbfa00ccc407621d333fabb`.
The maintained UI-only helper compiles the real menu, translations and bundled ImGui, renders through SDL2 software
geometry, and loads only bundled Libertinus fonts. The image is 1280×720, English, Medium scale, keyboard prompts,
illustrative Custom defaults and a synthetic 16:9 display. No game, Vulkan device, monitor probe, settings file,
save, private path or game-derived asset is used. This is not an official-binary or gameplay screenshot.

The old a06f7e2e image and final first-view illustration were visually compared, including the Quality preset help,
labels and navigation. Current version text and scrollbar reflect the newer source. The first Graphics
view remains the guide's Quality-preset illustration. The Custom values are examples rather than recommendations.
The PNG is copied unchanged from the helper output. Its caption, compiler-discovered source dependencies and actual
compiler/SDL2/libpng versions are recorded in the manifest. New monitor_choice.h is included in the captured inputs.
The content-derived reviewed revision hashes the sorted path=hash pairs with final newlines, separately from the
exact capture commit. Launcher images, original capture identities and historical reviews are otherwise unchanged.

The PR also carries a matched Screen-section pair: before e335bd5c and after 54d25c79. Both use the helper from
54d25c79, identical defaults and display geometry, with Fullscreen selected and settled scroll at the Screen heading.
The after image shows Fullscreen monitor below Fullscreen, defaulting to Auto (current monitor). All displayed labels
and help come from the maintained source; no text is overpainted. No named monitors are simulated or claimed by these
captures. Actual Windows multi-monitor and Linux single-display behavior is documented separately in the PR.

The original first focused-capture attempt selected Fullscreen without settling its scroll position, leaving that
row offscreen. It is retained only as private failed evidence and is not published. The fixture-only correction
does not change game behavior or the standard first-view Graphics capture.

Offline source/asset checks and rendered website review are recorded in the PR. A successful image hash check
does not establish runtime monitor behavior. Website build failures also present on matching main remain explicitly
separate from guide-image integrity and source review; no unavailable backend or display coverage is claimed.

## Website validation

Hookshot image integrity/source review and all 14 screenshot regression tests pass. Focused catalogue integration
checks pass; the complete Graphics test file retains two matching-main fixture failures (HDR Native's negative
case and the old Threaded rendering restart expectation). The normal website build stops on existing multi-row
tested-configuration fragments, whose schema requires one data row per file. Those upstream records are unchanged.

A source-only preview of committed 29267466 excluded exactly four invalid baseline catalogue fragments using the
production validator, retaining 486 valid records. The guide, menu, README and canonical PNG were unchanged in this
private catalogue fixture. Its build generated 20 pages. Six desktop/mobile/light/dark states and eight native
100/125/150/200-percent zoom states passed image loading/hash, overflow, caption, keyboard image-link navigation
and monitor-setting-card checks. Expanded monitor choices were also captured in all six viewport/theme states;
sample desktop/mobile/200-percent images were visually inspected. Owned headless browsers exited normally with
no page-console errors or HTTP 404s; no desktop input, game or user profile was used.

The catalogue-fixture preview is layout evidence, not a passing production build. Its `npm run check` stops on the
existing progress-feed validation failure before reaching the complete Node suite. Neither production guard is
disabled or relaxed by this PR. Those gates and unavailable runtime/backend coverage remain explicit in the PR.

## Retention after rebase onto 8e9cfc3a

Source review at 0aa01320 retains the original 54d25c79 captures and their exact PNG/capture identities.
Compiler preprocessing confirms the same dependency set. The four changed inputs are upscaler_rows.h
(optional DLSS CNN choices), vk_api.h (main-thread timing and appended monitor callbacks, ABI 28), vk_fps.h
(frame-trace declarations) and vk_menu.cpp (DLSS model choices and an Intel compiler hint outside this view).
The illustrated first Graphics view and Screen controls/defaults/help are unchanged. Reviewed-source hashes
advance to the inspected content; no capture, website preview, game build or runtime test is relabeled as new.
The SDL2 retarget correction changes host behavior, not the illustrated menu. The earlier native measurements
remain evidence for their original instrumented e335bd5c base, not fresh FPS measurements of the newer renderer.

## Retention after rebase onto f88e6e3a

Preprocessing adds only `gpu/vk/vk_new.h` and removes no input. The changed existing inputs are
`vk_api.h` (upstream out-of-memory callback and appended ABI-29 monitor callbacks), `vk_internal.h`
(allocation-handler declarations) and `vk_recorder.h` (nothrow-allocation guards using the new header).
These allocation and interface changes do not alter the illustrated menu rows, values or help.
The reviewed-source dependency hashes advance; the original capture revision, fixture and PNG identities
remain unchanged. No new image capture, game build, runtime check or performance measurement is claimed.
