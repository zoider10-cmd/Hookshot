"""The host's own allocations at Windows' commit limit (issue 333). A malloc or calloc in the NVN layer that failed at the
limit ended the game at once ("FATAL: native NVN: recording handle set"), with no wait and no out-of-memory notice. Now
hos_xmalloc / hos_xcalloc / hos_xrealloc (host/mkw_glue.c) wait for commit as a guest commit does, then say out of
memory, show the notice and only then stop.

Compiles the real hos_out_of_memory, hos_alloc_failed and hos_alloc_gave_up (its end, shared with the renderer's C++
allocations since issue 1280) and the pieces around them cut out of host/mkw_glue.c with
tests/host_alloc_wait_test.c's fake malloc, clock and notice, twice: the cut code's Windows side (page file wording,
GlobalMemoryStatusEx) and its Linux side (swap wording, sysinfo), on either host. Each case in its own process:

- recovers: refused three times, allocated 150 ms on, logged; realloc keeps the old block while it waits; no notice;
- limit: never given: 5 s of tries, the line, the notice (on a thread of its own: on the game's thread MessageBoxA
  showed nothing) waited for until it is closed, then the fatal that says out of memory; a guest commit refused after says nothing again;
- commit-first: a guest commit's notice already up on its own thread: the fatal waits until it is closed;
- not-limit: refused with plenty of commit left: no notice, the fatal says how much was left;
- overflow: calloc's count x size past size_t: the fatal at once, no wait;
- headless: HOS_HEADLESS shows no notice and so waits for none;
- no-thread: the notice's thread refused too (its own memory): no notice, no wait, still the fatal;
- test-switch: HOS_TEST_ALLOC_REFUSE refuses that label as at the limit, and no other.
- renderer, renderer-not-limit, renderer-switch (issue 1280): hos_alloc_gave_up with no size, as the renderer's new_handler
  calls it through MkwVkHost out_of_memory after its own 5 s: the line, the notice and the fatal with no byte count; no notice
  with plenty of commit left; and HOS_TEST_ALLOC_REFUSE=renderer taken as the limit.

And Linux's real thread_new and CreateThread (host/posix/win32_posix.c) cut out with tests/posix_thread_oom_test.c's
refusing calloc: NULL and ERROR_NOT_ENOUGH_MEMORY, not a write through NULL, so no-thread is what Linux does.

And by text: hos_commit's and the first-touch handler's failure (commit_refused) still go through the same notice, and
the NVN layer's and the video service's allocations go through the helpers, with no die() or hos_fatal() of their own
on a NULL.

python -I -B tests/test_host_alloc_wait.py [--cc gcc]
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
CASES = ("recovers", "limit", "commit-first", "not-limit", "overflow", "headless", "no-thread", "test-switch", "renderer",
         "renderer-not-limit", "renderer-switch")


def block(text, head):
    at = text.find(head)
    if at < 0:
        raise SystemExit("FAIL: not found: " + head)
    depth, i = 0, text.index("{", at)
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[at:j + 1]
    raise SystemExit("FAIL: unbalanced: " + head)


def check_sites():
    glue = (ROOT / "host/mkw_glue.c").read_text(encoding="utf-8")
    refused = block(glue, "static void commit_refused(uint64_t lo, uint64_t size, DWORD err)")
    if "hos_out_of_memory(0)" not in refused:
        raise SystemExit("FAIL: commit_refused does not say out of memory through hos_out_of_memory")
    nvn = (ROOT / "host/nvn_native.c").read_text(encoding="utf-8")
    for head, helper in (("static cmd_rec *cmd_adopt(", "hos_xcalloc("), ("static void cmd_release(", "hos_xrealloc("),
                         ("static void live_handle_add(", "hos_xcalloc("), ("static void pins_grow(", "hos_xcalloc("),
                         ("static void *pool_get(", "hos_xmalloc(")):
        body = block(nvn, head)
        if helper not in body or re.search(r"\b(malloc|calloc|realloc)\(", body):
            raise SystemExit("FAIL: %s allocates without %s" % (head, helper))
    if nvn.count("hos_xmalloc(") != 3 or "hos_xmalloc(" not in block(nvn, "static void live_handle_add("):
        raise SystemExit("FAIL: pool_get's two mallocs and live_handle_add's published table are not all hos_xmalloc")
    for head in ("static void cmd_reserve_rec(", "static uint8_t *flatten("):
        body = block(nvn, head)
        if "pool_get(" not in body or re.search(r"if \(!\w+\) die\(", body):
            raise SystemExit("FAIL: %s checks pool_get for NULL (it never is) or does not use it" % head)
    leftover = re.findall(r"if \(!\w+\) die\(\"(?:command buffer table|recording|texture copies)[^\n]*", nvn)
    if leftover:
        raise SystemExit("FAIL: an allocation in nvn_native.c still dies on NULL: " + leftover[0])
    video = (ROOT / "host/nn_video.c").read_text(encoding="utf-8")
    if "hos_fatal(NULL, \"video: out of memory" in video or video.count("hos_x") < 2:
        raise SystemExit("FAIL: nn_video.c's decoder table and image pool do not use the helpers")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    check_sites()
    glue = (ROOT / "host/mkw_glue.c").read_text(encoding="utf-8")
    pieces = [block(glue, head) for head in (
        "static DWORD WINAPI oom_box(LPVOID unused)", "void hos_out_of_memory(int wait)",
        "static int alloc_refused(const char *what)", "static void *alloc_try(",
        "void hos_alloc_gave_up(size_t n, const char *what)",   # (issue 1280: before its caller, as hos.h declares it)
        "void *hos_alloc_failed(int kind,", "void *hos_xmalloc(size_t size, const char *what)",
        "void *hos_xcalloc(size_t count, size_t size, const char *what)",
        "void *hos_xrealloc(void *old, size_t size, const char *what)")]
    win32 = (ROOT / "host/posix/win32_posix.c").read_text(encoding="utf-8")
    at = win32.find("typedef struct {\n    HObj h;\n    pthread_t th;")
    end = win32.find("} HThread;", at)
    if at < 0 or end < 0:
        raise SystemExit("FAIL: win32_posix.c's HThread is not where the fixture reads it")
    posix = [win32[at:end + len("} HThread;")], block(win32, "static HThread *thread_new(void)"),
             block(win32, "HANDLE CreateThread(void *attr, SIZE_T stack,")]
    if "static volatile LONG oom_state;" not in glue:
        raise SystemExit("FAIL: oom_state is not the static the fixture stands in for")
    cc = shutil.which(args.cc)
    if not cc:
        raise SystemExit("test_host_alloc_wait: no C compiler %r (pass --cc)" % args.cc)
    flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="host-alloc-wait-") as temporary:
        folder = Path(temporary)
        (folder / "host_alloc_wait.inc").write_text("\n".join(pieces) + "\n", encoding="utf-8")
        (folder / "posix_thread_oom.inc").write_text("\n".join(posix) + "\n", encoding="utf-8")
        runs = []
        for side in ("windows", "linux"):
            executable = folder / ("fixture-%s.exe" % side)
            subprocess.run([cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-DFIXTURE_LINUX=%d" % (side == "linux"),
                            "-I", str(folder), str(ROOT / "tests/host_alloc_wait_test.c"), "-o", str(executable)],
                           check=True, creationflags=flags)
            runs += [(side, executable, case) for case in CASES]
        executable = folder / "posix-thread.exe"
        subprocess.run([cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-I", str(folder),
                        str(ROOT / "tests/posix_thread_oom_test.c"), "-o", str(executable)], check=True, creationflags=flags)
        runs.append(("linux", executable, "posix-thread"))
        for side, executable, case in runs:
            result = subprocess.run([str(executable), case], capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=30, creationflags=flags)
            print("%s: %s" % (side, result.stdout), end="")
            if result.returncode:
                print(result.stderr, end="", file=sys.stderr)
                raise SystemExit("FAIL: %s case %s (exit %d)" % (side, case, result.returncode))
    print("PASS: a host allocation at the commit limit waits, then says out of memory and shows the notice before it stops")


if __name__ == "__main__":
    main()
