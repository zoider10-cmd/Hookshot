/* Actual endpoint module with synthetic WinMM metadata. Never opens or records an audio device. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmsystem.h>
#include <mmddk.h>
#include <mmdeviceapi.h>
#include <propsys.h>
#include <objbase.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <wchar.h>
const char *hos_options_file(void) { return "./hookshot_options.ini"; }
static unsigned synthetic_count = 80;
static int reordered;
static UINT WINAPI fake_count(void) { return synthetic_count; }
static MMRESULT WINAPI fake_caps(UINT_PTR index, LPWAVEOUTCAPSW caps, UINT size) {
    (void)index; assert(size == sizeof *caps); memset(caps, 0, size);
    wcscpy(caps->szPname, L"Mic \x03b1"); /* Duplicate Unicode labels, distinct endpoint IDs. */
    return MMSYSERR_NOERROR;
}
static MMRESULT WINAPI fake_message(HWAVEOUT device, UINT message, DWORD_PTR value, DWORD_PTR bytes) {
    unsigned index = (unsigned)(uintptr_t)device;
    if (index >= synthetic_count) return MMSYSERR_BADDEVICEID;
    if (reordered && (index == 0 || index == 79)) index = 79 - index;
    WCHAR id[80]; swprintf(id, 80, L"endpoint-%u", index);
    ULONG length = (ULONG)((wcslen(id) + 1) * sizeof(WCHAR));
    if (message == DRV_QUERYFUNCTIONINSTANCEIDSIZE) *(ULONG *)value = length;
    else { assert(message == DRV_QUERYFUNCTIONINSTANCEID && bytes >= length); memcpy((void *)value, id, length); }
    return MMSYSERR_NOERROR;
}
static HRESULT WINAPI fake_create(REFCLSID clsid, LPUNKNOWN outer, DWORD context, REFIID iid, LPVOID *object) {
    (void)clsid; (void)outer; (void)context; (void)iid; *object = NULL; return E_NOINTERFACE;
}
#define waveOutGetNumDevs fake_count
#define waveOutGetDevCapsW fake_caps
#define waveOutMessage fake_message
#define CoCreateInstance fake_create
#include "../host/audio_output_devices.c"

int main(void) {
    FILE *settings = fopen("hookshot_options.ini", "w"); assert(settings);
    fputs("audio_output=2\nmicrophone=1\naudio_output_device_id=endpoint-23\n", settings); fclose(settings);
    char id[HOS_OUTPUT_ID_CAP] = {0}, name[HOS_OUTPUT_NAME_CAP]; unsigned generation = 0;
    hos_audio_output_preference(id, sizeof id, &generation);
    assert(!strcmp(id, "endpoint-23"));
    assert(hos_audio_output_count() == 80);
    assert(hos_audio_output_info(79, id, sizeof id, name, sizeof name));
    assert(!strcmp(id, "endpoint-79") && !strcmp(name, "Mic \xce\xb1"));
    assert(!hos_audio_output_info(80, id, sizeof id, name, sizeof name));
    char short_id[4] = "old";
    assert(!hos_audio_output_info(79, short_id, sizeof short_id, name, sizeof name) && !strcmp(short_id, "old"));
    char short_name[6];
    assert(hos_audio_output_info(1, id, sizeof id, short_name, sizeof short_name));
    assert(!strcmp(short_name, "Mic ")); /* A cut UTF-8 lead byte is removed. */
    hos_audio_output_select("endpoint-79");
    hos_audio_output_preference(id, sizeof id, &generation);
    assert(!strcmp(id, "endpoint-79") && hos_audio_output_resolve(id) == 79);
    reordered = 1;
    assert(hos_audio_output_resolve(id) == 0); /* Save identity, not a driver index. */
    hos_audio_output_select("bad\nnew_setting=1");
    hos_audio_output_preference(id, sizeof id, &generation);
    assert(!strcmp(id, "endpoint-79"));
    synthetic_count = 0;
    assert(hos_audio_output_count() == 0 && hos_audio_output_resolve(id) == -1);
    synthetic_count = 80;
    assert(hos_audio_output_count() == 80 && hos_audio_output_resolve(id) == 0);
    hos_audio_output_report(HOS_OUTPUT_FALLBACK | HOS_OUTPUT_UNAVAILABLE);
    assert(hos_audio_output_state() == (HOS_OUTPUT_FALLBACK | HOS_OUTPUT_UNAVAILABLE));
    hos_audio_output_select(""); hos_audio_output_preference(id, sizeof id, &generation);
    assert(!*id);
    synthetic_count = 0; hos_audio_output_count();
    puts("PASS: endpoint metadata, 80 devices, Unicode/duplicate names, stable IDs, preference mailbox and reconnect");
    return 0;
}
