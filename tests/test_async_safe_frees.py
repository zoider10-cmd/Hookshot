"""Frees that waited on a frame count, not on the GPU's progress, game-free. No GPU. Each is a hazard on every GPU, reached
when the GPU runs late.

- Frees counted in frames: what the reactive mask, the temporal upscalers (DLSS and FSR 4 through temporal_later) and the
  FSR 3 inputs let go (later, free_dead) waits for the timeline value that followed it (vk_retirement_value) as well as for its
  frames, and never for a value of 0: the real functions run on a clock and a timeline of the test's. With no window nothing
  waits for the present ring, and 4 frames are fewer than the 48 recordings the GPU may be behind. (The overlays' dead list
  with no window: tests/test_ui_texture_upload.py, case headless.)
- (A read-back after a timed-out one, and the textures it copies from: main's #553 and #554, with their own tests,
  tests/test_readback_timeout_reuse.py and tests/test_readback_timeout_source.py.)

    python -I -B tests/test_async_safe_frees.py --headers <Vulkan-Headers/include> [--cxx clang++] [--source <tree>]

--source <tree> reads another tree's sources (the negative control: a tree without the fixes fails each check).
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    at = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[start:at]


def compile_run(a, name, code, failures):
    with tempfile.TemporaryDirectory(prefix="async-safe-frees-") as tmp:
        cpp, exe = Path(tmp) / (name + ".cpp"), Path(tmp) / (name + ".exe")
        cpp.write_text(code, encoding="utf-8")
        r = subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                            "-Wno-missing-field-initializers", "-I" + str(a.headers), str(cpp), "-o", str(exe)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode:
            failures.append("%s: the fixture did not build: %s" % (name, (r.stdout + r.stderr).strip()[-600:]))
            return
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
        if r.returncode:
            failures.append("%s: %s" % (name, (r.stdout + r.stderr).strip()[-600:]))


PRELUDE = r'''
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan_core.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <mutex>
#include <vector>
static int failed;
static void check(bool ok, const char* what) { if (!ok) { std::printf("FAIL: %s\n", what); failed++; } }
'''

F6_LATER = r'''
// ---- the replay's frame count and timeline, as a test sets them ----
uint64_t frame_no = 0, retirement = 0, done = 0;
uint64_t texture_frame_no() { return frame_no; }
uint64_t vk_retirement_value() { return retirement; }
uint64_t vk_timeline_completed() { return done; }
/* SYSTEMS */
template <class Later, class Free> void run(const char* name, Later later, Free free_dead) {
    char what[160];
    int freed = 0;
    frame_no = 10, retirement = 20, done = 0;
    later([&] { freed++; });
    frame_no = 15, done = 19;
    free_dead();
    std::snprintf(what, sizeof what, "%s: not freed before the timeline value that followed it, 5 frames on", name);
    check(freed == 0, what);
    done = 20;
    free_dead();
    std::snprintf(what, sizeof what, "%s: freed once the timeline is past it and its frames are", name);
    check(freed == 1, what);
    frame_no = 30, retirement = 40, done = 1000;
    later([&] { freed++; });
    frame_no = 34;
    free_dead();
    std::snprintf(what, sizeof what, "%s: still not before its frames, the timeline past it", name);
    check(freed == 1, what);
    frame_no = 35;
    free_dead();
    std::snprintf(what, sizeof what, "%s: freed at its frames, the timeline past it, as before", name);
    check(freed == 2, what);
    frame_no = 50, retirement = 0;
    later([&] { freed++; });
    frame_no = 5000, done = 5000;
    free_dead();
    std::snprintf(what, sizeof what, "%s: never freed on a value of 0 (no safe value)", name);
    check(freed == 2, what);
}
int main() {
    run("reactive mask", [](std::function<void()> f) { reactive::later(std::move(f)); }, [] { reactive::free_dead(); });
    run("temporal upscalers", [](std::function<void()> f) { temporal::later(std::move(f)); }, [] { temporal::free_dead(false); });
    run("FSR 3 inputs", [](std::function<void()> f) { fsr3_inputs::later(std::move(f)); }, [] { fsr3_inputs::free_dead(); });
    return failed ? 1 : 0;
}
'''


def later_system(namespace, source, failures):
    dead = re.search(r"\n    struct Dead \{[^\n]*\};\n", source)
    if not dead:
        failures.append("%s: no Dead list" % namespace)
        return ""
    return ("namespace %s {\nstruct State {%s    std::vector<Dead> dead;\n};\nState& st() { static State s; return s; }\n%s\n%s\n}\n"
            % (namespace, dead.group(0), block(source, "void later("), block(source, "void free_dead(")))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--headers", type=Path, required=True)
    p.add_argument("--cxx", default="c++")
    p.add_argument("--source", type=Path, default=ROOT)
    a = p.parse_args()
    vk = a.source.resolve() / "gpu" / "vk"
    failures = []

    # the three later() lists, run
    systems = "".join(later_system(ns, (vk / name).read_text(encoding="utf-8"), failures)
                      for ns, name in (("reactive", "vk_reactive.cpp"), ("temporal", "vk_temporal.cpp"),
                                       ("fsr3_inputs", "vk_fsr3_inputs.cpp")))
    if systems.count("namespace ") == 3:
        compile_run(a, "f6_later", PRELUDE + F6_LATER.replace("/* SYSTEMS */", systems), failures)
    temporal = (vk / "vk_temporal.cpp").read_text(encoding="utf-8")
    if "void temporal_later(std::function<void()> f) { later(std::move(f)); }" not in temporal:
        failures.append("DLSS's and FSR 4's frees (temporal_later) do not go through the temporal list")
    # (TAAU's replaced histories wait 120 frames: with no window every frame records its offscreen copy, so 120 frames are more
    # than the 48-slot recording ring lets the GPU be behind: left as they are)

    for f in failures:
        print("FAIL " + f)
    if failures:
        raise SystemExit("FAIL: %d" % len(failures))
    print("PASS: the later lists free on the GPU's progress")


if __name__ == "__main__":
    main()
