"""A wait for a CPU event that is met on arrival, by a signal no capture follows, stops once for a capture.

The game writes part of a frame's data after it has submitted the frame's work, then signals the event that work waits for
(nvnEventSignal). A queue stopped at that wait gets a capture when it goes on (resume_queue: memory_capture_now). A wait
the replay found met already went on with its submit's capture; when the signal had come after that capture was begun,
the frame was drawn with the data as it was before the game wrote it: the lit scene and Link dark for a frame (issue 366).
On the submitting thread (the render thread takes its capture at the signal itself, event_signal_queued) such a wait now
stops there once, and schedule() lets it on through resume_queue. The statements this depends on, read from the source:

  - capture_make counts a capture as begun before it collects the written pages, so what a thread wrote before it read the
    count is in the next capture or an older one;
  - the CPU's signal notes that count, after its place in the pending list and before the signal is counted;
  - the wait's met branch asks, before it counts the wait as met: a serial replay that may stop, not the wait a resume
    starts at, the switch on, and the event's last CPU signal not followed by a capture; then it stops as an unmet wait does;
  - the question reads the count before it takes the events' lock (a signal made meanwhile counts as after it);
  - it is off with the render thread and when a stopped queue takes no capture as it goes on (RX_VK_RESUME_CAPTURE=0:
    stopping would only loop);
  - resume_queue marks the wait it starts at for the length of that run, so one wait stops at most once.

python -I -B tests/test_met_wait_capture.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    """From marker to the brace closing its first one"""
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def need(cond, why):
    if not cond:
        raise SystemExit("FAIL: " + why)


def main():
    replay = (ROOT / "gpu" / "vk" / "vk_replay.cpp").read_text(encoding="utf-8")
    memory = (ROOT / "gpu" / "vk" / "vk_memory.cpp").read_text(encoding="utf-8")
    header = (ROOT / "gpu" / "vk" / "vk_internal.h").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")

    need("uint64_t memory_captures_begun();" in header, "vk_internal.h no longer declares memory_captures_begun")
    make = block(memory, "std::unique_ptr<Capture> capture_make() {")
    need("captures_begun.fetch_add(" in make, "capture_make no longer counts the capture as begun")
    need(make.index("if (!capture_on()) return nullptr;") < make.index("captures_begun.fetch_add(") < make.index("capture_scan("),
         "a capture must be counted as begun before it collects the written pages (and only when captures are on)")
    need("collect_written_in(" in block(memory, "int64_t capture_scan("), "capture_scan no longer collects the written pages")

    signal = block(replay, "void event_signal_queued(")
    need("ev_cpu_captures[gpu] = memory_captures_begun();" in signal, "a CPU signal no longer notes the captures begun")
    need(signal.index("ev_cpu_pending.emplace_back") < signal.index("ev_cpu_captures[gpu]") < signal.index("ev_cpu_signals.fetch_add"),
         "the signal's count of captures belongs between its place in the pending list and the count of signals")
    need(signal.index("ev_cpu_captures[gpu]") < signal.index("return;"), "the note belongs to the submitting thread's branch")

    asked = block(replay, "bool cpu_signal_uncaptured(")
    need(asked.index("memory_captures_begun()") < asked.index("ev_cpu_mu"), "the captures' count must be read before the events' lock")
    need("it->second >= begun" in asked, "a signal is uncaptured when no capture was begun after it")

    on = block(replay, "bool met_wait_capture_on() {")
    need("RX_VK_MET_WAIT_CAPTURE" in on and "resume_capture_on()" in on and "!async_on()" in on,
         "the switch, the resume capture and the submitting thread decide whether a met wait stops")

    wait = replay[replay.index("case NOP_WAIT_EVENT:"):replay.index("case NOP_REPORT_COUNTER:")]
    met = wait[wait.index("if (event_wait_met(have, w.mode, w.value)) {"):wait.index("} else if (suspend_ok) {")]
    cond = "if (suspend_ok && p != met_resumed_at && met_wait_capture_on() && cpu_signal_uncaptured(w.gpu)) {"
    need(cond in met, "the met branch no longer asks whether the signal is followed by a capture")
    stop = block(met, cond)
    need("suspend_at = p;" in stop and "return;" in stop, "a met wait with an uncaptured signal must stop as an unmet one does")
    need(met.index(cond) < met.index("st_waits_met++;"), "the wait is counted as met only when it goes on")

    resume = block(replay, "void resume_queue(uint64_t queue, bool forced) {")
    need("met_resumed_at = forced ? nullptr : from;" in resume, "resume_queue no longer marks the wait it starts at")
    need(resume.index("met_resumed_at = forced ? nullptr : from;") < resume.index("const bool went = run_submit(") <
         resume.index("met_resumed_at = nullptr;"), "the mark holds for the resumed run only")
    need("resume_capture_on()" in resume, "resume_queue and the met wait must read the same RX_VK_RESUME_CAPTURE")

    need("`RX_VK_MET_WAIT_CAPTURE=0`" in docs, "docs/development.md has no row for RX_VK_MET_WAIT_CAPTURE")
    print("PASS: a met wait for a CPU event with an uncaptured signal stops once for resume_queue's capture")


if __name__ == "__main__":
    main()
