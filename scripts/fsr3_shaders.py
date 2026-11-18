"""Compile AMD's FSR 3.1 upscaler passes into the SPIR-V headers gpu/vk uses.

The FidelityFX SDK ships each pass as GLSL that includes the SDK's own GPU headers, so the eleven
variants below are the same eight passes compiled with different options. They are checked in like
every other shader in gpu/vk/shaders, so a clone builds without glslang; this script regenerates
them, and --check proves the checked-in files still match their sources (tests/test_fsr3_shaders.py).

    python -I -B scripts/fsr3_shaders.py            # write gpu/vk/shaders/fsr3_*_comp_spv.h
    python -I -B scripts/fsr3_shaders.py --check    # compare instead of writing
"""
import argparse
import difflib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "third_party/fidelityfx-sdk"
GPU = SDK / "include/FidelityFX/gpu"
PASSES = SDK / "shaders/fsr3upscaler"
FI_PASSES = SDK / "shaders/frameinterpolation"
OF_PASSES = SDK / "shaders/opticalflow"
OUT = ROOT / "gpu/vk/shaders"

# The option set the renderer records these passes under. Each one is a promise about the inputs:
# the colour is HDR, the motion is low-resolution and not jittered, and the depth is reversed. They
# have to match what gpu/vk/vk_fsr3.cpp hands the passes, which is why they live in one place.
OPTIONS = [
    "-DFFX_GPU=1",
    "-DFFX_GLSL=1",
    "-DFFX_FSR3UPSCALER_OPTION_UPSAMPLE_USE_LANCZOS_TYPE=2",
    "-DFFX_FSR3UPSCALER_OPTION_REPROJECT_USE_LANCZOS_TYPE=0",
    "-DFFX_FSR3UPSCALER_OPTION_HDR_COLOR_INPUT=1",
    "-DFFX_FSR3UPSCALER_OPTION_LOW_RESOLUTION_MOTION_VECTORS=1",
    "-DFFX_FSR3UPSCALER_OPTION_JITTERED_MOTION_VECTORS=0",
    "-DFFX_FSR3UPSCALER_OPTION_INVERTED_DEPTH=1",
]

# name, the pass GLSL it compiles, extra defines. The _nowave variants are for devices without the
# subgroup operations the single-pass downsampler prefers.
VARIANTS = [
    ("prepare_inputs", "prepare_inputs", []),
    ("luma_pyramid", "luma_pyramid", []),
    ("luma_pyramid_nowave", "luma_pyramid", ["-DFFX_SPD_NO_WAVE_OPERATIONS=1"]),
    ("shading_change_pyramid", "shading_change_pyramid", []),
    ("shading_change_pyramid_nowave", "shading_change_pyramid", ["-DFFX_SPD_NO_WAVE_OPERATIONS=1"]),
    ("shading_change", "shading_change", []),
    ("prepare_reactivity", "prepare_reactivity", []),
    ("luma_instability", "luma_instability", []),
    ("accumulate", "accumulate", []),
    ("accumulate_sharpen", "accumulate", ["-DFFX_FSR3UPSCALER_OPTION_APPLY_SHARPENING=1"]),
    ("rcas", "rcas", []),
]


# (hookshot) Frame interpolation and the optical flow it runs on, the same arrangement: AMD ships
# each pass as GLSL over the SDK's own GPU headers, and the renderer records them as SPIR-V headers
# beside the upscaler's. The options are the same promises about the same inputs -- the depth is
# reversed and the motion is at the render extent -- because the inputs are the ones the upscaler is
# already given (gpu/vk/vk_fsr3fi.cpp). The names are interpolation's own, not the upscaler's: its
# low-resolution motion option is LOW_RES_, where the upscaler's is LOW_RESOLUTION_. A name the SDK
# does not read is dropped without a word, so tests/test_fsr3_shader_options.py checks each one.
FI_OPTIONS = [
    "-DFFX_GPU=1",
    "-DFFX_GLSL=1",
    "-DFFX_FRAMEINTERPOLATION_OPTION_INVERTED_DEPTH=1",
    "-DFFX_FRAMEINTERPOLATION_OPTION_LOW_RES_MOTION_VECTORS=1",
    "-DFFX_FRAMEINTERPOLATION_OPTION_JITTERED_MOTION_VECTORS=0",
]
OF_OPTIONS = ["-DFFX_GPU=1", "-DFFX_GLSL=1"]

# (hookshot) Frame interpolation's GPU headers with two changes of ours, made on a copy at compile time: third_party/
# stays AMD's, byte for byte (scripts/check_third_party.py), and what changes is written here, line by line, each one
# found exactly as many times as it says or the script stops. gpu/vk/vk_fsr3fi.cpp fills what the changes read.
#
#  1. A made frame anywhere between the two game frames, not only the midpoint. AMD's passes fix t at 0.5: the vector
#     fields keep half the motion, put each vector at the pixel's place half way, and look half a motion back into the
#     frame before and half forward into this one. cbFI's padding word (_pad1) carries t instead (0: the frame before, 1:
#     this one), and the fields keep half the motion as before, scaled where it is used: 2t of it back to the frame before,
#     2(1 - t) forward to this one, the vector put at the pixel's place 2(1 - t) of it from this frame's, and the blend's
#     weights t and 1 - t. At t = 0.5 every scale is 1 and the passes are AMD's.
#  2. The HUD kept where it is (dispatchFlags bit 16, set unless RX_VK_FSR_FG_HUD=0). This game draws its HUD into the
#     same picture as the scene and has no HUD-less colour, so AMD's passes moved it with the scene behind it: smeared
#     icons and text, a copy of the HUD trailing the camera. A pixel the same in both frames while the scene there moves
#     is the HUD (or a flat colour, where the frame's own pixel is right too): it is this frame's pixel. A sample of the
#     frame before or this one that lands on such a pixel is the HUD, not the scene behind it, which neither frame shows:
#     where only one of the two samples does, the other is taken.
FI_T = "InterpolationT()"
FI_PATCHES = {
    "ffx_frameinterpolation_callbacks_glsl.h": [
        ("        FfxInt32        _pad1;\n",
         "        FfxFloat32      fInterpolationT;   // (hookshot) the made frame's place: 0 the frame before, 1 this one\n", 1),
        ("    FfxFloat32 TanHalfFoV()\n    {\n        return cbFI.fTanHalfFOV;\n    }\n",
         "    FfxFloat32 TanHalfFoV()\n    {\n        return cbFI.fTanHalfFOV;\n    }\n"
         "\n"
         "    // (hookshot) the made frame's place between the frame before (0) and this one (1): AMD's passes fix it at 0.5\n"
         "    FfxFloat32 InterpolationT()\n    {\n        return cbFI.fInterpolationT;\n    }\n"
         "    // (the vector fields keep half the motion: the frame before is 2t of it away, this one 2(1 - t))\n"
         "    FfxFloat32 PrevScale()\n    {\n        return 2.0f * cbFI.fInterpolationT;\n    }\n"
         "    FfxFloat32 CurrScale()\n    {\n        return 2.0f * (1.0f - cbFI.fInterpolationT);\n    }\n"
         "    // (hookshot) the HUD kept where it is (vk_fsr3fi.cpp kKeepStatic)\n"
         "    FfxBoolean KeepStaticPixels()\n    {\n        return (cbFI.dispatchFlags & (1u << 16)) != 0u;\n    }\n", 1),
    ],
    "ffx_frameinterpolation_game_motion_vector_field.h": [
        ("    const FfxFloat32x2 fInterpolatedLocationUv = fUvInScreenSpace + fMotionVectorHalf;\n",
         "    const FfxFloat32x2 fInterpolatedLocationUv = fUvInScreenSpace + fMotionVectorHalf * CurrScale();\n", 1),
        ("        const FfxFloat32 fBreakDist = ffxMin(length(fMotionVectorHalf), length(FfxFloat32x2(0.5f, 0.5f)));\n",
         "        const FfxFloat32 fBreakDist = ffxMin(length(fMotionVectorHalf * CurrScale()), length(FfxFloat32x2(0.5f, 0.5f)));\n", 1),
    ],
    "ffx_frameinterpolation_optical_flow_vector_field.h": [
        ("GetBilinearSamplingData(fUv + fMotionVectorHalf, GetOpticalFlowSize2());\n",
         "GetBilinearSamplingData(fUv + fMotionVectorHalf * CurrScale(), GetOpticalFlowSize2());\n", 1),
    ],
    "ffx_frameinterpolation_reconstruct_previous_depth.h": [
        ("    ReconstructPrevDepth(iPxPos, 1, fDilatedDepth, fMotionVector * 0.5f, RenderSize());\n",
         "    ReconstructPrevDepth(iPxPos, 1, fDilatedDepth, fMotionVector * 0.5f * CurrScale(), RenderSize());\n", 1),
    ],
    "ffx_frameinterpolation_disocclusion_mask.h": [
        ("ComputeDepthClip(0, fDepthUv + gameMv.fMotionVector, fDilatedDepth);\n",
         "ComputeDepthClip(0, fDepthUv + gameMv.fMotionVector * PrevScale(), fDilatedDepth);\n", 1),
        ("ComputeDepthClip(1, fDepthUv - gameMv.fMotionVector, fDilatedDepth);\n",
         "ComputeDepthClip(1, fDepthUv - gameMv.fMotionVector * CurrScale(), fDilatedDepth);\n", 1),
    ],
    "ffx_frameinterpolation_common.h": [
        # (LoadInpaintedGameFieldMv's and SampleOpticalFlowMotionVectorField's: whether each end is inside the frame)
        ("    vfElement.bNegOutside = !IsUvInside(fUv - vfElement.fMotionVector);\n",
         "    vfElement.bNegOutside = !IsUvInside(fUv - vfElement.fMotionVector * CurrScale());\n", 2),
        ("    vfElement.bPosOutside = !IsUvInside(fUv + vfElement.fMotionVector);\n",
         "    vfElement.bPosOutside = !IsUvInside(fUv + vfElement.fMotionVector * PrevScale());\n", 2),
    ],
    "ffx_frameinterpolation.h": [
        ("+gameMv.fMotionVector * fUvLetterBoxScale, DisplaySize());",
         "+gameMv.fMotionVector * PrevScale() * fUvLetterBoxScale, DisplaySize());", 1),
        ("-gameMv.fMotionVector * fUvLetterBoxScale, DisplaySize());",
         "-gameMv.fMotionVector * CurrScale() * fUvLetterBoxScale, DisplaySize());", 1),
        ("+ofMv.fMotionVector * fUvLetterBoxScale, DisplaySize());",
         "+ofMv.fMotionVector * PrevScale() * fUvLetterBoxScale, DisplaySize());", 1),
        ("-ofMv.fMotionVector * fUvLetterBoxScale, DisplaySize());",
         "-ofMv.fMotionVector * CurrScale() * fUvLetterBoxScale, DisplaySize());", 1),
        ("        FfxFloat32 t = 0.5f;\n"
         "        t += 0.5f * (1 - (fDisocclusionFactor.x));\n"
         "        t -= 0.5f * (1 - (fDisocclusionFactor.y));\n",
         f"        FfxFloat32 t = {FI_T};\n"
         f"        t += (1.0f - {FI_T}) * (1 - (fDisocclusionFactor.x));\n"
         f"        t -= {FI_T} * (1 - (fDisocclusionFactor.y));\n", 1),
        ("        fInterpolatedColor = ffxLerp(fPrevColorGame.fRaw, fCurrColorGame.fRaw, ffxSaturate(t));\n",
         "        fInterpolatedColor = ffxLerp(fPrevColorGame.fRaw, fCurrColorGame.fRaw, ffxSaturate(t));\n"
         "        HookshotStaticSamples(fUvInScreenSpace, gameMv.fMotionVector * fUvLetterBoxScale, t, fPrevColorGame.fRaw,\n"
         "                              fCurrColorGame.fRaw, fInterpolatedColor);\n", 1),
        ("        FfxFloat32 ofT = 0.5f;\n", f"        FfxFloat32 ofT = {FI_T};\n", 1),
        ("            ofT = 0.5f;\n", f"            ofT = {FI_T};\n", 1),
        ("        const FfxFloat32x3 ofColor = ffxLerp(fPrevColorOF.fRaw, fCurrColorOF.fRaw, ofT);\n",
         "        FfxFloat32x3 ofColor = ffxLerp(fPrevColorOF.fRaw, fCurrColorOF.fRaw, ofT);\n"
         "        HookshotStaticSamples(fUvInScreenSpace, ofMv.fMotionVector * fUvLetterBoxScale, ofT, fPrevColorOF.fRaw,\n"
         "                              fCurrColorOF.fRaw, ofColor);\n", 1),
        ("        fInterpolatedColor = ffxLerp(ofColor, fInterpolatedColor, ffxSaturate(fGameMvBias));\n    }\n}\n",
         "        fInterpolatedColor = ffxLerp(ofColor, fInterpolatedColor, ffxSaturate(fGameMvBias));\n    }\n"
         "    HookshotStaticPixel(FfxInt32x2(iPxPos), max(gameMv.fVelocity, ofMv.fVelocity), fInterpolatedColor,\n"
         "                        fInPaintingWeight);\n}\n", 1),
        # (the two helpers, ahead of computeInterpolatedColor, which calls them)
        ("void updateInPaintingWeight(inout FfxFloat32 fInPaintingWeight, FfxFloat32 fFactor)\n",
         "// (hookshot) The HUD kept where it is: a pixel the same in both frames (to within half an 8-bit step), inside the\n"
         "// frame. KeepStaticPixels says whether to look at all\n"
         "FfxBoolean HookshotSame(FfxInt32x2 iPx)\n"
         "{\n"
         "    if (!IsInRect(iPx, InterpolationRectBase(), InterpolationRectSize())) return false;\n"
         "    const FfxFloat32x3 fDiff = abs(LoadPreviousBackbuffer(iPx) - LoadCurrentBackbuffer(iPx));\n"
         "    return max(fDiff.r, max(fDiff.g, fDiff.b)) <= (0.5f / 255.0f);\n"
         "}\n"
         "\n"
         "// A blend of the two frames' samples (0 < t < 1: both ends seen) where one sample lands on a pixel the same in both\n"
         "// frames and the other does not: that one is the HUD, the scene behind it in neither frame, so the other is taken.\n"
         "// fMv: the vector the samples were taken with, in UV (half the motion, as the fields keep it)\n"
         "void HookshotStaticSamples(FfxFloat32x2 fUv, FfxFloat32x2 fMv, FfxFloat32 t, FfxFloat32x3 fPrev, FfxFloat32x3 fCurr,\n"
         "                           inout FfxFloat32x3 fColor)\n"
         "{\n"
         "    if (!KeepStaticPixels() || t <= 0.0f || t >= 1.0f || length(fMv * DisplaySize()) < 0.5f) return;\n"
         "    const FfxBoolean bPrev = HookshotSame(FfxInt32x2((fUv + fMv * PrevScale()) * DisplaySize()));\n"
         "    const FfxBoolean bCurr = HookshotSame(FfxInt32x2((fUv - fMv * CurrScale()) * DisplaySize()));\n"
         "    if (bPrev && !bCurr) fColor = fCurr;\n"
         "    else if (bCurr && !bPrev) fColor = fPrev;\n"
         "}\n"
         "\n"
         "// The made pixel itself: the same in both frames while the scene there moves (fVelocity: the larger of the two\n"
         "// fields' vectors, in UV) is the HUD, or a flat colour where this frame's pixel is right too: this frame's pixel\n"
         "void HookshotStaticPixel(FfxInt32x2 iPx, FfxFloat32 fVelocity, inout FfxFloat32x3 fColor, inout FfxFloat32 fInPaintingWeight)\n"
         "{\n"
         "    if (!KeepStaticPixels() || fVelocity * length(FfxFloat32x2(DisplaySize())) < 0.5f || !HookshotSame(iPx)) return;\n"
         "    fColor = LoadCurrentBackbuffer(iPx);\n"
         "    fInPaintingWeight = 0.0f;\n"
         "}\n"
         "\n"
         "void updateInPaintingWeight(inout FfxFloat32 fInPaintingWeight, FfxFloat32 fFactor)\n", 1),
    ],
}


def patched_fi_headers(tmp):
    """Frame interpolation's GPU headers with FI_PATCHES applied, in tmp/frameinterpolation: the directory that goes
    first on the include path, so "frameinterpolation/..." and the headers' own includes of each other find these."""
    src = GPU / "frameinterpolation"
    dst = Path(tmp) / "patched-gpu" / "frameinterpolation"
    shutil.copytree(src, dst)
    for name, edits in FI_PATCHES.items():
        path = dst / name
        text = path.read_text(encoding="utf-8")
        for old, new, count in edits:
            found = text.count(old)
            if found != count:
                raise SystemExit(f"fsr3_shaders.py: {name}: expected {count} of {old.strip()[:70]!r}, found {found} "
                                 "(the SDK changed: write the patch again)")
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")
    return dst

# (name, the pass file, extra defines). The file is named outright rather than composed: AMD's
# optical-flow v5 passes end "_pass_v5.glsl" and the interpolation pass itself is just
# "ffx_frameinterpolation_pass.glsl", so a composed name is wrong for four of the eighteen.
FI_VARIANTS = [
    ("fi_setup", "ffx_frameinterpolation_setup_pass.glsl", []),
    ("fi_reconstruct_previous_depth", "ffx_frameinterpolation_reconstruct_previous_depth_pass.glsl", []),
    ("fi_reconstruct_and_dilate", "ffx_frameinterpolation_reconstruct_and_dilate_pass.glsl", []),
    ("fi_game_motion_vector_field", "ffx_frameinterpolation_game_motion_vector_field_pass.glsl", []),
    ("fi_optical_flow_vector_field", "ffx_frameinterpolation_optical_flow_vector_field_pass.glsl", []),
    ("fi_disocclusion_mask", "ffx_frameinterpolation_disocclusion_mask_pass.glsl", []),
    ("fi_game_vector_field_inpainting_pyramid",
     "ffx_frameinterpolation_compute_game_vector_field_inpainting_pyramid_pass.glsl", []),
    ("fi_inpainting_pyramid", "ffx_frameinterpolation_compute_inpainting_pyramid_pass.glsl", []),
    ("fi_interpolate", "ffx_frameinterpolation_pass.glsl", []),
    ("fi_inpainting", "ffx_frameinterpolation_inpainting_pass.glsl", []),
]
OF_VARIANTS = [
    ("of_prepare_luma", "ffx_opticalflow_prepare_luma_pass.glsl", []),
    ("of_luminance_pyramid", "ffx_opticalflow_compute_luminance_pyramid_pass.glsl", []),
    ("of_generate_scd_histogram", "ffx_opticalflow_generate_scd_histogram_pass.glsl", []),
    ("of_compute_scd_divergence", "ffx_opticalflow_compute_scd_divergence_pass.glsl", []),
    ("of_compute_optical_flow_v5", "ffx_opticalflow_compute_optical_flow_advanced_pass_v5.glsl", []),
    ("of_filter_optical_flow_v5", "ffx_opticalflow_filter_optical_flow_pass_v5.glsl", []),
    ("of_scale_optical_flow_v5", "ffx_opticalflow_scale_optical_flow_advanced_pass_v5.glsl", []),
]


def compile_family(glslang, name, source, extra, out_path, target_env, options, includes,
                   variable=True):
    """One frame-interpolation or optical-flow pass. The upscaler's compile_one is kept as it is:
    its passes are composed by name and its option set is the upscaler's own."""
    cmd = [glslang, "-V", "--quiet", "-S", "comp"]
    for d in includes:
        cmd.append("-I" + str(d))
    cmd += [*options, *extra]
    if variable:
        cmd += ["--variable-name", f"FSR3_{name.upper()}_COMP_SPV"]
    cmd += ["-o", str(out_path), str(source), "--target-env", target_env]
    subprocess.run(cmd, check=True)


def compile_one(glslang, name, pass_name, extra, out_path, target_env, variable=True):
    """Compile one variant. With `variable`, glslang writes a C header; without it, binary SPIR-V,
    which is what spirv-val reads."""
    defines = list(OPTIONS)
    if not any("APPLY_SHARPENING" in d for d in extra):
        defines.append("-DFFX_FSR3UPSCALER_OPTION_APPLY_SHARPENING=0")
    cmd = [glslang, "-V", "--quiet", "-S", "comp",
           "-I" + str(GPU), "-I" + str(GPU / "fsr3upscaler"),
           *defines, *extra]
    if variable:
        cmd += ["--variable-name", f"FSR3_{name.upper()}_COMP_SPV"]
    cmd += ["-o", str(out_path),
            str(PASSES / f"ffx_fsr3upscaler_{pass_name}_pass.glsl"),
            "--target-env", target_env]
    subprocess.run(cmd, check=True)


def strip_generator(text):
    """The header without glslang's own version comment.

    glslang writes its version into the first line as `// 1116.2.0`, so two glslang builds produce
    byte-different headers from identical SPIR-V. Comparing the whole text made this check fail on
    a CI runner whose glslang was one release behind the one that generated the checked-in files --
    a version bump reported as a source mismatch, which is the kind of red that teaches people to
    ignore red. The words after it are the module, and those are what this is about.
    """
    return [line for line in text.splitlines()
            if not line.strip().startswith("// ") or not line.strip()[3:].replace(".", "").isdigit()]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--glslang", default=None, help="glslangValidator; found on PATH by default")
    p.add_argument("--spirv-val", default=None, help="spirv-val, to validate each module")
    p.add_argument("--target-env", default="spirv1.3")
    p.add_argument("--check", action="store_true", help="compare with the checked-in headers")
    a = p.parse_args()
    glslang = a.glslang or shutil.which("glslangValidator") or shutil.which("glslang")
    if not glslang:
        print("glslangValidator not found; pass --glslang", file=sys.stderr)
        return 2

    bad = []
    with tempfile.TemporaryDirectory(prefix="fsr3-shaders-") as tmp:
        # the upscaler's eleven, then frame interpolation's ten and optical flow's seven
        families = [(name, None, pass_name, extra, None, None) for name, pass_name, extra in VARIANTS]
        # (frame interpolation's headers patched first: FI_PATCHES. Their directory goes ahead of the SDK's)
        fi_headers = patched_fi_headers(tmp)
        families += [(name, FI_PASSES / f, None, extra, FI_OPTIONS,
                      [fi_headers.parent, GPU, fi_headers, GPU / "opticalflow"])
                     for name, f, extra in FI_VARIANTS]
        families += [(name, OF_PASSES / f, None, extra, OF_OPTIONS, [GPU, GPU / "opticalflow"])
                     for name, f, extra in OF_VARIANTS]
        for name, source, pass_name, extra, options, includes in families:
            header = OUT / f"fsr3_{name}_comp_spv.h"
            made = Path(tmp) / header.name
            if source is None:
                compile_one(glslang, name, pass_name, extra, made, a.target_env)
            else:
                compile_family(glslang, name, source, extra, made, a.target_env, options, includes)
            if a.spirv_val:
                spv = Path(tmp) / f"{name}.spv"
                if source is None:
                    compile_one(glslang, name, pass_name, extra, spv, a.target_env, variable=False)
                else:
                    compile_family(glslang, name, source, extra, spv, a.target_env, options,
                                   includes, variable=False)
                subprocess.run([a.spirv_val, str(spv)], check=True)
            if a.check:
                have = header.read_text() if header.exists() else ""
                want = made.read_text()
                if strip_generator(have) != strip_generator(want):
                    bad.append(name)
                    if not have:
                        print(f"{header.name}: missing", file=sys.stderr)
                    else:
                        diff = difflib.unified_diff(have.splitlines(), want.splitlines(),
                                                    "checked in", "regenerated", n=0, lineterm="")
                        print("\n".join(list(diff)[:12]), file=sys.stderr)
            else:
                shutil.copyfile(made, header)
                print(f"wrote {header.relative_to(ROOT)} ({header.stat().st_size} bytes)")
    if bad:
        print(f"{len(bad)} header(s) do not match their source: {', '.join(bad)}", file=sys.stderr)
        return 1
    print(f"fsr3 shaders: {len(VARIANTS) + len(FI_VARIANTS) + len(OF_VARIANTS)} {'match' if a.check else 'written'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
