"""Which lifted functions run in a play session, and when each first ran: the data for sizing a hot list (what must be
compiled at full speed before Play, and what could wait or take a cheaper path; #362).

    python -I scripts/coverage/cover.py run <game folder> [--out DIR] [--seconds N] [--env K=V ...] [--nm llvm-nm.exe]
    python -I scripts/coverage/cover.py report <run folder> [--gen DIR | --csize FILE] [--hot LIST ...] [--json]
    python -I scripts/coverage/cover.py compare <listed run> <played run> [--csize FILE]

run: starts <game folder>\\bin\\hookshot.exe the way the launcher's Play does (that folder as the working folder, no arguments)
with cover_dll.c loaded before its entry point, then waits for the game to end (or --seconds, then stops it). Nothing is built
again: the lifted functions are found in the exe's own symbol table (f_<guest address>), and the DLL is compiled from
cover_dll.c with the launcher's clang (llvm-mingw). Marks: press Ctrl+Alt+M (in the game too; Windows' default sound says it
was taken) or type a note and Enter here. The first two hotkey marks are named "title screen" and "in play (file loaded)",
later ones "mark 3", ...; each is kept with its time, and the report says how many functions had run by then. Windows
only (run); report and compare read a run folder anywhere. The run folder (default
%LOCALAPPDATA%\\HookshotCover\\<date-time>) gets: fns.txt (each function's offset in the exe, its name(s) and host code
bytes), cover.bin (the DLL's: first-run time per function, rewritten every 5 s), marks.txt, cover.bin.log, report.txt.
What it holds is offsets, names (guest addresses) and times: no game code or data. The cost in the game: one breakpoint
exception per function, the first time it runs, and ~400 MB more committed memory (the code pages become private copies).

report: how many functions ran, their share of the host code (and of the lifted C with --gen, the lifted C folder of the
same game build, or --csize, a "name bytes" file), when they first ran (the arrival of new functions per 100 ms and per
second: what compiling them on first use would have to keep up with), what the given hot lists cover, and covered.txt
(the functions that ran, in first-run order with their times). Compile costs use nx2/chunks.py's model (size +
size^2/350000) over the lifted C, scaled to --compiler-s: the -O1 compiler-seconds of the whole lifted C (6,478 in
nightly-34's first build on a Ryzen 5 5600). compare: one run's functions as a shipped list, another run played against it.
"""
import argparse
import bisect
import ctypes
import datetime
import glob
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FN = re.compile(r"^([0-9a-fA-F]+) [Tt] (f_[0-9a-f]{8})$")
HEAD = re.compile(rb"^void (f_[0-9a-f]+)\(Ctx \*__restrict A64_NOESC c\) \{", re.M)
COMPILER_S = 6478.0   # (the lifted C's -O1 compiler-seconds: nightly-34's first build, Ryzen 5 5600, 4 compilers at once)


# ---- the toolchain ------------------------------------------------------------------------------------------------------
def tool_dirs():
    local = os.environ.get("LOCALAPPDATA", "")
    found = sorted(glob.glob(os.path.join(local, "HookshotLauncher", "toolchains", "*", "HookshotBuilder", "tools", "llvm-mingw", "bin")),
                   key=os.path.getmtime, reverse=True)
    found += glob.glob(os.path.join(local, "HookshotBuilder", "versions", "*", "*", "tools", "llvm-mingw", "bin"))
    return found


def tool(name, given=None):
    if given:
        return given
    for d in tool_dirs():
        p = os.path.join(d, name + ".exe")
        if os.path.exists(p):
            return p
    p = shutil.which(name)
    if p:
        return p
    sys.exit("cover: no %s found (the Hookshot Launcher's toolchain, or on the PATH)" % name)


def image_base(exe):
    with open(exe, "rb") as f:
        head = f.read(4096)
    pe = struct.unpack_from("<I", head, 0x3C)[0]
    if head[pe:pe + 4] != b"PE\0\0" or struct.unpack_from("<H", head, pe + 24)[0] != 0x20B:
        sys.exit("cover: %s is not a 64-bit PE file" % exe)
    return struct.unpack_from("<Q", head, pe + 24 + 24)[0]


def functions(exe, out, nm=None):
    """fns.bin (sorted distinct RVAs, uint32) and fns.txt ("rva host_bytes name[,name]") from the exe's symbol table"""
    t = time.time()
    text = subprocess.run([tool("llvm-nm", nm), "--defined-only", exe], capture_output=True, text=True, check=True).stdout
    base = image_base(exe)
    syms, fns = [], {}
    for line in text.splitlines():
        p = line.split()
        if len(p) == 3 and p[1] in "Tt":
            a = int(p[0], 16)
            syms.append(a)
            if p[2].startswith("f_") and len(p[2]) == 10:
                fns.setdefault(a - base, []).append(p[2])
    if not fns:
        sys.exit("cover: %s has no f_ symbols (a stripped exe?)" % exe)
    syms = sorted(set(syms))
    rvas = sorted(fns)
    with open(os.path.join(out, "fns.bin"), "wb") as f:
        f.write(struct.pack("<%dI" % len(rvas), *rvas))
    with open(os.path.join(out, "fns.txt"), "w", encoding="ascii") as f:
        for r in rvas:
            i = bisect.bisect_right(syms, r + base)
            size = (syms[i] - (r + base)) if i < len(syms) else 0
            f.write("%x %d %s\n" % (r, size, ",".join(fns[r])))
    print("cover: %d lifted functions (%d names) in %s, %.1f s" % (len(rvas), sum(len(v) for v in fns.values()),
                                                                  os.path.basename(exe), time.time() - t), flush=True)
    return len(rvas)


def build_dll(out, cc=None):
    src = os.path.join(HERE, "cover_dll.c")
    dll = os.path.join(out, "cover.dll")
    cc = cc or tool("x86_64-w64-mingw32-clang")
    subprocess.run([cc, "-O2", "-shared", "-municode", "-o", dll, src, "-Wl,--dependent-load-flag=0x800"], check=True)
    return dll


# ---- starting the game with the DLL ------------------------------------------------------------------------------------
if os.name == "nt":
    import ctypes.wintypes as w

    class SI(ctypes.Structure):
        _fields_ = [("cb", w.DWORD), ("lpReserved", w.LPWSTR), ("lpDesktop", w.LPWSTR), ("lpTitle", w.LPWSTR)] + \
                   [(f, w.DWORD) for f in ("dwX", "dwY", "dwXSize", "dwYSize", "dwXCountChars", "dwYCountChars", "dwFillAttribute",
                                           "dwFlags")] + \
                   [("wShowWindow", w.WORD), ("cbReserved2", w.WORD), ("lpReserved2", ctypes.c_void_p),
                    ("hStdInput", w.HANDLE), ("hStdOutput", w.HANDLE), ("hStdError", w.HANDLE)]


    class PI(ctypes.Structure):
        _fields_ = [("hProcess", w.HANDLE), ("hThread", w.HANDLE), ("dwProcessId", w.DWORD), ("dwThreadId", w.DWORD)]


    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL, w.DWORD, ctypes.c_void_p, w.LPCWSTR,
                                   ctypes.POINTER(SI), ctypes.POINTER(PI)]
    k32.VirtualAllocEx.restype = ctypes.c_void_p
    k32.VirtualAllocEx.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_size_t, w.DWORD, w.DWORD]
    k32.WriteProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k32.GetModuleHandleW.restype = ctypes.c_void_p
    k32.GetProcAddress.restype = ctypes.c_void_p
    k32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    k32.QueueUserAPC.argtypes = [ctypes.c_void_p, w.HANDLE, ctypes.c_size_t]
    k32.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    k32.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    k32.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]


def start_game(exe, folder, env, dll, args=""):
    block = "".join("%s=%s\0" % kv for kv in sorted(env.items(), key=lambda kv: kv[0].upper())) + "\0"
    eb = ctypes.create_unicode_buffer(block, len(block))
    si = SI(); si.cb = ctypes.sizeof(SI)
    pi = PI()
    cmd = ctypes.create_unicode_buffer('"%s"%s' % (exe, (" " + args) if args else ""))
    CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT = 0x4, 0x400
    if not k32.CreateProcessW(None, cmd, None, None, False, CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT, eb, folder,
                              ctypes.byref(si), ctypes.byref(pi)):
        sys.exit("cover: could not start %s (error %d)" % (exe, ctypes.get_last_error()))
    path = (dll + "\0").encode("utf-16-le")
    mem = k32.VirtualAllocEx(pi.hProcess, None, len(path), 0x3000, 0x04)
    ok = mem and k32.WriteProcessMemory(pi.hProcess, mem, path, len(path), None)
    load = k32.GetProcAddress(k32.GetModuleHandleW("kernel32.dll"), b"LoadLibraryW")
    # (an APC on the suspended main thread: it runs when the loader has set the process up, before the exe's entry point)
    ok = ok and load and k32.QueueUserAPC(load, pi.hThread, mem)
    if not ok:
        k32.TerminateProcess(pi.hProcess, 1)
        sys.exit("cover: could not load the DLL into the game (error %d)" % ctypes.get_last_error())
    k32.ResumeThread(pi.hThread)
    k32.CloseHandle(pi.hThread)
    return pi.hProcess, pi.dwProcessId


def read_cover(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != b"LSCOV1\0\0":
        raise ValueError("%s is not a cover file" % path)
    start, n, seen = struct.unpack_from("<QII", data, 8)
    return start, list(struct.unpack_from("<%dI" % n, data, 24)), seen


def run(a):
    if os.name != "nt":
        sys.exit("cover: run is Windows only (the DLL hooks the Windows game); report and compare work anywhere")
    folder = os.path.abspath(a.folder)
    exe = os.path.join(folder, "bin", "hookshot.exe")
    if not os.path.exists(exe):
        sys.exit("cover: %s has no bin\\hookshot.exe" % folder)
    out = os.path.abspath(a.out or os.path.join(os.environ["LOCALAPPDATA"], "HookshotCover",
                                                datetime.datetime.now().strftime("%Y%m%d-%H%M%S")))
    os.makedirs(out, exist_ok=True)
    busy = subprocess.run(["tasklist", "/FI", "IMAGENAME eq hookshot.exe", "/NH"], capture_output=True, text=True).stdout
    if "hookshot.exe" in busy.lower() and not a.force:
        sys.exit("cover: a game (hookshot.exe) is running already; close it first (or --force)")
    functions(exe, out, a.nm)
    dll = build_dll(out, a.cc)
    env = dict(os.environ)
    for kv in a.env:
        k, _, v = kv.partition("=")
        env[k] = v
    env.update(COVER_FNS=os.path.join(out, "fns.bin"), COVER_OUT=os.path.join(out, "cover.bin"))
    with open(os.path.join(out, "run.json"), "w") as f:
        json.dump(dict(folder=folder, exe=exe, exe_bytes=os.path.getsize(exe), exe_mtime=os.path.getmtime(exe),
                       env=a.env, started=time.time()), f, indent=1)
    marks = open(os.path.join(out, "marks.txt"), "a", encoding="utf-8")
    t0 = time.time()
    proc, pid = start_game(exe, folder, env, dll, a.args)
    print("cover: the game is running (pid %d); results go to %s" % (pid, out), flush=True)
    if not a.seconds:
        print("cover: press Ctrl+Alt+M (in the game too) when the title screen shows, again when you are in play after loading "
              "your file, and any time after; or type a note here and press Enter. Close the game normally to finish.", flush=True)

    def note():
        for line in sys.stdin:
            if line.strip():
                marks.write("%.1f %s\n" % (time.time() - t0, line.strip()))
                marks.flush()
                print("cover: marked '%s' at %.0f s" % (line.strip(), time.time() - t0), flush=True)
    def hotkey():
        # (Ctrl+Alt+M in any window, the game's too: a mark without leaving the game. The first two are named: the moments a
        # hot list is sized against; Windows' default sound says it was taken)
        import winsound
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        if not u32.RegisterHotKey(None, 1, 0x0001 | 0x0002 | 0x4000, ord("M")):   # (MOD_ALT | MOD_CONTROL | MOD_NOREPEAT)
            print("cover: Ctrl+Alt+M is taken by another program: type the notes here instead", flush=True)
            return
        names = ["title screen", "in play (file loaded)"]
        n = 0
        msg = w.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:   # (WM_HOTKEY)
                text = names[n] if n < len(names) else "mark %d" % (n + 1)
                n += 1
                marks.write("%.1f %s\n" % (time.time() - t0, text))
                marks.flush()
                print("cover: marked '%s' at %.0f s" % (text, time.time() - t0), flush=True)
                winsound.MessageBeep(0)
    if not a.seconds:
        threading.Thread(target=note, daemon=True).start()
        threading.Thread(target=hotkey, daemon=True).start()
    cov = os.path.join(out, "cover.bin")
    said_ok = False
    last_print = 0
    while k32.WaitForSingleObject(proc, 1000) == 0x102:   # (WAIT_TIMEOUT)
        el = time.time() - t0
        if not said_ok and el > 30:
            if not os.path.exists(cov):
                print("cover: WARNING: the DLL has written nothing after 30 s; see %s.log" % cov, flush=True)
            said_ok = True
        if el - last_print >= a.every and os.path.exists(cov):
            last_print = el
            try:
                _, firsts, seen = read_cover(cov)
                print("cover: %4.0f s: %d of %d functions have run" % (el, seen, len(firsts)), flush=True)
            except (OSError, ValueError, struct.error):
                pass
        if a.seconds and el >= a.seconds:
            print("cover: %d s reached; stopping the game (this tool started it)" % a.seconds, flush=True)
            time.sleep(6)   # (one more flush first)
            k32.TerminateProcess(proc, 0)
            k32.WaitForSingleObject(proc, 30000)
            break
    code = w.DWORD()
    k32.GetExitCodeProcess(proc, ctypes.byref(code))
    print("cover: the game ended (exit code %#x) after %.0f s" % (code.value, time.time() - t0), flush=True)
    marks.close()
    report(argparse.Namespace(run=out, gen=a.gen, csize=a.csize, hot=a.hot, json=False, compiler_s=a.compiler_s))


def model(size):
    """nx2/chunks.py's compile-cost model of one function's C"""
    return size + size * size // 350000


# ---- the report ----------------------------------------------------------------------------------------------------------
def c_sizes(gen):
    size = {}
    for p in sorted(glob.glob(os.path.join(gen, "code_*.c"))):
        t = open(p, "rb").read()
        ms = list(HEAD.finditer(t))
        st = [m.start() for m in ms] + [len(t)]
        for m, x, y in zip(ms, st, st[1:]):
            size[m.group(1).decode()] = y - x
    return size


def report(a):
    out = os.path.abspath(a.run)
    start, firsts, seen = read_cover(os.path.join(out, "cover.bin"))
    fns = []
    for line in open(os.path.join(out, "fns.txt"), encoding="ascii"):
        r, size, names = line.split()
        fns.append((int(r, 16), int(size), names.split(",")))
    if len(fns) != len(firsts):
        sys.exit("cover: fns.txt and cover.bin differ in length")
    csize = None
    if a.csize:
        csize = {l.split()[0]: int(l.split()[1]) for l in open(a.csize)}
    elif a.gen:
        csize = c_sizes(a.gen)
        with open(os.path.join(out, "csize.txt"), "w") as f:
            f.writelines("%s %d\n" % kv for kv in sorted(csize.items()))
    lines = []
    say = lines.append
    ran = [i for i, t in enumerate(firsts) if t]
    host_all = sum(s for _, s, _ in fns)
    host_ran = sum(fns[i][1] for i in ran)
    last = max(firsts) if ran else 0
    say("Run %s: %.0f s of the game recorded (the last first call at %.1f s)" % (out, last / 1000, last / 1000))
    say("Functions that ran: %d of %d = %.1f%%; their host code %.1f of %.1f MB = %.1f%%"
        % (len(ran), len(fns), 100.0 * len(ran) / len(fns), host_ran / 2**20, host_all / 2**20, 100.0 * host_ran / max(1, host_all)))
    cs = None
    if csize:
        cs = [sum(csize.get(n, 0) for n in names) for _, _, names in fns]
        c_all, c_ran = sum(cs), sum(cs[i] for i in ran)
        say("Their lifted C: %.1f of %.1f MB = %.1f%%" % (c_ran / 2**20, c_all / 2**20, 100.0 * c_ran / max(1, c_all)))
        # (nx2/chunks.py's compile-cost model, size + size^2/350000, scaled to the whole lifted C's -O1 compiler time)
        k_all = sum(model(s) for s in cs)
        k_ran = sum(model(cs[i]) for i in ran)
        say("Their compile cost (the build's model): %.1f%% = ~%.0f of the %.0f -O1 compiler-s of the whole lifted C"
            % (100.0 * k_ran / max(1, k_all), a.compiler_s * k_ran / max(1, k_all), a.compiler_s))
        sec_per = a.compiler_s / max(1, k_all)
    # (marks: how much had run by each)
    mp = os.path.join(out, "marks.txt")
    if os.path.exists(mp):
        try:
            started = json.load(open(os.path.join(out, "run.json")))["started"]
        except (OSError, ValueError, KeyError):
            started = start / 1000
        for line in open(mp, encoding="utf-8"):
            t, _, text = line.strip().partition(" ")
            at = (float(t) + started - start / 1000) * 1000
            k = [i for i in ran if firsts[i] <= at]
            extra = (", C %.1f MB" % (sum(cs[i] for i in k) / 2**20)) if cs else ""
            say("  by '%s' (%.0f s): %d functions, host %.1f MB%s" % (text, at / 1000, len(k), sum(fns[i][1] for i in k) / 2**20, extra))
    # (arrival: new functions per window, what a compile-on-first-use tier would have to keep up with)
    for win in (100, 1000, 10000):
        buckets = {}
        for i in ran:
            b = firsts[i] // win
            e = buckets.setdefault(b, [0, 0, 0])
            e[0] += 1
            e[1] += fns[i][1]
            e[2] += model(cs[i]) * sec_per if cs else 0
        top = sorted(buckets.items(), key=lambda kv: -kv[1][2 if cs else 1])[:5]
        say("Busiest %d ms windows (start s: new functions / host KB%s): %s" % (
            win, " / est. -O1 compiler-s" if cs else "",
            "; ".join("%.1f: %d / %d%s" % (b * win / 1000, e[0], e[1] >> 10, (" / %.1f" % e[2]) if cs else "") for b, e in top)))
        if cs and win == 100:
            loads = sorted(e[2] for e in buckets.values())
            say("  100 ms windows with new functions: %d; their est. -O1 compile time: median %.2f s, 99th pct %.1f s, max %.1f s; "
                "windows over 0.1 s of compiling: %d" % (len(loads), loads[len(loads) // 2], loads[int(len(loads) * 0.99)], loads[-1],
                                                         sum(1 for x in loads if x > 0.1)))
    # (the arrival over time, per minute)
    per_min = {}
    for i in ran:
        per_min[firsts[i] // 60000] = per_min.get(firsts[i] // 60000, 0) + 1
    say("New functions per minute: " + " ".join("%d:%d" % kv for kv in sorted(per_min.items())))
    if cs:
        big = sorted(ran, key=lambda i: -cs[i])[:10]
        say("Largest that ran (C KB at first-run s): " + ", ".join("%s %d@%.1f" % (fns[i][2][0], cs[i] >> 10, firsts[i] / 1000) for i in big))
    by_name = {n: i for i, (_, _, names) in enumerate(fns) for n in names}
    for h in a.hot or []:
        names = [l.split()[0] for l in open(h) if l.startswith("f_")]
        idx = {by_name[n] for n in names if n in by_name}
        both = [i for i in idx if firsts[i]]
        say("%s: %d functions, %d ran in this session (%.1f%% of the list); the list holds %.1f%% of what ran (host bytes %.1f%%)"
            % (os.path.basename(h), len(idx), len(both), 100.0 * len(both) / max(1, len(idx)), 100.0 * len(both) / max(1, len(ran)),
               100.0 * sum(fns[i][1] for i in both) / max(1, host_ran)))
    with open(os.path.join(out, "covered.txt"), "w", encoding="ascii") as f:
        for i in sorted(ran, key=lambda i: firsts[i]):
            f.write("%s %d\n" % (fns[i][2][0], firsts[i]))
    text = "\n".join(lines)
    print(text)
    with open(os.path.join(out, "report.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    if a.json:
        print(json.dumps(dict(ran=len(ran), total=len(fns), host_ran=host_ran, host_all=host_all)))


def compare(a):
    """A list from one session (A) shipped, another session (B) played: what B runs that A's list lacks (the misses a lazy tier
    would compile on first call or fall back for), when they come and how bunched. Both runs must be of the same exe."""
    def load(run):
        start, firsts, _ = read_cover(os.path.join(run, "cover.bin"))
        names = [line.split()[2].split(",")[0] for line in open(os.path.join(run, "fns.txt"), encoding="ascii")]
        return {n: t for n, t in zip(names, firsts) if t}
    A, B = load(a.listed), load(a.played)
    csize = {l.split()[0]: int(l.split()[1]) for l in open(a.csize)} if a.csize else {}
    k_all = sum(model(s) for s in csize.values()) or 1
    sec = lambda n: a.compiler_s * model(csize.get(n, 0)) / k_all
    miss = sorted((t, n) for n, t in B.items() if n not in A)
    print("listed run: %d functions; played run: %d; played but not listed: %d (%.1f%% of the played run's functions)"
          % (len(A), len(B), len(miss), 100.0 * len(miss) / max(1, len(B))))
    if csize:
        print("their lifted C %.1f MB, est. -O1 compile %.0f compiler-s" % (sum(csize.get(n, 0) for _, n in miss) / 2**20,
                                                                            sum(sec(n) for _, n in miss)))
    for win in (100, 1000):
        b = {}
        for t, n in miss:
            e = b.setdefault(t // win, [0, 0.0])
            e[0] += 1
            e[1] += sec(n) if csize else 0
        counts = sorted(e[0] for e in b.values())
        if counts:
            print("%d ms windows with misses: %d; misses per window: median %d, 99th pct %d, max %d%s" % (
                win, len(counts), counts[len(counts) // 2], counts[int(len(counts) * 0.99)], counts[-1],
                ("; est. -O1 compile per window: max %.1f s" % max(e[1] for e in b.values())) if csize else ""))
    per_min = {}
    for t, _ in miss:
        per_min[t // 60000] = per_min.get(t // 60000, 0) + 1
    print("misses per minute: " + " ".join("%d:%d" % kv for kv in sorted(per_min.items())))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("folder")
    r.add_argument("--out")
    r.add_argument("--seconds", type=int, default=0, help="stop the game after this many seconds (scripted runs)")
    r.add_argument("--env", action="append", default=[], help="K=V for the game's environment")
    r.add_argument("--args", default="", help="the game's command line arguments")
    r.add_argument("--every", type=int, default=30, help="print the count every this many seconds")
    r.add_argument("--nm")
    r.add_argument("--cc")
    r.add_argument("--force", action="store_true")
    for q in (r, sub.add_parser("report")):
        if q is not r:
            q.add_argument("run")
            q.add_argument("--json", action="store_true")
        q.add_argument("--gen", help="the lifted C folder of the same game build (sa/gen)")
        q.add_argument("--csize", help='a file of "f_name bytes" lines (csize.txt from an earlier report)')
        q.add_argument("--hot", action="append", help="a list of functions (hot_funcs.txt, hot_order.txt) to compare")
    c = sub.add_parser("compare", help="one run's functions as the shipped list, another run played against it")
    c.add_argument("listed")
    c.add_argument("played")
    c.add_argument("--csize")
    for q in (r, sub.choices["report"], c):
        q.add_argument("--compiler-s", type=float, default=COMPILER_S,
                       help="the -O1 compiler-seconds of the whole lifted C, which the cost model is scaled to (default %(default).0f)")
    a = p.parse_args()
    if a.cmd == "run":
        run(a)
    elif a.cmd == "compare":
        compare(a)
    else:
        report(a)


if __name__ == "__main__":
    main()
