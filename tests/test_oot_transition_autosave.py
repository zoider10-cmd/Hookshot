"""Run the OoT save-request hook against synthetic requests, without game data."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
#include <assert.h>
#include <stdint.h>

typedef struct { uint64_t x[32]; } Ctx;
static uint64_t parent;
static int autosave;

static uint64_t recomp_load64(Ctx *c, uint64_t address) {
    assert(address == c->x[31] + 24);
    return parent;
}

static int env_on(const char *name) { (void)name; return 0; }
#define hos_log(...) ((void)0)

int rx_option(int option, int fallback) {
    assert(option == HOS_OPT_TRANSITION_AUTOSAVE && fallback == 1);
    return autosave;
}

// HOOK

static void check(uint64_t caller, uint64_t site, unsigned reason, unsigned mode, int blocked) {
    Ctx c = {0};
    c.x[0] = 123;
    c.x[1] = reason;
    c.x[2] = mode;
    c.x[30] = caller;
    parent = site;
    assert(hos_oot_trace_save(&c) == blocked);
    assert(c.x[0] == (blocked ? 0 : 123));
}

int main(void) {
    const uint64_t wrapper = 0x80bc7764ULL;
    for (autosave = 0; autosave <= 1; ++autosave) {
        check(wrapper, 0x80bc7710ULL, 6, 0, !autosave);
        check(wrapper, 0x80bc7864ULL, 2, 0, !autosave);
        check(wrapper, 0x832a9764ULL, 1, 0, !autosave);
        check(wrapper, 0x80bc7864ULL, 1, 0, 0);
        check(wrapper, 0x80bc7864ULL, 6, 0, 0);
        check(wrapper, 0x80bc7710ULL, 2, 0, 0);
        check(wrapper, 0x80bc7864ULL, 2, 1, 0);
        check(0x83296490ULL, 0x80bc7864ULL, 2, 0, 0);
    }
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    host = (ROOT / "host/hos_main.c").read_text(encoding="utf-8")
    api = (ROOT / "gpu/vk/vk_api.h").read_text(encoding="utf-8")
    hook = re.search(r"^int hos_oot_trace_save\(Ctx \*c\) \{.*?^\}", host, re.M | re.S).group()
    option = re.search(r"enum \{ HOS_OPT_TRANSITION_AUTOSAVE = \d+ \};", api).group()
    with tempfile.TemporaryDirectory(prefix="oot-save-") as tmp:
        source = Path(tmp) / "test.c"
        binary = Path(tmp) / "test.exe"
        source.write_text(option + "\n" + FIXTURE.replace("// HOOK", hook), encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
    print("PASS: all known transition requests respect the toggle and unrelated requests pass through")


if __name__ == "__main__":
    main()
