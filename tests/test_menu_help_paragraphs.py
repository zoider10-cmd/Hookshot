"""Compile the real help paragraph renderer with fake font/draw calls; check line breaks, wrapping and measurement.
No window, game or GPU. python -I -B tests/test_menu_help_paragraphs.py --cxx clang++
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from srccut import block

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ['--cxx', '{cxx}']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='g++')
    args = parser.parse_args()
    ui = (ROOT/'gpu/vk/vk_ui.h').read_text(encoding='utf-8')
    fixture = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstring>
#include <string>
#include <vector>
using ImU32 = unsigned;
struct ImVec2 { float x, y; ImVec2(float x0=0, float y0=0):x(x0),y(y0){} };
namespace i18n { const char* tr(const char* t) { return t; } }
struct ImFont {
    const char* CalcWordWrapPosition(float, const char* t, const char* end, float wrap) {
        // ImGui can scan across hard breaks; the paragraph renderer must delimit each logical line itself.
        assert(!memchr(t, '\n', (size_t)(end-t)));
        return t + std::min(end-t, (std::ptrdiff_t)wrap);
    }
};
struct Line { std::string text; float y; };
struct Draw {
    std::vector<Line> lines;
    void AddText(ImFont*, float, ImVec2 at, ImU32, const char* begin, const char* end) {
        lines.push_back({std::string(begin,end), at.y});
    }
};
struct Ctx { Draw* d; };
@PARA@
int main() {
    ImFont font; Draw draw; Ctx ctx{&draw};
    const char* text = "Overview.\n\n- First percentage: before gain.\n- Second percentage: after gain.\n\nGain note.";
    float height = para(ctx,&font,10,{},0,text,200);
    assert(draw.lines.size()==4);
    assert(draw.lines[0].text=="Overview." && draw.lines[0].y==0);
    assert(draw.lines[1].text=="- First percentage: before gain." && draw.lines[1].y==26);
    assert(draw.lines[2].text=="- Second percentage: after gain." && draw.lines[2].y==39);
    assert(draw.lines[3].text=="Gain note." && draw.lines[3].y==65);
    assert(std::fabs(height-75)<0.001f);
    float measured = para(ctx,&font,10,{},0,text,200,false);
    assert(measured==height && draw.lines.size()==4);
    draw.lines.clear();
    height = para(ctx,&font,10,{},0,"abcd efgh",5);
    assert(draw.lines.size()==2 && draw.lines[0].text=="abcd " && draw.lines[1].text=="efgh");
    assert(std::fabs(height-23)<0.001f);
    draw.lines.clear();
    assert(para(ctx,&font,10,{},0,"",100)==0 && draw.lines.empty());
    // Even a width too small for one glyph advances by a complete UTF-8 character.
    assert(para(ctx,&font,10,{},0,"\xc3\xa9",0)==10);
    assert(draw.lines.size()==1 && draw.lines[0].text=="\xc3\xa9");
}
'''.replace('@PARA@', block(ui, 'inline float para('))
    with tempfile.TemporaryDirectory(prefix='help-paragraphs-') as folder:
        work = Path(folder)
        source = work/'fixture.cpp'
        source.write_text(fixture, encoding='utf-8')
        exe = work/'fixture.exe'
        subprocess.run([args.cxx, '-std=c++17', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print('PASS: explicit lines, blank paragraphs, wrapped text, matching measured height, empty text and UTF-8 fallback')


if __name__ == '__main__':
    main()
