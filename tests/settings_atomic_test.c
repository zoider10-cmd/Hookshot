/* The writer side of tests/test_settings_atomic.py: the writes of a setting, over host/hos_atomic_file.h, with a kill point at
   each step (the header's HOS_AF_STEP, and one between the calls of the old way) at which the process kills itself.

     settings_atomic_test <mode> <kill step> <folder>      kill step 0: none; the steps it took are printed ("steps N")

   Files hold one 4-byte word, a generation, repeated: a file that is part one generation and part another, or short, shows in
   one read. Generation 1 is the file the folder starts with, 2 and up the files written over it (the size differs between the
   two, as a settings file that grew did). settings.ini is the setting that is written; source.ini (40,000 bytes, generation 1)
   is the file a copy is made from. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef _WIN32
#include <signal.h>
#include <unistd.h>
#endif
#include <windows.h>   /* (host/posix's on Linux) */

static long kill_step, steps;
static void kill_point(const char *what) {
    (void)what;
    if (++steps != kill_step) return;
#ifdef _WIN32
    TerminateProcess(GetCurrentProcess(), 137);
#else
    kill(getpid(), SIGKILL);
#endif
}
#define HOS_AF_STEP(what) kill_point(what)
#include "../host/hos_atomic_file.h"

/* the size of a settings file in generation gen: the first generation's, or a later one's (it grew) */
static size_t size_of(uint32_t gen) { return gen > 1 ? 8004 : 8000; }
static uint32_t *words(size_t size, uint32_t gen) {
    uint32_t *w = (uint32_t *)malloc(size);
    for (size_t i = 0; i < size / 4; i++) w[i] = gen;
    return w;
}
static void path_of(char *out, size_t cap, const char *dir, const char *name) { snprintf(out, cap, "%s/%s", dir, name); }
/* a whole file written the plain way: the folder's start */
static void plain_file(const char *path, size_t size, uint32_t gen) {
    uint32_t *w = words(size, gen);
    FILE *f = fopen(path, "wb");
    if (!f || fwrite(w, 1, size, f) != size || fclose(f)) exit(2);
    free(w);
}
static void setup(const char *dir, int with_settings) {
    char p[1024];
    CreateDirectoryA(dir, NULL);
    path_of(p, sizeof p, dir, "source.ini");
    plain_file(p, 40000, 1);
    if (with_settings) {
        path_of(p, sizeof p, dir, "settings.ini");
        plain_file(p, size_of(1), 1);
    }
}

int main(int argc, char **argv) {
    if (argc != 4) return 2;
    const char *mode = argv[1], *dir = argv[3];
    kill_step = atol(argv[2]);
    char p[1024];
    int ok = 1;
    if (!strcmp(mode, "setup")) {   /* a folder that has the setting already */
        setup(dir, 1);
    } else if (!strcmp(mode, "setup_new")) {   /* a folder that has not */
        setup(dir, 0);
    } else if (!strcmp(mode, "write")) {   /* language.txt, mouse_sens.txt: hos_atomic_write over the file (or a new one) */
        uint32_t *w = words(size_of(2), 2);
        path_of(p, sizeof p, dir, "settings.ini");
        ok = hos_atomic_write(p, w, size_of(2));
        free(w);
    } else if (!strcmp(mode, "copy")) {   /* hos_atomic_copy_file: source.ini's bytes as settings.ini (the carry; the saves' move) */
        char from[1024];
        path_of(from, sizeof from, dir, "source.ini");
        path_of(p, sizeof p, dir, "settings.ini");
        ok = hos_atomic_copy_file(from, p);
    } else if (!strcmp(mode, "stale")) {   /* a leftover stand-in beside settings.ini, removed at the start */
        char junk[1100];
        path_of(p, sizeof p, dir, "settings.ini");
        snprintf(junk, sizeof junk, "%s%s", p, HOS_AF_NEW);
        plain_file(junk, 1000, 1);
        hos_atomic_remove_stale(p);
    } else if (!strcmp(mode, "remove_stale")) {   /* the start's clean-up alone */
        path_of(p, sizeof p, dir, "settings.ini");
        hos_atomic_remove_stale(p);
    } else if (!strcmp(mode, "plain_write") || !strcmp(mode, "plain_copy")) {
        /* the old ways, as control: fopen "w" and the pieces of fprintf (the file is empty from the first), and a copy made at the
           final name (CopyFileA's way) */
        path_of(p, sizeof p, dir, "settings.ini");
        const int copy = !strcmp(mode, "plain_copy");
        const size_t size = copy ? 40000 : size_of(2);
        uint32_t *w = words(size, copy ? 1 : 2);
        FILE *f = fopen(p, "wb");
        kill_point("plain: opened");
        ok = f != NULL;
        for (int i = 0; ok && i < 3; i++) {
            const size_t from = size / 3 / 4 * 4 * (size_t)i, to = i == 2 ? size : size / 3 / 4 * 4 * (size_t)(i + 1);
            ok = fwrite((const char *)w + from, 1, to - from, f) == to - from && fflush(f) == 0;
            kill_point("plain: piece");
        }
        if (f) ok = fclose(f) == 0 && ok;
        kill_point("plain: closed");
        free(w);
    } else if (!strcmp(mode, "loop")) {   /* writes without end: the test kills it at a time of its own */
        for (uint32_t gen = 2;; gen++) {
            uint32_t *w = words(size_of(gen), gen);
            path_of(p, sizeof p, dir, "settings.ini");
            hos_atomic_write(p, w, size_of(gen));
            free(w);
        }
    } else {
        return 2;
    }
    printf("steps %ld\n", steps);
    return ok ? 0 : 1;
}
