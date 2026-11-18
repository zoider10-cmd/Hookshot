#!/usr/bin/env python3
"""Render the maintained menu without a game, Vulkan device, window or private assets.
Linux capture helper; optional SDL2/libpng/C++/Vulkan-header dependencies are not used
by documentation builds. See docs/images/guide/README.md for the capture contract.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT, help='Hookshot checkout whose maintained menu to render')
    parser.add_argument('--vulkan-headers', type=Path, default=Path('/usr/include'), help='include directory containing vulkan/vulkan.h')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cxx', default='clang++')
    parser.add_argument('--views', nargs='+', choices=['graphics', 'graphics-screen', 'audio', 'controls'],
                        default=['graphics', 'audio', 'controls'], help='maintained views to capture; graphics-screen selects Fullscreen')
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if not (args.vulkan_headers / 'vulkan/vulkan.h').is_file():
        parser.error('--vulkan-headers must contain vulkan/vulkan.h (headers only; no Vulkan SDK runtime needed)')
    output.mkdir(parents=True, exist_ok=True)
    revision = run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True).stdout.strip()
    describe = run(['git', '-C', str(source), 'describe', '--tags', '--always'], capture_output=True).stdout.strip()
    flags = shlex.split(run(['pkg-config', '--cflags', '--libs', 'sdl2', 'libpng'], capture_output=True).stdout)
    with tempfile.TemporaryDirectory(prefix='hookshot-menu-capture-') as tmp:
        exe = Path(tmp) / 'menu-capture'
        command = [args.cxx, '-std=c++20', '-O1', '-ffunction-sections', '-fdata-sections',
                   '-Wno-deprecated-enum-enum-conversion', '-Wno-deprecated-enum-float-conversion',
                   '-DVK_NO_PROTOTYPES', '-DIMGUI_DISABLE_DEFAULT_SHELL_FUNCTIONS',
                   '-DHOOKSHOT_VERSION="' + describe + ' (UI fixture)"',
                   '-I' + str(source), '-I' + str(source / 'host/posix'), '-I' + str(source / 'gpu/vk/compat'),
                   '-I' + str(source / 'third_party/imgui'), '-I' + str(args.vulkan_headers.resolve()),
                   str(Path(__file__).with_name('menu.cpp')), str(source / 'gpu/vk/vk_menu_i18n.cpp')]
        command += [str(source / 'third_party/imgui' / p) for p in ['imgui.cpp', 'imgui_draw.cpp', 'imgui_widgets.cpp', 'imgui_tables.cpp']]
        # Ask the compiler which repository files this translation unit actually uses.
        # System dependencies are described by their toolchain versions below.
        dep_text = run(command + flags + ['-MM', '-MT', 'capture'], capture_output=True).stdout
        dependencies = shlex.split(dep_text.replace('\\\n', ' '))
        fixture_cpp = Path(__file__).with_name('menu.cpp').resolve()
        sources = set()
        for token in dependencies:
            if token == 'capture:':
                continue
            dep = Path(token).resolve()
            if dep != fixture_cpp and dep.is_relative_to(source):
                sources.add(dep.relative_to(source).as_posix())
        sources.update(p.relative_to(source).as_posix()
                       for p in (source / 'third_party/fonts/libertinus').iterdir() if p.is_file())
        tracked = set(run(['git', '-C', str(source), 'ls-files', '-z'], capture_output=True).stdout.split('\0'))
        if sources - tracked:
            parser.error('capture inputs must be tracked source files: ' + ', '.join(sorted(sources - tracked)))
        dirty = run(['git', '-C', str(source), 'diff', '--name-only', 'HEAD', '--', *sorted(sources)], capture_output=True).stdout
        if dirty:
            parser.error('capture inputs differ from the named source revision; commit them or use a clean checkout:\n' + dirty)
        hashes = {p: hashlib.sha256((source / p).read_bytes()).hexdigest() for p in sorted(sources)}
        command += flags + ['-Wl,--gc-sections', '-o', str(exe)]
        run(command)
        # No ambient game settings or display modes affect the fixture. A temporary cwd
        # also prevents accidentally reading files in the checkout or game installation.
        env = {k: v for k, v in os.environ.items() if not k.startswith(('HOS_', 'RX_', 'HOOKSHOT_'))}
        env['HOS_DISPLAY_MODES'] = '1280x720'
        for view in dict.fromkeys(args.views):
            run([str(exe), str(source / 'third_party/fonts/libertinus'), view, str(output / f'settings-{view}.png')], cwd=tmp, env=env)
    metadata = {'source_revision': revision, 'source_version': describe, 'source_files': hashes,
                'fixture_files': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                  for p in ['scripts/screenshots/menu.cpp', 'scripts/screenshots/capture_menu.py']},
                'width': 1280, 'height': 720, 'menu_size': 'Medium', 'language': 'English',
                'background': 'Solid RGB 16,18,21; no scene', 'backend': 'SDL2 software renderer',
                'state': 'Explicit 16:9; compiled Options defaults; no GPU SDK capabilities; no saved options; no game',
                'toolchain': {'compiler': run([args.cxx, '--version'], capture_output=True).stdout.splitlines()[0],
                              'sdl2': run(['pkg-config', '--modversion', 'sdl2'], capture_output=True).stdout.strip(),
                              'libpng': run(['pkg-config', '--modversion', 'libpng'], capture_output=True).stdout.strip()},
                'views': list(dict.fromkeys(args.views)),
                'images': {f'settings-{view}.png': hashlib.sha256((output / f'settings-{view}.png').read_bytes()).hexdigest()
                           for view in dict.fromkeys(args.views)}}
    (output / 'menu-capture.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    print('Captured ' + ', '.join(dict.fromkeys(args.views)) + ' from ' + describe + ' @ ' + revision)


if __name__ == '__main__':
    main()
