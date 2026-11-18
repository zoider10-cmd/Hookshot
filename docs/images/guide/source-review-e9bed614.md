# Graphics guide image: source review against e9bed614

Retain the UI-only `settings-graphics.png` captured from
`b2911d33405e84fdad97248b409814a40dce69cb` after reviewing main
`e9bed6147fbbe052c53bb883ae5f93bd2f6025c5`, integrated into PR #264.
The PNG was inspected at full size during this review. Its caption continues
to identify the original development build and illustrative Custom settings.
This record supersedes the older cf605c85 review, which concerned a replaced PNG.

The combined tree initially produced four `REVIEW REQUIRED` errors. These are
the only previously recorded menu inputs that changed since the capture:

| Source | Change and retention decision |
|---|---|
| `gpu/vk/vk_api.h` | Adds the `HOS_OPT_RENDER_THREAD` option identifier and documentation. It adds no pictured text or control and does not change the drawing fixture's host interface. |
| `gpu/vk/vk_menu.cpp` | Adds **Threaded rendering**, its hints, and the startup accessor. The new row is after **GPU device** in **GPU and memory**, below this first unscrolled view. The pictured rows, Quality preset help, navigation labels and input prompts remain unchanged. The website's complete settings list imports the new row from source. |
| `gpu/vk/vk_menu.h` | Adds `Options::threaded_rendering = 0` and the accessor declaration. The fixture accesses options by name, and the defaults of its pictured settings are unchanged. Its restart snapshot iterates the maintained row table, including the new row. |
| `gpu/vk/vk_recorder.h` | Adds the menu callback used to choose recorder mode. Command recording is not initialized by the drawing fixture; this does not alter the pictured controls. |

The new direct dependency `gpu/vk/threaded_rendering.h` is now recorded in
`reviewed_source.files`. It defines the new row's choices and policy, includes no
further headers, and was inspected along with the changed sources. The remaining
58-input capture set, except for the four files above, is unchanged. Fonts,
translations, ImGui and the capture helpers are unchanged.

Main advanced again to `2b1d38c682baaa4d52f2cacc75fffb9505c1f34f` before
publication. That revision is also integrated. All 59 reviewed menu inputs and
both capture helpers are unchanged from the reviewed e9bed614 sources.

Retention means the image still teaches the labelled controls; it does not mean
that a new capture would be pixel-identical. The additional off-screen row changes
the proportional scrollbar thumb (`scroll_bar` uses the total row count), and the
menu measures help across its rows. No fresh rendering or pixel-equivalence check
was performed. Neither scrollbar dimensions nor exact help-panel dimensions are
instructions in this guide. The original version banner, capture date, PNG hash,
`captured_source` and capture conditions remain unchanged.

The website regression test initially failed because its exact restart list
omitted **Threaded rendering**. The expected list now includes it without changing
the coverage or restart-mismatch assertions. The source guard is rerun against
the combined tree after this review, including the new dependency.

This is a source-and-existing-image review, not a fresh fixture capture or a live
game comparison. No game, capture build, save transfer or runtime experiment was
performed. Browser results reported by the maintainer on the prior PR head remain
separate evidence; they do not establish rendered validation of this update.
