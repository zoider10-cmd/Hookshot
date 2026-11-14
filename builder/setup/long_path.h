/* The setup's paths past MAX_PATH: copy_part_tree and rmtree walk trees (the builder zip's, a version's) whose files can lie
   deeper than 260 characters (the builder zip's deepest file is 163 characters below its folder). An absolute path gets the
   \\?\ form (\\?\UNC\ for a share), which Windows' file calls take up to 32767 characters; the trees are walked in one
   heap buffer per side, a name appended in place and cut off again.
   Include after windows.h (or a stand-in for its file calls: tests/test_setup_tool_merge.py). */
#ifndef HOOKSHOT_LONG_PATH_H
#define HOOKSHOT_LONG_PATH_H
#include <stdlib.h>
#include <wchar.h>

enum {
    LONG_PATH = 32768,   /* (characters in a long-path buffer: the \\?\ form's limit and its terminating 0) */
    TREE_DEPTH = 256     /* (folders below the top a walk goes into: a stack bound, real trees are about 20 deep) */
};

/* path in the \\?\ form, into out (LONG_PATH characters). Its length, 0 when it does not fit.
   Every caller's path comes from GetModuleFileNameW or GetFullPathNameW (hb_home_full, and the names derived from them), so
   / is already \, and . and .. parts and trailing dots and spaces are already resolved: the prefix turns that normalization
   off, it does not do it. A path like C:/x or C:\x\..\y would be taken literally, and a device path (\\.\) would be
   mistaken for a share: neither reaches here. A path already in the \\?\ form is kept, and a path neither absolute nor a
   share (a POSIX test's) is kept as it is. A trailing \ is removed, except a drive root's (\\?\C: is the volume, not its
   root folder). */
static size_t long_path(wchar_t *out, const wchar_t *path) {
    const wchar_t *prefix = L"", *rest = path;
    if (wcsncmp(path, L"\\\\?\\", 4)) {
        if (path[0] && path[1] == L':' && path[2] == L'\\') prefix = L"\\\\?\\";
        else if (path[0] == L'\\' && path[1] == L'\\') prefix = L"\\\\?\\UNC", rest = path + 1;
    }
    size_t n = wcslen(prefix) + wcslen(rest);
    if (!*path || n >= LONG_PATH) return 0;
    wcscpy(out, prefix), wcscat(out, rest);
    while (n > 1 && out[n - 1] == L'\\' && out[n - 2] != L':') out[--n] = 0;
    return n;
}

/* name appended to the n characters of p, with a \ unless p ends with one (a drive root). The new length, 0 when it does not
   fit (p unchanged). p[n] = 0 cuts it off again. */
static size_t long_join(wchar_t *p, size_t n, const wchar_t *name) {
    const size_t sep = n && p[n - 1] != L'\\', k = wcslen(name);
    if (n + sep + k >= LONG_PATH) return 0;
    if (sep) p[n] = L'\\';
    wmemcpy(p + n + sep, name, k + 1);
    return n + sep + k;
}

/* 1 when path (n characters) is folder (m characters) or lies under it: both from long_path, compared without case as
   Windows' file names are. ...\HookshotBuilder2 is not under ...\HookshotBuilder. Only the spelling is compared: the same
   folder named another way (a mapped drive and its share, a short 8.3 name, a link) is not seen. */
static int long_within(const wchar_t *path, size_t n, const wchar_t *folder, size_t m) {
    if (!m || n < m || CompareStringOrdinal(path, (int)m, folder, (int)m, TRUE) != CSTR_EQUAL) return 0;
    return n == m || path[m] == L'\\' || folder[m - 1] == L'\\';
}
#endif
