"""A pipeline belongs to the program object it was built from (gpu/vk/vk_draw.cpp graphics_pipeline).

The key names a program by its code and variant hash, and two program objects can share both: a pipeline built from one was
drawn with the other, its shaders under the other's layout and constants, and the GPU never finished the draw (device lost on an
RX 7800 XT, and near water on NVIDIA cards). Ported from Hookshot 65e2cb91 via HeyListen 1ae91a2d, with the kept-ready pipelines
HeyListen lacks. Checked by source:

- PipeEntry keeps its program object; every place that makes one stores it (graphics_pipeline, the precompile, and the
  kept-ready pipelines made at a program's create call or by the warm, which carry their object to the entry);
- an entry made for another object is not returned: this one gets its own, under a key of its own, which is not noted;
- RX_VK_PIPE_BY_PROGRAM=0 turns it off, read with the switches' one rule (env_value_off).

python -I -B tests/test_pipe_by_program.py
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


class PipeByProgramTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.draw = (ROOT / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")
        cls.programs = (ROOT / "gpu" / "vk" / "vk_programs.cpp").read_text(encoding="utf-8")
        cls.header = (ROOT / "gpu" / "vk" / "vk_pipelines.h").read_text(encoding="utf-8")

    def test_entry_keeps_its_program_object(self):
        self.assertIn("std::atomic<const Program*> prog{nullptr};", block(self.draw, "struct PipeEntry {"))

    def test_lookup_is_by_key_and_object(self):
        gp = block(self.draw, "PipeEntry* graphics_pipeline(")
        for need in ('const char* e = getenv("RX_VK_PIPE_BY_PROGRAM"); return !(e && env_value_off(e));',
                     "const uint64_t own = mix(key, (uint64_t)(uintptr_t)&p);",
                     "if (!by_program || own_key || !made_for || made_for == &p) return false;",
                     "key = own, own_key = true;",
                     "made_for_another(it->second->prog.load(std::memory_order_acquire));",
                     "e->prog.store(&p, std::memory_order_release);",
                     "mine.find(mkey)", "mine[mkey]",
                     "!own_key && pipeline_note(key"):
            self.assertIn(need, gp, need)
        self.assertNotIn("mine.find(key)", gp)
        self.assertNotIn("mine[key]", gp)
        # (the check comes before an entry is made for this draw)
        self.assertLess(gp.index("made_for_another(it->second->prog"), gp.index("PipeEntry* e = pipelines.emplace(key"))
        # (pipeline_note is called once, and only where the key is not its own)
        self.assertEqual(len(re.findall(r"\bpipeline_note\(", gp)), 1)

    def test_kept_ready_carries_its_object(self):
        self.assertIn("struct KeptPipe { VkPipeline pipeline; const Program* prog; };", self.draw)
        self.assertIn("std::unordered_map<uint64_t, KeptPipe> kept_ready;", self.draw)
        keep = block(self.draw, "bool pipeline_keep_ready(uint64_t key, VkPipeline pl, const Program* prog) {")
        self.assertIn("kept_ready.emplace(key, KeptPipe{pl, prog})", keep)
        self.assertIn("bool pipeline_keep_ready(uint64_t key, VkPipeline pl, const Program* prog);", self.header)
        gp = block(self.draw, "PipeEntry* graphics_pipeline(")
        for need in ("ke->prog.store(kept.prog, std::memory_order_release);", "if (!made_for_another(kept.prog)) return remember(ke);"):
            self.assertIn(need, gp, need)
        # (every caller names the object it built from)
        calls = re.findall(r"pipeline_keep_ready\(([^;]*)\);", self.draw + self.programs)
        self.assertTrue(calls)
        for args in calls:
            if args.startswith("uint64_t"):
                continue   # (the definition)
            self.assertEqual(args.count(","), 2, args)

    def test_precompile_stores_the_object(self):
        run = block(self.draw, "void precompile_run(")
        self.assertIn("e->prog.store(p, std::memory_order_release);", run)


if __name__ == "__main__":
    unittest.main()
