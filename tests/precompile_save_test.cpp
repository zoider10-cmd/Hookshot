// gpu/vk/precompile_save.h: when the precompile writes the pipeline cache before the title, and what the log says a save did.
// tests/test_precompile_save.py builds and runs it.
#include "../gpu/vk/precompile_save.h"

#include <cstdio>
#include <string>

static int failed = 0;
static void check(bool ok, const char* what) {
    if (!ok) {
        failed++;
        printf("FAIL: %s\n", what);
    }
}

int main() {
    using namespace precompile_save;
    check(after_s(nullptr) == 30 && after_s("") == 30, "unset: 30 s");
    check(after_s("0") == 0 && after_s("90") == 90, "a number of seconds");
    check(after_s("x") == 30 && after_s("10s") == 30 && after_s("-5") == 30, "not a whole number: the default");
    check(after_s("999999") == 86400, "a day at most");

    // (a Steam Deck's start from Steam: 1,222 s of graphics pipelines; a start that found them: 2 s)
    check(due(1222, 30, false, false, false), "a start that compiled for 20 minutes writes it");
    check(!due(2, 30, false, false, false), "a start that found its pipelines does not");
    check(due(30, 30, false, false, false), "at the time itself");
    check(!due(1222, 0, false, false, false), "0: never");
    check(!due(1222, 30, true, false, false), "not with pipelines left in the driver (gone on)");
    check(!due(1222, 30, false, true, false), "not after the window was closed in it");
    check(!due(1222, 30, false, false, true), "not in the preparation's process, which writes it anyway");

    Outcome o;
    check(said(o).find("did not run") != std::string::npos, "nothing ran");
    o.what = Outcome::kWritten, o.bytes = 449ull << 20;
    check(said(o) == "written, 449.0 MB", "written, with its size");
    o.what = Outcome::kSame;
    check(said(o).find("nothing new") != std::string::npos, "nothing new");
    o.what = Outcome::kOff;
    check(said(o).find("RX_VK_PCACHE_LOAD=0") != std::string::npos, "off, and why");
    o.what = Outcome::kWriteFailed, o.detail = "cache/hookshot_vk_pipelines.bin";
    check(said(o).find("cache/hookshot_vk_pipelines.bin could not be written") != std::string::npos, "the file named");
    o.what = Outcome::kError, o.detail = "disk full";
    check(said(o).find("disk full") != std::string::npos, "the error's words");
    for (Outcome::What w : {Outcome::kNoCache, Outcome::kFetchFailed})
        o.what = w, check(said(o).rfind("not written: ", 0) == 0, "the others say not written, and why");

    if (!failed) printf("PASS: the precompile's save before the title\n");
    return failed ? 1 : 0;
}
