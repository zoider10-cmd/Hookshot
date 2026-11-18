"""The renderer's C++ allocations at Windows' commit limit (issue 1280). In hookshot_vk.dll a refused operator new threw
std::bad_alloc that nothing caught, and the game ended with exception 0x20474343 ("An unexpected error"): no wait for memory
and no out-of-memory notice, where the host's own allocations wait since issue 333. Now mkwvk_init installs a new_handler,
new_refused (gpu/vk/vk_main.cpp), that waits up to 5 s for memory and then stops the game through the host's out-of-memory
line and notice (MkwVkHost out_of_memory, version 28).

Compiles the real new_refused and its constants, cut out of gpu/vk/vk_main.cpp, with tests/renderer_new_handler_test.cpp's
clock, log and host, and runs each case in its own process. The refusals are real: 1 PB asked of the C++ library's own
operator new, which calls the handler each time malloc refuses and tries again when it returns:

- limit, aligned, array: operator new, its aligned form and new[]: 100 tries 50 ms apart (5 s), one log line, then the host's
  out_of_memory with the renderer's label;
- continues, apart: tries that follow each other are one refusal's 5 s; a refusal a second after the last try gets a whole
  wait of its own;
- nothrow: in a NewNothrow scope (gpu/vk/vk_new.h) a nothrow new, aligned or not, and new (std::nothrow)[] get their null at
  once, with no wait and no stop; nothrow-unscoped: without the scope they wait and stop too, which is why the scope is there;
- old-host, no-host: a version-27 host (no out_of_memory) or none: std::bad_alloc after the wait, as before;
- small: an allocation that is given never runs the handler.

And by text: mkwvk_init installs the handler once it has the host; every std::nothrow new in the renderer is in a NewNothrow
scope; the host's out_of_memory callback is hos_alloc_gave_up (host/mkw_glue.c, tested by tests/test_host_alloc_wait.py); and
HOS_TEST_ALLOC_REFUSE's allocation runs at the replay's present.

python -I -B tests/test_renderer_new_handler.py [--cxx g++]
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import block, between  # noqa: E402

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu/vk"
CASES = ("limit", "aligned", "array", "continues", "apart", "nothrow", "nothrow-unscoped", "old-host", "no-host", "small")
HEAD = "// (hookshot, issue 1280) The renderer's C++ allocations at Windows' commit limit"


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def check_sites(main):
    init = block(main, "const MkwVkRenderer* mkwvk_init(const MkwVkHost* h)")
    if "std::set_new_handler(new_refused)" not in init:
        raise SystemExit("FAIL: mkwvk_init installs no new_handler: a C++ allocation refused at the commit limit throws "
                         "std::bad_alloc that nothing catches, and the game ends with exception 0x20474343 (issue 1280)")
    if init.index("host = &host_storage;") > init.index("std::set_new_handler(new_refused)"):
        raise SystemExit("FAIL: mkwvk_init installs the new_handler before it has the host to stop the game through")
    for path in sorted(VK.glob("*.cpp")) + sorted(VK.glob("*.h")):
        if path.name == "vk_new.h":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if "std::nothrow" in line and not line.lstrip().startswith("//") and \
                    not any("const NewNothrow" in previous for previous in lines[max(0, i - 3):i]):
                raise SystemExit("FAIL: %s:%d: a nothrow new outside a NewNothrow scope waits 5 s and stops the game at a "
                                 "refusal instead of giving its caller the null" % (path.relative_to(ROOT).as_posix(), i + 1))
    backend = read("host/rx_backend.c")
    if "hos_alloc_gave_up(0, what)" not in block(backend, "static void host_out_of_memory(const char *what)"):
        raise SystemExit("FAIL: the host's out_of_memory is not hos_alloc_gave_up's line, notice and stop")
    replay = read("gpu/vk/vk_replay.cpp")
    if not re.search(r"presents\+\+;\n\s*presents_now = presents;\n\s*new_refuse_test\(presents\);", replay):
        raise SystemExit("FAIL: HOS_TEST_ALLOC_REFUSE's allocation (new_refuse_test) is not run at the replay's present")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    args = parser.parse_args()
    main_text = read("gpu/vk/vk_main.cpp")
    check_sites(main_text)
    head = between(main_text, HEAD, "static void new_sleep_ms(int ms)")
    body = block(main_text, "void new_refused() {")
    cxx = shutil.which(args.cxx)
    if not cxx:
        raise SystemExit("test_renderer_new_handler: no C++ compiler %r (pass --cxx)" % args.cxx)
    flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="renderer-new-handler-") as temporary:
        folder = Path(temporary)
        (folder / "renderer_new_handler_head.inc").write_text(head + "\n", encoding="utf-8")
        (folder / "renderer_new_handler_body.inc").write_text(body + "\n", encoding="utf-8")
        executable = folder / "fixture.exe"
        subprocess.run([cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), "-I", str(folder),
                        str(ROOT / "tests/renderer_new_handler_test.cpp"), "-o", str(executable)],
                       check=True, creationflags=flags)
        for case in CASES:
            result = subprocess.run([str(executable), case], capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=30, creationflags=flags)
            print(result.stdout, end="")
            if result.returncode:
                print(result.stderr, end="", file=sys.stderr)
                raise SystemExit("FAIL: case %s (exit %d)" % (case, result.returncode))
    print("PASS: a refused C++ allocation in the renderer waits for memory, then says out of memory through the host")


if __name__ == "__main__":
    main()
