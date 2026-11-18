"""The renderer's built-in shaders from disk (gpu/vk/vk_builtin_spv.h; the dev-loop proposal's B2): with RX_VK_SHADER_DIR
set, <folder>/<name>.spv is used when it is SPIR-V, the compiled-in words otherwise; unset, the compiled-in words, without a
file looked for. The lookup is built as C++ with a stand-in log and run against made-up files, and every use of a
compiled-in array in gpu/vk goes through it. No game, GPU or glslang required.

python -I -B tests/test_builtin_spv.py [--cxx g++]
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu" / "vk"

DRIVER = r"""
#include <cstdarg>
#include <cstdio>
#include "vk_builtin_spv.h"
namespace mkwvk {
void logf(const char* fmt, ...) {
    va_list a;
    va_start(a, fmt);
    printf("log: ");
    vprintf(fmt, a);
    printf("\n");
    va_end(a);
}
}
const uint32_t CLEAR_VERT_SPV[] = {0x07230203u, 0x00010000u, 0u, 1u, 0u, 0xc0ffeeu};
int main() {
    const mkwvk::BuiltinSpv a = BUILTIN_SPV(CLEAR_VERT_SPV), b = BUILTIN_SPV(CLEAR_VERT_SPV);
    printf("from %s, %zu bytes, word 5 %x, kept %d\n", a.code == CLEAR_VERT_SPV ? "compiled-in" : "file", a.size,
           (unsigned)(a.size >= 24 ? a.code[5] : 0), a.code == b.code && a.size == b.size);
    return 0;
}
"""


def words(*w):
    return b"".join(x.to_bytes(4, "little") for x in w)


def build(cxx, folder):
    (folder / "driver.cpp").write_text(DRIVER, encoding="utf-8")
    exe = folder / ("driver.exe" if os.name == "nt" else "driver")
    r = subprocess.run([cxx, "-std=c++17", "-O1", "-I", str(VK), str(VK / "vk_builtin_spv.cpp"), str(folder / "driver.cpp"),
                        "-o", str(exe)], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("vk_builtin_spv.cpp did not build:\n" + (r.stderr or r.stdout)[-3000:])
    return exe


def run(exe, shader_dir, cxx):
    env = dict(os.environ)
    found = shutil.which(cxx)   # (its folder on the path: llvm-mingw's C++ library is a DLL beside it)
    if found:
        env["PATH"] = os.path.dirname(found) + os.pathsep + env.get("PATH", "")
    env.pop("RX_VK_SHADER_DIR", None)
    if shader_dir is not None:
        env["RX_VK_SHADER_DIR"] = str(shader_dir)
    r = subprocess.run([str(exe)], capture_output=True, text=True, env=env, encoding="utf-8")
    if r.returncode:
        raise SystemExit("the lookup's driver stopped (%d): %s" % (r.returncode, r.stderr[-2000:]))
    return r.stdout


def check_lookup(cxx):
    with tempfile.TemporaryDirectory(prefix="hookshot builtin spv-") as tmp:   # (a space in the folder's name)
        tmp = Path(tmp)
        exe = build(cxx, tmp)
        shaders = tmp / "my shaders"
        shaders.mkdir()
        cases = []
        out = run(exe, None, cxx)
        cases.append(("unset", out, "from compiled-in, 24 bytes, word 5 c0ffee, kept 1", False))
        out = run(exe, shaders, cxx)
        cases.append(("no file", out, "from compiled-in, 24 bytes, word 5 c0ffee, kept 1", False))
        (shaders / "clear_vert.spv").write_bytes(words(0x07230203, 0x00010300, 0, 1, 0, 0xbeef, 7))
        out = run(exe, shaders, cxx)
        cases.append(("a SPIR-V file", out, "from file, 28 bytes, word 5 beef, kept 1", "from"))
        (shaders / "clear_vert.spv").write_bytes(words(0x07230203, 0x00010300, 0, 1, 0, 0xbeef) + b"\0\0")
        out = run(exe, shaders, cxx)
        cases.append(("a file cut short", out, "from compiled-in, 24 bytes, word 5 c0ffee, kept 1", "not a whole number"))
        (shaders / "clear_vert.spv").write_bytes(words(0x03022307, 0x00010300, 0, 1, 0, 0xbeef))
        out = run(exe, shaders, cxx)
        cases.append(("not SPIR-V", out, "from compiled-in, 24 bytes, word 5 c0ffee, kept 1", "not SPIR-V"))
        for name, out, want, log in cases:
            lines = out.splitlines()
            if lines[-1:] != [want]:
                raise SystemExit("%s: got %r, wanted %r" % (name, lines[-1:], want))
            logs = [l for l in lines if l.startswith("log: ")]
            if not log and logs:
                raise SystemExit("%s: logged %r, wanted nothing" % (name, logs))
            if log and (len(logs) != 1 or log not in logs[0] or "clear_vert" not in logs[0]):
                raise SystemExit("%s: logged %r, wanted one line with %r (the second lookup is kept, not logged again)"
                                 % (name, logs, log))
            print("ok   %s: %s%s" % (name, want, (" (%s)" % logs[0][5:]) if logs else ""))


def check_every_use():
    """Every compiled-in array of gpu/vk/shaders and host_shaders is used through the lookup, so none is missed by it"""
    arrays = set()
    for folder in ("shaders", "host_shaders"):
        for h in (VK / folder).glob("*_spv.h"):
            arrays |= set(re.findall(r"\b([A-Z0-9_]+_SPV)\s*\[\]", h.read_text(encoding="utf-8", errors="replace")))
    if len(arrays) < 40:
        raise SystemExit("only %d compiled-in arrays found in gpu/vk/shaders and host_shaders" % len(arrays))
    used = set()
    for cpp in sorted(VK.glob("*.cpp")):
        if cpp.name == "vk_builtin_spv.cpp":   # (the lookup itself)
            continue
        text = cpp.read_text(encoding="utf-8", errors="replace")
        text = re.sub(r"^#include .*$", "", text, flags=re.M)
        used |= set(re.findall(r"\bBUILTIN_SPV(?:_ARGS)?\(([A-Z0-9_]+_SPV)\)", text))
        text = re.sub(r"\bBUILTIN_SPV(?:_ARGS)?\([A-Z0-9_]+_SPV\)", "", text)
        for m in re.finditer(r"^\s*PASS\(\"[^\"]*\",\s*([A-Z0-9_]+_SPV),", text, re.M):   # (the FSR 3 tables, named below)
            used.add(m.group(1))
        text = re.sub(r"^\s*PASS\(\"[^\"]*\",\s*[A-Z0-9_]+_SPV,", "", text, flags=re.M)
        bare = sorted(set(re.findall(r"\b([A-Z0-9_]+_SPV)\b", text)) & arrays)
        if bare:
            raise SystemExit("%s uses %s without builtin_spv (RX_VK_SHADER_DIR would not reach it)" % (cpp.name, ", ".join(bare)))
    for name in ("vk_fsr3.cpp", "vk_fsr3fi.cpp"):
        text = (VK / name).read_text(encoding="utf-8")
        if "#spv}" not in text or "builtin_spv(info.spv_name, info.spv, info.spv_bytes)" not in text or "mi.pCode = info.spv;" in text:
            raise SystemExit("%s: its passes' modules are not made through builtin_spv by the array's name" % name)
    print("ok   every use: %d compiled-in arrays used in gpu/vk, all through builtin_spv" % len(used & arrays))


def check_not_from_a_shared_file():
    """hookshot_env.txt is passed between players: a folder of shader code is not taken from it (its _DIR name)"""
    main = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    rule = main[main.index("static int env_line_allowed("):]
    rule = rule[:rule.index("\n}\n")]
    if '!strcmp(name + nl - 4, "_DIR")' not in rule or "if (names_file) return 0;" not in rule:
        raise SystemExit("env_line_allowed: a _DIR switch (RX_VK_SHADER_DIR) can be set from hookshot_env.txt")
    print("ok   RX_VK_SHADER_DIR is not taken from hookshot_env.txt")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    check_every_use()
    check_not_from_a_shared_file()
    check_lookup(args.cxx)
    print("builtin spv: ok")


if __name__ == "__main__":
    sys.exit(main())
