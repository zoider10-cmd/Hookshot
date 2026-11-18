# Graphics illustration and microphone test review

The Graphics illustration is recaptured from clean microphone-test topic
`5307877d06e189466c23fb1eb2a252dcfbb0c0d7`, rebased onto main `d76feb2d`, using `scripts/screenshots/capture_menu.py`.
It renders the maintained menu, translations, ImGui and bundled Libertinus fonts through SDL's software renderer.
No game, Vulkan device, microphone, saved settings, game assets or private paths are used. Capture size is
1280×720, English, Medium menu scale, keyboard prompts, explicit synthetic capabilities and default options.
This is a source-built UI example, not an official-binary or gameplay screenshot.

The earlier upstream illustration retained older Quality preset help about memory limits. The current help
names scaling and Shadow resolution. The new image preserves the guide's first unscrolled Graphics view while
showing current labels, help and navigation. Its illustrative Custom values are not recommendations. The PNG
and both versions were visually reviewed; capture metadata records the actual compiler, SDL/libpng versions,
complete compiler-discovered source dependencies and fixture hashes. Original capture provenance is retained
in repository history; other launcher images and their source reviews are unchanged. The rebased capture also
shows upstream's current Frame generation by row: Built-in FG, fixed when DLSS FG cannot run, replacing Auto.
The Audio feature controls and explanations are unchanged, so the captioned bc0997d4 Audio screenshots remain
valid historical feature illustrations. The new capture was visually inspected; no website layout or dimensions changed.

Final source review on main 3bb97bef retains this image: the below-view DLSS-model default changes only on cards
with less than 7 GB VRAM; the first Graphics view remains the same. The fixture's new device_vram_bytes()=0
stand-in represents an unknown card and does not enable DLSS. Original capture/PNG fields stay unchanged;
reviewed-source and fixture hashes advance to the inspected inputs. No new rendering is claimed for this delta.

The microphone feature adds Test microphone and Microphone gain in Audio, with the live read-only meter in
their help boxes. Separate same-view before/after Audio captures and synthetic active/stopped Test/Gain views
accompany its pull request. Synthetic levels demonstrate layout only; actual Windows/Linux play-tests establish
capture behavior separately. A 960×720 German fixture exposed clipped help; the topic includes a bounded-font
layout fix and a native rendered-line regression. The corrected German and English Test/Gain images were
visually reviewed for the explanation, percentage bullets, clipping note and non-adjustable meter.

The manifest review revision is a SHA-256 of sorted `path=hash` pairs with final newlines. This identifies the
reviewed source content after squash merging. Captured-source revision and capture conditions identify the
new rendering; neither is silently relabeled as a main or release capture. Launcher source review and live GPU
capability equivalence are not claimed by this menu-only review. Website verification is recorded separately.
