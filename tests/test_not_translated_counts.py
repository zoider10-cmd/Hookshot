"""Every program the shader preparation counts as failed is counted on a line by its reason, the ones past the 30 lines too.

prepare_run's "vk: prepared N shader programs (... M failed ...)" counts st_failed, which vk_shader.cpp adds to in four places,
each with its own "not translated" line that names 30 programs, so that a log is not flooded: a network left out on purpose
(a trace line) and any other failure in translate_into's catch (not for an answer seed_compute only tries), a mesh program in
translate_mesh_into's catch, and a seed stage that does not parse (seed_stage_failed's two callers). Past 30 the rest went
uncounted: a Mac start's "70 failed" named 31 programs. shader_fail_lines, right after the preparation's line, now gives each
reason's whole count. Checked here, with the catch blocks, seed_stage_failed, the counters and shader_fail_lines cut from the
source and run against small stand-ins:
- 69 networks, 40 other failures, 2 mesh failures and 1 stage that does not parse: still 30, 30, 2 and 1 lines naming them,
  then 4 count lines, 69, 40, 2 and 1, which add up to the 112 counted, each saying where its named lines are as a reader at
  the default level sees them: the networks' "at trace level" (their lines are trace lines, hidden there), the rest "above";
- 2 answers seed_compute only tries are neither counted nor named; with no failure there is no count line;
- the counts hold with 8 threads failing at once;
- prepare_run logs the count lines right after its own, and each st_failed++ goes with exactly one of the four counts.

No Vulkan, GPU or game. python -I -B tests/test_not_translated_counts.py [--cxx clang++] [--source <tree>]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker, start=0):
    at = text.index(marker, start)
    end = text.index("{", at) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[at:end]


FIXTURE = r"""
#include <atomic>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace fx {
enum LogLevel : int { log_error, log_warn, log_info, log_debug, log_trace };
std::mutex log_mu;
std::vector<std::string> lines;
void vlog(LogLevel level, const char* fmt, va_list a) {   // (vk_main.cpp vlogf's tags)
    static const char* const tags[] = {"[error] ", "[warn] ", "", "[debug] ", "[trace] "};
    char b[1024];
    const int n = std::snprintf(b, sizeof b, "%s", tags[level]);
    std::vsnprintf(b + n, sizeof b - n, fmt, a);
    std::lock_guard<std::mutex> lk(log_mu);
    lines.push_back(b);
}
void logf(const char* fmt, ...) {
    va_list a;
    va_start(a, fmt);
    vlog(log_info, fmt, a);
    va_end(a);
}
void logf_at(LogLevel level, const char* fmt, ...) {
    va_list a;
    va_start(a, fmt);
    vlog(level, fmt, a);
    va_end(a);
}
@@NETWORK@@
@@COUNTERS@@
struct Program { uint64_t key = 0; bool failed = false; };
struct Code { int stage = -1; uint64_t key = 0; std::string why; };
struct Forced { std::map<int, int> want; };
Forced* forced = nullptr;

void translate_into(Program& p, const char* what) {
    try {
        throw std::runtime_error(what);
    } @@TRANSLATE_CATCH@@
}
void translate_mesh_into(Program& p, const char* what) {
    try {
        throw std::runtime_error(what);
    } @@MESH_CATCH@@
}
@@SEED_STAGE_FAILED@@
const Program* seed_translate(const Code& c, uint64_t key) {   // (seed_translate's and seed_compute's return)
    return seed_stage_failed(c, key), st_failed++, nullptr;
}
@@FAIL_LINES@@
}  // namespace fx

int main(int argc, char** argv) {
    using namespace fx;
    if (argc > 1 && !std::strcmp(argv[1], "none")) {   // (no failure: no count line)
        shader_fail_lines();
        for (const std::string& l : lines) std::printf("LOG %s\n", l.c_str());
        return 0;
    }
    for (uint64_t i = 0; i < 69; i++) {   // (a Mac start's networks: 30 trace lines named 30 of them)
        Program p;
        p.key = 0x1000 + i;
        translate_into(p, network_left_out);
    }
    {   // (answers seed_compute only tries: neither counted nor named)
        Forced f;
        f.want[1] = 2;
        forced = &f;
        Program a, b;
        a.key = 0xa, b.key = 0xb;
        translate_into(a, network_left_out);
        translate_into(b, "a trial");
        forced = nullptr;
    }
    std::vector<std::thread> threads;   // (the preparation's workers fail at once: 8 x 5 other failures)
    for (int t = 0; t < 8; t++)
        threads.emplace_back([t] {
            for (int i = 0; i < 5; i++) {
                Program p;
                p.key = 0x2000 + (uint64_t)(t * 5 + i);
                translate_into(p, "vkCreateShaderModule failed");
            }
        });
    for (std::thread& t : threads) t.join();
    for (uint64_t i = 0; i < 2; i++) {
        Program p;
        p.key = 0x3000 + i;
        translate_mesh_into(p, "Mesh instruction markers not found");
    }
    seed_translate(Code{5, 0x79116b290d46542full, "the branch at instruction 16404 (+0x40140) goes outside the program"},
                   0x79116b290d46542full);
    shader_fail_lines();
    for (const std::string& l : lines) std::printf("LOG %s\n", l.c_str());
    std::printf("FAILED %lld\n", (long long)st_failed.load());
    return 0;
}
"""

WANT = [
    "vk: not translated, a network left out on this card: 69 programs (the first 30 named at trace level)",
    "vk: not translated: 40 programs (the first 30 named above)",
    "vk: not translated, mesh: 2 programs (named above)",
    "vk: not translated, a seed stage that does not parse: 1 program (named above)",
]


def cut(shader, draw, fails):
    """The pieces the fixture runs, and the checks on where they sit"""
    parts = {}
    network = re.findall(r'constexpr char network_left_out\[\] = "[^"]*";', shader)
    named = re.findall(r"constexpr int64_t kFailNamed = 30;", shader)
    counts = re.findall(r"std::atomic<int64_t> st_left_out, st_not_translated, st_mesh_not_translated, st_stage_failed;", shader)
    failed = re.findall(r"std::atomic<int64_t> st_translated, st_failed, st_translate_ns;", shader)
    if len(network) != 1 or len(failed) != 1:
        fails.append("vk_shader.cpp: network_left_out or st_failed not found")
        return None
    if len(named) != 1 or len(counts) != 1:
        fails.append("vk_shader.cpp: no count of every program each \"not translated\" line stands for (kFailNamed and the "
                     "four st_ counts)")
        return None
    if "void shader_fail_lines() {" not in shader:
        fails.append("vk_shader.cpp: no shader_fail_lines, the count lines after the preparation's")
        return None
    parts["@@NETWORK@@"] = network[0]
    parts["@@COUNTERS@@"] = "\n".join([failed[0], named[0], counts[0]])
    parts["@@TRANSLATE_CATCH@@"] = block(shader, "catch (const std::exception& e) {", shader.index("void translate_into(Program& p, const NvnState& s,"))
    parts["@@MESH_CATCH@@"] = block(shader, "catch (const std::exception& e) {", shader.index("void translate_mesh_into(Program& p,"))
    parts["@@SEED_STAGE_FAILED@@"] = block(shader, "void seed_stage_failed(const Code& c, uint64_t program) {")
    parts["@@FAIL_LINES@@"] = block(shader, "void shader_fail_lines() {")
    # (each failure counted goes with one count: 4 st_failed++, each count compared with the 30 once)
    if shader.count("st_failed++") != 4:
        fails.append("vk_shader.cpp counts failures in %d places, not the 4 the count lines cover" % shader.count("st_failed++"))
    for name in ("st_left_out", "st_not_translated", "st_mesh_not_translated", "st_stage_failed"):
        if shader.count(name + "++ < kFailNamed") != 1:
            fails.append("vk_shader.cpp: %s is not the one count of its \"not translated\" line" % name)
    if len(re.findall(r"seed_stage_failed\([^;]*?\), st_failed\+\+", shader)) != 2 or shader.count("seed_stage_failed(") != 3:
        fails.append("seed_stage_failed: wanted its two callers, each counting the failure as it returns")
    run = block(draw, "bool prepare_run(")
    head = run.index('logf("vk: prepared %zu shader programs')
    after = run[run.index(";", run.index("std::chrono::steady_clock::now() - t0).count())", head)) + 1:]
    if not after.lstrip().startswith("shader_fail_lines();"):
        fails.append("prepare_run does not log the count lines right after its \"prepared\" line")
    return parts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cxx", default=os.environ.get("CXX", "clang++"))
    ap.add_argument("--source", type=Path, default=ROOT)
    a = ap.parse_args()
    vk = a.source / "gpu" / "vk"
    shader = (vk / "vk_shader.cpp").read_text(encoding="utf-8")
    draw = (vk / "vk_draw.cpp").read_text(encoding="utf-8")
    fails = []
    parts = cut(shader, draw, fails)
    if parts:
        code = FIXTURE
        for key, value in parts.items():
            code = code.replace(key, value)
        with tempfile.TemporaryDirectory(prefix="not-translated-") as tmp:
            src, exe = Path(tmp) / "fixture.cpp", Path(tmp) / ("fixture" + (".exe" if os.name == "nt" else ""))
            src.write_text(code, encoding="utf-8")
            r = subprocess.run([a.cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror"] + ([] if os.name == "nt" else ["-pthread"]) +
                               [str(src), "-o", str(exe)], capture_output=True, text=True, timeout=180)
            if r.returncode:
                print(r.stdout + r.stderr)
                fails.append("the fixture did not compile")
            else:
                got = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
                none = subprocess.run([str(exe), "none"], capture_output=True, text=True, timeout=60)
                if got.returncode or none.returncode:
                    fails.append("the fixture failed: " + got.stderr + none.stderr)
                else:
                    out = got.stdout.splitlines()
                    logs = [line[4:] for line in out if line.startswith("LOG ")]
                    failed = [int(line[7:]) for line in out if line.startswith("FAILED ")]
                    named = [line for line in logs if re.search(r"program [0-9a-f]{16} not translated: ", line)]
                    trace = [line for line in named if line.startswith("[trace] ") and "network left out" in line]
                    if failed != [112] or len(named) != 63 or len(trace) != 30:
                        fails.append("the stand-ins: wanted 112 counted and 63 named (30 of the 69 networks, 30 of the 40 others, 2 "
                                     "mesh, 1 stage): %s counted, %d named, %d networks" % (failed, len(named), len(trace)))
                    if any("program 000000000000000a " in line or "program 000000000000000b " in line for line in named):
                        fails.append("an answer seed_compute only tries was named")
                    if logs[-4:] != WANT:
                        fails.append("the count lines:\n  got  " + "\n       ".join(logs[-4:]) + "\n  want " + "\n       ".join(WANT))
                    # (each count line says where its programs are named as they are logged: at trace level for a reason whose
                    # lines are all trace lines, "above" for one whose lines are at the default level)
                    named_at = {"network": {line.startswith("[trace] ") for line in named if "network left out" in line},
                                "others": {line.startswith("[trace] ") for line in named if "network left out" not in line}}
                    if named_at != {"network": {True}, "others": {False}} or \
                            not all(("at trace level" in line) == ("network left out" in line) for line in logs[-4:]):
                        fails.append("a count line says its programs are named where they are not at the default level")
                    total = sum(int(m.group(1)) for m in (re.search(r": (\d+) programs? \(", line) for line in logs[-4:]) if m)
                    if total != 112:
                        fails.append("the count lines add up to %d, not the 112 counted" % total)
                    if none.stdout.strip():
                        fails.append("with no failure, shader_fail_lines logged: " + none.stdout.strip())
    for f in fails:
        print("FAIL: " + f)
    if fails:
        return 1
    print("PASS: each reason a program was not translated has a count line after the preparation's, the ones past its 30 named "
          "lines included, adding up to the failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
