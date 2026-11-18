"""The renderer's switch table (gpu/vk/switches.def, switches.h) against the source, and its report of what a run set.

Every RX_ name the source reads from the environment has a row, every row is read somewhere, and a removed name (GONE)
is read nowhere: a switch added without a row, a row left behind by a deleted read and a removal that left a read all
fail here. A read is a whole string literal "RX_..." in code under gpu/, host/ or nx2/ (not in a comment, not part of a
longer string): the reads go through getenv, env_on and helpers that are handed the name, so the literal is what they
share. PREFIXES are the literals that are no switch themselves: the start of a family, matched against the names the
environment holds.

Then switches.h itself, compiled alone: find() on the sorted table, and report() on made-up environments (a switch set,
a removed one, a name that is none, nothing set).

    python -I -B tests/test_switch_table.py [--cxx g++]
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"
KINDS = ("diag", "tune", "kill", "attempt", "hw", "player")
TYPES = ("bool", "int", "float", "string", "enum")
# (literals that start a family of switches and are matched against the environment's names, not read themselves:
#  the program cache's stamp in gpu/vk/vk_shader.cpp hashes every set switch that begins with one)
PREFIXES = {
    "RX_VK_FOLLOW", "RX_VK_GP_", "RX_VK_MARKERS", "RX_VK_MESH", "RX_VK_MMA", "RX_VK_NAN", "RX_VK_NATIVE", "RX_VK_NETWORK",
    "RX_VK_SHARED",
}
SKIP_DIRS = {"third_party", "tests", "build-linux", "build-windows"}

ROW = re.compile(r'^SW\((RX_[A-Z0-9_]+), (\w+), (\w+), "((?:[^"\\]|\\.)*)", "((?:[^"\\]|\\.)*)"\)$')
GONE = re.compile(r'^GONE\((RX_[A-Z0-9_]+), "(\d{4}-\d{2}-\d{2})", "((?:[^"\\]|\\.)*)"\)$')
LITERAL = re.compile(r'"(RX_[A-Z0-9_]+)"')


def code_of(line):
    """The line up to a // comment that is not inside a string"""
    quoted, i = False, 0
    while i < len(line):
        c = line[i]
        if c == '"' and (i == 0 or line[i - 1] != "\\"):
            quoted = not quoted
        elif not quoted and line.startswith("//", i):
            return line[:i]
        i += 1
    return line


def table():
    rows, gone, bad = [], [], []
    for n, line in enumerate((VK / "switches.def").read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        m = ROW.match(line)
        if m:
            rows.append(m.groups())
            continue
        m = GONE.match(line)
        if m:
            gone.append(m.groups())
            continue
        bad.append("switches.def:%d is neither SW(name, kind, type, \"unset\", \"summary\") nor GONE(name, \"date\", \"became\")" % n)
    return rows, gone, bad


def literals():
    """{name: ["file:line", ...]} of the whole "RX_..." literals in code"""
    found = {}
    for base in ("gpu", "host", "nx2"):
        for path in sorted((ROOT / base).rglob("*")):
            if path.suffix not in (".c", ".cpp", ".h", ".inc") or SKIP_DIRS & set(path.relative_to(ROOT).parts):
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if '"RX_' not in line:
                    continue
                if line.lstrip().startswith(("//", "*", "/*")):
                    continue
                for m in LITERAL.finditer(code_of(line)):
                    found.setdefault(m.group(1), []).append("%s:%d" % (path.relative_to(ROOT).as_posix(), n))
    return found


FIXTURE = r"""
#include <cstdio>
#include <string>
#include <vector>
#include "switches.h"
using namespace mkwvk::switches;
static int bad;
static void need(bool ok, const char* what) { if (!ok) bad++, std::printf("FAIL: %s\n", what); }
static std::vector<std::string> run(std::vector<const char*> env, int* strangers) {
    env.push_back(nullptr);
    std::vector<std::string> lines;
    *strangers = report(env.data(), [&](const char* line) { lines.push_back(line); });
    return lines;
}
int main() {
    for (size_t i = 0; i < row_count; i++) need(find(rows[i].name) == &rows[i], rows[i].name);
    need(!find("RX_VK_NO_SUCH_SWITCH") && !find("") && !find("RX_"), "a name the table lacks is found");
    need(ours("RX_VK_X", 7) && !ours("RX_", 3) && !ours("HOS_X", 5) && !ours("PATH", 4), "ours()");
    int strangers = -1;
    auto lines = run({"PATH=/usr/bin", "HOS_FPS_MAX=240", "RXVK=1"}, &strangers);
    need(lines.size() == 1 && lines[0] == "vk: switches set: none" && strangers == 0, "nothing set");
    const std::string first = rows[0].name, kind = kind_name(rows[0].kind);
    const std::string a = first + "=1", b = "RX_VK_NO_SUCH_SWITCH=1", c = first + "=" + std::string(60, 'x');
    lines = run({"PATH=/usr/bin", a.c_str(), b.c_str()}, &strangers);
    need(strangers == 1 && lines.size() == 2, "a switch and a stranger: two lines");
    need(lines.size() == 2 && lines[0] == "vk: RX_VK_NO_SUCH_SWITCH is set, and is not a switch of this build: a misspelt name, or one "
                                          "from another build", "the stranger's line");
    need(lines.size() == 2 && lines[1] == "vk: switches set (1): " + first + "=1 (" + kind + ")", "the set line");
    lines = run({c.c_str()}, &strangers);
    need(lines.size() == 1 && lines[0] == "vk: switches set (1): " + first + "=" + std::string(45, 'x') + "... (" + kind + ")",
         "a long value is cut at 48");
    const std::string d = first + "=/home/someone/out.csv", w = first + "=C:\\Users\\someone\\out.csv";
    lines = run({d.c_str()}, &strangers);
    need(lines.size() == 1 && lines[0] == "vk: switches set (1): " + first + "=<a path> (" + kind + ")", "a path is not said");
    lines = run({w.c_str()}, &strangers);
    need(lines.size() == 1 && lines[0] == "vk: switches set (1): " + first + "=<a path> (" + kind + ")", "a Windows path is not said");
    if (gone[0].name) {
        const std::string g = std::string(gone[0].name) + "=1";
        lines = run({g.c_str()}, &strangers);
        need(strangers == 1 && lines.size() == 2 && lines[0] == std::string("vk: ") + gone[0].name +
             " is set, and is no longer a switch (since " + gone[0].since + "): " + gone[0].became, "a removed switch's line");
        need(lines.size() == 2 && lines[1] == "vk: switches set: none", "a removed switch is not counted as set");
    }
    std::printf("%zu rows\n", row_count);
    return bad ? 1 : 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    rows, gone, bad = table()
    names = [r[0] for r in rows]
    if names != sorted(names):
        at = next(i for i in range(1, len(names)) if names[i - 1] > names[i])
        bad.append("switches.def is not sorted by name: %s comes after %s" % (names[at], names[at - 1]))
    for name in sorted(set(n for n in names if names.count(n) > 1)):
        bad.append("%s has two rows" % name)
    for name, kind, typ, unset, summary in rows:
        if kind not in KINDS:
            bad.append("%s: kind %s is none of %s" % (name, kind, ", ".join(KINDS)))
        if typ not in TYPES:
            bad.append("%s: type %s is none of %s" % (name, typ, ", ".join(TYPES)))
        if not unset.strip() or not summary.strip():
            bad.append("%s: what it does unset and what setting it does must both be said" % name)
    gone_names = [g[0] for g in gone]
    for name in gone_names:
        if name in names:
            bad.append("%s is both a switch and a removed one" % name)
    read = literals()
    for name in sorted(read):
        if name in PREFIXES:
            continue
        if name in gone_names:
            bad.append("%s was removed (GONE) and is still read: %s" % (name, ", ".join(read[name][:4])))
        elif name not in names:
            bad.append("%s is read (%s) and has no row in gpu/vk/switches.def" % (name, ", ".join(read[name][:4])))
    for name in names:
        if name not in read:
            bad.append("%s has a row and nothing reads it: delete the row, or make it GONE(...) if players set it" % name)
    for name in sorted(PREFIXES):
        if name not in read:
            bad.append("the test's PREFIXES names %s, which the source no longer has" % name)
        if name in names:
            bad.append("%s is in the test's PREFIXES and has a row: it is one or the other" % name)
    main_cpp = (VK / "vk_main.cpp").read_text(encoding="utf-8")
    if "switches::report(env," not in main_cpp[main_cpp.index("int start(void* hwnd) {"):]:
        bad.append("vk_main.cpp's start() does not say which switches the run has set (switches::report)")
    if bad:
        raise SystemExit("FAIL: the switch table and the source disagree:\n  " + "\n  ".join(bad))
    with tempfile.TemporaryDirectory(prefix="switch-table-") as tmp:
        tmp = Path(tmp)
        cpp, exe = tmp / "fixture.cpp", tmp / ("fixture.exe" if sys.platform == "win32" else "fixture")
        cpp.write_text(FIXTURE, encoding="utf-8")
        r = subprocess.run([args.cxx, "-std=c++20", "-O1", "-Wall", "-Werror", "-I" + str(VK), str(cpp), "-o", str(exe)],
                           capture_output=True, text=True)
        if r.returncode:
            raise SystemExit("FAIL: switches.h does not compile alone:\n" + r.stdout + r.stderr)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout, end="")
        if r.returncode:
            raise SystemExit("FAIL: switches.h's find() or report()")
    kinds = {k: sum(1 for r in rows if r[1] == k) for k in KINDS}
    print("ok: %d switches (%s), %d removed, %d names read" % (len(rows), ", ".join("%s %d" % kv for kv in kinds.items()),
                                                                len(gone), len(read)))


if __name__ == "__main__":
    main()
