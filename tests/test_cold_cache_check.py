"""A start that loads at create calls asks the driver's own cache for a sample of the notes first, and builds them all again
before the title when it has lost them.

The marker (precompile_built_write) said every note had been built into the pipeline cache, but on NVIDIA that cache refers to the
driver's own, which a driver update empties and which evicts past its size: each listed pipeline was then compiled in play with
its draws left out (702,312 draws in 140 s on the gate route with NVIDIA's cache pointed at an empty folder), and only the next
start built them before the title. These checks keep the sample asked of the driver alone, without compiling, and the warm pass
run again when most of it is gone.

python -I -B tests/test_cold_cache_check.py
"""
from pathlib import Path
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (tests/srccut.py: python -I leaves this folder off the path)
from srccut import block   # noqa: E402

DRAW = (Path(__file__).resolve().parents[1] / "gpu" / "vk" / "vk_draw.cpp").read_text(encoding="utf-8")


class ColdCacheCheckTests(unittest.TestCase):
    def test_the_sample_is_asked_of_the_driver_alone_without_a_compile(self):
        check = block(DRAW, "bool notes_lost_by_driver()")
        self.assertIn('getenv("RX_VK_COLD_CHECK")', check)
        self.assertIn("pipelineCreationCacheControl", check)
        # (an empty scratch cache, and build_graphics asked with its cold flag: it compiles nothing)
        self.assertIn("driver_cache_only = true, driver_ask_cache = scratch;", check)
        self.assertIn("&cold);", check)
        self.assertLess(check.index("driver_cache_only = true, driver_ask_cache = scratch;"), check.index("build_graphics("))
        # (put back by a guard however the function ends, a throw included: the scratch cache and the file let go with it)
        guard = check[check.index("struct Restore"):check.index("} restore{f, scratch};")]
        for part in ("~Restore()", "driver_cache_only = false, driver_ask_cache = VK_NULL_HANDLE;", "vkDestroyPipelineCache", "fclose(f);"):
            self.assertIn(part, guard, part)
        self.assertLess(check.index("} restore{f, scratch};"), check.index("driver_cache_only = true, driver_ask_cache = scratch;"))

    def test_lost_means_most_of_an_asked_sample(self):
        check = block(DRAW, "bool notes_lost_by_driver()")
        self.assertIn("asked >= kSample / 3 && cold_n * 2 > asked", check)

    def test_a_lost_sample_runs_the_warm_pass_again(self):
        run = block(DRAW, "void precompile_run(void (*progress)(size_t done, size_t total))")
        guard = run.index("notes_lost_by_driver()")
        self.assertIn('!env_on("HOOKSHOT_PREPARE_ONLY")', run[run.rindex("if (", 0, guard):guard])
        self.assertLess(guard, run.index("if (!precompile_covers_notes()) precompile_warm(progress);"))
        self.assertIn("remove(precompile_built_path().c_str());", run[guard:guard + 120])


if __name__ == "__main__":
    unittest.main()
