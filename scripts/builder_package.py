"""The Windows Hookshot Builder's release zip (docs/releases.md), made in CI (.forgejo/workflows/release.yml, ci.yml). No game
data is involved. Python's standard library only.

    python -I scripts/builder_package.py llvm-mingw <folder> [--name] [--host windows|linux]
        llvm-mingw (its SHA-256 checked) unpacked into <folder>; prints its folder. --name: only its folder's name (a cache
        key). --host (default: this system): windows is tools.lock's, the one players get; linux is the same release's Linux
        build (LINUX_LLVM_MINGW below), which the release's Windows files are made with on the Linux runner
    python -I scripts/builder_package.py package <out folder> --publish <dotnet publish folder> --setup <setup exe>
        the builder's folder, HookshotBuilder\\ in the zip: the published builder, the setup (a game folder's hookshot.exe:
        make_game.py copies it there), LICENSE,
        the tracked gpu, host, nx2, scripts and third_party under tools\\, and the pipeline state list's sources
        (assets/pipeline_states/, which must be there and read). None of tools.lock's tools: the setup or the launcher adds
        those on the player's PC
    python -I scripts/builder_package.py zip <package folder> <version> --setup <setup exe> --out <zip>
        HookshotBuilder-<version>-windows-x64.zip: HookshotBuilder.exe (the setup), HookshotBuilder\\ (the package),
        tools.lock, VERSION and recomplauncher.json (RecompLauncher reads it at the top). Deterministic: the same files give
        the same bytes
"""
import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tools_module():
    spec = importlib.util.spec_from_file_location("tools", os.path.join(ROOT, "scripts", "tools.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# llvm-mingw's Linux build, the same release as tools.lock's (tests/test_windows_on_linux.py keeps the two the same): CI has no
# Windows runner (docs/forgejo-runners.md), so the setup, the Windows Vulkan back end and dav1d are compiled on Linux with it.
# (version, folder in the archive, SHA-256, size, URL), as a tools.lock line has them
LINUX_LLVM_MINGW = ("20261104", "llvm-mingw-20261104-ucrt-ubuntu-22.04-x86_64",
                    "919380403de87dca3c581c2053230cd298af5e891286628ba0613b7fed370926", 84104244,
                    "https://github.com/mstorsjo/llvm-mingw/releases/download/20261104/"
                    "llvm-mingw-20261104-ucrt-ubuntu-22.04-x86_64.tar.xz")


def llvm_mingw(a):
    tools = tools_module()
    if a.host == "windows":
        t = tools.named(tools.load(), "llvm-mingw")
    else:
        version, prefix, sha256, size, url = LINUX_LLVM_MINGW
        t = tools.Tool("llvm-mingw", version, "linux-x64", sha256, size, "-", prefix, [url])
    if a.name:
        print(t.prefix)
        return 0
    folder = os.path.join(a.folder, t.prefix)
    clang = os.path.join(folder, "bin", "clang.exe" if a.host == "windows" else "clang")
    if not os.path.isfile(clang):
        archive = tools.fetch(t, os.path.join(a.folder, ".cache"))   # (its size and SHA-256 checked)
        if a.host == "windows":
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(a.folder)
        else:
            with tarfile.open(archive, "r:xz") as tf:
                # (the "data" filter: nothing written outside the folder; the links inside it are kept. Python 3.12)
                tf.extractall(a.folder, filter="data")
    print(folder)
    return 0


def tracked(*paths):
    r = subprocess.run(["git", "ls-files", "-z", "--"] + list(paths), cwd=ROOT, check=True, stdout=subprocess.PIPE)
    return [f for f in r.stdout.decode("utf-8").split("\0") if f]


def copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)


def package(a):
    out = os.path.abspath(a.out)
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(a.publish, out)
    copy(a.setup, os.path.join(out, "HookshotBuilder-Setup.exe"))   # (a game folder's hookshot.exe: make_game.py copies it there)
    copy(os.path.join(ROOT, "LICENSE"), os.path.join(out, "LICENSE"))
    tools = os.path.join(out, "tools")
    for f in tracked("gpu", "host", "nx2", "scripts", "third_party"):
        copy(os.path.join(ROOT, f), os.path.join(tools, *f.split("/")))
    if state_list(tools) != 0:
        return 1
    print("package folder: %s" % out)
    return 0


def state_list(tools):
    """The sources of the pipeline state list a release ships (assets/pipeline_states/: the tour's list, the contributed ones and
    their notes), into tools/ at the same path: nx2/make_game.py merges them beside the game. Required: without them a new
    install's first field load is drawn white for seconds while its pipelines compile (v2.0.8 to v2.0.14 shipped none). 1, with
    the reason, when there are none or one does not read (nx2/pipeline_states.py check)"""
    spec = importlib.util.spec_from_file_location("pipeline_states", os.path.join(ROOT, "nx2", "pipeline_states.py"))
    states = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(states)
    src = states.sources_dir(ROOT)
    try:
        recs = states.check_sources(src)
    except SystemExit as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    dst = states.sources_dir(tools)
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    print("the pipeline state list: %s" % states.describe(recs))
    return 0


def make_zip(package_dir, version, setup, out):
    entries = {"HookshotBuilder.exe": setup, "tools.lock": os.path.join(ROOT, "tools.lock"),
               "recomplauncher.json": os.path.join(ROOT, "recomplauncher.json"), "VERSION": (version + "\n").encode(),
               # (the release again where the builder and the game read it: Runner.cs's Version, nx2/version.py's release(),
               # and through them the game folder's hookshot_version.txt and the first line of hookshot_log.txt)
               "HookshotBuilder/tools/version.txt": (version + "\n").encode()}
    for d, dirs, names in os.walk(package_dir):
        dirs.sort()
        for n in names:
            full = os.path.join(d, n)
            entries["HookshotBuilder/" + os.path.relpath(full, package_dir).replace(os.sep, "/")] = full
    with zipfile.ZipFile(out + ".new", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            data = entries[name]
            if not isinstance(data, bytes):
                with open(data, "rb") as f:
                    data = f.read()
            z.writestr(info, data, compresslevel=6)
    os.replace(out + ".new", out)
    print("%s: %d files, %d MB" % (out, len(entries), os.path.getsize(out) >> 20))
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("llvm-mingw")
    s.add_argument("folder", nargs="?", default="")
    s.add_argument("--name", action="store_true")
    s.add_argument("--host", choices=("windows", "linux"), default="windows" if os.name == "nt" else "linux")
    s = sub.add_parser("package")
    s.add_argument("out")
    s.add_argument("--publish", required=True)
    s.add_argument("--setup", required=True)
    s = sub.add_parser("zip")
    s.add_argument("package")
    s.add_argument("version")
    s.add_argument("--setup", required=True)
    s.add_argument("--out", required=True)
    a = p.parse_args()
    if a.cmd == "zip":
        return make_zip(a.package, a.version, a.setup, a.out)
    return {"llvm-mingw": llvm_mingw, "package": package}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
