"""Run the production cap selection and native interval with fake options; no game or OS sleeps."""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]

def block(text, marker):
    start = text.index(marker)
    at = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[at] == "{") - (text[at] == "}")
        at += 1
    return text[start:at]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    vi = (ROOT / "host/nn_vi.c").read_text(encoding="utf-8")
    selection = vi[vi.index("enum { FPS_UNCAPPED"):]
    selection = selection[:selection.index(block(vi, "static int fps_max(void) {")) + len(block(vi, "static int fps_max(void) {"))]
    interval = block(vi, "int hos_vi_native_interval(")
    api = (ROOT / "gpu/vk/vk_api.h").read_text(encoding="utf-8")
    cap_enum = block(api, "enum { HOS_OPT_FPS_CAP") + ";"
    fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef void Ctx;
CAP_ENUM
static int chosen, env_reads, movie_reads, ini_reads, per_frame = 1;
static int64_t now = 1000000000LL;
int64_t hos_now_ns(void) { return now; }
static const char *override, *movie_override;
static char *fake_getenv(const char *name) {
    if (!strcmp(name, "HOS_FPS_MAX")) { ++env_reads; return (char *)override; }
    if (!strcmp(name, "HOS_MOVIE_PACE")) { ++movie_reads; return (char *)movie_override; }
    return NULL;
}
#define getenv fake_getenv
#define hos_log(...) ((void)0)
int hos_ini_option(const char *key, int other) { ++ini_reads; return !strcmp(key,"frame_rate_cap") ? chosen : other; }
int rx_option(int id, int other) { return id == HOS_OPT_FPS_CAP ? chosen : id == 0 ? !per_frame : other; }
SELECTION
static int present_interval;
INTERVAL
int main(int argc, char **argv) {
    assert(argc == 5);
    movie_override = strcmp(argv[4], "unset") ? argv[4] : NULL;
    chosen = atoi(argv[1]);
    override = strcmp(argv[2], "unset") ? argv[2] : NULL;
    const int expected = atoi(argv[3]);
    for (int i = 0; i < 10000; ++i) fps_refresh();
    assert(fps_max() == expected && env_reads == 1 && ini_reads == 1);
    assert(hos_vi_native_interval(NULL, 2) == 2);
    assert(present_interval == (expected == 30 ? 1 : 2));
    if (expected == 30) assert(1000000000LL / fps_max() * present_interval == 33333333LL);
    if (!override) {
        chosen = 0; fps_refresh(); assert(fps_max() == 60);
        chosen = -1; fps_refresh(); assert(fps_max() == 30);
    } else {
        chosen = 6; fps_refresh(); assert(fps_max() == expected);
    }
    /* Movies must not defeat an explicit 30 cap. The upstream 60-only assist
       still boosts to 240 and expires, with no extra environment/ini reads. */
    movie_seen_at = (uint64_t)now;
    if (!override) chosen = -1;
    fps_refresh();
    const int row = override ? expected : 30;
    assert(fps_max() == (row == 60 && !movie_override ? FPS_MOVIE : row));
    if (!override) {
        chosen = 0; fps_refresh(); assert(fps_max() == (!movie_override ? FPS_MOVIE : 60));
        chosen = -1; fps_refresh(); assert(fps_max() == 30);
        assert(hos_vi_native_interval(NULL, 2) == 2 && present_interval == 1);
        chosen = 0; now += MOVIE_STALE_NS + 1; fps_refresh(); assert(fps_max() == 60);
        chosen = -1; fps_refresh(); assert(fps_max() == 30);
    }
    assert(env_reads == 1 && ini_reads == 1 && movie_reads == (movie_override ? 2 : 1));
}
'''.replace("CAP_ENUM", cap_enum).replace("SELECTION", selection).replace("INTERVAL", interval)
    with tempfile.TemporaryDirectory(prefix="cap-30-") as tmp:
        source = Path(tmp) / "fixture.c"
        exe = Path(tmp) / "fixture.exe"
        source.write_text(fixture, encoding="utf-8")
        subprocess.run([args.cc, "-x", "c", "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(exe)], check=True)
        for cap, env, expected in [(-1,"unset",30), (0,"30",30), (6,"30",30), (-1,"60",60),
                                    (-1,"120",120), (-1,"1000",1000), (-1,"0",60), (-1,"invalid",60),
                                    (7,"unset",60), (-2,"unset",60)]:
            for movie in ("unset", "0"):
                subprocess.run([str(exe), str(cap), env, str(expected), movie], check=True)
    replay = (ROOT / "gpu/vk/vk_replay.cpp").read_text(encoding="utf-8")
    assert "next30" not in replay, "the 30 cap must not add a renderer limiter"
    assert 'opts.fps_cap == -1 && !std::getenv("HOS_FPS_MAX")' not in replay
    print("PASS: single host 30 FPS period, live changes, env precedence/read-once, Per frame interval, 60-only movie boost/expiry, explicit 30 during movies and no renderer limiter")

if __name__ == "__main__":
    main()
