"""The PC's queue of builds, test runs and measurements: several agents (and people) share one PC, its GPU, its CPUs and its
memory, and a timed run is only worth its numbers when nothing else runs beside it (docs/development.md, *Sharing a PC: the
job queue*). Python's standard library only.

    python -I scripts/job_queue.py run NAME [--mode MODE] [--priority high|normal|low] [--when-idle] [--group G] -- CMD...
        CMD when the queue lets it, with its output as it comes. Exits with CMD's status. MODE:
          build       a build or anything heavy on the CPU and memory (make_game.py, dev_packs.py base/pack): at most
                      HOOKSHOT_QUEUE_BUILD_SLOTS (2) at once, never beside a timed run. No GPU
          light       game-free checks, a renderer-only build, copies: HOOKSHOT_QUEUE_LIGHT_SLOTS (4) at once. No GPU
          shared      the game, for anything that is not a number (screenshots, checks, logs, A/B flashes in one session):
                      up to HOOKSHOT_QUEUE_GPU_SHARED (3) at once, each with its own game folder and data folder
          gpu         the game alone on the GPU, not a measurement (builds may run beside it)
          timing      a measurement (fps, frame times, hitches): alone on the GPU, on its own CPUs, no build or other
                      timed run beside it, its memory never swapped out, and not while you play
          timing-cpu  a measurement without the GPU (a build's time): as timing, but shared and gpu runs may go beside it
          profile     a profile recorded in the game (perf, RX_VK_PGO_FILE, HOS_SAMPLE_ALL): as timing
        --priority: high before normal before low; a ticket that waited 30 min moves up a level (never past high). FIFO within
        a level, and a job never starts ahead of a waiting one it would hold up (no starvation). --when-idle: the ticket keeps
        its place but waits while you play. --group: timed runs of one group go one at a time, so one agent's batch lets
        others' go between its runs (default: the name's first word).
    python -I scripts/job_queue.py status [--json]     who plays, what runs, the queue and why each waits, memory and disk
    python -I scripts/job_queue.py history [-n N] [--json]   the last jobs: waited, ran, status, and a timed run's noise
    python -I scripts/job_queue.py cancel ID|NAME      stop a job of yours (its runner gets SIGTERM and stops its command; on
                                                       Windows the runner and every process under it end, its job object's)

Inside a job (HOOKSHOT_JOB set) run runs CMD directly: a script under the queue may call it again.

What a job gets (beside the environment it was started with):
  - HOOKSHOT_JOB, HOOKSHOT_JOB_NAME, HOOKSHOT_JOB_MODE. Never an OOT_, RX_ or A64_ variable: make_game.py lift_key hashes
    every one of those, so a variable naming the job (an older queue set OOT_STATUS_LOCK=<name>) gave each job its own lift
    key, and no build ever took another's translation from the lift store. OOT_STATUS_* inherited from that queue is dropped.
  - TMPDIR on disk: when it (or /tmp) is a RAM file system (tmpfs), it moves to <state>/tmp/<job>, kept a day after the job.
    Builds, game folders, work folders and test output never go on a RAM file system: two 5 GB test folders in /tmp once
    held 10 GB of memory and swap.
  - __GL_SHADER_DISK_CACHE_PATH (when unset) for the GPU modes: NVIDIA names its shader cache after the program, so test
    runs otherwise share (and shrink) the cache of the game you play. HOOKSHOT_QUEUE_NV_CACHE names the folder.
  - Linux: its own systemd scope (systemd-run --user --scope), so the OOM killer stops that job and not the terminal it came
    from; CPU affinity while a timed run measures (the timed run on one core complex, everything else on the others).

Every job also waits for memory: HOOKSHOT_QUEUE_MIN_FREE_GB (6) available, memory pressure (PSI "full" avg10) at most
HOOKSHOT_QUEUE_MAX_PRESSURE (10%), swap in use at most HOOKSHOT_QUEUE_MAX_SWAP_GB (32). A timed run waits too while a build
runs outside the queue (a python running make_game.py or nx2/build.py).

Settings: environment variables, or the same names in ~/.config/hookshot/job_queue.json (Windows: %APPDATA%\\Hookshot\\)
as {"HOOKSHOT_QUEUE_BUILD_SLOTS": 3, ...}; the environment wins. The CPUs: HOOKSHOT_QUEUE_TIMING_CPUS and
HOOKSHOT_QUEUE_OTHER_CPUS ("0-5,12-17"), by default the first L3 cache domain for timed runs and the rest for the others
(none when there is one). The queue's tickets are in HOOKSHOT_QUEUE_DIR ($XDG_RUNTIME_DIR/hookshot-queue), its history and
temporary folders in HOOKSHOT_QUEUE_STATE (~/.cache/hookshot-queue). Tickets of the older queue (oot-status, in
$XDG_RUNTIME_DIR/oot-gpu.queue) that are running count as running jobs here.
"""
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

WINDOWS = os.name == "nt"
if WINDOWS:
    import msvcrt
else:
    import fcntl

PRIO = {"high": 0, "normal": 1, "low": 2}
AGING = 1800   # (seconds of waiting that move a ticket up one level)
POLL = 1.0
# (mode: (GPU use, CPU use). GPU: exclusive / shared / None. CPU: quiet (a timed run's own CPUs, nothing heavy beside it) /
# heavy (a build slot) / light (a light slot) / None (counted in no slot))
MODES = {
    "build": (None, "heavy"),
    "light": (None, "light"),
    "shared": ("shared", None),
    "gpu": ("exclusive", None),
    "timing": ("exclusive", "quiet"),
    "timing-cpu": (None, "quiet"),
    "profile": ("exclusive", "quiet"),
}
MEASURING = ("timing", "timing-cpu", "profile")
# (what an HOOKSHOT_JOB variable must never be: the lift key hashes these, make_game.py lift_key)
LIFT_KEY_PREFIXES = ("A64_", "OOT_", "RX_")
DEFAULTS = {
    "HOOKSHOT_QUEUE_GPU_SHARED": "3",
    "HOOKSHOT_QUEUE_BUILD_SLOTS": "2",
    # (a third build only while HOOKSHOT_QUEUE_ROOMY_GB is free and memory pressure is low: three builds that each prepared
    # shaders once took swap to 37 GB)
    "HOOKSHOT_QUEUE_BUILD_SLOTS_MAX": "2",
    "HOOKSHOT_QUEUE_ROOMY_GB": "14",
    "HOOKSHOT_QUEUE_LIGHT_SLOTS": "4",
    "HOOKSHOT_QUEUE_MIN_FREE_GB": "6",
    "HOOKSHOT_QUEUE_MAX_PRESSURE": "10",
    "HOOKSHOT_QUEUE_MAX_SWAP_GB": "32",
    "HOOKSHOT_QUEUE_MIN_DISK_GB": "40",
    "HOOKSHOT_QUEUE_QUIET": "1",
    "HOOKSHOT_QUEUE_SCOPE": "1",
    "HOOKSHOT_QUEUE_NO_SWAP": "1",
    "HOOKSHOT_QUEUE_GAMES": "hookshot,hookshot.exe,hookshot,lichii",
    "HOOKSHOT_QUEUE_HEAVY": "make_game.py,nx2/build.py",
    "HOOKSHOT_QUEUE_TIMING_CPUS": "",
    "HOOKSHOT_QUEUE_OTHER_CPUS": "",
    "HOOKSHOT_QUEUE_DIR": "",
    "HOOKSHOT_QUEUE_STATE": "",
    "HOOKSHOT_QUEUE_NV_CACHE": "",
    "HOOKSHOT_QUEUE_LEGACY": "",
}


# ---- settings ----

def config_path():
    if WINDOWS:
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Hookshot", "job_queue.json")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "hookshot", "job_queue.json")


def settings(environ=None):
    environ = os.environ if environ is None else environ
    s = dict(DEFAULTS)
    try:
        with open(config_path(), encoding="utf-8") as f:
            s.update({k: str(v) for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError, AttributeError):
        pass
    s.update({k: environ[k] for k in DEFAULTS if environ.get(k, "") != ""})
    return s


def number(s, name):
    try:
        return float(s[name])
    except (KeyError, ValueError):
        return float(DEFAULTS[name])


def state_dir(s):
    if s["HOOKSHOT_QUEUE_STATE"]:
        return s["HOOKSHOT_QUEUE_STATE"]
    if WINDOWS:
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Hookshot", "queue")
    return os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "hookshot-queue")


def queue_dir(s):
    if s["HOOKSHOT_QUEUE_DIR"]:
        return s["HOOKSHOT_QUEUE_DIR"]
    run = None if WINDOWS else os.environ.get("XDG_RUNTIME_DIR")
    return os.path.join(run, "hookshot-queue") if run else os.path.join(state_dir(s), "tickets")


def legacy_dir(s):
    if s["HOOKSHOT_QUEUE_LEGACY"]:
        return s["HOOKSHOT_QUEUE_LEGACY"]
    run = None if WINDOWS else os.environ.get("XDG_RUNTIME_DIR")
    return os.path.join(run, "oot-gpu.queue") if run else ""


def cpu_list(text):
    out = set()
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return out


def cpu_text(cpus):
    cpus, out, i = sorted(cpus), [], 0
    while i < len(cpus):
        j = i
        while j + 1 < len(cpus) and cpus[j + 1] == cpus[j] + 1:
            j += 1
        out.append(str(cpus[i]) if i == j else "%d-%d" % (cpus[i], cpus[j]))
        i = j + 1
    return ",".join(out)


def l3_domains(sysfs="/sys/devices/system/cpu"):
    """The CPUs grouped by the L3 cache they share (a Ryzen's core complexes), first CPU first"""
    groups = set()
    try:
        names = os.listdir(sysfs)
    except OSError:
        return []
    for n in names:
        if not re.match(r"cpu\d+$", n):
            continue
        try:
            with open(os.path.join(sysfs, n, "cache", "index3", "shared_cpu_list")) as f:
                groups.add(frozenset(cpu_list(f.read().strip())))
        except (OSError, ValueError):
            continue
    return sorted(groups, key=min)


def cpu_sets(s, domains=None):
    """(the timed run's CPUs, everyone else's while it runs), or (None, None): no pinning"""
    usable = set(range(os.cpu_count() or 1))
    if hasattr(os, "sched_getaffinity"):
        usable = set(os.sched_getaffinity(0)) | usable
    timing = cpu_list(s["HOOKSHOT_QUEUE_TIMING_CPUS"]) & usable
    other = cpu_list(s["HOOKSHOT_QUEUE_OTHER_CPUS"]) & usable
    if not timing:
        domains = l3_domains() if domains is None else domains
        if len(domains) < 2:
            return None, None
        timing = set(domains[0]) & usable
    if not other:
        other = usable - timing
    if not timing or not other:
        return None, None
    return timing, other


# ---- processes ----

def proc_start(pid):
    """The process's start time (clock ticks since boot on Linux): a pid used again is not the same process"""
    if WINDOWS:
        return _win_start(pid)
    try:
        with open("/proc/%d/stat" % pid) as f:
            stat = f.read()
        return int(stat[stat.rindex(")") + 2:].split()[19])
    except (OSError, ValueError, IndexError):
        if sys.platform != "linux":
            try:
                os.kill(pid, 0)
                return 0
            except PermissionError:
                return 0
            except OSError:
                return None
        return None


def _win_start(pid):
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)   # (PROCESS_QUERY_LIMITED_INFORMATION)
    if not h:
        return None
    try:
        code = wintypes.DWORD()
        if not k.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:   # (STILL_ACTIVE)
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(h, *[ctypes.byref(t) for t in times]):
            return 0
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        k.CloseHandle(h)


# (Windows) A job's command and everything it starts, in a job object of the runner's. Windows has no signal a runner can
# clean up on: cancel's os.kill is TerminateProcess, and a runner that ends that way (or crashes, or loses its console) runs
# no finally, so its command and the command's own children went on as orphans: builds and games of a cancelled job running
# on beside the next one. With JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE the runner's handle is the job's only one, and its end,
# however it comes, kills them all. A command that ends by itself lets what it started go on, as on Linux (_win_job_release)
_KILL_ON_JOB_CLOSE = 0x2000
_CREATE_SUSPENDED = 0x00000004


def _win_job_limits(job, flags):
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class Io(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("Read", "Write", "Other", "ReadBytes", "WriteBytes", "OtherBytes")]

    class Extended(ctypes.Structure):
        _fields_ = [("Basic", Basic), ("Io", Io), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    info = Extended()
    info.Basic.LimitFlags = flags
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    return bool(k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)))   # (JobObjectExtendedLimitInformation)


def _win_job_start(child):
    """The suspended child into a new kill-on-close job object, then let go. Returns the job's handle, or None when it could not
    be made (the child runs anyway, as before)"""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    nt = ctypes.WinDLL("ntdll")
    nt.NtResumeProcess.argtypes = [wintypes.HANDLE]
    job = k.CreateJobObjectW(None, None)
    if job and not (_win_job_limits(job, _KILL_ON_JOB_CLOSE) and k.AssignProcessToJobObject(job, int(child._handle))):
        k.CloseHandle(job)
        job = None
    nt.NtResumeProcess(int(child._handle))   # (started suspended, so nothing it starts is outside the job)
    return job


def _win_job_release(job, keep_running):
    """The runner's handle on the job closed: what is still in it ends, unless keep_running (the command ended by itself: what it
    left running, a game it started, goes on as without the queue)"""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    if keep_running:
        _win_job_limits(job, 0)
    k.CloseHandle(job)


def _win_kill_tree(pid):
    """pid and every process under it (taskkill /T): a runner from before the job object, or one whose job could not be made"""
    r = subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, text=True)
    return r.returncode == 0


def pidns():
    try:
        return os.readlink("/proc/self/ns/pid")
    except (OSError, AttributeError):
        return ""


def alive(t):
    """True, False, or None: can't tell from here (another pid namespace: a sandboxed caller)"""
    if t.get("ns") and t["ns"] != pidns():
        return None
    for pid, st in ((t.get("pid"), t.get("start")), (t.get("child"), t.get("child_start"))):
        if pid:
            now = proc_start(pid)
            if now is not None and (st is None or now == st):
                return True
    return False


def all_pids():
    try:
        return [int(d) for d in os.listdir("/proc") if d.isdigit()]
    except OSError:
        return []


def argv_of(pid):
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
    except OSError:
        return []


def env_of(pid):
    """None: not readable (starting, ending, or not ours)"""
    try:
        with open("/proc/%d/environ" % pid, "rb") as f:
            data = f.read()
    except OSError:
        return None
    env = dict(kv.split("=", 1) for kv in data.decode("utf-8", "replace").split("\0") if "=" in kv)
    return env or None


def tree(pid):
    """pid and its descendants"""
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        out.append(p)
        try:
            for t in os.listdir("/proc/%d/task" % p):
                try:
                    with open("/proc/%d/task/%s/children" % (p, t)) as f:
                        todo.extend(int(c) for c in f.read().split())
                except OSError:
                    pass
        except OSError:
            pass
    return out


def pin(root, cpus):
    """Every thread of root's tree onto cpus (children started later inherit it)"""
    if not hasattr(os, "sched_setaffinity"):
        return
    for p in tree(root):
        try:
            for t in os.listdir("/proc/%d/task" % p):
                try:
                    os.sched_setaffinity(int(t), cpus)
                except OSError:
                    pass
        except OSError:
            pass


def game_procs(s):
    """The games running: [{pid, name, job}], job the HOOKSHOT_JOB (or older queue lock) it runs under, "" for nobody's
    (yours), None when its environment can't be read"""
    names = {n.strip().lower() for n in s["HOOKSHOT_QUEUE_GAMES"].split(",") if n.strip()}
    out = []
    for pid in all_pids():
        try:
            exe = os.path.basename(os.readlink("/proc/%d/exe" % pid)).replace(" (deleted)", "")
        except OSError:
            exe = ""
        argv = argv_of(pid)
        a0 = os.path.basename(argv[0]) if argv else ""
        try:
            with open("/proc/%d/comm" % pid) as f:
                comm = f.read().strip()
        except OSError:
            comm = ""
        hit = next((n for n in (exe, a0, comm) if n.lower() in names), None)
        if not hit:
            continue
        env = env_of(pid)
        job = None if env is None else (env.get("HOOKSHOT_JOB") or env.get("OOT_STATUS_LOCK") or "")
        if any(a == "--prepare-shaders" for a in argv):   # (a build's shader preparation: never someone playing)
            job = job or "prepare"
        out.append({"pid": pid, "name": hit, "job": job})
    return out


def user_playing(s):
    fake = os.environ.get("HOOKSHOT_QUEUE_PLAYING_FILE")   # (tests: you "play" while this file is there)
    if fake:
        return os.path.exists(fake)
    if WINDOWS or not any(g["job"] == "" for g in game_procs(s)):
        return False
    time.sleep(1)   # (looked at twice: a job's game between its exec and its first readable environ looks like yours)
    return any(g["job"] == "" for g in game_procs(s))


def heavy_procs(s, skip=()):
    """Builds running outside the queue: a python running one of HOOKSHOT_QUEUE_HEAVY's scripts, not in a job's tree"""
    pats = [p.strip() for p in s["HOOKSHOT_QUEUE_HEAVY"].split(",") if p.strip()]
    skip = set(skip)
    out = []
    for pid in all_pids():
        if pid in skip:
            continue
        argv = argv_of(pid)
        if argv and "python" in os.path.basename(argv[0]) and any(a.endswith(p) for a in argv[1:4] for p in pats):
            env = env_of(pid) or {}
            if not env.get("HOOKSHOT_JOB") and not env.get("OOT_STATUS_LOCK"):
                out.append(pid)
    return out


# ---- memory and disk ----

def meminfo():
    try:
        with open("/proc/meminfo") as f:
            return {l.split(":")[0]: int(l.split()[1]) * 1024 for l in f if len(l.split()) >= 2}
    except (OSError, ValueError):
        return {}


def pressure(kind="memory", line="full"):
    try:
        with open("/proc/pressure/%s" % kind) as f:
            for l in f:
                if l.startswith(line + " "):
                    return float(dict(kv.split("=") for kv in l.split()[1:])["avg10"])
    except (OSError, ValueError, KeyError):
        pass
    return None


GB = float(1 << 30)


def memory_short(s):
    """Why a job should wait for memory, or None"""
    info = meminfo()
    if not info:
        return None
    free = info.get("MemAvailable", 0) / GB
    swap = (info.get("SwapTotal", 0) - info.get("SwapFree", 0)) / GB
    if free < number(s, "HOOKSHOT_QUEUE_MIN_FREE_GB"):
        return "memory: %.1f GB free (waits for %.0f)" % (free, number(s, "HOOKSHOT_QUEUE_MIN_FREE_GB"))
    p = pressure()
    if p is not None and p > number(s, "HOOKSHOT_QUEUE_MAX_PRESSURE"):
        return "memory: thrashing, %.0f%% of the last 10 s stalled on it (waits under %.0f%%)" % (
            p, number(s, "HOOKSHOT_QUEUE_MAX_PRESSURE"))
    # (swap alone is no test of a shortage: what idle programs left there never drains, so it is only a ceiling)
    if swap > number(s, "HOOKSHOT_QUEUE_MAX_SWAP_GB"):
        return "memory: %.1f GB of swap in use (waits under %.0f)" % (swap, number(s, "HOOKSHOT_QUEUE_MAX_SWAP_GB"))
    return None


def memory_roomy(s):
    info = meminfo()
    p = pressure()
    return bool(info) and info.get("MemAvailable", 0) / GB >= number(s, "HOOKSHOT_QUEUE_ROOMY_GB") and (p is None or p < 3)


def mounts():
    try:
        with open("/proc/mounts") as f:
            return [(l.split()[1].replace("\\040", " "), l.split()[2]) for l in f if len(l.split()) >= 3]
    except OSError:
        return []


def on_ram(path, table=None):
    """The path is on a RAM file system (tmpfs, ramfs): never for builds, game folders or test output"""
    if WINDOWS:
        return False
    p = os.path.realpath(path)
    best, kind = "", ""
    for mnt, fs in mounts() if table is None else table:
        if (p == mnt or p.startswith(mnt.rstrip("/") + "/")) and len(mnt) >= len(best):
            best, kind = mnt, fs
    return kind in ("tmpfs", "ramfs")


def disk_free_gb(path):
    try:
        return shutil.disk_usage(path).free / GB
    except OSError:
        return None


# ---- the queue ----

class Lock:
    """An exclusive lock on a file (flock, or msvcrt on Windows), held for a short decision"""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.f = open(self.path, "a+")
        if WINDOWS:
            while True:
                try:
                    self.f.seek(0)
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if WINDOWS:
            try:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        self.f.close()


def write_ticket(qdir, t):
    os.makedirs(qdir, exist_ok=True)
    tmp = os.path.join(qdir, ".%d.tmp" % t["pid"])
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(t, f)
    os.replace(tmp, os.path.join(qdir, "%d.json" % t["pid"]))


def read_tickets(qdir, clean=True):
    out = []
    try:
        names = os.listdir(qdir)
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        p = os.path.join(qdir, n)
        try:
            with open(p, encoding="utf-8") as f:
                t = json.load(f)
        except (OSError, ValueError):
            continue
        if alive(t) is False:   # (left by a killed runner)
            if clean:
                try:
                    os.remove(p)
                except OSError:
                    pass
            continue
        out.append(t)
    return out


def legacy_tickets(s):
    """The older queue's running tickets (oot-status), as running jobs of the mode they map to. Its waiting ones are its own"""
    d = legacy_dir(s)
    out = []
    for t in read_tickets(d, clean=False) if d else ():
        if t.get("state") != "active":
            continue
        mode = t.get("mode")
        if mode == "timing":
            gpu, cpu = (None if t.get("cpu_only") else "exclusive"), "quiet"
            mode = "timing-cpu" if t.get("cpu_only") else "timing"
        elif mode == "build":
            gpu, cpu = None, "light" if t.get("light") else "heavy"
            mode = "light" if t.get("light") else "build"
        elif mode == "shared":
            gpu, cpu = "shared", None
        else:
            gpu, cpu, mode = "exclusive", None, "gpu"
        out.append(dict(t, mode=mode, gpu=gpu, cpu=cpu, legacy=True, pid=-abs(t.get("pid", 0)) or -1, prio=t.get("prio", "normal")))
    return out


def rank(t, now):
    p = PRIO.get(t.get("prio"), 1)
    if p == 0:
        return (-1, t["t"], t["pid"])
    return (max(0, p - int((now - t["t"]) // AGING)), t["t"], t["pid"])


def group(t):
    """Whose timed runs these are: --group, else the name's first word (area-<what> keeps two)"""
    if t.get("group"):
        return t["group"]
    parts = [p for p in re.split(r"[-:_ ./]", t["name"].lower()) if p]
    if not parts:
        return t["name"]
    return "-".join(parts[:2]) if parts[0] == "area" and len(parts) > 1 else parts[0]


def deferred(t, ts):
    """Another timed run of t's group runs, or waits since before t: t keeps its place but lets other groups' go first"""
    if t["mode"] not in MEASURING:
        return None
    for o in ts:
        if o["pid"] == t["pid"] or o["mode"] not in MEASURING or group(o) != group(t):
            continue
        if o["state"] == "active" or (o["state"] == "waiting" and o.get("ready", True) and (o["t"], o["pid"]) < (t["t"], t["pid"])):
            return o
    return None


class Use:
    """What the running jobs (and the waiting ones ahead, which keep their claim) hold"""

    def __init__(self):
        self.gpu_excl = []
        self.gpu_shared = []
        self.quiet = []
        self.heavy = []
        self.light = []

    def add(self, t):
        if t.get("gpu") == "exclusive":
            self.gpu_excl.append(t)
        elif t.get("gpu") == "shared":
            self.gpu_shared.append(t)
        {"quiet": self.quiet, "heavy": self.heavy, "light": self.light}.get(t.get("cpu"), []).append(t)


def conflict(t, use, slots, quiet=True):
    """Why t can't start beside what use holds, or None"""
    names = lambda ts: ", ".join("%s (%s)" % (o["name"], o["mode"]) for o in ts)
    if t.get("gpu") == "exclusive" and (use.gpu_excl or use.gpu_shared):
        return "the GPU: " + names(use.gpu_excl + use.gpu_shared)
    if t.get("gpu") == "shared":
        if use.gpu_excl:
            return "the GPU: " + names(use.gpu_excl)
        if len(use.gpu_shared) >= slots["shared"]:
            return "the %d shared GPU slots: %s" % (slots["shared"], names(use.gpu_shared))
    cpu = t.get("cpu")
    if cpu == "quiet":
        if use.quiet:
            return "a timed run: " + names(use.quiet)
        if quiet and use.heavy:
            return "builds (a timed run goes alone): " + names(use.heavy)
    elif cpu == "heavy":
        if quiet and use.quiet:
            return "a timed run (no build beside it): " + names(use.quiet)
        if len(use.heavy) >= slots["build"]:
            return "the %d build slots: %s" % (slots["build"], names(use.heavy))
    elif cpu == "light" and len(use.light) >= slots["light"]:
        return "the %d light slots: %s" % (slots["light"], names(use.light))
    return None


def blocker(me, ts, now, slots, quiet=True):
    """Why the ticket `me` can't start now, or None. Pure: the tickets, the time and the slots only. The running jobs hold what
    they use; each waiting ticket ahead of me (by rank) that is ready keeps a claim on what it needs, so a job behind it that
    would hold it up waits too (no starvation: a stream of shared runs never keeps a gpu run waiting for ever)"""
    s = deferred(me, ts)
    if s:
        return "one timed run per group at a time: %s first" % s["name"]
    use = Use()
    for t in ts:
        if t["state"] == "active" and t["pid"] != me["pid"]:
            use.add(t)
    waiting = sorted((t for t in ts if t["state"] == "waiting" and (t.get("ready", True) or t["pid"] == me["pid"])),
                     key=lambda t: rank(t, now))
    for t in waiting:
        if t["pid"] == me["pid"]:
            why = conflict(me, use, slots, quiet)
            return None if why is None else "waits for " + why
        if not deferred(t, ts):
            t = dict(t, name=t["name"] + ", queued ahead")
            use.add(t)
    return None


def slots_now(s, roomy=None):
    build = int(number(s, "HOOKSHOT_QUEUE_BUILD_SLOTS"))
    top = int(number(s, "HOOKSHOT_QUEUE_BUILD_SLOTS_MAX"))
    if top > build and (memory_roomy(s) if roomy is None else roomy):
        build = top
    return {"shared": int(number(s, "HOOKSHOT_QUEUE_GPU_SHARED")), "build": build,
            "light": int(number(s, "HOOKSHOT_QUEUE_LIGHT_SLOTS"))}


# ---- a job ----

def safe(name):
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name)[:48] or "job"


def job_env(environ, name, mode, s, me_pid):
    """The environment a job runs with (the module's notes): never a new OOT_, RX_ or A64_ variable"""
    env = {k: v for k, v in environ.items() if not k.startswith("OOT_STATUS_")}
    env.update(HOOKSHOT_JOB=str(me_pid), HOOKSHOT_JOB_NAME=name, HOOKSHOT_JOB_MODE=mode)
    state = state_dir(s)
    tmp = env.get("TMPDIR") or "/tmp"
    if not WINDOWS and on_ram(tmp):
        root = os.path.join(state, "tmp")
        try:
            os.makedirs(root, exist_ok=True)
            for old in os.listdir(root):
                p = os.path.join(root, old)
                if os.path.isdir(p) and time.time() - os.path.getmtime(p) > 86400:
                    shutil.rmtree(p, ignore_errors=True)
            d = os.path.join(root, "%s-%d" % (safe(name), me_pid))
            os.makedirs(d, exist_ok=True)
            env.update(TMPDIR=d, TMP=d, TEMP=d)
        except OSError:
            pass
    if MODES[mode][0] and not env.get("__GL_SHADER_DISK_CACHE_PATH"):
        nv = s["HOOKSHOT_QUEUE_NV_CACHE"] or os.path.join(state, "nvcache")
        try:
            os.makedirs(nv, exist_ok=True)   # (NVIDIA keeps no cache at all in a folder that isn't there)
            env["__GL_SHADER_DISK_CACHE_PATH"] = nv
            env.setdefault("__GL_SHADER_DISK_CACHE_SIZE", str(10 << 30))
            env.setdefault("__GL_SHADER_DISK_CACHE_SKIP_CLEANUP", "1")
        except OSError:
            pass
    return env


def scope_ok():
    if WINDOWS or not shutil.which("systemd-run"):
        return False
    try:
        return subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "--collect", "--", "true"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def history_append(s, rec):
    p = os.path.join(state_dir(s), "history.jsonl")
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


class Noise:
    """For a timed run: how busy the rest of the PC was while it measured (PSI cpu "some" avg10, the load, builds outside
    the queue moved off its CPUs), kept in the history so a noisy measurement shows"""

    def __init__(self):
        self.cpu_pressure = 0.0
        self.load = 0.0
        self.strays = set()

    def sample(self):
        p = pressure("cpu", "some")
        if p is not None:
            self.cpu_pressure = max(self.cpu_pressure, p)
        try:
            self.load = max(self.load, os.getloadavg()[0])
        except (OSError, AttributeError):
            pass

    def record(self):
        return {"cpu_pressure_max": round(self.cpu_pressure, 1), "load_max": round(self.load, 1), "builds_outside": len(self.strays)}


def say(text):
    print("job_queue: " + text, file=sys.stderr, flush=True)


def run(name, mode, cmd, prio="normal", idle=False, grp="", environ=None, s=None):
    """Queue, wait, run cmd; returns its exit status"""
    environ = dict(os.environ if environ is None else environ)
    s = settings(environ) if s is None else s
    if environ.get("HOOKSHOT_JOB") or environ.get("OOT_STATUS_LOCK"):
        say("inside job %s: running %s directly" % (environ.get("HOOKSHOT_JOB_NAME") or environ.get("OOT_STATUS_LOCK"), name))
        return subprocess.call(cmd)
    qdir = queue_dir(s)
    try:
        os.makedirs(qdir, exist_ok=True)
        probe = os.path.join(qdir, ".probe.%d" % os.getpid())
        open(probe, "w").close()
        os.remove(probe)
    except OSError as e:
        sys.exit("job_queue: can't write the queue at %s (%s). In a sandbox, run it outside: the queue is the PC's" % (qdir, e))
    gpu, cpu = MODES[mode]
    quiet = s["HOOKSHOT_QUEUE_QUIET"] != "0"
    me = {"name": name, "pid": os.getpid(), "start": proc_start(os.getpid()), "ns": pidns(), "mode": mode, "gpu": gpu,
          "cpu": cpu, "prio": prio, "t": time.time(), "state": "waiting", "ready": True, "idle": idle, "group": grp,
          "cmd": " ".join(cmd), "cwd": os.getcwd()}
    lock = os.path.join(qdir, ".lock")
    said, last_idle, child, job = None, 0.0, None, None
    noise = Noise()
    if cpu == "heavy":
        free = disk_free_gb(os.getcwd())
        if free is not None and free < number(s, "HOOKSHOT_QUEUE_MIN_DISK_GB"):
            say("%.0f GB free on this drive: clean up old workspaces, game folders and caches (Tooling's "
                "scripts/workspaces.py clean)" % free)
    try:
        with Lock(lock):
            write_ticket(qdir, me)
        while True:
            need_idle = idle or mode in MEASURING
            if need_idle and time.time() - last_idle >= (10 if me["ready"] else 2):
                last_idle = time.time()
                ready = not user_playing(s)
                if ready != me["ready"]:
                    me["ready"] = ready
                    with Lock(lock):
                        write_ticket(qdir, me)
                if not ready and said != "playing":
                    say("%s waits: you are playing (it keeps its place)" % name)
                    said = "playing"
            if me["ready"]:
                with Lock(lock):
                    ts = read_tickets(qdir) + legacy_tickets(s)
                    for t in ts:
                        if t["pid"] == me["pid"]:
                            t.update(me)
                    why = blocker(me, ts, time.time(), slots_now(s), quiet)
                    if why is None and cpu == "quiet" and quiet:
                        own = set()
                        for t in ts:
                            if t["state"] == "active" and t.get("child"):
                                own.update(tree(t["child"]))
                        strays = heavy_procs(s, own)
                        if strays:
                            why = "waits for a build outside the queue (pid %d: %s)" % (strays[0], " ".join(argv_of(strays[0])[:3]))
                    if why is None:
                        why = memory_short(s)
                    if why is None:
                        me.update(state="active", since=time.time(), waited=time.time() - me["t"])
                        write_ticket(qdir, me)
                        break
                if why != said:
                    say("%s %s" % (name, why))
                    said = why
            time.sleep(POLL)
        if said:
            say("%s starts (%s, waited %.0f s)" % (name, mode, me["waited"]))
        env = job_env(environ, name, mode, s, me["pid"])
        timing_cpus, other_cpus = cpu_sets(s)
        pre = None
        if cpu == "quiet" and timing_cpus and hasattr(os, "sched_setaffinity"):
            pre = lambda: os.sched_setaffinity(0, timing_cpus)
        run_cmd = list(cmd)
        if s["HOOKSHOT_QUEUE_SCOPE"] != "0" and scope_ok():
            props = ["-p", "MemorySwapMax=0"] if cpu == "quiet" and s["HOOKSHOT_QUEUE_NO_SWAP"] != "0" else []
            run_cmd = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                       "--unit=hookshot-job-%s-%d" % (safe(name), me["pid"])] + props + ["--"] + run_cmd
        stop = threading.Event()
        if WINDOWS:
            child = subprocess.Popen(run_cmd, env=env, creationflags=_CREATE_SUSPENDED)
            job = _win_job_start(child)
        else:
            child = subprocess.Popen(run_cmd, env=env, preexec_fn=pre)
        me.update(child=child.pid, child_start=proc_start(child.pid))
        with Lock(lock):
            write_ticket(qdir, me)
        if timing_cpus and not WINDOWS:
            threading.Thread(target=_keep_apart, args=(s, qdir, me, child.pid, cpu, timing_cpus, other_cpus, noise, stop),
                             daemon=True).start()
        try:
            rc = child.wait()
        finally:
            stop.set()
        end = time.time()
        rec = {"name": name, "mode": mode, "cmd": me["cmd"][:300], "cwd": me["cwd"], "queued": me["t"], "started": me["since"],
               "ended": end, "waited": round(me["waited"], 1), "ran": round(end - me["since"], 1), "status": rc}
        if cpu == "quiet":
            rec["noise"] = noise.record()
            if noise.strays or noise.cpu_pressure > 20:
                say("%s: the PC was busy while it measured (%s): check the numbers" % (name, json.dumps(rec["noise"])))
        history_append(s, rec)
        return rc
    finally:
        ended = child is None or child.poll() is not None
        if not ended:
            child.terminate()
            try:
                child.wait(10)
            except subprocess.TimeoutExpired:
                child.kill()
        if job is not None:
            _win_job_release(job, keep_running=ended)
        try:
            os.remove(os.path.join(qdir, "%d.json" % me["pid"]))
        except OSError:
            pass


def _keep_apart(s, qdir, me, child, cpu, timing_cpus, other_cpus, noise, stop):
    """Every 2 s while the job runs. A timed run: builds started outside the queue move off its CPUs, and the noise is
    sampled. Any other job: onto the other CPUs while a timed run measures, all of them back after it"""
    pinned = False
    while not stop.wait(2):
        if cpu == "quiet":
            noise.sample()
            own = set()
            for t in read_tickets(qdir, clean=False):
                if t.get("child"):
                    own.update(tree(t["child"]))
            for p in heavy_procs(s, own):
                noise.strays.add(p)
                pin(p, other_cpus)
            continue
        timing = any(t.get("cpu") == "quiet" and t["state"] == "active" and t["pid"] != me["pid"]
                     for t in read_tickets(qdir, clean=False) + legacy_tickets(s))
        if timing and not pinned:
            pin(child, other_cpus)
            pinned = True
        elif not timing and pinned:
            pin(child, timing_cpus | other_cpus)
            pinned = False


# ---- what runs ----

def ago(sec):
    sec = int(sec)
    return "%d s" % sec if sec < 120 else "%d min" % (sec // 60) if sec < 7200 else "%.1f h" % (sec / 3600)


def status(s, as_json=False):
    now = time.time()
    qdir = queue_dir(s)
    can_clean = os.access(qdir, os.W_OK)
    ts = read_tickets(qdir, clean=can_clean) + legacy_tickets(s)
    slots = slots_now(s)
    quiet = s["HOOKSHOT_QUEUE_QUIET"] != "0"
    games = [] if WINDOWS else game_procs(s)
    info = meminfo()
    timing_cpus, other_cpus = cpu_sets(s)
    running = sorted((t for t in ts if t["state"] == "active"), key=lambda t: t.get("since", t["t"]))
    waiting = sorted((t for t in ts if t["state"] == "waiting"), key=lambda t: rank(t, now))
    rows = []
    for t in waiting:
        why = "you are playing (keeps its place)" if not t.get("ready", True) else blocker(t, ts, now, slots, quiet)
        rows.append(dict(t, why=why or "starting (or waiting for memory)"))
    heavy = [] if WINDOWS else heavy_procs(s, [p for t in running if t.get("child") for p in tree(t["child"])])
    if as_json:
        print(json.dumps({"games": games, "running": running, "waiting": rows, "builds_outside": heavy, "slots": slots,
                          "memory": {"available_gb": info.get("MemAvailable", 0) / GB, "pressure": pressure()},
                          "queue": qdir}, indent=1))
        return 0
    yours = [g for g in games if g["job"] == ""]
    print("playing: %s" % (", ".join("%s (pid %d)" % (g["name"], g["pid"]) for g in yours) if yours else "nobody"))
    for g in games:
        if g["job"]:
            print("  game: %s pid %d under job %s" % (g["name"], g["pid"], g["job"]))
    if info:
        swap = (info.get("SwapTotal", 0) - info.get("SwapFree", 0)) / GB
        p = pressure()
        print("memory: %.1f GB available, %.1f GB swap in use%s" % (info.get("MemAvailable", 0) / GB, swap,
                                                                   "" if p is None else ", pressure %.0f%%" % p))
    free = disk_free_gb(os.getcwd())
    if free is not None:
        print("disk here: %.0f GB free" % free)
    print("CPUs: %s" % ("timed runs %s, the rest %s while one measures" % (cpu_text(timing_cpus), cpu_text(other_cpus))
                        if timing_cpus else "no pinning (one L3 domain; HOOKSHOT_QUEUE_TIMING_CPUS sets it)"))
    print("slots: %d build, %d light, %d shared GPU" % (slots["build"], slots["light"], slots["shared"]))
    print("running:" if running else "running: nothing")
    for t in running:
        print("  %-24s %-10s for %-7s waited %-7s %s%s" % (t["name"], t["mode"], ago(now - t.get("since", t["t"])),
                                                          ago(t.get("waited", 0)), t.get("cmd", "")[:70],
                                                          "  (older queue)" if t.get("legacy") else ""))
    for p in heavy:
        print("  (a build outside the queue: pid %d %s)" % (p, " ".join(argv_of(p)[:3])[:80]))
    if rows:
        print("queue:")
    for i, t in enumerate(rows, 1):
        print("  %d. %-22s %-10s %-6s waiting %-7s %s" % (i, t["name"], t["mode"], t.get("prio", "normal"), ago(now - t["t"]), t["why"]))
    return 0


def history(s, n=20, as_json=False):
    p = os.path.join(state_dir(s), "history.jsonl")
    try:
        with open(p, encoding="utf-8") as f:
            recs = [json.loads(l) for l in f if l.strip()][-n:]
    except (OSError, ValueError):
        recs = []
    if as_json:
        print(json.dumps(recs, indent=1))
        return 0
    for r in recs:
        noise = r.get("noise")
        print("%s  %-24s %-10s waited %-7s ran %-7s status %-4s%s" % (
            time.strftime("%m-%d %H:%M", time.localtime(r["started"])), r["name"], r["mode"], ago(r["waited"]), ago(r["ran"]),
            r["status"], "  noise %s" % json.dumps(noise) if noise else ""))
    return 0


def cancel(s, what):
    hits = [t for t in read_tickets(queue_dir(s)) if str(t["pid"]) == what or t["name"] == what]
    if not hits:
        sys.exit("job_queue: no job %s in the queue" % what)
    for t in hits:
        try:
            if WINDOWS and _win_kill_tree(t["pid"]):   # (the runner and its command's whole tree, for a runner without a job object too)
                say("stopped %s (pid %d) and every process it started" % (t["name"], t["pid"]))
                continue
            os.kill(t["pid"], signal.SIGTERM)
            say("stopped %s (pid %d)" % (t["name"], t["pid"]))
        except OSError as e:
            say("could not stop %s: %s" % (t["name"], e))
    return 0


def main(argv):
    cmd = []
    if "--" in argv:   # (the command is everything after --, its own options too: argparse's REMAINDER took ours with it)
        i = argv.index("--")
        argv, cmd = argv[:i], argv[i + 1:]
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="what", required=True)
    r = sub.add_parser("run")
    r.add_argument("name")
    r.add_argument("--mode", choices=sorted(MODES), default="gpu")
    r.add_argument("--priority", choices=sorted(PRIO), default="normal")
    r.add_argument("--when-idle", action="store_true")
    r.add_argument("--group", default="")
    st = sub.add_parser("status")
    st.add_argument("--json", action="store_true")
    h = sub.add_parser("history")
    h.add_argument("-n", type=int, default=20)
    h.add_argument("--json", action="store_true")
    c = sub.add_parser("cancel")
    c.add_argument("job")
    a = p.parse_args(argv)
    s = settings()
    if a.what == "status":
        return status(s, a.json)
    if a.what == "history":
        return history(s, a.n, a.json)
    if a.what == "cancel":
        return cancel(s, a.job)
    if not cmd:
        p.error("run needs a command after --")
    if not WINDOWS:   # (a kill runs the clean-up: the command stopped, the ticket gone)
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
        signal.signal(signal.SIGHUP, lambda *_: sys.exit(129))
    return run(a.name, a.mode, cmd, a.priority, a.when_idle, a.group)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
