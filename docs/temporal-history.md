# Temporal history validity

DLSS, FSR 4, XeSS and the default FSR 3.1 path use the shared temporal chain. FSR 3.1's legacy path and frame interpolation prepare their own inputs. If camera reprojection fails, motion vectors are unavailable and the previous picture has no valid mapping to the current one. Each path must deliver a reset in that same frame rather than retaining unusable history.

Validate both input matrices and each result coefficient before converting to float. A finite double outside the float range is rejected before conversion. Preserve the existing algorithm, singularity threshold and age/size rules: valid consecutive camera motion retains history. This adds no camera-cut heuristic or interface change.

The game-free fixture compiles actual reprojection math, both preparation policies, the shared frame reset and all four consumer assignments (DLSS, FSR4, XeSS, FSR3.1). It covers singular and non-finite inputs, float overflow/boundaries, recovery, frame gaps, FSR3.1 size changes and valid perspectives at16:9 and ultrawide. Engine SDKs and a GPU are not required. CPU cases do not prove in-game frequency, visual gains or GPU handling of injected invalid matrices.

## DLSS feature creation and dynamic input sizes

NGX feature creation uses the selected quality mode's recommended render dimensions from
`NGX_DLSS_GET_OPTIMAL_SETTINGS`. The minimum and maximum dimensions returned by that call describe
the supported dynamic-resolution range; they size the shared input images and decide when an existing
feature can be reused. Each evaluation still receives the frame's actual render subrect. Native AA
creates its feature at the full render/output size.

Keep those dimensions separate: creating at the dynamic maximum instead of the recommendation can
increase the cost of models L and M even when the evaluation's render subrect is smaller. NVIDIA's
[Streamline DLSS implementation](https://github.com/NVIDIA-RTX/Streamline/blob/main/source/plugins/sl.dlss/dlssEntry.cpp)
also creates the feature using the recommended dimensions. `tests/test_dlss_feature_size.py` compiles
the actual preparation function with a recording SDK stand-in and checks creation, requested input
dimensions, range reuse, rounded sizes, native AA and failed queries for K, L and M. The fixture does
not allocate GPU images or execute NGX evaluation. In particular, a rounded Ultra Performance input
of 1147x480 against an advertised 1146x480 maximum still needs validation with the real NGX runtime.

## PsychoV35 with temporal upscalers

The gameplay TAAU replacement also supports Native HDR PsychoV35's RGBA16F buffers without this switch. It remains a
spatial upscale with FXAA, used where the game network cannot run correctly; this does not restore temporal AA. Its
input and output views, output shader and history all use the matching format. A format change discards its history;
the prior image stays alive until in-flight work can no longer use it. Its perceptual input is decoded once on output.

NVIDIA DLSS/DLAA, AMD FSR 4 (and its Native AA), Intel XeSS (and its Native AA) and FSR 3.1 on the shared chain automatically take the Native HDR PsychoV35 scene, whose gameplay network input and output are RGBA16F (`upscaler_rows.h` `takes_psychov35`: the engines the chain gives linear light in HDR). `RX_VK_PSYCHOV35_DLSS=0` disables this compatibility route; unset, empty or nonzero enables it. Both this chain and independent FSR FG admission use `upscaler_rows::psychov35_compatibility`, cached once per process. Vanilla's packed B10G11R11 route is unchanged. FSR 3.1's legacy `RX_VK_FSR3_CHAIN=0` upscaler remains unsupported; TAAU and Off are separate paths independent of this switch.

FSR 3.1's passes are already compiled for HDR input (`scripts/fsr3_shaders.py`). Its shared-chain engine opts into
linear HDR preparation/output only for Native HDR PsychoV35. Vanilla retains its existing perceptual preparation.
Changing the tone mapper or input format resets history. The route diagnostic names FSR 3.1, and the ordinary status
line counts its actual evaluations; a selected menu row alone does not prove the engine ran.


Upscaler Off also accepts Native HDR PsychoV35's matching RGBA16F input and output, without this switch. It bypasses
the game's network: at 100% the output shader fetches the corresponding input texel; below 100% it samples with a
linear filter. This path decodes the network input's perceptual colour once, unlike the HDR engines' output pass,
which receives already-linear colour. It adds no temporal anti-aliasing or frame-generation input handoff. Mixed
formats, unsupported scene formats and unrelated compute dispatches remain rejected.

The network's perceptual colour encoding still needs the existing HDR prep square to linear light, even though the scene tone-map pass itself writes linear colour. Storage precision does not determine that encoding. The typed RGBA16F output pass writes the engine's linear result without squaring again. FSR 4 takes the same pair: its context is made for HDR, linear colour while the game presents PQ (`vk_fsr4.cpp`), and the route waits for that context as DLSS's waits for its HDR feature (`RX_VK_FSR4_HDR=0` prevents it). XeSS takes the same pair, its context made for HDR with XeSS's own exposure (`vk_xess.cpp`; `RX_VK_XESS_HDR=0` prevents it). Changing the tone mapper or input format resets history.

Regenerate the output variant with glslang 16.6.0:

```sh
python -I -B tests/test_psychov35_dlss.py --write --glslang glslang --cxx clang++
```

The existing packed output header is unchanged. `tests/test_psychov35_dlss.py` checks format pairs, the same policy at camera/actor/reactive consumers, history resets, HDR prep selection and the compiled output's RGBA16F storage image type. `tests/test_psychov35_default.py` executes both admission gates with unset/empty/0/1/2, real Native HDR selection, mixed formats and unsupported FG multipliers.

### Hookshot review and NVIDIA frame generation

This path adapts [Hookshot #2707](https://github.com/NotRexed/Hookshot/pull/2707),
head `f1d654ce6f841fd4ce5bcbbe8900629a5394e484`, by nooblikejagger. It is an open draft at the time of review.
Its author reports a successful RTX 4070 SUPER HDR-display test for DLSS, but no controlled performance comparison
or NVIDIA frame-generation measurement. Those results do not validate this Hookshot port.

[Hookshot #2481](https://github.com/NotRexed/Hookshot/pull/2481) introduced PsychoV35 and deliberately narrowed
RGBA16F to Native HDR plus PsychoV35. Its discussion confirms that selecting DLSS and frame generation in the menu
did not prove they ran: the log revealed the format rejection and fallback. [Hookshot #2243](https://github.com/NotRexed/Hookshot/pull/2243)
established the native-HDR DLSS encoding; its author confirmed that it landed through
[Hookshot #2342](https://github.com/NotRexed/Hookshot/pull/2342). Removing the format
check alone would leave a packed-format storage shader bound to an RGBA16F image. Skipping the prep decode because
storage is floating point would instead change brightness.

[Hookshot #2118](https://github.com/NotRexed/Hookshot/pull/2118), merged, supplies the NGX frame-generation path
already in Hookshot. It takes the temporal chain's inputs and logs successful and fallback sets every 600 presents.
In Hookshot, `temporal_upscale` calls `dlss_fg_inputs` after a successful evaluation and output dispatch. That function
copies the frame's depth and motion and carries its camera and history reset; it does not inspect the scene colour format.
When the chain rejects RGBA16F, no new inputs reach it and `dlss_fg_frames` falls back with `FG_SKIP_INPUTS`.
Accepting the scene restores this handoff. Existing GPU/runtime support, fixed-multiplier, gap and maximum-frame checks
still apply; accepting RGBA16F does not promise that every present can use NVIDIA frame generation.

Runtime validation must start cold with Native HDR, PsychoV35, DLSS/DLAA, the switch above and a supported fixed NVIDIA
frame-generation multiplier. Verify the HDR feature creation, the log line `vk: PsychoV35 DLSS: RGBA16F linear route`
with network input and output format 97, repeated DLSS drawn-frame counts and `DLSS Frame Gen (NGX)` made-frame counts.
Compare against the switch off and Vanilla in the same scene, then switch tone mappers and DLSS/DLAA during play. Check
brightness on an HDR display, edges, actor motion, history resets and validation errors. With FSR 4 or its Native AA, the log
line is `vk: PsychoV35 FSR 4: RGBA16F linear route`, the status lines count `AMD FSR 4 ...: N frames drawn`, and no
`the game's upscale runs` follows; there is no NVIDIA frame generation to check. A transitional packed-format
frame after a hot switch is insufficient evidence; a menu selection alone is insufficient too. Record measured runs in
`tested-configurations.md`.

## Native HDR and FSR 3.1 frame generation

FSR 3.1 interpolation prepares its own scene depth and camera motion, and takes the shared chain's motion over it, the
skinned draws' own in it, whenever the chain makes one: with an engine drawing, or for the interpolation alone with none
(`temporal_fg_inputs`). It makes the frames at any Frame generation setting with Frame generation by at FSR 3.1 FG, or at DLSS FG where DLSS FG
does not (`RX_VK_FSR_FG=0` never, `=1` over the row). Native HDR PsychoV35 also needs the existing
compatibility policy (enabled unless `RX_VK_PSYCHOV35_DLSS=0`) to accept matching RGBA16F network buffers. Known and shape-detected networks use
matching sampled/storage views; mixed formats and unrelated dispatches are rejected. This does not enable the legacy
FSR 3.1 upscaler. Its PsychoV35 input compatibility defaults on. With PsychoV35 and no engine drawing, the chain does not
take the RGBA16F scene, so the interpolation keeps its own camera motion there.

The present copied into frame generation can contain PQ codes despite its UNORM capture storage. Pass the captured
present's native-PQ flag from both presentation paths; give the same transfer function and peak luminance to the AMD
frame-interpolation and optical-flow constant blocks. SDR retains transfer 0 and its unused 0..1 range; native PQ uses
transfer 1 and 0..the selected HDR peak in nits. This corrects Native HDR metadata for Vanilla too. The SDK fields are
documented in [AMD's frame-interpolation guide](https://gpuopen.com/manuals/fidelityfx_sdk/techniques/frame-interpolation/).
The constant-block layout is the SDK's; its one padding word carries the made frame's place (below).

Scene input format or tone-map changes reset depth/motion history. Encoding or PQ peak changes, frame gaps, cuts and
resizes reset interpolation history, so frames in different colour spaces are never blended. A reset frame keeps the
new source for the next interval but produces no AMD midpoint; existing fallback remains in effect for that frame.

Validate Native HDR PsychoV35 at 67/83/100%, Vanilla HDR and SDR, an HDR-peak change, FG Off/on, and camera movement.
On NVIDIA hardware, disable NVIDIA FG to isolate FSR. Inspect `fsr3fi` generated-frame and missing-input counts, the
PQ/peak diagnostic and actual generated captures; a selected menu row proves none of these. Record GPU/driver/OS,
scene and exact commits. These are functional checks, not an uncapped performance measurement or calibrated HDR proof.

AMD's passes make the midpoint only and move the HUD with the scene. `scripts/fsr3_shaders.py` (`FI_PATCHES`) compiles
them from a patched copy of the SDK's headers, `third_party/` unchanged: the made frame's place `t` (0 the frame before, 1
this one) comes from cbFI's padding word, so a set makes each of its frames at its own place (k/m at a fixed multiplier;
at Auto, each refresh's), and a pixel the same in both frames while the scene there moves (the HUD drawn over it) is kept
where it is (dispatchFlags bit 16; `RX_VK_FSR_FG_HUD=0` turns it off). The optical flow and the dilated inputs run once
a game frame, the rest once a made frame, and the interpolation is given every present it is asked for, with no frame to
make too, so its history is the frame before whatever the next set asks for. A semi-transparent HUD over a moving scene is
not the same in both frames and can still smear a little. This does not solve the separate general scene-transition
flicker.
