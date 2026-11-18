/* Synthetic device calls around the real nn_audio.c output section. No device or game is opened. */
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../host/audio_output_devices.h"

typedef void *HWAVEOUT;
typedef char *LPSTR;
typedef unsigned MMRESULT;
typedef struct {
    unsigned wFormatTag, nChannels, nSamplesPerSec, wBitsPerSample, nBlockAlign, nAvgBytesPerSec;
} WAVEFORMATEX;
typedef struct { LPSTR lpData; unsigned dwBufferLength, dwFlags; } WAVEHDR;
#define MMSYSERR_NOERROR 0
#define WHDR_DONE 1
#define WHDR_PREPARED 2
#define WHDR_INQUEUE 16
#define WAVE_MAPPER ((unsigned)-1)
#define WAVE_FORMAT_PCM 1
#define CALLBACK_NULL 0
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL %s:%d: %s\n", scenario, __LINE__, #x); exit(1); } } while (0)

static const char *scenario;
static int prepare_calls, write_calls, accepted, unprepare_calls, open_calls, close_calls, reset_calls, logs;
static unsigned last_device, last_channels;
static uint64_t now_ms;
static int fail_prepare, fail_write, fail_unprepare, fail_open, fail_open6;
static int gone_write_at, gone_unprepare, opens_fail;   /* (the device gone: "no driver" 6, "invalid handle" 5) */
static uint32_t default_key = 11;                       /* (Windows' default output, as au_default_key says) */
static int queued[10];
static WAVEHDR *known[10];
static char last_log[512];

static const char *device_override;
static char requested_output[HOS_OUTPUT_ID_CAP];
static unsigned requested_generation = 1;
static int named_device = 1, route_state;
static int fail_named_open;
static const char *test_getenv(const char *name) { return !strcmp(name, "HOS_AUDIO_DEVICE") ? device_override : NULL; }
void hos_audio_output_preference(char *id, int capacity, unsigned *generation) {
    if (*generation != requested_generation) {
        CHECK(audio_output_copy_id(id, (size_t)capacity, requested_output));
        *generation = requested_generation;
    }
}
int hos_audio_output_resolve(const char *id) { return !strcmp(id, "named-endpoint") ? named_device : -1; }
void hos_audio_output_report(int state) { route_state = state; }
static void hos_log(const char *format, ...) {
    va_list args;
    va_start(args, format);
    vsnprintf(last_log, sizeof last_log, format, args);
    va_end(args);
    logs++;
}
static int slot(WAVEHDR *h) {
    for (int i = 0; i < 10; i++) if (known[i] == h) return i;
    for (int i = 0; i < 10; i++) if (!known[i]) { known[i] = h; return i; }
    CHECK(0);
    return -1;
}
static MMRESULT test_open(HWAVEOUT *out, unsigned device, const WAVEFORMATEX *f,
                          uintptr_t callback, uintptr_t instance, unsigned flags) {
    (void)callback; (void)instance; (void)flags;
    last_device = device;
    CHECK((f->nChannels == 2 || f->nChannels == 6) && f->nSamplesPerSec == 48000 && f->wBitsPerSample == 16);
    CHECK(f->nBlockAlign == 2 * f->nChannels && f->nAvgBytesPerSec == 48000 * f->nBlockAlign);
    last_channels = f->nChannels;
    open_calls++;
    if (fail_named_open && device == (unsigned)named_device) return 7;
    if (opens_fail) return 6;   /* (MMSYSERR_NODRIVER: the audio service down) */
    if (fail_open || (fail_open6 && f->nChannels == 6)) return 7;   /* (MMSYSERR_NOMEM; a device without 5.1: 32) */
    *out = (void *)(uintptr_t)(device == WAVE_MAPPER ? 1 : device + 2);
    return 0;
}
static MMRESULT test_prepare(HWAVEOUT out, WAVEHDR *h, unsigned size) {
    (void)out; (void)size;
    CHECK(!queued[slot(h)]);
    prepare_calls++;
    if (fail_prepare && (fail_prepare < 0 || prepare_calls == 1)) return 7;
    h->dwFlags |= WHDR_PREPARED;
    return 0;
}
static MMRESULT test_write(HWAVEOUT out, WAVEHDR *h, unsigned size) {
    (void)out; (void)size;
    const int i = slot(h);
    CHECK(!queued[i]);
    write_calls++;
    if (gone_write_at && write_calls == gone_write_at) return 6;   /* (MMSYSERR_NODRIVER) */
    if (!(h->dwFlags & WHDR_PREPARED)) return 34; /* WAVERR_UNPREPARED: no completion follows. */
    if (fail_write && (fail_write < 0 || write_calls == 1)) return 7; /* MMSYSERR_NOMEM: no buffer was queued. */
    queued[i] = 1;
    h->dwFlags = (h->dwFlags & ~WHDR_DONE) | WHDR_INQUEUE;
    accepted++;
    return 0;
}
static MMRESULT test_unprepare(HWAVEOUT out, WAVEHDR *h, unsigned size) {
    (void)out; (void)size;
    CHECK(!queued[slot(h)]);
    unprepare_calls++;
    if (gone_unprepare) return 5;   /* (MMSYSERR_INVALHANDLE, every call until the handle is closed) */
    if (fail_unprepare && unprepare_calls == 1) return 33; /* WAVERR_STILLPLAYING: do not reuse. */
    h->dwFlags &= ~WHDR_PREPARED;
    return 0;
}
static MMRESULT test_reset(HWAVEOUT out) {
    (void)out;
    reset_calls++;
    for (int i = 0; i < 10; i++) if (queued[i]) {   /* (waveOutReset: every queued block marked done) */
        queued[i] = 0;
        known[i]->dwFlags = (known[i]->dwFlags & ~WHDR_INQUEUE) | WHDR_DONE;
    }
    return 0;
}
static MMRESULT test_close(HWAVEOUT out) { (void)out; close_calls++; gone_unprepare = 0; return 0; }
/* (the platform helpers nn_audio.c defines before its output section) */
static unsigned au_device_count(void) { return 2; }
static void au_device_name(unsigned device, char *out, size_t size) { snprintf(out, size, "test device %u", device); }
static uint64_t au_ms(void) { return now_ms; }
static uint32_t au_default_key(void) { return default_key; }
static void au_opened(HWAVEOUT w) { (void)w; }
static int speakers = 2;   /* (the game's speakers: 6 in the "surround" and "fallback" cases) */
static int au_speakers(void) { return speakers; }
static const WAVEFORMATEX *au_format(const WAVEFORMATEX *f) { return f; }
#define getenv test_getenv
#define env_on(name) (getenv(name) && !env_value_off(getenv(name)))   /* (the switches read through the stand-in above) */
#define waveOutOpen test_open
#define waveOutPrepareHeader test_prepare
#define waveOutWrite test_write
#define waveOutUnprepareHeader test_unprepare
#define waveOutReset test_reset
#define waveOutClose test_close
#include "audio_output.inc"

static void complete_all(void) {
    for (int i = 0; i < 10; i++) if (queued[i]) {
        queued[i] = 0;
        known[i]->dwFlags = (known[i]->dwFlags & ~WHDR_INQUEUE) | WHDR_DONE;
    }
}
static void frames(int count, int complete) {
    int16_t pcm[FRAME * 6];
    for (int j = 0; j < count; j++) {
        for (int i = 0; i < FRAME * out_channels; i++) pcm[i] = (int16_t)(j * 31 + i);
        output_frame(pcm);
        if (complete) complete_all();
    }
}
/* one frame mixed for `channels`, 7777 past its end: what a copy with another count would take */
static void mixed_frame(int channels) {
    int16_t pcm[FRAME * 6];
    for (int i = 0; i < FRAME * 6; i++) pcm[i] = (int16_t)(i < FRAME * channels ? 100 + i : 7777);
    output_frame(pcm);
}
static int blocks_hold(int16_t value) {
    for (int b = 0; b < NBLOCKS; b++)
        for (int i = 0; i < FRAME * 2 * 6; i++)
            if (blocks[b][i] == value) return 1;
    return 0;
}
int main(int argc, char **argv) {
    CHECK(argc == 2);
    scenario = argv[1];
    fail_prepare = !strcmp(scenario, "prepare");
    fail_write = !strcmp(scenario, "write");
    fail_unprepare = !strcmp(scenario, "unprepare");
    fail_open = !strcmp(scenario, "open");
    if (!strcmp(scenario, "bounded")) fail_prepare = -1;
    if (!strcmp(scenario, "surround") || !strcmp(scenario, "fallback") || !strcmp(scenario, "upmix") ||
        !strcmp(scenario, "downmix") || !strcmp(scenario, "retry"))
        speakers = 6;
    fail_open6 = !strcmp(scenario, "fallback") || !strcmp(scenario, "upmix");
    opens_fail = !strcmp(scenario, "retry") || !strcmp(scenario, "same-layout-retry");
    output_open();
    if (!strcmp(scenario, "named-stall-budget") || !strcmp(scenario, "named-backoff")) {
        strcpy(requested_output, "named-endpoint"), requested_generation++;
        output_route_update();
        uint64_t previous_wait = 0;
        for (int attempt = 0; attempt < 10; attempt++) {
            CHECK(out_named_active && wout);
            frames(NBLOCKS * 2, 0); /* Open succeeds, but no queued block ever completes. */
            now_ms += 1;
            frames(1, 0);
            now_ms += 1501;
            frames(1, 0);
            printf("OBSERVE %s: named stall %d, named=%d fallback=%d reopens=%d\n",
                   scenario, attempt + 1, out_named_active, !!(route_state & HOS_OUTPUT_FALLBACK), out_reopens);
            fflush(stdout);
            CHECK(wout && !out_named_active && (route_state & HOS_OUTPUT_FALLBACK));
            const uint64_t delay = out_named_retry_at - now_ms;
            if (!strcmp(scenario, "named-backoff")) {
                CHECK(delay >= previous_wait);
                CHECK(attempt == 0 || delay > previous_wait || delay == 60000);
                previous_wait = delay;
            }
            const int before = accepted;
            frames(4, 1);
            CHECK(accepted == before + 2); /* Fallback still plays after more than six named stalls. */
            now_ms = out_named_retry_at;
            output_route_update();
        }
    } else if (!strcmp(scenario, "named-open-failure")) {
        fail_named_open = 1;
        strcpy(requested_output, "named-endpoint"), requested_generation++;
        output_route_update();
        CHECK(wout && !out_named_active && (route_state & HOS_OUTPUT_FALLBACK));
        frames(4, 1);
        for (int attempt = 0; attempt < 8; attempt++) {
            complete_all();
            if (fill_frames) frames(1, 1);
            frames(3, 0); /* A queued fallback block plus a partially mixed one. */
            const int closes = close_calls, resets = reset_calls, fill = fill_frames, calls = open_calls;
            int queued_before[10]; memcpy(queued_before, queued, sizeof queued);
            HWAVEOUT fallback = wout;
            now_ms = out_named_retry_at;
            output_route_update();
            CHECK(open_calls > calls); /* Actually attempted the resolvable named endpoint. */
            CHECK(wout == fallback && close_calls == closes && reset_calls == resets && fill_frames == fill);
            CHECK(!memcmp(queued_before, queued, sizeof queued));
            frames(3, 1);
        }
        fail_named_open = 0;
        speakers = 6;
        now_ms = out_named_retry_at;
        output_route_update(); /* A successful probe switches layout before the next mix. */
        CHECK(out_named_active && out_channels == 6 && !route_state && fill_frames == 0);
        mixed_frame(out_channels);
        CHECK(fill_frames == 1 && !blocks_hold(7777));
    } else if (!strcmp(scenario, "named-retry-stereo")) {
        fail_named_open = 1, speakers = 6;
        strcpy(requested_output, "named-endpoint"), requested_generation++;
        output_route_update();
        CHECK(!out_named_active && out_channels == 6);
        fail_named_open = 0, fail_open6 = 1;
        now_ms = out_named_retry_at;
        output_route_update();
        CHECK(out_named_active && out_channels == 2 && last_channels == 2 && last_device == (unsigned)named_device);
        mixed_frame(out_channels);
        CHECK(fill_frames == 1 && !blocks_hold(7777));
    } else if (!strcmp(scenario, "named-write-failure")) {
        strcpy(requested_output, "named-endpoint"), requested_generation++;
        output_route_update();
        CHECK(out_named_active);
        out_named_retry_wait = 60000;
        fail_write = -1;
        frames(6200, 1);
        CHECK(accepted == 0 && unprepare_calls > 3000);
        CHECK(out_named_retry_wait == 60000); /* Reusing a never-queued header is not consumed audio. */
    } else if (!strcmp(scenario, "named-healthy-reset")) {
        fail_named_open = 1;
        strcpy(requested_output, "named-endpoint"), requested_generation++;
        output_route_update();
        CHECK(out_named_retry_wait > 3000);
        /* Even a long-lived healthy fallback must retain the named endpoint's backoff. */
        frames(6200, 1);
        CHECK(out_named_retry_wait > 3000);
        fail_named_open = 0;
        now_ms = out_named_retry_at;
        output_route_update();
        CHECK(out_named_active && out_named_retry_wait > 3000);
        now_ms += 60000;
        frames(NBLOCKS * 2, 0); /* Elapsed time and queued writes are not proof of consumption. */
        CHECK(out_named_retry_wait > 3000);
        complete_all();
        frames(6200, 1); /* More than 30 seconds of completed 10 ms blocks. */
        CHECK(out_named_retry_wait == 3000);
    } else if (!strcmp(scenario, "selection")) {
        CHECK(last_device == WAVE_MAPPER);
        strcpy(requested_output, "named-endpoint"), requested_generation++;
        output_route_update();
        CHECK(last_device == 1 && out_named_active && !route_state && close_calls == 1);
        requested_output[0] = 0, requested_generation++;
        output_route_update();
        CHECK(last_device == WAVE_MAPPER && !out_named_active && close_calls == 2);
    } else if (!strcmp(scenario, "named-missing")) {
        named_device = -1;
        strcpy(requested_output, "named-endpoint"), requested_generation++;
        output_route_update();
        CHECK(last_device == WAVE_MAPPER && (route_state & HOS_OUTPUT_FALLBACK));
        const int calls = open_calls;
        named_device = 73; /* The endpoint returns at a new index, beyond the former microphone-size limits. */
        output_route_update();
        CHECK(open_calls == calls);
        now_ms += 3001;
        output_route_update();
        CHECK(last_device == 73 && out_named_active && !route_state);
    } else if (!strcmp(scenario, "named-override")) {
        device_override = "7";
        strcpy(requested_output, "named-endpoint"), requested_generation++;
        output_route_update();
        CHECK(last_device == 7 && (route_state & HOS_OUTPUT_OVERRIDE) && !out_named_active);
    } else if (!strcmp(scenario, "named-format")) {
        speakers = 6, fail_open6 = 1;
        strcpy(requested_output, "named-endpoint"), requested_generation++;
        output_route_update();
        CHECK(last_device == 1 && last_channels == 2 && out_named_active);
        CHECK(out_channels == 2 && !(route_state & HOS_OUTPUT_FALLBACK));
    } else if (!strcmp(scenario, "layout-reopen")) {
        /* This PCM was mixed for stereo. Reopening as surround must drop it before the ring copy. */
        speakers = 6, default_key++, now_ms += 1001;
        mixed_frame(2);
        CHECK(out_channels == 6 && fill_frames == 0 && accepted == 0 && !blocks_hold(7777));
        frames(2, 1);
        CHECK(fill_frames == 0 && accepted == 1 && hdr[0].dwBufferLength == FRAME * 2 * 6 * 2);
        output_close();
        out_retry = 1, out_retry_at = now_ms, speakers = 2, now_ms += 1001;
        mixed_frame(6);
        CHECK(out_channels == 2 && fill_frames == 0 && accepted == 1);
        frames(2, 1);
        CHECK(accepted == 2 && hdr[0].dwBufferLength == FRAME * 2 * 2 * 2);
    } else if (!strcmp(scenario, "named-default-change")) {
        strcpy(requested_output, "named-endpoint"), requested_generation++;
        output_route_update();
        int calls = open_calls;
        default_key++, now_ms += 2000;
        frames(2, 1);
        CHECK(last_device == 1 && open_calls == calls);
    } else if (!strcmp(scenario, "pre-mix")) {
        /* Same order as renderer_main: route first, then construct PCM using the selected sink's channels. */
        speakers = 6;
        strcpy(requested_output, "named-endpoint"), requested_generation++;
        output_route_update();
        CHECK(out_channels == 6 && out_named_active && fill_frames == 0);
        mixed_frame(out_channels);
        CHECK(fill_frames == 1 && !blocks_hold(7777));
        frames(1, 1);
        CHECK(accepted == 1 && hdr[0].dwBufferLength == FRAME * 2 * 6 * 2);
        CHECK(blocks[0][FRAME * 6 - 1] == (int16_t)(100 + FRAME * 6 - 1));
    } else if (fail_open6) {
        CHECK(open_calls == 4 && last_channels == 2 && last_device == WAVE_MAPPER);   /* (5.1 on all three, then stereo) */
        CHECK(out_channels == 2 && hdr[0].dwBufferLength == FRAME * 2 * 2 * 2);
        CHECK(strstr(last_log, "default device") && strstr(last_log, "stereo"));
        logs = 0;
        if (!strcmp(scenario, "upmix")) {
            frames(10, 1);
            fail_open6 = 0;              /* the new default takes 5.1 */
            default_key = 12;
            now_ms += 1000;
            const int before = accepted;
            mixed_frame(2);              /* mixed in stereo before the move */
            CHECK(close_calls == 1 && open_calls == 5 && out_channels == 6);
            CHECK(fill_block == 0 && fill_frames == 0 && !blocks_hold(7777));   /* nothing of it queued */
            frames(2, 1);
            CHECK(accepted == before + 1 && blocks[0][FRAME * 6 - 1] == (int16_t)(FRAME * 6 - 1));
            CHECK(blocks[0][FRAME * 6] == 31);
        } else {
            frames(40, 1);
            CHECK(accepted == 20 && !logs);
        }
    } else if (opens_fail) {
        const int attempts = !strcmp(scenario, "same-layout-retry") ? 3 : 6;
        CHECK(open_calls == attempts && !wout && out_channels == 2);
        mixed_frame(2);
        CHECK(open_calls == attempts);   /* not again within the second */
        opens_fail = 0;                  /* a device plugged in, and it takes the requested layout */
        now_ms += 1000;
        mixed_frame(2);
        CHECK(wout && open_calls == attempts + 1 && !write_calls && !blocks_hold(7777));
        if (!strcmp(scenario, "same-layout-retry")) {
            CHECK(out_channels == 2 && fill_frames == 1);
            frames(1, 1);
        } else {
            CHECK(out_channels == 6 && fill_frames == 0);
            frames(2, 1);
        }
        CHECK(accepted == 1);
        CHECK(blocks[0][FRAME * out_channels] == (!strcmp(scenario, "same-layout-retry") ? 0 : 31));
    } else if (fail_open) {
        CHECK(open_calls == 3);   /* (the default, then both devices; HOS_AUDIO_DEVICE unset) */
        CHECK(!wout);
        frames(40, 1);
        CHECK(!prepare_calls && !write_calls && logs == 3);
        CHECK(strstr(last_log, "waveOutOpen") && strstr(last_log, "7"));
    } else if (open_calls != 1 || last_device != WAVE_MAPPER || logs != 1 || !strstr(last_log, "default device")) {
        CHECK(0);   /* (a working default is opened first, and named in the log) */
    } else if ((logs = 0), !strcmp(scenario, "surround")) {
        CHECK(last_channels == 6 && out_channels == 6 && strstr(last_log, "5.1"));
        CHECK(hdr[0].dwBufferLength == FRAME * 2 * 6 * 2);   /* (two frames of six 16-bit channels) */
        frames(40, 1);
        CHECK(accepted == 20 && prepare_calls == 20 && write_calls == 20 && !logs);
        CHECK(blocks[9][0] == 38 * 31 && blocks[9][FRAME * 6] == 39 * 31);
        CHECK(blocks[9][FRAME * 6 - 1] == (int16_t)(38 * 31 + FRAME * 6 - 1));
    } else if (!strcmp(scenario, "downmix")) {
        CHECK(out_channels == 6);
        frames(10, 1);
        fail_open6 = 1;                  /* the new default takes stereo only */
        default_key = 12;
        now_ms += 1000;
        const int before = accepted;
        mixed_frame(6);
        CHECK(close_calls == 1 && out_channels == 2 && hdr[0].dwBufferLength == FRAME * 2 * 2 * 2);
        CHECK(fill_block == 0 && fill_frames == 0);   /* the 5.1 frame not queued as two stereo ones */
        frames(2, 1);
        CHECK(accepted == before + 1 && blocks[0][FRAME * 2 - 1] == (int16_t)(FRAME * 2 - 1));
        CHECK(blocks[0][FRAME * 2] == 31);
    } else if (!strcmp(scenario, "lost")) {
        gone_write_at = 25;              /* a Bluetooth headset off: its 25th block, "no driver" */
        frames(60, 1);
        CHECK(reset_calls == 1 && close_calls == 1 && open_calls == 2 && last_device == WAVE_MAPPER);
        CHECK(accepted >= 28);           /* the default took the blocks after it */
    } else if (!strcmp(scenario, "gone")) {
        frames(20, 1);
        gone_unprepare = 1;              /* the audio service restarted: every call on the old handle "invalid" */
        frames(2, 1);
        CHECK(close_calls == 1 && open_calls == 2 && last_device == WAVE_MAPPER);
        const int before = accepted;
        frames(10, 1);
        CHECK(accepted == before + 5);   /* (before, the same block tried again for good: no sound for the run) */
    } else if (!strcmp(scenario, "service")) {
        frames(10, 1);
        opens_fail = 1;                  /* the service down: no device opens */
        gone_write_at = write_calls + 1;
        frames(2, 1);
        CHECK(close_calls == 1 && !wout && open_calls == 4);   /* (the first open, then the default and both devices) */
        frames(5, 1);
        CHECK(open_calls == 4);          /* not again within the second */
        now_ms += 1000;
        frames(1, 1);
        CHECK(open_calls == 7 && !wout); /* a second later: all three again, the service still down */
        opens_fail = 0;
        now_ms += 1000;
        frames(1, 1);
        CHECK(wout && open_calls == 8 && last_device == WAVE_MAPPER);   /* the service back: the default first */
        const int before = accepted;
        frames(4, 1);
        CHECK(accepted == before + 2);
    } else if (!strcmp(scenario, "default")) {
        frames(10, 1);
        default_key = 12;                /* Windows moves its default (the headset back) */
        now_ms += 500;
        frames(1, 1);
        CHECK(open_calls == 1);          /* looked at once a second */
        now_ms += 600;
        frames(1, 1);
        CHECK(close_calls == 1 && open_calls == 2 && last_device == WAVE_MAPPER && out_default_key == 12);
        CHECK(fill_frames == 1);         /* stereo again: the frame mixed before the move kept */
        now_ms += 2000;
        frames(2, 1);
        CHECK(open_calls == 2);          /* the same default: not opened again */
        const int before = accepted;
        frames(4, 1);
        CHECK(accepted == before + 2);
    } else if (!strcmp(scenario, "stall")) {
        frames(20, 0);                   /* every block queued, none ever completes: the device takes nothing */
        now_ms += 1000;
        frames(1, 0);                    /* the stall noticed */
        CHECK(open_calls == 1);
        now_ms += 1600;
        frames(1, 0);                    /* 1.6 s later: closed, the next candidate (device 0) opened */
        CHECK(reset_calls == 1 && close_calls == 1 && open_calls == 2 && last_device == 0);
        CHECK(strstr(last_log, "test device 0"));
        const int before = accepted;
        frames(4, 1);
        CHECK(accepted == before + 2);   /* the new device takes blocks */
    } else if (fail_prepare > 0 || fail_write) {
        frames(40, 1);
        fprintf(stderr, "ring %s: accepted %d, prepare %d, write %d\n", scenario, accepted, prepare_calls, write_calls);
        CHECK(accepted == 19); /* One failed block, then the same slot works on the next ring. */
        CHECK(fill_block == 0 && fill_frames == 0);
        CHECK(logs == 1);
        if (fail_prepare) CHECK(write_calls == 19); /* Never write an unprepared header. */
    } else if (fail_unprepare) {
        frames(20, 1);
        int16_t before[FRAME * 4];
        memcpy(before, blocks[0], sizeof before);
        frames(1, 0);
        CHECK(fill_frames == 0 && fill_block == 0);
        CHECK(!memcmp(before, blocks[0], sizeof before));
        CHECK(hdr[0].dwFlags == (WHDR_DONE | WHDR_PREPARED));
        frames(2, 1);
        CHECK(accepted == 11 && unprepare_calls == 2 && logs == 1);
    } else if (!strcmp(scenario, "busy")) {
        frames(20, 0);
        int16_t before[FRAME * 4];
        memcpy(before, blocks[0], sizeof before);
        frames(5, 0);
        CHECK(accepted == 10 && fill_frames == 0 && fill_block == 0);
        CHECK(!memcmp(before, blocks[0], sizeof before));
        CHECK(!unprepare_calls);
        complete_all();
        frames(2, 1);
        CHECK(accepted == 11);
    } else if (fail_prepare < 0) {
        frames(80, 1);
        CHECK(prepare_calls == 40 && write_calls == 0 && accepted == 0);
        CHECK(logs > 0 && logs <= 8);
    } else {
        CHECK(!strcmp(scenario, "normal"));
        frames(40, 1);
        CHECK(accepted == 20 && prepare_calls == 20 && write_calls == 20 && unprepare_calls == 10);
        CHECK(fill_block == 0 && fill_frames == 0 && !logs);
        CHECK(blocks[9][0] == 38 * 31 && blocks[9][FRAME * 2] == 39 * 31);
    }
    printf("PASS %s: actual output ring\n", scenario);
    return 0;
}
