"""The dead transient render targets are looked for at every present, not only at the eviction's pass every tenth.

RX_VK_DEAD_EVERY has defaulted to 1 ("every present") since the target pool's bound grew, but the code that read it sat behind
texture_frame's `if (frame_no % 10) return;` and so ran at every tenth present: a frame's dead targets waited up to nine more
presents and came back to the pool ten frames' worth at once. gpu/vk/dead_targets.h now says when the pass runs and when the
sweep between the passes does; this compiles it (and target_pool.h's idle rule) with a small fixture and checks the presents
each runs at, then reads vk_texture.cpp for the wiring: the gate calls the sweep before it returns, and the sweep lets go only
what the pass's own rule would (drawn over from another start, unused long enough, the GPU done), writing nothing back.

python -I -B tests/test_dead_targets_sweep.py [--cxx clang++]
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
from srccut import block   # noqa: E402

RUN_ALL_ARGS = ["--cxx", "clang++"]

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''#include <cstdio>
#include "dead_targets.h"
#include "target_pool.h"
using namespace mkwvk;
static int fails;
#define CHECK(name, cond) do { if (!(cond)) { std::printf("FAIL: %s (line %d)\n", name, __LINE__); fails++; } } while (0)
int main() {
    CHECK("the pass runs at every tenth present", dead_targets::pass_due(10) && dead_targets::pass_due(20) && dead_targets::pass_due(600));
    for (unsigned long long f = 1; f < 10; f++) CHECK("and at none between", !dead_targets::pass_due(f) && !dead_targets::pass_due(10 + f));

    // (every present: the sweep at the nine presents between two passes, never at a pass's own)
    int looked = 0, both = 0;
    for (unsigned long long f = 1; f <= 100; f++) {
        const bool pass = dead_targets::pass_due(f), sweep = dead_targets::sweep_due(f, 1, true);
        looked += pass || sweep, both += pass && sweep;
    }
    CHECK("at RX_VK_DEAD_EVERY=1 the dead targets are looked for at every present", looked == 100);
    CHECK("never by both at one present", both == 0);

    // (RX_VK_DEAD_EVERY=10: the pass alone, as it was in effect before)
    looked = 0;
    for (unsigned long long f = 1; f <= 100; f++) looked += dead_targets::sweep_due(f, 10, true);
    CHECK("at RX_VK_DEAD_EVERY=10 the sweep never runs", looked == 0);

    // (every second present: 2, 4, 6, 8 of each ten)
    looked = 0;
    for (unsigned long long f = 1; f <= 100; f++) looked += dead_targets::sweep_due(f, 2, true);
    CHECK("at RX_VK_DEAD_EVERY=2 the sweep runs at the even presents between", looked == 40);
    CHECK("0 is taken as 1", dead_targets::sweep_due(3, 0, true));

    // (off: RX_VK_DEAD_TARGETS=0 or RX_VK_NO_EVICT)
    looked = 0;
    for (unsigned long long f = 1; f <= 100; f++) looked += dead_targets::sweep_due(f, 1, false);
    CHECK("off, the sweep never runs", looked == 0);

    // (a candidate: unused long enough, the GPU past its last use, one level and layer)
    CHECK("unused for a present and the GPU done", dead_targets::candidate(12, 10, 1, 500, 500, true));
    CHECK("not while the GPU may still use it", !dead_targets::candidate(12, 10, 1, 501, 500, true));
    CHECK("not one of several levels or layers", !dead_targets::candidate(12, 10, 1, 500, 500, false));
    CHECK("RX_VK_DEAD_MIN_UNUSED=3 keeps one unused for two", !dead_targets::candidate(12, 10, 3, 500, 500, true));
    CHECK("and lets one unused for three go", dead_targets::candidate(13, 10, 3, 500, 500, true));

    // (the pool's idle time)
    CHECK("a pooled image waits 8 presents by default", target_pool::kIdlePresents == 8);
    CHECK("eight presents in the pool: kept", !target_pool::idle_out(108, 100, target_pool::kIdlePresents));
    CHECK("nine: given back", target_pool::idle_out(109, 100, target_pool::kIdlePresents));
    CHECK("RX_VK_POOL_IDLE=120 keeps it for 120", !target_pool::idle_out(220, 100, 120) && target_pool::idle_out(221, 100, 120));

    if (!fails) std::puts("PASS: the dead targets are looked for at every present; the pool's idle images go after 8");
    return fails ? 1 : 0;
}
'''


def wiring():
    tex = (ROOT / "gpu" / "vk" / "vk_texture.cpp").read_text(encoding="utf-8")
    fails = []

    def need(cond, what):
        if not cond:
            fails.append(what)

    frame = block(tex, "void texture_frame(uint64_t completed)")
    need("if (frame_no % 10) return;" not in frame, "texture_frame still returns at nine presents of ten before the dead targets")
    gate = frame.find("if (!dead_targets::pass_due(frame_no)) {")
    need(gate >= 0, "texture_frame's gate is dead_targets::pass_due")
    if gate >= 0:
        body = frame[gate:frame.index("return;", gate)]
        need("dead_targets::sweep_due(frame_no, dead_every_presents()," in body, "the gate asks sweep_due with RX_VK_DEAD_EVERY")
        need("dead_targets_sweep(completed);" in body, "the gate calls the sweep before it returns")
        need('env_on("RX_VK_NO_EVICT")' in body and "dead_targets_on()" in body, "the sweep is off with RX_VK_NO_EVICT or RX_VK_DEAD_TARGETS=0")
        need(frame.index("pool_trim();") < gate, "the pool is trimmed before the gate, every present")
    sweep = block(tex, "void dead_targets_sweep(uint64_t completed)")
    for part in ("dead_min_unused_presents()", "dead_targets::candidate(frame_no, tex->last_frame, need, tex->last_value, completed,",
                 "tex->levels == 1 && tex->layers == 1 && tex->depth <= 1", "target_overlap::shifted_over(lo, hi, tex->last_frame,",
                 "(*it)->last_written", "destroy_later(*tex);", "forget_gpu(tex);", "remade.erase(tex);", "textures.erase(it)"):
        need(part in sweep, "the sweep: " + part)
    for part in ("flush_textures", "flush_texture(", "readback"):
        need(part not in sweep, "the sweep writes nothing back (%s)" % part)
    every = block(tex, "uint64_t dead_every_presents()")
    need('getenv("RX_VK_DEAD_EVERY")' in every and ": 1;" in every, "RX_VK_DEAD_EVERY defaults to 1")
    trim = block(tex, "size_t pool_trim()")
    need('getenv("RX_VK_POOL_IDLE")' in trim and "target_pool::kIdlePresents" in trim, "RX_VK_POOL_IDLE defaults to target_pool.h's")
    need("!target_pool::idle_out(frame_no, v[i].since, idle)" in trim, "the trim uses target_pool::idle_out")
    return fails


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="clang++", help="C++ compiler")
    a = p.parse_args()
    fails = wiring()
    for f in fails:
        print("FAIL: " + f)
    if fails:
        raise SystemExit("test_dead_targets_sweep: failed")
    print("PASS: texture_frame runs the dead targets' sweep on the presents between its passes")
    cxx = shutil.which(a.cxx)
    if not cxx:
        raise SystemExit("test_dead_targets_sweep: no C++ compiler %r (pass --cxx)" % a.cxx)
    with tempfile.TemporaryDirectory(prefix="dead-targets-") as temp:
        d = Path(temp)
        src, exe = d / "fixture.cpp", d / "fixture.exe"
        src.write_text(FIXTURE, encoding="utf-8")
        subprocess.run([cxx, "-std=c++17", "-O2", "-I", str(ROOT / "gpu" / "vk"), str(src), "-o", str(exe)], check=True)
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        print(result.stdout, end="")
        if result.returncode:
            raise SystemExit("test_dead_targets_sweep: failed")


if __name__ == "__main__":
    main()
