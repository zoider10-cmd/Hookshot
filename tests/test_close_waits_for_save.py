"""Closing the game waits for a file the game is writing, so a save in progress is not cut short (host/nn_fs.c,
host/hos_relaunch.c).

nn::fs::Commit is nothing here: a save goes straight into its files. Every close (the window, the control bridge's
quit, the Windows stop worker) runs hos_close_finish, which waits up to 3 s while a file open for writing was written in
the last second. The wait in host/nn_fs.c is compiled with a made-up clock and checked:

- nothing open for writing, or a file open for writing but not written for a second: no wait;
- a write 100 ms ago, then nothing: the close waits until a second after that write, and logs it;
- a write that goes on: the close stops waiting at 3 s;
- OpenFile counts a file opened for writing, CloseFile uncounts it, WriteFile and SetFileSize mark a write.

python -I -B tests/test_close_waits_for_save.py [--cc gcc]
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
from srccut import block, between   # noqa: E402

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static int64_t now_ns = 5000000000LL, write_every_ns, next_write_ns;
static int sleeps, logs;
static char last_log[256];
static void wrote_now(void);
int64_t hos_now_ns(void) { return now_ns; }
void hos_sleep_ns(int64_t ns) {   /* (the game's threads go on meanwhile: one may write again) */
    sleeps++;
    now_ns += ns;
    if (write_every_ns && now_ns >= next_write_ns) next_write_ns = now_ns + write_every_ns, wrote_now();
}
void hos_log(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(last_log, sizeof last_log, fmt, ap);
    va_end(ap);
    logs++;
}
/* NN_FS_WRITES */
int main(void) {
    hos_fs_wait_writes();
    assert(!sleeps && !logs);   /* nothing open for writing */

    writes_open = 1;
    wrote_now();
    now_ns += 2000000000LL;
    hos_fs_wait_writes();
    assert(!sleeps && !logs);   /* open for writing, written 2 s ago */

    wrote_now();
    now_ns += 100000000LL;
    int64_t t0 = now_ns;
    hos_fs_wait_writes();
    assert(logs == 1 && now_ns - t0 >= 890000000LL && now_ns - t0 <= 920000000LL);

    write_every_ns = 50000000LL, next_write_ns = 0, logs = 0;
    wrote_now();
    t0 = now_ns;
    hos_fs_wait_writes();
    assert(logs == 1 && now_ns - t0 >= 3000000000LL && now_ns - t0 <= 3020000000LL);

    writes_open = 0, write_every_ns = 0, sleeps = logs = 0;
    wrote_now();
    hos_fs_wait_writes();
    assert(!sleeps && !logs);   /* written just now, but closed */
    puts("ok");
    return 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    relaunch = (ROOT / "host/hos_relaunch.c").read_text(encoding="utf-8")
    finish = block(relaunch, "void hos_close_finish(void) {")
    if "hos_fs_wait_writes();" not in finish or finish.index("hos_fs_wait_writes();") > finish.index("hos_log_flush();"):
        raise SystemExit("closing does not wait for a file the game is writing (host/hos_relaunch.c hos_close_finish)")

    fs = (ROOT / "host/nn_fs.c").read_text(encoding="utf-8")
    opened = block(fs, "HLE(_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci) {")
    if "if (want_write) __atomic_add_fetch(&writes_open, 1, __ATOMIC_RELAXED);" not in opened:
        raise SystemExit("OpenFile does not count a file opened for writing")
    closed = block(fs, "HLE(_ZN2nn2fs9CloseFileENS0_10FileHandleE) {")
    if "if (fh->writable) __atomic_sub_fetch(&writes_open, 1, __ATOMIC_RELAXED);" not in closed:
        raise SystemExit("CloseFile does not uncount a file opened for writing")
    write = block(fs, "HLE(_ZN2nn2fs9WriteFileENS0_10FileHandleElPKvmRKNS0_11WriteOptionE) {")
    at = write.index("WriteFile(fh->h,")
    if "wrote_now();" not in write[:at] or "wrote_now();" not in write[at:]:
        raise SystemExit("WriteFile does not mark a write before and after it")
    size = block(fs, "HLE(_ZN2nn2fs11SetFileSizeENS0_10FileHandleEl) {")
    if "wrote_now();" not in size or size.index("wrote_now();") > size.index("SetEndOfFile("):
        raise SystemExit("SetFileSize does not mark a write")

    with tempfile.TemporaryDirectory(prefix="longshot-close-waits-") as temp:
        src, exe = Path(temp) / "close_waits.c", Path(temp) / "close_waits.exe"
        src.write_text(HARNESS.replace("/* NN_FS_WRITES */", between(fs, "static int writes_open;", "/* ---- mounts")),
                       encoding="utf-8")
        subprocess.run([args.cc, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", str(src), "-o", str(exe)],
                       check=True, timeout=120)
        out = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    if out.returncode or out.stdout.strip() != "ok":
        raise SystemExit("the close's wait for a write: %s%s" % (out.stdout, out.stderr))
    print("PASS: closing waits up to 3 s for a file the game is writing")


if __name__ == "__main__":
    main()
