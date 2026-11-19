"""The saved logs without the player's user name (host/log_redact.c, gpu/vk/compat/hookshot_redact.h, nx2/log_redact.py).

- the shared rule: the home folder as a whole is ~ (%USERPROFILE% on Windows), the user's name as a folder of any path <user>,
  and the rest of each path stays: names with spaces, an apostrophe, letters outside ASCII; another drive's Users folder;
  OneDrive under the home folder; Linux's /home, /media, /run/media and /var/home; a name that is also a word of the line
  is left alone; redacting again changes nothing;
- the game's own line (hos_log_redact): this PC's home folder and name, read from the environment, and on Windows the name
  of the home folder itself when it is not USERNAME (and its short 8.3 name, where the drive makes them);
- a log file once its run has ended (hos_log_redact_file): rewritten in place, only when it is the run named, left alone
  when already clean, longer and shorter lines both;
- the builder's --log file (nx2/log_redact.py): the same output as the C rule for the same line, whole lines only, a line
  cut across writes redacted whole, and make_game.py's build_log writing through it;
- the Insert menu's Bug report: the same output, line for line;
- the places that call it (source checks): hos_vlog and hos_fatal, the start's rotation, the crash watch, the crash window and
  the Bug report sharing the one implementation.
"""
import argparse
import importlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ["--cc", "clang", "--cxx", "{cxx}"]   # (tests/run_all.py: skipped where there is no clang)
sys.path.insert(0, str(ROOT / "nx2"))
log_redact = importlib.import_module("log_redact")

HARNESS = r"""
#include "log_redact.h"
#include "../gpu/vk/compat/hookshot_redact.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
static void unhex(char *out, const char *hex) {
    size_t o = 0;
    for (; hex[0] && hex[1] && o < 1023; hex += 2) {
        unsigned v = 0;
        sscanf(hex, "%2x", &v);
        out[o++] = (char)v;
    }
    out[o] = 0;
}
static char *slurp(FILE *f, size_t *n) {
    size_t cap = 1 << 16, at = 0;
    char *s = (char *)malloc(cap);
    for (size_t k; s && (k = fread(s + at, 1, cap - at, f)) > 0;) {
        at += k;
        if (at == cap) s = (char *)realloc(s, cap *= 2);
    }
    if (s) s[at] = 0;
    *n = at;
    return s;
}
int main(int argc, char **argv) {
    if (argc < 2) return 2;
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY), _setmode(_fileno(stdout), _O_BINARY);
#endif
    if (!strcmp(argv[1], "core") && argc == 5) {   /* home user windows (home and user in hex: UTF-8 whatever the code page), the lines on stdin */
        char home[1024], user[1024];
        unhex(home, argv[2]), unhex(user, argv[3]);
        size_t n;
        char *text = slurp(stdin, &n), *out = (char *)malloc(n * 7 + 1);
        for (size_t i = 0; i < n;) {
            const char *nl = (const char *)memchr(text + i, '\n', n - i);
            const size_t len = nl ? (size_t)(nl - (text + i)) + 1 : n - i;
            const size_t got = hookshot_redact_line(out, n * 7 + 1, text + i, len, home, user, atoi(argv[4]));
            fwrite(out, 1, got, stdout);
            i += len;
        }
        return 0;
    }
    if (!strcmp(argv[1], "line")) {   /* the lines on stdin, this PC's home folder and name */
        char line[4096], out[8192];
        while (fgets(line, sizeof line, stdin)) {
            hos_log_redact(out, sizeof out, line);
            fputs(out, stdout);
        }
        return 0;
    }
    if (!strcmp(argv[1], "file") && argc >= 3) {   /* path [run_id] */
        printf("%d\n", hos_log_redact_file(argv[2], argc > 3 ? argv[3] : NULL));
        return 0;
    }
    return 2;
}
"""

MENU = r"""
#include "vk_bug_report.h"
#include <cstdio>
#include <cstdlib>
#include <string>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
static std::string unhex(const char* h) {
    std::string s;
    for (; h[0] && h[1]; h += 2) s += (char)std::strtoul(std::string(h, 2).c_str(), nullptr, 16);
    return s;
}
int main(int argc, char** argv) {
    if (argc != 4) return 2;
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY), _setmode(_fileno(stdout), _O_BINARY);
#endif
    std::string text;
    char b[4096];
    for (size_t k; (k = std::fread(b, 1, sizeof b, stdin)) > 0;) text.append(b, k);
    for (size_t i = 0; i < text.size();) {
        size_t nl = text.find('\n', i);
        const size_t len = nl == std::string::npos ? text.size() - i : nl - i + 1;
        const std::string out = mkwvk::bug_report::redact(text.substr(i, len), unhex(argv[1]), unhex(argv[2]), argv[3][0] == '1');
        std::fwrite(out.data(), 1, out.size(), stdout);
        i += len;
    }
}
"""

# (line, home, user, windows, expected)
CASES = [
    ("-> /home/al/Games/x\n", "/home/al", "al", 0, "-> ~/Games/x\n"),
    ("/home/alice/x /home/al\n", "/home/al", "al", 0, "/home/alice/x ~\n"),
    ("/run/media/al/SD, /var/home/al/x, /media/al/disk, /home/al/.local\n", "/home/al", "al", 0,
     "/run/media/<user>/SD, /var/home/<user>/x, /media/<user>/disk, ~/.local\n"),
    ("Malice and al, /x/alx/ and vk: al\n", "/home/al", "al", 0, "Malice and al, /x/alx/ and vk: al\n"),
    ("/HOME/AL/x\n", "/home/al", "al", 0, "/HOME/AL/x\n"),
    ("C:\\Users\\John Smith\\Games\\x\n", "C:\\Users\\John Smith", "John Smith", 1, "%USERPROFILE%\\Games\\x\n"),
    ("c:/users/john smith/Games\n", "C:\\Users\\John Smith", "John Smith", 1, "%USERPROFILE%/Games\n"),
    ("D:\\Users\\JOHN SMITH\\x\n", "C:\\Users\\John Smith", "John Smith", 1, "D:\\Users\\<user>\\x\n"),
    ("C:\\Users\\Mary Jane Watson\\OneDrive\\Documents\\Longshot\\logs\n", "C:\\Users\\Mary Jane Watson", "Mary Jane Watson", 1,
     "%USERPROFILE%\\OneDrive\\Documents\\Longshot\\logs\n"),
    ("C:\\Users\\Seán O'Brien\\AppData\\Local\\Temp\\x.tmp and E:\\Users\\Seán O'Brien\\Games\n",
     "C:\\Users\\Seán O'Brien", "Seán O'Brien", 1,
     "%USERPROFILE%\\AppData\\Local\\Temp\\x.tmp and E:\\Users\\<user>\\Games\n"),
    ("/home/jörg/Spiele/Longshot/logs/hookshot_log.txt\n", "/home/jörg", "jörg", 0, "~/Spiele/Longshot/logs/hookshot_log.txt\n"),
    ("vk: device 0: NVIDIA GeForce RTX 4090, no path here\n", "/home/al", "al", 0,
     "vk: device 0: NVIDIA GeForce RTX 4090, no path here\n"),
    ("Games\\Longshot\\cache and ./logs/x relative\n", "C:\\Users\\al", "al", 1, "Games\\Longshot\\cache and ./logs/x relative\n"),
    ("max played; C:\\Users\\max\\x\n", "C:\\Users\\max", "max", 1, "max played; %USERPROFILE%\\x\n"),
    ("nothing here\n", "", "", 0, "nothing here\n"),
]


def compile_harness(cc, tmp):
    src, exe = tmp / "harness.c", tmp / ("harness" + (".exe" if os.name == "nt" else ""))
    src.write_text(HARNESS, encoding="utf-8")
    subprocess.run([cc, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-D_CRT_SECURE_NO_WARNINGS", "-I", str(ROOT / "host"),
                    str(src), str(ROOT / "host/log_redact.c"), "-o", str(exe)], check=True, timeout=180)
    return exe


def run(exe, args, text="", env=None):
    r = subprocess.run([str(exe), *args], input=text.encode("utf-8"), capture_output=True, env=env, timeout=60)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.decode("utf-8")


def core_checks(exe):
    for line, home, user, windows, want in CASES:
        hx = [home.encode("utf-8").hex(), user.encode("utf-8").hex()]
        got = run(exe, ["core", *hx, str(windows)], line)
        assert got == want, ("C", line, got, want)
        assert run(exe, ["core", *hx, str(windows)], got) == got, ("C again", got)
        py = log_redact.redact_line(line, home, user, bool(windows))
        assert py == want, ("Python", line, py, want)
        assert log_redact.redact_line(py, home, user, bool(windows)) == py, ("Python again", py)


def menu_checks(cxx, exe, tmp):
    """the Insert menu's Bug report (gpu/vk/vk_bug_report.cpp redact): the same output as the shared rule, line for line"""
    src, menu = tmp / "menu.cpp", tmp / ("menu" + (".exe" if os.name == "nt" else ""))
    src.write_text(MENU, encoding="utf-8")
    subprocess.run([cxx, "-std=c++20", "-O1", *([] if os.name == "nt" else ["-pthread"]), "-I", str(ROOT / "gpu/vk"), str(src),
                    str(ROOT / "gpu/vk/vk_bug_report.cpp"), "-o", str(menu)], check=True, timeout=300)
    for line, home, user, windows, want in CASES:
        hx = [home.encode("utf-8").hex(), user.encode("utf-8").hex()]
        assert run(menu, [*hx, str(windows)], line) == want == run(exe, ["core", *hx, str(windows)], line), ("menu", line)


def env_for(home, user):
    env = dict(os.environ)
    if os.name == "nt":
        env.update(USERPROFILE=home, USERNAME=user)
    else:
        env.update(HOME=home, USER=user)
    return env


def here_checks(exe, tmp):
    if os.name == "nt":
        # (a profile folder named for the PC, which USERNAME is not: both go)
        home = "C:\\Users\\john.PC"
        env = env_for(home, "john")
        got = run(exe, ["line"], "C:\\Users\\john.PC\\x and D:\\Users\\john.PC\\y and D:\\Users\\john\\z\n", env)
        assert got == "%USERPROFILE%\\x and D:\\Users\\<user>\\y and D:\\Users\\<user>\\z\n", got
        # (the short 8.3 name of the home folder, where the drive makes them)
        long_home = tmp / "Jonathan Smithson Longname"
        long_home.mkdir()
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(str(long_home), buf, 1024)
        short = buf.value if n else ""
        got = run(exe, ["line"], short + "\\AppData\\Local\\Temp\\x.tmp\n", env_for(str(long_home), "Jonathan Smithson"))
        if short and short.lower() != str(long_home).lower():
            assert got == "%USERPROFILE%\\AppData\\Local\\Temp\\x.tmp\n", (short, got)
            print("  (the 8.3 name checked: %s)" % short)
        else:
            print("  (this drive makes no 8.3 names: the short name's case not checked)")
    else:
        env = env_for("/home/al", "al")
        got = run(exe, ["line"], "[hos Main] saves in /home/al/.local/share/longshot and /run/media/al/SD\n", env)
        assert got == "[hos Main] saves in ~/.local/share/longshot and /run/media/<user>/SD\n", got


def file_checks(exe, tmp):
    home = "C:\\Users\\Pat Smith" if os.name == "nt" else "/home/pat smith"
    user = "Pat Smith" if os.name == "nt" else "pat smith"
    env = env_for(home, user)
    w = "%USERPROFILE%" if os.name == "nt" else "~"
    sep = "\\" if os.name == "nt" else "/"
    raw = ("longshot v3.0.0\nrun_id: 0123abcd\n"
           "loader: layer manifest " + home + sep + "AppData" + sep + "x.json\n"
           "a line with no path\n" + home + sep + "y\nno newline at the end " + home)
    want = raw.replace(home, w)
    log = tmp / "hookshot_log.txt"
    log.write_bytes(raw.encode("utf-8"))
    assert run(exe, ["file", str(log), "ffffffff"], "", env).strip() == "0"   # (another run's: left alone)
    assert log.read_bytes() == raw.encode("utf-8")
    assert run(exe, ["file", str(log), "0123abcd"], "", env).strip() == "1"
    assert log.read_bytes().decode("utf-8") == want, log.read_bytes()
    assert run(exe, ["file", str(log)], "", env).strip() == "0"   # (clean already: not written)
    # (shorter: a long home folder for a short ~; longer: a short one for %USERPROFILE%)
    short_home = "C:\\U" if os.name == "nt" else "/h"
    log.write_bytes(("x " + short_home + sep + "a\n").encode("utf-8"))
    assert run(exe, ["file", str(log)], "", env_for(short_home, "U")).strip() == "1"
    assert log.read_bytes().decode("utf-8") == "x " + w + sep + "a\n"
    assert run(exe, ["file", str(tmp / "none.txt")], "", env).strip() == "-1"


def python_checks(tmp):
    here = ("/home/al", "al", "", False)
    out = io.StringIO()
    lines = log_redact.RedactedLines(out, here)
    lines.write("compiling /ho")
    assert out.getvalue() == ""   # (whole lines only)
    lines.write("me/al/work/x.c\nlinked /home/al/y and /run/media/al/z\nleft")
    assert out.getvalue() == "compiling ~/work/x.c\nlinked ~/y and /run/media/<user>/z\n", out.getvalue()
    lines.close()
    assert out.getvalue().endswith("\nleft")
    home, user, folder, windows = log_redact.who({"USERPROFILE": "C:\\Users\\john.PC", "USERNAME": "john"}, windows=True)
    assert (home, user, folder, windows) == ("C:\\Users\\john.PC", "john", "john.PC", True)
    assert log_redact.redact("D:\\Users\\john.PC\\x C:\\Users\\john.PC\\y", (home, user, folder, windows)) == \
        "D:\\Users\\<user>\\x %USERPROFILE%\\y"
    # make_game.py's --log goes through it, and closes it
    make_game = (ROOT / "nx2/make_game.py").read_text(encoding="utf-8")
    start = make_game.index("def build_log(path):")
    body = make_game[start:make_game.index("\n\n\n", start)]
    assert "saved = _log_redact.RedactedLines(log)" in body and "LogStream(sys.stdout, saved)" in body
    assert "LogStream(sys.stderr, saved)" in body and "saved.close()" in body
    assert "import log_redact as _log_redact" in make_game


def source_checks():
    threads = (ROOT / "host/hos_thread.c").read_text(encoding="utf-8")
    vlog = threads[threads.index("static void hos_vlog("):threads.index("void hos_log(const char *fmt, ...) {")]
    assert vlog.index("snprintf(raw,") < vlog.index("hos_log_redact(line, sizeof line, raw);") < vlog.index("hos_control_log(line)")
    assert vlog.index("hos_log_redact(line,") < vlog.index("log_queue(line)") < vlog.index("fputs(line, stderr)")
    fatal = threads[threads.index("void hos_fatal("):threads.index("void a64_on_trap(")]
    assert fatal.index("hos_log_redact(clean, sizeof clean, buf);") < fatal.index('"[hos %s] FATAL: %s"')
    main = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    assert main.index("MOVEFILE_REPLACE_EXISTING);") < main.index("hos_log_redact_file(to, NULL);") < main.index('freopen(path, "w", stderr)')
    dialog = (ROOT / "host/hos_crash_dialog.c").read_text(encoding="utf-8")
    helper = dialog[dialog.index("static int helper(const HosCrashArgs *a) {"):]
    assert helper.index("hos_log_redact_file(log->path, run_id);") < helper.index("read_log(log, &s.who);")
    assert helper.index("wait_game(a, &have_exit, &code)") < helper.index("hos_log_redact_file(")
    header = (ROOT / "host/hos_crash_dialog.h").read_text(encoding="utf-8")
    assert "return hookshot_redact_line(out, cap, line, n, home, user, windows);" in header
    menu = (ROOT / "gpu/vk/vk_bug_report.cpp").read_text(encoding="utf-8")
    redact = menu[menu.index("std::string redact(const std::string& line"):menu.index("std::string cpu_name() {")]
    assert "hookshot_redact_line(" in redact


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cc", default=os.environ.get("CC", "gcc"))
    ap.add_argument("--cxx", default=os.environ.get("CXX", "g++"))
    a = ap.parse_args()
    source_checks()
    python_checks(None)
    with tempfile.TemporaryDirectory(prefix="log-redact-") as t:
        tmp = Path(t)
        exe = compile_harness(a.cc, tmp)
        core_checks(exe)
        menu_checks(a.cxx, exe, tmp)
        here_checks(exe, tmp)
        file_checks(exe, tmp)
    print("PASS: the saved logs without the user name (the rule in C and Python, the game's line, the file after its run, "
          "the builder's log, the callers)")


if __name__ == "__main__":
    main()
