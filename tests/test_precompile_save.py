"""A start whose noted pipelines were compiled, not found, writes the pipeline cache before the title (gpu/vk/precompile_save.h).

In play the pipeline cache is written only once it has grown 64 MB. A Steam Deck start from Steam compiled its 32,438 noted
pipelines for 20 minutes under keys the cache did not have, and grew it by 4.3 MB (RADV keeps a pipeline as its key and its
shaders' hashes; the code was already there): nothing was written, and the next start had only the driver's own folder. This
checks precompile_save.h (tests/precompile_save_test.cpp) and the wiring in vk_draw.cpp: precompile_run writes the cache when
it is due, with the start-up screen's saving state on, as precompile_warm (RX_VK_LOAD=create) does, and both log what the save
did, which pipeline_cache_save records for each way it ends; and docs/development.md's row.
python -I -B tests/test_precompile_save.py [--cxx c++]
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
from srccut import block   # noqa: E402

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def in_order(text, parts):
    at = 0
    for p in parts:
        at = text.find(p, at)
        if at < 0:
            return False
        at += len(p)
    return True


def check_sources():
    draw = (ROOT / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
    problems = []
    if '#include "precompile_save.h"' not in draw:
        return ["vk_draw.cpp does not include precompile_save.h"]
    said = "precompile_save::said(pcache_save_outcome)"
    saving = ["prepare_saving_now.store(true", "pipeline_cache_save(true)", "prepare_saving_now.store(false", said]
    run = block(draw, "void precompile_run(void (*progress)(size_t done, size_t total)) {")
    if "precompile_save::due(" not in run or 'getenv("RX_VK_PRECOMPILE_SAVE_S")' not in run:
        problems.append("precompile_run does not decide the save with precompile_save::due and RX_VK_PRECOMPILE_SAVE_S")
    if not in_order(run, ["precompile_save::due("] + saving):
        problems.append("precompile_run's save is not inside the start-up screen's saving state, or its log does not say what "
                        "the save did")
    warm = block(draw, "void precompile_warm(void (*progress)(size_t done, size_t total)) {")
    if not in_order(warm, saving):
        problems.append("precompile_warm (RX_VK_LOAD=create) does not log what its save did")
    save = block(draw, "void pipeline_cache_save(bool force) {")
    for kind in ("kNoCache", "kOff", "kFetchFailed", "kSame", "kWritten", "kWriteFailed", "kError"):
        if "Outcome::" + kind not in save:
            problems.append("pipeline_cache_save never records " + kind)
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    if "`RX_VK_PRECOMPILE_SAVE_S" not in docs:
        problems.append("docs/development.md does not name RX_VK_PRECOMPILE_SAVE_S")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default=os.environ.get("CXX", "c++"))
    args = parser.parse_args()
    cxx = shutil.which(args.cxx)
    if not cxx:
        raise SystemExit("C++ compiler not found: " + args.cxx)
    problems = check_sources()
    if not (ROOT / "gpu" / "vk" / "precompile_save.h").exists():
        problems.append("gpu/vk/precompile_save.h is missing")
    else:
        with tempfile.TemporaryDirectory(prefix="hookshot-precompile-save-") as folder:
            exe = Path(folder) / "t"
            r = subprocess.run([cxx, "-std=c++17", "-O0", "-Wall", "-Wextra", "-Werror",
                                str(ROOT / "tests" / "precompile_save_test.cpp"), "-o", str(exe)],
                               capture_output=True, text=True, timeout=120)
            if r.returncode:
                raise SystemExit("FAIL: precompile_save_test.cpp does not compile\n" + r.stdout + r.stderr)
            r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
            print(r.stdout, end="")
            if r.returncode:
                problems.append("precompile_save_test failed")
    if problems:
        raise SystemExit("FAIL:\n  " + "\n  ".join(problems))
    print("PASS: a long precompile writes the pipeline cache before the title and says what the save did")


if __name__ == "__main__":
    main()
