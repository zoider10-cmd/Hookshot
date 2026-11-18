"""Compile and run the GPU clock's rules (gpu/vk/gpu_clock.h; no game/GPU), and check that the renderer still uses them: the
device's render node and power level read, the state asked through an amdgpu context of its own, once the device is made, and
the Steam Deck told apart as the Quality preset Auto (this PC) tells it. The rules are built twice: with the system's
<drm/amdgpu_drm.h>, and with a copy of it that has no stable power states, as before Linux 5.18.

python -I -B tests/test_gpu_clock.py [--cxx g++]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "g++"]

ROOT = Path(__file__).resolve().parents[1]


def need(where, text, needles):
    for needle in needles:
        if needle not in text:
            raise SystemExit(where + " no longer has: " + needle)


def body(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def check_source():
    main = (ROOT / "gpu/vk/vk_main.cpp").read_text(encoding="utf-8")
    create = body(main, "bool create_device() {")
    call = "gpu_clock_device_created(has_extension(exts, VK_EXT_PHYSICAL_DEVICE_DRM_EXTENSION_NAME));"
    need("create_device", create, [call])
    if not create.index("vkCreateDevice(") < create.index(call):
        raise SystemExit("create_device: the GPU clock is asked for before the device is made")
    # (the Deck as auto_profile tells it: the same names, the same flag)
    profile = body(main, "void auto_profile() {")
    need("auto_profile", profile, ['"Custom GPU 0405"', '"Custom GPU 0932"', 'getenv("SteamDeck")'])
    rules = (ROOT / "gpu/vk/gpu_clock.h").read_text(encoding="utf-8")
    need("gpu_clock.h", rules, ['"Custom GPU 0405"', '"Custom GPU 0932"'])

    clock = (ROOT / "gpu/vk/vk_gpu_clock.cpp").read_text(encoding="utf-8")
    held = body(clock, "void gpu_clock_device_created(bool drm) {")
    need("vk_gpu_clock.cpp", clock, ["static_assert(sizeof(Ctx) == 16", "kOpAllocCtx = 1;", "kOpSetStablePstate = 6;",
                                     "_IOWR('d', 0x40 + 0x02, Ctx)", "O_RDWR | O_CLOEXEC"])
    need("gpu_clock_device_created", held, ["VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRM_PROPERTIES_EXT", "power_dpm_force_performance_level",
                                            'getenv("RX_VK_GPU_CLOCK")', 'getenv("SteamDeck")', "makedev("])
    # (the level read before the choice: a level someone chose stays theirs)
    if not held.index("f.level = read_line(") < held.index("gpu_clock::choose(f)"):
        raise SystemExit("gpu_clock_device_created: the power level must be read before the choice")
    # (held: after the state is set, nothing closes the file; the driver puts the level back at the process's end)
    after = held[held.index("a.in.op = kOpSetStablePstate"):]
    after = after[after.index("!= 0) {"):]
    after = after[after.index("}") + 1:]
    if "close(fd)" in after:
        raise SystemExit("gpu_clock_device_created: the render node's file must stay open once the state is held")
    # (on by default on the Steam Deck only: elsewhere nothing is opened or read unless RX_VK_GPU_CLOCK asks for it)
    if not held.index("gpu_clock::looked_at(f)") < held.index("vkGetPhysicalDeviceProperties2("):
        raise SystemExit("gpu_clock_device_created: off the Deck and unset, it must return before anything is asked or read")
    if not held.index("f.deck_apu = gpu_clock::deck_apu(p.deviceName);") < held.index("gpu_clock::looked_at(f)"):
        raise SystemExit("gpu_clock_device_created: the Deck's APU must be known before the default is chosen")
    need("gpu_clock_device_created", held, ["VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU"])
    need("auto_profile", profile, ["hw.integrated"])
    need("docs/development.md", (ROOT / "docs/development.md").read_text(encoding="utf-8"), ["`RX_VK_GPU_CLOCK=1`"])


STABLE_PSTATE_DEFINE = re.compile(r"^#define\s+AMDGPU_CTX_(?:OP_(?:GET|SET)_STABLE_PSTATE|STABLE_PSTATE_\w+)\b.*$",
                                  re.MULTILINE)


def system_drm_dir(cxx):
    """The folder of the <drm/amdgpu_drm.h> the compiler finds, or None"""
    found = subprocess.run([cxx, "-std=c++20", "-x", "c++", "-M", "-"], input="#include <drm/amdgpu_drm.h>\n",
                           capture_output=True, text=True)
    if found.returncode:
        return None
    for path in found.stdout.replace("\\\n", " ").split():
        if path.endswith("/drm/amdgpu_drm.h"):
            return Path(path).parent
    return None


def old_header(drm_dir, into):
    """A copy of the system's drm headers without the stable power states, as an amdgpu_drm.h from before Linux 5.18
    (Ubuntu 22.04's linux-libc-dev 5.15) has them: the folder to put first on the include path"""
    old = into / "old-drm-headers"
    (old / "drm").mkdir(parents=True)
    for header in drm_dir.glob("*.h"):
        text = header.read_text(encoding="utf-8")
        if header.name == "amdgpu_drm.h":
            text = STABLE_PSTATE_DEFINE.sub("", text)
            if "STABLE_PSTATE_PEAK" in text or "OP_SET_STABLE_PSTATE" in text:
                raise SystemExit("test_gpu_clock.py: the stable power states were not taken out of the old header's copy")
        (old / "drm" / header.name).write_text(text, encoding="utf-8")
    return old


def build_and_run(cxx, exe, extra=()):
    subprocess.run([cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", *extra,
                    str(ROOT / "tests/test_gpu_clock.cpp"), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="gpu-clock-") as tmp:
        build_and_run(args.cxx, Path(tmp) / "gpu-clock")
        # (the same with an amdgpu_drm.h from before the stable power states: the check must still build there)
        drm_dir = system_drm_dir(args.cxx)
        if drm_dir is None:
            print("gpu clock: no <drm/amdgpu_drm.h> here, so no older one to make from it")
            return
        old = old_header(drm_dir, Path(tmp))
        build_and_run(args.cxx, Path(tmp) / "gpu-clock-old-header", ["-isystem", str(old)])


if __name__ == "__main__":
    main()
