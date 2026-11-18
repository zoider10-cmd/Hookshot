"""A draw's descriptors through the per-binding reuse (RX_VK_DESC_KEEP, from Triforce v0.5.0 72793f2 tests/test_desc_keep.py):
each one takes what the program's draw before left it only while every input and stamp it was resolved from is the same.

1. gpu/vk/desc_keep.h compiled alone (case header): for each kind (a sampled texture, a user uniform buffer, a stage's constants, a
   read-only storage buffer) every input and every stamp it stands on stops a take when it moves, and no other kind's result is
   taken; another program or count in a slot empties it.
2. vk_draw.cpp's block before build_descriptors (desc_keep_mode, kept_uniform, kept_texture, buf_stamps, buf_keep, keep_check) cut
   out of the source and run against stand-ins for texture_view_of, sampler_for, uniform_range and the generations
   (tests/desc_keep_test.cpp), which count their calls: a texture is looked up again when its slot is registered anew, a sampler
   registration changed, a texture was destroyed or made again or a frame left one for later (issue 1126: the destroy
   generation), or the submission is a new one; a uniform buffer when an inline update came, a pool moved or a mirror was made
   (gpu_bind_stamp), or the recording is another; c1 within its recording; never a failed one, a copy in the recording's stream,
   a driver bank, or a user uniform buffer under the uniform snapshot. A generation that moves while its lookup runs makes the
   next one look again. Off unless RX_VK_DESC_KEEP=1; =check resolves every time and counts and logs one that comes out
   otherwise; RX_VK_DESC_REUSE=never, RX_VK_SAMPLER_CACHE=0, RX_VK_LATE_DEFER=1 and the diagnostics turn it off.
3. build_descriptors itself (source): only a draw's build keeps (not a dispatch's or a dump's); the textures go through
   kept_texture and the uniform buffers through kept_uniform; a handle table's elements are not kept; a storage buffer is kept
   only when single and read-only and not of a program that picks among pointers, its stamps read before its binding and its
   result kept after; every descriptor kind moves the place counter, so each kept result is its own descriptor's; a new
   recording moves the recording's stamp; the words go to the same DescWriter the push (templates, delta) reads.
python -I -B tests/test_desc_keep.py --headers <Vulkan include folder> [--cxx g++] [--source <vk_draw.cpp>]
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
from srccut import between, block   # noqa: E402

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]
CASES = ["header", "default", "on", "off", "no-reuse", "sampler-cache-off", "late-defer", "texture", "compute", "texture-moved",
         "texture-dummy", "texture-no-sampler", "uniform", "uniform-snapshot", "uniform-stream", "uniform-moved", "c1", "storage",
         "check", "check-bad"]


def need(cond, why):
    if not cond:
        raise SystemExit(why)


def check_build(source):
    build = block(source, "void build_descriptors(")
    need("void build_descriptors(const NvnState& s, const Program& p, bool keep = false) {" in source,
         "build_descriptors keeps unless asked to (keep: a draw's build only)")
    need("desc_keep::Prog* const kp = keep && desc_keep_mode() && !dump_on()" in build,
         "build_descriptors keeps descriptors outside a draw's own build, or in a dump")
    need("build_descriptors(s, p, true);" in block(source, "void draw(VkCommandBuffer"), "a draw does not keep its descriptors")
    need(source.count("build_descriptors(s, p, true)") == 1, "something other than a draw keeps descriptors")
    need(build.count("jn += d.count;") == 5, "a descriptor kind does not move the place counter: kept results would be another's")
    need("kept_uniform(kp, jb + k, s, st, d.index + k)" in build, "the uniform buffers do not go through kept_uniform")
    need("uniform_range(" not in build, "a uniform buffer is resolved past kept_uniform")
    need("smp = kept_texture(is_table ? nullptr : kp, jb + k, handle, vt, d.is_depth," in build,
         "the sampled textures do not go through kept_texture, or a handle table's elements are kept")
    need("sampler_for(" not in build and "texture_view_of(handle, vt, ViewUse::Sample" not in build,
         "a sampled texture is looked up past kept_texture")
    need("out.put_image(smp, view)" in build, "a sampled texture's descriptor is not what kept_texture gave")
    ssbo = between(build, "for (const auto& d : info.storage_buffers_descriptors)", "auto texel_views")
    need("kp && d.count == 1 && !d.is_written && !info.native_global_bounds" in ssbo,
         "a storage buffer other than a single read-only one is kept")
    need(ssbo.index("buf_stamps(desc_keep::kSsbo)") < ssbo.index("gpu_buffer_bind("),
         "a storage buffer's stamps are read after it is bound")
    need(ssbo.index("out.put_buffer(sbi);") < ssbo.index("buf_keep(*kp, jb + k, *ke, desc_keep::kSsbo, addr, size, kn, kept_took, (bool)b, sbi)"),
         "a storage buffer is kept before its result, or without saying whether it was bound")
    need("dw()." not in build, "build_descriptors asks for the thread's writer again: the push reads `out`")
    begin = block(source, "void draw_begin_recording(")
    need("desc_rec++" in begin and begin.index("cur = &r;") < begin.index("desc_rec++"),
         "a new recording keeps the last one's buffers")
    disp = block(source, "void dispatch(VkCommandBuffer")
    need("build_descriptors(s, p);" in disp, "a dispatch's build is not the plain one")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--headers", type=Path, required=True)
    p.add_argument("--cxx", default="g++")
    p.add_argument("--source", type=Path, default=ROOT / "gpu" / "vk" / "vk_draw.cpp", help="another vk_draw.cpp (a mutation)")
    a = p.parse_args()
    source = a.source.read_text(encoding="utf-8")
    check_build(source)
    keep = between(source, "// ---- (Triforce) Per-binding descriptor reuse (desc_keep.h) ----", "void build_descriptors(")
    fixture = (ROOT / "tests" / "desc_keep_test.cpp").read_text(encoding="utf-8").replace("/* KEEP */", keep)
    with tempfile.TemporaryDirectory(prefix="desc-keep-") as tmp:
        cpp, exe = Path(tmp) / "fixture.cpp", Path(tmp) / "fixture.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers", "-pthread",
                        "-I" + str(a.headers), "-I" + str(ROOT / "gpu" / "vk"), str(cpp), "-o", str(exe)], check=True)
        for case in CASES:
            subprocess.run([str(exe), case], check=True, timeout=20)
    print("PASS: %d cases: a kept descriptor is taken only while what it was resolved from stands" % len(CASES))


if __name__ == "__main__":
    main()
