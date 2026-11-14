/* Windows Builder home protocol. No cwd discovery, installation, UI or process launch here.
   The app uses the same marker format (BuilderHome.cs). */
#ifndef HOOKSHOT_PORTABLE_HOME_H
#define HOOKSHOT_PORTABLE_HOME_H
#include <windows.h>
#include <string.h>
#include <wchar.h>

#define HB_HOME_MARKER L".hookshot-portable"
#define HB_HOME_MAGIC "Hookshot Builder portable home v1"
/* --portable's home beside the setup. Not HookshotBuilder: that is the builder the zip carries, beside the setup too, which the
   setup copies into the home's versions\<tag>; a home of that name would be copied into itself */
#define HB_HOME_FOLDER L"HookshotBuilder-data"

typedef struct { wchar_t root[MAX_PATH]; int portable; } HbHome;

static int hb_home_full(wchar_t *out, const wchar_t *path) {
    if (!path || !*path) return 0;
    const int drive = ((path[0] >= L'A' && path[0] <= L'Z') || (path[0] >= L'a' && path[0] <= L'z')) &&
                      path[1] == L':' && (path[2] == L'\\' || path[2] == L'/');
    int unc = (path[0] == L'\\' || path[0] == L'/') && (path[1] == L'\\' || path[1] == L'/') &&
              path[2] && path[2] != L'?' && path[2] != L'.';
    if (unc) {
        const wchar_t *share = wcspbrk(path + 2, L"\\/");
        unc = share && share > path + 2 && share[1] && share[1] != L'\\' && share[1] != L'/';
    }
    if (!drive && !unc) return 0;
    DWORD n = GetFullPathNameW(path, MAX_PATH, out, NULL);
    if (!n || n >= MAX_PATH) return 0;
    while (n > 3 && (out[n - 1] == L'\\' || out[n - 1] == L'/')) out[--n] = 0;
    return 1;
}

static int hb_home_join(wchar_t *out, size_t cap, const wchar_t *root, const wchar_t *name) {
    const size_t a = wcslen(root), b = wcslen(name);
    if (a + b + 2 > cap) return 0;
    memcpy(out, root, a * sizeof *out);
    out[a] = L'\\';
    memcpy(out + a + 1, name, (b + 1) * sizeof *out);
    return 1;
}

static int hb_home_volume(const wchar_t *path) {
    if (wcslen(path) == 3 && path[1] == L':') return 1;
    if (path[0] == L'\\' && path[1] == L'\\') {
        const wchar_t *share = wcschr(path + 2, L'\\');
        return share && !wcschr(share + 1, L'\\');
    }
    return 0;
}

static int hb_home_parent(wchar_t *path) {
    if (hb_home_volume(path)) return 0;
    wchar_t *last = wcsrchr(path, L'\\');
    if (!last) return 0;
    if (last == path + 2 && path[1] == L':') last[1] = 0;
    else *last = 0;
    return 1;
}

/* 0 missing, 1 read (including an empty file), -1 unreadable. Reads at most cap bytes, including oversized input. */
static int hb_home_bytes(const wchar_t *path, char *bytes, DWORD cap, DWORD *length) {
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                              NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) {
        DWORD why = GetLastError();
        return why == ERROR_FILE_NOT_FOUND || why == ERROR_PATH_NOT_FOUND ? 0 : -1;
    }
    DWORD have = 0;
    while (have < cap) {
        DWORD got = 0;
        if (!ReadFile(file, bytes + have, cap - have, &got, NULL)) { CloseHandle(file); return -1; }
        if (!got) break;
        have += got;
    }
    CloseHandle(file);
    *length = have;
    return 1;
}

/* The ASCII magic is exact, with up to CR/LF at its end; malformed, inaccessible and oversized markers never mean default. */
static int hb_home_marked(const wchar_t *root) {
    wchar_t path[MAX_PATH];
    char bytes[sizeof HB_HOME_MAGIC + 2];
    DWORD n = 0;
    if (!hb_home_join(path, MAX_PATH, root, HB_HOME_MARKER)) return -1;
    int read = hb_home_bytes(path, bytes, sizeof bytes, &n);
    if (read != 1) return read;
    const DWORD magic = sizeof HB_HOME_MAGIC - 1;
    if (n > magic + 2) return -1;
    while (n && (bytes[n - 1] == '\r' || bytes[n - 1] == '\n')) n--;
    return n == magic && !memcmp(bytes, HB_HOME_MAGIC, magic) && !hb_home_volume(root) ? 1 : -1;
}

/* Caller creates the dedicated home first. Existing marker data is validated, never overwritten. */
static int hb_home_mark(const wchar_t *root) {
    if (hb_home_volume(root)) return 0;
    int was = hb_home_marked(root);
    if (was) return was == 1;
    wchar_t path[MAX_PATH];
    if (!hb_home_join(path, MAX_PATH, root, HB_HOME_MARKER)) return 0;
    HANDLE file = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return hb_home_marked(root) == 1;
    const char text[] = HB_HOME_MAGIC "\n";
    DWORD wrote = 0;
    int ok = WriteFile(file, text, sizeof text - 1, &wrote, NULL) && wrote == sizeof text - 1;
    CloseHandle(file);
    return ok;
}

static int hb_home_discover(HbHome *home, const wchar_t *requested, const wchar_t *exe, const wchar_t *standard) {
    memset(home, 0, sizeof *home);
    HbHome found = {{0}, 0};
    if (requested && *requested) {
        if (!hb_home_full(found.root, requested)) return 0;
        int marked = hb_home_marked(found.root);
        if (marked < 0) return 0;
        found.portable = marked;
        *home = found;
        return 1;
    }
    wchar_t directory[MAX_PATH], setup_directory[MAX_PATH];
    if (!hb_home_full(directory, exe) || !hb_home_parent(directory)) return 0;
    wcscpy(setup_directory, directory);
    for (int depth = 0; depth <= 3; depth++) {
        int marked = hb_home_marked(directory);
        if (marked < 0) return 0;
        if (marked) { wcscpy(home->root, directory); home->portable = 1; return 1; }
        if (!hb_home_parent(directory)) break;
    }
    /* The original setup remains beside its dedicated data folder after --portable's first invocation. */
    {
        wchar_t sibling[MAX_PATH];
        if (hb_home_join(sibling, MAX_PATH, setup_directory, HB_HOME_FOLDER)) {
            int marked = hb_home_marked(sibling);
            if (marked < 0) return 0;
            if (marked) { wcscpy(home->root, sibling); home->portable = 1; return 1; }
        }
    }
    if (!hb_home_full(found.root, standard)) return 0;
    *home = found;
    return 1;
}
#endif
