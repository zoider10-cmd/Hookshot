"""Exercise the actual DLSS object-job dependencies and cache keys with authored SDK headers and a real compiler."""
import argparse
import ast
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from types import SimpleNamespace

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build-script", type=Path, default=ROOT / "nx2/build.py")
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()
    tree = ast.parse(a.build_script.read_text(encoding="utf-8"))
    # (renderer_deps and its helpers: the back end's files are keyed by their depfile's headers once they have one)
    wanted = ("tree_headers", "flag_text", "object_key", "renderer_deps", "depfile_paths", "depfile_of")
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    def assigned(n, names):
        return isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets)
    inputs = [n for n in ast.walk(tree) if assigned(n, ("HEADER_EXTS", "_HEADER_DIGESTS", "DEPFILE_JOBS", "ngx_flags", "ngx_deps",
                                                         "vdeps_roots", "vdeps"))]
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == "src"
             and isinstance(n.iter, ast.Call) and isinstance(n.iter.func, ast.Name) and n.iter.func.id == "vk_sources"]
    # (the depfile helpers are a later build.py's: an older --build-script has the first three alone)
    assert set(wanted[:3]) <= {n.name for n in functions} and len(loops) == 1, \
        "actual dependency/key functions and Vulkan producer loop are required"
    code = compile(ast.Module(body=functions + inputs + loops, type_ignores=[]), str(a.build_script), "exec")
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    with tempfile.TemporaryDirectory(prefix="dlss-sdk-cache-") as folder:
        root = Path(folder)
        vk, sdk = root / "gpu/vk", root / "authored sdk"
        vk.mkdir(parents=True)
        (sdk / "include/detail").mkdir(parents=True)
        header = sdk / "include/detail/value.h"
        header.write_text("#define SDK_VALUE 11\n", encoding="utf-8")
        (sdk / "include/authored_ngx.h").write_text("#include <detail/value.h>\n", encoding="utf-8")
        common = vk / "common.h"
        common.write_text("// authored backend header\n", encoding="utf-8")
        src = vk / "vk_dlss.cpp"
        src.write_text("#ifdef HOOKSHOT_NGX\n#include <authored_ngx.h>\n#else\n#define SDK_VALUE 3\n#endif\n"
                       "int main() { return SDK_VALUE; }\n", encoding="utf-8")
        other = vk / "vk_other.cpp"
        other.write_text("// unrelated backend source\n", encoding="utf-8")
        def jobs(sdk_path=sdk):
            ns = dict(os=os, re=re, hashlib=hashlib, kit=SimpleNamespace(ROOT=str(root)), NGX_SDK=str(sdk_path) if sdk_path else "",
                      vk=str(vk), GPU=str(root / "gpu"), vk_jobs=[], cxx=a.cxx, obj_dir=str(root / "obj"),
                      vflags=["-std=c++17", "-O0"], imgui_flags=[], imgui_users=(), shader_stamp="", stamp_def="",
                      vk_lib_deps=b"", logo_text=b"", imgui_deps=b"", vk_sources=lambda: [str(src), str(other)],
                      vk_pgo_flags=[])   # (RX_VK_PGO: no profile, as by default)
            exec(code, ns)
            return {Path(j[1]).name: (ns["object_key"](j[1], j[3], j[4]), j) for j in ns["vk_jobs"]}

        cache = {}
        def result(job):
            # (the job's flags preprocess the source, and its SDK_VALUE is read from the text: nothing is linked or run. A
            # tiny new program run from the temp folder is what Defender's machine-learning guess quarantines as a trojan,
            # Trojan:Win32/Bearfoos.A!ml, which failed this check and alarmed whoever ran it. -MD is left out: no depfile)
            key, (_, source, _, compile_flags, _) = job
            if key not in cache:
                text = subprocess.run([a.cxx, *[f for f in compile_flags if f not in ("-MD", "-MMD")], "-E", "-P", source],
                                      check=True, capture_output=True, text=True, cwd=root, **flags).stdout
                cache[key] = int(re.search(r"return (\d+);", text).group(1))
            return cache[key]

        first = jobs()
        disabled = jobs(None)
        assert result(first["vk_dlss.cpp"]) == 11
        assert result(disabled["vk_dlss.cpp"]) == 3
        header.write_text("#define SDK_VALUE 22\n", encoding="utf-8")
        changed = jobs()
        assert result(changed["vk_dlss.cpp"]) == 22, "SDK header edit reused stale DLSS code from the actual job key"
        assert first["vk_dlss.cpp"][0] != changed["vk_dlss.cpp"][0]
        assert first["vk_other.cpp"][0] == changed["vk_other.cpp"][0], "SDK change invalidated an unrelated backend object"
        assert disabled["vk_dlss.cpp"][0] == jobs(None)["vk_dlss.cpp"][0], "disabled NGX depends on SDK headers"
        relocated = root / "relocated sdk"
        shutil.copytree(sdk, relocated)
        assert changed["vk_dlss.cpp"][0] == jobs(relocated)["vk_dlss.cpp"][0], "SDK relocation defeated content-based reuse"
        assert result(jobs(relocated)["vk_dlss.cpp"]) == 22 and len(cache) == 3
        header.write_text("#define SDK_VALUE 11\n", encoding="utf-8")
        assert result(jobs()["vk_dlss.cpp"]) == 11 and len(cache) == 3, "restoring headers did not reuse their original object"
        common.write_text("// changed backend header\n", encoding="utf-8")
        assert first["vk_other.cpp"][0] != jobs()["vk_other.cpp"][0], "existing backend dependencies were lost"
    print("PASS: actual DLSS job rebuilds changed SDK headers; relocation, restoration, disabled NGX and unrelated objects retain reuse")


if __name__ == "__main__":
    main()
