"""The guest window is a memfd's whenever /dev/udmabuf opens, even when udmabuf's size_limit_mb can't be read (issue 1135).

A Flatpak's or Steam's container shows /dev/udmabuf but not /sys/module, so the limit file can't be opened there. The
renderer then takes udmabuf's default, 64 MB (gpu/vk/vk_memory.cpp, import_dma_buf), and splits larger pools into
pieces of that size; the start-up check in host/hos_main.c has to choose the memfd window the same way, or every pool is
a host-pointer import (6-10 fps on an AMD APU under Steam, 30 with HOS_GUEST_MEMFD=1).

The check cuts the block that decides it out of host/hos_main.c by its text and runs it with the limit file missing,
holding a number, holding 0 and holding no number, and with /dev/udmabuf not opened.

    python -I -B tests/test_udmabuf_limit_unreadable.py [--cc gcc]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]
RUN_ALL_SKIP = {"windows": "the Linux guest window's start-up check (POSIX file descriptors)"}
ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#define hos_log(...) (fprintf(stderr, __VA_ARGS__), fputc('\n', stderr))
/* the limit file is the path in LIMIT_FILE, or missing when it is unset */
static FILE *fixture_fopen(const char *path, const char *mode) {
    if (strcmp(path, "/sys/module/udmabuf/parameters/size_limit_mb") != 0) return NULL;
    const char *p = getenv("LIMIT_FILE");
    return p ? fopen(p, mode) : NULL;
}
#define fopen fixture_fopen
int main(int argc, char **argv) {
    int usable = 0;
    unsigned long long limit_mb = 0;   /* (main's block before issue 1135 read the limit into it) */
    (void)limit_mb;
    const int u = atoi(argv[1]) ? open("/dev/null", O_RDWR | O_CLOEXEC) : -1;
    (void)argc;
@@CODE@@
    printf("%d\n", usable);
    return 0;
}
'''


def run(exe, opened, limit_text, tmp):
    env = {"PATH": "/usr/bin:/bin"}
    if limit_text is not None:
        path = Path(tmp) / "size_limit_mb"
        path.write_text(limit_text, encoding="utf-8")
        env["LIMIT_FILE"] = str(path)
    out = subprocess.run([str(exe), "1" if opened else "0"], capture_output=True, text=True, check=True, env=env)
    return int(out.stdout), out.stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    src = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    start = src.index('const int u = open("/dev/udmabuf", O_RDWR | O_CLOEXEC);')
    begin = src.index("if (u >= 0) {", start)
    code = src[begin:src.index("if (!usable && !e)", begin)]
    with tempfile.TemporaryDirectory(prefix="udmabuf-limit-") as tmp:
        c, exe = Path(tmp) / "fixture.c", Path(tmp) / "fixture"
        c.write_text(FIXTURE.replace("@@CODE@@", code), encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(c), "-o", str(exe)], check=True)

        # the report: /dev/udmabuf opens, the limit file can't be read -> the memfd window, and the log says why
        usable, log = run(exe, True, None, tmp)
        assert usable == 1, f"/dev/udmabuf opened but size_limit_mb unreadable: the window must still be a memfd's (got usable={usable})"
        assert "size_limit_mb" in log and "64 MB" in log, f"the assumed default is said in the log: {log!r}"

        # a readable limit, whatever it holds (the renderer reads it and takes 64 MB for 0 or no number): quietly
        for text in ("64\n", "256\n", "0\n", "x\n", ""):
            usable, log = run(exe, True, text, tmp)
            assert usable == 1, (text, usable)
            assert not log, (text, log)

        # /dev/udmabuf not opened: no memfd window, whatever the limit file says
        for text in (None, "64\n"):
            usable, _ = run(exe, False, text, tmp)
            assert usable == 0, (text, usable)
    print("PASS: /dev/udmabuf opened -> memfd window, size_limit_mb readable or not; not opened -> none")


if __name__ == "__main__":
    main()
