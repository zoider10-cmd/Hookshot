/* SPDX-License-Identifier: GPL-3.0-or-later
 * Appended to test_audio_in.py's fake SDL/clock/HLE fixture by test_microphone_test_gain.py.
 * The source under test is the real nn_audio_in.c; no microphone, game or window is opened. */
#include <assert.h>
#include <limits.h>

static void stop_guest(uint64_t *s) {
    CALL(imp__ZN2nn5audio15StopInputStreamEPNS0_15InputStreamTypeE, U(s));
    CALL(imp__ZN2nn5audio16CloseInputStreamEPNS0_15InputStreamTypeE, U(s));
}

static void sample_formats(void) {
    Source src = {0};
    int16_t pcm16[] = {INT16_MIN, -10001, 0, 10001, INT16_MAX}, original[5];
    memcpy(original, pcm16, sizeof pcm16);
    src.format = FMT_PCM16;
    mic_gain = 100;
    mic_process(&src, (uint8_t *)pcm16, sizeof pcm16, clock_ns);
    assert(!memcmp(original, pcm16, sizeof pcm16));
    mic_gain = 200;
    mic_process(&src, (uint8_t *)pcm16, sizeof pcm16, clock_ns);
    assert(pcm16[0] == INT16_MIN && pcm16[1] == -20002 && pcm16[3] == 20002 && pcm16[4] == INT16_MAX);
    assert(src.input_peak == 1000 && src.output_peak == 1000 && src.clip_until > clock_ns);
    mic_gain = 0;
    mic_process(&src, (uint8_t *)pcm16, sizeof pcm16, clock_ns);
    for (int i = 0; i < 5; i++) assert(pcm16[i] == 0);

    int8_t pcm8[] = {INT8_MIN, -100, 100, INT8_MAX};
    src.format = FMT_PCM8, mic_gain = 400;
    mic_process(&src, (uint8_t *)pcm8, sizeof pcm8, clock_ns);
    assert(pcm8[0] == INT8_MIN && pcm8[1] == INT8_MIN && pcm8[2] == INT8_MAX && pcm8[3] == INT8_MAX);
    int32_t pcm32[] = {INT32_MIN, -1000000000, 1000000000, INT32_MAX};
    src.format = FMT_PCM32;
    mic_process(&src, (uint8_t *)pcm32, sizeof pcm32, clock_ns);
    assert(pcm32[0] == INT32_MIN && pcm32[1] == INT32_MIN && pcm32[2] == INT32_MAX && pcm32[3] == INT32_MAX);
    int32_t half[] = {INT32_MIN, INT32_MAX};
    mic_gain = 50;
    mic_process(&src, (uint8_t *)half, sizeof half, clock_ns);
    assert(half[0] == -1073741824 && half[1] == 1073741823);

    float fp[] = {-INFINITY, NAN, INFINITY, -1.0f, -0.25f, 0.25f, 1.0f};
    src.format = FMT_FLOAT, mic_gain = 400;
    mic_process(&src, (uint8_t *)fp, sizeof fp, clock_ns);
    assert(fp[0] == 0 && fp[1] == 0 && fp[2] == 0 && fp[3] == -1 && fp[4] == -1 && fp[5] == 1 && fp[6] == 1);
    /* Unaligned storage and finite float unity, including negative zero. */
    float normal[] = {-0.0f, -0.12345f, 0.98765f};
    uint8_t unaligned[sizeof normal + 1];
    memcpy(unaligned + 1, normal, sizeof normal);
    mic_gain = 100;
    mic_process(&src, unaligned + 1, sizeof normal, clock_ns);
    assert(!memcmp(unaligned + 1, normal, sizeof normal));
    /* Meter peaks decay under continuous capture, not just after silence. */
    MS(200);
    float quiet = 0.1f;
    mic_process(&src, (uint8_t *)&quiet, sizeof quiet, clock_ns);
    assert(src.input_peak <= 101 && src.output_peak <= 101);
    puts("PASS: unity, attenuation, saturation, signed limits, all accepted formats, non-finite floats, unaligned samples, meter decay");
}

int main(void) {
    static uint8_t names[1][256], work[0x4000];
    static uint64_t stream[0x360 / 8], other[0x360 / 8];
    static const uint32_t format[4] = {2, 1, 48000, 0};
    int levels[2], state;
    int16_t buf[8], buf2[8];
    sample_formats();
    hos_mic_select(0, "", -1);
    assert(hos_mic_test(1, 100, levels) == 32 && opens == 0);
    hos_mic_select(1, "", -1);
    assert(hos_mic_test(0, -1, levels) == 0 && opens == 0 && mic_gain == 0);
    assert(hos_mic_test(0, 900, levels) == 0 && mic_gain == 400);
    assert(hos_mic_test(1, 200, levels) == 3 && opened == 1);
    mic_bytes = 4, next_sample = 20000;
    state = hos_mic_test(1, 200, levels);
    assert((state & 27) == 27 && levels[0] >= 610 && levels[1] >= 999);
    MS(300);
    state = hos_mic_test(1, 200, levels);
    assert(!(state & 8) && levels[0] == 0 && levels[1] == 0);
    MS(800);
    assert(!(hos_mic_test(1, 200, levels) & 16));
    assert(hos_mic_test(0, 100, levels) == 0 && closed == 1);
    puts("PASS: explicit start/stop, Off, gain bounds, fresh/stale levels, clipping hold");

    /* Game first: two guest streams and test share one source and one gain pass. */
    assert(OPEN(stream, names[0]) == 0 && START(stream) == 0);
    assert(OPEN(other, names[0]) == 0 && START(other) == 0);
    int before = opened, closes = closed;
    assert(hos_mic_test(1, 200, levels) & 1);
    assert(opened == before);
    mic_bytes = 8, next_sample = 1000;
    hos_mic_test(1, 200, levels);
    assert(READ(stream, buf, 4) == 4 && READ(other, buf2, 4) == 4);
    assert(buf[0] == 2000 && buf[3] == 2006 && !memcmp(buf, buf2, 8));
    hos_mic_test(0, 100, levels);
    assert(closed == closes);
    stop_guest(stream); assert(closed == closes);
    stop_guest(other); assert(closed == closes + 1);
    puts("PASS: game-first sharing, identical guest streams, gain once, stopping test retains game capture");

    /* Test first: queued test audio is drained before the first game stream joins. */
    assert(hos_mic_test(1, 100, levels) & 1);
    before = opened, closes = closed;
    mic_bytes = 8, next_sample = 30000;
    assert(OPEN(stream, names[0]) == 0 && START(stream) == 0);
    assert(opened == before && FILLED(stream) == 0 && mic_bytes == 0);
    mic_bytes = 4, next_sample = 7;
    assert(READ(stream, buf, 2) == 2 && buf[0] == 7 && buf[1] == 8);
    stop_guest(stream);
    assert(closed == closes && (hos_mic_test(1, 100, levels) & 1));
    hos_mic_select(0, "", -1);
    assert(hos_mic_test(1, 100, levels) == 32 && closed == closes + 1);
    puts("PASS: test-first handoff drops old test samples; stopping game retains test; Off releases test");

    hos_mic_select(2, "Missing microphone", -1);
    state = hos_mic_test(1, 100, levels);
    assert((state & 7) == 7);  /* selected name missing, default stands in */
    hos_mic_test(0, 100, levels);
    no_default = 1;
    assert(hos_mic_test(1, 100, levels) == 1 && levels[0] == 0);
    hos_mic_test(0, 100, levels);
    no_default = 0;
    puts("PASS: fallback is reported, unavailable capture has no fabricated level");

    /* All four guest sources may exist at once: test has its own reserved slot. */
    for (int i = 0; i < MAX_STREAMS; i++) {
        streams[i].used = streams[i].started = 1;
        streams[i].format = FMT_PCM16, streams[i].channels = 1;
        streams[i].rate = 8000 + i * 1000, streams[i].frame_bytes = 2;
        streams[i].source = -1;
        attach(&streams[i]);
    }
    assert(hos_mic_test(1, 100, levels) & 1);
    assert(test_stream.source == MAX_STREAMS);
    hos_mic_test(0, 100, levels);
    for (int i = 0; i < MAX_STREAMS; i++) detach(&streams[i]);
    puts("PASS: test reference does not exhaust guest stream/source capacity");
    assert(logged > 0); // capture opens/fallbacks still reach the host log
    return 0;
}
