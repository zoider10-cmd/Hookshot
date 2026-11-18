"""A song's playback after the ocarina above 60 fps (nx2/oot_patches.py patch_song_cue, host/oot_high_fps.h oot_song_cue).

After a song is played on the ocarina the game plays its melody and shows its notes one at a time with it. Each update while
the melody plays, the playback (f_832b2af0; f_832b2dc0 is the ocarina's other melody playback, the same code) asks f_832b7b50
whether the note flag is set: a word beside the melody's sound handle that the sound engine sets when the melody reaches a note
and clears on its next run. When it is set, the playback goes on to the next note. The sound engine runs in the sound job,
which runs at 60 Hz above 60 fps, so the flag stayed set for two or three game updates at 120 to 165 fps and each one went on a
note: the notes came two or three at a time, ahead of the music. The patch passes the flag through the host after each of the
two calls: read again before the sound job has run again, a set flag is the same note.

An authored update for each playback (the call's lift text, the game's branch on its result, a stand-in for going on a note)
goes through patch_file and is compiled with host/oot_high_fps.c whole (guest memory, its lock and the switches as stand-ins)
and a stand-in sound engine that sets the flag for one run at each note of a six-note melody (Zelda's Lullaby's spacing, as
the game played it at 60 fps). Frames run as the game runs them: the sound job's phases through the host's gate, then both
playbacks:
- at 120, 144, 165 and 240 fps, at 90, uncapped with each frame's time varying, at 60 and about 60 with a cap above 60, a frame
  slower than 60 fps and a cap of 60, each playback goes on one note at each of the melody's notes after the first, on the sound job's run
  that set it (as at 60 fps);
- two notes on consecutive runs of the sound engine (a long frame's step can bring them) are two notes, at 120 fps, on frames
  slower than 60 fps and at a cap of 60, and at 75, 90, 144 and 165 fps, uncapped with each frame's time varying and about
  60 fps (steps of 0.98 to 1.02) with the pair at four places in the melody: the flag set again by the next run is a new
  note, however close in time the two runs are;
- at a cap of 60 the host hands back the game's own: a playback read twice a frame goes on two notes at each, as the game would;
- the unpatched updates compiled the same way fail the 120 fps check (the bug, shown without the fix);
- the patch is scoped to its two functions, a second run changes nothing, and a changed anchor is left alone with a warning.
No game files or lifted function body are used.

python -I -B tests/test_song_note_cue.py [--cc gcc]
"""
import argparse
import contextlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import oot_patches  # noqa: E402

# (the two playbacks as the lift writes the call and the branch on its result; the game's going on a note as a stand-in)
PLAYED_HEAD = "void f_832b2af0(Ctx *__restrict A64_NOESC c) {\n"
PLAYED_CALL = "c->x[30] = 0x832b2c84ULL; f_832b7b50(c);\n"
OTHER_HEAD = "void f_832b2dc0(Ctx *__restrict A64_NOESC c) {\n"
OTHER_CALL = "c->x[30] = 0x832b2ed4ULL; f_832b7b50(c);\n"
PLAYED = (PLAYED_HEAD + "    { uint64_t _a=c->x[8], _b=32ULL; uint64_t _r=_a+_b; c->x[0]=_r; }\n" + PLAYED_CALL
          + "if (!((c->x[0] >> 0) & 1)) { goto L_832b2c94; }\n"
          + "    next_note(0);   /* (the game's: the next note when one was waiting) */\n"
          + "L_832b2c94:;\n}\n")
OTHER = (OTHER_HEAD + "    { uint64_t _a=c->x[8], _b=32ULL; uint64_t _r=_a+_b; c->x[0]=_r; }\n" + OTHER_CALL
         + "if (!((c->x[0] >> 0) & 1)) { goto L_832b3044; }\n"
         + "    next_note(1);\n"
         + "L_832b3044:;\n}\n")
UNRELATED = PLAYED.replace("f_832b2af0", "f_932b2af0").replace("next_note(0)", "unrelated++")
LIFTED = '#include "a64.h"\n' + PLAYED + OTHER + UNRELATED

# (stand-ins for the host file's and the lift's world: guest memory as one array with the time object's slot, a lock that is
# none, the switches on, no log)
RUNTIME = r'''#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "oot_high_fps.h"
typedef struct { uint64_t x[32]; } Ctx;
#define A64_NOESC
static uint8_t mem[0x3000];
static uint8_t *guest(uint64_t a) {
    if (a == 0x84c9e890ULL) return mem + 0x100;   /* (the time object's slot) */
    return a < sizeof mem ? mem + a : mem;
}
#define GP(a) ((void *)guest(a))
#define G64(a) (*(uint64_t *)GP(a))
typedef int SRWLOCK;
#define SRWLOCK_INIT 0
static void AcquireSRWLockExclusive(SRWLOCK *l) { (void)l; }
static void ReleaseSRWLockExclusive(SRWLOCK *l) { (void)l; }
typedef long long LONG64;
static LONG64 InterlockedIncrement64(volatile LONG64 *p) { return ++*p; }
static void hos_log(const char *f, ...) { (void)f; }
static int env_on(const char *name) { (void)name; return 1; }
volatile uint32_t hos_frame_seconds_bits;
static int unrelated;
static void next_note(int playback);
static uint32_t flag;   /* (the note flag: the sound engine's word) */
/* (the game's: whether the flag is set) */
static void f_832b7b50(Ctx *c) { c->x[0] = flag != 0; }
'''

FRAMES = r'''
#define NOTES 6
static const int lullaby[NOTES] = {10, 60, 85, 165, 218, 246};   /* (the sound engine's runs at which the melody reaches a note) */
static const int close_notes[NOTES] = {10, 60, 61, 165, 218, 246};   /* (two on consecutive runs: a long frame's step) */
static const int *melody = lullaby;
static int runs, note[2], waiting[2], went[2][16];
static Ctx ctx;
/* (the game's going on a note: the first note's flag sets the note waiting, each one after goes on to the next; on the sound
   engine's run it happened) */
static void next_note(int playback) {
    if (waiting[playback]) {
        if (note[playback] < 16) went[playback][note[playback]] = runs;
        note[playback]++;
    }
    waiting[playback] = 1;
}
/* (the sound engine's run: the flag set for this run when the melody reaches a note, else clear) */
static void sound_engine(void) {
    runs++;
    flag = 0;
    for (int i = 0; i < NOTES; i++)
        if (melody[i] == runs) flag = 0x100000;
}
/* one game frame of step (60 / its fps; with no frame time at a cap of 60): the sound job's phases through the gate, then the
   two playbacks, reads times each */
static void frame(float step, int timed_now, int reads) {
    const float seconds = step / 60.0f;
    hos_frame_seconds_bits = timed_now ? oot_float_bits(seconds) : 0;
    memcpy(mem + 0x2010, &step, 4);
    for (uint32_t phase = 0; phase < 3; phase++)
        if (hos_oot_sound_gate(&ctx, phase, 0x84c9e890ULL) && phase == 0) sound_engine();
    for (int r = 0; r < reads; r++) {
        f_832b2af0(&ctx);
        f_832b2dc0(&ctx);
    }
}
static int failures, checks;
/* a melody's playback at a step (jitter: each frame's step varies around it by up to that much; reads, the playbacks' reads
   a frame), expected to go on per_note notes at each of the melody's notes after the first one's (whose first sets the note
   waiting) */
static void run(const char *what, const int *notes, float step, float jitter, int timed_now, int reads, int per_note) {
    int expected[16], n = 0;
    for (int i = 0; i < NOTES; i++)
        for (int k = 0; k < per_note; k++)
            if (i || k) expected[n++] = notes[i];
    melody = notes;
    memset(note, 0, sizeof note);
    memset(waiting, 0, sizeof waiting);
    memset(went, 0, sizeof went);
    runs = 0;
    flag = 0;
    hos_frame_seconds_bits = 0;
    for (uint32_t phase = 0; phase < 3; phase++) hos_oot_sound_gate(&ctx, phase, 0x84c9e890ULL);   /* (the gate starts afresh) */
    runs = 0;
    uint32_t seed = 1;
    for (int i = 0; i < 100000 && runs < 300; i++) {
        seed = seed * 1664525u + 1013904223u;
        const float s = step + jitter * ((float)(seed >> 8) / 8388608.0f - 1.0f);
        frame(s, timed_now, reads);
    }
    for (int p = 0; p < 2; p++) {
        checks++;
        int ok = note[p] == n;
        for (int i = 0; ok && i < n; i++) ok = went[p][i] == expected[i];
        if (!ok) {
            printf("FAIL: %s: playback %d went on %d notes, on the sound engine's runs", what, p, note[p]);
            for (int i = 0; i < note[p] && i < 16; i++) printf(" %d", went[p][i]);
            printf(" (expected %d:", n);
            for (int i = 0; i < n; i++) printf(" %d", expected[i]);
            printf(")\n");
            failures++;
        }
    }
}
int main(void) {
    const uint64_t time_at = 0x1000, time_obj = 0x2000;
    memcpy(mem + 0x100, &time_at, 8);
    memcpy(mem + 0x1000, &time_obj, 8);
    run("120 fps", lullaby, 0.5f, 0.0f, 1, 1, 1);
    run("144 fps", lullaby, 60.0f / 144.0f, 0.0f, 1, 1, 1);
    run("165 fps", lullaby, 60.0f / 165.0f, 0.0f, 1, 1, 1);
    run("240 fps", lullaby, 0.25f, 0.0f, 1, 1, 1);
    run("90 fps", lullaby, 60.0f / 90.0f, 0.0f, 1, 1, 1);
    run("uncapped, each frame's time varying (100 to 300 fps)", lullaby, 0.4f, 0.2f, 1, 1, 1);
    run("60 fps under a cap above 60", lullaby, 1.0f, 0.0f, 1, 1, 1);
    run("a frame slower than 60 fps", lullaby, 1.25f, 0.0f, 1, 1, 1);
    run("a cap of 60", lullaby, 1.0f, 0.0f, 0, 1, 1);
    run("120 fps, two notes on consecutive runs of the sound engine", close_notes, 0.5f, 0.0f, 1, 1, 1);
    run("a frame slower than 60 fps, two notes on consecutive runs", close_notes, 1.25f, 0.0f, 1, 1, 1);
    run("a cap of 60, two notes on consecutive runs", close_notes, 1.0f, 0.0f, 0, 1, 1);
    run("a cap of 60, the playbacks read twice a frame (the game's own: two notes at each)", lullaby, 1.0f, 0.0f, 0, 2, 2);
    run("about 60 fps under a cap above 60 (steps 0.98 to 1.02)", lullaby, 1.0f, 0.02f, 1, 1, 1);
    /* (two notes on consecutive runs at a few places in the melody, at rates whose runs don't fall evenly: the gate's
       remainder can put two runs less than a 60 fps frame apart, so a rule by time rather than by the job's runs fails) */
    static const float rates[] = {75.0f, 90.0f, 144.0f, 165.0f};
    for (int k = 0; k < 4; k++) {
        const int pair[NOTES] = {10, 60 + k, 61 + k, 165, 218, 246};
        char what[160];
        for (int r = 0; r < 4; r++) {
            snprintf(what, sizeof what, "%g fps, two notes on consecutive runs (%d and %d)", rates[r], 60 + k, 61 + k);
            run(what, pair, 60.0f / rates[r], 0.0f, 1, 1, 1);
        }
        snprintf(what, sizeof what, "uncapped, each frame's time varying, two notes on consecutive runs (%d and %d)", 60 + k, 61 + k);
        run(what, pair, 0.4f, 0.2f, 1, 1, 1);
        snprintf(what, sizeof what, "about 60 fps (steps 0.98 to 1.02), two notes on consecutive runs (%d and %d)", 60 + k, 61 + k);
        run(what, pair, 1.0f, 0.02f, 1, 1, 1);
    }
    if (unrelated) {
        printf("FAIL: the unrelated function went through the host\n");
        failures++;
    }
    if (!failures) printf("PASS: a song's playback goes on one note at each of its melody's notes (%d checks)\n", checks);
    return failures != 0;
}
'''


def host_file(source):
    """host/oot_high_fps.c without its includes but the logic's header, for RUNTIME's stand-ins"""
    keep = ('#include "oot_high_fps.h"',)
    return "\n".join(line for line in source.split("\n") if not line.startswith("#include") or line in keep)


def build_and_run(cc, update, directory):
    host = host_file((ROOT / "host" / "oot_high_fps.c").read_text(encoding="utf-8"))
    source, binary = Path(directory) / "fixture.c", Path(directory) / "fixture.exe"
    source.write_text(RUNTIME + host + "\n" + update.replace('#include "a64.h"\n', "") + FRAMES, encoding="utf-8")
    subprocess.run([cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-I", str(ROOT / "host"),
                    str(source), "-o", str(binary), "-lm"], check=True)
    return subprocess.run([str(binary)], text=True, capture_output=True, timeout=60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    patched, counts, _ = oot_patches.patch_file(LIFTED, "code_045.c")
    hooked = "hos_oot_song_cue(" in patched
    with tempfile.TemporaryDirectory(prefix="song-note-cue-") as directory:
        result = build_and_run(args.cc, patched, directory)
        print(result.stdout, end="")
        if result.returncode != 0:
            raise SystemExit("FAIL: a song's playback above 60 fps (the patch %s)" % ("is in" if hooked else "is missing"))
        native = build_and_run(args.cc, LIFTED, directory)
        if native.returncode == 0 or "FAIL: 120 fps:" not in native.stdout:
            raise SystemExit("FAIL: the unpatched updates did not fail the 120 fps check")
        print("PASS: the unpatched updates compile and fail the 120 fps check (two notes at each of the melody's)")
    assert counts["song note flag"] == 2
    assert UNRELATED in patched
    again, repeated, _ = oot_patches.patch_file(patched, "code_045.c")
    assert again == patched and repeated["song note flag"] == 2
    for altered, found in ((LIFTED.replace(PLAYED_CALL, PLAYED_CALL.replace("0x832b2c84", "0x832b2c88"), 1), 1),
                           (LIFTED.replace(OTHER_HEAD, OTHER_HEAD + OTHER_CALL, 1), 1),
                           ('#include "a64.h"\n' + UNRELATED, 0)):
        output, missing, _ = oot_patches.patch_file(altered, "code_045.c")
        assert missing["song note flag"] == found, (missing["song note flag"], found)
        assert found or output == altered
        warning = io.StringIO()
        with contextlib.redirect_stdout(warning):
            oot_patches.report([Path("code_045.c")], [missing])
        assert "WARNING: the song playbacks' note flag was found at %d of 2 places" % found in warning.getvalue()
    print("PASS: scoped, idempotent, and a changed anchor is left alone with a warning")


if __name__ == "__main__":
    main()
