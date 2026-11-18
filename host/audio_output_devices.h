/* Playback metadata/preferences. These functions never open or close an audio handle. */
#pragma once
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#define HOS_OUTPUT_ID_CAP 2048
#define HOS_OUTPUT_NAME_CAP 1024
enum { HOS_OUTPUT_FALLBACK = 1, HOS_OUTPUT_OVERRIDE = 2, HOS_OUTPUT_UNAVAILABLE = 4 };

/* Endpoint IDs are opaque. Reject oversize/control-containing values instead of truncating an ID. */
static inline int audio_output_copy_id(char *out, size_t capacity, const char *id) {
    if (!out || !capacity || !id || strlen(id) >= capacity) return 0;
    for (const unsigned char *p = (const unsigned char *)id; *p; p++)
        if (*p < 0x20 || *p == 0x7f) return 0;
    memmove(out, id, strlen(id) + 1);
    return 1;
}
static inline void audio_output_read_id(FILE *f, char *out, size_t capacity) {
    char line[4096];
    if (!capacity) return;
    out[0] = 0;
    while (f && fgets(line, sizeof line, f)) {
        if (!strchr(line, '\n') && !feof(f)) {
            if (!strncmp(line, "audio_output_device_id=", 23)) out[0] = 0;
            int c; while ((c = fgetc(f)) != '\n' && c != EOF) {}
            continue;
        }
        const char key[] = "audio_output_device_id=";
        if (strncmp(line, key, sizeof key - 1)) continue;
        line[strcspn(line, "\r\n")] = 0;
        if (!audio_output_copy_id(out, capacity, line + sizeof key - 1)) out[0] = 0;
    }
}
#ifdef __cplusplus
extern "C" {
#endif
int hos_audio_output_count(void);
int hos_audio_output_info(int index, char *id, int id_capacity, char *name, int name_capacity);
void hos_audio_output_select(const char *id);
int hos_audio_output_state(void);
/* Audio thread: read the preference mailbox, resolve an ID, publish effective-route flags. */
void hos_audio_output_preference(char *id, int capacity, unsigned *generation);
int hos_audio_output_resolve(const char *id);
void hos_audio_output_report(int state);
#ifdef __cplusplus
}
#endif
