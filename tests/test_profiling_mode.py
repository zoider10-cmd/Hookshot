"""The profiling mode (HOS_PROFILE=1, host/profiling.c), without the game: the packed sample format written by
hos_sample_write (cut out of profiling.c and compiled with a stub) reads back through scripts/samples.py as the plain
format's lines, and scripts/profile_report.py reads a made-up profile folder (presents, frame trace, packed samples, events,
cpu.csv, a log) into a report that names the stutter, the main thread's hot function and the long wait for a virtual core.
Then the source checks: the switch is read after hookshot_env.txt in both mains, the old HOS_RECORD_STUTTERS says what took
its place, both samplers write through hos_sample_write and start the mode, the renderer's frame trace goes into the folder
with the host's clock, and a long wait for a virtual core is an event.

python -I -B tests/test_profiling_mode.py
"""
import collections
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "scripts"))
from srccut import between, block  # noqa: E402
import samples  # noqa: E402

PLAIN = [
    "# t0_ns 1000000000",
    "0 sead::MainThread|hookshot+10;hookshot+20",
    "0 Presentation_Thread|libc.so.6+5;hookshot+30",
    "2 sead::MainThread|hookshot+10;hookshot+20",
    "2 Presentation_Thread|libc.so.6+5;hookshot+40",
    "4 sead::MainThread|hookshot+10;hookshot+20",
]

DRIVER = r'''
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
static int env_on(const char *name) { return getenv(name) != NULL; }
%s
int main(int argc, char **argv) {
    FILE *in = fopen(argv[1], "r"), *out = fopen(argv[2], "w");
    char line[1024];
    while (fgets(line, sizeof line, in)) {
        line[strcspn(line, "\n")] = 0;
        if (line[0] == '#') fprintf(out, "%%s\n", line);
        else hos_sample_write(out, line);
    }
    fclose(out);
    return 0;
}
'''


def need(ok, what):
    if not ok:
        raise SystemExit("profiling mode: " + what)


def packed_format():
    """hos_sample_write packs; samples.lines gives the plain lines back"""
    cc = os.environ.get("CC") or shutil.which("clang") or shutil.which("gcc") or shutil.which("cc")
    if not cc:
        print("profiling mode: no C compiler, the packed writer's part skipped")
        return
    src = (ROOT / "host/profiling.c").read_text(encoding="utf-8")
    # (the writer and its table: from the table's first line to the end of the file)
    writer = src[src.index(between(src, "static uint64_t *pk_keys;", "\n")):]
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "driver.c").write_text(DRIVER % writer, encoding="utf-8")
        (d / "plain.txt").write_text("\n".join(PLAIN) + "\n", encoding="utf-8")
        exe = str(d / "t")
        subprocess.run([cc, "-std=c11", "-Wall", str(d / "driver.c"), "-o", exe], check=True)
        env = dict(os.environ, HOS_SAMPLE_PACKED="1")
        subprocess.run([exe, str(d / "plain.txt"), str(d / "packed.txt")], check=True, env=env)
        packed = (d / "packed.txt").read_text(encoding="utf-8").splitlines()
        need(sum(1 for l in packed if l.startswith("s ")) == 3, "three distinct stacks are not written once each: %r" % packed)
        need("0 sead::MainThread|=1" in packed and "4 sead::MainThread|=1" in packed, "a repeated stack is not written by its id")
        back = [l.rstrip("\n") for l in samples.lines(str(d / "packed.txt"))]
        need(back == PLAIN, "the packed file does not read back as the plain one: %r" % back)
        env.pop("HOS_SAMPLE_PACKED")
        subprocess.run([exe, str(d / "plain.txt"), str(d / "same.txt")], check=True, env=env)
        need((d / "same.txt").read_text(encoding="utf-8").splitlines() == PLAIN, "without HOS_SAMPLE_PACKED the lines changed")


def report():
    """a made-up profile folder: 60 frames of 16.7 ms and one of 120 ms at the 40th"""
    with tempfile.TemporaryDirectory() as t:
        game = Path(t) / "game"
        d = game / "logs" / "profile-20261116-120000"
        d.mkdir(parents=True)
        t0 = 1_000_000_000
        at, pres, frames = t0, [], []
        for i in range(60):
            ms = 120.0 if i == 40 else 16.7
            at += int(ms * 1e6)
            pres.append("%d,%d,%d,0,0,0,0" % (i + 1, at, int(ms * 1e6) if i else 0))
            frames.append((i + 1, ms, at))
        (d / "presents.csv").write_text("frame,return_ns,interval_ns,present_begin_ns,renderer_begin_ns,renderer_end_ns,"
                                        "vcore_back_ns\n" + "\n".join(pres) + "\n", encoding="utf-8")
        cols = ["frame", "ms", "pipe_wait_ms", "translate_ms", "game_ms", "pace_ms", "main_cpu_ms", "main_blocked_ms",
                "main_vcore_ms", "at_ns"]
        rows = [",".join(cols)]
        for n, ms, a in frames:
            slow = ms > 100
            rows.append(",".join(str(x) for x in (n, ms, 90.0 if slow else 0.0, 0.0, 10.0, 6.0, 8.0, 100.0 if slow else 5.0,
                                                  0.0, a)))
        (d / "frames.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
        lines, stacks = ["# t0_ns %d" % t0], {}
        for ms in range(18, int((at - t0) / 1e6), 2):   # (from the first present, the run's 0 s)
            in_slow = frames[40][2] - 120e6 <= t0 + ms * 1e6 <= frames[40][2]
            for th, st in (("sead::MainThread", "libc.so.6+5;hookshot+99" if in_slow else "hookshot+10;hookshot+20"),
                           ("ARes_Loading_0", "hookshot+77" if in_slow else "libc.so.6+5;hookshot+99")):
                if st not in stacks:
                    stacks[st] = len(stacks) + 1
                    lines.append("s %d %s" % (stacks[st], st))
                lines.append("%d %s|=%d" % (ms, th, stacks[st]))
        (d / "all.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        wait_end = frames[40][2] - 10_000_000
        (d / "events.txt").write_text("%d vcore_wait 80.0 ms from %d: ARes_Loading_0 (priority 26) waited for a core: given by "
                                      "sead::MainThread\n" % (wait_end, wait_end - 80_000_000), encoding="utf-8")
        (d / "cpu.csv").write_text("t_ns,process_cpu_ns,rss_mb,available_mb\n%d,0,1000,8000\n%d,%d,1100,7900\n" %
                                   (t0, at, (at - t0) * 2), encoding="utf-8")
        (d / "process.json").write_text(json.dumps({"env": {"HOS_PROFILE": "1", "HOS_SAMPLE_ALL": str(d / "all.txt")}}),
                                        encoding="utf-8")
        (d / "game.log").write_text("[hos host] prof: threads in 5 s: sead::MainThread 60%; ARes_Loading_0 12%;\n",
                                    encoding="utf-8")
        out = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "scripts/profile_report.py"), str(d), "--maps", str(t)],
                             capture_output=True, text=True, encoding="utf-8")
        need(out.returncode == 0, "profile_report.py failed:\n" + out.stdout + out.stderr)
        rep = (d / "report.md").read_text(encoding="utf-8")
        need("**Frames:** 60 in" in rep or "**Frames:** 59 in" in rep, "the frame count is not in the report")
        need("1 frames of 50 ms or more" in rep, "the stutter is not counted")
        need("### 120.0 ms at" in rep, "the stutter is not listed")
        need("pipe_wait_ms 90.0" in rep, "the stutter's trace columns are not named")
        need("ARes_LoadingN running 100 %" in rep, "what ran in the stutter is not named")
        need("**Virtual core:** 80.0 ms wait" in rep, "the long wait for a virtual core is not put in its stutter")
        need("`hookshot+10`" in rep or "`hookshot+20`" in rep, "the main thread's hot code is not listed")
        need(str(d) not in rep and t not in rep, "the report names this PC's folders")
        load = json.loads((d / "load.json").read_text(encoding="utf-8"))
        need(abs(load["window_cores"] - 2.0) < 0.01, "load.json's cores are not cpu.csv's: %r" % load)
        need("**Browse it:**" in rep, "the report does not point to the trace and the flame graphs")
        with gzip.open(d / "trace.json.gz", "rt", encoding="utf-8") as f:
            trace = json.load(f)["traceEvents"]
        need(any(e.get("name") == "STUTTER 120 ms" and e["ph"] == "X" for e in trace), "the trace has no slice for the stutter")
        need(any(e.get("ph") == "M" and e["args"].get("name") == "ARes_Loading_0" for e in trace), "the trace has no track for a thread")
        need(any(e.get("name") == "ARes_Loading_0 waited 80.0 ms" for e in trace), "the trace has no slice for the virtual-core wait")
        depth = collections.Counter()
        for e in trace:   # (every slice a sample opened is closed, on its own thread)
            if e["ph"] in "BE":
                depth[e["tid"]] += 1 if e["ph"] == "B" else -1
                need(depth[e["tid"]] >= 0, "a slice ends that was not open")
        need(not any(depth.values()), "slices are left open at the end of the trace")
        scope = json.loads((d / "speedscope.json").read_text(encoding="utf-8"))
        names = [pr["name"] for pr in scope["profiles"]]
        need("every thread, running" in names and "sead::MainThread" in names, "speedscope.json lacks its profiles: %r" % names)
        frames = [f["name"] for f in scope["shared"]["frames"]]
        main = scope["profiles"][names.index("sead::MainThread")]
        need(abs(sum(main["weights"]) - 2.0 * len([l for l in lines if l.split("|")[0].endswith("sead::MainThread")])) < 0.01,
             "speedscope's weights are not the samples at 2 ms each")
        need("hookshot+10" in frames, "speedscope.json does not name the main thread's frames")


def sources():
    main = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    need(main.count("    load_hookshot_env();\n    hos_profiling_env();") == 2, "HOS_PROFILE=1 is not read after hookshot_env.txt "
         "in both mains")
    need('{"HOS_RECORD_STUTTERS", "HOS_PROFILE=1' in main, "HOS_RECORD_STUTTERS does not name what took its place")
    need("record_stutters_env" not in main, "HOS_RECORD_STUTTERS is still read")
    prof = (ROOT / "host/profiling.c").read_text(encoding="utf-8")
    env = block(prof, "void hos_profiling_env(void)")
    need('env_on("HOS_PROFILE")' in env and 'set_default("HOS_SAMPLE_ALL", path);' in env, "the mode does not sample")
    for name in ("HOS_SAMPLE_PACKED", "HOS_PRESENT_TRACE", "RX_VK_FRAME_TRACE", "HOS_PROFILE_EVERY", "HOS_THREAD_TIMES",
                 "RX_VK_PASS_TIMING"):
        need('set_default("%s"' % name in env, "the mode does not set " + name)
    need("if (getenv(name)) return;" in block(prof, "static void set_default(const char *name, const char *value)"),
         "the mode replaces a switch already set")
    for path in ("host/posix/prof.c", "host/mkw_glue.c"):
        src = (ROOT / path).read_text(encoding="utf-8")
        need("hos_profiling_start();" in block(src, "void hos_prof_start(void)"), path + ": the mode's thread is not started")
        need("else hos_sample_write(out, line);" in block(src, "static DWORD WINAPI sample_all_thread(void *p)"),
             path + ": the sampler does not write through hos_sample_write")
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    need('getenv("HOS_PROFILE_DIR")' in replay and "host->now_ns ? host->now_ns() : 0" in replay,
         "the frame trace is not in the folder, or not on the host's clock")
    threads = (ROOT / "host/hos_thread.c").read_text(encoding="utf-8")
    need('hos_profiling_event("vcore_wait' in block(threads, "static void vc_long_wait(HosThread *t, int64_t waited, int how, unsigned m)"),
         "a long wait for a virtual core is not an event")
    for script in ("crit.py", "hotlist.py", "vkprof.py", "chain.py", "cpu_report.py"):
        need("samples.lines(" in (ROOT / "scripts" / script).read_text(encoding="utf-8"), script + " does not read packed samples")


if __name__ == "__main__":
    sources()
    packed_format()
    report()
    print("profiling mode: ok")
