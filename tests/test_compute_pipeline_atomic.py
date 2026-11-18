"""A compute program's pipeline is read and published atomically in vk_draw.cpp.

The dispatch's build worker, the dispatch itself and the precompile's threads write Program::compute_pipeline while other
recording threads read it (dispatch() reads it before taking ParLock). Plain reads and writes of it there were a data
race. Every use of it in vk_draw.cpp now goes through std::atomic_ref (release stores, acquire loads), and the
synchronous build makes the pipeline into a local and publishes it only once made.

python -I -B tests/test_compute_pipeline_atomic.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    src = (ROOT / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
    uses = 0
    plain = []
    for n, line in enumerate(src.splitlines(), 1):
        code = line.split("//", 1)[0]
        for m in re.finditer(r"\bcompute_pipeline\b", code):
            if code[m.end():m.end() + 1] == "_":
                continue
            uses += 1
            if "std::atomic_ref<VkPipeline>(" not in code[max(0, m.start() - 40):m.start()]:
                plain.append(f"{n}: {line.strip()}")
    if uses < 5:
        raise SystemExit("compute_pipeline is barely used in vk_draw.cpp now: this test needs updating")
    if plain:
        raise SystemExit("compute_pipeline used without std::atomic_ref:\n" + "\n".join(plain))
    if "cached_compute(&ci, &p.compute_pipeline)" in src:
        raise SystemExit("the synchronous build writes compute_pipeline in place, before it is made")
    print(f"compute_pipeline: {uses} uses in vk_draw.cpp, all atomic")


if __name__ == "__main__":
    main()
