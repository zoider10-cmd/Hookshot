"""Game-free: the button prompts' cache files (host/prompts.c write_patched: cache/prompts/Common.bntx.zs and Common.blarc.zs, each
with its key file) when a write fails part way (the disk full). The last good file and its key stay as they were, so going
back to that setting serves the same bytes again; nothing is left beside them; a later write that succeeds replaces the file and
the key. write_patched is compiled from host/prompts.c with its zstd helpers; the Windows file calls are stand-ins on POSIX
calls; a write fails at a file size limit (RLIMIT_FSIZE, SIGXFSZ ignored).

python -I -B tests/test_prompt_cache_errors.py [--cc gcc]
"""
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]
RUN_ALL_SKIP = {"windows": "a file size limit (RLIMIT_FSIZE) is POSIX's"}

ROOT = Path(__file__).resolve().parents[1]
GAME = 300000   # (the game's file: three of write_patched's 128 KB chunks)
RUN_AT, RUN_LEN = 140000, 64   # (one run, in the second chunk)


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def unpack(data):
    """the bytes of a zstd frame of raw blocks (as zstd_head and zstd_block write it)"""
    at, out = 10, bytearray()
    while True:
        check(at + 3 <= len(data), "the frame ends inside a block header")
        bh = data[at] | data[at + 1] << 8 | data[at + 2] << 16
        n = bh >> 3
        check((bh >> 1) & 3 == 0, "a block that is not raw")
        out += data[at + 3:at + 3 + n]
        at += 3 + n
        if bh & 1:
            check(at == len(data), "bytes after the last block")
            return bytes(out)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    src = (ROOT / "host" / "prompts.c").read_text(encoding="utf-8")
    run_type = re.search(r"typedef struct \{[^}]*\} Run;", src)
    check(run_type is not None, "host/prompts.c has no Run")
    harness = "\n".join([
        "#include <signal.h>", "#include <stdint.h>", "#include <stdio.h>", "#include <stdlib.h>", "#include <string.h>",
        "#include <sys/resource.h>", "#include <sys/stat.h>", "#include <unistd.h>",
        "#define MAX_PATH 260", "#define INVALID_FILE_ATTRIBUTES 0xFFFFFFFFu", "#define MOVEFILE_REPLACE_EXISTING 1u",
        "static unsigned GetFileAttributesA(const char *p) { struct stat st; return stat(p, &st) ? INVALID_FILE_ATTRIBUTES : 0; }",
        "static int DeleteFileA(const char *p) { return unlink(p) == 0; }",
        "static int MoveFileExA(const char *a, const char *b, unsigned flags) { (void)flags; return rename(a, b) == 0; }",
        re.search(r"static void wr32le\(.*", src).group(0),
        block(src, "static void zstd_head("),
        block(src, "static int zstd_block("),
        run_type.group(0),
        block(src, "static int run_cmp("),
        block(src, "static int run_order("),
        block(src, "static int write_patched("),
        # (argv: the game's file, out, the key file, the key (hex), the run's byte, the file size limit (0 none))
        "int main(int argc, char **argv) {",
        "    if (argc != 7) return 2;",
        "    static uint8_t data[%d];" % RUN_LEN,
        "    memset(data, argv[5][0], sizeof data);",
        "    Run run = {%d, %d, 0, data};" % (RUN_AT, RUN_LEN),
        "    const long limit = atol(argv[6]);",
        "    if (limit > 0) {",
        "        signal(SIGXFSZ, SIG_IGN);",
        "        struct rlimit r = {(rlim_t)limit, (rlim_t)limit};",
        "        if (setrlimit(RLIMIT_FSIZE, &r)) return 3;",
        "    }",
        "    printf(\"%d\\n\", write_patched(argv[1], argv[2], argv[3], strtoull(argv[4], NULL, 16), &run, 1));",
        "    return 0;",
        "}", ""])
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        c, exe = tmp / "cache.c", tmp / "cache"
        c.write_text(harness, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", str(c),
                        "-o", str(exe)], check=True)
        game, out, key = tmp / "Common.bntx", tmp / "Common.bntx.zs", tmp / "Common.key"
        game.write_bytes(bytes(i * 7 & 0xFF for i in range(GAME)))

        def write(h, byte, limit=0):
            r = subprocess.run([str(exe), str(game), str(out), str(key), h, byte, str(limit)], capture_output=True, text=True)
            check(r.returncode == 0, "the harness exited %d: %s" % (r.returncode, r.stderr))
            return r.stdout.split() == ["1"]

        def want(byte):
            g = bytearray(game.read_bytes())
            g[RUN_AT:RUN_AT + RUN_LEN] = byte.encode() * RUN_LEN
            return bytes(g)

        check(write("a", "A"), "setting A was not written")
        a_bytes, a_key = out.read_bytes(), key.read_bytes()
        check(unpack(a_bytes) == want("A"), "setting A's file is not the game's file with A's run")
        check(a_key == b"000000000000000a", "setting A's key is %r" % a_key)

        # (setting B, the disk full part way: the file size limit inside the second chunk)
        check(not write("b", "B", limit=200000), "setting B's cut write was reported as written")
        check(out.read_bytes() == a_bytes, "a failed write of setting B changed setting A's file (%d bytes, was %d)" %
              (out.stat().st_size, len(a_bytes)))
        check(key.read_bytes() == a_key, "a failed write of setting B changed the key to %r" % key.read_bytes())
        left = sorted(x.name for x in tmp.iterdir() if x.name not in ("cache.c", "cache", game.name, out.name, key.name))
        check(not left, "a failed write left %s" % left)

        # (back on setting A: its key matches, the same bytes are served)
        check(write("a", "A"), "setting A after B's failed write was not served")
        check(out.read_bytes() == a_bytes, "setting A after B's failed write serves other bytes")

        # (setting B with room: file and key replaced)
        check(write("b", "B"), "setting B was not written")
        check(unpack(out.read_bytes()) == want("B"), "setting B's file is not the game's file with B's run")
        check(key.read_bytes() == b"000000000000000b", "setting B's key is %r" % key.read_bytes())
        left = sorted(x.name for x in tmp.iterdir() if x.name not in ("cache.c", "cache", game.name, out.name, key.name))
        check(not left, "a write left %s" % left)
    print("ok: a write cut at the disk's end keeps the last good file and its key, nothing left beside them; a later write "
          "replaces both")


if __name__ == "__main__":
    main()
