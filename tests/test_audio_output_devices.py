"""Playback selector source contracts and compiled fake-device fixtures. --source-only never invokes a compiler."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "clang", "--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]

def source_contracts():
    menu = (ROOT / 'gpu/vk/vk_menu.cpp').read_text(encoding='utf-8')
    audio = (ROOT / 'host/nn_audio.c').read_text(encoding='utf-8')
    api = (ROOT / 'gpu/vk/vk_api.h').read_text(encoding='utf-8')
    build = (ROOT / 'nx2/build.py').read_text(encoding='utf-8')
    devices = (ROOT / 'host/audio_output_devices.c').read_text(encoding='utf-8')
    assert re.search(r'\{TAB_AUDIO, "Microphone", &opts\.mic,', menu)
    assert 'TAB_GAMEPLAY, "Microphone"' not in menu
    assert re.search(r'\{TAB_AUDIO, "Output device", &output_pick,', menu)
    assert re.search(r'\{TAB_AUDIO, "Speaker layout", &opts\.audio_output,', menu)
    assert 'if (r.value == &opts.audio_output) return "audio_output";' in menu
    tick = menu[menu.index('void menu_tick()'):]
    assert tick.count('refresh_outputs();') == 1, 'Device discovery must not poll on the render-frame path'
    assert 'if (open_now.load()) refresh_outputs();' in tick, 'Refresh on explicit menu opening'
    assert 'r.value != &output_pick' in menu and 'audio_output_device_id=%s' in menu
    assert 'output_forced()' in menu and 'audio_output_device_name' in menu
    assert int(re.search(r'#define MKWVK_API_VERSION (\d+)', api).group(1)) >= 26
    assert api.index('int (*take_text)') < api.index('int (*audio_output_count)')
    backend = (ROOT / 'host/rx_backend.c').read_text(encoding='utf-8')
    check_host_callbacks(api, backend)
    assert '#include "options_path.h"' in devices and 'hos_options_file()' in devices
    assert 'hos_game_path_a' not in devices
    assert re.search(r'\{TAB_AUDIO, "Speaker layout", &opts\.audio_output, 0, 3,', menu)
    assert 'audio_mono(pcm, FRAME, out_channels, rx_option(HOS_OPT_AUDIO_OUTPUT, 0) == 3);' in audio
    assert 'translator_files.stamp(vk)' in build and 'HOOKSHOT_SHADER_STAMP' in build
    assert 'DRV_QUERYFUNCTIONINSTANCEID' in devices and 'calloc(total ? total : 1' in devices
    assert 'waveOutOpen' not in devices and 'SDL_OpenAudio' not in devices
    mixer = audio[audio.index('static DWORD WINAPI renderer_main'):]
    assert mixer.index('output_route_update();') < mixer.index('render_frame(pcm, out_channels);')
    assert mixer.index('render_frame(pcm, out_channels);') < mixer.index('output_frame(pcm);')
    output_frame = audio[audio.index('static void output_frame('):audio.index('/* ---- parameter updates')]
    assert output_frame.index('const int mixed = out_channels;') < output_frame.index('output_open_default();')
    guard = output_frame.index('if (out_channels != mixed) return;')
    assert output_frame.index('output_move("Windows\' default output changed");') < guard < output_frame.index('memcpy(blocks[')
    return menu


def check_host_callbacks(api, backend):
    """Match callback slots, including the two callbacks predating this feature."""
    def code(text):
        return re.sub(r'//[^\n]*', '', re.sub(r'/\*.*?\*/', '', text, flags=re.S))
    body = code(api.split('typedef struct MkwVkHost {', 1)[1].split('} MkwVkHost;', 1)[0])
    fields = [re.search(r'\(\*(\w+)\)', d).group(1) if '(*' in d else d.split()[-1]
              for d in body.split(';') if d.strip()]
    body = code(backend.split('static const MkwVkHost vk_host = {', 1)[1].split('};', 1)[0])
    table = [value.strip() for value in body.split(',') if value.strip()]
    expected = {'take_text': 'host_take_text', 'options_path': 'hos_options_file',
                'audio_output_count': 'hos_audio_output_count', 'audio_output_info': 'hos_audio_output_info',
                'audio_output_select': 'hos_audio_output_select', 'audio_output_state': 'hos_audio_output_state',
                'mic_test': 'hos_mic_test', 'perf_info': 'hos_perf_info',
                'main_thread_times': 'host_main_thread_times', 'out_of_memory': 'host_out_of_memory',
                'monitor_count': 'hos_monitor_count',
                'monitor_info': 'hos_monitor_info', 'monitor_select': 'hos_monitor_select'}
    assert len(fields) == len(table), 'Host interface/initializer lengths differ'
    assert fields[-len(expected):] == list(expected), 'Append monitor callbacks after out-of-memory without shifting earlier callbacks'
    for field, value in expected.items():
        assert table[fields.index(field)] == value, 'Wrong host callback slot: ' + field

PARSER = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stddef.h>
#include "audio_output_devices.h"
#include "gpu/vk/vk_api.h"
_Static_assert(MKWVK_API_VERSION >= 26, "performance info needs a new ABI version");
_Static_assert(MKWVK_API_VERSION == 29, "fullscreen monitor selection extends the out-of-memory ABI");
_Static_assert(offsetof(MkwVkHost, options_path) == offsetof(MkwVkHost, take_text) + sizeof(((MkwVkHost *)0)->take_text),
               "keep the version-23 settings path after text input");
_Static_assert(offsetof(MkwVkHost, audio_output_count) == offsetof(MkwVkHost, options_path) + sizeof(((MkwVkHost *)0)->options_path),
               "append playback after the existing settings path");
_Static_assert(offsetof(MkwVkHost, mic_test) == offsetof(MkwVkHost, audio_output_state) + sizeof(((MkwVkHost *)0)->audio_output_state),
               "append microphone test after playback without shifting earlier callbacks");
_Static_assert(offsetof(MkwVkHost, perf_info) == offsetof(MkwVkHost, mic_test) + sizeof(((MkwVkHost *)0)->mic_test),
               "append performance info after the microphone test without shifting earlier callbacks");
_Static_assert(offsetof(MkwVkHost, main_thread_times) == offsetof(MkwVkHost, perf_info) + sizeof(((MkwVkHost *)0)->perf_info),
               "append the main thread's times after performance info without shifting earlier callbacks");
_Static_assert(offsetof(MkwVkHost, out_of_memory) == offsetof(MkwVkHost, main_thread_times) + sizeof(((MkwVkHost *)0)->main_thread_times),
               "append the renderer's out-of-memory stop after the main thread's times without shifting earlier callbacks");
_Static_assert(offsetof(MkwVkHost, monitor_count) == offsetof(MkwVkHost, out_of_memory) + sizeof(((MkwVkHost *)0)->out_of_memory),
               "append monitor selection without shifting the out-of-memory callback");
_Static_assert(offsetof(MkwVkHost, monitor_info) == offsetof(MkwVkHost, monitor_count) + sizeof(((MkwVkHost *)0)->monitor_count),
               "monitor info slot follows monitor count");
_Static_assert(offsetof(MkwVkHost, monitor_select) == offsetof(MkwVkHost, monitor_info) + sizeof(((MkwVkHost *)0)->monitor_info),
               "monitor select slot follows monitor info");
int main(void) {
    char id[HOS_OUTPUT_ID_CAP] = "old";
    assert(audio_output_copy_id(id, sizeof id, "opaque=id") && !strcmp(id, "opaque=id"));
    assert(!audio_output_copy_id(id, sizeof id, "bad\nsetting=1") && !strcmp(id, "opaque=id"));
    char big[HOS_OUTPUT_ID_CAP+1]; memset(big, 'x', sizeof big-1); big[sizeof big-1]=0;
    assert(!audio_output_copy_id(id, sizeof id, big));
    FILE *f=tmpfile(); assert(f);
    fputs("audio_output=2\nmicrophone=1\naudio_output_device_id=opaque=id\r\n",f);
    rewind(f); audio_output_read_id(f,id,sizeof id); fclose(f); assert(!strcmp(id,"opaque=id"));
    f=tmpfile(); assert(f); fputs("audio_output_device_id=",f);
    for(int i=0;i<9000;i++) fputc('x',f);
    fputs("\nmicrophone=1\n",f); rewind(f); audio_output_read_id(f,id,sizeof id); fclose(f); assert(!*id);
    f=tmpfile(); assert(f); fputs("audio_output_device_id=bad\tvalue\n",f);
    rewind(f); audio_output_read_id(f,id,sizeof id); fclose(f); assert(!*id);
    return 0;
}
'''

MENU = r'''
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "audio_output_devices.h"
#include <cassert>
std::vector<std::pair<std::string,std::string>> names;
std::string selected;
int state;
int count(){return (int)names.size();}
int info(int i,char* id,int ic,char* name,int nc){
    if(i<0 || (size_t)i>=names.size())return 0;
    if(!audio_output_copy_id(id,(size_t)ic,names[i].first.c_str()))return 0;
    snprintf(name,(size_t)nc,"%s",names[i].second.c_str());return 1;
}
void select_output(const char* id){selected=id;}
int status(){return state;}
int64_t now(){return 1000000000;}
struct Host{int(*audio_output_count)();int(*audio_output_info)(int,char*,int,char*,int);void(*audio_output_select)(const char*);int(*audio_output_state)();int64_t(*now_ns)();};
Host h{count,info,select_output,status,now},*host=&h;
namespace i18n { const char* tr(const char* text) { return text; } }
@GLOBALS@
struct Row{int*value;int hi;}; Row rows[]={{&output_pick,0}};
@HELPERS@
int main(){
    for(int i=0;i<80;i++)names.push_back({"id-"+std::to_string(i),i<2?"Duplicate":"Output "+std::to_string(i)});
    refresh_outputs();assert(output_devices.size()==80 && rows[0].hi==80 && output_pick==0);
    assert(std::string(tx_output_device(1))!=std::string(tx_output_device(2)));
    output_pick=24;output_chosen();assert(selected=="id-23" && output_want=="id-23");
    names.erase(names.begin()+23);refresh_outputs();
    assert(output_missing && output_pick==80 && output_want=="id-23");
    assert(std::string(tx_output_device(output_pick)).find("not connected")!=std::string::npos);
    names.push_back({"id-23","Renamed endpoint"});refresh_outputs();
    assert(!output_missing && output_pick==80 && output_saved_name=="Renamed endpoint");
    output_pick=0;output_chosen();assert(selected.empty() && output_want.empty());
    assert(output_id_key("bad\nsetting=1").empty());
    assert(output_id_key("opaque=id\r\n")=="opaque=id");
    assert(output_id_key(std::string(HOS_OUTPUT_ID_CAP,'x').c_str()).empty());
#ifdef _WIN32
    _putenv("HOS_AUDIO_DEVICE=7");
#else
    setenv("HOS_AUDIO_DEVICE","7",1);
#endif
    output_pick=1;output_chosen();assert(selected.empty() && output_want.empty());
    assert(std::string(tx_output_device(1)).find("Overridden")!=std::string::npos);
    return 0;
}
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-only', action='store_true')
    parser.add_argument('--cc', default='clang')
    parser.add_argument('--cxx', default='clang++')
    args = parser.parse_args()
    menu = source_contracts()
    if args.source_only:
        print('PASS: playback/menu source contracts only; native fixtures and runtime remain unverified')
        return
    with tempfile.TemporaryDirectory(prefix='output-devices-') as tmp:
        work = Path(tmp)
        def run(command):
            subprocess.run([str(x) for x in command], cwd=work, check=True)
        header = ROOT / 'host'
        src, exe = work/'parser.c', work/'parser.exe'
        src.write_text(PARSER, encoding='utf-8')
        run([args.cc,'-std=c11','-Wall','-Wextra','-Werror','-I',ROOT,'-I',header,src,'-o',exe]);run([exe])
        globals_text=menu[menu.index('// The playback row stores'):menu.index('constexpr int kMaxMics')]
        helpers=menu[menu.index('void refresh_outputs()'):menu.index('void mic_tell_host()')]
        src,exe=work/'menu.cpp',work/'menu.exe'
        src.write_text(MENU.replace('@GLOBALS@',globals_text).replace('@HELPERS@',helpers),encoding='utf-8')
        run([args.cxx,'-std=c++17','-Wall','-Wextra','-Werror','-I',header,src,'-o',exe]);run([exe])
        if os.name=='nt':
            exe=work/'metadata.exe'
            run([args.cc,'-std=c11','-Wall','-Wextra','-Werror',ROOT/'tests/audio_output_devices_test.c','-lole32','-o',exe]);run([exe])
    print('PASS: playback settings parser, menu selection and applicable metadata fixtures')

if __name__=='__main__':
    main()
