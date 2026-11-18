/* (hookshot) The sound manager's job at 60 Hz, the physics solver's steps rounded up, a horse's jump blend, a moving
   floor's carry and a song playback's note flag once a note, under a Frame rate cap above 60, the cloth's time below 60
   fps and its solves above 60: the lifted f_80435300, f_83373400, f_838ceb80, f_838cfc10, f_82c59eb0, f_80159dc0,
   f_8015d490, f_838baa40, f_81b3aa48, f_81b47080, f_832b2af0 and f_832b2dc0 call these (nx2/oot_patches.py);
   host/oot_high_fps.h has why and the logic.
   HOS_FPS_LOG (on, by the switches' rule: =0 is off): what they do, every 600 calls. */
#include "hos.h"
#include "oot_high_fps.h"
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdlib.h>

#include "../gpu/vk/compat/hookshot_env.h" /* (env_on: the switches' one rule) */

extern volatile uint32_t hos_frame_seconds_bits;   /* (host/nn_vi.c: the frame's seconds, 0 at a cap of 60) */
extern volatile uint64_t hos_step_probe;           /* (host/nn_vi.c: f_80706be0's object, its +0xd58 the game clock in 60ths) */

static int timed(void) { return __atomic_load_n(&hos_frame_seconds_bits, __ATOMIC_RELAXED) != 0; }
static int fps_log(void) {
    static int on = -1;   /* (read by the game's threads) */
    int v = __atomic_load_n(&on, __ATOMIC_RELAXED);
    if (v < 0) v = env_on("HOS_FPS_LOG"), __atomic_store_n(&on, v, __ATOMIC_RELAXED);
    return v;
}

static OotSoundGate sound_gate = OOT_SOUND_GATE_INIT;
static long long sound_calls, sound_runs;   /* (HOS_FPS_LOG's counts, under sound_lock) */
static SRWLOCK sound_lock = SRWLOCK_INIT;   /* (the job's phases may come from different threads) */
static uint64_t bgm_flags_at;   /* (the guest address of the music manager's change flags, from its last read; under sound_lock) */
static uint8_t bgm_held;        /* (the flags seen on frames the gate held the job, since the update last ran; under sound_lock) */
/* shortcut: one bit set on two held frames between runs is handled once (bit 6 then counts down once); count per bit if that is
   ever seen to matter */
static uint8_t bgm_run;         /* (those, handed to the update's run: its own thread) */
static long long sound_job_runs;   /* (phase 0's runs, for the song playbacks' note flag; under sound_lock) */
static OotSongCue song_cue[2];     /* (each playback's last read of it; under sound_lock) */
static long long cue_reads, cue_held;   /* (HOS_FPS_LOG's counts, under sound_lock) */

/* f_80435300's head: phase w2, slot the guest address of the pointer to the object whose +0x10 is the game step (the job's own
   load). 0: the job returns at once */
int hos_oot_sound_gate(Ctx *c, uint32_t phase, uint64_t slot) {
    (void)c;
    float step = 1.0f;
    const int t = timed();
    if (t && phase == 0) {
        const uint64_t object = G64(slot);
        const uint64_t time = object ? G64(object) : 0;
        if (time) step = oot_bits_float(*(const uint32_t *)GP(time + 0x10));
    }
    long long ran = -1;
    AcquireSRWLockExclusive(&sound_lock);
    const int run = oot_sound_gate(&sound_gate, phase, step, t);
    if (!run && bgm_flags_at) bgm_held |= *(const uint8_t *)GP(bgm_flags_at);   /* (what the update would have read now) */
    if (run && phase == 0) sound_job_runs++;
    if (phase == 0 && fps_log()) {
        sound_runs += run;
        if (!(++sound_calls % 600)) ran = sound_runs, sound_runs = 0;
    }
    ReleaseSRWLockExclusive(&sound_lock);
    if (ran >= 0)
        hos_log("oot: sound job ran %lld of the last 600 frames (step %.3f%s)", ran, step,
                oot_sound_partial(step, t) ? ", held to 60 Hz" : "");
    return run;
}

/* After f_832b7b50 in a song's playback (site 0: f_832b2af0, the song just played; 1: f_832b2dc0, the ocarina's other melody
   playback): game, its result (bit 0: the note flag is set). Above a cap of 60, bit 0 cleared when the flag was read set before
   and the sound job has not run since */
uint64_t hos_oot_song_cue(uint32_t site, uint64_t game) {
    const int t = timed();
    long long held = -1;
    AcquireSRWLockExclusive(&sound_lock);
    const int cue = oot_song_cue(&song_cue[site & 1], (int)(game & 1), sound_job_runs, t);
    if (t && fps_log()) {
        cue_held += (int)(game & 1) && !cue;
        if (!(++cue_reads % 600)) held = cue_held, cue_held = 0;
    }
    ReleaseSRWLockExclusive(&sound_lock);
    if (held >= 0) hos_log("oot: a song's playback read its note flag set again before the sound job ran %lld of the last 600 reads", held);
    return cue ? game : game & ~(uint64_t)1;
}

/* The step f_80435300's phase 0 hands to the sound engine, and the music manager's update f_83373400 reads (its float's bits) */
uint32_t hos_oot_sound_step(uint32_t step_bits) {
    return oot_sound_step(step_bits, timed());
}

/* The frame's seconds f_83373400 reads, with the step beside it (floats' bits) */
uint32_t hos_oot_sound_seconds(uint32_t seconds_bits, uint32_t step_bits) {
    return oot_sound_seconds(seconds_bits, step_bits, timed());
}

/* f_83373400's head: the change flags held back since its last run are this run's */
void hos_oot_bgm_begin(void) {
    AcquireSRWLockExclusive(&sound_lock);
    bgm_run = bgm_held;
    bgm_held = 0;
    ReleaseSRWLockExclusive(&sound_lock);
}

/* f_83373400's reads of the change flags (at, their guest address; flags, the byte it read): with the ones held back */
uint64_t hos_oot_bgm_flags(uint64_t at, uint64_t flags) {
    AcquireSRWLockExclusive(&sound_lock);
    bgm_flags_at = at;
    ReleaseSRWLockExclusive(&sound_lock);
    return flags | bgm_run;
}

/* The solver steps of f_838ceb80 / f_838cfc10: game, the game's count; scaled_bits, the float it cut; per_frame_bits, the steps
   of a 60 fps frame (a float) */
uint32_t hos_oot_solver_steps(uint32_t game, uint32_t scaled_bits, uint32_t per_frame_bits) {
    const int32_t steps = oot_solver_steps((int32_t)game, scaled_bits, per_frame_bits, timed());
    if (fps_log()) {
        static volatile LONG64 calls;
        const LONG64 n = InterlockedIncrement64(&calls);
        if (n % 600 == 1)
            hos_log("oot: physics solver steps %d (the game's %d: frame step %.3f x %.0f steps a 60 fps frame)", steps, (int32_t)game,
                    (oot_bits_float(scaled_bits) - 0.001f) / oot_bits_float(per_frame_bits), oot_bits_float(per_frame_bits));
    }
    return (uint32_t)steps;
}

/* f_82c59eb0's test of its step against 1 (a horse's jump): step_bits its step (a float's bits), slot the guest address of the
   pointer to the time object (+0x10 this frame's step). 1: the step is the whole frame's, the branch for steps under 1 is skipped */
int hos_oot_horse_whole_step(uint32_t step_bits, uint64_t slot) {
    const int t = timed();
    uint32_t frame = 0;
    if (t) {
        const uint64_t object = G64(slot);
        const uint64_t time = object ? G64(object) : 0;
        if (time) frame = *(const uint32_t *)GP(time + 0x10);
    }
    const int whole = oot_horse_whole_step(step_bits, frame, t);
    if (fps_log()) {
        static volatile LONG64 calls, skipped;
        const LONG64 s = whole ? InterlockedIncrement64(&skipped) : skipped;
        const LONG64 n = InterlockedIncrement64(&calls);
        if (n % 600 == 0)
            hos_log("oot: a horse's jump blend: the whole-frame step skipped the slow-motion branch %lld of %lld times (step %.3f, "
                    "the frame's %.3f)", (long long)s, (long long)n, oot_bits_float(step_bits), oot_bits_float(frame));
    }
    return whole;
}

/* f_80159dc0's, f_8015d490's and f_838baa40's slow-time test before they carry a character by a tenth of its floor's velocity
   (inv_dt_bits: the physics' 1/dt, which was over 100; slot as for the horse's step): 1, the tenth (the game's verdict) */
int hos_oot_floor_carry_slow(uint32_t inv_dt_bits, uint64_t slot) {
    const uint64_t object = G64(slot);
    const uint64_t time = object ? G64(object) : 0;
    const uint32_t frame = time ? *(const uint32_t *)GP(time + 0x10) : 0;
    const int slow = oot_floor_carry_slow(inv_dt_bits, frame, timed());
    if (fps_log()) {
        static volatile LONG64 calls, kept;
        const LONG64 k = slow ? InterlockedIncrement64(&kept) : kept;
        const LONG64 n = InterlockedIncrement64(&calls);
        if (n % 600 == 0)
            hos_log("oot: a moving floor's carry: the slow-time tenth kept %lld of %lld times (1/dt %.1f, the frame's step %.3f)",
                    (long long)k, (long long)n, oot_bits_float(inv_dt_bits), oot_bits_float(frame));
    }
    return slow;
}

/* The time f_81b3aa48 loads from the cloth's step context, times the game's frame step below 60 fps (floats' bits). HOS_FPS_CLOTH=0
   (or off, false, no): the game's, a 60th a frame */
uint32_t hos_oot_cloth_seconds(uint32_t seconds_bits, uint32_t step_bits) {
    static int on = -1;   /* (read by the game's threads) */
    int v = __atomic_load_n(&on, __ATOMIC_RELAXED);
    if (v < 0) {
        const char *e = getenv("HOS_FPS_CLOTH");
        v = !(e && *e && env_value_off(e));
        __atomic_store_n(&on, v, __ATOMIC_RELAXED);
    }
    const uint32_t seconds = oot_cloth_seconds(seconds_bits, step_bits, v);
    if (fps_log()) {
        static volatile LONG64 calls;
        const LONG64 n = InterlockedIncrement64(&calls);
        if (n % 600 == 1)
            hos_log("oot: cloth time %.2f ms (the game's %.2f ms: frame step %.3f%s; %lld setups)", oot_bits_float(seconds) * 1000.0f,
                    oot_bits_float(seconds_bits) * 1000.0f, oot_bits_float(step_bits), v ? "" : ", HOS_FPS_CLOTH=0", (long long)n);
    }
    return seconds;
}

static OotClothGate cloth_gate = OOT_CLOTH_GATE_INIT;
static long long cloth_calls, cloth_solves;   /* (HOS_FPS_LOG's counts, under cloth_lock) */
static SRWLOCK cloth_lock = SRWLOCK_INIT;     /* (the solve jobs run on the game's job workers, several at once) */

/* f_81b47080's head, the cloth's solve job: step_bits the game's frame step (the float f_83b6ea90 writes). 0: the job returns at
   once, the cloth held this frame. HOS_FPS_CLOTH_60=1 (by the switches' rule): at most 60 solves a second above a cap of 60 */
int hos_oot_cloth_solve(uint32_t step_bits) {
    static int on = -1;   /* (read by the game's threads) */
    int v = __atomic_load_n(&on, __ATOMIC_RELAXED);
    if (v < 0) v = env_on("HOS_FPS_CLOTH_60"), __atomic_store_n(&on, v, __ATOMIC_RELAXED);
    const int t = timed();
    if (!v || !t) return 1;   /* (off, or a cap of 60: every job solves, and no lock taken) */
    double clock = NAN;   /* (no clock: the gate stands aside) */
    const uint64_t probe = __atomic_load_n(&hos_step_probe, __ATOMIC_RELAXED);
    if (probe) memcpy(&clock, GP(probe + 0xd58), 8);
    const float step = oot_bits_float(step_bits);
    long long solved = -1, calls = 0;
    AcquireSRWLockExclusive(&cloth_lock);
    const int solve = oot_cloth_gate(&cloth_gate, clock, step, v, t);
    if (fps_log()) {
        cloth_solves += solve;
        if (!(++cloth_calls % 600)) solved = cloth_solves, calls = cloth_calls, cloth_solves = 0;
    }
    ReleaseSRWLockExclusive(&cloth_lock);
    if (solved >= 0)
        hos_log("oot: cloth solved %lld of the last 600 solve jobs (step %.3f, HOS_FPS_CLOTH_60; %lld jobs)", solved, step, calls);
    return solve;
}
