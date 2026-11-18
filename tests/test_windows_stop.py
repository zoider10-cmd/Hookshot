"""Drive Windows stop callbacks and their watchdog without Windows, a game or a GPU.

The production unit is compiled against Win32 stand-ins, not a reimplemented policy.
--compile-only is for Windows-target cross compilation; it never runs that executable.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--stop-source", type=Path)
    parser.add_argument("--control-source", type=Path)
    parser.add_argument("--compile-only", action="store_true")
    args = parser.parse_args()
    source = (args.stop_source or args.source / "host/windows_stop.c").read_text(encoding="utf-8")
    source = source.replace("#ifdef _WIN32\n#include <windows.h>", "").removesuffix("#endif\n")
    fixture = (ROOT / "tests/windows_stop_test.c").read_text(encoding="utf-8")
    fixture = fixture.replace("/* ACTUAL_WINDOWS_STOP */", source)
    control = (args.control_source or args.source / "host/control.c").read_text(encoding="utf-8")
    relaunch = (args.source / "host/hos_relaunch.c").read_text(encoding="utf-8")
    chain = r'''
#define _CRT_SECURE_NO_WARNINGS
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
static int relaunch_asked, order, exited, restarted, window_logs, clean_ends;
static void rx_close_asked(void) { assert(order == 0); order = 1; }
static void hos_log(const char *fmt, ...) {
    if (strstr(fmt, "close work done")) { assert(order == 1); order = 2; }
    if (strstr(fmt, "display: window closed")) window_logs++;
}
static void hos_log_flush(void) { assert(order == 2); order = 3; }
void hos_crash_clean_end(void) { assert(order == 3); order = 4; clean_ends++; }
static void relaunch(void) { assert(order == 4); restarted++; }
static void ExitProcess(unsigned code) { assert(order == 4 && code == 0); exited++; }
/* ACTUAL_FINISH */
/* ACTUAL_CLOSE */
/* ACTUAL_QUIT */
int main(void) {
    order = 1;
    hos_close_finish();
    assert(order == 4 && clean_ends == 1 && exited == 0 && restarted == 0);   /* returning after flush and clean-end */
    order = 0; relaunch_asked = 1;
    game_quit();
    assert(exited == 1 && restarted == 0 && window_logs == 0 && clean_ends == 2);
    puts("PASS: control quit flushes the shared tail, ignores pending restart and does not claim a window closed");
    order = 1; exited = 0;
    hos_window_closed_exit();
    assert(exited == 1 && restarted == 1 && window_logs == 1 && clean_ends == 3);
    order = 1; exited = restarted = window_logs = 0; relaunch_asked = 0;
    hos_window_closed_exit();
    assert(exited == 1 && restarted == 0 && window_logs == 1 && clean_ends == 4);
    puts("PASS: window close still flushes before its optional relaunch and ExitProcess");
}
'''
    chain = chain.replace("/* ACTUAL_FINISH */", function(relaunch, "void hos_close_finish(void)"))
    chain = chain.replace("/* ACTUAL_CLOSE */", function(relaunch, "void hos_window_closed_exit(void)"))
    chain = chain.replace("/* ACTUAL_QUIT */", function(control, "static void game_quit(void)"))
    with tempfile.TemporaryDirectory(prefix="windows-stop-") as temp:
        for name, text in (("events", fixture), ("close-chain", chain)):
            path = Path(temp) / (name + ".c")
            exe = Path(temp) / (name + ".exe")
            path.write_text(text, encoding="utf-8")
            subprocess.run([args.cc, "-std=c11", "-O0", "-Wall", "-Wextra", "-Werror", str(path), "-o", str(exe)],
                           check=True)
            if args.compile_only:
                print("PASS: compiled and linked " + name + " (not executed)")
            else:
                subprocess.run([str(exe)], check=True, timeout=10)


if __name__ == "__main__":
    main()
