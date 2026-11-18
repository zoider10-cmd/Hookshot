# Microphone device limit: guide image review

Review date: 2026-11-15. Compared main `9e6f231d0ded199793e8270d20ec60cdb765d28f` with microphone-limit commit
`ed097a30aeaa424cc25a7d9ade43b110312877fc`.

## Decision

Leave the existing guide PNGs and their capture/review fingerprints unchanged for this fix. The maintained
`settings-graphics.png` was visually inspected. It shows the Graphics tab, with Quality preset selected and its help
panel visible; it does not show the microphone selector or a recording-device name.

The only menu-code change in this topic is `kMaxMics` from 16 to 64. Its matching host change raises `MAX_DEVICES`
to 64. These constants affect microphone enumeration, name resolution and the range of the existing Gameplay →
Microphone selector. They do not add or move a row, change its label or help, alter tab navigation, or change any
Graphics setting. Off and Default remain unchanged. Systems with more than 16 endpoints can see additional names;
that behavior is covered by the before/after native regression, not illustrated by the existing Graphics image.

No new screenshot is supplied for this topic: the existing guide illustrations do not depict the changed device-list
content. A high-endpoint screenshot could supplement the regression evidence, but is not needed to replace an
unaffected guide illustration. Menu relocation and new audio controls are outside this topic and require their own
visual review when proposed.

## Existing drift and evidence limits

The read-only `scripts/check_guide_screenshots.py --review-sources` check validates all seven image assets but reports
12 changed Hookshot input fingerprints relative to its recorded `e9bed614` review. Eleven of those source paths are
unchanged by this topic. `gpu/vk/vk_menu.cpp` also contains upstream changes predating this fix, in addition to the
one changed microphone constant. The displayed Graphics help still describes the older VRAM-budget behavior, which
upstream main changed before this topic. This review does not certify that older illustration as a fresh rendering
of current main, resolve upstream source-review drift, or approve replacement fingerprints for unrelated changes.

Launcher source checks report `NOT CHECKED` because no Launcher checkout was supplied. This topic changes no
Launcher source or image. The image's original version caption, PNG, capture provenance and prior review metadata
remain intact. No fresh fixture rendering, pixel-equivalence test, gameplay capture or website render was performed.
