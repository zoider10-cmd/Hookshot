"""The Windows game builds the Vulkan back end only, as the Linux one does: no WebGPU renderer, no wgpu-native.

Every Windows build used to compile TOTKPort's WebGPU renderer (gpu/render/*.cpp) and suyu's shader recompiler with its WGSL
back end into the exe (nx2/build.py gpu_sources, ~160 C++ files at -O2) when tools.lock's wgpu-native was there, and the
builder downloaded it for every player, while the game drew with it only when RX_BACKEND named another renderer than Vulkan
or Vulkan did not start. The renderer and RX_BACKEND are gone: the exe is linked with the stand-ins host/rx_nowgpu.c (Linux:
host/posix/linux_stubs.c), which draw nothing.

Reads the source: the build compiles nothing of gpu/render's and names no wgpu-native, no tool list asks for it, host/rx_backend.c
starts the Vulkan back end without RX_BACKEND, and every renderer function the host names is defined by the stand-ins on both
platforms (the link). No game, no compiler.

python -I -B tests/test_no_webgpu.py
"""
import ast
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(what, ok):
    if not ok:
        raise SystemExit("FAIL: " + what)


def read(*parts):
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def defined(source):
    """The C functions a file defines (a name, its parameters, then its body)"""
    return set(re.findall(r"^[A-Za-z_][\w \*]*?\b(\w+)\([^;{]*\)\s*\{", source, re.M))


def main():
    build = read("nx2", "build.py")
    tree = ast.parse(build)
    functions = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    check("nx2/build.py still has gpu_sources (the WebGPU renderer's sources)", "gpu_sources" not in functions)
    check("nx2/build.py still reads WGPU_NATIVE or wgpu-native", "WGPU" not in names and "WGPU_NATIVE" not in build
          and "webgpu.h" not in build and "wgpu_native" not in build and "rx_wgpu_names" not in build)
    # (gpu/render is a dependency of the Vulkan back end's objects, for its headers: nothing of it is compiled. It is one of the
    # folders whose headers the objects are named by, vdeps_roots: the blob of all of them, vdeps, and the depfiles' headers
    # under them, renderer_deps)
    render = [line for line in build.splitlines() if 'os.path.join(GPU, "render")' in line]
    check("nx2/build.py uses gpu/render for more than the Vulkan back end's header dependencies: %r" % render,
          len(render) == 1 and render[0].strip().startswith("vdeps_roots = (") and "vdeps = tree_headers(*vdeps_roots)" in build
          and "renderer_deps(vdeps, vdeps_roots, obj)" in build)
    check("nx2/build.py leaves host/rx_nowgpu.c out of the Windows build", "have_wgpu" not in build and re.search(
        r'not \(LINUX and f in \("display\.c", "mf_av1\.c", "rx_nowgpu\.c"\)\)\s*\n\s*and \(f != "dav1d_av1\.c"', build))
    sources = sorted(p.name for p in (ROOT / "gpu" / "render").iterdir() if p.suffix in (".c", ".cpp"))
    check("gpu/render still has sources: %s" % sources, not sources)
    for header in ("rx.h", "rx_nvn.h", "nvn_api.h"):   # (host/display.c, host/nvn_native.c, gpu/vk/vk_api.h)
        check("gpu/render/%s is gone: the host or the Vulkan back end includes it" % header, (ROOT / "gpu" / "render" / header).is_file())

    lock = read("tools.lock")
    check("tools.lock still has wgpu-native", not re.search(r"^tool wgpu-native ", lock, re.M))
    spec = importlib.util.spec_from_file_location("tools_under_test", ROOT / "scripts" / "tools.py")
    tools = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tools)
    check("scripts/tools.py still requires wgpu-native", all("wgpu-native" not in need for need in tools.REQUIRED.values()))
    check("the builder still points WGPU_NATIVE at a tools folder", "WGPU_NATIVE" not in read("builder", "HookshotBuilder", "Runner.cs"))
    beside = next(line for line in read("nx2", "make_game.py").splitlines() if line.startswith("BESIDE = "))
    check("make_game.py still copies wgpu_native.dll into the game folder", "wgpu_native" not in beside)

    backend = read("host", "rx_backend.c")
    start = backend[backend.index("int rx_start(void *hwnd) {"):]
    start = start[:start.index("\n}\n")]
    check("host/rx_backend.c still reads RX_BACKEND", 'getenv("RX_BACKEND")' not in backend)
    check("rx_start does not start the Vulkan back end first, unconditionally",
          start.index("load_vulkan(dll)") < start.index("wgr_start(hwnd)") and "if (!b" not in start)
    load = backend[backend.index("static const MkwVkRenderer *load_vulkan(const char *dll) {"):]
    load = load[:load.index("\n}\n")]
    check("load_vulkan still names a WebGPU renderer to fall back to", "WebGPU" not in load and "RX_BACKEND" not in load)

    # (the link: every wgr_* the host declares, and the live input's commands, defined by each platform's stand-ins)
    wanted = set(re.findall(r"^[\w \*]*?\b(wgr_\w+)\(", backend, re.M)) | {"rx_collect_written"}
    hid = read("host", "nn_hid.c")
    wanted |= {n for n in ("rx_request_frame_dump", "rx_set_screenshot_ms", "rx_request_rdoc_capture", "rx_flash_dark_arm")
               if n + "(" in hid}
    check("host/rx_backend.c declares no wgr_* stand-ins (the check reads the wrong file)", len(wanted) > 10)
    for path in (("host", "rx_nowgpu.c"), ("host", "posix", "linux_stubs.c")):
        missing = sorted(wanted - defined(read(*path)))
        check("%s does not define %s: the game does not link" % ("/".join(path), ", ".join(missing)), not missing)
    print("ok   no WebGPU renderer and no wgpu-native in the Windows build; the stand-ins define what the host calls")


if __name__ == "__main__":
    main()
