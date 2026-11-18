"""The Insert menu's save (gpu/vk/vk_menu.cpp save) never leaves hookshot_options.ini cut short, and saves wherever the
in-place write did. A save that cannot be written whole (a full disk, often an SD card on a Steam Deck, or the game closed
while it writes) must leave the file as it was: a file cut after a few lines made the next start take the defaults for
every row past the cut, the controls among them, and a file cut to nothing made it a first start, Auto (this PC) chosen
over the player's preset. The file is written beside itself and moved over it once whole; where that cannot be done the
save still happens:

- full_disk: a write past the disk's room leaves the old file whole, no .new left, one log line, none the second time
- success: a save leaves no .new beside the file
- symlink: a linked options file (settings synced elsewhere) stays a link, and its target gets the new settings
- folder_read_only: a game folder that cannot take a new file, holding a writable options file, still saves in place,
  and says so once in the log
- mode: the file keeps its permissions (0600 stays 0600)
- file_read_only: a read-only options file is kept as it is, and said once in the log
- user_folder: the file in the launcher's user folder (--user, host/options_path.c), away from the folder the game runs in:
  the save is moved over it there and leaves nothing in the game's folder, and a line in the log names the file's whole path
- no_file: no settings file this run (options_path() empty: the host found no place for it) saves nothing, makes nothing in
  the folder the game runs in and logs nothing
- output_device: a named output is saved once by ID and name, never its list index; switching to the system default
  removes both saved fields and old numeric selections while preserving unrelated settings

The real save() is cut out of the source and compiled with stand-ins for the menu's rows and the host's bindings. A full
disk is RLIMIT_FSIZE (the write past it fails with EFBIG, SIGXFSZ ignored), checked to hold before the save is tried. Each
case runs in a process and a folder of its own; each checks its own preconditions. No game, GPU or window.

    python -I -B tests/test_menu_save_atomic.py [--cxx g++] [case ...]
"""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
RUN_ALL_SKIP = {"windows": "RLIMIT_FSIZE, symlinks and POSIX modes stand in for the cases: POSIX only"}

ROOT = Path(__file__).resolve().parents[1]
CASES = ["full_disk", "success", "symlink", "folder_read_only", "mode", "file_read_only", "user_folder", "no_file",
         "output_device"]


def block(text, marker):
    start = text.index(marker)
    depth = 0
    for at in range(text.index("{", start), len(text)):
        depth += text[at] == "{"
        depth -= text[at] == "}"
        if depth == 0:
            return text[start:at + 1]
    raise SystemExit("unterminated: " + marker)


FIXTURE = r'''#include <cerrno>
#include <csignal>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dirent.h>
#include <mutex>
#include <string>
#include <vector>
#include <sys/resource.h>
#include <sys/stat.h>
#include <unistd.h>
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
enum { HOS_SW_N = 16, HOS_KEY_OC_NOTE_L = 24, HOS_KEY_OC_NOTE_X = 28, HOS_KEY_N = 30 };
enum { HOS_BIND_PAD, HOS_BIND_KEY };
struct Out { unsigned w, h; };
struct Options { int preset = 1, fps_cap = 0, vram_budget = 1, output_res = 0, ultrawide = 1, game_lang = 0, budget = 1,
                 hold_toggle = 0, gpu_device = 0; } opts;
struct Row { const char* name; int* value; };
int output_pick = 0;
std::string output_want, output_saved_name;
int monitor_pick = 0;
std::string monitor_want, monitor_saved_name; // Real save() also persists this identity; this fixture tests atomicity.
Row rows[] = {{"Quality preset", &opts.preset}, {"Game frame rate cap", &opts.fps_cap}, {"VRAM budget", &opts.vram_budget},
              {"Output resolution", &opts.output_res}, {"Aspect ratio", &opts.ultrawide}, {"Game language", &opts.game_lang},
              {"Output device", &output_pick}};
std::string dir;
std::vector<std::string> logged;
void logf(const char* fmt, ...) {
    char b[512];
    va_list a;
    va_start(a, fmt);
    std::vsnprintf(b, sizeof b, fmt, a);
    va_end(a);
    logged.push_back(b);
    std::fprintf(stderr, "log: %s\n", b);
}
bool no_file = false;   // (options_path() empty: no settings file this run)
std::string ini_path() { return no_file ? std::string() : dir + "/hookshot_options.ini"; }
const char* ini_key(const Row& r) {
    static char k[32];
    size_t n = 0;
    for (const char* p = r.name; *p && n + 1 < sizeof k; p++) k[n++] = *p == ' ' ? '_' : (char)(*p | 0x20);
    k[n] = 0;
    return k;
}
int saved_value(int* v) { return *v; }
int custom_index() { return 1; }
bool env_holds(const int*) { return false; }
Out player_custom_output{0, 0};
Out output_at(int) { return {1280, 800}; }
int aspect_started = 0, ultrawide_read = 1;
bool aspect_follows_host(int) { return true; }
std::string mic_want;
unsigned long long auto_for = 0, auto_tuned = 0;
namespace gpu_choice { struct Card {}; inline std::string card_id(const std::vector<Card>&, int) { return {}; } }   // (the GPU device row's card)
std::vector<gpu_choice::Card> gpu_device_cards;
std::string gpu_saved_card;
bool gpu_card_missing = false;
struct { int steps = 0; bool went_down = false; } auto_tuning;
const char* const bind_names[HOS_KEY_N] = {"a", "b", "x", "y", "ls", "rs", "l", "r", "zl", "zr", "plus", "minus", "left",
    "up", "right", "down", "move_up", "move_down", "move_left", "move_right", "cam_up", "cam_down", "cam_left", "cam_right",
    "note_l", "note_r", "note_a", "note_y", "note_x", "walk"};
struct Host { int (*binding)(int set, int button, int slot); };
int binding(int set, int button, int slot) { return set == HOS_BIND_PAD ? (slot ? -1 : button % 4) : slot ? 0 : 'A' + button; }
Host host_v{binding};
Host* host = &host_v;
bool can_bind() { return true; }

@SAVE@

std::string slurp(const std::string& p) {
    std::string s;
    if (FILE* f = std::fopen(p.c_str(), "rb")) {
        char b[4096];
        for (size_t n; (n = std::fread(b, 1, sizeof b, f)) > 0;) s.append(b, n);
        std::fclose(f);
    }
    return s;
}
/// The names in a folder, but . and ..
std::vector<std::string> names(const std::string& in) {
    std::vector<std::string> v;
    if (DIR* d = opendir(in.c_str())) {
        while (dirent* e = readdir(d))
            if (strcmp(e->d_name, ".") && strcmp(e->d_name, "..")) v.push_back(e->d_name);
        closedir(d);
    }
    return v;
}
bool has(const std::string& text, const char* line) { return text.find(line) != std::string::npos; }
/// The player's options, as a save writes them, with a line the menu keeps for others
std::string first_save() {
    if (FILE* f = std::fopen(ini_path().c_str(), "w")) std::fputs("discord_app_id=1234567890\n", f), std::fclose(f);
    save();
    const std::string s = slurp(ini_path());
    CHECK(has(s, "game_frame_rate_cap=0\n") && has(s, "discord_app_id=1234567890\n") && has(s, "key_walk="));
    logged.clear();
    return s;
}
int main(int argc, char** argv) {
    CHECK(argc == 3);
    dir = argv[1];
    const std::string c = argv[2];
    std::signal(SIGXFSZ, SIG_IGN);   // (a write past the limit fails with EFBIG, as a full disk's with ENOSPC)
    if (c == "full_disk") {
        output_pick = 1;
        output_want = "fixture-old-id";
        output_saved_name = "Fixture old speakers";
        const std::string before = first_save();
        CHECK(has(before, "audio_output_device_id=fixture-old-id\n"));
        CHECK(has(before, "audio_output_device_name=Fixture old speakers\n"));
        constexpr rlim_t kRoom = 200;   // (the disk's room: less than the file)
        CHECK(before.size() > 2 * kRoom);
        rlimit was{};
        CHECK(getrlimit(RLIMIT_FSIZE, &was) == 0);
        rlimit full = was;
        full.rlim_cur = kRoom;
        CHECK(setrlimit(RLIMIT_FSIZE, &full) == 0);
        {   // (the full disk holds: a write past kRoom fails)
            const std::string probe = dir + "/probe";
            FILE* f = std::fopen(probe.c_str(), "w");
            CHECK(f);
            const std::string big(kRoom * 2, 'x');
            const bool wrote = std::fwrite(big.data(), 1, big.size(), f) == big.size();
            const bool closed = std::fclose(f) == 0;
            CHECK(!(wrote && closed));
            CHECK(std::remove(probe.c_str()) == 0);
        }
        opts.fps_cap = 2;   // (a row changed: the save that does not fit)
        output_want = "fixture-new-id";
        output_saved_name = "Fixture new speakers";
        save();
        const std::string after = slurp(ini_path());
        if (after != before) {
            std::fprintf(stderr, "FAIL: a save that did not fit left hookshot_options.ini at %zu bytes of %zu:\n%s\n",
                         after.size(), before.size(), after.c_str());
            return 1;
        }
        CHECK(names(dir).size() == 1);   // (nothing of the failed save left beside it)
        CHECK(logged.size() == 1);       // (said, once)
        opts.fps_cap = 3;
        save();                           // (failing again: not said again)
        CHECK(slurp(ini_path()) == before && names(dir).size() == 1);
        CHECK(logged.size() == 1);
        CHECK(setrlimit(RLIMIT_FSIZE, &was) == 0);
        save();   // (with room again, the change is saved)
        const std::string again = slurp(ini_path());
        CHECK(has(again, "game_frame_rate_cap=3\n") && has(again, "discord_app_id=1234567890\n") && has(again, "key_walk="));
        CHECK(has(again, "audio_output_device_id=fixture-new-id\n"));
        CHECK(has(again, "audio_output_device_name=Fixture new speakers\n"));
        CHECK(!has(again, "fixture-old-id") && !has(again, "Fixture old speakers"));
        CHECK(names(dir).size() == 1);
    } else if (c == "success") {
        first_save();
        opts.fps_cap = 2;
        save();
        CHECK(has(slurp(ini_path()), "game_frame_rate_cap=2\n"));
        CHECK(names(dir).size() == 1 && names(dir)[0] == "hookshot_options.ini");
        CHECK(logged.empty());
    } else if (c == "symlink") {
        // (the game folder's file a link to a synced folder's)
        const std::string synced = dir + "/synced", game = dir + "/game";
        CHECK(mkdir(synced.c_str(), 0755) == 0 && mkdir(game.c_str(), 0755) == 0);
        const std::string target = synced + "/hookshot_options.ini";
        if (FILE* f = std::fopen(target.c_str(), "w")) std::fputs("discord_app_id=1234567890\n", f), std::fclose(f);
        dir = game;
        CHECK(symlink(target.c_str(), ini_path().c_str()) == 0);
        struct stat st{};
        CHECK(lstat(ini_path().c_str(), &st) == 0 && S_ISLNK(st.st_mode));
        opts.fps_cap = 2;
        save();
        CHECK(lstat(ini_path().c_str(), &st) == 0);
        if (!S_ISLNK(st.st_mode)) {
            std::fprintf(stderr, "FAIL: the save replaced the linked options file with a file of its own\n");
            return 1;
        }
        const std::string synced_now = slurp(target);
        CHECK(has(synced_now, "game_frame_rate_cap=2\n") && has(synced_now, "discord_app_id=1234567890\n"));
        CHECK(names(game).size() == 1 && names(synced).size() == 1);
        CHECK(logged.empty());
    } else if (c == "folder_read_only") {
        first_save();
        CHECK(chmod(dir.c_str(), 0555) == 0);
        {   // (the folder takes no new file)
            const std::string probe = dir + "/probe";
            FILE* f = std::fopen(probe.c_str(), "w");
            if (f) std::fclose(f), std::remove(probe.c_str());
            CHECK(!f);
        }
        opts.fps_cap = 2;
        save();
        const std::string after = slurp(ini_path());
        const bool saved = has(after, "game_frame_rate_cap=2\n") && has(after, "key_walk=");
        const size_t said = logged.size();
        opts.fps_cap = 3;
        save();
        const std::string again = slurp(ini_path());
        CHECK(chmod(dir.c_str(), 0755) == 0);
        if (!saved) {
            std::fprintf(stderr, "FAIL: a game folder that takes no new file lost the save:\n%s\n", after.c_str());
            return 1;
        }
        CHECK(has(again, "game_frame_rate_cap=3\n"));
        CHECK(said == 1 && logged.size() == 1);   // (said once, with why)
        CHECK(names(dir).size() == 1);
    } else if (c == "mode") {
        first_save();
        CHECK(chmod(ini_path().c_str(), 0600) == 0);
        opts.fps_cap = 2;
        save();
        struct stat st{};
        CHECK(stat(ini_path().c_str(), &st) == 0);
        CHECK(has(slurp(ini_path()), "game_frame_rate_cap=2\n"));
        if ((st.st_mode & 07777) != 0600) {
            std::fprintf(stderr, "FAIL: the options file's mode is %o after a save, not 600\n", (unsigned)(st.st_mode & 07777));
            return 1;
        }
    } else if (c == "file_read_only") {
        const std::string before = first_save();
        CHECK(chmod(ini_path().c_str(), 0444) == 0);
        CHECK(access(ini_path().c_str(), W_OK) != 0);   // (not root: the mode holds)
        opts.fps_cap = 2;
        save();
        const std::string after = slurp(ini_path());
        const size_t said = logged.size();
        opts.fps_cap = 3;
        save();
        struct stat st{};
        CHECK(stat(ini_path().c_str(), &st) == 0);
        CHECK(chmod(ini_path().c_str(), 0644) == 0);
        if (after != before) {
            std::fprintf(stderr, "FAIL: a read-only options file was replaced:\n%s\n", after.c_str());
            return 1;
        }
        CHECK((st.st_mode & 07777) == 0444);
        CHECK(said == 1 && logged.size() == 1);
        CHECK(names(dir).size() == 1);
    } else if (c == "user_folder") {
        // (the launcher's user folder holds the file; the game runs in its own folder, which gets nothing)
        const std::string game = dir + "/game", user = dir + "/user";
        CHECK(mkdir(game.c_str(), 0755) == 0 && mkdir(user.c_str(), 0755) == 0 && chdir(game.c_str()) == 0);
        dir = user;
        first_save();
        opts.fps_cap = 2;
        save();
        CHECK(has(slurp(ini_path()), "game_frame_rate_cap=2\n") && has(slurp(ini_path()), "discord_app_id=1234567890\n"));
        CHECK(names(user).size() == 1 && names(game).empty());
        CHECK(logged.empty());
        CHECK(chmod(ini_path().c_str(), 0444) == 0);
        opts.fps_cap = 3;
        save();
        CHECK(chmod(ini_path().c_str(), 0644) == 0);
        CHECK(has(slurp(ini_path()), "game_frame_rate_cap=2\n") && names(user).size() == 1 && names(game).empty());
        if (logged.size() != 1 || logged[0].find(ini_path()) == std::string::npos) {
            std::fprintf(stderr, "FAIL: a read-only file in the user folder is not said once with its path (%zu lines)\n",
                         logged.size());
            return 1;
        }
    } else if (c == "output_device") {
        FILE* f = std::fopen(ini_path().c_str(), "w");
        CHECK(f);
        std::fputs("discord_app_id=1234567890\noutput_device=7\n"
                   "audio_output_device_id=stale-id\naudio_output_device_name=Stale speakers\n", f);
        CHECK(std::fclose(f) == 0);
        output_pick = 2;
        output_want = "fixture-output-id";
        output_saved_name = "Fixture speakers";
        save();
        const std::string named = slurp(ini_path());
        CHECK(has(named, "audio_output_device_id=fixture-output-id\n"));
        CHECK(has(named, "audio_output_device_name=Fixture speakers\n"));
        CHECK(named.find("audio_output_device_id=") == named.rfind("audio_output_device_id="));
        CHECK(named.find("audio_output_device_name=") == named.rfind("audio_output_device_name="));
        CHECK(!has(named, "\noutput_device=") && !has(named, "stale-id") && !has(named, "Stale speakers"));
        CHECK(has(named, "discord_app_id=1234567890\n") && has(named, "key_walk="));
        output_pick = 37;   // (the enumeration index changes; the saved endpoint stays the same)
        save();
        CHECK(slurp(ini_path()) == named);
        output_pick = 0;
        output_want.clear();
        output_saved_name.clear();
        save();
        const std::string defaults = slurp(ini_path());
        CHECK(!has(defaults, "audio_output_device_id=") && !has(defaults, "audio_output_device_name="));
        CHECK(!has(defaults, "\noutput_device="));
        CHECK(has(defaults, "discord_app_id=1234567890\n") && has(defaults, "key_walk="));
        CHECK(names(dir).size() == 1 && logged.empty());
    } else if (c == "no_file") {
        CHECK(chdir(dir.c_str()) == 0);
        no_file = true;
        opts.fps_cap = 2;
        save();
        save();
        if (!names(dir).empty() || !logged.empty()) {
            std::fprintf(stderr, "FAIL: a run with no settings file left %zu files in the game's folder and %zu log lines\n",
                         names(dir).size(), logged.size());
            return 1;
        }
    } else {
        CHECK(!"a case");
    }
    std::printf("menu save: %s ok\n", c.c_str());
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="g++")
    p.add_argument("cases", nargs="*", default=CASES)
    a = p.parse_args()
    if os.geteuid() == 0:
        print("SKIP: as root the read-only cases' modes do not hold")
        return
    src = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    fixture = FIXTURE.replace("@SAVE@", block(src, "void save() {"))
    failed = []
    with tempfile.TemporaryDirectory(prefix="menu-save-") as tmp:
        cpp = Path(tmp) / "menu_save.cpp"
        cpp.write_text(fixture, encoding="utf-8")
        exe = Path(tmp) / "menu-save"
        subprocess.run([a.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", str(cpp), "-o", str(exe)],
                       check=True)
        for case in a.cases:
            data = Path(tmp) / case
            data.mkdir()
            r = subprocess.run([str(exe), str(data), case], timeout=60)
            os.chmod(data, 0o755)   # (a folder a case left read-only: the clean-up can remove it)
            if r.returncode:
                failed.append(case)
    if failed:
        raise SystemExit("FAIL: " + ", ".join(failed))
    print("PASS: the options file is replaced whole or not at all, and saved wherever it was before")


if __name__ == "__main__":
    main()
