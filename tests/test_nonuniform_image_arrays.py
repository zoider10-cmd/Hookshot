"""Storage image, image buffer and texture buffer arrays are indexed nonuniformly where the GPU can, as texture arrays are,
without game files or a GPU.

The renderer's profile (make_profile, gpu/vk/vk_shader.cpp) tells the translator which kinds of descriptor array the GPU
indexes nonuniformly: it decorates such an array's index, element and texel pointer NonUniform and declares the kind's
capability. make_profile, storage_binding_align (vk_internal.h) and translator_stamp's nonuniform word are cut out of the
tree into tests/nonuniform_image_arrays_ir.cpp, which takes the profile of five GPUs (none of the three features
shaderStorageImageArrayNonUniformIndexing, shaderUniformTexelBufferArrayNonUniformIndexing and
shaderStorageTexelBufferArrayNonUniformIndexing, each alone, all three) and translates 13 synthetic compute programs with
each: image buffer, storage image, texture buffer and texture arrays (read and written, added to atomically, fetched; one
program with all four) and the same programs with single descriptors, through the real texture pass and SPIR-V back end.

Every module must translate and pass spirv-val (Vulkan 1.3). An array of a kind the GPU indexes nonuniformly (textures:
always) must have NonUniform on its access chains and atomic texel pointers and the kind's capability; any other array none
of them, and a module without such an array no NonUniform at all. translator_stamp must add nothing for a GPU with all three
features and a word of its own for each GPU without one. The device must be created with the features it reports
(vk_main.cpp).

python -I -B tests/test_nonuniform_image_arrays.py --headers <SPIRV-Headers/include> --spirv-val spirv-val [--cxx clang++]
    [--tree <a checkout>] [--base-tree <a checkout>] [--keep <folder>] [--jobs N]
--tree tests another checkout (main's, or its parent's: the test fails there). --base-tree builds the fixture against that
checkout too and requires every module whose program has no array of a kind the GPU's features turn on to be byte for byte
the same: on a GPU with none of the features, every module. --keep copies the modules; --jobs limits the compilers.
Builds the same Eden IR/SPIR-V and Sirit sources as the renderer, with its compatibility headers.
"""
# SPDX-License-Identifier: GPL-3.0-or-later
import argparse
import concurrent.futures
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{spirv_headers}", "--spirv-val", "{spirv_val}"]
# (spirv-val: SPIRV-Tools comes with the Linux runner's packages, not on Windows)
RUN_ALL_SKIP = {"windows": "needs spirv-val: checked on Linux"}

ROOT = Path(__file__).resolve().parents[1]
KINDS = ('texbuf', 'imgbuf', 'tex', 'img')   # (Eden's binding order: texture buffers, image buffers, textures, images)
# The kinds each GPU of the fixture indexes nonuniformly by its features (textures always: make_profile)
DEVICES = {
    'none': set(),
    'storage-image': {'img'},
    'uniform-texel-buffer': {'texbuf'},
    'storage-texel-buffer': {'imgbuf'},
    'all': {'img', 'texbuf', 'imgbuf'},
}
# The kinds of descriptor array (count above 1) each program has
PROGRAMS = {
    'imgbuf-1': set(), 'img-1': set(), 'texbuf-1': set(), 'imgbuf-atomic-1': set(), 'img-atomic-1': set(), 'mixed-1': set(),
    'tex-2': {'tex'}, 'imgbuf-2': {'imgbuf'}, 'img-3': {'img'}, 'texbuf-2': {'texbuf'}, 'imgbuf-atomic-2': {'imgbuf'},
    'img-atomic-3': {'img'}, 'mixed': {'texbuf', 'imgbuf', 'tex', 'img'},
}
# (each kind's capability for nonuniform indexing: its number and name)
CAPABILITY = {'texbuf': (5311, 'UniformTexelBufferArrayNonUniformIndexing'),
              'imgbuf': (5312, 'StorageTexelBufferArrayNonUniformIndexing'),
              'tex': (5307, 'SampledImageArrayNonUniformIndexing'), 'img': (5309, 'StorageImageArrayNonUniformIndexing')}
OP_CAPABILITY, OP_TYPE_IMAGE, OP_TYPE_SAMPLED_IMAGE, OP_TYPE_ARRAY = 17, 25, 27, 28
OP_TYPE_POINTER, OP_CONSTANT, OP_VARIABLE, OP_IMAGE_TEXEL_POINTER, OP_ACCESS_CHAIN, OP_DECORATE = 32, 43, 59, 60, 65, 71
DIM_BUFFER, UNIFORM_CONSTANT, DECORATION_BINDING, DECORATION_NON_UNIFORM = 5, 0, 33, 5300
# (what translator_stamp adds for the nonuniform features, cut out of it: from its comment to the next one's)
STAMP_START, STAMP_END = '    // (and which descriptor arrays the GPU indexes nonuniformly', '    // (RX_VK_GP_, not RX_VK_GP'


def section(text, start, end, what):
    if start not in text:
        raise SystemExit('FAIL: %s: no %r' % (what, start))
    first = text.index(start)
    return text[first:text.index(end, first)]


def profile_cut(tree):
    """nonuniform_profile.inc for tree: its storage_binding_align, make_profile and translator_stamp's nonuniform word (empty,
    STAMP_SECTION 0, where it has none)"""
    vk = tree / 'gpu/vk'
    shader = (vk / 'vk_shader.cpp').read_text(encoding='utf-8')
    internal = (vk / 'vk_internal.h').read_text(encoding='utf-8')
    stamp = section(shader, 'uint64_t translator_stamp() {', '    return h;\n}', 'vk_shader.cpp translator_stamp')
    word = section(stamp, STAMP_START, STAMP_END, 'translator_stamp') if STAMP_START in stamp else ''
    return ('// (cut out of %s by tests/test_nonuniform_image_arrays.py)\n' % tree
            + section(internal, 'inline uint64_t storage_binding_align()', '/// A range of guest memory', 'vk_internal.h')
            + section(shader, 'Shader::Profile make_profile(', 'Shader::HostTranslateInfo host_info()', 'vk_shader.cpp')
            + 'const Shader::Profile* current_profile = nullptr;\n'
            + 'const Shader::Profile& profile() { return *current_profile; }\n'
            + '#define STAMP_SECTION %d\n' % bool(word)
            + 'template <class Add> void stamp_section(Add&& add) {\n    (void)add;\n' + word + '}\n')


def build_fixture(cxx, flags, sources, exe, jobs):
    """One object a source, jobs at once, then linked"""
    (exe.parent / 'obj').mkdir()
    objs = [exe.parent / 'obj' / ('%03d.o' % i) for i in range(len(sources))]
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        list(pool.map(lambda job: subprocess.run([cxx, *flags, '-c', str(job[0]), '-o', str(job[1])], check=True),
                      zip(sources, objs)))
    subprocess.run([cxx, *map(str, objs), '-o', str(exe)], check=True)


def emit(args, tree, folder):
    """The fixture built against tree's profile and back end and run into folder:
    ({'device.program': words or 'refused: ...'}, {device: stamp words})"""
    vk = tree / 'gpu/vk'
    cut = folder / 'cut'
    cut.mkdir()
    (cut / 'nonuniform_profile.inc').write_text(profile_cut(tree), encoding='utf-8')
    sources = sorted({p for directory in ('eden/shader_recompiler/backend/spirv',
                      'eden/shader_recompiler/frontend/ir', 'eden/shader_recompiler/ir_opt', 'sirit/src')
                      for p in (vk / directory).rglob('*.cpp')})
    flags = ['-std=c++20', '-include', str(vk / 'compat' / 'hookshot_env.h'), '-O1', '-D_CRT_SECURE_NO_WARNINGS',
             '-DVK_NO_PROTOTYPES', '-DMKWVK_INCLUDES=2']
    for header in ('algorithm', 'cstdio', 'cstdlib', 'cstring', 'functional', 'string', 'vector'):
        flags += ['-include', header]
    flags += ['-I' + str(p) for p in (cut, vk / 'compat', tree / 'gpu/compat', vk / 'eden',
              tree / 'gpu/third_party/suyu', vk / 'sirit/include', vk / 'sirit/src', args.headers)]
    exe = folder / 'fixture.exe'
    build_fixture(args.cxx, flags, [ROOT / 'tests/nonuniform_image_arrays_ir.cpp', *sources], exe, args.jobs)
    modules = folder / 'modules'
    env = {k: v for k, v in os.environ.items() if not k.startswith('RX_VK_')}   # (make_profile's test switches unset)
    run = subprocess.run([str(exe), str(modules)], check=True, capture_output=True, text=True, env=env)
    cases, stamps = {}, {}
    for line in run.stdout.splitlines():
        if line.startswith('stamp '):
            _, device, words = line.split(' ', 2)
            stamps[device] = words
            continue
        name, rest = line.split(' ', 1)
        cases[name] = rest if rest.startswith('refused: ') else int(rest)
    return modules, cases, stamps


def parse(path):
    """The module's capabilities, its ids decorated NonUniform, its descriptor arrays of images ({variable: (kind, count)},
    UniformConstant variables with a binding), its access chains ({result: base}) and its texel pointers ({result: image})"""
    data = path.read_bytes()
    words = struct.unpack('<%dI' % (len(data) // 4), data)
    images, sampled, arrays, constants, pointers, variables, bindings = {}, set(), {}, {}, {}, {}, set()
    capabilities, non_uniform, chains, texel_pointers = set(), set(), {}, {}
    i = 5
    while i < len(words):
        count, op = words[i] >> 16, words[i] & 0xFFFF
        operands = words[i + 1:i + count]
        if op == OP_CAPABILITY:
            capabilities.add(operands[0])
        elif op == OP_TYPE_IMAGE:
            images[operands[0]] = (operands[2], operands[6])   # (dim, sampled: 1 sampled, 2 storage)
        elif op == OP_TYPE_SAMPLED_IMAGE:
            sampled.add(operands[0])
        elif op == OP_TYPE_ARRAY:
            arrays[operands[0]] = (operands[1], operands[2])
        elif op == OP_CONSTANT:
            constants[operands[1]] = operands[2]
        elif op == OP_TYPE_POINTER:
            pointers[operands[0]] = (operands[1], operands[2])
        elif op == OP_VARIABLE:
            variables[operands[1]] = (operands[0], operands[2])
        elif op == OP_ACCESS_CHAIN:
            chains[operands[1]] = operands[2]
        elif op == OP_IMAGE_TEXEL_POINTER:
            texel_pointers[operands[1]] = operands[2]
        elif op == OP_DECORATE and operands[1] == DECORATION_BINDING:
            bindings.add(operands[0])
        elif op == OP_DECORATE and operands[1] == DECORATION_NON_UNIFORM:
            non_uniform.add(operands[0])
        i += count
    descriptors = {}
    for variable in (v for v in variables if v in bindings):
        pointer, storage = variables[variable]
        if storage != UNIFORM_CONSTANT:
            continue
        element, count = pointers[pointer][1], 1
        if element in arrays:
            element, count = arrays[element][0], constants[arrays[element][1]]
        if element in sampled:
            kind = 'tex'
        else:
            dim, use = images[element]
            kind = ('texbuf' if use == 1 else 'imgbuf') if dim == DIM_BUFFER else 'img'
        descriptors[variable] = (kind, count)
    return capabilities, non_uniform, descriptors, chains, texel_pointers


def check_module(args, name, module):
    """What is wrong with one module, as lines"""
    device, program = name.split('.', 1)
    failures = []
    valid = subprocess.run([args.spirv_val, '--target-env', 'vulkan1.3', str(module)], capture_output=True, text=True)
    if valid.returncode:
        said = (valid.stdout + valid.stderr).strip().splitlines() or ['exit %d' % valid.returncode]
        failures.append('%s: spirv-val: %s' % (name, said[0]))
    capabilities, non_uniform, descriptors, chains, texel_pointers = parse(module)
    made = {kind for kind, count in descriptors.values() if count > 1}
    if made != PROGRAMS[program]:
        failures.append('%s: arrays of %s declared, not of %s' % (name, sorted(made), sorted(PROGRAMS[program])))
    wanted = PROGRAMS[program] & (DEVICES[device] | {'tex'})   # (the arrays the GPU indexes nonuniformly)
    for variable, (kind, count) in sorted(descriptors.items()):
        reached = sorted(chain for chain, base in chains.items() if base == variable)
        if count > 1 and not reached:
            failures.append('%s: the %s array is never indexed' % (name, kind))
        texels = sorted(texel for texel, image in texel_pointers.items() if image in reached or image == variable)
        decorated = count > 1 and kind in wanted   # (a single descriptor takes no index: never NonUniform)
        for what, ids in (('access chains', reached), ('atomic texel pointers', texels)):
            wrong = [i for i in ids if (i in non_uniform) != decorated]
            if wrong:
                failures.append('%s: %d of %d %s of the %s %s NonUniform' % (
                    name, len(wrong), len(ids), what, kind + ' array' if count > 1 else 'single ' + kind,
                    'without' if decorated else 'with'))
    for kind in KINDS:
        number, capability = CAPABILITY[kind]
        if (number in capabilities) != (kind in wanted):
            failures.append('%s: %s' % (name, 'no ' + capability if kind in wanted
                                        else capability + ' without such an array indexed nonuniformly'))
    if not wanted and non_uniform:
        failures.append('%s: NonUniform decorations without an array indexed nonuniformly' % name)
    return failures


def check_stamps(stamps):
    """What is wrong with translator_stamp's nonuniform word, as lines"""
    if sorted(stamps) != sorted(DEVICES):
        return ['the fixture printed the stamps of %s, not of %s' % (sorted(stamps), sorted(DEVICES))]
    if 'missing' in stamps.values():
        return ['translator_stamp has no nonuniform word (%r): a program made for a GPU with the features is kept for '
                'one without them' % STAMP_START.strip()]
    failures = []
    if stamps['all'] != '-':
        failures.append('translator_stamp adds %s for a GPU with all three features: their caches start over' % stamps['all'])
    for device, words in stamps.items():
        if device != 'all' and words == '-':
            failures.append('translator_stamp adds nothing for the GPU %s: it shares the cache of one with all three' % device)
    if len(set(stamps.values())) != len(stamps):
        failures.append('translator_stamp adds the same for two GPUs: %s' % stamps)
    return failures


def check_device(tree):
    """What is wrong with the device's features, as lines: Vulkan 1.2's are queried into the chain vkCreateDevice takes, the
    three are not switched off, and dev.vk12 (make_profile's) is what was queried"""
    main = (tree / 'gpu/vk/vk_main.cpp').read_text(encoding='utf-8')
    device = section(main, 'bool create_device() {', 'vkCreateDevice(dev.physical, &ci', 'vk_main.cpp create_device')
    failures = []
    for text in ('f.pNext = &f11, f11.pNext = &f12', 'vkGetPhysicalDeviceFeatures2(dev.physical, &f);', 'dev.vk12 = f12;',
                 'ci.pNext = &f;'):
        if text not in device:
            failures.append('create_device: no %r before vkCreateDevice' % text)
    if re.search(r'\.shader(StorageImage|UniformTexelBuffer|StorageTexelBuffer)ArrayNonUniformIndexing\s*=[^=]', main):
        failures.append('vk_main.cpp switches a nonuniform indexing feature off')
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='clang++')
    parser.add_argument('--headers', type=Path, required=True)
    parser.add_argument('--spirv-val', default='spirv-val')
    parser.add_argument('--tree', type=Path, default=ROOT, help='the checkout whose profile and back end are tested')
    parser.add_argument('--base-tree', type=Path, help='a checkout whose modules must be the same where no feature applies')
    parser.add_argument('--keep', type=Path, help='a folder to copy the modules to')
    parser.add_argument('--jobs', type=int, default=os.cpu_count() or 2, help='compilers at once')
    args = parser.parse_args()
    tree = args.tree.resolve()
    with tempfile.TemporaryDirectory(prefix='nonuniform-arrays-') as temp:
        folder = Path(temp).resolve()
        (folder / 'tree').mkdir()
        modules, cases, stamps = emit(args, tree, folder / 'tree')
        if args.keep:
            shutil.copytree(modules, args.keep, dirs_exist_ok=True)
        expected = sorted('%s.%s' % (d, p) for d in DEVICES for p in PROGRAMS)
        failures = [] if sorted(cases) == expected else ['%d cases, not %d: %s' % (len(cases), len(expected), sorted(cases))]
        translated = sorted(name for name, words in cases.items() if isinstance(words, int))
        failures += ['%s: translation %s' % (name, words) for name, words in sorted(cases.items()) if isinstance(words, str)]
        with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
            for lines in pool.map(lambda name: check_module(args, name, modules / (name + '.spv')), translated):
                failures += lines
        failures += check_stamps(stamps) + check_device(tree)
        same = []
        if args.base_tree:
            (folder / 'base').mkdir()
            base_modules, base_cases, _ = emit(args, args.base_tree.resolve(), folder / 'base')
            for name in expected:
                device, program = name.split('.', 1)
                if PROGRAMS[program] & DEVICES[device]:
                    continue
                ours, theirs = modules / (name + '.spv'), base_modules / (name + '.spv')
                if ours.exists() and theirs.exists() and ours.read_bytes() == theirs.read_bytes():
                    same.append(name)
                else:
                    failures.append('%s: not byte for byte the base tree\'s module (%s)' % (
                        name, base_cases.get(name, 'not made') if not theirs.exists() else 'differs'))
    for device in DEVICES:
        print('stamp %s: %s' % (device, stamps.get(device)))
    if failures:
        for failure in failures:
            print('FAIL: ' + failure)
        raise SystemExit(1)
    print('PASS: storage image, image buffer and texture buffer arrays decorated NonUniform exactly where the GPU indexes '
          'them nonuniformly; %d modules validate; the stamp keeps the GPUs apart%s' % (
              len(translated), '; %d modules without such an array byte for byte the base tree\'s' % len(same)
              if args.base_tree else ''))


if __name__ == '__main__':
    main()
