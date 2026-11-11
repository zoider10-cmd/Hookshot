/* (amd-fix, sharkiix version) The update check: at start, the latest release of github.com/Shakoquo/Mako is asked for (a few
   seconds at most, nothing when offline). The official updater (NotRexed's builder --update) is not used: it would build the folder
   again without the AMD fixes.

   A release can carry a GRAPHICS PATCH: two assets
     hookshot_vk.dll         the Vulkan back end + shader translator. It holds no game code (nx2/build.py builds it with no lift,
                             RX_VK_ONLY=1), so it can be shared; hookshot.exe (the game's code) never is.
     hookshot_vk_update.txt  lines name=value: base=<HOOKSHOT_FORK_BASE of the exe it fits>, api=<MKWVK_API_VERSION>,
                             size=<bytes of the dll>
   When base and api match this exe, the player is offered the patch: the dll is downloaded (about 3 MB), checked (size, "MZ"), the
   old one kept as hookshot_vk.prev.dll (host/rx_backend.c falls back to it if the new one does not start), and the game goes on with
   the new one: no rebuild. Otherwise (no patch, or one made for another exe) the player is told a new version needs a rebuild with
   the builder and can open the release page.

   The installed patch's tag is kept in user\hookshot_vk_version.txt (version=...); without it the folder is HOOKSHOT_FORK_VERSION.
   "Cancel" skips that release (user\hookshot_update_skip.txt). HOOKSHOT_NO_UPDATE_CHECK=1 (hookshot_env.txt) turns the check off.

   RELEASING: a full release (anything in host/, nx2/, game patches, vk_api.h, an upstream merge) sets HOOKSHOT_FORK_BASE and
   HOOKSHOT_FORK_VERSION below to the new tag and players rebuild once. A graphics-only fix (gpu/vk/** alone) keeps them, and its
   release (tag = the new version) carries hookshot_vk.dll + hookshot_vk_update.txt with base = HOOKSHOT_FORK_BASE. */
#ifdef _WIN32
#include "hos_paths.h"
#include <windows.h>
#include <winhttp.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../gpu/vk/vk_api.h"   /* (MKWVK_API_VERSION) */

#define HOOKSHOT_FORK_BASE "mako-3.3"      /* (the exe: which graphics patches fit it) */
#define HOOKSHOT_FORK_VERSION "mako-3.3"   /* (the release this folder was built from) */
#define UPDATE_HOST L"api.github.com"
#define UPDATE_PATH L"/repos/Shakoquo/Mako/releases/latest"
#define RELEASES_PAGE L"https://github.com/Shakoquo/Mako/releases/latest"

/* (a line "name=value" of a text buffer: its value, trimmed) */
static int value_in(const char *text, const char *name, char *out, size_t cap) {
    const size_t n = strlen(name);
    for (const char *s = text; s && *s;) {
        if ((unsigned char)s[0] == 0xEF && (unsigned char)s[1] == 0xBB && (unsigned char)s[2] == 0xBF) s += 3;
        const char *eol = strchr(s, '\n');
        const size_t len = eol ? (size_t)(eol - s) : strlen(s);
        if (len > n && !strncmp(s, name, n) && s[n] == '=') {
            size_t v = len - n - 1;
            const char *val = s + n + 1;
            while (v && (val[v - 1] == '\r' || val[v - 1] == ' ' || val[v - 1] == '\t')) v--;
            if (v && v < cap) {
                memcpy(out, val, v);
                out[v] = 0;
                return 1;
            }
            return 0;
        }
        s = eol ? eol + 1 : NULL;
    }
    return 0;
}

static int read_value(const wchar_t *path, const char *name, char *out, size_t cap) {
    FILE *f = _wfopen(path, L"rb");
    if (!f) return 0;
    char buf[4097];
    const size_t got = fread(buf, 1, 4096, f);
    fclose(f);
    buf[got] = 0;
    return value_in(buf, name, out, cap);
}

/* (GET https://host/path: the body, at most max bytes; NULL on any failure. Redirects are followed: release assets go to another host) */
static char *https_get(const wchar_t *host, const wchar_t *path, const wchar_t *headers, size_t max, size_t *out_len, DWORD timeout) {
    char *body = NULL;
    size_t have = 0;
    int ok = 0;
    HINTERNET s = WinHttpOpen(L"Mako-update", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!s) return NULL;
    WinHttpSetTimeouts(s, timeout, timeout, timeout, timeout);
    HINTERNET c = WinHttpConnect(s, host, INTERNET_DEFAULT_HTTPS_PORT, 0);
    HINTERNET r = c ? WinHttpOpenRequest(c, L"GET", path, NULL, WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, WINHTTP_FLAG_SECURE) : NULL;
    if (r && WinHttpSendRequest(r, headers ? headers : WINHTTP_NO_ADDITIONAL_HEADERS, headers ? (DWORD)-1 : 0, WINHTTP_NO_REQUEST_DATA, 0, 0, 0) &&
        WinHttpReceiveResponse(r, NULL)) {
        DWORD status = 0, size = sizeof status;
        WinHttpQueryHeaders(r, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, WINHTTP_HEADER_NAME_BY_INDEX, &status, &size, WINHTTP_NO_HEADER_INDEX);
        if (status == 200 && (body = (char *)malloc(max + 1))) {
            DWORD got = 0;
            ok = 1;
            while (have < max) {
                if (!WinHttpReadData(r, body + have, (DWORD)(max - have), &got)) { ok = 0; break; }
                if (!got) break;
                have += got;
            }
            body[have] = 0;
        }
    }
    if (r) WinHttpCloseHandle(r);
    if (c) WinHttpCloseHandle(c);
    WinHttpCloseHandle(s);
    if (!ok) {
        free(body);
        return NULL;
    }
    if (out_len) *out_len = have;
    return body;
}

/* (a full https URL: split into host and path, then fetched) */
static char *https_get_url(const char *url, size_t max, size_t *out_len) {
    if (strncmp(url, "https://", 8)) return NULL;
    const char *h = url + 8, *p = strchr(h, '/');
    if (!p || p - h >= 255) return NULL;
    wchar_t host[256], path[2048];
    const int hl = MultiByteToWideChar(CP_UTF8, 0, h, (int)(p - h), host, 255);
    if (hl <= 0) return NULL;
    host[hl] = 0;
    if (!MultiByteToWideChar(CP_UTF8, 0, p, -1, path, 2048)) return NULL;
    return https_get(host, path, NULL, max, out_len, 15000);
}

/* (in the release JSON: the browser_download_url of the asset whose name is `name`) */
static int asset_url(const char *json, const char *name, char *out, size_t cap) {
    char want[160];
    const int wl = snprintf(want, sizeof want, "/%s", name);
    for (const char *k = json; (k = strstr(k, "\"browser_download_url\"")); k += 22) {
        const char *q = strchr(k + 22, '"');
        if (!q) return 0;
        const char *e = strchr(q + 1, '"');
        if (!e) return 0;
        const size_t len = (size_t)(e - q - 1);
        if (len < cap && len >= (size_t)wl && !strncmp(e - wl, want, (size_t)wl)) {
            memcpy(out, q + 1, len);
            out[len] = 0;
            return 1;
        }
    }
    return 0;
}

static void skip_release(const wchar_t *dir, const char *tag) {
    wchar_t user[MAX_PATH + 16], file[MAX_PATH + 64];
    _snwprintf(user, MAX_PATH + 16, L"%ls\\user", dir);
    CreateDirectoryW(user, NULL);
    _snwprintf(file, MAX_PATH + 64, L"%ls\\user\\hookshot_update_skip.txt", dir);
    FILE *f = _wfopen(file, L"wb");
    if (f) fprintf(f, "skip=%s\n", tag), fclose(f);
}

/* (the patch: downloaded beside the dll, checked, swapped in; 1 when it is in place) */
static int install_patch(const wchar_t *dir, const char *dll_url, long long want_size, const char *tag) {
    size_t len = 0;
    char *dll = https_get_url(dll_url, 64u << 20, &len);
    if (!dll) return 0;
    if (len < 4096 || dll[0] != 'M' || dll[1] != 'Z' || (want_size > 0 && (long long)len != want_size)) {
        fprintf(stderr, "update: the downloaded hookshot_vk.dll is not right (%zu bytes): left as it was\n", len);
        free(dll);
        return 0;
    }
    wchar_t part[MAX_PATH + 64], cur[MAX_PATH + 64], prev[MAX_PATH + 64], ver[MAX_PATH + 64], user[MAX_PATH + 16];
    _snwprintf(part, MAX_PATH + 64, L"%ls\\hookshot_vk.dll.part", dir);
    _snwprintf(cur, MAX_PATH + 64, L"%ls\\hookshot_vk.dll", dir);
    _snwprintf(prev, MAX_PATH + 64, L"%ls\\hookshot_vk.prev.dll", dir);
    FILE *f = _wfopen(part, L"wb");
    const int written = f && fwrite(dll, 1, len, f) == len;
    if (f) fclose(f);
    free(dll);
    if (!written) {
        DeleteFileW(part);
        return 0;
    }
    /* (an antivirus may hold a new file a moment: a few tries) */
    int moved = GetFileAttributesW(cur) == INVALID_FILE_ATTRIBUTES;
    for (int t = 0; t < 10 && !moved; t++) {
        if (t) Sleep(300);
        moved = MoveFileExW(cur, prev, MOVEFILE_REPLACE_EXISTING);
    }
    if (!moved) {
        DeleteFileW(part);
        return 0;
    }
    int placed = 0;
    for (int t = 0; t < 10 && !placed; t++) {
        if (t) Sleep(300);
        placed = MoveFileExW(part, cur, MOVEFILE_REPLACE_EXISTING);
    }
    if (!placed) {   /* (the old one back) */
        MoveFileExW(prev, cur, MOVEFILE_REPLACE_EXISTING);
        DeleteFileW(part);
        return 0;
    }
    _snwprintf(user, MAX_PATH + 16, L"%ls\\user", dir);
    CreateDirectoryW(user, NULL);
    _snwprintf(ver, MAX_PATH + 64, L"%ls\\user\\hookshot_vk_version.txt", dir);
    if ((f = _wfopen(ver, L"wb"))) fprintf(f, "version=%s\n", tag), fclose(f);
    return 1;
}

void hos_update_check(void) {
    if (getenv("HOOKSHOT_NO_UPDATE_CHECK") && strcmp(getenv("HOOKSHOT_NO_UPDATE_CHECK"), "0")) return;
    wchar_t dir[MAX_PATH], file[MAX_PATH + 64];
    DWORD n = hos_game_path_w(dir, MAX_PATH);
    if (!n || n >= MAX_PATH) return;
    while (n && dir[n - 1] != L'\\' && dir[n - 1] != L'/') n--;
    if (!n) return;
    dir[n - 1] = 0;

    char have[128] = HOOKSHOT_FORK_VERSION, skipped[128] = "", tag[128] = "";
    _snwprintf(file, MAX_PATH + 64, L"%ls\\user\\hookshot_vk_version.txt", dir);
    read_value(file, "version", have, sizeof have);
    _snwprintf(file, MAX_PATH + 64, L"%ls\\user\\hookshot_update_skip.txt", dir);
    read_value(file, "skip", skipped, sizeof skipped);

    char *json = https_get(UPDATE_HOST, UPDATE_PATH, L"Accept: application/vnd.github+json\r\n", 1u << 20, NULL, 3000);
    if (!json) {
        fprintf(stderr, "update: the latest release could not be asked for (offline, or no release yet)\n");
        return;
    }
    const char *k = strstr(json, "\"tag_name\"");
    if (k && (k = strchr(k + 10, '"'))) {
        const char *e = strchr(++k, '"');
        if (e && e > k && (size_t)(e - k) < sizeof tag) memcpy(tag, k, (size_t)(e - k)), tag[e - k] = 0;
    }
    fprintf(stderr, "update: this folder is %s (exe %s), the latest release is %s\n", have, HOOKSHOT_FORK_BASE, tag[0] ? tag : "?");
    if (!tag[0] || !strcmp(tag, have) || !strcmp(tag, skipped)) {
        free(json);
        return;
    }

    /* (a graphics patch for this exe?) */
    char manifest_url[1024], dll_url[1024], base[128] = "", api[32] = "", size[32] = "";
    int patch = 0;
    /* (Mako 3.3: the release files' new names, mako_vk_update.txt + mako_vk.dll, or the old ones that every release up to
       3.0.2 has and that games before 3.3 look for; the file saved beside the exe keeps its name, hookshot_vk.dll) */
    if ((asset_url(json, "mako_vk_update.txt", manifest_url, sizeof manifest_url) &&
         asset_url(json, "mako_vk.dll", dll_url, sizeof dll_url)) ||
        (asset_url(json, "hookshot_vk_update.txt", manifest_url, sizeof manifest_url) &&
         asset_url(json, "hookshot_vk.dll", dll_url, sizeof dll_url))) {
        char *m = https_get_url(manifest_url, 16 << 10, NULL);
        if (m) {
            value_in(m, "base", base, sizeof base);
            value_in(m, "api", api, sizeof api);
            value_in(m, "size", size, sizeof size);
            free(m);
        }
        patch = !strcmp(base, HOOKSHOT_FORK_BASE) && atoi(api) == MKWVK_API_VERSION;
        fprintf(stderr, "update: the release has a graphics patch for exe %s, api %s (%s)\n", base, api,
                patch ? "fits this game" : "not for this game: a rebuild is needed");
    }
    free(json);

    wchar_t wtag[128], whave[128], text[2048];
    MultiByteToWideChar(CP_UTF8, 0, tag, -1, wtag, 128);
    MultiByteToWideChar(CP_UTF8, 0, have, -1, whave, 128);
    if (patch) {
        _snwprintf(text, 2048,
                   L"A graphics update for Mako is out: %ls (this game is %ls).\n\n"
                   L"It is a small download (about 3 MB) and needs NO rebuild. The previous version is kept as a backup.\n"
                   L"The first start after it prepares the shaders again (a few minutes): that is normal.\n\n"
                   L"Yes: update now\nNo: not now (asked again next time)\nCancel: skip this version",
                   wtag, whave);
        const int answer = MessageBoxW(NULL, text, L"Mako update", MB_YESNOCANCEL | MB_ICONINFORMATION | MB_TOPMOST | MB_SETFOREGROUND);
        if (answer == IDCANCEL) skip_release(dir, tag);
        if (answer != IDYES) return;
        if (install_patch(dir, dll_url, _atoi64(size), tag)) {
            fprintf(stderr, "update: graphics patch %s installed\n", tag);
            MessageBoxW(NULL, L"The update is installed. The game starts now.", L"Mako update", MB_OK | MB_ICONINFORMATION | MB_TOPMOST);
        } else {
            fprintf(stderr, "update: graphics patch %s could not be installed\n", tag);
            MessageBoxW(NULL, L"The update could not be downloaded or installed. The game starts as it was.", L"Mako update",
                        MB_OK | MB_ICONWARNING | MB_TOPMOST);
        }
        return;
    }
    _snwprintf(text, 2048,
               L"A new version of Mako is out: %ls (this game is %ls).\n\n"
               L"This one changes the game itself, so it needs a rebuild with the Hookshot Builder from the release page. "
               L"Your saves and settings stay.\n\n"
               L"Yes: open the release page\nNo: not now (asked again next time)\nCancel: skip this version",
               wtag, whave);
    const int answer = MessageBoxW(NULL, text, L"Mako update", MB_YESNOCANCEL | MB_ICONINFORMATION | MB_TOPMOST | MB_SETFOREGROUND);
    if (answer == IDCANCEL) skip_release(dir, tag);
    if (answer == IDYES) ShellExecuteW(NULL, L"open", RELEASES_PAGE, NULL, NULL, SW_SHOWNORMAL);
}
#elif defined(__linux__)
#include "hos_paths.h"
#include <ctype.h>
#include <sys/stat.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* (the same offer as Windows, when the player started bin/hookshot itself. The launcher sets HOOKSHOT_NO_UPDATE_CHECK
   and asks in its own window. curl and zenity do the network and the question; without either, the game just starts) */

static int read_value(const char *path, const char *name, char *out, size_t cap) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    char line[1024];
    const size_t n = strlen(name);
    int found = 0;
    while (!found && fgets(line, sizeof line, f)) {
        char *s = line;
        if (strncmp(s, name, n) || s[n] != '=') continue;
        s += n + 1;
        size_t len = strlen(s);
        while (len && (s[len - 1] == '\n' || s[len - 1] == '\r' || s[len - 1] == ' ')) s[--len] = 0;
        if (len && len < cap) memcpy(out, s, len + 1), found = 1;
    }
    fclose(f);
    return found;
}


static int pipe_tag(const char *cmd, char *tag, size_t cap) {
    FILE *p = popen(cmd, "r");
    if (!p) return 0;
    char buf[8192];
    size_t n = fread(buf, 1, sizeof buf - 1, p);
    pclose(p);
    buf[n] = 0;
    const char *k = strstr(buf, "\"tag_name\"");
    if (k && (k = strchr(k + 10, '"'))) {
        const char *e = strchr(++k, '"');
        if (e && e > k && (size_t)(e - k) < cap) {
            memcpy(tag, k, (size_t)(e - k));
            tag[e - k] = 0;
            return safe_tag(tag);
        }
    }
    if (!strncmp(buf, "tag ", 4)) {
        const char *s = buf + 4;
        size_t len = strcspn(s, "\r\n");
        if (len && len < cap) {
            memcpy(tag, s, len);
            tag[len] = 0;
            return safe_tag(tag);
        }
    }
    return 0;
}

static int latest_tag(char *tag, size_t cap) {
    if (pipe_tag("curl -fsSL --max-time 4 --retry 2 -A Hookshot-update-check "
                 "-H \"Accept: application/vnd.github+json\" "
                 "https://api.github.com/repos/NotRexed/Hookshot/releases/latest 2>/dev/null", tag, cap))
        return 1;
    return pipe_tag("curl -fsSL --max-time 8 --retry 2 -A Hookshot-update-check "
                    "https://github.com/NotRexed/Hookshot/releases/latest/download/hookshot-linux.txt 2>/dev/null", tag, cap);
}

/* the builder an update installed (builder/linux/linux_update.py): <data>/hookshot/builder/versions/<current>/AppRun. The
   builder= line names the AppImage that built the folder, which the player may have deleted since */
static int installed_builder(char *out, size_t cap) {
    const char *home = getenv("HOOKSHOT_BUILDER_HOME"), *data = getenv("XDG_DATA_HOME"), *user = getenv("HOME");
    char root[MAX_PATH * 2], path[MAX_PATH * 2 + 64], tag[128];
    if (home && *home) snprintf(root, sizeof root, "%s/hookshot/builder", home);
    else if (data && *data) snprintf(root, sizeof root, "%s/hookshot/builder", data);
    else if (user && *user) snprintf(root, sizeof root, "%s/.local/share/hookshot/builder", user);
    else return 0;
    snprintf(path, sizeof path, "%s/current", root);
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    const int got = fgets(tag, sizeof tag, f) != NULL;
    fclose(f);
    if (!got) return 0;
    tag[strcspn(tag, "\r\n ")] = 0;
    if (!safe_tag(tag)) return 0;
    if (snprintf(out, cap, "%s/versions/%s/AppRun", root, tag) >= (int)cap) return 0;
    return access(out, X_OK) == 0;
}

void hos_update_check(void) {
    const char *off = getenv("HOOKSHOT_NO_UPDATE_CHECK");
    if (off && strcmp(off, "0")) return;
    char path[MAX_PATH + 64], have[128], builder[MAX_PATH * 2], skipped[128] = "", tag[128];
    DWORD n = hos_game_path_a(path, MAX_PATH);
    if (!n || n >= MAX_PATH) return;
    while (n && path[n - 1] != '/') n--;
    if (!n) return;
    path[n] = 0;
    char dir[MAX_PATH];
    memcpy(dir, path, n);
    dir[n] = 0;
    snprintf(path, sizeof path, "%shookshot_version.txt", dir);
    if (!read_value(path, "version", have, sizeof have) || !safe_tag(have)) return;
    snprintf(path, sizeof path, "%suser/hookshot_update_skip.txt", dir);
    read_value(path, "skip", skipped, sizeof skipped);
    if (!latest_tag(tag, sizeof tag)) {
        fprintf(stderr, "update: the latest release could not be asked for (offline?)\n");
        return;
    }
    fprintf(stderr, "update: this folder is %s, the latest release is %s\n", have, tag);
    if (!strcmp(tag, have) || !strcmp(tag, skipped)) return;
    snprintf(path, sizeof path, "%shookshot_version.txt", dir);
    const int has_builder = installed_builder(builder, sizeof builder) ||
                            (read_value(path, "builder", builder, sizeof builder) && access(builder, X_OK) == 0);
    char text[1600], cmd[4096];
    snprintf(text, sizeof text,
             has_builder
                 ? "A new version of Hookshot is out: %s (this game is %s). Update now? The game closes, and Hookshot Builder downloads only what changed and builds this folder again. Your saves and settings stay."
                 : "A new version of Hookshot is out: %s (this game is %s). The builder that made this folder was not found. Open the download page?",
             tag, have);
    snprintf(cmd, sizeof cmd, "zenity --list --title=Hookshot --hide-header --column= --text='%s' 'Update now' 'Not now' 'Skip this version'", text);
    FILE *pick = popen(cmd, "r");
    if (!pick) return;
    char answer[64] = "";
    if (!fgets(answer, sizeof answer, pick)) answer[0] = 0;
    pclose(pick);
    if (!strncmp(answer, "Skip", 4)) {
        snprintf(path, sizeof path, "%suser", dir);
        mkdir(path, 0755);
        snprintf(path, sizeof path, "%suser/hookshot_update_skip.txt", dir);
        FILE *f = fopen(path, "wb");
        if (f) fprintf(f, "skip=%s\n", tag), fclose(f);
        return;
    }
    if (strncmp(answer, "Update", 6)) return;
    if (!has_builder) {
        if (fork() == 0) {
            execlp("xdg-open", "xdg-open", "https://github.com/NotRexed/Hookshot/releases/latest", (char *)0);
            _exit(127);
        }
        return;
    }
    pid_t pid = fork();
    if (pid == 0) {
        execl(builder, builder, "--update", dir, "--tag", tag, (char *)0);
        _exit(127);
    }
    if (pid > 0) {
        fprintf(stderr, "update: Hookshot Builder started to update to %s; the game closes\n", tag);
        fflush(stderr);
        _exit(0);
    }
}
#else
void hos_update_check(void) {}
#endif
