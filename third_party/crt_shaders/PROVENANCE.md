# CRT shader sources

These four files are unchanged copies from [libretro/slang-shaders](https://github.com/libretro/slang-shaders),
commit [`2345ee91602a7404d3a1a6a5df6108d7305fdad4`](https://github.com/libretro/slang-shaders/tree/2345ee91602a7404d3a1a6a5df6108d7305fdad4).
Paths below are relative to this directory and match upstream. `SHA256SUMS` hashes the original bytes, without
line-ending conversion. The local `.gitattributes` disables Git text conversion for the imports, including on Windows.
The notices in the source files are authoritative and have not been removed or replaced.

| Upstream file | SHA-256 | Author / licence |
|---|---|---|
| [`crt/shaders/crt-lottes.slang`](https://github.com/libretro/slang-shaders/blob/2345ee91602a7404d3a1a6a5df6108d7305fdad4/crt/shaders/crt-lottes.slang) | `e382eec413c2acf5d03cce65d447347553032acf2e550826d0142a9c51d559ef` | Timothy Lottes; explicit PUBLIC DOMAIN dedication, including permission to take, use and change it |
| [`crt/shaders/hyllian/crt-hyllian-fast.slang`](https://github.com/libretro/slang-shaders/blob/2345ee91602a7404d3a1a6a5df6108d7305fdad4/crt/shaders/hyllian/crt-hyllian-fast.slang) | `4b8dc17d092440d6e1edd31aaea41165bc491e82e112ddb974f1db2d450be11e` | Copyright 2011–2015 Hyllian; cgwg's magenta/green dotmask; GLSL/Slang ports by DariusG and hunterk; full MIT permission and warranty notice |
| [`crt/shaders/zfast_crt/zfast_crt_finemask.slang`](https://github.com/libretro/slang-shaders/blob/2345ee91602a7404d3a1a6a5df6108d7305fdad4/crt/shaders/zfast_crt/zfast_crt_finemask.slang) | `0214419beed4c08d991288e90f8a73700fd7da567a454ad2ffe725b3b6eea366` | FINEMASK entry point for the implementation below |
| [`crt/shaders/zfast_crt/zfast_crt_impl.inc`](https://github.com/libretro/slang-shaders/blob/2345ee91602a7404d3a1a6a5df6108d7305fdad4/crt/shaders/zfast_crt/zfast_crt_impl.inc) | `e1006274577b85f18ed793856b46f92d5cd6f6207a98af398004644006907bf1` | Copyright 2017 Greg Hogan (SoltanGris42); explicit GPL-2.0-or-later; credits Inigo Quilez's scaling algorithm |

`PROVENANCE.md`, `SHA256SUMS` and `.gitattributes` are Hookshot packaging files, not upstream imports. No other shaders,
presets, assets or licences from the collection are imported here. The upstream authors retain their notices; Hookshot's
adapters and packaging changes are distinct from these copies.

## Compute adapters and the intentional differences

The hand-adapted sources are outside this directory, in `gpu/vk/shaders/crt_lottes.comp`, `crt_hyllian.comp` and
`crt_zfast.comp`. Each retains its upstream notice. These are fixed native ports, not a Slang/preset loader.
`tests/test_crt_shaders.py` compares their filter math with the pinned source sections, in addition to checking these
hashes, the defaults and the generated headers.

All three replace the vertex/fragment stages and RetroArch uniforms with an 8×8 compute dispatch, binding 0 `Source`
(combined sampler), binding 1 `dst` (write-only RGBA8), and exactly 36 bytes of push constants:
`vec4 SourceSize; vec4 OutputSize; uint style;`. Each size is `(width, height, 1/width, 1/height)`. The input is the actual
virtual raster, not a full-resolution image with fictitious source dimensions. Pixel centres in the destination
rectangle supply the texture coordinates; masks use destination-pixel dimensions. All texture reads explicitly use
LOD 0, and every adapter writes alpha 1. Out-of-range dispatch invocations do not write. Samplers use opaque-black
clamp-to-border: nearest for Lottes/Hyllian, linear for zfast.

- **Lottes:** retains the sRGB/linear transfer functions, Gaussian horizontal reconstruction, scanline weights, bloom,
  distortion and shadow-mask math. The fixed parameters are the upstream defaults, except for the two selected looks:
  `style == 1` selects `shadowMask = 2` (aperture grille) and `warpX = warpY = 0`; `style == 2` selects `shadowMask = 1`
  (compressed TV mask) with the original `warpX = 0.031`, `warpY = 0.041`. The flat look is professional-monitor-style,
  **not a calibrated Sony PVM/BVM model**. Bloom stays enabled; `SIMPLE_LINEAR_GAMMA` stays disabled. The inactive
  `GL_ES` border workaround is omitted; the Vulkan sampler supplies the original black-border behavior.
- **Hyllian Fast:** retains Catmull–Rom/Hermite reconstruction, gamma, scanline strength/brightness and cgwg's dotmask,
  with every upstream parameter at its default (`SHARPER = 0`, Catmull–Rom). The vertex stage's reciprocal pixel size
  `ps` and `(-0.49999, 0)` texture-coordinate offset are evaluated per compute invocation, before the original fragment
  math. The only numerical-domain fix is `max(color, vec3(0.0))` immediately before `GAMMA_IN`: cubic negative lobes
  can otherwise feed negative RGB to fractional `pow`, whose GLSL result is undefined. Values above 1 are not clipped
  there; the original positive-domain math remains unchanged. The unused `InputSize` alias and vertical `dy` are omitted.
- **zfast:** retains the FINEMASK entry point's sharper Quilez scaling, horizontal blur mix, brightness-dependent
  scanlines and mask fade, with all six upstream defaults. Vertex values `maskFade = 0.3333 * MASK_FADE` and
  `invDims = 1 / SourceSize.xy` are carried into compute. The disabled `BLACK_OUT_BORDER` branch (which references an
  undeclared `tc` upstream) is omitted; black borders come from the sampler. The fragment source assigns only RGB;
  the compute adapter explicitly supplies opaque alpha rather than carrying an undefined value.

`gpu/vk/shaders/crt_downsample.comp` is Hookshot code, not an upstream shader. It has the same two descriptor bindings,
no push constants, and integrates each destination pixel's rectangular footprint over the source texel squares with
`texelFetch` and exact overlap weights. It works when either source axis is smaller than the virtual raster as well
as for downsampling. It does not approximate area filtering with a few bilinear samples. The renderer supplies the
already cropped/scaled finished SDR image; the shaders neither crop again nor force a 4:3 aspect ratio.

These shaders expect SDR code values. The renderer applies them after window effects and before HDR expansion and
Hookshot overlays, and bypasses them for Native PQ without changing the saved selection. Off does not invoke them.

## Regenerating checked-in SPIR-V

From the repository root, with glslang installed:

```
python -I -B scripts/crt_shaders.py --glslang glslangValidator
python -I -B scripts/crt_shaders.py --check --glslang glslangValidator
python -I -B tests/test_crt_shaders.py --glslang glslangValidator
```

The generator uses `-V --target-env vulkan1.2 --vn` and writes `gpu/vk/shaders/crt_{lottes,hyllian,zfast,downsample}_comp_spv.h`;
the array names are respectively `CRT_LOTTES_COMP_SPV`, `CRT_HYLLIAN_COMP_SPV`, `CRT_ZFAST_COMP_SPV` and
`CRT_DOWNSAMPLE_COMP_SPV`. Every header starts with the adapter's SHA-256 and generation command, followed by its notice
and glslang's output. Headers are checked in, so player builds need no shader compiler. `--check` always checks the
source hash/notice; it recompiles when glslang is available (required if explicitly supplied). It compares SPIR-V words
with the same compiler version, and reports a different-version mismatch as not byte-comparable, not as a source mismatch.
Source checks and compiler checks are not GPU execution or visual-fidelity evidence.

tree-sha256: ebf3121502f455fa4e14fe60e46ee5ce34e823bcc0e92ee1d83381e6382ae772
