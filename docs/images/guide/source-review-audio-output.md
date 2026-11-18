# Graphics illustration retained for audio output selection

The canonical PNG and its version caption retain the upstream main capture from
`b2911d33405e84fdad97248b409814a40dce69cb`. No Graphics image is replaced for the audio feature.
The existing upstream review and original capture conditions remain the capture's provenance.

The audio change adds Output device, renames Speaker layout and moves Microphone within the Audio tab. It changes
no pictured Graphics row, default or help text. The rebased upstream shadow-resolution control is below this
first unscrolled view; its added translations do not change the English illustration. The upstream FPS details and
Debug controls are separate views. The picture's Quality preset, Custom output size, upscaler and frame-generation
controls and navigation remain applicable. The full PNG was visually inspected for labels, help and privacy.

The source-review check requires a review when shared menu/API/translation inputs change. The manifest therefore
updates only the reviewed-source hashes and review notes. Its review revision is `sha256:` followed by the digest
of the UTF-8 string formed by sorted `path=hash` pairs, one per line with a final newline. This identifies reviewed
content after a squash merge without relying on temporary branch commits. Captured-source hashes, PNG hash,
capture date, version and capture toolchain stay unchanged.

The reviewed fixture adds explicit SDR and unavailable-XeSS stand-ins for newer menu dependencies. These do not
change the recorded Graphics defaults; current fixture hashes are separate from the original capture inputs.
No new fixture rendering, pixel equivalence, scrollbar-size equivalence or live GPU capability check is claimed.
The review records the illustration's instructional applicability, not a new capture. External Launcher source
review remains unchanged.
