"""Startup playback preference uses the real shared options path, never a second beside-game reader.

Compiles production audio_output_devices.c and options_path.c, with the POSIX shim on Linux. No device is enumerated,
opened or recorded. Each process starts fresh and the only files are synthetic ini files under a temporary directory.
python -I -B tests/test_audio_output_preferences.py [--cc gcc]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]

MAIN = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "options_path.h"
#include "audio_output_devices.h"
void hos_log(const char *fmt, ...) { (void)fmt; }
int main(int argc, char **argv) {
    if (!getenv("TEST_NO_PATH")) hos_options_choose(argc, argv);
    char id[HOS_OUTPUT_ID_CAP] = "not initialized";
    unsigned generation = 0;
    hos_audio_output_preference(id, sizeof id, &generation);
    assert(generation != 0);
    const char *expected = getenv("TEST_EXPECTED_ID");
    assert(expected && !strcmp(id, expected));
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='gcc')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='audio-output-preferences-') as temp:
        temp = Path(temp)
        game, user, relative = temp/'game', temp/'user', temp/'game'/'relative-user'
        for folder in [game, user, relative]:
            folder.mkdir(parents=True, exist_ok=True)
        source = temp/'main.c'
        source.write_text(MAIN, encoding='utf-8')
        executable = game/('fixture.exe' if os.name == 'nt' else 'fixture')
        command = [args.cc, '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-I', str(ROOT/'host')]
        if os.name != 'nt':
            command += ['-I', str(ROOT/'host/posix')]
        command += [str(source), str(ROOT/'host/audio_output_devices.c'), str(ROOT/'host/options_path.c')]
        if os.name == 'nt':
            command += ['-lole32', '-lwinmm']
        else:
            # Match the production POSIX layer, without making its pre-existing warnings part of the fixture contract.
            shim = temp/'posix.o'
            subprocess.run([args.cc, '-std=gnu11', '-I', str(ROOT/'host/posix'), '-c',
                            str(ROOT/'host/posix/win32_posix.c'), '-o', str(shim)], check=True)
            command += [str(shim), '-lpthread', '-ldl']
        subprocess.run(command + ['-o', str(executable)], check=True)
        # Synthetic image marker exercises options_path's relative --user behavior, not game discovery.
        (game/'image.bin').write_text('synthetic fixture marker', encoding='utf-8')
        files = {game/'hookshot_options.ini': 'audio_output_device_id=from-game\n',
                 user/'hookshot_options.ini': 'audio_output_device_id=from-user\n',
                 relative/'hookshot_options.ini': 'audio_output_device_id=from-relative-user\n',
                 temp/'override.ini': 'audio_output_device_id=from-override\n'}
        for path, text in files.items():
            path.write_text(text, encoding='utf-8')
        baseline = {path: path.read_bytes() for path in files}

        def run(expected, *argv, **overrides):
            env = {k: v for k, v in os.environ.items() if k not in
                   ('HOS_OPTIONS_FILE', 'TEST_NO_PATH', 'TEST_EXPECTED_ID')}
            env.update(TEST_EXPECTED_ID=expected, **overrides)
            subprocess.run([str(executable), *map(str, argv)], cwd=temp, env=env, check=True, timeout=30)

        run('from-user', '--user', user)
        run('from-relative-user', '--user', 'relative-user')
        run('from-override', '--user', user, HOS_OPTIONS_FILE=str(temp/'override.ini'))
        run('', '--user', temp/'missing-user')
        run('', '--user', user, HOS_OPTIONS_FILE=str(temp/'missing.ini'))
        run('', '--user', user, HOS_OPTIONS_FILE=str(user))   # Directory: unreadable as an ini file.
        run('', TEST_NO_PATH='1')
        run('from-game')
        for path, original in baseline.items():
            assert path.read_bytes() == original, 'Preference lookup must not modify settings'
        assert not (temp/'missing-user').exists() and not (temp/'missing.ini').exists()
    print('PASS: startup output preference follows --user, relative --user, HOS_OPTIONS_FILE and missing/empty paths')


if __name__ == '__main__':
    main()
