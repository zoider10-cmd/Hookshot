/* Playback endpoint metadata and a locked preference mailbox. Discovery never opens a stream. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdlib.h>
#include <stdint.h>
#include <limits.h>
#include "audio_output_devices.h"
#include "options_path.h"
#ifdef _WIN32
#include <mmsystem.h>
#include <mmddk.h>
#include <mmdeviceapi.h>
#include <propsys.h>
#include <objbase.h>
#else
/* Preference-only fixtures and the renderer need no SDL implementation. */
extern int hos_sdl_output_count(void) __attribute__((weak));
extern int hos_sdl_output_info(int, char *, int, char *, int) __attribute__((weak));
extern int hos_sdl_output_resolve(const char *) __attribute__((weak));
#endif
typedef struct { char *id, *name; } OutputDevice;
static OutputDevice *devices;
static int device_count;
static SRWLOCK devices_lock = SRWLOCK_INIT, preference_lock = SRWLOCK_INIT;
static char wanted[HOS_OUTPUT_ID_CAP];
static unsigned preference_generation = 1;
static int preference_loaded, effective_state;

static void load_preference(void) { /* preference_lock exclusive */
    if (preference_loaded) return;
    preference_loaded = 1;
    const char *path = hos_options_file();
    if (!path || !*path) return;   /* No chosen settings path: Default, without a beside-game fallback. */
    FILE *f = fopen(path, "r");
    if (f) { audio_output_read_id(f, wanted, sizeof wanted); fclose(f); }
}
void hos_audio_output_preference(char *id, int capacity, unsigned *generation) {
    if (!id || capacity <= 0 || !generation) return;
    AcquireSRWLockExclusive(&preference_lock);
    load_preference();
    if (*generation != preference_generation && audio_output_copy_id(id, (size_t)capacity, wanted))
        *generation = preference_generation;
    ReleaseSRWLockExclusive(&preference_lock);
}
void hos_audio_output_select(const char *id) {
    char checked[HOS_OUTPUT_ID_CAP];
    if (!audio_output_copy_id(checked, sizeof checked, id)) return;
    AcquireSRWLockExclusive(&preference_lock);
    load_preference();
    if (strcmp(wanted, checked)) {
        memcpy(wanted, checked, strlen(checked) + 1);
        if (++preference_generation == 0) preference_generation = 1;
    }
    ReleaseSRWLockExclusive(&preference_lock);
}
int hos_audio_output_state(void) { return __atomic_load_n(&effective_state, __ATOMIC_RELAXED); }
void hos_audio_output_report(int state) { __atomic_store_n(&effective_state, state, __ATOMIC_RELAXED); }
#ifdef _WIN32
static char *output_utf8(const WCHAR *wide) {
    int n = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide, -1, NULL, 0, NULL, NULL);
    if (n <= 0) return NULL;
    char *s = (char *)malloc((size_t)n);
    if (s && !WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide, -1, s, n, NULL, NULL)) { free(s); s = NULL; }
    return s;
}
static WCHAR *output_wide_id(unsigned index) {
    ULONG bytes = 0;
    if (waveOutMessage((HWAVEOUT)(UINT_PTR)index, DRV_QUERYFUNCTIONINSTANCEIDSIZE, (DWORD_PTR)&bytes, 0) != MMSYSERR_NOERROR ||
        bytes < sizeof(WCHAR) || bytes > 131072 || bytes % sizeof(WCHAR)) return NULL;
    WCHAR *id = (WCHAR *)calloc(1, (size_t)bytes + sizeof(WCHAR));
    if (id && waveOutMessage((HWAVEOUT)(UINT_PTR)index, DRV_QUERYFUNCTIONINSTANCEID, (DWORD_PTR)id, bytes) != MMSYSERR_NOERROR) {
        free(id); id = NULL;
    }
    return id;
}
static char *output_label(IMMDeviceEnumerator *e, const WCHAR *id, unsigned index) {
    static const PROPERTYKEY key = {{0xa45c254e,0xdf1c,0x4efd,{0x80,0x20,0x67,0xd1,0x46,0xa8,0x50,0xe0}},14};
    char *name = NULL;
    IMMDevice *d = NULL;
    if (e && SUCCEEDED(e->lpVtbl->GetDevice(e, id, &d)) && d) {
        IPropertyStore *p = NULL;
        if (SUCCEEDED(d->lpVtbl->OpenPropertyStore(d, STGM_READ, &p)) && p) {
            PROPVARIANT v; memset(&v, 0, sizeof v);
            if (SUCCEEDED(p->lpVtbl->GetValue(p, &key, &v)) && v.vt == VT_LPWSTR && v.pwszVal) name = output_utf8(v.pwszVal);
            PropVariantClear(&v);
            p->lpVtbl->Release(p);
        }
        d->lpVtbl->Release(d);
    }
    if (!name) {
        WAVEOUTCAPSW caps;
        if (waveOutGetDevCapsW(index, &caps, sizeof caps) == MMSYSERR_NOERROR) name = output_utf8(caps.szPname);
    }
    if (!name) {
        char text[64]; snprintf(text, sizeof text, "Playback device %u", index + 1);
        name = (char *)malloc(strlen(text) + 1);
        if (name) strcpy(name, text);
    }
    if (name) for (unsigned char *p = (unsigned char *)name; *p; p++) if (*p < 0x20 || *p == 0x7f) *p = ' ';
    return name;
}
#endif
int hos_audio_output_count(void) {
    OutputDevice *fresh = NULL;
    int count = 0;
#ifdef _WIN32
    static const GUID clsid = {0xbcde0395,0xe52f,0x467c,{0x8e,0x3d,0xc4,0x57,0x92,0x91,0x69,0x2e}};
    static const GUID iid = {0xa95664d2,0x9614,0x4f35,{0xa7,0x46,0xde,0x8d,0xb6,0x36,0x17,0xe6}};
    HRESULT com = CoInitializeEx(NULL, COINIT_MULTITHREADED);
    IMMDeviceEnumerator *e = NULL;
    (void)CoCreateInstance(&clsid, NULL, CLSCTX_ALL, &iid, (void **)&e);
    unsigned total = waveOutGetNumDevs();
    if (total <= INT_MAX && (!total || sizeof *fresh <= SIZE_MAX / (size_t)total))
        fresh = (OutputDevice *)calloc(total ? total : 1, sizeof *fresh);
    for (unsigned i = 0; fresh && i < total; i++) {
        WCHAR *wide = output_wide_id(i);
        char *id = wide ? output_utf8(wide) : NULL, valid[HOS_OUTPUT_ID_CAP];
        char *name = id && *id && audio_output_copy_id(valid, sizeof valid, id) ? output_label(e, wide, i) : NULL;
        free(wide);
        if (id && name) { fresh[count].id = id; fresh[count++].name = name; }
        else { free(id); free(name); }
    }
    if (e) e->lpVtbl->Release(e);
    if (SUCCEEDED(com)) CoUninitialize();
#else
    const int total = hos_sdl_output_count ? hos_sdl_output_count() : 0;
    if (total >= 0 && (!total || sizeof *fresh <= SIZE_MAX / (size_t)total))
        fresh = (OutputDevice *)calloc(total ? (size_t)total : 1, sizeof *fresh);
    for (int i = 0; fresh && hos_sdl_output_info && i < total; i++) {
        char id[HOS_OUTPUT_ID_CAP], name[HOS_OUTPUT_NAME_CAP];
        if (!hos_sdl_output_info(i, id, sizeof id, name, sizeof name)) continue;
        fresh[count].id = (char *)malloc(strlen(id) + 1);
        fresh[count].name = (char *)malloc(strlen(name) + 1);
        if (!fresh[count].id || !fresh[count].name) {
            free(fresh[count].id), free(fresh[count].name);
            continue;
        }
        strcpy(fresh[count].id, id), strcpy(fresh[count].name, name);
        count++;
    }
#endif
    AcquireSRWLockExclusive(&devices_lock);
    for (int i = 0; i < device_count; i++) { free(devices[i].id); free(devices[i].name); }
    free(devices); devices = fresh; device_count = count;
    ReleaseSRWLockExclusive(&devices_lock);
    return count;
}
int hos_audio_output_info(int index, char *id, int id_capacity, char *name, int name_capacity) {
    int ok = 0;
    if (!id || !name || id_capacity <= 0 || name_capacity <= 0) return 0;
    AcquireSRWLockShared(&devices_lock);
    if (index >= 0 && index < device_count && audio_output_copy_id(id, (size_t)id_capacity, devices[index].id)) {
        snprintf(name, (size_t)name_capacity, "%s", devices[index].name);
        size_t n = strlen(name);
        if (n && (unsigned char)name[n-1] >= 0x80) {
            size_t start = n - 1;
            while (start && ((unsigned char)name[start] & 0xc0) == 0x80) start--;
            unsigned char lead = (unsigned char)name[start];
            size_t bytes = lead >= 0xf0 ? 4 : lead >= 0xe0 ? 3 : lead >= 0xc0 ? 2 : 1;
            if (start + bytes > n) name[start] = 0;
        }
        ok = 1;
    }
    ReleaseSRWLockShared(&devices_lock);
    return ok;
}
int hos_audio_output_resolve(const char *id) {
#ifdef _WIN32
    for (unsigned i = 0, n = waveOutGetNumDevs(); id && *id && i < n; i++) {
        WCHAR *wide = output_wide_id(i);
        char *candidate = wide ? output_utf8(wide) : NULL;
        int match = candidate && !strcmp(candidate, id);
        free(wide); free(candidate);
        if (match && i <= INT_MAX) return (int)i;
    }
#else
    return hos_sdl_output_resolve ? hos_sdl_output_resolve(id) : -1;
#endif
    return -1;
}
