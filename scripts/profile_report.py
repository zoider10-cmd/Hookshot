"""The profiling mode's report (HOS_PROFILE=1, host/profiling.c): a profile folder, logs/profile-<date>-<time>/, read into
one markdown page of where the run's time went and what each stutter was.

    python -I scripts/profile_report.py <profile folder> [--maps <folder>] [--out <file>] [--stutter-ms 50] [--top 20]
        [--from-s <s>] [--to-s <s>] [--stutters 15]

--maps: the build's symbols, to name the samples' frames: on Linux the game folder (its hookshot and hookshot_vk.so), on
Windows a folder with hookshot.map and hookshot_vk.map of the same build (RX_MAPS, as scripts/prof.py takes them). By default
the game folder the profile is in (<folder>/../..), else RX_MAPS. Without them the frames stay module+offset.
--from-s / --to-s: the part of the run to read, in seconds from its first present (by default all of it; the loading and the
first shader preparation are in it).

The page (report.md in the folder unless --out):
  At a glance   the frame rate and frame times, what limits the frame, the hottest code on the game's two serial threads,
                what the stutters are spent on, and the memory over the run: where to look first
  Over time     each part of the run: fps, its worst frames, the stutters, CPU cores and memory
  Frame parts   the frame trace's columns: a frame on average, and a stutter on average
  Threads       each thread's CPU (HOS_THREAD_TIMES) and its running share in the samples
  CPU           the hottest functions by thread: self (the leaf) and inclusive, and where the main thread waits
  Stutters      the slowest frames one by one: their trace columns, what each thread ran in them, where the main thread
                waited, and the long waits for a virtual core in them; then what all stutters share that steady frames don't
  GPU           the last GPU pass timing block of the log (RX_VK_PASS_TIMING)

It also writes load.json (the whole run as the measured window, its cores from cpu.csv) when the folder has none, so that
scripts/cpu_report.py reads the folder as a run (Windows captures, with --maps). The page names lifted functions by their
guest address (f_<address>): keep it on this PC; scripts/cpu_report.py makes the publishable view.
"""
import argparse, bisect, collections, csv, json, os, re, shutil, statistics, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prof  # noqa: E402
import samples  # noqa: E402

MAIN, PRESENT = "sead::MainThread", "Presentation_Thread"
# (the frame trace's columns that are a time in the frame: the rest are counts)
CAUSES = ("pipe_wait_ms", "translate_ms", "memsync_ms", "pipelines_ms", "uploads_ms", "programs_ms", "slot_wait_ms", "gpu_behind_ms",
          "late_wait_ms", "readback_wait_ms", "tex_frame_ms", "draw_ms", "desc_ms", "cmds_ms", "tex_lookup_ms")
PARTS = ("game_ms", "render_ms", "gpu_wait_ms", "pace_ms", "wait_render_ms", "wait_gpu_ms", "wait_main_ms")
MAIN_COLS = ("main_cpu_ms", "main_blocked_ms", "main_vcore_ms")
WHAT = {
    "pipe_wait_ms": "draws waiting for a pipeline", "translate_ms": "shader translation", "memsync_ms": "the memory sync",
    "pipelines_ms": "pipeline creation", "uploads_ms": "texture uploads", "programs_ms": "program setup",
    "slot_wait_ms": "waiting for a recording slot (the GPU behind)", "gpu_behind_ms": "the GPU behind",
    "late_wait_ms": "the capture's wait for the GPU", "readback_wait_ms": "a read-back's wait for the GPU",
    "tex_frame_ms": "the textures' frame work (eviction, sweeps)", "draw_ms": "draw translation", "desc_ms": "descriptors",
    "cmds_ms": "command recording", "tex_lookup_ms": "texture lookups",
    "game_ms": "the game's own code", "render_ms": "the renderer's recording and submitting", "gpu_wait_ms": "waiting for the GPU",
    "pace_ms": "frame pacing (the cap, the game's sleeps, V-Sync)", "wait_render_ms": "the game waiting for the renderer",
    "wait_gpu_ms": "the game waiting for the GPU", "wait_main_ms": "the present waiting for the main thread",
    "main_cpu_ms": "main thread on the CPU", "main_blocked_ms": "main thread blocked", "main_vcore_ms": "main thread waiting for a virtual core",
}


def pct(xs, p):
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(p / 100.0 * len(s)))]


def f1(x):
    return "%.1f" % x


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def num(row, k, default=0.0):
    try:
        return float(row.get(k) or default)
    except ValueError:
        return default


class Names:
    """module+offset frames named from the build's symbols (scripts/prof.py), cached by frame and by stack"""

    def __init__(self, folder):
        self.maps = prof.load_symbols(folder) if folder else {}
        self.frame_cache, self.stack_cache = {}, {}

    def frame(self, fr):
        r = self.frame_cache.get(fr)
        if r is None:
            mod, _, off = fr.rpartition("+")
            r = mod or fr
            if mod in self.maps:
                addrs, names = self.maps[mod]
                try:
                    i = bisect.bisect_right(addrs, int(off, 16)) - 1
                except ValueError:
                    i = -1
                if i >= 0:
                    r = prof.module_name(mod) + ":" + prof.demangle(names[i])
            elif mod in prof.RUN_MODS:
                r = fr   # (no symbols: the offset is all there is)
            self.frame_cache[fr] = r
        return r

    def stack(self, st):
        """(running, leaf, owner: the innermost frame of Hookshot's, named frames)"""
        r = self.stack_cache.get(st)
        if r is None:
            frames = [x for x in st.split(";") if x]
            named = [self.frame(x) for x in frames]
            leafmod = frames[0].rpartition("+")[0] if frames else ""
            running = bool(frames) and not prof.waiting(leafmod, named)
            owner = next((n for x, n in zip(frames, named) if x.rpartition("+")[0] in prof.RUN_MODS), named[0] if named else "?")
            r = self.stack_cache[st] = (running, named[0] if named else "?", owner, tuple(named))
        return r


def wait_key(named):
    """where a blocked thread waits: the import it called, under the innermost lifted function (as scripts/crit.py names it)"""
    imp = next((n for n in named if ":imp_" in n or ":hle_" in n), None)
    fn = next((n for n in named if ":f_" in n), None)
    head = imp.replace(":hle_", ":imp_", 1).split(":imp_")[1][:48] + " <- " if imp else ""
    ours = next((n for n in named if n.startswith(("hookshot:", "hookshot_vk:", "hookshot.exe:", "hookshot_vk.dll:"))), None)
    return head + (fn or ours or (named[0] if named else "?"))


def group(thread):
    """worker pools as one row: a name's trailing number left out"""
    return re.sub(r"[_ ]?\d+$", "N", thread) if re.search(r"\d+$", thread) and not thread.startswith("mkw_vk") else thread


def default_maps(d):
    """the build's symbols for a profile folder d: the game folder it is in (<d>/../..) when that holds the binaries or maps,
    else RX_MAPS"""
    game = os.path.dirname(os.path.dirname(os.path.abspath(d)))
    if any(os.path.exists(os.path.join(game, m)) for m in ("hookshot", "hookshot_vk.so", "hookshot.map", "hookshot_vk.map")):
        return game
    return os.environ.get("RX_MAPS")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--maps")
    ap.add_argument("--out")
    ap.add_argument("--stutter-ms", type=float, default=50.0)
    ap.add_argument("--stutters", type=int, default=15, help="how many of the slowest frames to show one by one")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--from-s", type=float)
    ap.add_argument("--to-s", type=float)
    ap.add_argument("--no-trace", action="store_true", help="no trace.json.gz and speedscope.json (scripts/profile_trace.py)")
    a = ap.parse_args()
    d = os.path.abspath(a.folder)
    if not os.path.isdir(d):
        raise SystemExit("no folder %s" % d)
    game = os.path.dirname(os.path.dirname(d))
    maps = a.maps or default_maps(d)
    names = Names(maps)
    out = []
    w = out.append

    # ---- the files
    log_path = os.path.join(d, "game.log")
    if not os.path.exists(log_path):   # (the run's log, beside the folder, unless a later run has written it since)
        live, pj = os.path.join(game, "logs", "hookshot_log.txt"), os.path.join(d, "process.json")
        if os.path.exists(live) and os.path.exists(pj) and os.path.getmtime(live) >= os.path.getmtime(pj):
            later = [p for p in os.listdir(os.path.dirname(d)) if p.startswith("profile-") and p > os.path.basename(d)]
            mine = os.path.basename(d) in open(live, encoding="utf-8", errors="replace").read()   # (its prof: line names the folder)
            if not later and mine:   # (the log names this folder: it is this run's)
                shutil.copyfile(live, log_path)
    log = open(log_path, encoding="utf-8", errors="replace").read().splitlines() if os.path.exists(log_path) else []
    env = {}
    if os.path.exists(os.path.join(d, "process.json")):
        env = json.load(open(os.path.join(d, "process.json"), encoding="utf-8")).get("env", {})
    presents = read_csv(os.path.join(d, "presents.csv"))
    frames = read_csv(os.path.join(d, "frames.csv"))
    cpu = read_csv(os.path.join(d, "cpu.csv"))
    events = []
    if os.path.exists(os.path.join(d, "events.txt")):
        for line in open(os.path.join(d, "events.txt"), encoding="utf-8", errors="replace"):
            ns, _, text = line.rstrip("\n").partition(" ")
            if ns.isdigit():
                m = re.match(r"vcore_wait ([\d.]+) ms from (\d+): (.*)", text)
                events.append((int(m.group(2)) if m else int(ns), int(ns), float(m.group(1)) if m else 0.0, m.group(3) if m else text))
    sample_path = os.path.join(d, "all.txt")
    t0_ns = None
    if os.path.exists(sample_path):
        with open(sample_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("# t0_ns "):
                    t0_ns = int(line.split()[2])
                    break

    # ---- the clock: seconds from the first present
    # (a run that ended abruptly cuts its last line: num() takes what is there, and a row without its time is left out)
    pres = [(int(num(r, "return_ns")), num(r, "interval_ns") / 1e6) for r in presents if num(r, "return_ns") > 0]
    fr_at = [int(num(r, "at_ns")) for r in frames]
    starts = [x for x in ([pres[0][0]] if pres else []) + ([x for x in fr_at if x][:1]) + ([t0_ns] if t0_ns else [])]
    if not starts:
        raise SystemExit("%s holds no presents, frames or samples: not a profile folder (HOS_PROFILE=1)" % d)
    origin = starts[0] if pres or any(fr_at) else min(starts)   # (the first present: the run's 0 s, as --from-s counts)
    lo = origin + int((a.from_s or 0) * 1e9)
    hi = origin + int(a.to_s * 1e9) if a.to_s is not None else None

    def inside(ns):
        return ns >= lo and (hi is None or ns <= hi)

    def sec(ns):
        return (ns - origin) / 1e9

    # (frame times: the game's presents, else the renderer's)
    if pres:
        ft = [(ns, ms) for ns, ms in pres[1:] if inside(ns) and ms > 0]
        source = "the game's presents (presents.csv)"
    else:
        ft = [(at, num(r, "ms")) for r, at in zip(frames, fr_at) if at and inside(at)]
        source = "the renderer's presents (frames.csv)"
    ms_list = [ms for _, ms in ft]
    span_s = (ft[-1][0] - ft[0][0]) / 1e9 if len(ft) > 1 else 0.0
    fps = len(ft) / span_s if span_s > 0 else 0.0
    slow = [(ns, ms) for ns, ms in ft if ms >= a.stutter_ms]

    # (the frame trace's rows in the window, and its slow frames: the stutters)
    rows = [(at, r) for r, at in zip(frames, fr_at) if at and inside(at)]
    stutters = sorted(((at, num(r, "ms"), r) for at, r in rows if num(r, "ms") >= a.stutter_ms), key=lambda x: -x[1])
    if not stutters and slow:   # (no frame trace: the game's presents)
        stutters = sorted(((ns, ms, {}) for ns, ms in slow), key=lambda x: -x[1])

    # (cpu.csv)
    cpu_rows = [(int(num(r, "t_ns")), int(num(r, "process_cpu_ns")), num(r, "rss_mb"), num(r, "available_mb")) for r in cpu
                if num(r, "t_ns") > 0 and r.get("available_mb") not in (None, "")]
    cpu_in = [c for c in cpu_rows if inside(c[0])]
    cores = (cpu_in[-1][1] - cpu_in[0][1]) / (cpu_in[-1][0] - cpu_in[0][0]) if len(cpu_in) > 1 else None

    # ---- the samples: streamed, one sweep (one ms) at a time
    windows = []   # (start_ns, end_ns, index) of the stutters
    for i, (at, ms, _) in enumerate(stutters):
        windows.append((at - ms * 1e6, at, i))
    windows.sort()
    wstarts = [x[0] for x in windows]
    th_all, th_run = collections.Counter(), collections.Counter()
    self_fn = collections.defaultdict(collections.Counter)    # thread group -> leaf -> running samples
    owner_fn = collections.defaultdict(collections.Counter)   # thread group -> innermost frame of ours -> running samples
    incl = collections.Counter()
    serial_incl = collections.defaultdict(collections.Counter)
    main_waits, main_waits_st = collections.Counter(), collections.Counter()
    st_own, st_th_all, st_th_run = collections.Counter(), collections.Counter(), collections.Counter()
    per = [dict(th_all=collections.Counter(), th_run=collections.Counter(), fn=collections.defaultdict(collections.Counter),
                waits=collections.Counter(), inst=0, idle=0) for _ in stutters]
    inst = idle = st_inst = st_idle = 0
    steady_own = collections.Counter()

    def sweep(at_ns, sw):
        nonlocal inst, idle, st_inst, st_idle
        if not inside(at_ns):
            return
        inst += 1
        game_running = any(r for th, (r, *_x) in sw if not th.startswith("mkw_vk"))
        idle += not game_running
        hit = []
        j = bisect.bisect_right(wstarts, at_ns) - 1
        while j >= 0 and len(hit) < 4:   # (the windows that hold this sweep: they seldom overlap)
            if windows[j][0] <= at_ns <= windows[j][1]:
                hit.append(windows[j][2])
            if at_ns - windows[j][0] > 5e9:
                break
            j -= 1
        if hit:
            st_inst += 1
            st_idle += not game_running
        for th, (running, leaf, owner, named) in sw:
            g = group(th)
            th_all[th] += 1
            if running:
                th_run[th] += 1
                self_fn[g][leaf] += 1
                owner_fn[g][owner] += 1
                for n in set(named):
                    incl[n] += 1
                    if th in (MAIN, PRESENT):
                        serial_incl[th][n] += 1
                (st_own if hit else steady_own)[(g, owner)] += 1
            elif th == MAIN:
                k = wait_key(named)
                main_waits[k] += 1
                if hit:
                    main_waits_st[k] += 1
            if hit:
                st_th_all[g] += 1
                st_th_run[g] += running
            for i in hit:
                p = per[i]
                p["th_all"][g] += 1
                p["th_run"][g] += running
                if running:
                    p["fn"][g][owner if leaf == owner else "%s <- %s" % (leaf, owner)] += 1
                elif th == MAIN:
                    p["waits"][wait_key(named)] += 1
        for i in hit:
            per[i]["inst"] += 1
            per[i]["idle"] += not game_running

    if os.path.exists(sample_path):
        cur, sw = None, []
        for ns, th, st in samples.timed(sample_path):   # (a sweep's samples share their time)
            if ns != cur:
                if sw:
                    sweep(cur, sw)
                cur, sw = ns, []
            sw.append((th, names.stack(st)))
        if sw:
            sweep(cur, sw)

    # ---- the log
    thread_cpu = collections.defaultdict(list)
    for line in log:
        if "prof: threads in " in line:
            for name, p in re.findall(r" ([^;]+?) (\d+)%;", line.split(":", 2)[-1]):
                thread_cpu[name.strip()].append(float(p))
    gpu_block = []
    for i, line in enumerate(log):
        if "vk: GPU pass timing, " in line:
            block = [line]
            for nxt in log[i + 1:]:
                if "vk:   " not in nxt:
                    break
                block.append(nxt)
            gpu_block = block

    # ---- the frame trace's columns
    cols = [c for c in (frames[0].keys() if frames else []) if c not in ("frame", "at_ns")]

    def mean(rs, c):
        return statistics.fmean([num(r, c) for r in rs]) if rs else 0.0
    all_rows = [r for _, r in rows]
    st_rows = [r for _, _, r in stutters if r]
    steady_rows = [r for r in all_rows if num(r, "ms") < a.stutter_ms]
    parts_med = {c: statistics.median([num(r, c) for r in steady_rows]) for c in PARTS if c in cols and steady_rows}
    dominant = collections.Counter()
    for r in st_rows:
        best = max((c for c in CAUSES + MAIN_COLS[1:] + ("game_ms",) if c in cols), key=lambda c: num(r, c), default=None)
        if best:
            dominant[best] += 1

    # ================= the page
    title = os.path.basename(d)
    w("# Profile %s" % title)
    w("")
    # (the switches, but not the paths the mode set: they name this PC's folders)
    sw_env = " ".join("`%s=%s`" % kv for kv in sorted(env.items()) if not re.search(r"[\\/]", kv[1]))
    w("Made by `scripts/profile_report.py` from `%s` (HOS_PROFILE=1). Switches: %s." % (os.path.basename(d), sw_env or "none recorded"))
    ver = next((l.split("hookshot ", 1)[1].strip() for l in log if "hookshot v" in l), None)
    gpu = next((m.group(1) for l in log for m in [re.search(r"vk: ([^;]+?, Vulkan \d+\.\d+, driver \w+); mesh shaders", l)] if m), None)
    if ver or gpu:
        w("Build %s; %s." % (ver or "?", gpu or "GPU not in the log"))
    w("Read from %.0f s to %s of the run (seconds from its first present). Frame times from %s. Symbols: %s." %
      (a.from_s or 0, "%.0f s" % a.to_s if a.to_s is not None else "its end", source,
       "the build's (%s)" % ", ".join(sorted(names.maps)) if names.maps else "none (frames are module+offset: give --maps)"))
    w("")

    # -- at a glance
    w("## At a glance")
    w("")
    if ms_list:
        w("- **Frames:** %d in %.0f s, **%.1f fps**; frame time median %.1f ms, p99 %.1f ms, p99.9 %.1f ms, worst %.1f ms. "
          "%d frames of %.0f ms or more (%d over 100 ms, %d over 250 ms)." %
          (len(ms_list), span_s, fps, statistics.median(ms_list), pct(ms_list, 99), pct(ms_list, 99.9), max(ms_list),
           len(slow), a.stutter_ms, sum(1 for x in ms_list if x > 100), sum(1 for x in ms_list if x > 250)))
    if parts_med:
        top = max(parts_med, key=parts_med.get)
        w("- **What a frame is spent on** (median of the frames under %.0f ms, the FPS counter's Breakdown): %s. The largest is "
          "**%s** (%s)%s." % (a.stutter_ms, ", ".join("%s %.1f ms" % (c, v) for c, v in parts_med.items()), top, WHAT[top],
                              ": the frame is capped or V-Synced, so the frame rate is not what limits it" if top == "pace_ms" else ""))
    for th in (MAIN, PRESENT):
        if th_all[th]:
            own = owner_fn[group(th)].most_common(3)
            fms = 1000.0 / fps if fps else 0
            w("- **%s:** running %.0f %% of the time; hottest: %s." % (
                th, 100.0 * th_run[th] / th_all[th],
                "; ".join("`%s` %.1f %% (%.2f ms a frame)" % (k, 100.0 * v / th_all[th], fms * v / th_all[th]) for k, v in own) or "-"))
    if st_rows or stutters:
        w("- **Stutters:** %d frames of %.0f ms or more in the frame trace. What took most of each: %s." % (
            len(stutters), a.stutter_ms, ", ".join("%s (%s) in %d" % (c, WHAT.get(c, c), n) for c, n in dominant.most_common(5)) or "-"))
        if st_inst and inst:
            over = []
            for k, v in st_own.most_common(200):
                s_share, b_share = v / max(1, st_inst), steady_own[k] / max(1, inst - st_inst)
                if s_share > 2 * b_share and s_share > 0.05:
                    over.append((s_share - b_share, k, s_share, b_share))
            over.sort(reverse=True)
            if over:
                w("  - Running far more in stutters than in steady frames: %s." % "; ".join(
                    "`%s` on %s (%.0f %% of a stutter's instants, %.0f %% otherwise)" % (k[1], k[0], 100 * s, 100 * b)
                    for _, k, s, b in over[:5]))
            w("  - No game thread running in %.0f %% of the stutters' instants (%.0f %% otherwise): the frame waits on something "
              "outside the game's CPU work." % (100.0 * st_idle / st_inst, 100.0 * (idle - st_idle) / max(1, inst - st_inst)))
        st_spans = [(at - ms * 1e6, at) for at, ms, _ in stutters]
        vw = [e for e in events if e[2] >= 0 and any(s <= e[1] and e[0] <= t for s, t in st_spans)]
        if events:
            w("  - %d of the run's %d long waits for a virtual core overlap a stutter." % (len(vw), len(events)))
    if len(cpu_in) > 1:
        w("- **CPU and memory:** %.2f cores on average; the process's memory %.0f MB at the start, %.0f MB at most, %.0f MB at "
          "the end; the system's available memory at least %.0f MB." % (
              cores or 0, cpu_in[0][2], max(c[2] for c in cpu_in), cpu_in[-1][2], min(c[3] for c in cpu_in)))
    w("")

    # -- over time
    if ft:
        w("## Over time")
        w("")
        total = (ft[-1][0] - ft[0][0]) / 1e9
        step = max(10, int(total / 20 / 10 + 1) * 10)
        w("| from s | fps | median ms | p99 ms | worst ms | frames >= %.0f ms | cores | memory MB |" % a.stutter_ms)
        w("|---|---|---|---|---|---|---|---|")
        b0 = ft[0][0]
        k = 0
        while b0 + k * step * 1e9 <= ft[-1][0]:
            s, e = b0 + k * step * 1e9, b0 + (k + 1) * step * 1e9
            xs = [ms for ns, ms in ft if s <= ns < e]
            cs = [c for c in cpu_rows if s <= c[0] < e]
            c_cores = (cs[-1][1] - cs[0][1]) / (cs[-1][0] - cs[0][0]) if len(cs) > 1 else None
            if xs:
                w("| %.0f | %.1f | %.1f | %.1f | %.1f | %d | %s | %s |" % (
                    sec(s), len(xs) / step, statistics.median(xs), pct(xs, 99), max(xs), sum(1 for x in xs if x >= a.stutter_ms),
                    "%.2f" % c_cores if c_cores is not None else "-", "%.0f" % max(c[2] for c in cs) if cs else "-"))
            k += 1
        w("")

    # -- frame parts
    if cols:
        w("## Frame parts (frames.csv)")
        w("")
        w("The frame trace's columns, in ms a frame (counts as they are): every frame, the frames under %.0f ms, and the "
          "stutters. Some columns are inside others (the Breakdown's parts add up to the frame; the renderer's columns are "
          "inside its part)." % a.stutter_ms)
        w("")
        w("| column | every frame | steady | stutters | what |")
        w("|---|---|---|---|---|")
        for c in cols:
            w("| %s | %.2f | %.2f | %.2f | %s |" % (c, mean(all_rows, c), mean(steady_rows, c), mean(st_rows, c), WHAT.get(c, "")))
        w("")

    # -- threads
    if th_all or thread_cpu:
        w("## Threads")
        w("")
        w("CPU: the thread's average share of a core (the log's `prof: threads in` lines, HOS_THREAD_TIMES; a thread under 5 % "
          "in a line counts 0 there). Running: its share of the samples in which it was on the CPU, not waiting.")
        w("")
        w("| thread | CPU % | running % of samples | samples |")
        w("|---|---|---|---|")
        n_lines = max((len(v) for v in thread_cpu.values()), default=0)
        avg = {t: sum(v) / n_lines for t, v in thread_cpu.items()} if n_lines else {}
        keys = sorted(set(th_all) | set(avg), key=lambda t: (-avg.get(t, 0.0), -th_run[t]))
        for t in keys[:40]:
            c = avg.get(t)
            w("| %s | %s | %s | %d |" % (t, "%.0f" % c if c is not None else "-",
                                         "%.0f" % (100.0 * th_run[t] / th_all[t]) if th_all[t] else "-", th_all[t]))
        w("")

    # -- CPU by function
    if th_all:
        w("## CPU")
        w("")
        w("Per thread (worker pools as one row), the functions it was running in: **self** the leaf (the function executing, "
          "the system's or driver's included), **ours** the innermost frame of Hookshot's code (who asked for the work). Share "
          "of that thread's samples.")
        w("")
        busy = sorted(self_fn, key=lambda g: -sum(self_fn[g].values()))
        totals = collections.Counter()
        for t, v in th_all.items():
            totals[group(t)] += v
        for g in busy[:12]:
            w("### %s" % g)
            w("")
            w("| self | % | ours | % |")
            w("|---|---|---|---|")
            sl, ol = self_fn[g].most_common(a.top), owner_fn[g].most_common(a.top)
            for i in range(max(len(sl), len(ol))):
                s = sl[i] if i < len(sl) else ("", 0)
                o = ol[i] if i < len(ol) else ("", 0)
                w("| %s | %s | %s | %s |" % ("`%s`" % s[0] if s[0] else "", f1(100.0 * s[1] / totals[g]) if s[0] else "",
                                             "`%s`" % o[0] if o[0] else "", f1(100.0 * o[1] / totals[g]) if o[0] else ""))
            w("")
        for th in (MAIN, PRESENT):
            if serial_incl[th]:
                w("### %s, inclusive (the function anywhere in the stack)" % th)
                w("")
                for k, v in serial_incl[th].most_common(a.top):
                    w("- %.1f %%  `%s`" % (100.0 * v / th_all[th], k))
                w("")
        if main_waits:
            nb = sum(main_waits.values())
            w("### Where %s waits" % MAIN)
            w("")
            w("Share of its blocked samples (%.0f %% of its samples are blocked); in stutters as a share of its blocked samples in "
              "them." % (100.0 * nb / max(1, th_all[MAIN])))
            w("")
            w("| wait | all | in stutters |")
            w("|---|---|---|")
            ns_ = sum(main_waits_st.values())
            for k, v in main_waits.most_common(a.top):
                w("| `%s` | %.1f | %s |" % (k, 100.0 * v / nb, f1(100.0 * main_waits_st[k] / ns_) if ns_ else "-"))
            w("")
        w("### Inclusive, every thread")
        w("")
        for k, v in incl.most_common(a.top):
            w("- %.1f %% of a core  `%s`" % (100.0 * v / max(1, inst), k))
        w("")

    # -- stutters
    if stutters:
        w("## Stutters")
        w("")
        w("The %d slowest of the %d frames of %.0f ms or more, slowest first. Time in seconds from the first present." % (
            min(a.stutters, len(stutters)), len(stutters), a.stutter_ms))
        w("")
        for i, (at, ms, r) in enumerate(stutters[:a.stutters]):
            w("### %.1f ms at %.1f s" % (ms, sec(at)))
            w("")
            if r:
                big = sorted(((c, num(r, c)) for c in CAUSES + PARTS + MAIN_COLS if c in r and num(r, c) >= 1.0), key=lambda x: -x[1])
                w("- **Trace:** %s." % (", ".join("%s %.1f" % kv for kv in big[:8]) or "nothing over 1 ms"))
                counts = [(c, r[c]) for c in ("pipe_waits", "left_out", "uploads", "upload_mb", "textures_gone") if c in r and num(r, c)]
                if counts:
                    w("- **Counts:** %s." % ", ".join("%s %s" % kv for kv in counts))
            p = per[i] if i < len(per) else None
            if p and p["inst"]:
                w("- **Samples:** %d sweeps; no game thread running in %d of them." % (p["inst"], p["idle"]))
                runs = sorted(p["th_all"], key=lambda g: -p["th_run"][g])
                for g in runs[:8]:
                    if not p["th_run"][g]:
                        continue
                    fn = p["fn"][g].most_common(2)
                    w("  - %s running %.0f %%: %s" % (g, 100.0 * p["th_run"][g] / p["th_all"][g],
                                                     "; ".join("`%s` %.0f %%" % (k, 100.0 * v / p["th_all"][g]) for k, v in fn)))
                if p["waits"]:
                    nw = sum(p["waits"].values())
                    w("  - %s waits in: %s" % (MAIN, "; ".join("`%s` %.0f %%" % (k, 100.0 * v / nw) for k, v in p["waits"].most_common(3))))
            ev = [e for e in events if e[0] <= at and e[1] >= at - ms * 1e6]
            for e in ev[:5]:
                w("- **Virtual core:** %.1f ms wait ending at %.1f s: %s" % (e[2], sec(e[1]), e[3]))
            w("")
    if events:
        w("## Long waits for a virtual core")
        w("")
        w("The %d longest of the run's %d (events.txt):" % (min(a.top, len(events)), len(events)))
        w("")
        for e in sorted(events, key=lambda e: -e[2])[:a.top]:
            w("- %.1f ms at %.1f s: %s" % (e[2], sec(e[1]), e[3]))
        w("")
    if gpu_block:
        w("## GPU (the log's last pass timing block)")
        w("")
        w("```")
        w("\n".join(re.sub(r"^.*?vk:", "vk:", l) for l in gpu_block))
        w("```")
        w("")

    if not a.no_trace:   # (the profiler viewers' files, linked from the page's top)
        import profile_trace
        trace, scope = profile_trace.write(d, names, a.from_s, a.to_s)
        at = out.index("## At a glance")
        out.insert(at, "**Browse it:** open `%s` in [Perfetto](https://ui.perfetto.dev) (each thread's stack over time, the frames "
                      "and stutters, the virtual-core waits, CPU and memory counters) and `%s` in "
                      "[speedscope](https://www.speedscope.app) (flame graphs and each function's self and total time by "
                      "thread). Both read the file in the browser; nothing is uploaded." % (os.path.basename(trace), os.path.basename(scope)))
        out.insert(at + 1, "")
    path = a.out or os.path.join(d, "report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    # (load.json for scripts/cpu_report.py: the read part of the run as its measured window)
    lj = os.path.join(d, "load.json")
    if not os.path.exists(lj) and pres:
        first = pres[0][0] - int(pres[0][1] * 1e6)
        json.dump({"window_present_s": [(lo - first) / 1e9 if a.from_s else 0.0, (ft[-1][0] - first) / 1e9 if ft else 0.0],
                   "window_cores": cores, "made_by": "scripts/profile_report.py"}, open(lj, "w", encoding="utf-8"))
    print(path)


if __name__ == "__main__":
    main()
