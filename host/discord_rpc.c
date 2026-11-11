/* (hookshot) Discord Rich Presence: "Playing Hookshot" with the time played in the player's Discord status, through the local
   IPC of a Discord client running on this PC. Nothing leaves the machine but the activity itself, and nothing is sent while the
   Insert menu's "Discord status" row is off (on by default; it does nothing without a Discord client running).

   Discord shows the *application's* name above the status ("Playing <name>") and its art: the status needs a Discord application
   of its own (discord.com/developers/applications, named Hookshot, its art uploaded under Rich Presence > Art Assets with the key
   below). This build ships a Mako/OoT application ID and art keys by default; hookshot_options.ini can optionally override the
   id, text, and large/small art keys for downstream/personal branding. HOS_DISCORD_APP_ID still overrides the id.

   One host thread owns the connection. It connects to the first of Discord's discord-ipc-0..9 that completes a handshake and
   writes the activity again every 60 s: that write is the keep-alive, and one that fails closes the connection and tries again
   15 s later. Discord clears the status itself when the process ends and the pipe closes. Every answer is read and dropped:
   unread, they would fill the pipe and block the client.

   The protocol is Discord's documented IPC (discord-rpc's rpc_connection.h): a frame is <opcode u32 LE><length u32 LE><JSON>,
   Handshake 0, Frame 1, Close 2, Ping 3, Pong 4. The handshake {"v":1,"client_id":...} is answered by a Ready frame; a
   SET_ACTIVITY frame by a frame; a Ping is echoed as a Pong. */
#include "hos_paths.h"   /* (first: hos_game_path_a, and windows.h on Windows) */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef _WIN32
#include <windows.h>
#else
#include <errno.h>
#include <poll.h>
#include <pthread.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#endif

#include "../gpu/vk/vk_api.h"

#define HOOKSHOT_DISCORD_APP_ID_DEFAULT "1569877496780947547"   /* Mako/OoT Discord application id */
#define HOOKSHOT_DISCORD_DETAILS_DEFAULT "The Legend of Zelda: Ocarina of Time"
#define HOOKSHOT_DISCORD_STATE_DEFAULT "Exploring Hyrule"
#define HOOKSHOT_DISCORD_LARGE_IMAGE_DEFAULT "ocarina-title-new-960x540"
#define HOOKSHOT_DISCORD_LARGE_TEXT_DEFAULT "The Legend of Zelda: Ocarina of Time"
#define HOOKSHOT_DISCORD_SMALL_IMAGE_DEFAULT "a59d076a-8dfa-4d04-8580-fb17ae4784df"
#define HOOKSHOT_DISCORD_SMALL_TEXT_DEFAULT "Mako Emulator"

void hos_log(const char *fmt, ...);
int rx_option(int id, int otherwise);
const char *hos_version(void);   /* hos_main.c */

enum { OP_HANDSHAKE = 0, OP_FRAME = 1, OP_CLOSE = 2, OP_PING = 3, OP_PONG = 4 };
#define ANSWER_CAP 8192

/* ---- the local connection: a named pipe on Windows, a Unix socket elsewhere ---- */
#ifdef _WIN32
typedef HANDLE Ipc;
#define IPC_NONE INVALID_HANDLE_VALUE
static uint64_t now_ms(void) { return GetTickCount64(); }
static void sleep_ms(unsigned ms) { Sleep(ms); }
static Ipc ipc_connect(int i) {
    char name[48];
    snprintf(name, sizeof name, "\\\\.\\pipe\\discord-ipc-%d", i);
    /* (identification only: another program that made a pipe of this name cannot act as this one) */
    return CreateFileA(name, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION,
                       NULL);
}
static void ipc_close(Ipc p) { CloseHandle(p); }
static int ipc_write(Ipc p, const void *d, size_t n) {
    DWORD done = 0;
    return WriteFile(p, d, (DWORD)n, &done, NULL) && done == n;
}
/* bytes read (0: none came before the deadline), -1 broken */
static int ipc_read(Ipc p, void *d, size_t n, uint64_t deadline) {
    for (;;) {
        DWORD avail = 0;
        if (!PeekNamedPipe(p, NULL, 0, NULL, &avail, NULL)) return -1;
        if (avail) {
            DWORD got = 0;
            if (!ReadFile(p, d, (DWORD)(n < avail ? n : avail), &got, NULL)) return -1;
            return (int)got;
        }
        if (now_ms() >= deadline) return 0;
        Sleep(10);
    }
}
static unsigned long process_id(void) { return GetCurrentProcessId(); }
#else
typedef int Ipc;
#define IPC_NONE (-1)
static uint64_t now_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000 + (uint64_t)t.tv_nsec / 1000000;
}
static void sleep_ms(unsigned ms) { usleep(ms * 1000u); }
static Ipc ipc_connect(int i) {
    const char *dir = getenv("XDG_RUNTIME_DIR");
    if (!dir) dir = getenv("TMPDIR");
    if (!dir) dir = "/tmp";
    /* (Flatpak and Snap Discord put theirs one folder down) */
    const char *subs[] = {"", "app/com.discordapp.Discord/", "snap.discord/"};
    for (size_t s = 0; s < sizeof subs / sizeof *subs; s++) {
        struct sockaddr_un a;
        memset(&a, 0, sizeof a);
        a.sun_family = AF_UNIX;
        snprintf(a.sun_path, sizeof a.sun_path, "%s/%sdiscord-ipc-%d", dir, subs[s], i);
        const int fd = socket(AF_UNIX, SOCK_STREAM, 0);
        if (fd < 0) return IPC_NONE;
        if (!connect(fd, (struct sockaddr *)&a, sizeof a)) return fd;
        close(fd);
    }
    return IPC_NONE;
}
static void ipc_close(Ipc p) { close(p); }
static int ipc_write(Ipc p, const void *d, size_t n) {
    const char *c = d;
    while (n) {
        const ssize_t w = send(p, c, n, MSG_NOSIGNAL);
        if (w <= 0) return 0;
        c += w, n -= (size_t)w;
    }
    return 1;
}
static int ipc_read(Ipc p, void *d, size_t n, uint64_t deadline) {
    const uint64_t t = now_ms();
    struct pollfd f = {p, POLLIN, 0};
    const int r = poll(&f, 1, deadline > t ? (int)(deadline - t) : 0);
    if (r < 0) return errno == EINTR ? 0 : -1;
    if (!r) return 0;
    const ssize_t got = recv(p, d, n, 0);
    return got > 0 ? (int)got : -1;
}
static unsigned long process_id(void) { return (unsigned long)getpid(); }
#endif

/* ---- settings ---- */
typedef struct DiscordSettings {
    char app_id[24];
    char details[128];
    char state[128];
    char large_image[128];
    char large_text[128];
    char small_image[128];
    char small_text[128];
} DiscordSettings;

static int valid_app_id(const char *s) {
    const size_t n = strlen(s);
    if (!n || n > 20) return 0;
    for (; *s; s++)
        if (*s < '0' || *s > '9') return 0;
    return 1;
}
static void setting_copy(char *out, size_t cap, const char *value) {
    if (!cap) return;
    snprintf(out, cap, "%s", value ? value : "");
}
static void set_ini_value(DiscordSettings *s, const char *key, const char *value) {
    if (!strcmp(key, "discord_app_id")) {
        if (!*value || valid_app_id(value)) setting_copy(s->app_id, sizeof s->app_id, value);
    } else if (!strcmp(key, "discord_details")) {
        setting_copy(s->details, sizeof s->details, value);
    } else if (!strcmp(key, "discord_state")) {
        setting_copy(s->state, sizeof s->state, value);
    } else if (!strcmp(key, "discord_large_image")) {
        setting_copy(s->large_image, sizeof s->large_image, value);
    } else if (!strcmp(key, "discord_large_text")) {
        setting_copy(s->large_text, sizeof s->large_text, value);
    } else if (!strcmp(key, "discord_small_image")) {
        setting_copy(s->small_image, sizeof s->small_image, value);
    } else if (!strcmp(key, "discord_small_text")) {
        setting_copy(s->small_text, sizeof s->small_text, value);
    }
}
/*
   Discord Rich Presence has built-in Mako/OoT branding, so users do not need to configure anything.
   hookshot_options.ini remains an optional override path for downstream/personal branding, and HOS_DISCORD_APP_ID still overrides the id.
*/
static void read_discord_settings(DiscordSettings *s) {
    memset(s, 0, sizeof *s);
    setting_copy(s->app_id, sizeof s->app_id, HOOKSHOT_DISCORD_APP_ID_DEFAULT);
    setting_copy(s->details, sizeof s->details, HOOKSHOT_DISCORD_DETAILS_DEFAULT);
    setting_copy(s->state, sizeof s->state, HOOKSHOT_DISCORD_STATE_DEFAULT);
    setting_copy(s->large_image, sizeof s->large_image, HOOKSHOT_DISCORD_LARGE_IMAGE_DEFAULT);
    setting_copy(s->large_text, sizeof s->large_text, HOOKSHOT_DISCORD_LARGE_TEXT_DEFAULT);
    setting_copy(s->small_image, sizeof s->small_image, HOOKSHOT_DISCORD_SMALL_IMAGE_DEFAULT);
    setting_copy(s->small_text, sizeof s->small_text, HOOKSHOT_DISCORD_SMALL_TEXT_DEFAULT);

    char path[1024];
    const DWORD n = hos_game_path_a(path, (DWORD)sizeof path);
    char *slash = n ? (strrchr(path, '\\') ? strrchr(path, '\\') : strrchr(path, '/')) : NULL;
    if (slash) {
        snprintf(slash + 1, (size_t)(path + sizeof path - slash - 1), "hookshot_options.ini");
        FILE *f = fopen(path, "r");
        if (f) {
            char line[512];
            while (fgets(line, sizeof line, f)) {
                line[strcspn(line, "\r\n")] = 0;
                char *eq = strchr(line, '=');
                if (!eq || eq == line) continue;
                *eq = 0;
                set_ini_value(s, line, eq + 1);
            }
            fclose(f);
        }
    }

    const char *e = getenv("HOS_DISCORD_APP_ID");
    if (e && valid_app_id(e)) setting_copy(s->app_id, sizeof s->app_id, e);
    if (*s->app_id && !valid_app_id(s->app_id)) *s->app_id = 0;
}

/* JSON string content, without surrounding quotes. Invalid control bytes are encoded as \u00XX. */
static void json_escape(char *out, size_t cap, const char *in) {
    static const char hex[] = "0123456789abcdef";
    size_t at = 0;
    if (!cap) return;
    for (const unsigned char *p = (const unsigned char *)in; *p && at + 1 < cap; p++) {
        const unsigned char c = *p;
        if (c == '\"' || c == '\\') {
            if (at + 2 >= cap) break;
            out[at++] = '\\', out[at++] = (char)c;
        } else if (c < 0x20) {
            if (at + 6 >= cap) break;
            out[at++] = '\\', out[at++] = 'u', out[at++] = '0', out[at++] = '0';
            out[at++] = hex[c >> 4], out[at++] = hex[c & 15];
        } else {
            out[at++] = (char)c;
        }
    }
    out[at] = 0;
}

/* ---- frames ---- */
static void le32(uint8_t *at, uint32_t v) { at[0] = (uint8_t)v, at[1] = (uint8_t)(v >> 8), at[2] = (uint8_t)(v >> 16), at[3] = (uint8_t)(v >> 24); }
static int write_frame(Ipc p, uint32_t op, const char *json) {
    uint8_t head[8];
    le32(head, op), le32(head + 4, (uint32_t)strlen(json));
    return ipc_write(p, head, sizeof head) && ipc_write(p, json, strlen(json));
}
/* 1 a whole frame (buf NUL-terminated, a longer payload cut), 0 the deadline passed, -1 broken */
static int read_one_frame(Ipc p, uint32_t *op, char *buf, size_t cap, uint64_t deadline) {
    uint8_t head[8];
    size_t got = 0;
    while (got < sizeof head) {
        const int n = ipc_read(p, head + got, sizeof head - got, deadline);
        if (n < 0) return -1;
        if (!n) return 0;
        got += (size_t)n;
    }
    *op = head[0] | head[1] << 8 | head[2] << 16 | (uint32_t)head[3] << 24;
    const uint32_t len = head[4] | head[5] << 8 | head[6] << 16 | (uint32_t)head[7] << 24;
    size_t taken = 0, kept = 0;
    while (taken < len) {
        char tmp[512];
        size_t want = len - taken;
        if (want > sizeof tmp) want = sizeof tmp;
        const int n = ipc_read(p, tmp, want, deadline);
        if (n < 0) return -1;
        if (!n) return 0;
        for (int i = 0; i < n && kept + 1 < cap; i++) buf[kept++] = tmp[i];
        taken += (size_t)n;
    }
    buf[kept] = 0;
    return 1;
}
/* the next frame that is not a Ping (echoed as a Pong); a Close counts as broken */
static int read_frame(Ipc p, uint32_t *op, char *buf, size_t cap, unsigned ms) {
    const uint64_t deadline = now_ms() + ms;
    for (;;) {
        const int r = read_one_frame(p, op, buf, cap, deadline);
        if (r != 1) return r;
        if (*op == OP_PING) {
            if (!write_frame(p, OP_PONG, buf)) return -1;
            continue;
        }
        return *op == OP_CLOSE ? -1 : 1;
    }
}
static Ipc connect_client(const char *app_id) {
    for (int i = 0; i < 10; i++) {
        const Ipc p = ipc_connect(i);
        if (p == IPC_NONE) continue;
        char json[96], answer[ANSWER_CAP];
        snprintf(json, sizeof json, "{\"v\":1,\"client_id\":\"%s\"}", app_id);
        uint32_t op = 0;
        if (write_frame(p, OP_HANDSHAKE, json) && read_frame(p, &op, answer, sizeof answer, 2000) == 1 && op == OP_FRAME) return p;
        ipc_close(p);
    }
    return IPC_NONE;
}
/* the activity: configured text/art, plus the start of play for Discord's elapsed timer */
static int send_activity(Ipc p, long long started, const DiscordSettings *s) {
    static unsigned nonce;
    char details[768], state[768], large_image[768], large_text[768], small_image[768], small_text[768];
    char assets[4096], json[8192], answer[ANSWER_CAP];
    json_escape(details, sizeof details, s->details);
    json_escape(state, sizeof state, s->state);
    json_escape(large_image, sizeof large_image, s->large_image);
    json_escape(large_text, sizeof large_text, s->large_text);
    json_escape(small_image, sizeof small_image, s->small_image);
    json_escape(small_text, sizeof small_text, s->small_text);

    assets[0] = 0;
    if (*large_image || *small_image) {
        size_t used = 0;
        used += (size_t)snprintf(assets + used, sizeof assets - used, ",\"assets\":{");
        if (*large_image) {
            used += (size_t)snprintf(assets + used, sizeof assets - used,
                                     "\"large_image\":\"%s\"%s", large_image, *large_text ? "," : "");
            if (*large_text)
                used += (size_t)snprintf(assets + used, sizeof assets - used, "\"large_text\":\"%s\"", large_text);
        }
        if (*small_image) {
            if (*large_image) used += (size_t)snprintf(assets + used, sizeof assets - used, ",");
            used += (size_t)snprintf(assets + used, sizeof assets - used,
                                     "\"small_image\":\"%s\"%s", small_image, *small_text ? "," : "");
            if (*small_text)
                used += (size_t)snprintf(assets + used, sizeof assets - used, "\"small_text\":\"%s\"", small_text);
        }
        snprintf(assets + used, sizeof assets - used, "}");
    }

    snprintf(json, sizeof json,
             "{\"cmd\":\"SET_ACTIVITY\",\"nonce\":\"%u\",\"args\":{\"pid\":%lu,\"activity\":{"
             "\"details\":\"%s\",\"state\":\"%s\",\"timestamps\":{\"start\":%lld}%s}}}",
             ++nonce, process_id(), details, state, started, assets);
    if (!write_frame(p, OP_FRAME, json)) return 0;
    uint32_t op = 0;
    const int r = read_frame(p, &op, answer, sizeof answer, 2000);
    static int said;
    if (r == 1 && !said) {   /* (Discord's answer, once: an ERROR event says why it took no status) */
        said = 1;
        if (strstr(answer, "\"evt\":\"ERROR\"")) hos_log("discord: the status was refused: %.300s", answer);
        else hos_log("discord: status set");
    }
    return r >= 0;
}

/* ---- the presence thread ---- */
static void presence_main(void) {
    DiscordSettings settings;
    read_discord_settings(&settings);
    const long long started = (long long)time(NULL);
    Ipc ipc = IPC_NONE;
    uint64_t retry_at = 0, send_at = 0, reread_at = now_ms() + 15000;
    int said_no_client = 0, said_no_app = 0;
    for (;;) {
        sleep_ms(500);
        if (now_ms() >= reread_at) {   /* options can be edited while the game runs */
            DiscordSettings was = settings;
            read_discord_settings(&settings);
            if (strcmp(was.app_id, settings.app_id)) {
                if (ipc != IPC_NONE) ipc_close(ipc), ipc = IPC_NONE;
                retry_at = 0, said_no_app = 0;
            } else if (memcmp(&was, &settings, sizeof settings)) {
                send_at = 0;
            }
            reread_at = now_ms() + 15000;
        }
        if (!rx_option(HOS_OPT_DISCORD, 1)) {   /* the Insert menu's row, off */
            if (ipc != IPC_NONE) ipc_close(ipc), ipc = IPC_NONE;
            continue;
        }
        if (!settings.app_id[0]) {
            if (!said_no_app)
                hos_log("discord: no application id: set discord_app_id= in hookshot_options.ini or HOS_DISCORD_APP_ID; "
                        "the status stays off");
            said_no_app = 1;
            continue;
        }
        if (ipc == IPC_NONE && now_ms() >= retry_at) {
            ipc = connect_client(settings.app_id);
            if (ipc == IPC_NONE) {
                retry_at = now_ms() + 15000;
                if (!said_no_client) hos_log("discord: no Discord client is running; trying again every 15 s");
                said_no_client = 1;
            } else {
                hos_log("discord: connected (application %s)", settings.app_id);
                send_at = 0, said_no_client = 0;
            }
        }
        if (ipc != IPC_NONE && now_ms() >= send_at) {
            if (send_activity(ipc, started, &settings)) {
                send_at = now_ms() + 60000;
            } else {
                hos_log("discord: the connection broke; connecting again");
                ipc_close(ipc), ipc = IPC_NONE;
                retry_at = now_ms() + 15000;
            }
        }
    }
}
#ifdef _WIN32
static DWORD WINAPI presence_thread(LPVOID arg) {
    (void)arg;
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_LOWEST);
    presence_main();
    return 0;
}
#else
static void *presence_thread(void *arg) {
    (void)arg;
    presence_main();
    return NULL;
}
#endif

/* hos_main.c, once the game starts (not for --prepare-shaders). HOS_DISCORD=0: no thread at all */
void hos_discord_start(void) {
    const char *e = getenv("HOS_DISCORD");
    if (e && !atoi(e)) return;
#ifdef _WIN32
    HANDLE t = CreateThread(NULL, 256u << 10, presence_thread, NULL, 0, NULL);
    if (t) CloseHandle(t);
    else hos_log("discord: cannot start the presence thread");
#else
    pthread_t t;
    if (!pthread_create(&t, NULL, presence_thread, NULL)) pthread_detach(t);
    else hos_log("discord: cannot start the presence thread");
#endif
}
