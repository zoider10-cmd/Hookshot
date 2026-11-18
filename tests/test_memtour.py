"""scripts/memtour.py without a game: the memory sampler against a made-up /proc, the tour against a fake control bridge
(what it presses, in which order, how it copes with a refused teleport and with a save that never loads), and the summary
(peaks, and each area's numbers cut out by the tour's marks).

python -I -B tests/test_memtour.py
"""
import importlib.util
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ctl = load("hookshot_ctl")
mt = load("memtour")


def fake_proc(root, pid=42, anon=3000, shmem=5000, swap=700, vmswap=200, avail=900, swap_used=1500):
    kb = 1024
    (root / str(pid)).mkdir(parents=True, exist_ok=True)
    (root / str(pid) / "status").write_text(
        f"Name:\thookshot\nVmRSS:\t{(anon + shmem + 50) * kb} kB\nRssAnon:\t{anon * kb} kB\nRssFile:\t{50 * kb} kB\n"
        f"RssShmem:\t{shmem * kb} kB\nVmSwap:\t{vmswap * kb} kB\n")
    (root / str(pid) / "smaps_rollup").write_text(f"Rss:\t1 kB\nSwap:\t{swap * kb} kB\nSwapPss:\t1 kB\n")
    (root / "meminfo").write_text(
        f"MemTotal:\t{15000 * kb} kB\nMemAvailable:\t{avail * kb} kB\nShmem:\t{5000 * kb} kB\n"
        f"SwapTotal:\t{8000 * kb} kB\nSwapFree:\t{(8000 - swap_used) * kb} kB\n")


class Sampling(unittest.TestCase):
    def test_a_row_counts_resident_and_swapped_memory_once(self):
        with tempfile.TemporaryDirectory() as d:
            fake_proc(Path(d))
            r = mt.sample(42, d)
        self.assertEqual((r["anon"], r["shmem"], r["vmswap"], r["swap_all"]), (3000, 5000, 200, 700))
        self.assertEqual(r["shmem_swapped"], 500)                # smaps Swap counts shared pages VmSwap leaves out
        self.assertEqual(r["game_total"], 3000 + 5000 + 700)     # file pages are not in it
        self.assertEqual((r["memavail"], r["swapused"]), (900, 1500))

    def test_a_process_that_is_gone_gives_no_row(self):
        with tempfile.TemporaryDirectory() as d:
            fake_proc(Path(d))
            self.assertIsNone(mt.sample(43, d))

    def test_the_sampler_writes_rows_and_stops_with_the_process(self):
        with tempfile.TemporaryDirectory() as d:
            fake_proc(Path(d))
            s = mt.Sampler(42, Path(d) / "mem.csv", 0.05, proc=d)
            s.start()
            time.sleep(0.4)
            for p in (Path(d) / "42").iterdir():
                p.unlink()
            (Path(d) / "42").rmdir()
            s.join(5)
            self.assertFalse(s.is_alive())
            rows = mt.read_rows(Path(d) / "mem.csv")
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0]["game_total"], 8700)
        self.assertEqual(list(rows[0]), mt.COLUMNS)


class Bridge:
    """A fake control bridge: replies by command, writes the requests down, and moves a clock the tour reads"""

    def __init__(self, clock, loaded_after=2, refuse=0, event=0):
        self.requests, self.clock, self.presses = [], clock, 0
        self.loaded_after, self.refuse, self.event = loaded_after, refuse, event

    def request(self, cmd, **args):
        self.requests.append((cmd, args))
        if cmd in ("stick", "press"):
            self.clock.t += args.get("frames", 0) / 60
            if cmd == "press":
                self.presses += 1
        if cmd == "status":
            play = self.presses >= self.loaded_after
            return {"ok": True, "frame": 500, "state": "play" if play else "title", "stalled": False,
                    "game": {"event": False, "loading": False}}
        if cmd == "teleport" and args.get("to") is None:
            return {"ok": True, "destinations": [{"index": 0}, {"index": 5}]}
        if cmd == "teleport":
            if self.event:
                return {"ok": False, "error": "refused",
                        "message": "the game refused the teleport: an event is playing (a cutscene, a map change's)"}
            if self.refuse:
                self.refuse -= 1
                return {"ok": True, "sent": False, "refused": "busy"}
            return {"ok": True, "sent": True, "map": f"Map{args['to']}"}
        if cmd == "wait" and args.get("event") == "map":
            return {"ok": True, "map": args["map"]}
        return {"ok": True}

    def names(self):
        return [c for c, _ in self.requests]


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


class Touring(unittest.TestCase):
    def tour(self, **kw):
        clock = Clock()
        marks = []
        b = Bridge(clock, **kw)
        t = mt.Tour(ctl, b, lambda e, d="": marks.append((e, str(d))), clock, sleep=lambda s: None)
        return t, b, marks

    def test_it_presses_a_until_the_save_is_loaded_then_tours(self):
        t, b, marks = self.tour()
        t.run([13, 1], dwell=2, laps=1, settle=1)
        self.assertEqual(b.presses, 2)
        self.assertEqual([e for e, _ in marks],
                         ["in_play", "teleport", "arrived", "dwell", "teleport", "arrived", "dwell", "tour_done"])
        self.assertEqual([d for e, d in marks if e == "teleport"], ["0:13:Map13", "0:1:Map1"])
        first_tp = b.names().index("teleport")
        self.assertIn("stick", b.names()[:first_tp])              # the settle walk comes before the first teleport
        self.assertEqual(b.names().count("stick") > 2, True)

    def test_laps_repeat_the_destinations(self):
        t, b, marks = self.tour(loaded_after=0)
        t.run([3], dwell=0, laps=3, settle=0)
        self.assertEqual([d for e, d in marks if e == "teleport"], ["0:3:Map3", "1:3:Map3", "2:3:Map3"])

    def test_a_refused_teleport_is_retried(self):
        t, b, marks = self.tour(loaded_after=0, refuse=2)
        t.run([7], dwell=0, laps=1, settle=0)
        self.assertEqual(sum(e == "teleport_not_sent" for e, _ in marks), 2)
        self.assertEqual(sum(e == "teleport" for e, _ in marks), 1)

    def test_an_event_refusal_presses_a_until_the_text_box_closes(self):
        class Text(Bridge):
            def request(self, cmd, **args):
                if cmd == "press" and self.event:
                    self.event -= 1
                return super().request(cmd, **args)
        clock, marks = Clock(), []
        b = Text(clock, loaded_after=0, event=2)
        t = mt.Tour(ctl, b, lambda e, d="": marks.append((e, str(d))), clock, sleep=lambda s: None)
        t.run([7], dwell=0, laps=1, settle=0)
        self.assertEqual(sum(e == "teleport_error" for e, _ in marks), 2)
        self.assertEqual(b.presses, 2)
        self.assertEqual([d for e, d in marks if e == "teleport"], ["0:7:Map7"])

    def test_a_busy_refusal_presses_nothing(self):
        t, b, marks = self.tour(loaded_after=0, refuse=2)
        t.run([7], dwell=0, laps=1, settle=0)
        self.assertEqual(b.presses, 0)

    def test_a_teleport_that_is_always_refused_is_marked_failed_and_skipped(self):
        t, b, marks = self.tour(loaded_after=0, refuse=99)
        t.run([7, 8], dwell=5, laps=1, settle=0)
        self.assertEqual([d for e, d in marks if e == "teleport_failed"], ["7", "8"])
        self.assertNotIn("dwell", [e for e, _ in marks])

    def test_a_save_that_never_loads_stops_the_tour(self):
        t, b, marks = self.tour(loaded_after=10 ** 9)
        with self.assertRaises(ctl.Failed) as cm:
            t.to_play(timeout=30)
        self.assertEqual(cm.exception.code, 3)

    def test_an_error_reply_is_a_failure_not_a_pass(self):
        class Bad(Bridge):
            def request(self, cmd, **args):
                return {"ok": False, "error": "timeout", "message": "no frame"}
        t = mt.Tour(ctl, Bad(Clock()), lambda *a: None, Clock(), sleep=lambda s: None)
        with self.assertRaises(ctl.Failed):
            t.to_play()

    def test_all_asks_the_game_for_its_destinations(self):
        t, b, _ = self.tour()
        self.assertEqual(t.destinations("all"), [0, 5])
        self.assertEqual(t.destinations("13, 1,2"), [13, 1, 2])


class Summary(unittest.TestCase):
    ROWS = [dict(t=i * 2.0, wall=100.0 + i * 2, pid=1, rss=0, anon=a, shmem=s, file=0, vmswap=v, swap_all=v + sw,
                 shmem_swapped=sw, game_total=a + s + v + sw, memavail=av, swapused=u, sys_shmem=0)
            for i, (a, s, v, sw, av, u) in enumerate([
                (1000, 2000, 0, 0, 5000, 0), (1100, 4000, 0, 0, 3000, 0), (1200, 6000, 100, 300, 800, 400),
                (1300, 5000, 200, 900, 400, 900), (1300, 3000, 200, 900, 1500, 900)])]
    MARKS = [(100.0, "in_play", ""), (104.0, "teleport", "0:13:KokiriForest"), (108.0, "teleport", "0:1:Market"),
             (110.0, "tour_done", "")]

    def test_areas_are_cut_by_the_marks(self):
        self.assertEqual(mt.areas(self.MARKS), [("start", 100.0, 104.0), ("teleport 0 13 KokiriForest", 104.0, 108.0),
                                               ("teleport 0 1 Market", 108.0, 110.0)])

    def test_peaks_and_areas_in_the_markdown(self):
        text = mt.summarize(self.ROWS, self.MARKS, "# t")
        self.assertIn("| peak game total (resident + swapped) | 7,600 |", text)        # 1200 + 6000 + 400, the third row
        self.assertIn("| lowest MemAvailable | 400 |", text)
        self.assertIn("| system swap in use, peak | 900 |", text)
        self.assertIn("(below 500 MB available) | 5 (1)", text)
        # the second area is walls 104 to 108, the last three rows: peak 7,600, end 5,400, lowest MemAvailable 400
        line = next(l for l in text.splitlines() if l.startswith("| teleport 0 13"))
        self.assertEqual([c.strip() for c in line.split("|")[2:5]], ["7,600", "5,400", "1,500"])  # (end private 1300+200)
        self.assertEqual(line.split("|")[6].strip(), "400")

    def test_no_samples_say_so(self):
        self.assertIn("no memory samples", mt.summarize([], []))


class Usage(unittest.TestCase):
    def test_a_bad_number_is_refused_before_a_game_starts(self):
        with self.assertRaises(SystemExit):
            mt.parse(["game", "--save", "s", "--laps", "0"])

    def test_defaults(self):
        a = mt.parse(["game", "--save", "s"])
        self.assertEqual((a.dests, a.dwell, a.laps, a.settle, a.interval), (mt.DEFAULT_DESTS, 40, 1, 20, 2.0))


if __name__ == "__main__":
    unittest.main()
