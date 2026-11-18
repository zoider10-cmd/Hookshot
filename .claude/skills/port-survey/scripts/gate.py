"""gate.py <name> <variant A> <variant B> [--win 50]: the A/B's verdict from bench.sh's runs.

Per run, over the last --win seconds: mean fps, the 1% low (fps of the 99th-percentile frame time) and the worst
frame. FAIL when the median mean-fps or 1% low drops more than 2% and B loses
nearly every pair of runs (Mann-Whitney, U <= 16% of pairs), or drops more than 5% at all; PASS when one rises more
than 2% and B wins nearly every pair. A same-build A/A on this PC spread 67-73 fps: use 5 reps a side. Prints a table and PASS, FAIL or NOISE (no clear change either way, which also passes the gate:
'no worse'). A run with fewer than 500 frames (crashed, did not load) makes it FAIL."""
import sys, os, glob, statistics as st

P = "F:/Games/perf-ab/runs"


def one(path, win):
    rows = [l.split(",") for l in open(path) if l[:1].isdigit()]
    t = [(float(r[1]), float(r[2])) for r in rows]
    if not t:
        return None
    w = sorted(ms for s, ms in t if s >= t[-1][0] - win)
    if len(w) < 500:
        return None
    return {"fps": 1000 / st.mean(w), "low1": 1000 / w[int(len(w) * .99)], "worst": w[-1], "n": len(w)}


def main(a):
    win = 50.0
    if "--win" in a:
        i = a.index("--win"); win = float(a[i + 1]); del a[i:i + 2]
    name, A, B = a
    res = {}
    for v in (A, B):
        res[v] = []
        for f in sorted(glob.glob(os.path.join(P, "%s_%s_*" % (name, v), "frames.csv"))):
            r = one(f, win)
            print("%-40s %s" % (os.path.basename(os.path.dirname(f)),
                                "no good run" if r is None else "%.1f fps, 1%% low %.1f, worst %.1f ms (%d frames)" % (r["fps"], r["low1"], r["worst"], r["n"])))
            res[v].append(r)
    def upscaler(v):   # (what the runs' logs say the build has: two sides built differently are not comparable)
        out = set()
        for f in glob.glob(os.path.join(P, "%s_%s_*" % (name, v), "stdout.txt")):
            t = open(f, encoding="utf-8", errors="replace").read()
            out.add("no FSR 4" if "this build has no FSR 4" in t else "FSR 4" if "AMD FSR 4" in t else "?")
        return out
    ua, ub = upscaler(A), upscaler(B)
    if ua != ub:
        print("FAIL: not comparable: %s ran %s, %s ran %s (build both the same way: HOOKSHOT_FSR=1)" % (A, sorted(ua), B, sorted(ub))); return 1
    if not res[A] or not res[B] or None in res[A] + res[B]:
        print("FAIL: a run is missing or did not play"); return 1
    verdict = "NOISE"
    for k in ("fps", "low1"):
        a = [r[k] for r in res[A]]; b = [r[k] for r in res[B]]
        ma, mb = st.median(a), st.median(b)
        ch = (mb - ma) / ma
        # (Mann-Whitney U: of every pair of runs, how many B wins; ties count half. 5 runs a side: U <= 4 or >= 21
        # is a one-sided p of about 0.075, which one outlier run cannot reach alone)
        u = sum((y > x) + 0.5 * (y == x) for x in a for y in b); n = len(a) * len(b)
        lo, hi = 0.16 * n, 0.84 * n
        print("%-5s A %.1f  B %.1f  change %+.1f%%  B wins %.1f of %d pairs" % (k, ma, mb, ch * 100, u, n))
        if (ch < -0.02 and u <= lo) or ch < -0.05:
            verdict = "FAIL"
        elif ch > 0.02 and u >= hi and verdict != "FAIL":
            verdict = "PASS"
    print(verdict)
    return 0 if verdict != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
