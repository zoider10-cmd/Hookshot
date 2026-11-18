"""scripts/crash_groups.py on crash records, reports and log ends as the game writes them, no forge.

A group's name must not change from one build to the next (an offset does, so it only sub-lists a group), a device
lost must count as that however the process then ended, an uncaught C++ exception at Windows' commit limit is memory
(#1056), and the modules it calls the graphics driver must be the ones the crash window does
(hos_crash_driver_module, host/hos_crash_dialog.h).

    python -I -B tests/test_crash_groups.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import crash_groups  # noqa: E402


def record(kind="crash", version="v3.0.0-rc.5 (source 013b1d3a)", run="7c3b378c5b9fc201fe61bceecc09b9be", reason="unhandled exception",
           module="hookshot.exe+0x96a3a6a", exception="0xc0000005", signal="0", host=(), guest=()):
    lines = ["Hookshot %s record 1" % kind, "version: " + version, "run_id: " + run, "when: 20261116T134514Z", "uptime_s: 41",
             "reason: " + reason, "thread: host", "module_offset: " + module, "pid: 11496"]
    if kind == "crash":
        lines += ["signal: " + signal, "signal_code: 0", "exception: " + exception, "fault_address_class: null",
                  "host_backtrace_method: Windows unwind"]
        lines += ["host_backtrace: " + f for f in host] + ["guest_register: x0=0x1"] + ["guest_backtrace: " + g for g in guest]
    return "\n".join(lines + ["dump: off", "record_complete: yes"]) + "\n"


FORM = "### Hookshot version\n\n%s\n\n### Graphics card and driver version\n\n%s\n\n### hookshot_log.txt\n\n"
LOST = "[hos host] vk: FATAL: the GPU device was lost (VK_ERROR_DEVICE_LOST): the driver stopped or reset the GPU\n"
HUNG = "[hos host] vk: FATAL: the GPU hung: no submission finished in 30 s, and the driver never reported the device lost\n"
VRAM_FULL = "[hos host] vk: VRAM: 4000 MB used of 5249 MB allowed\n[hos host] vk: VRAM: 5294 MB used of 5249 MB allowed (1182 MB free)\n"
VRAM_ROOM = "[hos host] vk: VRAM: 5294 MB used of 5249 MB allowed\n[hos host] vk: VRAM: 3000 MB used of 5249 MB allowed\n"
COMMIT = "[hos host] mem: commit of 0x10000 bytes at the commit limit made after 50 ms (7 so far)\n"
THROWN = ("KERNELBASE.dll+0xc782a", "hookshot_vk.dll+0x54088d", "ucrtbase.dll+0x37b0")

NAMES = [
    # (what is checked, the title, the text, the group names wanted, in the order of the text's records)
    ("an access violation in lifted code", "Game: Hookshot closed unexpectedly while you were playing",
     record(host=("hookshot.exe+0x96a3a6a",), guest=("0x8028ca9c", "0x80291504")), ["access violation in the game code"]),
    ("the same crash in another build keeps its name", "",
     record(version="nightly-357-55e8fbd5 (source 370494fb)", module="hookshot.exe+0x5925c29", guest=("0x8028ca9c",)),
     ["access violation in the game code"]),
    ("a crash in the driver names the driver", "", record(module="nvoglv64.dll+0xea725b") + VRAM_FULL,
     ["access violation in the graphics driver (nvoglv64.dll), VRAM full"]),
    ("the last VRAM line decides", "", record(module="igvk64.dll+0x127e0b") + VRAM_ROOM,
     ["access violation in the graphics driver (igvk64.dll)"]),
    ("a device lost record", "", record(reason="device lost", exception="0x0", module="hookshot.exe+0x1b7c8048"), ["GPU device lost"]),
    ("an unclean end after a device lost is a device lost", "", record(kind="unclean", reason="ended without a clean exit",
                                                                    module="unknown") + LOST, ["GPU device lost"]),
    ("an unclean end after a hang", "", record(kind="unclean", module="unknown") + LOST + HUNG, ["GPU hung (no submission finished)"]),
    ("an unclean end with nothing known", "", record(kind="unclean", module="unknown"), ["ended with no crash record"]),
    ("an unclean end at the commit limit, VRAM full", "", record(kind="unclean", module="unknown") + COMMIT + VRAM_FULL,
     ["ended with no crash record, commit limit, VRAM full"]),
    ("a thrown exception is named by our frame under it", "", record(exception="0x20474343", module=THROWN[0], host=THROWN),
     ["uncaught C++ exception in the renderer"]),
    ("a thrown exception at the commit limit is memory", "", record(exception="0x20474343", module=THROWN[0], host=THROWN) + COMMIT,
     ["out of memory (uncaught C++ exception at the commit limit) in the renderer"]),
    ("a Linux signal", "", record(exception="0x0", signal="11", module="libhookshot_vk.so+0x2aa2f1"),
     ["access violation (SIGSEGV) in the renderer"]),
    ("hos_fatal", "", record(reason="hos_fatal", exception="0x0", module="hookshot+0x1a0e9790"), ["fatal error (hos_fatal) in the game code"]),
    ("an exception code with no name", "", record(exception="0xc0000374", module="ntdll.dll+0x1"),
     ["exception 0xc0000374 in the system library (ntdll.dll)"]),
    ("two records, two groups", "", record() + "\n" + record(run="c40f5054316a46567012ae772f1430ac", reason="device lost", exception="0x0"),
     ["access violation in the game code", "GPU device lost"]),
    ("a record pasted and attached counts once", "", record() + "\n```\n" + record(), ["access violation in the game code"]),
    ("no record: the log's CRASH line", "",
     "[hos sead::MainThread] CRASH: exception 0xc0000005 (read 0x100000001030, guest 0x1030) at hookshot.exe+0x5925c29\n",
     ["access violation in the game code"]),
    ("no record: the log's device lost", "", LOST + VRAM_FULL, ["GPU device lost, VRAM full"]),
    ("no record: the crash window's verdict", "", "What went wrong: The graphics driver failed. Update your graphics driver.\n",
     ["GPU device lost"]),
    ("no record: ended from outside", "", "What went wrong: Hookshot ended without a crash report: it was closed from outside\n",
     ["ended with no crash record"]),
    ("no record: memory", "", "What went wrong: Your PC ran out of memory. Close other programs and try again\n",
     ["out of memory (the crash window's verdict)"]),
    ("nothing at all", "", "it crashed\n", ["nothing in the report says how it ended"]),
]
STAGES = [("Game: Hookshot closed unexpectedly while you were playing", "play"), ("Game: Hookshot closed unexpectedly during the start", "start"),
          ("Game: Hookshot closed unexpectedly while it prepared the shaders", "shaders"), ("Game: Hookshot closed unexpectedly", "")]


def main():
    bad = []

    def check(what, got, want):
        print("%s %-58s -> %s" % ("ok  " if got == want else "FAIL", what, got))
        if got != want:
            bad.append("%s: wanted %r" % (what, want))

    for what, title, text, want in NAMES:
        check(what, [crash_groups.group_name(e) for e in crash_groups.events(title, text)], want)
    for title, want in STAGES:
        check("stage of %r" % title[-28:], crash_groups.stage_of(title), want)

    # (three reports: two share a group across builds and the game's caller, one is alone; the largest group first)
    reports = [
        {"id": 3, "title": STAGES[0][0], "text": FORM % ("v3.0.0-rc.5", "NVIDIA GeForce RTX 3080") + NAMES[0][2]},
        {"id": 2, "title": STAGES[1][0], "text": FORM % ("nightly-357", "Intel(R) Arc(TM) A770 Graphics") + NAMES[1][2]},
        {"id": 1, "title": STAGES[0][0], "text": FORM % ("v3.0.0-rc.5", "AMD Radeon RX 6800 XT") + NAMES[4][2]},
    ]
    groups = crash_groups.group(reports)
    check("the groups, the largest first", [(g["name"], g["reports"]) for g in groups],
          [("access violation in the game code", [3, 2]), ("GPU device lost", [1])])
    check("a group's cards and stages", (dict(groups[0]["vendors"]), dict(groups[0]["stages"])),
          ({"NVIDIA": 1, "Intel": 1}, {"play": 1, "start": 1}))
    check("lifted code is listed by the game's caller, across builds", dict(groups[0]["frames"]), {("", "the game's 0x8028ca9c"): [3, 2]})
    check("a device lost lists no address", list(groups[1]["frames"]), [("v3.0.0-rc.5 (source 013b1d3a)", "unknown")])
    text = crash_groups.show(groups, len(reports), {1: "u1", 2: "u2", 3: "u3"}.get, True)
    check("the markdown list links each report", "[#3](u3), [#2](u2)" in text and "called from `the game's 0x8028ca9c`" in text, True)

    # (the same modules as the crash window calls the graphics driver)
    source = (ROOT / "host" / "hos_crash_dialog.h").read_text(encoding="utf-8")
    m = re.search(r"hos_crash_driver_module\(const char \*module\) \{\s*static const char \*const drivers\[\] = \{(.*?)\};", source, re.S)
    if not m:
        raise SystemExit("host/hos_crash_dialog.h: hos_crash_driver_module's drivers[] not found")
    check("the driver modules are hos_crash_driver_module's", list(crash_groups.DRIVER_MODULES), re.findall(r'"([^"]+)"', m.group(1)))

    if bad:
        raise SystemExit("crash_groups.py: %d wrong: %s" % (len(bad), "; ".join(bad)))


if __name__ == "__main__":
    main()
