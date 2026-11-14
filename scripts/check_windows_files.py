"""The Windows Hookshot Builder's release zip, checked as Windows files on the Linux runner that makes it
(.forgejo/workflows/build-windows.yml): what a build on Windows gave, and a build elsewhere could quietly lose. No game data is
involved. Python's standard library, and llvm-mingw's llvm-objdump and llvm-readobj.

    python -I scripts/check_windows_files.py --objdump <llvm-objdump> --readobj <llvm-readobj> <zip>
        the files (HookshotBuilder.exe, the setup, at the top; HookshotBuilder\\ the published builder, its setup copy, the
        tools), the setup's PE header, imports and resources (windres: its icon, manifest and version), the builder's apphost
        (GUI subsystem, so no console window, its version and manifest copied from the assembly) and its .NET (self-contained
        .NET 8, win-x64, and no WPF: the builder has no window)
    python -I scripts/check_windows_files.py --wine <wine> <zip>
        each started under Wine, nothing downloaded: the setup's --play of an empty folder ("error No built game to start"),
        the builder's --cli with no Python ("error The build tools could not start"). A sign that they load and their
        imports and .NET resolve, not a test of what they do (RELEASING.md, "Needs a Windows tester")

Prints what is wrong, and exits 1, when anything is.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile

# (the zip's own files, and the builder folder's that a Windows publish has: the app, its apphost, .NET's host and runtime, and
# what builder_package.py adds. No WPF: the builder has no window)
TOP = ("HookshotBuilder.exe", "VERSION", "recomplauncher.json", "tools.lock")
BUILDER = ("HookshotBuilder.exe", "HookshotBuilder.dll", "HookshotBuilder.deps.json", "HookshotBuilder.runtimeconfig.json",
           "HookshotBuilder-Setup.exe", "LICENSE",
           "hostfxr.dll", "hostpolicy.dll", "coreclr.dll", "clrjit.dll", "System.Private.CoreLib.dll",
           "tools/nx2/make_game.py", "tools/scripts/tools.py", "tools/version.txt")
# (the libraries the setup may import: Windows' own, and the UCRT's api-ms-win-crt-*; never llvm-mingw's libc++ or winpthread)
SETUP_IMPORTS = re.compile(r"^(kernel32|user32|gdi32|advapi32|shell32|ole32|comctl32|winhttp|bcrypt|shlwapi|oleaut32)\.dll$"
                           r"|^api-ms-win-crt-[a-z0-9-]+\.dll$", re.I)
# (setup.c's -l libraries that it calls into: lld imports a library only when something of it is used, so -lole32 adds none)
SETUP_NEEDS = ("winhttp.dll", "bcrypt.dll", "comctl32.dll", "shell32.dll")
# (llvm-readobj --coff-resources: the resource types each must carry)
SETUP_RESOURCES = ("ICON", "GROUP_ICON", "VERSIONINFO", "MANIFEST")   # (setup.rc)
APPHOST_RESOURCES = ("VERSIONINFO", "MANIFEST")   # (the assembly's, copied into the apphost by the SDK's HostWriter)

problems = []


def bad(message):
    problems.append(message)
    print("  wrong: " + message)


def run(*cmd):
    return subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout.decode("utf-8", "replace")


def pe(objdump, readobj, path, name, gui, resources):
    head = run(objdump, "-p", path)
    if "file format coff-x86-64" not in head and "file format pei-x86-64" not in head:
        bad("%s: not an x86-64 PE file" % name)
    if not re.search(r"^Magic\s+020b", head, re.M):
        bad("%s: not PE32+" % name)
    sub = re.search(r"^Subsystem\s+0*([0-9a-f]+)", head, re.M)
    if not sub or int(sub.group(1), 16) != (2 if gui else 3):
        bad("%s: subsystem %s, not %s" % (name, sub and sub.group(1), "Windows GUI (2)" if gui else "console (3)"))
    types = set(re.findall(r"Type: ([A-Z_]+)", run(readobj, "--coff-resources", path)))
    for t in resources:
        if t not in types:
            bad("%s: no %s resource (it has %s)" % (name, t, ", ".join(sorted(types)) or "none"))
    imports = sorted({m.lower() for m in re.findall(r"^\s*DLL Name: (\S+)", head, re.M)})
    print("%s: PE32+ x86-64, subsystem %s, resources %s; imports %s" % (
        name, sub and int(sub.group(1), 16), ", ".join(sorted(types)), ", ".join(imports)))
    return head, imports


def files(a):
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(a.zip) as z:
            names = set(z.namelist())
            for n in TOP:
                if n not in names:
                    bad("the zip has no %s" % n)
            for n in BUILDER:
                if "HookshotBuilder/" + n not in names:
                    bad("the zip has no HookshotBuilder/%s" % n)
            for n in names:
                if n.endswith((".pdb", ".exe.config")) or "/ref/" in n:
                    bad("the zip has %s, which a release build leaves out" % n)
            z.extractall(tmp)
        print("%s: %d files" % (os.path.basename(a.zip), len(names)))
        b = os.path.join(tmp, "HookshotBuilder")
        with open(os.path.join(tmp, "VERSION"), "rb") as f1, open(os.path.join(b, "tools", "version.txt"), "rb") as f2:
            if f1.read() != f2.read():   # (the game's log and hookshot_version.txt name the release from the second)
                bad("VERSION and HookshotBuilder/tools/version.txt differ")
        with open(os.path.join(tmp, "HookshotBuilder.exe"), "rb") as f1, open(os.path.join(b, "HookshotBuilder-Setup.exe"), "rb") as f2:
            if f1.read() != f2.read():
                bad("HookshotBuilder.exe (the setup) and HookshotBuilder/HookshotBuilder-Setup.exe differ")

        head, imports = pe(a.objdump, a.readobj, os.path.join(tmp, "HookshotBuilder.exe"), "the setup", True, SETUP_RESOURCES)
        for n in imports:
            if not SETUP_IMPORTS.match(n):
                bad("the setup imports %s, which is not Windows' own" % n)
        for n in SETUP_NEEDS:
            if n not in imports:
                bad("the setup does not import %s" % n)
        # (--dependent-load-flag=0x800: LOAD_LIBRARY_SEARCH_SYSTEM32 in its load config)
        if not re.search(r"DependentLoadFlags: 0x0*800\b", run(a.readobj, "--coff-load-config", os.path.join(tmp, "HookshotBuilder.exe"))):
            bad("the setup's DependentLoadFlags is not 0x800 (LOAD_LIBRARY_SEARCH_SYSTEM32)")

        exe = os.path.join(b, "HookshotBuilder.exe")
        pe(a.objdump, a.readobj, exe, "the builder", True, APPHOST_RESOURCES)
        with open(exe, "rb") as f:
            data = f.read()
        if "Hookshot Builder".encode("utf-16-le") not in data:
            bad("the builder's apphost has not the assembly's version resource (no \"Hookshot Builder\" in it)")
        if b"HookshotBuilder.dll" not in data:
            bad("the builder's apphost does not name HookshotBuilder.dll (the SDK did not write it)")
        dll = run(a.objdump, "-p", os.path.join(b, "HookshotBuilder.dll"))
        if "file format pei-x86-64" not in dll and "file format pei-i386" not in dll and "file format coff" not in dll:
            bad("HookshotBuilder.dll is not a PE file")
        for n in names:   # (a window's toolkit is not shipped: the builder is command-line only)
            if re.match(r"HookshotBuilder/(Presentation|wpfgfx|System\.Windows\.Forms)", n):
                bad("the zip has %s: the builder has no window and needs no WPF or Windows Forms" % n)
        with open(os.path.join(b, "HookshotBuilder.runtimeconfig.json"), encoding="utf-8") as f:
            rc = json.load(f)["runtimeOptions"]
        included = {x["name"]: x["version"] for x in rc.get("includedFrameworks", [])}
        if rc.get("tfm") != "net8.0":
            bad("the builder's runtimeconfig is for %s, not net8.0" % rc.get("tfm"))
        if not included.get("Microsoft.NETCore.App", "").startswith("8."):
            bad("the builder does not carry Microsoft.NETCore.App 8 (self-contained): %s" % (included or rc.get("frameworks")))
        if "Microsoft.WindowsDesktop.App" in included:
            bad("the builder carries Microsoft.WindowsDesktop.App (WPF): it has no window")
        with open(os.path.join(b, "HookshotBuilder.deps.json"), encoding="utf-8") as f:
            target = json.load(f)["runtimeTarget"]["name"]
        if target != ".NETCoreApp,Version=v8.0/win-x64":
            bad("the builder's runtime target is %s, not .NETCoreApp,Version=v8.0/win-x64" % target)
        print("the builder: %s, self-contained %s" % (target, ", ".join("%s %s" % kv for kv in sorted(included.items()))))


def wine(a):
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(a.zip) as z:
            z.extractall(tmp)
        empty = os.path.join(tmp, "empty")
        os.makedirs(empty)
        env = dict(os.environ, WINEDEBUG=os.environ.get("WINEDEBUG", "-all"))
        # (Z: is / in Wine)
        checks = (("the setup", [os.path.join(tmp, "HookshotBuilder.exe"), "--play", "Z:" + empty.replace("/", "\\")],
                   "error No built game to start"),
                  # (the builder's --cli: its tools found beside it, no Python in the Wine prefix, so the Runner stops with an
                  # "error" line; what matters is that .NET and the builder started)
                  ("the builder", [os.path.join(tmp, "HookshotBuilder", "HookshotBuilder.exe"), "--cli", "--version"],
                   "error The build tools"))
        for name, cmd, want in checks:
            try:
                r = subprocess.run([a.wine] + cmd, cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, timeout=300)
            except subprocess.TimeoutExpired:
                bad("%s did not stop under Wine in 300 s" % name)
                continue
            out = r.stdout.decode("utf-8", "replace")
            lines = [l for l in out.splitlines() if l.startswith(want)]
            print("%s under Wine: exit %d, %s" % (name, r.returncode, lines[0] if lines else "(no %r line)" % want))
            if not lines or "Unhandled exception" in out:
                bad("%s under Wine did not say %r:\n%s" % (name, want, out[-2000:]))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("zip")
    p.add_argument("--objdump")
    p.add_argument("--readobj")
    p.add_argument("--wine")
    a = p.parse_args()
    if a.wine:
        wine(a)
    elif a.objdump and a.readobj:
        files(a)
    else:
        p.error("--objdump and --readobj, or --wine")
    if problems:
        print("%d problem(s)" % len(problems), file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
