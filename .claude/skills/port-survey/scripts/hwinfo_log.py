"""hwinfo_log.py <out.csv> [--seconds N] [--every MS] [--match WORD,...]: logs HWiNFO64's sensors to a CSV.

Reads HWiNFO's shared memory (Global\\HWiNFO_SENS_SM2), which HWiNFO offers while it runs with Settings > Shared
Memory Support ticked (the free version: 12 hours a run). Nothing is sent anywhere. Each line: the time, then one
column per reading whose sensor or label contains one of --match (default: GPU, CPU, temperature and clock words).
Stops after --seconds (default 3600) or when <out.csv>.stop exists. Windows only.

    py -I hwinfo_log.py F:/Games/perf-ab/runs/x/hwinfo.csv --seconds 300 --every 500
    py -I hwinfo_log.py --list            (what HWiNFO offers now)
"""
import ctypes
import os
import struct
import sys
import time

NAME = "Global\\HWiNFO_SENS_SM2"
MATCH = ("GPU Temperature", "GPU Hot Spot", "GPU Memory Junction", "GPU Clock", "GPU Memory Clock", "GPU Power",
         "GPU Core Load", "GPU Utilization", "GPU D3D Usage", "Total Board Power", "GPU ASIC Power",
         "Core Clocks (avg)", "Core Effective Clock", "CPU (Tctl/Tdie)", "CPU Package Power", "Total CPU Usage",
         "Physical Memory Used", "GPU Memory Allocated", "GPU D3D Memory Dedicated")


def snapshot():
    """[(sensor name, label, unit, value)] read now, or None when HWiNFO's shared memory is not there"""
    k32 = ctypes.windll.kernel32
    k32.OpenFileMappingW.restype = ctypes.c_void_p
    k32.MapViewOfFile.restype = ctypes.c_void_p
    h = k32.OpenFileMappingW(0x0004, False, NAME)   # (FILE_MAP_READ)
    if not h:
        return None
    try:
        view = k32.MapViewOfFile(ctypes.c_void_p(h), 0x0004, 0, 0, 0)
        if not view:
            return None
        try:
            head = ctypes.string_at(view, 44)
            sig, _, _, _, s_off, s_size, s_n, r_off, r_size, r_n = struct.unpack("<IIIqIIIIII", head)
            if sig not in (0x53695748, 0x44414544):   # ("HWiS"; "DEAD" when HWiNFO stopped sharing)
                return None
            names = []
            for i in range(s_n):
                raw = ctypes.string_at(view + s_off + i * s_size, s_size)
                names.append(raw[8 + 128:8 + 256].split(b"\0")[0].decode("latin-1") or raw[8:136].split(b"\0")[0].decode("latin-1"))
            out = []
            for i in range(r_n):
                raw = ctypes.string_at(view + r_off + i * r_size, r_size)
                _, sensor, _ = struct.unpack_from("<III", raw, 0)
                label = raw[12 + 128:12 + 256].split(b"\0")[0].decode("latin-1") or raw[12:140].split(b"\0")[0].decode("latin-1")
                unit = raw[268:284].split(b"\0")[0].decode("latin-1")
                value = struct.unpack_from("<d", raw, 284)[0]
                out.append((names[sensor] if sensor < len(names) else "?", label, unit, value))
            return out
        finally:
            k32.UnmapViewOfFile(ctypes.c_void_p(view))
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))


def main(a):
    if a[:1] == ["--list"]:
        snap = snapshot()
        if snap is None:
            print("HWiNFO's shared memory is not there: start HWiNFO64 with Settings > Shared Memory Support ticked")
            return 1
        for s, l, u, v in snap:
            print("%-40s %-40s %10.2f %s" % (s[:40], l[:40], v, u))
        return 0
    out, seconds, every, match = a[0], 3600.0, 500, MATCH
    if "--seconds" in a:
        seconds = float(a[a.index("--seconds") + 1])
    if "--every" in a:
        every = int(a[a.index("--every") + 1])
    if "--match" in a:
        match = tuple(a[a.index("--match") + 1].split(","))
    snap = snapshot()
    if snap is None:
        print("HWiNFO's shared memory is not there: start HWiNFO64 with Settings > Shared Memory Support ticked")
        return 1
    keep = [i for i, (s, l, u, v) in enumerate(snap) if any(m.lower() in (s + " " + l).lower() for m in match)]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    start = time.time()
    with open(out, "w", encoding="utf-8") as f:
        f.write("time_s," + ",".join('"%s: %s [%s]"' % (snap[i][0], snap[i][1], snap[i][2]) for i in keep) + "\n")
        while time.time() - start < seconds and not os.path.exists(out + ".stop"):
            now = snapshot()
            if now is None or len(now) != len(snap):
                break
            f.write("%.2f," % (time.time() - start) + ",".join("%.2f" % now[i][3] for i in keep) + "\n")
            f.flush()
            time.sleep(every / 1000)
    print("logged %d readings to %s" % (len(keep), out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
