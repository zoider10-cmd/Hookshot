"""Native microphone test/gain lifecycle and sample-processing checks, with fake SDL/clock.

No hardware capture, game, GPU, or installation. Also compile the actual menu lifetime helper.
python -I -B tests/test_microphone_test_gain.py --cc clang --cxx clang++
"""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from srccut import block, between

ROOT = Path(__file__).resolve().parents[1]
RUN_ALL_ARGS = ['--cc', 'clang', '--cxx', '{cxx}']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--cxx', default='g++')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('audio_fixture', ROOT/'tests/test_audio_in.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    api = (ROOT/'gpu/vk/vk_api.h').read_text(encoding='utf-8')
    backend = (ROOT/'host/rx_backend.c').read_text(encoding='utf-8')
    menu = (ROOT/'gpu/vk/vk_menu.cpp').read_text(encoding='utf-8')
    header = (ROOT/'gpu/vk/vk_menu.h').read_text(encoding='utf-8')
    assert int(re.search(r'#define MKWVK_API_VERSION (\d+)', api).group(1)) >= 25   # (25: the microphone test; later versions append)
    assert api.index('int (*take_text)') < api.index('int (*audio_output_state)') < api.index('int (*mic_test)')
    initializer = block(backend, 'static const MkwVkHost vk_host =')
    assert initializer.index('host_take_text,') < initializer.index('hos_audio_output_state,') < initializer.index('hos_mic_test,')
    assert 'int microphone_gain = 100;' in header
    for row in ('Microphone gain', 'Test microphone'):
        assert '{TAB_AUDIO, "'+row+'"' in menu
    assert '{TAB_AUDIO, "Microphone level"' not in menu
    assert 'mic_tick{mine}' in menu and '~MicTick() { mic_test_tick(focused); }' in menu
    assert 'mic_testing = !mic_testing;' in menu
    # The meter must never register slider hit bounds: it has no editable row value.
    meter = block(menu, 'void mic_help_meter(ui::Ctx& c, ImVec2 a, ImVec2 b) {')
    assert 'false, &unused0, &unused1, false)' in meter
    assert 'hits.' not in meter
    slider = block(menu, 'void slider_cell(')
    assert 'ui::triangle' in block(slider, 'if (adjustable)')
    assert '*t0 = adjustable ? x0 : 0, *t1 = adjustable ? x1 : 0;' in slider
    assert 'mic_help_meter(c,' in block(menu, 'void help_box(')
    assert 'mic_testing' not in block(menu, 'void save()')
    assert 'mic_testing' not in block(menu, 'void menu_init()')
    # Gain uses the ordinary persisted row path; the test itself is session-only.
    assert '&opts.microphone_gain, 0, 400, 10, tx_percent' in menu
    assert 'saved_value(r.value)' in block(menu, 'void save()')

    with tempfile.TemporaryDirectory(prefix='mic-test-gain-') as folder:
        work = Path(folder)
        for name, text in (('hos.h', helper.HOS_H), ('windows.h', helper.WINDOWS_H),
                           ('hos_sdl.h', (ROOT/'host/hos_sdl.h').read_text(encoding='utf-8')),
                           ('nn_audio_in.c', (ROOT/'host/nn_audio_in.c').read_text(encoding='utf-8'))):
            (work/name).write_text(text, encoding='utf-8')
        fixture = between(helper.FIXTURE, '#include <stdarg.h>', 'int main(void) {')
        fixture += (ROOT/'tests/microphone_test_gain_test.c').read_text(encoding='utf-8')
        (work/'fixture.c').write_text(fixture, encoding='utf-8')
        exe = work/('fixture.exe' if os.name == 'nt' else 'fixture')
        subprocess.run([args.cc, '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-include', helper.ENV_ON_H,
                        '-I', str(work), str(work/'fixture.c'), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)

        # Exercise the actual SDL2 ring callback/read and SDL3 read wrapper, without loading SDL.
        sdl = (ROOT/'host/hos_sdl.c').read_text(encoding='utf-8')
        mic_type = between(sdl, 'typedef struct {\n    uint32_t dev;', 'static void mic2_push(')
        adapter = r'''
#include <stdint.h>
#include <string.h>
#include <assert.h>
static int version, lock_calls, unlock_calls;
static struct { int ok; void *GetData, *LockDevice, *UnlockDevice; } rec;
static void take_lock(uint32_t dev) { (void)dev; lock_calls++; }
static void release_lock(uint32_t dev) { (void)dev; unlock_calls++; }
static int read_three(void *mic, void *dst, int count) {
    (void)mic;
    int16_t sample = 1234;
    if (count < 2) return -1;
    memcpy(dst, &sample, 2); return 2;
}
@TYPE@
@PUSH@
@LOCK@
@READ@
int main(void) {
    rec.ok = 1; rec.LockDevice = (void *)take_lock; rec.UnlockDevice = (void *)release_lock;
    uint8_t ring[8] = {}, in[12] = {0,1,2,3,4,5,6,7,8,9,10,11}, out[8] = {};
    Mic2 mic = {1, ring, sizeof ring, 0, 0}; version = 2;
    mic2_push(&mic, in, 6);
    assert(hos_sdl_mic_read(&mic, out, 4) == 4 && !memcmp(out, in, 4));
    mic2_push(&mic, in + 6, 6); // wrap; only the newest eight bytes remain
    assert(hos_sdl_mic_read(&mic, out, 8) == 8 && !memcmp(out, in + 4, 8));
    assert(lock_calls == 2 && unlock_calls == 2);
    version = 3; rec.GetData = (void *)read_three;
    int16_t sample = 0;
    assert(hos_sdl_mic_read(&mic, &sample, 2) == 2 && sample == 1234);
    assert(hos_sdl_mic_read(&mic, &sample, 1) == 0); // SDL3 read error becomes no samples
    assert(hos_sdl_mic_read(0, &sample, 2) == 0);
}
'''
        for marker, value in (('@TYPE@', mic_type), ('@PUSH@', block(sdl, 'static void mic2_push(')),
                              ('@LOCK@', block(sdl, 'static void mic2_lock(')),
                              ('@READ@', block(sdl, 'int hos_sdl_mic_read('))):
            adapter = adapter.replace(marker, value)
        (work/'adapter.c').write_text(adapter, encoding='utf-8')
        exe = work/('adapter.exe' if os.name == 'nt' else 'adapter')
        subprocess.run([args.cc, '-std=gnu11', '-Wall', '-Wextra', '-Werror', str(work/'adapter.c'), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)

        # Compile the real post-navigation helper and exercise all lifetime exits.
        cpp = r'''
#include <atomic>
#include <cassert>
bool mic_testing = false;
int mic_levels[2] = {}, mic_test_state = 0;
std::atomic<bool> open_now{true};
constexpr int TAB_AUDIO = 1;
int cur_tab = TAB_AUDIO, page = 0, calls, enabled_seen, gain_seen;
struct { int mic = 1, microphone_gain = 100; } opts;
int fake_test(int on, int gain, int *levels) {
    calls++; enabled_seen = on; gain_seen = gain;
    levels[0] = on ? 100 : 0; levels[1] = on ? 200 : 0;
    return on ? 11 : 0;
}
struct Host { int (*mic_test)(int,int,int*); } host_value{fake_test}, *host = &host_value;
@HELPER@
int main() {
    mic_test_tick(true); assert(!enabled_seen); // entering Audio alone never starts capture
    mic_testing = true; opts.microphone_gain = 200;
    mic_test_tick(true); assert(enabled_seen && gain_seen == 200 && mic_levels[1] == 200);
    mic_test_tick(false); assert(!mic_testing && !enabled_seen && !mic_levels[1]);
    mic_testing = true; open_now = false; mic_test_tick(true); assert(!mic_testing && !enabled_seen);
    open_now = true; mic_testing = true; cur_tab = 0; mic_test_tick(true); assert(!mic_testing && !enabled_seen);
    cur_tab = TAB_AUDIO; mic_testing = true; page = 1; mic_test_tick(true); assert(!mic_testing && !enabled_seen);
    page = 0; mic_testing = true; opts.mic = 0; mic_test_tick(true); assert(!mic_testing && !enabled_seen);
    opts.mic = 1; mic_test_tick(true); assert(!mic_testing); // restoring a device does not restart a test
    host = nullptr; mic_testing = true; mic_test_tick(true); assert(!mic_testing && !mic_test_state);
}
'''.replace('@HELPER@', block(menu, 'void mic_test_tick(bool focused)'))
        (work/'menu.cpp').write_text(cpp, encoding='utf-8')
        exe = work/('menu.exe' if os.name == 'nt' else 'menu')
        subprocess.run([args.cxx, '-std=c++17', '-Wall', '-Wextra', '-Werror', str(work/'menu.cpp'), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print('PASS: SDL2 ring/locking, SDL3 reads/errors, menu start/stop/exit paths, persistence and ABI wiring')


if __name__ == '__main__':
    main()
