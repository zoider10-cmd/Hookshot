#include "hos.h"
#include "fullscreen_monitor.h"
#include "options_path.h"
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

static SRWLOCK monitor_lock=SRWLOCK_INIT;
static MkwVkMonitor monitor_list[HOS_MONITOR_MAX];
static int monitor_n, monitor_window, monitor_loaded, monitor_start;
static char monitor_want[512];

void hos_monitor_load(void) {
    AcquireSRWLockExclusive(&monitor_lock);
    if (!monitor_loaded) {
        monitor_loaded=1;
        FILE *f=fopen(hos_options_file(),"r");
        if (f) {
            char line[4096];
            while (fgets(line,sizeof line,f)) {
                line[strcspn(line,"\r\n")]=0;
                if (!strncmp(line,"fullscreen_monitor_id=",22))
                    hos_monitor_copy_id(monitor_want,sizeof monitor_want,line+22);
                if (!strncmp(line,"fullscreen=",11)) monitor_start=atoi(line+11)!=0;
            }
            fclose(f);
        }
        const char *forced=getenv("HOS_FULLSCREEN");
        if (forced) monitor_start=atoi(forced)!=0;
    }
    ReleaseSRWLockExclusive(&monitor_lock);
}
int hos_monitor_start_fullscreen(void) { hos_monitor_load(); return monitor_start; }
void hos_monitor_wanted(char out[512]) {
    hos_monitor_load();
    AcquireSRWLockShared(&monitor_lock);
    memcpy(out,monitor_want,sizeof monitor_want);
    ReleaseSRWLockShared(&monitor_lock);
}
void hos_monitor_select(const char *id) {
    char checked[512];
    if (!hos_monitor_copy_id(checked,sizeof checked,id)) return;
    hos_monitor_load();
    AcquireSRWLockExclusive(&monitor_lock);
    strcpy(monitor_want,checked);
    ReleaseSRWLockExclusive(&monitor_lock);
}
void hos_monitor_publish(const MkwVkMonitor *list,int count,int window_ready) {
    if (count<0 || count>HOS_MONITOR_MAX) return;
    AcquireSRWLockExclusive(&monitor_lock);
    memcpy(monitor_list,list,(size_t)count*sizeof *list);
    monitor_n=count; monitor_window=window_ready;
    ReleaseSRWLockExclusive(&monitor_lock);
}
int hos_monitor_count(void) {
    AcquireSRWLockShared(&monitor_lock); int n=monitor_n; ReleaseSRWLockShared(&monitor_lock); return n;
}
int hos_monitor_info(int index,MkwVkMonitor *out) {
    if (!out) return 0;
    AcquireSRWLockShared(&monitor_lock);
    int ok=index>=0 && index<monitor_n;
    if (ok) *out=monitor_list[index];
    ReleaseSRWLockShared(&monitor_lock);
    return ok;
}
int hos_monitor_screen_size(int *width,int *height) {
    if (!width || !height) return 0;
    hos_monitor_load();
    AcquireSRWLockShared(&monitor_lock);
    int pick=-1;
    if (!monitor_window && monitor_start) pick=hos_monitor_find(monitor_list,monitor_n,monitor_want);
    if (pick<0) for (int i=0;i<monitor_n;i++) if (monitor_list[i].flags&HOS_MONITOR_CURRENT) { pick=i; break; }
    if (pick<0) for (int i=0;i<monitor_n;i++) if (monitor_list[i].flags&HOS_MONITOR_PRIMARY) { pick=i; break; }
    int ok=pick>=0 && monitor_list[pick].width>0 && monitor_list[pick].height>0;
    if (ok) { *width=monitor_list[pick].width; *height=monitor_list[pick].height; }
    ReleaseSRWLockShared(&monitor_lock);
    return ok;
}
