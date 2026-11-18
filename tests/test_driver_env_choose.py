"""RADV_FORCE_VRS_CONFIG_FILE is dropped before Vulkan loads (host/hos_main.c driver_env_choose).

The Steam Deck's Game Mode sets RADV_FORCE_VRS_CONFIG_FILE for Steam and everything it starts, naming a file Steam writes the
Half Rate Shading rate to. With the file there, RADV gives every graphics pipeline another key: on a Steam Deck OLED the same
install compiled its 32,438 noted pipelines at about 20 a second (25-30 minutes) with it, and loaded them in 22 s without it or
with it naming no file. The preparation runs without it, so every start from Game Mode compiled again what it built. This cuts
driver_env_choose out of hos_main.c and runs it:
 - the variable naming a file that exists is dropped, named in HOOKSHOT_DRIVER_ENV_SET, and said for the game's log;
 - RX_VK_HALF_RATE_SHADING=1 keeps it (and says so); 0 or unset drops it;
 - a name with no file there, an empty value, or no variable: nothing changes, nothing is said;
 - RADV_FORCE_VRS (a rate set by hand) and Mesa's cache variables are never touched;
and checks it runs after hookshot_env.txt is read and before the window (SDL) may load Vulkan, that game_main says it again
once its log is open, and docs/development.md's row.
python -I -B tests/test_driver_env_choose.py [--cxx c++]
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
RUN_ALL_SKIP = {"windows": "the Linux main's code (stat, setenv, unsetenv)"}

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <sys/stat.h>
static char driver_env_said[1024];
%s
int main() {
    driver_env_choose();
    for (const char *name : {"RADV_FORCE_VRS_CONFIG_FILE", "RADV_FORCE_VRS", "MESA_SHADER_CACHE_DIR", "HOOKSHOT_DRIVER_ENV_SET"}) {
        const char *v = getenv(name);
        printf("%%s=%%s\n", name, v ? v : "(unset)");
    }
    printf("SAID=%%s\n", driver_env_said);
    return 0;
}
"""


def function(source, signature):
    start = source.index(signature)
    first = source.index("{", start)
    depth, at = 1, first + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(source[at], 0)
        at += 1
    return source[start:at]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default=os.environ.get("CXX", "c++"))
    args = parser.parse_args()
    cxx = shutil.which(args.cxx)
    if not cxx:
        raise SystemExit("C++ compiler not found: " + args.cxx)
    src = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    if "static void driver_env_choose(void) {" not in src:
        raise SystemExit("FAIL: host/hos_main.c has no driver_env_choose: Game Mode's RADV_FORCE_VRS_CONFIG_FILE reaches RADV")
    problems = []
    main_fn = src[src.rindex("int main(int argc, char **argv) {"):]
    if "driver_env_choose();" not in main_fn:
        problems.append("the Linux main does not call driver_env_choose")
    elif not (main_fn.index("load_hookshot_env();") < main_fn.index("driver_env_choose();") < main_fn.index("hos_display_init()")):
        problems.append("driver_env_choose runs before hookshot_env.txt is read or after the window may have loaded Vulkan")
    game = function(src, "static int game_main(int argc, char **argv) {")
    if "driver_env_log();" not in game or game.index("driver_env_log();") < game.index("freopen(path"):
        problems.append("game_main does not say what driver_env_choose did once its log is open")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    if "`RX_VK_HALF_RATE_SHADING=1`" not in docs:
        problems.append("docs/development.md does not name RX_VK_HALF_RATE_SHADING=1")
    with tempfile.TemporaryDirectory(prefix="hookshot-driver-env-") as folder:
        tmp = Path(folder)
        (tmp / "t.cpp").write_text(HARNESS % function(src, "static void driver_env_choose(void) {"), encoding="utf-8")
        r = subprocess.run([cxx, "-std=c++17", "-O0", "-Wall", "-Wextra", "-Werror", str(tmp / "t.cpp"), "-o", str(tmp / "t")],
                           capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise SystemExit("FAIL: driver_env_choose does not compile\n" + r.stdout + r.stderr)

        def run(env):
            out = subprocess.run([str(tmp / "t")], env=env, capture_output=True, text=True, timeout=30)
            if out.returncode:
                raise SystemExit("FAIL: the harness ended with %d\n%s" % (out.returncode, out.stderr))
            return dict(line.split("=", 1) for line in out.stdout.splitlines()), out.stderr

        vrs = tmp / "radv_vrs.HZwZkLhg"
        vrs.write_text("1x1", encoding="utf-8")
        empty = tmp / "radv_vrs.empty"
        empty.write_text("", encoding="utf-8")
        base = {k: v for k, v in os.environ.items()
                if not k.startswith(("RADV_", "MESA_", "RX_VK_HALF_RATE_SHADING", "HOOKSHOT_DRIVER_ENV_SET"))}
        game_mode = dict(base, RADV_FORCE_VRS_CONFIG_FILE=str(vrs), MESA_SHADER_CACHE_DIR="/steam/shadercache/1")
        for name, env in (("Game Mode's file", game_mode), ("=0", dict(game_mode, RX_VK_HALF_RATE_SHADING="0")),
                          ("an empty file", dict(game_mode, RADV_FORCE_VRS_CONFIG_FILE=str(empty)))):
            got, err = run(env)
            if got["RADV_FORCE_VRS_CONFIG_FILE"] != "(unset)":
                problems.append("%s: RADV_FORCE_VRS_CONFIG_FILE kept: %r" % (name, got))
            if got["HOOKSHOT_DRIVER_ENV_SET"] != "RADV_FORCE_VRS_CONFIG_FILE":
                problems.append("%s: not named in HOOKSHOT_DRIVER_ENV_SET: %r" % (name, got))
            if "dropped" not in got["SAID"] or "RX_VK_HALF_RATE_SHADING=1" not in got["SAID"] or "dropped" not in err:
                problems.append("%s: the log line does not say it was dropped and how to keep it: %r" % (name, got["SAID"]))
            if got["MESA_SHADER_CACHE_DIR"] != "/steam/shadercache/1":
                problems.append("%s: Mesa's cache folder touched: %r" % (name, got))
        got, err = run(dict(game_mode, RX_VK_HALF_RATE_SHADING="1"))
        if got["RADV_FORCE_VRS_CONFIG_FILE"] != str(vrs) or got["HOOKSHOT_DRIVER_ENV_SET"] != "(unset)":
            problems.append("RX_VK_HALF_RATE_SHADING=1 does not keep it: %r" % got)
        if "kept" not in got["SAID"]:
            problems.append("RX_VK_HALF_RATE_SHADING=1: the log does not say it was kept")
        for name, env in (("a name with no file", dict(base, RADV_FORCE_VRS_CONFIG_FILE=str(tmp / "gone"))),
                          ("an empty value", dict(base, RADV_FORCE_VRS_CONFIG_FILE="")), ("no variable", base)):
            got, err = run(env)
            want = env.get("RADV_FORCE_VRS_CONFIG_FILE", "(unset)")
            if got["RADV_FORCE_VRS_CONFIG_FILE"] != want or got["HOOKSHOT_DRIVER_ENV_SET"] != "(unset)" or got["SAID"] or err:
                problems.append("%s: changed or said something (RADV reads no file then): %r" % (name, got))
        got, _ = run(dict(game_mode, RADV_FORCE_VRS="2x2"))
        if got["RADV_FORCE_VRS"] != "2x2":
            problems.append("RADV_FORCE_VRS, a rate set by hand, was touched: %r" % got)
    if problems:
        raise SystemExit("FAIL:\n  " + "\n  ".join(problems))
    print("PASS: Game Mode's RADV_FORCE_VRS_CONFIG_FILE is dropped before Vulkan loads, kept with RX_VK_HALF_RATE_SHADING=1, "
          "and the game's log says which")


if __name__ == "__main__":
    main()
