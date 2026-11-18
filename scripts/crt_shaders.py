"""Compile Hookshot's fixed CRT compute adapters into checked-in SPIR-V headers.

The unchanged libretro sources and their notices are in third_party/crt_shaders;
the hand-adapted .comp files are in gpu/vk/shaders. This is not a Slang loader.
Player builds include the headers and do not need glslang or this script.

    python -I -B scripts/crt_shaders.py --glslang glslangValidator
    python -I -B scripts/crt_shaders.py --check --glslang glslangValidator

Every header starts with its .comp SHA-256 and command, then retains the shader's
opening notice. --check always checks that prefix. If glslang is available it also
recompiles; an explicit --glslang is required to exist. Different compiler versions
may emit different SPIR-V, which is reported separately from source staleness.
"""
import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "gpu/vk/shaders"
SHADERS = ("crt_lottes", "crt_hyllian", "crt_zfast", "crt_downsample")
TARGET_ENV = "vulkan1.2"


def source_line(comp, name):
    """Match the source-hash convention used by test_fg_scale_sharpen.py."""
    digest = hashlib.sha256(comp.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    return (f"// {comp.name} sha256 {digest} (scripts/crt_shaders.py: "
            f"glslangValidator -V --target-env {TARGET_ENV} --vn {name.upper()}_COMP_SPV)\n")


def prefix(comp, name):
    """Keep all opening attribution/licence comments in the generated header too."""
    text = comp.read_text(encoding="utf-8")
    version, _, rest = text.partition("\n")
    if version != "#version 450" or "layout(local_size_x" not in rest:
        raise SystemExit(f"{comp.name}: expected #version 450 and the compute layout after the opening notice")
    return source_line(comp, name) + rest[:rest.index("layout(local_size_x")]


def words(text, name):
    """Read this shader's glslang --vn array, not numbers from its comments."""
    array = re.search(r"\b" + name.upper() + r"_COMP_SPV\s*\[\s*\]\s*=\s*\{(.*?)\};", text, re.S)
    if not array:
        raise SystemExit(f"{name}_comp_spv.h: missing {name.upper()}_COMP_SPV array")
    result = re.findall(r"0x[0-9a-fA-F]{8}", array.group(1))
    if not result or result[0].lower() != "0x07230203":
        raise SystemExit(f"{name}_comp_spv.h: missing SPIR-V magic")
    return [int(word, 16) for word in result]


def generator(text):
    """glslang's --vn version line, as in scripts/host_shaders.py."""
    found = re.search(r"^\t// (\d+\.\d+\.\d+)$", text, re.M)
    return found.group(1) if found else None


def checked_header(comp, name):
    header = comp.with_name(name + "_comp_spv.h")
    if not header.is_file():
        raise SystemExit(f"{header.name}: missing; run python -I -B scripts/crt_shaders.py")
    text = header.read_text(encoding="utf-8")
    opening = prefix(comp, name)
    if not text.startswith(opening):
        raise SystemExit(f"{header.name}: source hash, command or notice is stale; "
                         "run python -I -B scripts/crt_shaders.py")
    body = text[len(opening):]
    words(body, name)
    return body


def compile_one(glslang, comp, name, out):
    result = subprocess.run([glslang, "-V", "--target-env", TARGET_ENV, "--vn", name.upper() + "_COMP_SPV",
                             "-o", str(out), str(comp)], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"{comp.name}: glslang failed ({result.returncode})\n" + result.stdout + result.stderr)
    return out.read_text(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--glslang", help="glslangValidator path; otherwise find glslangValidator/glslang on PATH")
    parser.add_argument("--check", action="store_true", help="check headers without modifying any source or header")
    args = parser.parse_args()
    glslang = (shutil.which(args.glslang) if args.glslang else
               shutil.which("glslangValidator") or shutil.which("glslang"))
    if not glslang and (args.glslang or not args.check):
        raise SystemExit("glslang not found; pass --glslang with its executable path")

    old = {name: checked_header(DIR / (name + ".comp"), name) for name in SHADERS} if args.check else {}
    if not glslang:
        print(f"CRT shaders: {len(SHADERS)} source hashes/notices match; no glslang, compilation not checked")
        return

    bad = []
    different_version = []
    made = {}
    with tempfile.TemporaryDirectory(prefix="crt-shaders-") as tmp:
        for name in SHADERS:
            comp = DIR / (name + ".comp")
            body = compile_one(glslang, comp, name, Path(tmp) / (name + "_comp_spv.h"))
            new_words = words(body, name)
            if args.check:
                if new_words == words(old[name], name):
                    continue
                old_version, new_version = generator(old[name]), generator(body)
                if old_version and new_version and old_version != new_version:
                    different_version.append(name)
                    print(f"{name}: glslang {new_version} differs from the checked-in {old_version}; "
                          "compiled, but SPIR-V is not byte-comparable with that version", file=sys.stderr)
                else:
                    bad.append(name)
            else:
                made[name] = prefix(comp, name) + body
    if bad:
        raise SystemExit("CRT headers differ from their sources compiled by the same glslang: " + ", ".join(bad) +
                         "; run python -I -B scripts/crt_shaders.py")
    if args.check:
        print(f"CRT shaders: {len(SHADERS)} source hashes/notices match and compile; "
              f"{len(SHADERS) - len(different_version)} SPIR-V arrays match, "
              f"{len(different_version)} differ with another compiler version")
    else:
        # Do not replace any checked-in header until every shader has compiled.
        for name in SHADERS:
            (DIR / (name + "_comp_spv.h")).write_text(made[name], encoding="utf-8", newline="\n")
        print(f"CRT shaders: {len(SHADERS)} headers written")


if __name__ == "__main__":
    main()
