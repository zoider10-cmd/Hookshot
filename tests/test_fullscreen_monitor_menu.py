"""Fullscreen monitor identity/menu regression fixture; no game or display server needed.

Compiles actual menu refresh/selection functions and the shared identity helper. Run only when
test compilation is authorized: python -I -B tests/test_fullscreen_monitor_menu.py --cxx clang++
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from srccut import block

PREFIX = r'''
#include "monitor_choice.h"
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
using namespace mkwvk;
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x); exit(1); } } while (0)
namespace i18n { static const char* tr(const char* text) { return text; } }
struct MkwVkMonitor { char id[512],name[256]; int width,height,flags; };
struct Host {
    int (*monitor_count)();
    int (*monitor_info)(int,MkwVkMonitor*);
    void (*monitor_select)(const char*);
};
static Host *host;
std::vector<monitor_choice::Choice> fullscreen_monitors;
int monitor_pick=0;
std::string monitor_want,monitor_saved_name;
bool monitor_missing=false;
bool menu_refresh=false;
struct Row { int *value; int hi; };
Row rows[]={{&monitor_pick,0}};
'''

FIXTURE = r'''
static std::vector<MkwVkMonitor> connected;
static std::string requested;
static int count() { return (int)connected.size(); }
static int info(int index,MkwVkMonitor* out) {
    if (index<0 || index>=(int)connected.size()) return 0;
    *out=connected[index]; return 1;
}
static void select_monitor(const char* id) { requested=id; }
static MkwVkMonitor monitor(const char* id,const char* name,int flags=0) {
    MkwVkMonitor m{};
    snprintf(m.id,sizeof m.id,"%s",id); snprintf(m.name,sizeof m.name,"%s",name);
    m.width=2560; m.height=1440; m.flags=flags; return m;
}
int main() {
    Host h{count,info,select_monitor}; host=&h;
    connected={monitor("display:A","Panel",1),monitor("display:B","Panel")};
    monitor_want="display:B"; refresh_monitors();
    CHECK(monitor_pick==2 && !monitor_missing && monitor_saved_name=="Panel");
    CHECK(std::string(tx_fullscreen_monitor(2)).find("2560x1440")!=std::string::npos);
    CHECK(std::string(tx_fullscreen_monitor(2)).find("[2]")!=std::string::npos);
    CHECK(monitor_choice::current_id(fullscreen_monitors)=="display:A");
    std::reverse(connected.begin(),connected.end()); refresh_monitors();
    CHECK(monitor_pick==1 && monitor_want=="display:B");
    connected.erase(connected.begin()); refresh_monitors();
    CHECK(monitor_missing && monitor_pick==2 && rows[0].hi==2);
    CHECK(monitor_want=="display:B" && monitor_saved_name=="Panel");
    monitor_chosen(); CHECK(requested=="display:B"); // unavailable selection stays intact
    CHECK(std::string(tx_fullscreen_monitor(monitor_pick)).find("not connected")!=std::string::npos);
    connected.push_back(monitor("display:B","Panel")); refresh_monitors();
    CHECK(!monitor_missing && monitor_pick==2);
    monitor_pick=0; monitor_chosen(); CHECK(requested.empty() && monitor_want.empty());
    CHECK(monitor_saved_name.empty() && monitor_pick==0);
    CHECK(std::string(tx_fullscreen_monitor(0))=="Auto (current monitor)");
    monitor_pick=1; monitor_chosen(); CHECK(requested=="display:A" && monitor_want=="display:A");
    connected.clear(); refresh_monitors(); CHECK(monitor_missing && monitor_want=="display:A");
    host=nullptr; monitor_chosen(); CHECK(monitor_want=="display:A");
    CHECK(monitor_choice::id_key("display:A\r\n")=="display:A");
    CHECK(monitor_choice::id_key("bad\nidentity").empty());
    CHECK(monitor_choice::id_key(std::string(512,'x').c_str()).empty());
    std::vector<monitor_choice::Choice> duplicate={{"same","A"},{"same","B"}};
    CHECK(monitor_choice::pick(duplicate,"same")==3);
    CHECK(monitor_choice::pick(duplicate,"")==0);
    puts("fullscreen monitor menu fixture: passed");
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="clang++")
    args = p.parse_args()
    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    funcs = ["bool can_monitors()", "const char* tx_fullscreen_monitor(int value)",
             "std::string output_name_key(const char* text)", "void refresh_monitors()", "void monitor_chosen()"]
    source = PREFIX + "\n".join(block(menu, name) for name in funcs) + FIXTURE
    save = block(menu, "void save()")
    assert 'fprintf(f, "fullscreen_monitor_id=%s\\n", monitor_want.c_str())' in save
    assert "r.value != &monitor_pick" in save
    assert 'key == "fullscreen_monitor_id"' in save
    assert 'key == "fullscreen_monitor_name"' in save
    assert 'if (!strcmp(line, "fullscreen_monitor_id")) monitor_want = monitor_choice::id_key(eq + 1)' in menu
    assert 'if (r.value == &monitor_pick) monitor_chosen();' in block(menu, "void set_row(Row& r, int v, int dir, bool keep = true)")
    follow = block(menu, "void outputs_follow_screen()")
    assert "previous_monitor == current_monitor" in follow  # equal-sized different monitors refresh modes
    assert '"Fullscreen monitor", &monitor_pick' in menu
    with tempfile.TemporaryDirectory(prefix="fullscreen-monitor-menu-") as tmp:
        src = Path(tmp) / "fixture.cpp"
        exe = Path(tmp) / ("fixture.exe" if sys.platform == "win32" else "fixture")
        src.write_text(source, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++17", "-Wall", "-Wextra", "-I", str(ROOT / "gpu/vk"),
                        str(src), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
