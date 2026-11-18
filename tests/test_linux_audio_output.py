"""Linux playback discovery and stream lifetime, with fake SDL2/SDL3; no hardware or game.

python -I -B tests/test_linux_audio_output.py --cc clang
--source <checkout> --metadata-only also runs against pre-fix main: its empty Linux list fails at runtime.
The full fixture compiles the production SDL sound section and POSIX waveOut section via srccut.
Thread synchronization is modeled, not stress-tested; real PipeWire/PulseAudio/ALSA playback remains a host test.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "clang"]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from srccut import between

PREFIX = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <limits.h>
#include <string.h>
#undef _WIN32
#include "audio_output_devices.h"
typedef int SRWLOCK;
#define SRWLOCK_INIT 0
static void AcquireSRWLockExclusive(SRWLOCK *p) { assert(!*p); *p=1; }
static void ReleaseSRWLockExclusive(SRWLOCK *p) { assert(*p); *p=0; }
#define AcquireSRWLockShared AcquireSRWLockExclusive
#define ReleaseSRWLockShared ReleaseSRWLockExclusive
static const char *hos_options_file(void) { return NULL; }
extern int hos_sdl_output_count(void) __attribute__((weak));
extern int hos_sdl_output_info(int, char *, int, char *, int) __attribute__((weak));
extern int hos_sdl_output_resolve(const char *) __attribute__((weak));
'''

METADATA = r'''
int hos_sdl_output_count(void) { return 2; }
int hos_sdl_output_info(int i, char *id, int cap, char *name, int ncap) {
    if (i < 0 || i > 1) return 0;
    snprintf(id,cap,"sdl:pipewire:%s",i ? "Headphones" : "Speakers");
    snprintf(name,ncap,"%s",i ? "Headphones" : "Speakers");
    return 1;
}
int hos_sdl_output_resolve(const char *id) { return !strcmp(id,"sdl:pipewire:Headphones") ? 7 : -1; }
int main(void) {
    int count=hos_audio_output_count();
    printf("Linux playback count: %d (expected 2)\n",count); fflush(stdout);
    assert(count==2);
    char id[2048], name[1024], small[2];
    assert(hos_audio_output_info(1,id,sizeof id,name,sizeof name));
    assert(!strcmp(name,"Headphones") && !strcmp(id,"sdl:pipewire:Headphones"));
    assert(!hos_audio_output_info(2,id,sizeof id,name,sizeof name));
    assert(!hos_audio_output_info(1,small,sizeof small,name,sizeof name));
    assert(hos_audio_output_resolve("sdl:pipewire:Headphones")==7);
    assert(hos_audio_output_resolve("missing")==-1);
    puts("PASS Linux metadata bridge");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='clang')
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--metadata-only', action='store_true')
    args = parser.parse_args()
    devices = (args.source/'host/audio_output_devices.c').read_text(encoding='utf-8')
    devices = devices[devices.index('typedef struct { char *id, *name; } OutputDevice;'):]
    fixtures = [('metadata', PREFIX + devices + METADATA)]
    if not args.metadata_only:
        sdl = (args.source/'host/hos_sdl.c').read_text(encoding='utf-8')
        sound = between(sdl, '/* ---- sound ---- */', '/* ---- (hookshot) microphones:')
        posix = (args.source/'host/posix/win32_posix.c').read_text(encoding='utf-8')
        wave = posix[posix.index('/* ---- waveOut on SDL\'s audio'):]
        # The real files are separate translation units. Keep weak declarations before definitions in this combined fixture.
        split = wave.index('typedef struct {')
        sound = wave[:split] + sound
        wave = wave[split:]
        # GCC knows the weak functions are defined in this combined fixture (the real files are separate TUs).
        # Suppress only that fixture artifact, keeping every other -Wall/-Wextra warning an error.
        wave = ('#if defined(__GNUC__) && !defined(__clang__)\n'
                '#pragma GCC diagnostic push\n#pragma GCC diagnostic ignored "-Waddress"\n#endif\n' + wave +
                '\n#if defined(__GNUC__) && !defined(__clang__)\n#pragma GCC diagnostic pop\n#endif\n')
        # waveOut is the final section; any later source addition must explicitly delimit this fixture.
        fake = (ROOT/'tests/linux_audio_output_test.c').read_text(encoding='utf-8')
        assert fake.count('/* PRODUCTION_SOUND */') == 1
        assert fake.count('/* PRODUCTION_WAVE */') == 1
        fixture = PREFIX + devices + fake.replace('/* PRODUCTION_SOUND */', sound).replace('/* PRODUCTION_WAVE */', wave)
        fixtures.append(('sdl', fixture))
    with tempfile.TemporaryDirectory(prefix='linux-audio-output-') as temporary:
        folder = Path(temporary)
        for name, text in fixtures:
            c = folder/(name+'.c')
            exe = folder/(name+('.exe' if sys.platform=='win32' else ''))
            c.write_text(text, encoding='utf-8')
            command = [args.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(ROOT/'host'), str(c), '-o', str(exe)]
            subprocess.run(command, check=True, timeout=90)
            for version in (('2', '3') if name=='sdl' else ('metadata',)):
                subprocess.run([str(exe), version], check=True, timeout=20)
    return 0


if __name__ == '__main__':
    sys.exit(main())
