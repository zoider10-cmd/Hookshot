"""scripts/coverage/cover.py report and compare count what a run folder says, on any OS.

Writes a made-up run folder (fns.txt, cover.bin in cover_dll.c's format, marks.txt, run.json) and a csize file, then checks
the report's counts (functions that ran, host bytes, lifted C, the compile cost from nx2/chunks.py's model scaled to
--compiler-s), how many had run by each mark, covered.txt's order, a hot list's cover, and compare's misses between two
runs. Also that cover_dll.c writes the header read_cover reads.

python -I -B tests/test_coverage_report.py
"""
import os
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COVER = os.path.join(ROOT, "scripts", "coverage", "cover.py")
DLL_C = os.path.join(ROOT, "scripts", "coverage", "cover_dll.c")

# (name, host bytes, lifted C bytes, first-run ms; 0 = never ran)
FNS = [("f_80000000", 100, 1000, 500), ("f_80000100", 200, 350000, 0), ("f_80000200", 300, 3000, 1500),
       ("f_80000300", 400, 4000, 30000), ("f_80000400", 500, 5000, 0)]
START_MS = 1_700_000_000_000


def write_run(folder, firsts, marks=()):
    os.makedirs(folder)
    with open(os.path.join(folder, "fns.txt"), "w", encoding="ascii") as f:
        for i, (name, host, _, _) in enumerate(FNS):
            f.write("%x %d %s\n" % (0x1000 + i * 0x100, host, name))
    with open(os.path.join(folder, "cover.bin"), "wb") as f:
        f.write(b"LSCOV1\0\0" + struct.pack("<QII", START_MS, len(firsts), sum(1 for t in firsts if t)))
        f.write(struct.pack("<%dI" % len(firsts), *firsts))
    with open(os.path.join(folder, "run.json"), "w") as f:
        f.write('{"started": %.3f}' % (START_MS / 1000))
    with open(os.path.join(folder, "marks.txt"), "w", encoding="utf-8") as f:
        f.writelines("%.1f %s\n" % m for m in marks)


def cover(*args):
    r = subprocess.run([sys.executable, "-I", "-B", COVER] + list(args), capture_output=True, text=True)
    if r.returncode:
        raise AssertionError("cover.py %s failed:\n%s%s" % (" ".join(args), r.stdout, r.stderr))
    return r.stdout


def expect(text, line):
    if line not in text:
        raise AssertionError("expected %r in:\n%s" % (line, text))


def main():
    with open(DLL_C, encoding="utf-8") as f:
        dll = f.read()
    # (the DLL writes magic, u64 start, u32 count, u32 seen, then the times: what read_cover and write_run take)
    expect(dll, 'WriteFile(h, "LSCOV1\\0\\0", 8, &w, NULL) && WriteFile(h, &start_unix_ms, 8, &w, NULL)')
    expect(dll, "uint32_t head[2] = {n, (uint32_t)seen};")

    with tempfile.TemporaryDirectory() as tmp:
        run_a = os.path.join(tmp, "a")
        write_run(run_a, [t for *_, t in FNS], marks=[(1.0, "title screen"), (20.0, "in play (file loaded)")])
        csize = os.path.join(tmp, "csize.txt")
        with open(csize, "w") as f:
            f.writelines("%s %d\n" % (n, c) for n, _, c, _ in FNS)
        hot = os.path.join(tmp, "hot.txt")
        with open(hot, "w") as f:
            f.write("f_80000000\nf_80000100\nf_99999999\n")

        out = cover("report", run_a, "--csize", csize, "--hot", hot, "--compiler-s", "1000")
        expect(out, "Functions that ran: 3 of 5 = 60.0%; their host code 0.0 of 0.0 MB = 53.3%")
        # (C: 8,000 of 363,000 bytes; the model: s + s*s//350000 per function; f_80000100 alone is 350,000 + 350,000)
        model = lambda s: s + s * s // 350000
        k_all = sum(model(c) for _, _, c, _ in FNS)
        k_ran = model(1000) + model(3000) + model(4000)
        expect(out, "Their lifted C: 0.0 of 0.3 MB = 2.2%")
        expect(out, "Their compile cost (the build's model): %.1f%% = ~%.0f of the 1000 -O1 compiler-s"
               % (100.0 * k_ran / k_all, 1000.0 * k_ran / k_all))
        expect(out, "by 'title screen' (1 s): 1 functions")
        expect(out, "by 'in play (file loaded)' (20 s): 2 functions")
        expect(out, "New functions per minute: 0:3")
        expect(out, "hot.txt: 2 functions, 1 ran in this session (50.0% of the list); the list holds 33.3% of what ran")
        with open(os.path.join(run_a, "covered.txt"), encoding="ascii") as f:
            got = [line.split() for line in f]
        assert got == [["f_80000000", "500"], ["f_80000200", "1500"], ["f_80000300", "30000"]], got
        with open(os.path.join(run_a, "report.txt"), encoding="utf-8") as f:
            assert f.read().strip() == out.strip()

        # (B played f_80000100 and f_80000400 too, at 2 s and 70 s: A's list misses those two)
        run_b = os.path.join(tmp, "b")
        write_run(run_b, [400, 2000, 1600, 0, 70000])
        out = cover("compare", run_a, run_b, "--csize", csize, "--compiler-s", "1000")
        expect(out, "listed run: 3 functions; played run: 4; played but not listed: 2 (50.0% of the played run's functions)")
        expect(out, "misses per minute: 0:1 1:1")
    print("test_coverage_report: OK")


if __name__ == "__main__":
    main()
