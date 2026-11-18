"""The options file (hookshot_options.ini) is written whole or not at all (gpu/vk/vk_menu.cpp save, replace_file).

save() wrote it with fopen "w", which empties it first: a crash or a kill during the write left it empty or cut short, and the
next start took what was left for the player's settings. Now the lines go to <ini>.new, which is moved over the file in one
step (MoveFileExW on Windows, the path turned to wide from UTF-8; rename elsewhere). From HeyListen 7cec25ab / Longshot 524d5520.

- The source: save() writes the part, not the file, and moves it over only when the write went through; replace_file converts
  with CP_UTF8.
- replace_file compiled and run: an old file is replaced by the new bytes, a missing one is made, and no .new is left.
  (UTF-8 folder names: tests/test_utf8_paths.py runs the game's narrow functions in one; replace_file's wide conversion is
  CP_UTF8, checked above.)

python -I -B tests/test_options_atomic.py [--cxx clang++]
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def block(source, marker):
    start = source.index(marker)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


HARNESS = r"""
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <string>
#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#endif
@REPLACE@
static std::string slurp(const std::string& p) {
    std::string s;
    if (FILE* f = fopen(p.c_str(), "rb")) {
        char b[256];
        size_t n;
        while ((n = fread(b, 1, sizeof b, f))) s.append(b, n);
        fclose(f);
    }
    return s;
}
static void put(const std::string& p, const char* s) {
    FILE* f = fopen(p.c_str(), "wb");
    fputs(s, f);
    fclose(f);
}
int main(int argc, char** argv) {
    const std::string ini = std::string(argv[1]) + "/hookshot_options.ini", part = ini + ".new";
    int bad = 0;
    put(part, "a=1\n");
    if (!replace_file(part, ini) || slurp(ini) != "a=1\n") puts("FAIL: a missing file is not made"), bad = 1;
    put(part, "a=2\nb=3\n");
    if (!replace_file(part, ini) || slurp(ini) != "a=2\nb=3\n") puts("FAIL: the old file is not replaced"), bad = 1;
    if (FILE* f = fopen(part.c_str(), "rb")) fclose(f), puts("FAIL: the part is left behind"), bad = 1;
    if (!bad) puts("ok");
    return bad;
}
"""


def check_source(menu):
    save = block(menu, "void save() {")
    if 'fopen(ini_path().c_str(), "w")' in save:
        raise SystemExit("FAIL: save() still empties hookshot_options.ini before writing it")
    for needle in ('const std::string ini = ini_path(), part = ini + ".new";', 'fopen(part.c_str(), "w")',
                   "const bool written = fflush(f) == 0 && !ferror(f);",
                   "if (fclose(f) == 0 && written) replace_file(part, ini);", "else remove(part.c_str());"):
        if needle not in save:
            raise SystemExit("FAIL: save() does not write the options to a part moved over the file: " + needle)
    replace = block(menu, "bool replace_file(const std::string& part, const std::string& path) {")
    for needle in ("CP_UTF8", "MOVEFILE_REPLACE_EXISTING", "rename(part.c_str(), path.c_str())"):
        if needle not in replace:
            raise SystemExit("FAIL: replace_file has no " + needle)
    if "CP_ACP" in replace:
        raise SystemExit("FAIL: replace_file converts with the ANSI code page")
    return replace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    replace = check_source((ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8"))
    compiler = shutil.which(args.cxx)
    if not compiler:
        raise SystemExit("C++ compiler not found: " + args.cxx)
    with tempfile.TemporaryDirectory(prefix="options-atomic-") as temporary:
        folder = Path(temporary)
        (folder / "fixture.cpp").write_text(HARNESS.replace("@REPLACE@", replace), encoding="utf-8")
        exe = folder / ("fixture.exe" if os.name == "nt" else "fixture")
        subprocess.run([compiler, "-std=c++17", "-O1", "-w", str(folder / "fixture.cpp"), "-o", str(exe)], check=True,
                       timeout=120)
        game = folder / "game"
        game.mkdir()
        result = subprocess.run([str(exe), str(game)], capture_output=True, text=True, timeout=30)
        print(result.stdout, end="")
        if result.returncode or "ok" not in result.stdout:
            raise SystemExit("hookshot_options.ini is not replaced whole")
    print("options file: written beside it and moved over it whole")


if __name__ == "__main__":
    main()
