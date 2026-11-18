/* Window-thread display snapshots and renderer-thread preferences. No callback calls SDL. */
#pragma once
#include "../gpu/vk/vk_api.h"
#include <string.h>
#include <stddef.h>
#define HOS_MONITOR_MAX 64

/* An opaque saved key is UTF-8 text on one INI line, bounded and never silently truncated. */
static int hos_monitor_copy_id(char *out, size_t cap, const char *id) {
    if (!out || !cap || !id) return 0;
    size_t n = strlen(id);
    if (n >= cap) return 0;
    for (size_t i=0; i<n; i++) if ((unsigned char)id[i]<32 || (unsigned char)id[i]==127) return 0;
    memcpy(out,id,n+1);
    return 1;
}
/* A duplicated identity never resolves arbitrarily. Enumeration indices are only UI positions. */
static int hos_monitor_find(const MkwVkMonitor *list, int count, const char *id) {
    int found=-1;
    if (!id || !*id) return -1;
    for (int i=0; i<count; i++) if (!strcmp(list[i].id,id)) {
        if (found>=0) return -1;
        found=i;
    }
    return found;
}
int hos_monitor_count(void);
int hos_monitor_info(int index, MkwVkMonitor *out);
void hos_monitor_select(const char *id);
int hos_monitor_screen_size(int *width, int *height);
void hos_monitor_publish(const MkwVkMonitor *list, int count, int window_ready);
void hos_monitor_wanted(char out[512]);
void hos_monitor_load(void);
int hos_monitor_start_fullscreen(void);
/* Windows may enumerate on the startup thread; Linux publishes before starting the game thread. */
void hos_monitor_prepare(void);
