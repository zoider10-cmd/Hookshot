"""A game started from its icon writes its log to logs/hookshot_log.txt (host/hos_main.c, game_main): stderr is opened
again on that file. When the file cannot be opened (a logs/ folder left by a run as root, a read-only game folder),
the game keeps the stderr it was started with: the C library's freopen closes stderr when its open fails, and the
next file the game opened (the guest memory's memfd) then took its descriptor, 2.

The code is cut out of hos_main.c and run with stubs for the Windows calls it makes. The log's path is made unopenable
by a file named logs where the folder would be, which no user, root included, can open a file under; the fixture checks
that before it runs the code. A second run with a real logs/ folder checks that the log is opened there at all.

python -I -B tests/test_log_open_failure.py [--cc gcc]
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_SKIP = {"windows": "the fixture checks POSIX file descriptors: the code is the same on Windows"}

ROOT = Path(__file__).resolve().parents[1]

START = "HANDLE err = GetStdHandle(STD_ERROR_HANDLE);"
END = "} else hos_crash_record_prepare(NULL);"

FIXTURE = r'''#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#define MAX_PATH 4096
typedef unsigned long DWORD;
typedef void *HANDLE;
#define STD_ERROR_HANDLE ((DWORD)-12)
#define INVALID_HANDLE_VALUE ((HANDLE)-1)
#define FILE_TYPE_UNKNOWN 0
#define INVALID_FILE_ATTRIBUTES ((DWORD)-1)
#define MOVEFILE_REPLACE_EXISTING 1
#define CHECK(x) do { if (!(x)) { printf("FAIL: %s (%s)\n", #x, why); return 1; } } while (0)
static const char *game_exe;
static int startup_stderr = -1;
static HANDLE GetStdHandle(DWORD which) { (void)which; return (HANDLE)&startup_stderr; }
static DWORD GetFileType(HANDLE h) { (void)h; return FILE_TYPE_UNKNOWN; }   /* (started from an icon: /dev/null) */
static DWORD hos_game_path_a(char *out, DWORD size) { snprintf(out, size, "%s", game_exe); return (DWORD)strlen(out); }
static DWORD GetFileAttributesA(const char *p) { struct stat st; return stat(p, &st) ? INVALID_FILE_ATTRIBUTES : 0; }
static int MoveFileExA(const char *from, const char *to, DWORD flags) { (void)flags; return rename(from, to) == 0; }
static void hos_crash_record_prepare(const char *log_path) { (void)log_path; }
static void open_log(void) {
''' + "{body}" + r'''
}
int main(int argc, char **argv) {
    const char *why = "";
    game_exe = argv[1];
    const int unopenable = !strcmp(argv[2], "unopenable");
    char log[MAX_PATH];
    snprintf(log, sizeof log, "%s", game_exe);
    *strrchr(log, '/') = 0;
    strcat(log, "/logs/hookshot_log.txt");
    const int null = open("/dev/null", O_WRONLY);   /* (stderr as a desktop launcher leaves it) */
    why = "set up";
    CHECK(null >= 0 && dup2(null, 2) == 2 && close(null) == 0);
    if (unopenable) {
        FILE *f = fopen(log, "w");
        why = "the log must not be openable for this case";
        CHECK(!f && errno == ENOTDIR);
    }
    open_log();
    fprintf(stderr, "the line after\n");
    fflush(stderr);
    if (unopenable) {
        why = "stderr was closed: the next file the game opens takes descriptor 2";
        CHECK(fcntl(2, F_GETFD) != -1);
        const int next = open("/dev/null", O_RDONLY);
        CHECK(next != 2);
        printf("PASS: an unopenable log leaves the stderr the game was started with\n");
    } else {
        FILE *f = fopen(log, "r");
        char line[64] = "";
        why = "the log was not opened in logs/";
        CHECK(f && fgets(line, sizeof line, f) && !strcmp(line, "the line after\n"));
        printf("PASS: the log is opened in logs/\n");
    }
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()
    text = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    start = text.index(START)
    end = text.index(END, start) + len(END)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "fixture.c"
        src.write_text(FIXTURE.replace("{body}", text[start:end]), encoding="utf-8")
        exe = tmp / "fixture"
        subprocess.run([a.cc, "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Werror", str(src), "-o", str(exe)],
                       check=True)
        failed = 0
        for case in ("openable", "unopenable"):
            game = tmp / case
            game.mkdir()
            if case == "openable":
                (game / "logs").mkdir()
            else:
                (game / "logs").write_text("a file where the logs folder would be\n", encoding="utf-8")
            r = subprocess.run([str(exe), str(game / "hookshot"), case], stdout=subprocess.PIPE, text=True)
            print(r.stdout.strip())
            failed |= r.returncode != 0
        raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
