"""The game's zstd stream decode on the host's libzstd (host/hos_zstd.c, HOS_NATIVE_ZSTD), compiled as it is with the vendored
zstd decoder over a small guest window, on frames made here with python-zstandard (no game data):

- frames with and without checksums, with a dictionary (with entropy tables, and raw content), empty and one byte long, of RLE
  and raw blocks, fed whole and in chunks from 7 bytes to 128 KB + 3 and at random, so headers and blocks are split between
  chunks through the staging buffer: the output is the original, each call answers what is still to come and the last 0,
  and the stream object ends as the game's wrapper leaves it (state 4, output pointer and room moved by the content, staging
  empty, the context pointer set to the workspace); a stream object decodes a second frame after its first, and two decode
  in turn;
- failures answer as the game's wrapper does: a wrong checksum, a wrong or missing dictionary, a bad magic, an unknown
  content size or a header split from the first chunk -1, too little output room -2, bytes after the frame -3, a block split
  with too small a staging buffer -1; a failed or finished stream is left to the lifted code;
- a DDict the game makes again in place for another dictionary with the same ID and size is taken anew;
- nothing is done on the host and nothing written with the switch off, for a workspace that is not 8-byte aligned, for a
  DDict whose ID libzstd reads otherwise, or with all 64 host entries in use (and an entry is free again once its stream
  ends);
- every page changed is marked for the GPU mirror (HOS_WRITTEN) after its last change, and the virtual core is given up and
  taken back once a call (kept with HOS_NATIVE_ZSTD=2);
- a broken copy (the staging buffer's fill never stored) must fail.

The game's whole-buffer decode (hos_zstd_frames for f_8010b380, HOS_NATIVE_ZSTD_FRAMES) on the same kinds of frames in one
call, and two frames with a skippable one between: the result is the content's size and the output the original; failures
give zstd's error code (wrong checksum, too little room, a wrong or missing dictionary, a bad magic, bytes after the frame);
a DDict made again in place is taken anew; the switch off, a raw dictionary or another format are left to the lifted code,
writing nothing; nothing is written outside the output room, and all of it is marked; the core is kept. A broken copy (the
DDict never passed to libzstd) must fail.

Byte-for-byte equality with the game's own decoder (f_80115c80 run in Unicorn on the game's image) needs the game: checked
locally, not here.

    python -I -B tests/test_native_zstd.py [--cxx g++]
"""
import argparse
import os
import random
import struct
import subprocess
import tempfile
from pathlib import Path

import zstandard

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
RUN_ALL_MODULES = ["zstandard"]

ROOT = Path(__file__).resolve().parents[1]
ZSTD = ROOT / "third_party/zstd/lib"
SOURCES = ["common/debug.c", "common/entropy_common.c", "common/error_private.c", "common/fse_decompress.c", "common/xxhash.c",
           "common/zstd_common.c", "decompress/huf_decompress.c", "decompress/zstd_ddict.c", "decompress/zstd_decompress.c",
           "decompress/zstd_decompress_block.c"]
ENV_ON_H = ROOT / "gpu/vk/compat/hookshot_env.h"
BROKEN = ("                S_STAGED(g) = (uint32_t)staged;\n", "")   # (the staging fill never stored)
BROKEN_F = ("ZSTD_decompress_usingDDict(z, GP(dst), room, GP(src), n, d->dd)",   # (the whole-buffer decode's DDict not passed)
            "ZSTD_decompress_usingDDict(z, GP(dst), room, GP(src), n, NULL)")
F_LOG = 'hos_log("zstd: the game\'s whole-buffer decode on the host\'s libzstd %s (HOS_NATIVE_ZSTD_FRAMES)", ZSTD_versionString());'
BROKEN_ONCE = ("if (zs_publish(&mode, m) && m) " + F_LOG + "\n",
               "if (m) " + F_LOG + "\n        zs_publish(&mode, m);\n")   # (the old way: logged, then published)
BROKEN_STORE = ("    int unset = -1;\n    return __atomic_compare_exchange_n(mode, &unset, m, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED);\n",
                "    __atomic_store_n(mode, m, __ATOMIC_RELAXED);\n    return 1;\n")   # (every first caller publishes and logs)
BROKEN_NOTE = ("    zs_unlock();\n    if (first) hos_log(", "    if (first) hos_log(")   # (logged under zs_lock...)
BROKEN_NOTE2 = ('hos_log("zstd: a decode runs lifted: %s", why);\n}', 'hos_log("zstd: a decode runs lifted: %s", why);\n'
                "    zs_unlock();\n}")   # (...and released after)

# the guest window: base, size, and where things are in it
BASE, SIZE = 0x10000000, 4 << 20
S0, S_STEP = BASE + 0x100, 0x40          # stream objects
WORK = BASE + 0x2000                     # their workspace (the host never writes it)
DDICT, DICT = (BASE + 0x10000, BASE + 0x18000), (BASE + 0x20000, BASE + 0x30000)
STAGE, STAGE_CAP = BASE + 0x40000, 0x22000   # (two: odd streams use the second, at STAGE + 0x24000)
SRC = (BASE + 0x90000, BASE + 0x110000)  # the two input buffers the game's job loop alternates
DST, DST_CAP = BASE + 0x200000, 0x100000
DST2 = BASE + 0x300000

HOS_H = r'''
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
typedef struct { uint64_t x[32]; } Ctx;
extern uint8_t *zs_mem;
#define ZS_BASE 0x%xull
#define GP(a) ((void *)(zs_mem + ((uint64_t)(a) - ZS_BASE)))
#define G64(a) (*(uint64_t *)GP(a))
#define G32(a) (*(uint32_t *)GP(a))
void zs_mark(const void *p, size_t n);
#define HOS_WRITTEN(p, n) zs_mark((p), (n))
int hos_vcore_away(void);
void hos_vcore_back(void);
void hos_log(const char *fmt, ...);
''' % BASE

FIXTURE = r'''
#include <stdio.h>
#include <stdarg.h>
#include "hos.h"
#define SIZE 0x%xull
uint8_t *zs_mem;
static uint8_t marks[SIZE >> 12], *shadow;   /* (a page as it was at its last mark: the GPU mirror may copy it then) */
static int aways, backs;
void zs_mark(const void *p, size_t n) {
    const size_t a = (size_t)((const uint8_t *)p - zs_mem);
    if (n && a < SIZE)
        for (size_t q = a >> 12; q <= (a + n - 1) >> 12 && q < (SIZE >> 12); q++)
            marks[q] = 1, memcpy(shadow + (q << 12), zs_mem + (q << 12), 4096);
}
int hos_vcore_away(void) { aways++; return 1; }
void hos_vcore_back(void) { backs++; }
void hos_log(const char *fmt, ...) { (void)fmt; }
#include "hos_zstd.c"
static FILE *in;
static void rd(void *p, size_t n) {
    if (fread(p, 1, n, in) != n) { fprintf(stderr, "short case\n"); exit(2); }
}
int main(int argc, char **argv) {
    (void)argc;
    in = fopen(argv[1], "rb");
    FILE *out = fopen(argv[2], "wb");
    zs_mem = calloc(1, SIZE);
    shadow = malloc(SIZE);
    uint8_t *before = malloc(SIZE);
    uint32_t nops;
    rd(zs_mem, SIZE);
    rd(&nops, 4);
    for (uint32_t op = 0; op < nops; op++) {
        uint32_t nw;
        rd(&nw, 4);
        for (uint32_t k = 0; k < nw; k++) {
            uint64_t a;
            uint32_t n;
            rd(&a, 8);
            rd(&n, 4);
            rd(GP(a), n);
        }
        Ctx c;
        uint32_t frames;
        memset(&c, 0, sizeof c);
        rd(&frames, 4);   /* (1: the whole-buffer decode, x0-x7; else a stream call, x0-x3) */
        rd(c.x, 64);
        const uint64_t g = frames ? 0x%xull : c.x[0];   /* (for the whole-buffer decode: the stream fields read anywhere) */
        memcpy(before, zs_mem, SIZE);
        memset(marks, 0, sizeof marks);
        aways = backs = 0;
        const int32_t handled = frames ? hos_zstd_frames(&c) : hos_zstd_stream(&c);
        int32_t changed = 0, unmarked = 0;
        for (size_t q = 0; q < SIZE >> 12; q++)
            if (memcmp(before + (q << 12), zs_mem + (q << 12), 4096))   /* (unmarked, or written after its last mark) */
                changed++, unmarked += !marks[q] || memcmp(shadow + (q << 12), zs_mem + (q << 12), 4096);
        const int32_t rec[5] = {handled, changed, unmarked, aways, backs};
        fwrite(rec, 4, 5, out);
        fwrite(&c.x[0], 8, 1, out);
        const int32_t st[2] = {*(uint8_t *)GP(g), (int32_t)G32(g + 20)};   /* (the object's state, still to come, output) */
        fwrite(st, 4, 2, out);
        fwrite(GP(g + 8), 8, 1, out);
    }
    fwrite(zs_mem, 1, SIZE, out);
    fclose(out);
    return 0;
}
''' % (SIZE, S0)

# first calls from two threads at once. Held in the log: the second runs start to end while the first is in its first log
# line (a stand-in hos_log holds it there), so a switch published after its log line, or a log line written under zs_lock,
# shows every time. Cold ("cold" argument): a stand-in env_on holds each caller that reads a switch unset until two have, so
# both go on to publish it and only one may log. (The fallback table's lock itself is not shown by either: no probe holds a
# thread between its read and its write.)
CONC = r'''
#ifdef _WIN32   /* (Windows threads with every compiler there: the Microsoft runtime has no pthread.h or sched.h) */
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
typedef HANDLE thr_t;
#define THR_FN(name) static DWORD WINAPI name(LPVOID p)
#define THR_RET return 0
static void thr_start(thr_t *t, LPTHREAD_START_ROUTINE f, void *p) { *t = CreateThread(NULL, 0, f, p, 0, NULL); }
static void thr_join(thr_t t) {
    WaitForSingleObject(t, INFINITE);
    CloseHandle(t);
}
static void thr_yield(void) { SwitchToThread(); }
#else
#include <pthread.h>
#include <sched.h>
typedef pthread_t thr_t;
#define THR_FN(name) static void *name(void *p)
#define THR_RET return NULL
static void thr_start(thr_t *t, void *(*f)(void *), void *p) { pthread_create(t, NULL, f, p); }
static void thr_join(thr_t t) { pthread_join(t, NULL); }
static void thr_yield(void) { sched_yield(); }
#endif
#include <stdio.h>
#include <time.h>
#include "hos.h"
uint8_t *zs_mem;
void zs_mark(const void *p, size_t n) { (void)p, (void)n; }
int hos_vcore_away(void) { return 1; }
void hos_vcore_back(void) {}
static int armed, b_done, stuck, n_on, n_note;
static int (*fn)(Ctx *);
static Ctx cb;
static thr_t tb;
THR_FN(second) {
    (void)p;
    fn(&cb);
    __atomic_store_n(&b_done, 1, __ATOMIC_SEQ_CST);
    THR_RET;
}
void hos_log(const char *fmt, ...) {
    __atomic_fetch_add(strstr(fmt, "runs lifted") ? &n_note : &n_on, 1, __ATOMIC_SEQ_CST);
    if (!__atomic_exchange_n(&armed, 0, __ATOMIC_SEQ_CST)) return;
    thr_start(&tb, second, NULL);
    const time_t t0 = time(NULL);
    while (!__atomic_load_n(&b_done, __ATOMIC_SEQ_CST) && time(NULL) - t0 < 3) thr_yield();
    stuck = !__atomic_load_n(&b_done, __ATOMIC_SEQ_CST);
}
static int meet, met;
static int cold_env_on(const char *name) {
    if (__atomic_load_n(&meet, __ATOMIC_SEQ_CST)) {
        __atomic_fetch_add(&met, 1, __ATOMIC_SEQ_CST);
        const time_t t0 = time(NULL);
        while (__atomic_load_n(&met, __ATOMIC_SEQ_CST) < 2 && time(NULL) - t0 < 10) thr_yield();
    }
    return env_on(name);
}
#define env_on cold_env_on
#include "hos_zstd.c"
#undef env_on
THR_FN(call) {
    fn((Ctx *)p);
    THR_RET;
}
static void cold(const char *name, int (*f)(Ctx *), Ctx a) {
    Ctx b = a;
    thr_t t1, t2;
    fn = f, n_on = n_note = met = 0, meet = 1;
    thr_start(&t1, call, &a);
    thr_start(&t2, call, &b);
    thr_join(t1);
    thr_join(t2);
    meet = 0;
    printf("%s %d %d %d 0\n", name, met, n_on, n_note);
}
static void phase(const char *name, int (*f)(Ctx *), Ctx a) {
    fn = f, cb = a, n_on = n_note = b_done = stuck = 0, armed = 1;
    f(&a);
    const int started = !armed;
    if (started) thr_join(tb);
    printf("%s %d %d %d %d\n", name, started, n_on, n_note, stuck);
}
int main(int argc, char **argv) {
    zs_mem = calloc(1, 0x10000);
    Ctx s = {{0}}, raw = {{0}}, fmt = {{0}};
    s.x[0] = ZS_BASE + 0x100;                                     /* a stream the host has no entry for */
    raw.x[0] = ZS_BASE, raw.x[5] = ZS_BASE + 0x400, raw.x[6] = 16;   /* a raw dictionary */
    fmt.x[0] = ZS_BASE + 0x8000, G32(ZS_BASE + 0x8000 + 0x7110) = 1;  /* another frame format */
    if (argc > 1 && argv[1][0]) {   /* cold: two first callers that both read the switch unset */
        cold("cold-stream", hos_zstd_stream, s);
        cold("cold-raw", hos_zstd_frames, raw);
        return 0;
    }
    phase("stream", hos_zstd_stream, s);
    phase("raw", hos_zstd_frames, raw);
    phase("format", hos_zstd_frames, fmt);
    return 0;
}
'''


def conc_checks(exe, tmp, quick=False):
    got, bad = {}, []
    for arg in ([], ["cold"]):
        r = subprocess.run([str(exe)] + arg, env=dict(os.environ, HOS_NATIVE_ZSTD="1", HOS_NATIVE_ZSTD_FRAMES="1"),
                           capture_output=True, text=True, timeout=60)
        got.update((ln.split()[0], tuple(map(int, ln.split()[1:]))) for ln in r.stdout.splitlines() if ln.strip())
        bad += ["exit %d %s" % (r.returncode, arg)] if r.returncode else []
    want = {"stream": (1, 1, 0, 0), "raw": (1, 1, 1, 0), "format": (1, 0, 1, 0),   # (held in the log)
            "cold-stream": (2, 1, 0, 0), "cold-raw": (2, 1, 1, 0)}                  # (both read the switch unset)
    return ["first calls at once, %s: (second call made or switch read unset by, switch lines, fallback lines, second call "
            "held) %s, not %s" % (k, got.get(k), v) for k, v in want.items() if got.get(k) != v] + bad


# ---------------------------------------------------------------- content (made here)
def synth(kind, size, seed):
    rng = random.Random(seed)
    if kind == "text":
        words = ["".join(rng.choice("etaoinshrdlucmfw") for _ in range(rng.randint(2, 9))) for _ in range(1500)]
        out = bytearray()
        while len(out) < size:
            out += (" ".join(rng.choice(words) for _ in range(rng.randint(4, 14))) + ".\n").encode()
        return bytes(out[:size])
    if kind == "mesh":
        out, n = bytearray(), 0
        while len(out) < size:
            out += struct.pack("<6f", n % 97, (n * 7) % 13 / 13.0, n // 97, 0.0, 1.0, 0.5)
            n += 1
        return bytes(out[:size])
    if kind == "mixed":
        out = bytearray()
        while len(out) < size:
            if rng.random() < 0.4 or len(out) < 64:
                out += rng.randbytes(rng.randint(8, 200))
            else:
                d = rng.randint(1, len(out))
                for _ in range(rng.randint(4, 300)):
                    out.append(out[len(out) - d])
        return bytes(out[:size])
    return bytes(size) if kind == "zero" else rng.randbytes(size)


def compress(data, level=3, ck=False, d=None, size=True):
    return zstandard.ZstdCompressor(level=level, write_checksum=ck, write_content_size=size, dict_data=d).compress(data)


def guest_ddict(d, kind):
    """a DDict as the game's lays it out: content and size at +8/+16, repeat offsets +0x6834, dictID +0x6840, entropy +0x6844"""
    b = d.as_bytes()
    out = bytearray(0x6860)
    struct.pack_into("<QQ", out, 8, 0, len(b))   # (content filled in by place())
    out[0x18:0x18 + min(len(b), 0x6800)] = b[:0x6800]   # (stands for the tables the game builds: other per dictionary)
    struct.pack_into("<3I", out, 0x6834, 1, 4, 8)
    struct.pack_into("<II", out, 0x6840, d.dict_id() if kind == "full" else 0, 1 if kind == "full" else 0)
    return out, b


def place(writes, slot, d, kind, wrong_id=False):
    dd, content = guest_ddict(d, kind)
    struct.pack_into("<Q", dd, 8, DICT[slot])
    if wrong_id:
        struct.pack_into("<I", dd, 0x6840, d.dict_id() ^ 1)
    writes += [(DDICT[slot], bytes(dd)), (DICT[slot], content)]
    return DDICT[slot]


def s_obj(i):
    return S0 + i * S_STEP


def s_init(i, dst=DST, room=DST_CAP, stage_cap=STAGE_CAP, work=WORK):
    return (s_obj(i), struct.pack("<B7xQiiQQiiQ", 1, dst, room, 0, work, STAGE + (i & 1) * 0x24000, stage_cap, 0, 0))


def chunks(data, split, seed=0, first=18):
    head, rest = data[:first], data[first:]
    if split == "whole":
        sizes = [len(rest)]
    elif split == "random":
        rng, sizes, left = random.Random(seed), [], len(rest)
        while left > 0:
            sizes.append(min(left, rng.choice([1, 2, 5, 17, 300, 4096, 20000, 70000, 140000])))
            left -= sizes[-1]
    else:
        sizes = [split] * (len(rest) // split) + ([len(rest) % split] if len(rest) % split else [])
    out, at = [head + rest[:sizes[0]]] if sizes else [head], sizes[0] if sizes else 0
    for n in sizes[1:]:
        out.append(rest[at:at + n])
        at += n
    return [c for c in out if c] or [b""]


def stream(i, frame, split, ddict=0, init=None, seed=0, first=18):
    ops = []
    for k, ch in enumerate(chunks(frame, split, seed, first)):
        w = ([init] if init and k == 0 else []) + [(SRC[k & 1], ch)]
        ops.append((w, [s_obj(i), SRC[k & 1], len(ch), ddict]))
    return ops


# ---------------------------------------------------------------- running
class Crash(Exception):
    pass


def run(exe, tmp, ops, mode="1", pre=()):
    img = bytearray(SIZE)
    for a, b in pre:
        img[a - BASE:a - BASE + len(b)] = b
    case, res = Path(tmp) / "case.bin", Path(tmp) / "res.bin"
    parts = [bytes(img), struct.pack("<I", len(ops))]
    for writes, x in ops:
        parts.append(struct.pack("<I", len(writes)))
        for a, b in writes:
            parts.append(struct.pack("<QI", a, len(b)) + b)
        parts.append(struct.pack("<I8Q", len(x) == 8, *(list(x) + [0] * (8 - len(x)))))
    case.write_bytes(b"".join(parts))
    r = subprocess.run([str(exe), str(case), str(res)], env=dict(os.environ, HOS_NATIVE_ZSTD=mode, HOS_NATIVE_ZSTD_FRAMES=mode))
    if r.returncode:
        raise Crash("the fixture stopped with %#x" % (r.returncode & 0xFFFFFFFF))
    raw = res.read_bytes()
    calls = [struct.unpack_from("<5iQiiQ", raw, 44 * k) for k in range(len(ops))]
    mem = raw[44 * len(ops):]
    return calls, mem


def field(mem, i):
    """a stream object's fields: state, output pointer, room, still to come, workspace, staging, its size and fill, context"""
    return struct.unpack_from("<B7xQiiQQiiQ", mem, s_obj(i) - BASE)


def signed(x0):
    return x0 - (1 << 32) if x0 >= 1 << 31 else x0


class Checker:
    def __init__(self):
        self.failed = []

    def __call__(self, cond, what):
        if not cond:
            self.failed.append(what)


def check_calls(chk, name, calls, mode="1"):
    for k, (h, changed, unmarked, aways, backs, x0, *_) in enumerate(calls):
        chk(unmarked == 0, "%s: call %d changed %d page(s) without a mark after the change" % (name, k, unmarked))
        if h:
            chk(aways == backs and aways == (1 if mode == "1" else 0) or (aways == backs == 0 and signed(x0) == -1),
                "%s: call %d gave the core up %d times and took it back %d" % (name, k, aways, backs))
        else:
            chk(changed == 0, "%s: call %d left to the lifted code but wrote %d page(s)" % (name, k, changed))


def good(chk, exe, tmp, name, data, frame, split, d=None, kind=None, seed=0, mode="1"):
    pre = []
    dd = place(pre, 0, d, kind) if d else 0
    calls, mem = run(exe, tmp, stream(0, frame, split, dd, s_init(0), seed), mode=mode, pre=pre)
    check_calls(chk, name, calls, mode)
    chk(all(c[0] == 1 for c in calls), "%s: a call was not done on the host" % name)
    got = [signed(c[5]) for c in calls]
    chk(got[-1] == 0 and all(r >= 0 for r in got), "%s: results %s" % (name, got[-4:]))
    chk([c[6] for c in calls] == [2] * (len(calls) - 1) + [4], "%s: states after each call %s" % (name, [c[6] for c in calls][:6]))
    # (each result is what is still to come: the content less what is out; 0 only once all of it is)
    chk(all(signed(c[5]) == c[7] == len(data) - (c[8] - DST) for c in calls if c[0]),
        "%s: a result is not what is still to come: %s" % (name, [(signed(c[5]), c[7], c[8] - DST) for c in calls][:4]))
    st, dst, room, left, work, stage, cap, staged, ctx = field(mem, 0)
    chk(mem[DST - BASE:DST - BASE + len(data)] == data, "%s: the output is not the original" % name)
    chk((st, dst, room, left, staged, ctx) == (4, DST + len(data), DST_CAP - len(data), 0, 0, WORK),
        "%s: fields %s" % (name, (st, hex(dst), room, left, staged, hex(ctx))))


def fails(chk, exe, tmp, name, frame, split, want, d=None, kind=None, init=None, wrong_id=False, first=18, data=None):
    pre = []
    dd = place(pre, 0, d, kind, wrong_id) if d else 0
    calls, mem = run(exe, tmp, stream(0, frame, split, dd, init or s_init(0), first=first), pre=pre)
    check_calls(chk, name, calls)
    done = [k for k, c in enumerate(calls) if c[0] and signed(c[5]) < 0]
    chk(bool(done) and signed(calls[done[0]][5]) == want and field(mem, 0)[0] == 3,
        "%s: wanted %d and state 3, got %s state %d" % (name, want, [signed(c[5]) for c in calls][-3:], field(mem, 0)[0]))
    chk(all(c[0] == 0 for c in calls[done[0] + 1:]) if done else True, "%s: a call after the failure done on the host" % name)
    return calls, mem


def checks(exe, tmp, quick=False):
    """the failed checks' messages; quick: the first frame's only (the broken copy)"""
    chk = Checker()
    full = zstandard.train_dictionary(8192, [synth("text", 3000, 100 + i) for i in range(200)])
    other = zstandard.train_dictionary(8192, [synth("mesh", 3000, 300 + i) for i in range(200)])
    raw = zstandard.ZstdCompressionDict(synth("text", 16 << 10, 7), dict_type=zstandard.DICT_TYPE_RAWCONTENT)
    text, mesh, mixed = synth("text", 200 << 10, 1), synth("mesh", 64 << 10, 2), synth("mixed", 300 << 10, 3)
    zero, noise, small = synth("zero", 300 << 10, 4), synth("noise", 150 << 10, 5), synth("text", 48 << 10, 6)
    frames = [("text", text, compress(text, 3), None, None), ("mesh-l19-ck", mesh, compress(mesh, 19, True), None, None),
              ("mixed-ck", mixed, compress(mixed, 6, True), None, None), ("rle", zero, compress(zero, 1), None, None),
              ("raw-ck", noise, compress(noise, 1, True), None, None), ("empty", b"", compress(b""), None, None),
              ("one-byte-ck", b"A", compress(b"A", 3, True), None, None),
              ("dict-ck", small, compress(small, 9, True, full), full, "full"),
              ("raw-dict", small, compress(small, 3, False, raw), raw, "raw")]
    for name, data, frame, d, kind in frames:   # (7-byte chunks for the small frames only: a call each, CI time)
        for split in ("whole", 300, 4096, 131075, "random") + ((7,) if len(frame) < 16000 else ()):
            good(chk, exe, tmp, "%s/%s" % (name, split), data, frame, split, d, kind, seed=len(name))
        if quick:
            return chk.failed
    # failures
    ck = compress(mesh, 19, True)
    fails(chk, exe, tmp, "bytes after the frame", compress(small) + b"\x28\xb5", "whole", -3)
    for split in ("whole", 7):
        fails(chk, exe, tmp, "wrong checksum/%s" % split, ck[:-1] + bytes([ck[-1] ^ 1]), split, -1)
        fails(chk, exe, tmp, "output room short/%s" % split, compress(text), 300 if split == 7 else split, -2,
              init=s_init(0, room=len(text) - 1))
        fails(chk, exe, tmp, "wrong dictionary/%s" % split, compress(small, 3, False, full), split, -1, other, "full")
        fails(chk, exe, tmp, "no dictionary/%s" % split, compress(small, 3, False, full), split, -1)
    fails(chk, exe, tmp, "staging too small", compress(text), 7, -1, init=s_init(0, stage_cap=0x100))
    fails(chk, exe, tmp, "bad magic", b"\x29" + compress(small)[1:], "whole", -1)
    fails(chk, exe, tmp, "unknown content size", compress(small, size=False), "whole", -1)
    fails(chk, exe, tmp, "header split from the first chunk", compress(small), 3, -1, first=0)
    # a stream object used again, and two streams in turn
    pre = []
    dd = place(pre, 1, full, "full")
    ops = stream(0, compress(text, 3, True), 4096, 0, s_init(0)) + stream(0, compress(small, 9, True, full), 7, dd, s_init(0, DST2))
    calls, mem = run(exe, tmp, ops, pre=pre)
    check_calls(chk, "used again", calls)
    chk(mem[DST2 - BASE:DST2 - BASE + len(small)] == small and field(mem, 0)[0] == 4 and signed(calls[-1][5]) == 0,
        "used again: the second frame")
    a = stream(0, compress(mixed, 6, True), 4096, 0, s_init(0))
    b = stream(1, compress(small, 9, True, full), 100, dd, s_init(1, DST2))
    calls, mem = run(exe, tmp, [o for pair in zip(a, b) for o in pair] + a[len(b):] + b[len(a):], pre=pre)
    check_calls(chk, "two streams", calls)
    chk(mem[DST - BASE:DST - BASE + len(mixed)] == mixed and mem[DST2 - BASE:DST2 - BASE + len(small)] == small
        and field(mem, 0)[0] == field(mem, 1)[0] == 4, "two streams: outputs")
    same_a, same_b = (zstandard.train_dictionary(8192, [synth(k, 3000, s + i) for i in range(200)], dict_id=12345).as_bytes()
                      for k, s in (("text", 500), ("mesh", 700)))
    n = max(len(same_a), len(same_b))   # (the same size: a full dictionary's content is all past its header, so more at its end)
    same_a, same_b = (zstandard.ZstdCompressionDict(x + synth("text", n - len(x), 9), dict_type=zstandard.DICT_TYPE_FULLDICT)
                      for x in (same_a, same_b))
    if len(same_a.as_bytes()) == len(same_b.as_bytes()) and same_a.dict_id() == same_b.dict_id():
        pre = []
        dd = place(pre, 0, same_a, "full")
        tiny_a, tiny_b = synth("text", 300, 11), synth("mesh", 300, 12)   # (small frames use the dictionary's own tables)
        ops = stream(0, compress(tiny_a, 3, True, same_a), "whole", dd, s_init(0))
        second = stream(0, compress(tiny_b, 3, True, same_b), "whole", dd, s_init(0, DST2))
        place(second[0][0], 0, same_b, "full")   # (the game makes its DDict again at the same place, for the other dictionary)
        ops += second
        calls, mem = run(exe, tmp, ops, pre=pre)
        check_calls(chk, "DDict made again", calls)
        chk(mem[DST2 - BASE:DST2 - BASE + len(tiny_b)] == tiny_b and signed(calls[-1][5]) == 0,
            "DDict made again in place (same ID and size): the second frame %s" % [signed(c[5]) for c in calls][-2:])
    else:
        chk(False, "the two same-ID dictionaries differ in size: the DDict-made-again case does not run")
    # left to the lifted code: switch off, a misaligned workspace, a DDict libzstd reads another ID from, no free entry
    for name, mode, init, d in (("switch off", "0", s_init(0), None), ("misaligned workspace", "1", s_init(0, work=WORK + 1), None),
                                ("DDict ID differs", "1", s_init(0), full)):
        pre = []
        dd = place(pre, 0, d, "full", wrong_id=True) if d else 0
        calls, _ = run(exe, tmp, stream(0, compress(small, 3, False, d), 4096, dd, init), mode=mode, pre=pre)
        # (the stream's first call decides; past it the lifted code would have started the stream, which no fixture runs)
        n = len(calls) if mode == "0" else 1
        chk(all(c[0] == 0 and c[1] == 0 for c in calls[:n]), "%s: done on the host (%s)" % (name, [c[:2] for c in calls[:2]]))
    f = compress(text)   # (65 streams start; then the first ends, and its entry takes the next one)
    ops = [([s_init(i), (SRC[0], f[:100])], [s_obj(i), SRC[0], 100, 0]) for i in range(65)]
    ops.append(([(SRC[1], f[100:])], [s_obj(0), SRC[1], len(f) - 100, 0]))
    ops.append(([s_init(65, DST2), (SRC[0], f[:100])], [s_obj(65), SRC[0], 100, 0]))
    calls, mem = run(exe, tmp, ops)
    chk(all(c[0] == 1 for c in calls[:64]) and calls[64][0] == 0 and calls[64][1] == 0,
        "64 entries: the 65th stream %s" % (calls[64][:2],))
    chk(calls[65][0] == 1 and signed(calls[65][5]) == 0 and calls[66][0] == 1, "64 entries: not free again after a stream ended")
    # the core kept with =2
    good(chk, exe, tmp, "HOS_NATIVE_ZSTD=2", text, compress(text), 4096, mode="2")
    return chk.failed


# ---------------------------------------------------------------- the whole-buffer decode (f_8010b380)
D_FORMAT = 0x7110   # (the game's context: its format)
E_CHECKSUM, E_DICT, E_PREFIX, E_ROOM, E_SRCSIZE = 22, 32, 10, 70, 72   # (zstd's error codes: the game's are the same)


def whole(frame, room, dd=0, raw=(0, 0)):
    """one call of the whole-buffer decode: the frames at SRC[0], the output at DST, nonzero guard bytes on both sides of
    the output room (a write past it shows even when it writes zero)"""
    guard = bytes([0xA5]) * 64
    return ([(SRC[0], frame), (DST - 64, guard), (DST + room, guard)], [WORK, DST, room, SRC[0], len(frame), raw[0], raw[1], dd])


def zerr(x0):
    return (1 << 64) - x0 if x0 > (1 << 64) - 120 else 0


def frames_checks(exe, tmp, quick=False):
    """the failed checks' messages; quick: the dictionary frames only (the broken copy)"""
    chk = Checker()
    full = zstandard.train_dictionary(8192, [synth("text", 3000, 100 + i) for i in range(200)])
    other = zstandard.train_dictionary(8192, [synth("mesh", 3000, 300 + i) for i in range(200)])
    raw = zstandard.ZstdCompressionDict(synth("text", 16 << 10, 7), dict_type=zstandard.DICT_TYPE_RAWCONTENT)
    text, mesh, mixed = synth("text", 200 << 10, 1), synth("mesh", 64 << 10, 2), synth("mixed", 300 << 10, 3)
    zero, noise, small = synth("zero", 300 << 10, 4), synth("noise", 150 << 10, 5), synth("text", 48 << 10, 6)
    skip = struct.pack("<II", 0x184D2A55, 5) + b"skip!"
    cases = [("dict-ck", small, compress(small, 9, True, full), full, "full"),
             ("raw-dict", small, compress(small, 3, False, raw), raw, "raw")]
    if not quick:
        cases += [("text", text, compress(text, 3), None, None), ("mesh-l19-ck", mesh, compress(mesh, 19, True), None, None),
                  ("mixed-ck", mixed, compress(mixed, 6, True), None, None), ("rle", zero, compress(zero, 1), None, None),
                  ("raw-ck", noise, compress(noise, 1, True), None, None), ("empty", b"", compress(b""), None, None),
                  ("one-byte-ck", b"A", compress(b"A", 3, True), None, None),
                  ("unknown content size", small, compress(small, size=False), None, None),
                  ("two frames, a skippable one between", text + small, compress(text, 3) + skip + compress(small, 9, True),
                   None, None)]
        cases += [(name + ", 64 KB more room", data, frame, d, kind, len(data) + (64 << 10))
                  for name, data, frame, d, kind in cases[:4]]
    for name, data, frame, d, kind, *more in cases:
        pre = []
        dd = place(pre, 0, d, kind) if d else 0
        room = more[0] if more else len(data)
        x = whole(frame, room, dd)
        calls, mem = run(exe, tmp, [x], pre=pre)
        h, changed, unmarked, aways, backs, x0 = calls[0][:6]
        chk(h == 1 and x0 == len(data), "whole %s: handled %d, result %#x" % (name, h, x0))
        chk(mem[DST - BASE:DST - BASE + len(data)] == data, "whole %s: the output is not the original" % name)
        chk(unmarked == 0 and aways == backs == 0, "whole %s: %d page(s) unmarked, core given up %d" % (name, unmarked, aways))
        off = run(exe, tmp, [x], mode="0", pre=pre)[1]   # (memory as it was: nothing changes outside the output room)
        chk(mem[:DST - BASE] == off[:DST - BASE] and mem[DST - BASE + room:] == off[DST - BASE + room:],
            "whole %s: memory outside the output room changed" % name)
    if quick:
        return chk.failed
    ck = compress(mesh, 19, True)
    pre = []
    dd_other = place(pre, 1, other, "full")
    for name, frame, room, dd, want in (("wrong checksum", ck[:-1] + bytes([ck[-1] ^ 1]), len(mesh), 0, E_CHECKSUM),
                                        ("output room short", compress(text), len(text) - 1, 0, E_ROOM),
                                        ("wrong dictionary", compress(small, 3, False, full), len(small), dd_other, E_DICT),
                                        ("no dictionary", compress(small, 3, False, full), len(small), 0, E_DICT),
                                        ("bad magic", b"\x29" + compress(small)[1:], len(small), 0, E_PREFIX),
                                        ("bytes after the frame", compress(small) + b"\x28\xb5", len(small), 0, E_SRCSIZE)):
        calls, mem = run(exe, tmp, [whole(frame, room, dd)], pre=pre)
        h, changed, unmarked, x0 = calls[0][0], calls[0][1], calls[0][2], calls[0][5]
        chk(h == 1 and zerr(x0) == want, "whole %s: handled %d, error %d, wanted %d" % (name, h, zerr(x0), want))
        chk(unmarked == 0, "whole %s: %d page(s) unmarked" % (name, unmarked))
        off = run(exe, tmp, [whole(frame, room, dd)], mode="0", pre=pre)[1]   # (nothing written outside the output room)
        chk(mem[:DST - BASE] == off[:DST - BASE] and mem[DST - BASE + room:] == off[DST - BASE + room:],
            "whole %s: memory outside the output room changed" % name)
    # the game's DDict made again in place for another dictionary with the same ID and size
    same_a, same_b = (zstandard.train_dictionary(8192, [synth(k, 3000, s + i) for i in range(200)], dict_id=12345).as_bytes()
                      for k, s in (("text", 500), ("mesh", 700)))
    n = max(len(same_a), len(same_b))
    same_a, same_b = (zstandard.ZstdCompressionDict(x + synth("text", n - len(x), 9), dict_type=zstandard.DICT_TYPE_FULLDICT)
                      for x in (same_a, same_b))
    pre = []
    dd = place(pre, 0, same_a, "full")
    tiny_a, tiny_b = synth("text", 300, 11), synth("mesh", 300, 12)
    second = whole(compress(tiny_b, 3, True, same_b), len(tiny_b), dd)
    place(second[0], 0, same_b, "full")
    ops = [whole(compress(tiny_a, 3, True, same_a), len(tiny_a), dd), second]
    calls, mem = run(exe, tmp, ops, pre=pre)
    chk(calls[1][5] == len(tiny_b) and mem[DST - BASE:DST - BASE + len(tiny_b)] == tiny_b,
        "whole: DDict made again in place (same ID and size): the second decode %#x" % calls[1][5])
    off, room = run(exe, tmp, ops, mode="0", pre=pre)[1], max(len(tiny_a), len(tiny_b))
    chk(mem[:DST - BASE] == off[:DST - BASE] and mem[DST - BASE + room:] == off[DST - BASE + room:],
        "whole: DDict made again: memory outside the output room changed")
    # left to the lifted code, writing nothing: switch off, a raw dictionary, another format
    fmt = [(WORK + D_FORMAT, struct.pack("<I", 1))]
    for name, mode, x, pre in (("switch off", "0", whole(compress(small), len(small)), []),
                               ("a raw dictionary", "1", whole(compress(small), len(small), raw=(DICT[0], 1000)), []),
                               ("another format", "1", whole(compress(small), len(small)), fmt)):
        calls, _ = run(exe, tmp, [x], mode=mode, pre=pre)
        chk(calls[0][0] == 0 and calls[0][1] == 0, "whole %s: done on the host (%s)" % (name, calls[0][:2]))
    return chk.failed


def build(cxx, tmp, broken=False, conc=False):
    stem, ext = os.path.splitext(cxx) if cxx.lower().endswith(".exe") else (cxx, "")
    cc = stem[:-2] + ext if stem.endswith("++") else "cc"   # (the C compiler beside the C++ one)
    if Path(cc).name == "g" or cc.endswith("-g"):
        cc += "cc"
    d = Path(tmp) / ("broken%d" % len(list(Path(tmp).glob("broken*"))) if broken else "conc" if conc else "ok")
    d.mkdir()
    src = (ROOT / "host/hos_zstd.c").read_text(encoding="utf-8")
    for old, new in ([broken] if broken and isinstance(broken[0], str) else broken or []):
        if src.count(old) != 1:
            raise SystemExit("FAIL: the broken variant's line is not in host/hos_zstd.c: %r" % old)
        src = src.replace(old, new)
    (d / "hos_zstd.c").write_text(src, encoding="utf-8")   # (beside the stand-in hos.h: quotes look there first)
    (d / "hos.h").write_text(HOS_H, encoding="utf-8")
    (d / "fixture.c").write_text(CONC if conc else FIXTURE, encoding="utf-8")
    flags = ["-O1", "-DZSTD_DISABLE_ASM", "-DZSTD_LEGACY_SUPPORT=0", "-DZSTD_MULTITHREAD=0", "-D_CRT_SECURE_NO_WARNINGS",
             "-I" + str(ZSTD)]
    objs = []
    zobj = Path(tmp) / "zstd"
    zobj.mkdir(exist_ok=True)
    for i, f in enumerate(SOURCES):
        o = zobj / ("z%d.o" % i)
        if not o.exists():
            subprocess.run([cc, "-c", str(ZSTD / f), "-o", str(o), "-w"] + flags, check=True)
        objs.append(str(o))
    exe = d / "fixture.exe"
    subprocess.run([cc, "-std=gnu11", "-include", str(ENV_ON_H), "-Wall", "-Wextra", "-I", str(d), str(d / "fixture.c"),
                    "-o", str(exe)] + flags + objs + (["-pthread"] if conc and os.name != "nt" else []), check=True)
    return exe


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    with tempfile.TemporaryDirectory(prefix="native-zstd-") as tmp:
        exe = build(a.cxx, tmp)
        failed = checks(exe, tmp)
        if failed:
            raise SystemExit("FAIL:\n  " + "\n  ".join(failed))
        print("PASS: the host's zstd stream decode answers, writes and marks as the game's wrapper does")
        failed = frames_checks(exe, tmp)
        if failed:
            raise SystemExit("FAIL:\n  " + "\n  ".join(failed))
        print("PASS: the host's whole-buffer decode answers and writes as the game's does")
        failed = conc_checks(build(a.cxx, tmp, conc=True), tmp)
        if failed:
            raise SystemExit("FAIL:\n  " + "\n  ".join(failed))
        print("PASS: first calls from two threads at once (one held in its log line, or both reading the switch unset) log "
              "the switch and each fallback once, outside zs_lock")
        for what, fault, run_checks in (("staging fill never stored", BROKEN, checks),
                                        ("whole-buffer DDict not passed", BROKEN_F, frames_checks),
                                        ("switch published after its log line", BROKEN_ONCE, conc_checks),
                                        ("switch always stored, every first caller logs", BROKEN_STORE, conc_checks),
                                        ("fallback logged under zs_lock", [BROKEN_NOTE, BROKEN_NOTE2], conc_checks)):
            try:
                broken = run_checks(build(a.cxx, tmp, broken=fault, conc=run_checks is conc_checks), tmp, quick=True)
            except Crash as e:
                broken = [str(e)]
            if not broken:
                raise SystemExit("FAIL: the broken copy (%s) passed: the checks prove nothing" % what)
            print("PASS: the broken copy (%s) fails (%d checks, e.g. %s)" % (what, len(broken), broken[0]))


if __name__ == "__main__":
    main()
