"""Queues stopped at a wait are not made to go while a thread of the game's waits for the GPU (gpu/vk/hold_gpu.h).

The order's watch thread (gpu/vk/vk_replay.cpp sync_watch) makes queues stopped for longer than hold_ms go past their
waits: a game that polls for that work would wait for ever otherwise. But OoT's main thread waits once a frame for the GPU
to finish the frame before (nvnSyncWait, its own queue's recorded work), and makes the signal the stopped queues wait for
after that wait. When the GPU took longer than hold_ms (a load's uploads), the stopped queues were made to go and the frame
was drawn with what the game had not written yet: the lit scene and Link dark for a frame (issue 366). Now they are held on
while such a wait is under way and for hold_ms after it, up to a bound.

The rule is compiled and run (tests/hold_gpu_test.cpp). And the source: wait() counts a thread in gpu_waiters only around its
wait for its own queue's recorded work and only when its timeout is not a poll's; sync_watch reads the count, takes the
later of the queues' stop and the last such wait as the hold's start, and asks the rule before it drains.

python -I -B tests/test_hold_gpu.py [--cxx g++]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    """From marker to the brace closing its first one"""
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def need(cond, why):
    if not cond:
        raise SystemExit("FAIL: " + why)


def check_source():
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    docs = (ROOT / "docs/development.md").read_text(encoding="utf-8")
    need('#include "hold_gpu.h"' in replay, "vk_replay.cpp no longer includes hold_gpu.h")

    waiter = block(replay, "struct GpuWaiter {")
    need("if (counted) gpu_waiters.fetch_add(1" in waiter and "if (counted) gpu_waiters.fetch_sub(1" in waiter,
         "GpuWaiter must count a thread in and out, and only when told to")

    wait = block(replay, "int wait(uint64_t f, uint64_t timeout_ns) {")
    mine = block(wait, "if (mine) {")
    need("GpuWaiter waiting(timeout_ns > 1000000);" in mine, "a poll must not count as a wait for the GPU")
    need(mine.index("GpuWaiter waiting(") < mine.index("wait_recorded(f, timeout_ns, &ok)"),
         "the thread is counted for the length of its wait for its own queue's recorded work")
    need(wait.count("GpuWaiter") == 1, "only the wait for a queue's own recorded work counts: a wait that needs stopped work "
                                       "is let on by sync_drain, not held for")

    watch = block(replay, "void sync_watch() {")
    need("gpu_waiters.load(" in watch and "if (gpu_wait) gpu_wait_seen = now;" in watch, "sync_watch no longer notes a wait for the GPU")
    need("std::max(blocked_since, gpu_wait_seen)" in watch, "the hold after a wait starts at the later of the stop and the wait")
    need("hold_gpu::choose(hold_gpu_on, gpu_wait," in watch, "sync_watch no longer asks the rule")
    force = watch[watch.index("case hold_gpu::Choice::Force:"):]
    need("drain(3);" in force and watch.count("drain(3);") == 1, "the stopped queues are made to go only where the rule says so")
    need(watch.index("schedule();") < watch.index("hold_gpu::choose("), "the look at the queues comes before the hold's question")
    need('getenv("RX_VK_HOLD_GPU_WAIT")' in watch and 'getenv("RX_VK_HOLD_GPU_MS")' in watch, "the switches are read in sync_watch")
    need("(double)hold_ms()" in watch, "the bound is never under hold_ms")

    need("`RX_VK_HOLD_GPU_WAIT=0`" in docs and "`RX_VK_HOLD_GPU_MS=<ms>`" in docs, "docs/development.md has no rows for the hold's switches")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="hold-gpu-") as tmp:
        exe = Path(tmp) / "hold-gpu"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", str(ROOT / "tests/hold_gpu_test.cpp"), "-o", str(exe)],
                       check=True)
        subprocess.run([str(exe)], check=True, timeout=60)


if __name__ == "__main__":
    main()
