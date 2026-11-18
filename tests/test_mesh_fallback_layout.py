"""The compute fallback's record layouts (RX_VK_MESH_FB_LAYOUT=aos or soa; emit_spirv.h MeshFallbackLayout) through the
real SPIR-V back end, without game files or a GPU.

tests/mesh_fallback_layout_ir.cpp emits each layout's mesh stage (a program that writes its stage buffer as a game's does) and
generated vertex stage for the shapes the fallback's programs take. Every module passes spirv-val (SPIR-V 1.6; the vertex stages
Vulkan 1.3 too: the mesh stages' workgroup arrays carry an ArrayStride that Vulkan 1.3's rules refuse, as every mesh fallback
program on main does). RuntimeInfo's layout left unset (0) translates byte for byte as aos, the way main did before soa;
soa changes every program. The switch unset is soa (mesh_rule::fb_layout, which the model checks).

tests/mesh_fallback_layout_model.cpp models what each layout's workgroups write and what its draw reads, for random meshlets
and past the area: every layout draws the meshlets' own primitives, in order, with the same corners first.

And the wiring: the switch is a name under RX_VK_MESH, which the program cache's stamp takes (a run with it translates again,
a run without it keeps its caches), and the translation hands it to the mesh stage and its vertex stage alike.

    python -I -B tests/test_mesh_fallback_layout.py --headers <SPIRV-Headers/include> [--spirv-val spirv-val] [--cxx g++] [--jobs N]
"""
import argparse
import concurrent.futures
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{spirv_headers}", "--spirv-val", "{spirv_val}"]
RUN_ALL_SKIP = {"windows": "builds the SPIR-V back end with POSIX compiler flags and needs spirv-val: checked on Linux"}

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
SHAPES = ("tri-pos-first", "tri-pos-later-prim", "tri-wide", "tri-task", "lines", "points")


def cxx_std(cxx):
    """-std=c++23 where the compiler has it, else -std=c++2b, as nx2/bake_mimo.py's cxx_std: gpu/vk/compat/common/assert.h needs
    C++23's static in a constexpr function (g++ 13 refuses it under -std=c++20)"""
    probe = "constexpr int f(int n){if(n<0){static int x=0;return ++x;}return n;} static_assert(f(1)==1);"
    for std in ("-std=c++23", "-std=c++2b"):
        if subprocess.run([cxx, std, "-x", "c++", "-fsyntax-only", "-"], input=probe, text=True, capture_output=True).returncode == 0:
            return std
    sys.exit("FAIL: %s has no C++23 mode: the recompiler needs one" % cxx)


def flags(args):
    out = [cxx_std(args.cxx), "-include", str(VK / "compat" / "hookshot_env.h"), "-O1", "-w", "-D_CRT_SECURE_NO_WARNINGS",
           "-DVK_NO_PROTOTYPES", "-DMKWVK_INCLUDES=2", "-DNDEBUG"]
    for header in ("algorithm", "cstdio", "cstdlib", "cstring", "functional", "string", "vector"):
        out += ["-include", header]
    return out + ["-I" + str(p) for p in (VK, VK / "compat", ROOT / "gpu/compat", VK / "eden", ROOT / "gpu/third_party/suyu",
                                          VK / "sirit/include", VK / "sirit/src", args.headers)]


def build(args, folder):
    sources = sorted({p for d in ("eden/shader_recompiler/backend/spirv", "eden/shader_recompiler/frontend/ir",
                                  "eden/shader_recompiler/ir_opt", "sirit/src") for p in (VK / d).rglob("*.cpp")})
    f = flags(args)
    all_sources = [ROOT / "tests" / "mesh_fallback_layout_ir.cpp", *sources]
    objs = [folder / ("%03d-%s.o" % (i, s.stem)) for i, s in enumerate(all_sources)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        results = list(pool.map(lambda so: subprocess.run([args.cxx, *f, "-c", str(so[0]), "-o", str(so[1])],
                                                          capture_output=True, text=True), zip(all_sources, objs)))
    for source, result in zip(all_sources, results):
        if result.returncode:
            print(result.stdout, result.stderr, end="")
            return None, "%s does not compile" % source.name
    exe = folder / "mesh_fallback_layout_ir.exe"
    linked = subprocess.run([args.cxx, *f, *map(str, objs), "-o", str(exe)], capture_output=True, text=True)
    if linked.returncode:
        print(linked.stdout, linked.stderr, end="")
        return None, "the fixture does not link"
    model = folder / "mesh_fallback_layout_model.exe"
    made = subprocess.run([args.cxx, *f, "-O2", str(ROOT / "tests" / "mesh_fallback_layout_model.cpp"), "-o", str(model)],
                          capture_output=True, text=True)
    if made.returncode:
        print(made.stdout, made.stderr, end="")
        return None, "the model does not compile"
    return (exe, model), None


def wiring(fails):
    shader = (VK / "vk_shader.cpp").read_text(encoding="utf-8")
    stamp = shader[shader.index("uint64_t translator_stamp() {"):]
    stamp = stamp[:stamp.index("\n}\n")]
    if '"RX_VK_MESH"' not in stamp:
        fails.append("translator_stamp no longer takes the RX_VK_MESH switches: RX_VK_MESH_FB_LAYOUT would not key the program cache")
    for line in ("mrt.mesh_fallback_layout = fallback ? mesh_fallback_layout() : 0;",
                 "vrt.mesh_fallback_layout = mrt.mesh_fallback_layout;",
                 'mesh_rule::fb_layout(getenv("RX_VK_MESH_FB_LAYOUT"))'):
        if line not in shader:
            fails.append("vk_shader.cpp: no `%s`" % line)
    if "RX_VK_MESH_FB_LAYOUT" not in (ROOT / "docs" / "development.md").read_text(encoding="utf-8"):
        fails.append("docs/development.md does not describe RX_VK_MESH_FB_LAYOUT")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--headers", type=Path, required=True)
    p.add_argument("--spirv-val", default="spirv-val")
    p.add_argument("--cxx", default="g++")
    p.add_argument("--jobs", type=int, default=4)
    a = p.parse_args()
    fails = []
    wiring(fails)
    with tempfile.TemporaryDirectory(prefix="mesh-fallback-layout-") as tmp:
        tmp = Path(tmp)
        exes, why = build(a, tmp)
        if exes is None:
            sys.exit("FAIL: " + str(why))
        fixture, model = exes
        modules = tmp / "modules"
        modules.mkdir()
        r = subprocess.run([str(fixture), str(modules)], capture_output=True, text=True)
        if r.returncode:
            sys.exit("FAIL: the fixture: %s%s" % (r.stdout, r.stderr))
        count = 0
        for spv in sorted(modules.glob("*.spv")):
            count += 1
            for env in ("spv1.6",) + (("vulkan1.3",) if spv.name.endswith("-vertex.spv") else ()):
                val = subprocess.run([a.spirv_val, "--target-env", env, str(spv)], capture_output=True, text=True)
                if val.returncode:
                    fails.append("%s: spirv-val (%s): %s" % (spv.name, env, (val.stdout + val.stderr).strip()[:400]))
        same = lambda x, y: (modules / x).read_bytes() == (modules / y).read_bytes()
        for shape in SHAPES:
            for stage in ("mesh", "vertex"):
                m = lambda layout: "%s-%s-%s.spv" % (shape, layout, stage)
                if not same(m("default"), m("aos")):
                    fails.append("%s: RuntimeInfo's layout unset is not aos's translation" % m("default"))
                if same(m("aos"), m("soa")):
                    fails.append("%s: soa translates as aos" % m("soa"))
        r = subprocess.run([str(model)], capture_output=True, text=True)
        print(r.stdout.strip())
        if r.returncode or "0 failed" not in r.stdout:
            fails.append("the model: %s%s" % (r.stdout.strip()[-2000:], r.stderr.strip()))
    if fails:
        print("\n".join("FAIL: " + f for f in fails))
        sys.exit(1)
    print("PASS: %d modules spirv-val clean; aos as main, soa its own; the model's layouts draw the same" % count)


if __name__ == "__main__":
    main()
