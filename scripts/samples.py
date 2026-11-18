"""The all-thread sampler's file (HOS_SAMPLE_ALL, host/posix/prof.c and host/mkw_glue.c sample_all_thread), read the same
way in either of its formats:

    plain   "<ms> <thread>|<frame>;<frame>;..." a sample, innermost frame first, each module+offset
    packed  (HOS_SAMPLE_PACKED, the profiling mode's: host/profiling.c) each distinct stack once, "s <id> <frames>", before
            the first sample of it, "<ms> <thread>|=<id>"

lines(path) gives every line as the plain format has it ("# t0_ns", "# at" and other notes as they are), so a reader of the
plain format reads both by opening the file with it.
"""


def lines(path):
    stacks = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("s "):
                _, sid, stack = line.rstrip("\n").split(" ", 2)
                stacks[sid] = stack
                continue
            head, bar, stack = line.partition("|")
            if bar and stack.startswith("="):
                yield "%s|%s\n" % (head, stacks.get(stack[1:].rstrip("\n"), ""))
            else:
                yield line


def timed(path):
    """(ns, thread, stack) a sample, its time on the host's clock (hos_now_ns): each "# t0_ns" line starts the ms after it
    again (the sampler writes one each time it opens the file: a pause and a resume of HOS_SAMPLE_ALL's <file>.go). Samples
    before the first "# t0_ns" are left out"""
    t0 = None
    for line in lines(path):
        if line.startswith("# t0_ns "):
            try:
                t0 = int(line.split()[2])
            except (IndexError, ValueError):
                pass
            continue
        head, bar, stack = line.rstrip("\n").partition("|")
        ms, _, thread = head.partition(" ")
        if bar and t0 is not None and ms.isdigit():
            yield t0 + int(ms) * 1000000, thread, stack
