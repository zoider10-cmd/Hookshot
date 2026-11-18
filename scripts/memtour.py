#!/usr/bin/env python3
"""A memory tour: start a game folder through the control bridge, load a save, teleport through some areas while
sampling the game's memory and the system's, and write what it saw. For a report like "the game outgrows 16 GB of RAM
and the swap fills" (or for a change that should move it): one command, and numbers that two PCs, or two builds, can
compare.

    python -I scripts/memtour.py GAME_DIR (--save SAVE_FOLDER [--slot NN] | --repo-save NAME) [--out DIR]
        [--dests 13,1,2,3,0,7,9,11 | all] [--dwell 40] [--laps 1] [--settle 20] [--interval 2]
        [--env NAME=VALUE ...] [--exe FILE] [--wrapper '["admission", "command"]']

It uses `scripts/hookshot_ctl.py` (docs/control.md): `launch --profile test` (headless, a copy of the save, the game
folder's own options), A pressed until the save is loaded, the OoT debug teleport to each destination (`hookshot_ctl.py
teleport` lists them; `all` takes every one) with a walk and camera swings for DWELL seconds in each, and a clean quit.
A first start prepares shaders before the first frame: give it `--launch-timeout`, or run the game once first.

Written to OUT (default `work/memtour-<time>`, a new folder):
    mem.csv      one row every INTERVAL seconds: the game's RssAnon, RssShmem, swap (anonymous and shared), the sum
                 `game_total` (resident + swapped, file pages left out: they can be dropped), MemAvailable, swap in use
    marks.csv    the tour's events with wall times (in_play, each teleport, arrival, dwell)
    summary.md   the peaks and each area's peak, end value and lowest MemAvailable
    run/         the control run's folder (manifest, log.txt, shots/)

Linux only (it reads /proc). The numbers are observations of one run: a change is shown by runs in turn, on the same
PC, the same scene and the same settings, not by one run each way. Standard library only."""
import argparse
import csv
import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DESTS = "13,1,2,3,0,7,9,11"
COLUMNS = ["t", "wall", "pid", "rss", "anon", "shmem", "file", "vmswap", "swap_all", "shmem_swapped", "game_total",
           "memavail", "swapused", "sys_shmem"]


def load_ctl(path=None):
    spec = importlib.util.spec_from_file_location("hookshot_ctl", path or HERE / "hookshot_ctl.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def kv_mb(path, keys):
    """{key: MB} for the `Key:   N kB` lines of a /proc file, or None when it can't be read (the process went away)"""
    out = {}
    try:
        with open(path) as f:
            for line in f:
                k, _, v = line.partition(":")
                if k in keys:
                    out[k] = int(v.split()[0]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return out


def sample(pid, proc="/proc"):
    """One row of memory numbers (MB) for process `pid`, or None. game_total = RssAnon + RssShmem + smaps Swap: what the
    game holds in RAM and in swap, shared memory included (VmSwap counts only the anonymous swap entries)."""
    st = kv_mb(f"{proc}/{pid}/status", ("VmRSS", "RssAnon", "RssShmem", "RssFile", "VmSwap"))
    sm = kv_mb(f"{proc}/{pid}/smaps_rollup", ("Swap",))
    mi = kv_mb(f"{proc}/meminfo", ("MemAvailable", "SwapTotal", "SwapFree", "Shmem"))
    if not st or sm is None or not mi or "RssAnon" not in st or "MemAvailable" not in mi:
        return None
    swap_all, vmswap = sm.get("Swap", 0), st.get("VmSwap", 0)
    return dict(pid=pid, rss=st["VmRSS"], anon=st["RssAnon"], shmem=st["RssShmem"], file=st.get("RssFile", 0),
                vmswap=vmswap, swap_all=swap_all, shmem_swapped=max(swap_all - vmswap, 0),
                game_total=st["RssAnon"] + st["RssShmem"] + swap_all, memavail=mi["MemAvailable"],
                swapused=mi.get("SwapTotal", 0) - mi.get("SwapFree", 0), sys_shmem=mi.get("Shmem", 0))


class Sampler(threading.Thread):
    """Writes a row to `path` every `interval` seconds until stopped or the process is gone"""

    def __init__(self, pid, path, interval=2.0, proc="/proc"):
        super().__init__(daemon=True)
        self.pid, self.path, self.interval, self.proc = pid, path, interval, proc
        self.stop_event = threading.Event()

    def run(self):
        t0 = time.time()
        with open(self.path, "w", buffering=1, newline="") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            while not self.stop_event.is_set():
                now = time.time()
                row = sample(self.pid, self.proc)
                if row is None and not os.path.isdir(f"{self.proc}/{self.pid}"):
                    break
                if row:
                    row.update(t=round(now - t0, 1), wall=round(now, 1))
                    w.writerow([row[c] for c in COLUMNS])
                self.stop_event.wait(max(0.0, self.interval - (time.time() - now)))

    def stop(self):
        self.stop_event.set()
        self.join(10)


class Marks:
    """Events with wall times, to marks.csv as they happen and in memory for the summary"""

    def __init__(self, path, echo=True):
        self.rows, self.echo = [], echo
        self.f = open(path, "w", buffering=1, newline="")
        self.w = csv.writer(self.f)
        self.w.writerow(["wall", "event", "detail"])

    def __call__(self, event, detail=""):
        wall = time.time()
        self.rows.append((wall, event, str(detail)))
        self.w.writerow([f"{wall:.1f}", event, detail])
        if self.echo:
            print(f'{time.strftime("%H:%M:%S")} {event} {detail}', flush=True)

    def close(self):
        self.f.close()


WALK = [("L", 0, 1, 150), ("R", 0.6, 0, 60), ("L", 0.7, 0.7, 120), ("R", -0.6, 0, 60), ("L", -0.7, 0.7, 120),
        ("L", 0, -1, 90), ("R", 0.8, 0, 90)]   # (stick, x, y, frames): forward with turns and camera swings


class Tour:
    """The tour itself, against a control bridge `b` (hookshot_ctl.Bridge or anything with its request()) and the
    client module `ctl` (for Failed and check)"""

    def __init__(self, ctl, b, mark, clock=time.time, sleep=time.sleep):
        self.ctl, self.b, self.mark, self.clock, self.sleep = ctl, b, mark, clock, sleep

    def request(self, cmd, **args):
        return self.ctl.check(self.b.request(cmd, **args))

    def to_play(self, timeout=600):
        """Press A through the title and the file select until the save is loaded and Link can be steered"""
        self.request("wait", event="frame", frame=1, timeout=900)
        end = self.clock() + timeout
        while True:
            if self.ctl.ready_status(self.request("status"), "play"):
                return
            if self.clock() > end:
                raise self.ctl.Failed("the save was not loaded after %d s" % timeout, 3)
            self.request("press", buttons="A", frames=8, timeout=30)
            self.request("wait", event="present", frames=60, timeout=60)

    def walk(self, seconds):
        end, i = self.clock() + seconds, 0
        while self.clock() < end:
            s, x, y, frames = WALK[i % len(WALK)]
            i += 1
            try:
                self.request("stick", stick=s, x=x, y=y, frames=frames, timeout=30)
            except self.ctl.Failed as e:
                self.mark("input_error", e)
                self.sleep(1)

    def destinations(self, spec):
        if spec != "all":
            return [int(x) for x in spec.split(",") if x.strip()]
        return [d["index"] for d in self.request("teleport")["destinations"]]

    def teleport(self, lap, d):
        """Send the teleport (the game refuses while it is busy: retried), wait for the map and for play again"""
        sent = None
        for _ in range(6):
            try:
                r = self.request("teleport", to=d, timeout=15)
            except self.ctl.Failed as e:
                self.mark("teleport_error", f"{d} {e}")
                if "event is playing" in str(e):
                    # a text box (the owl, a first visit's words) waits for A, not for time
                    try:
                        self.request("press", buttons="A", frames=8, timeout=30)
                    except self.ctl.Failed as pe:
                        self.mark("input_error", pe)
                self.sleep(3)
                continue
            if r.get("sent"):
                sent = r
                break
            self.mark("teleport_not_sent", f'{d} {r.get("refused") or r.get("error") or r}')
            self.sleep(4)
        if not sent:
            self.mark("teleport_failed", d)
            return False
        self.mark("teleport", f'{lap}:{d}:{sent.get("map")}')
        try:
            w = self.request("wait", timeout=90, event="map", map=sent.get("map"))
            self.mark("arrived", f'{lap}:{d}:{w.get("map")}')
            self.request("wait", timeout=90, event="in_play")
        except self.ctl.Failed as e:
            self.mark("arrive_error", f"{d} {e}")
        return True

    def run(self, dests, dwell, laps, settle):
        self.to_play()
        self.mark("in_play")
        self.walk(settle)
        for lap in range(laps):
            for d in dests:
                if self.teleport(lap, d):
                    self.mark("dwell", f"{lap}:{d}")
                    self.walk(dwell)
        self.mark("tour_done")


def read_rows(path):
    with open(path, newline="") as f:
        return [{k: float(v) for k, v in r.items()} for r in csv.DictReader(f)]


def areas(marks):
    """[(label, start wall, end wall)] from the marks: the save's own area from in_play, then each teleport's dwell"""
    marks = [(float(w), e, d) for w, e, d in marks]
    out, cur = [], None
    for wall, event, detail in marks:
        if event in ("in_play", "teleport", "tour_done"):
            if cur:
                out.append((cur[0], cur[1], wall))
            cur = None if event == "tour_done" else (
                "start" if event == "in_play" else "teleport " + detail.replace(":", " "), wall)
    return out


def summarize(rows, marks, header=""):
    """Markdown: the run's peaks and each area's numbers. `rows` are mem.csv's rows, `marks` (wall, event, detail)"""
    if not rows:
        return header + "\nno memory samples\n"
    col = lambda k, rs=rows: [r[k] for r in rs]
    last = rows[-1]
    out = [header.rstrip(), "", "| | MB |", "|---|---|",
           f"| peak game total (resident + swapped) | {max(col('game_total')):,.0f} |",
           f"| game total at the end | {last['game_total']:,.0f} |",
           f"| peak private memory (RssAnon + its swap) | {max(r['anon'] + r['vmswap'] for r in rows):,.0f} |",
           f"| peak shared memory (resident + swapped) | {max(r['shmem'] + r['shmem_swapped'] for r in rows):,.0f} |",
           f"| lowest MemAvailable | {min(col('memavail')):,.0f} |",
           f"| system swap in use, peak | {max(col('swapused')):,.0f} |",
           f"| samples (below 500 MB available) | {len(rows)} ({sum(r['memavail'] < 500 for r in rows)}) |", ""]
    areas_ = areas(marks)
    if areas_:
        out += ["| area | peak total | end total | end private | end shared | lowest MemAvailable | swap peak |",
                "|---|---|---|---|---|---|---|"]
        for label, a, b in areas_:
            rs = [r for r in rows if a <= r["wall"] <= b]
            if not rs:
                continue
            e = rs[-1]
            out.append(f"| {label} | {max(col('game_total', rs)):,.0f} | {e['game_total']:,.0f} | "
                       f"{e['anon'] + e['vmswap']:,.0f} | {e['shmem'] + e['shmem_swapped']:,.0f} | "
                       f"{min(col('memavail', rs)):,.0f} | {max(col('swapused', rs)):,.0f} |")
    return "\n".join(out) + "\n"


def parse(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game_dir")
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--save", help="a save folder: a copy is the run's save, the source is only read")
    where.add_argument("--repo-save", help="a repository save (assets/saves/NAME, hookshot_ctl.py saves --repo) instead")
    ap.add_argument("--slot")
    ap.add_argument("--out", help="a new or empty folder (default work/memtour-<time>)")
    ap.add_argument("--dests", default=DEFAULT_DESTS, help="teleport indices, comma separated, or all")
    ap.add_argument("--dwell", type=float, default=40, help="seconds in each area")
    ap.add_argument("--laps", type=int, default=1)
    ap.add_argument("--settle", type=float, default=20, help="seconds in the save's own area before the first teleport")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds between memory samples")
    ap.add_argument("--env", action="append", default=[], metavar="NAME=VALUE")
    ap.add_argument("--exe")
    ap.add_argument("--wrapper", help="a JSON array: an admission command the game starts behind")
    ap.add_argument("--launch-timeout", type=float, default=900)
    a = ap.parse_args(argv)
    if a.dwell < 0 or a.laps < 1 or a.settle < 0 or a.interval <= 0:
        ap.error("--dwell and --settle are not negative, --laps is at least 1, --interval is above 0")
    return a


def main(argv=None):
    a = parse(argv)
    if not sys.platform.startswith("linux"):
        print("memtour: memory is sampled from /proc: Linux only", file=sys.stderr)
        return 2
    ctl = load_ctl()
    env = {}
    for kv in a.env:
        k, sep, v = kv.partition("=")
        if not sep or not k:
            print("memtour: --env NAME=VALUE", file=sys.stderr)
            return 2
        env[k] = v
    out = Path(a.out or "work/memtour-" + time.strftime("%Y%m%d-%H%M%S")).absolute()
    if out.is_symlink() or (out.exists() and (not out.is_dir() or any(out.iterdir()))):
        print(f"memtour: {out} is not a new or empty folder", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    session = sampler = bridge = None
    mark = Marks(out / "marks.csv")
    code = 0
    try:
        session = ctl.start_session(a.game_dir, run=str(out / "run"), exe=a.exe, save=a.save, slot=a.slot,
                                    repo_save=a.repo_save, profile="test", env=env, timeout=a.launch_timeout,
                                    wrapper=json.loads(a.wrapper) if a.wrapper else None)
        info = session.info()
        mark("started", f'pid {info["pid"]}')
        sampler = Sampler(info["pid"], out / "mem.csv", a.interval)
        sampler.start()
        bridge = ctl.Bridge(info["socket"], 10)
        tour = Tour(ctl, bridge, mark)
        tour.run(tour.destinations(a.dests), a.dwell, a.laps, a.settle)
    except ctl.Failed as e:
        mark("error", e)
        print(f"memtour: {e}", file=sys.stderr)
        code = e.code if isinstance(e.code, int) and e.code else 1
    except KeyboardInterrupt:
        mark("interrupted")
        code = 130
    finally:
        if session:
            try:
                session.stop(30, terminate=True)
            except Exception as e:   # (the game is gone or going: the samples are what matter)
                print(f"memtour: stop: {e}", file=sys.stderr)
        if sampler:
            sampler.stop()
        mark.close()
        if bridge:
            bridge.close()
    header = f"# Memory tour of {a.game_dir}\n\nsave {a.save or 'repo ' + a.repo_save}, dests {a.dests}, dwell {a.dwell} s, laps {a.laps}, " \
             f"settle {a.settle} s, env {env or '-'}, {time.strftime('%Y-%m-%d %H:%M')}"
    if (out / "mem.csv").is_file():
        text = summarize(read_rows(out / "mem.csv"), mark.rows, header)
        (out / "summary.md").write_text(text)
        print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
