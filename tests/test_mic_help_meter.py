"""Compile the real microphone help formatting, sizing and drawing with fake UI calls. No game/GPU/window.

Checks that the two rows share explanation/meter support, the meter has no editable hit region, and its reserved
space remains stable across states and menu scales. Font metrics are stand-ins; visual acceptance is a separate check.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from srccut import block, between

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ['--cxx', '{cxx}']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='g++')
    args = parser.parse_args()
    menu = (ROOT/'gpu/vk/vk_menu.cpp').read_text(encoding='utf-8')
    ui = (ROOT/'gpu/vk/vk_ui.h').read_text(encoding='utf-8')
    assert '{TAB_AUDIO, "Microphone level"' not in menu
    options = block(menu, 'void draw_options(')
    assert 'const bool mic_help = mic_help_row(selr);' in options
    assert 'bar_top - 10 * s, mic_help)' in options and 'bar_top - 12 * s, mic_help)' in options
    measurement = block(menu, 'float measure_help(')
    assert 'mic_help_text(r.help)' in measurement and 'mic_meter_height(c, width)' in measurement
    # Navigating from Test to Gain must not release the test (capture lifetime remains Audio/page/focus based).
    lifetime = block(menu, 'void mic_test_tick(')
    assert 'cur_tab != TAB_AUDIO' in lifetime and 'page != 0' in lifetime
    assert 'tab_selected' not in lifetime
    help_constant = between(menu, 'constexpr const char* kMicLevelHelp', '\nconst char* tx_percent(')
    fixture = r'''
#include <algorithm>
#include <cassert>
#include <cfloat>
#include <cstddef>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
using ImU32 = unsigned;
struct ImVec2 { float x,y; ImVec2(float a=0,float b=0):x(a),y(b){} };
struct ImFont {
    const char* CalcWordWrapPosition(float px,const char* t,const char* end,float width) {
        return t+std::min(end-t,(std::ptrdiff_t)std::max(0.f,std::floor(width/(px*.5f))));
    }
};
namespace i18n {
bool translated = false;
const char* tr(const char* s) {
    if (!translated) return s;
    if (!strcmp(s,"Start or stop capture.")) return "Capture : démarrer ou arrêter.";
    if (!strcmp(s,"Waiting for samples")) return "En attente d'échantillons";
    if (!strcmp(s," (Default fallback)")) return " (microphone par défaut utilisé)";
    if (!strcmp(s,"Microphone unavailable")) return "Microphone indisponible";
    if (!strcmp(s,"Clipping")) return "Écrêtage";
    if (!strcmp(s,"Default fallback")) return "Microphone par défaut utilisé";
    if (!strcmp(s,"Test stopped")) return "Test arrêté";
    if (!strncmp(s,"Shows microphone signal strength",31)) return "Niveau du signal.\n\n- Avant le gain.\n- Après le gain.";
    if (!strcmp(s,"Testing: 12% -> 24%")) return "Test en cours : 12% -> 24%";
    return s;
}
}
struct Draw {
    ImVec2 clip_a,clip_b;
    float text_bottom=0;
    void AddText(ImFont*,float px,ImVec2 p,ImU32,const char*,const char*) { text_bottom=std::max(text_bottom,p.y+px); }
    void AddRectFilled(ImVec2,ImVec2,ImU32,float=0) {}
    void AddLine(ImVec2,ImVec2,ImU32,float) {}
    void PushClipRect(ImVec2 a,ImVec2 b,bool) { clip_a=a;clip_b=b; }
    void PopClipRect() {}
};
namespace ui {
struct Ctx {float s=1; struct {ImFont *body,*heading,*strong;} f; Draw* d;};
constexpr ImU32 kInk=1,kSoft=2,kAccent=3,kGoldHi=4,kEdge=5;
ImU32 alpha(ImU32 c,float) {return c;}
void box(Ctx&,ImVec2,ImVec2) {}
void text(Ctx&,ImFont*,float,ImVec2,ImU32,const char*) {}
void text_mid(Ctx&,ImFont*,float,float,float,ImU32,const char*) {}
void diamond(Ctx&,ImVec2,float,ImU32) {}
@PARA@
}
struct Row {int tab;const char* name;};
constexpr int TAB_AUDIO=1;
bool mic_testing=false;
int mic_levels[2]={},mic_test_state=0;
@EXPLANATION@
@HELPERS@
static int meter_calls;
static ImVec2 meter_a,meter_b;
static std::string rendered_label;
static bool rendered_adjustable;
void slider_cell(ui::Ctx&,ImVec2 a,ImVec2 b,const char* label,int peak,bool selected,float* t0,float* t1,bool adjustable) {
    meter_calls++;meter_a=a;meter_b=b;rendered_label=label;rendered_adjustable=adjustable;
    assert(!selected && !adjustable && peak>=0 && peak<=1000);
    *t0=*t1=0;
}
@DRAW_METER@
@HELP_BOX@
int main() {
    assert(mic_help_row({TAB_AUDIO,"Test microphone"}));
    assert(mic_help_row({TAB_AUDIO,"Microphone gain"}));
    assert(!mic_help_row({TAB_AUDIO,"Volume"}) && !mic_help_row({0,"Test microphone"}));
    const std::string help=mic_help_text("Start or stop capture.");
    assert(help.find("Start or stop capture.\n\nShows microphone signal strength") == 0);
    assert(help.find("\n- Second percentage:") != std::string::npos);
    assert(help.find("\n\n- First percentage:") != std::string::npos);
    assert(mic_meter_label(11,120,240)=="Testing: 12% -> 24%");
    assert(mic_meter_label(11,-500,5000)=="Testing: 0% -> 100%");
    assert(mic_meter_label(0,100,100)=="Test stopped");
    assert(mic_meter_status(1)=="Microphone unavailable");
    assert(mic_meter_status(3)=="Waiting for samples");
    assert(mic_meter_status(11).empty());
    assert(mic_meter_status(27)=="Clipping");
    assert(mic_meter_status(31)=="Clipping (Default fallback)");
    assert(mic_meter_status(15)=="Default fallback");
    i18n::translated=true;
    assert(mic_help_text("Start or stop capture.")=="Capture : démarrer ou arrêter.\n\nNiveau du signal.\n\n- Avant le gain.\n- Après le gain.");
    assert(mic_meter_label(11,120,240)=="Test en cours : 12% -> 24%");
    assert(mic_meter_status(0)=="Test arrêté");
    assert(mic_meter_status(7)=="En attente d'échantillons (microphone par défaut utilisé)");
    assert(mic_meter_status(5)=="Microphone indisponible (microphone par défaut utilisé)");
    assert(mic_meter_status(31)=="Écrêtage (microphone par défaut utilisé)");
    assert(mic_meter_status(15)=="Microphone par défaut utilisé");
    i18n::translated=false;
    ImFont font;Draw draw;ui::Ctx c{1,{&font,&font,&font},&draw};
    // A long translated paragraph must reduce only as needed and use the same size for measuring and drawing.
    const std::string long_help(600, 'x');
    const float available=ui::para(c,c.f.body,16.f,ImVec2(),0,long_help.c_str(),260.f,false);
    const float fitted=mic_help_font_size(c,long_help.c_str(),260.f,available);
    assert(fitted >= 14.f && fitted < 18.f);
    assert(ui::para(c,c.f.body,fitted,ImVec2(),0,long_help.c_str(),260.f,false) <= available);
    assert(mic_help_font_size(c,"Short help.",260.f,600.f)==18.f);
    assert(mic_help_font_size(c,long_help.c_str(),260.f,1.f)==14.f); // readable lower bound
    mic_testing=true;mic_test_state=11;
    help_box(c,0,330,100,"Test microphone",long_help.c_str(),nullptr,nullptr,0,false,0,650,true);
    assert(draw.text_bottom <= draw.clip_b.y); // rendered final line survives the bounded box, not just measurement
    for(float scale : {.75f,1.f,1.5f}) for(float width : {260.f,380.f,600.f}) {
        c.s=scale;
        mic_testing=false;meter_calls=0;
        help_box(c,0,width*scale,20*scale,"Test microphone","Start or stop capture.",nullptr,nullptr,0,false,0,650*scale,true);
        assert(meter_calls==0);
        const float stopped_height=draw.clip_b.y-draw.clip_a.y;
        mic_testing=true;mic_test_state=31;mic_levels[0]=120;mic_levels[1]=240;
        help_box(c,0,width*scale,20*scale,"Microphone gain","Start or stop capture.",nullptr,nullptr,0,false,0,650*scale,true);
        assert(meter_calls==1 && !rendered_adjustable && rendered_label=="Testing: 12% -> 24%");
        assert(meter_a.y>=draw.clip_a.y && meter_b.y<=draw.clip_b.y);
        assert(meter_a.x>=draw.clip_a.x && meter_b.x<=draw.clip_b.x);
        assert(std::fabs(stopped_height-(draw.clip_b.y-draw.clip_a.y))<.01f);
        meter_calls=0;
        help_box(c,0,width*scale,0,"Volume","Other help.",nullptr,nullptr);
        assert(meter_calls==0); // unrelated help never gains a meter
    }
}
'''
    helpers = '\n'.join(block(menu, signature) for signature in
                        ('bool mic_help_row(', 'std::string mic_help_text(', 'std::string mic_meter_label(',
                         'std::string mic_meter_status(', 'float mic_meter_height('))
    helpers += '\n' + block(menu, 'float mic_help_font_size(')
    for token, value in (('@PARA@', block(ui, 'inline float para(')), ('@EXPLANATION@', help_constant),
                         ('@HELPERS@', helpers), ('@DRAW_METER@', block(menu, 'void mic_help_meter(ui::Ctx& c, ImVec2 a, ImVec2 b) {')),
                         ('@HELP_BOX@', block(menu, 'void help_box('))):
        fixture = fixture.replace(token, value)
    with tempfile.TemporaryDirectory(prefix='mic-help-meter-') as folder:
        work = Path(folder)
        source = work/'fixture.cpp'
        source.write_text(fixture, encoding='utf-8')
        exe = work/'fixture.exe'
        subprocess.run([args.cxx,'-std=c++17','-Wall','-Wextra','-Werror',str(source),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
    print('PASS: shared help and bullets, Testing percentages, status flags, read-only meter, stable sizing and Audio-row lifetime')


if __name__ == '__main__':
    main()
