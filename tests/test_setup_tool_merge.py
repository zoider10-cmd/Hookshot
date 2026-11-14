"""The Windows setup (builder/setup/setup.c) installs tools.lock's third-party tool into the builder's own
HookshotBuilder/tools/third_party: the release zip has that folder already (the repository's third_party sources,
scripts/builder_package.py), and the tool's archive holds only the prebuilt files that go among them (a64emit.dll,
SDL3.dll, ..., scripts/tools.py assemble third-party). The tool's files are merged in, file by file; a file both have is
refused and never replaced; an installed version's third_party (sources and tool together) is never moved or copied onto
the new one, which in a portable home used to remove the new one's sources on the failed copy.

A fake builder zip (builder_package.make_zip) and a fake third-party archive (tools.assemble_third_party) are unpacked
the way the setup's tar.exe would unpack them (zipfile here), then the setup's own place_tool and reuse_part, cut out of
setup.c, run over them: compiled against windows.h on Windows, and against a small POSIX stand-in for the Win32 file
calls they make on Linux (no Wine needed). No game data, no network.

Run with: python -I tests/test_setup_tool_merge.py [--cc gcc]
"""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def function(source, marker):
    start = source.index(marker)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


# (the Win32 file calls place_tool, reuse_part and the helpers they use make, over POSIX: '\\' becomes '/'. MoveFileW and
# CopyFileW(..., TRUE) refuse an existing target, as Windows' do; a symbolic link is a reparse point)
POSIX_WIN32 = r'''
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <wchar.h>
#include <stdarg.h>
typedef unsigned long DWORD;
typedef int BOOL;
typedef void *HANDLE;
typedef const wchar_t *LPCWSTR;
#define TRUE 1
#define FALSE 0
#define MAX_PATH 260
#define INVALID_HANDLE_VALUE ((HANDLE)(intptr_t)-1)
#define INVALID_FILE_ATTRIBUTES 0xFFFFFFFFul
#define FILE_ATTRIBUTE_DIRECTORY 0x10ul
#define FILE_ATTRIBUTE_NORMAL 0x80ul
#define FILE_ATTRIBUTE_REPARSE_POINT 0x400ul
#define ERROR_FILE_NOT_FOUND 2
#define ERROR_ACCESS_DENIED 5
#define ERROR_NO_MORE_FILES 18
#define ERROR_ALREADY_EXISTS 183
#define GENERIC_READ 0x80000000ul
#define FILE_SHARE_READ 1
#define OPEN_EXISTING 3
typedef struct { DWORD dwFileAttributes; wchar_t cFileName[MAX_PATH]; } WIN32_FIND_DATAW;
typedef struct { wchar_t root[MAX_PATH]; int portable; } HbHome;
static DWORD last_error;
static DWORD GetLastError(void) { return last_error; }
static void SetLastError(DWORD e) { last_error = e; }
static void u8(const wchar_t *w, char *out) {
    size_t n = wcstombs(out, w, 4 * MAX_PATH - 1);
    if (n == (size_t)-1) n = 0;
    out[n] = 0;
    for (char *q = out; *q; q++) if (*q == '\\') *q = '/';
}
static int failed(void) { last_error = errno == ENOENT ? ERROR_FILE_NOT_FOUND : errno == EEXIST ? ERROR_ALREADY_EXISTS : ERROR_ACCESS_DENIED; return 0; }
static DWORD GetFileAttributesW(LPCWSTR path) {
    char p[4 * MAX_PATH]; struct stat st;
    u8(path, p);
    if (lstat(p, &st)) return failed(), INVALID_FILE_ATTRIBUTES;
    if (S_ISLNK(st.st_mode)) return FILE_ATTRIBUTE_REPARSE_POINT | (stat(p, &st) == 0 && S_ISDIR(st.st_mode) ? FILE_ATTRIBUTE_DIRECTORY : 0);
    return S_ISDIR(st.st_mode) ? FILE_ATTRIBUTE_DIRECTORY : FILE_ATTRIBUTE_NORMAL;
}
static BOOL MoveFileW(LPCWSTR from, LPCWSTR to) {
    char a[4 * MAX_PATH], b[4 * MAX_PATH]; struct stat st;
    u8(from, a), u8(to, b);
    if (!lstat(b, &st)) { last_error = ERROR_ALREADY_EXISTS; return FALSE; }
    return rename(a, b) ? failed() : TRUE;
}
static BOOL CopyFileW(LPCWSTR from, LPCWSTR to, BOOL fail_if_exists) {
    char a[4 * MAX_PATH], b[4 * MAX_PATH], buf[65536]; ssize_t n;
    u8(from, a), u8(to, b);
    int in = open(a, O_RDONLY), out = in < 0 ? -1 : open(b, O_WRONLY | O_CREAT | (fail_if_exists ? O_EXCL : O_TRUNC), 0644);
    if (out < 0) { if (in >= 0) close(in); return failed(); }
    while ((n = read(in, buf, sizeof buf)) > 0) if (write(out, buf, (size_t)n) != n) { n = -1; break; }
    close(in), close(out);
    return n == 0;
}
static BOOL CreateDirectoryW(LPCWSTR path, void *sa) { char p[4 * MAX_PATH]; (void)sa; u8(path, p); return mkdir(p, 0755) ? failed() : TRUE; }
static BOOL RemoveDirectoryW(LPCWSTR path) { char p[4 * MAX_PATH]; u8(path, p); return rmdir(p) ? failed() : TRUE; }
static BOOL DeleteFileW(LPCWSTR path) { char p[4 * MAX_PATH]; u8(path, p); return unlink(p) ? failed() : TRUE; }
static BOOL SetFileAttributesW(LPCWSTR path, DWORD a) { (void)path, (void)a; return TRUE; }
typedef struct { DIR *dir; char base[4 * MAX_PATH]; } Find;
static BOOL FindNextFileW(HANDLE h, WIN32_FIND_DATAW *fd) {
    Find *f = (Find *)h;
    struct dirent *e = readdir(f->dir);
    if (!e) { last_error = ERROR_NO_MORE_FILES; return FALSE; }
    mbstowcs(fd->cFileName, e->d_name, MAX_PATH - 1);
    fd->cFileName[MAX_PATH - 1] = 0;
    char p[8 * MAX_PATH]; struct stat st;
    snprintf(p, sizeof p, "%s/%s", f->base, e->d_name);
    fd->dwFileAttributes = lstat(p, &st) ? 0 : S_ISLNK(st.st_mode) ? FILE_ATTRIBUTE_REPARSE_POINT : S_ISDIR(st.st_mode) ? FILE_ATTRIBUTE_DIRECTORY : FILE_ATTRIBUTE_NORMAL;
    return TRUE;
}
static HANDLE FindFirstFileW(LPCWSTR pattern, WIN32_FIND_DATAW *fd) {
    Find *f = (Find *)calloc(1, sizeof *f);
    u8(pattern, f->base);
    char *star = strrchr(f->base, '/');
    if (!star || strcmp(star, "/*")) { free(f); last_error = ERROR_FILE_NOT_FOUND; return INVALID_HANDLE_VALUE; }
    *star = 0;
    if (!(f->dir = opendir(f->base))) { free(f); failed(); return INVALID_HANDLE_VALUE; }
    if (!FindNextFileW(f, fd)) { closedir(f->dir), free(f); last_error = ERROR_FILE_NOT_FOUND; return INVALID_HANDLE_VALUE; }
    return f;
}
static BOOL FindClose(HANDLE h) { Find *f = (Find *)h; closedir(f->dir), free(f); return TRUE; }
#define CSTR_EQUAL 2
#include <wctype.h>
static int CompareStringOrdinal(const wchar_t *a, int na, const wchar_t *b, int nb, BOOL ignore_case) {
    if (na != nb) return na < nb ? 1 : 3;
    for (int i = 0; i < na; i++) {
        wint_t x = ignore_case ? towupper((wint_t)a[i]) : (wint_t)a[i], y = ignore_case ? towupper((wint_t)b[i]) : (wint_t)b[i];
        if (x != y) return x < y ? 1 : 3;
    }
    return CSTR_EQUAL;
}
static HANDLE CreateFileW(LPCWSTR path, DWORD access, DWORD share, void *sa, DWORD how, DWORD flags, HANDLE t) {
    char p[4 * MAX_PATH]; (void)access, (void)share, (void)sa, (void)how, (void)flags, (void)t;
    u8(path, p);
    int fd = open(p, O_RDONLY);
    return fd < 0 ? (failed(), INVALID_HANDLE_VALUE) : (HANDLE)(intptr_t)(fd + 1);
}
static BOOL ReadFile(HANDLE h, void *buf, DWORD n, DWORD *got, void *o) {
    (void)o; ssize_t r = read((int)(intptr_t)h - 1, buf, n); *got = r > 0 ? (DWORD)r : 0; return r >= 0;
}
static BOOL CloseHandle(HANDLE h) { return close((int)(intptr_t)h - 1) == 0; }
static int hb_home_join(wchar_t *out, size_t cap, const wchar_t *root, const wchar_t *name) {
    const size_t a = wcslen(root), b = wcslen(name);
    if (a + b + 2 > cap) return 0;
    memcpy(out, root, a * sizeof *out);
    out[a] = L'\\';
    memcpy(out + a + 1, name, (b + 1) * sizeof *out);
    return 1;
}
'''

WINDOWS_HEAD = r'''
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <stdarg.h>
#include "portable_home.h"
#include "long_path.h"
'''

HARNESS = r'''
static HbHome g_home;
static void fail(const wchar_t *format, ...) { (void)format; exit(90); }
/* place <from> <to> <expected> | reuse <versions> <staged install> <portable> <sha> <expected> */
static int run(int argc, wchar_t **argv) {
    if (argc == 5 && !wcscmp(argv[1], L"place")) return place_tool(argv[2], argv[3]) == _wtoi(argv[4]) ? 0 : 21;
    if (argc == 7 && !wcscmp(argv[1], L"reuse")) {
        Part part;
        memset(&part, 0, sizeof part);
        wcstombs(part.sha, argv[5], sizeof part.sha - 1);
        strcpy(part.dest, "HookshotBuilder/tools/third_party"), strcpy(part.from, "third_party");
        strcpy(part.url, "https://invalid.example/third-party.zip");
        g_home.portable = _wtoi(argv[4]);
        return reuse_part(argv[2], "v-new", &part, argv[3]) == _wtoi(argv[6]) ? 0 : 22;
    }
    return 20;
}
#ifdef _WIN32
int wmain(int argc, wchar_t **argv) { return run(argc, argv); }
#else
#include <locale.h>
int main(int argc, char **argv) {
    setlocale(LC_ALL, "C.UTF-8");
    wchar_t *w[8];
    if (argc > 8) return 20;
    for (int i = 0; i < argc; i++) {
        w[i] = (wchar_t *)calloc(4 * 260, sizeof(wchar_t));
        mbstowcs(w[i], argv[i], 4 * 260 - 1);
    }
    return run(argc, w);
}
#define _wtoi(s) ((int)wcstol((s), NULL, 10))
#endif
'''


def harness(source):
    part_end = source.index("} Part;") + len("} Part;")
    code = (WINDOWS_HEAD if WINDOWS else POSIX_WIN32 + '#include "long_path.h"\n#define _wtoi(s) ((int)wcstol((s), NULL, 10))\n')
    code += source[source.rfind("typedef struct", 0, part_end):part_end] + "\n"
    code += "static HbHome g_home;\nstatic void fail(const wchar_t *format, ...);\n"
    for marker in ("static int home_path(", "static void rmtree_at(", "static void rmtree(", "static void mkdirs(", "static void read_small(",
                   "static int part_folder(", "static int copy_tree_at(", "static int copy_part_tree(", "static int place_tool(",
                   "static int reuse_part("):
        code += function(source, marker) + "\n"
    return code + HARNESS.replace("static HbHome g_home;\n", "").replace("#define _wtoi(s) ((int)wcstol((s), NULL, 10))\n", "")


def unpack(archive, into):
    """the setup's tar.exe -xf <zip> -C <folder>"""
    with zipfile.ZipFile(archive) as z:
        z.extractall(into)


def tree(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    source = (ROOT / "builder/setup/setup.c").read_text(encoding="utf-8")
    package = module("builder_package_under_test", ROOT / "scripts/builder_package.py")
    tools = module("tools_under_test", ROOT / "scripts/tools.py")
    third = tools.named(tools.load(), "third-party")
    assert third.dest == "HookshotBuilder/tools/third_party" and third.prefix == "third_party", third.line()
    with tempfile.TemporaryDirectory(prefix="setup-tool-merge-") as folder:
        root = Path(folder)
        c, exe = root / "merge.c", root / "merge.exe"
        c.write_text(harness(source), encoding="utf-8")
        flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-I" + str(ROOT / "builder/setup")]
        subprocess.run([args.cc, *flags, *(["-municode"] if WINDOWS else []), str(c), "-o", str(exe)], check=True)

        def run(*argv):
            r = subprocess.run([str(exe), *map(str, argv)])
            assert r.returncode == 0, "%s: exit %d" % (" ".join(map(str, argv)), r.returncode)

        # (the builder's package: its tracked third_party sources under tools/, as builder_package.py package copies them)
        pkg = root / "package"
        sources = {"third_party/a64-kit/lift/a64emit.cpp": b"// the emitter's source\n",
                   "third_party/a64-kit/lift/build_emit.py": b"# builds a64emit.dll\n",
                   "third_party/sdl2/PROVENANCE.md": b"SDL2 and SDL3, prebuilt\n",
                   "third_party/zbic/zbic.c": b"/* zbic */\n"}
        for rel, data in {"HookshotBuilder.exe": b"MZ builder", **{"tools/" + k: v for k, v in sources.items()}}.items():
            (pkg / rel).parent.mkdir(parents=True, exist_ok=True)
            (pkg / rel).write_bytes(data)
        (root / "setup.exe").write_bytes(b"MZ setup")
        package.make_zip(str(pkg), "v3.0.0-test", str(root / "setup.exe"), str(root / "builder.zip"))
        # (the third-party tool: Hookshot's third_party part, with sources, made into the prebuilt files only)
        prebuilt = {"a64-kit/lift/a64emit.dll": b"MZ a64emit", "a64-kit/tools/lld-link.exe": b"MZ lld-link",
                    "sdl2/SDL2.dll": b"MZ SDL2", "sdl2/SDL3.dll": b"MZ SDL3", "zbic/zbic.dll": b"MZ zbic"}
        with zipfile.ZipFile(root / "hookshot-third-party.zip", "w") as z:
            for rel, data in prebuilt.items():
                z.writestr("HookshotBuilder/tools/third_party/" + rel, data)
            z.writestr("HookshotBuilder/tools/third_party/a64-kit/lift/a64emit.cpp", b"// Hookshot's copy, not taken\n")
        tools.assemble_third_party(str(root / "hookshot-third-party.zip"), "HookshotBuilder/tools/third_party",
                                   str(root / "third-party.zip"), set(sources))

        # 1. a fresh install: the builder zip unpacked into the staged version, then the tool merged into its third_party
        staged = root / "versions/v-new.part"
        unpack(root / "builder.zip", staged)
        dest = staged / "HookshotBuilder/tools/third_party"
        assert dest.is_dir(), "the builder zip has no tools/third_party: this test's premise is gone"
        unpack(root / "third-party.zip", staged / ".tool-0")
        run("place", staged / ".tool-0/third_party", dest, 1)
        want = {k[len("third_party/"):]: v for k, v in sources.items()}
        want.update(prebuilt)
        assert tree(dest) == want, sorted(tree(dest))
        assert not [p for p in (staged / ".tool-0").rglob("*") if p.is_file()], "a tool file was left behind"

        # 2. a tool file the builder has already: refused, and the builder's file kept as it was
        clash = root / "clash"
        (clash / "a64-kit/lift").mkdir(parents=True)
        (clash / "a64-kit/lift/a64emit.cpp").write_bytes(b"// not the builder's\n")
        run("place", clash, dest, 0)
        assert (dest / "a64-kit/lift/a64emit.cpp").read_bytes() == sources["third_party/a64-kit/lift/a64emit.cpp"]
        # (a file where the builder has a folder, and the other way round: refused too)
        (root / "file-for-folder").mkdir()
        (root / "file-for-folder/sdl2").write_bytes(b"not a folder")
        run("place", root / "file-for-folder", dest, 0)
        assert (dest / "sdl2").is_dir()
        if not WINDOWS:   # (a link in the tool's folder: refused, never followed)
            (root / "linked/zbic").mkdir(parents=True)
            os.symlink("/etc/hostname", root / "linked/zbic/extra.dll")
            run("place", root / "linked", dest, 0)
            assert not (dest / "zbic/extra.dll").exists()

        # 3. a dest the builder zip lacks: the tool's folder moved whole, as before
        other = root / "other.part"
        unpack(root / "third-party.zip", other / ".tool-1")
        (other / "HookshotBuilder/tools").mkdir(parents=True)   # (the setup's mkdirs of dest's parent)
        run("place", other / ".tool-1/third_party", other / "HookshotBuilder/tools/third_party", 1)
        assert tree(other / "HookshotBuilder/tools/third_party") == prebuilt

        # 4. an update: the installed version (v-old) lists the tool's SHA-256, and its third_party holds its sources too.
        # Never moved or copied onto the new version's own third_party, portable or not, and the new one is kept whole
        versions = root / "versions"
        old = versions / "v-old/HookshotBuilder/tools/third_party"
        (old / "a64-kit/lift").mkdir(parents=True)
        (old / "a64-kit/lift/a64emit.cpp").write_bytes(b"// v-old's source\n")
        (old / "a64-kit/lift/a64emit.dll").write_bytes(b"MZ a64emit")
        (versions / "current.txt").write_text("v-old\n")
        (versions / "v-old/parts.txt").write_text(third.sha256 + "\n")
        before = tree(dest)
        for portable in (1, 0):
            run("reuse", versions, staged, portable, third.sha256, 0)
            assert tree(dest) == before, "portable=%d: the new version's third_party changed" % portable
            assert (old / "a64-kit/lift/a64emit.cpp").read_bytes() == b"// v-old's source\n"
        # (a tool folder the new version does not have yet is still taken from the installed one)
        (versions / "v-old/parts.txt").write_text(third.sha256 + "\n")
        bare = versions / "v-bare.part"
        bare.mkdir()
        run("reuse", versions, bare, 1, third.sha256, 1)
        assert (bare / "HookshotBuilder/tools/third_party/a64-kit/lift/a64emit.dll").read_bytes() == b"MZ a64emit"
    print("setup tool merge: the third-party tool merged into the builder zip's third_party; clashes, links and a reused "
          "folder refused; a fresh dest moved whole")


if __name__ == "__main__":
    main()
