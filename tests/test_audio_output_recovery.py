"""Same native recovery checks against either host source, without selector-only API requirements.

python -I -B tests/test_audio_output_recovery.py [--cc gcc] [--source host/nn_audio.c] [--case upmix]
The unchanged output section is compiled with authored device spies shared with audio_output_errors_test.c.
Historical main aa95d35f fails upmix/downmix/retry; current main includes PR 448 and should pass these guards too.
No game, device, microphone or dump is opened. PR 448: https://git.magicbean.dev/MagicBeanDev/Hookshot/pulls/448
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]
CASES = ("upmix", "downmix", "retry", "same-layout-retry", "default", "normal")
REGRESSIONS = {"upmix", "downmix", "retry"}

MAIN = r'''
int main(int argc, char **argv) {
    CHECK(argc == 2);
    scenario = argv[1];
#ifdef HAVE_ROUTE_UPDATE
    /* A reference only: prevent unused-function warnings in the topic without calling selector-only behavior. */
    (void)output_route_update;
#endif
    CHECK(!strcmp(scenario, "upmix") || !strcmp(scenario, "downmix") || !strcmp(scenario, "retry") ||
          !strcmp(scenario, "same-layout-retry") || !strcmp(scenario, "default") || !strcmp(scenario, "normal"));
    const int layout_change = !strcmp(scenario, "upmix") || !strcmp(scenario, "downmix") || !strcmp(scenario, "retry");
    speakers = layout_change ? 6 : 2;
    fail_open6 = !strcmp(scenario, "upmix");
    opens_fail = !strcmp(scenario, "retry") || !strcmp(scenario, "same-layout-retry");
    output_open();
    const int mixed = out_channels;
    if (!strcmp(scenario, "upmix")) {
        CHECK(wout && mixed == 2);
        fail_open6 = 0;
        default_key++;
        now_ms = 1001;
    } else if (!strcmp(scenario, "downmix")) {
        CHECK(wout && mixed == 6);
        fail_open6 = 1;
        default_key++;
        now_ms = 1001;
    } else if (opens_fail) {
        CHECK(!wout && mixed == 2);
        opens_fail = 0;
        now_ms = 1001;
    } else if (!strcmp(scenario, "default")) {
        CHECK(wout && mixed == 2);
        default_key++;
        now_ms = 1001;
    } else CHECK(wout && mixed == 2);
    /* Six-channel allocation keeps an unguarded upmix copy in bounds; sentinel data exposes it. */
    mixed_frame(mixed);
    printf("OBSERVE %s: mixed=%d reopened=%d fill_frames=%d sentinel=%d\n",
           scenario, mixed, out_channels, fill_frames, blocks_hold(7777));
    printf("DEVICE %s: opens=%d closes=%d resets=%d logs=%d device=%u channels=%u route=%d\n",
           scenario, open_calls, close_calls, reset_calls, logs, last_device, last_channels, route_state);
    fflush(stdout);
    CHECK(wout && out_channels == (!strcmp(scenario, "upmix") || !strcmp(scenario, "retry") ? 6 : 2));
    if (layout_change) {
        CHECK(mixed != out_channels);
        CHECK(fill_frames == 0); /* Without PR 448's guard, old-layout PCM reaches the reopened ring. */
        CHECK(!blocks_hold(7777));
        frames(2, 1);
    } else {
        CHECK(mixed == out_channels);
        CHECK(fill_frames == 1); /* A same-layout recovery must keep this frame. */
        CHECK(blocks[0][0] == 100 && blocks[0][FRAME * out_channels - 1] == (int16_t)(100 + FRAME * out_channels - 1));
        frames(1, 1);
    }
    CHECK(accepted == 1 && fill_frames == 0 && !blocks_hold(7777));
    CHECK(hdr[0].dwBufferLength == FRAME * 2 * out_channels * sizeof blocks[0][0]);
    printf("PASS %s: recovery layout guard and subsequent native ring submission\n", scenario);
    return 0;
}
'''


def build(source_path, cc, folder):
    source = source_path.read_text(encoding="utf-8")
    definitions = []
    for name in ("FRAME", "RATE"):
        found = re.findall(r"^#define " + name + r"\s+\d+[^\n]*", source, re.M)
        assert len(found) == 1, name
        definitions.extend(found)
    section = source[source.index("#define NBLOCKS"):source.index("/* ---- parameter updates")]
    actual = "\n".join(definitions) + "\n" + section
    (folder/"audio_output.inc").write_text(actual, encoding="utf-8")
    spies = (ROOT/"tests/audio_output_errors_test.c").read_text(encoding="utf-8").split("int main(int argc, char **argv) {", 1)[0]
    spies = spies.replace('#include "../host/audio_output_devices.h"', '#include "audio_output_devices.h"')
    driver = spies + MAIN
    fixture = folder/"recovery.c"
    fixture.write_text(driver, encoding="utf-8")
    executable = folder/("recovery.exe" if os.name == "nt" else "recovery")
    command = [cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(folder), "-I", str(ROOT/"host"),
               "-include", str(ROOT/"gpu/vk/compat/hookshot_env.h")]
    if "static void output_route_update(void)" in section:
        command.append("-DHAVE_ROUTE_UPDATE")
    command += [str(fixture), "-o", str(executable)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if result.returncode:
        raise RuntimeError("Fixture did not compile; this is not a regression result:\n" + result.stdout + result.stderr)
    metadata = dict(command=command, compile_exitcode=result.returncode, compiler_output=result.stdout+result.stderr,
                    source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
                    output_section_sha256=hashlib.sha256(actual.encode()).hexdigest(),
                    driver_sha256=hashlib.sha256(driver.encode()).hexdigest())
    return executable, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--source", type=Path, default=ROOT/"host/nn_audio.c")
    parser.add_argument("--case", choices=CASES)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="audio-recovery-control-") as temporary:
        exe, _ = build(args.source, args.cc, Path(temporary))
        print("COMPILE PASS: native recovery driver", flush=True)
        failed = False
        for case in ((args.case,) if args.case else CASES):
            result = subprocess.run([str(exe), case], capture_output=True, text=True, timeout=30)
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            failed |= result.returncode != 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
