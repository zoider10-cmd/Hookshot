"""The Linux builder's build tools: tools.lock's linux-x64 lines (the compiler, the sysroot, FFmpeg, SDL2, the Vulkan headers),
which are not in the AppImage (docs/releases.md, "tools.lock"). AppRun asks this file where they are before it starts
nx2/make_game.py (--cli), and puts what it prints in the environment.

    linux_tools.py env [--install]

Each tool is looked for, in order:
  1. in the builder itself, at its tools.lock dest (<AppDir>/usr/lib/hookshot/emsdk, ...): the Hookshot Launcher unpacks
     the AppImage into <launcher home>/toolchains/<version>/ and each tool beside it there (Core/Toolchains.cs), as it does
     on Windows; a developer's AppDir too;
  2. in the launcher's own copy of this version (<launcher home>/toolchains/<version>/, its toolchain.json naming the tool's
     SHA-256), when the AppImage is started by itself on a PC where the launcher installed the same version;
  3. in the builder's toolchains ($XDG_DATA_HOME/hookshot/builder/toolchains/<version>/, the same layout), where --install
     puts what is missing: each archive downloaded from tools.lock's URLs, checked by its size and SHA-256
     (scripts/tools.py), and unpacked at its dest, its stamp in .tools/<name>. A tool another version there already has
     (the same SHA-256) is linked from it, not downloaded again; once a version's tools are there, nothing is downloaded.
The download's progress goes to stderr (--cli, and RecompLauncher's --cli --prepare). What is printed is `export NAME='value'`
for each tool found.
"""
import argparse
import fcntl
import json
import os
import re
import shlex
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS_ROOT = os.environ.get("HOOKSHOT_TOOLS") or os.path.dirname(os.path.dirname(HERE))   # (usr/share/hookshot, or a checkout)
SYSTEM = "linux-x64"
# (what make_game.py and nx2/build.py read for each tool, and the file in it when it is one file)
ENV = {"emsdk": ("EMSDK", ""), "sysroot": ("HOOKSHOT_SYSROOT", ""), "ffmpeg": ("HOOKSHOT_FFMPEG", ""),
       "sdl2": ("HOOKSHOT_SDL2", "libSDL2-2.0.so.0"), "cpm": ("RX_CPM", "")}
TAG = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,127}$")


def _tools_py():
    sys.path.insert(0, os.path.join(TOOLS_ROOT, "scripts"))
    try:
        import tools
    finally:
        sys.path.pop(0)
    return tools


tools = _tools_py()


def data_root(environ=os.environ):
    """The builder's own data: $HOOKSHOT_BUILDER_HOME or $XDG_DATA_HOME/hookshot/builder"""
    base = environ.get("HOOKSHOT_BUILDER_HOME") or environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "hookshot", "builder")


def launcher_toolchains(environ=os.environ):
    """The launcher's toolchains folder (its LauncherHome: $HOOKSHOT_LAUNCHER_HOME, else $XDG_DATA_HOME/hookshot/launcher)"""
    home = environ.get("HOOKSHOT_LAUNCHER_HOME")
    if not home:
        home = os.path.join(environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "hookshot", "launcher")
    return os.path.join(home, "toolchains")


def app_root(tools_root=TOOLS_ROOT):
    """The builder's root, where AppRun is: <root>/usr/share/hookshot is tools_root (None in a checkout)"""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(tools_root))))
    return root if os.path.isfile(os.path.join(root, "AppRun")) else None


def version(tools_root=TOOLS_ROOT):
    try:
        with open(os.path.join(tools_root, "VERSION"), encoding="utf-8") as f:
            tag = f.readline().strip()
    except OSError:
        tag = ""
    return tag if TAG.match(tag) and tag not in (".", "..") else "dev"


def lock(tools_root=TOOLS_ROOT):
    """This builder's linux-x64 tools (its own tools.lock, inside the AppImage)"""
    path = os.path.join(tools_root, "tools.lock")
    return tools.of_system(tools.load(path), SYSTEM) if os.path.isfile(path) else []


def _at(root, tool):
    return os.path.join(root, *tool.dest.split("/"))


def _launcher_has(folder, tool):
    """The launcher's copy of a version names this archive (toolchain.json, written once the version is complete)"""
    try:
        with open(os.path.join(folder, "toolchain.json"), encoding="utf-8") as f:
            parts = json.load(f).get("Parts") or []
    except (OSError, ValueError, AttributeError):
        return False
    return any(isinstance(p, dict) and p.get("Sha") == tool.sha256 for p in parts) and os.path.isdir(_at(folder, tool))


def find(tool, tag, tools_root=TOOLS_ROOT, environ=os.environ):
    """The folder the tool is at (its dest under it), or None"""
    own = app_root(tools_root)
    if own and os.path.isdir(_at(own, tool)):
        return own
    theirs = os.path.join(launcher_toolchains(environ), tag)
    if tag != "dev" and _launcher_has(theirs, tool):
        return theirs
    mine = os.path.join(data_root(environ), "toolchains", tag)
    if os.path.isdir(_at(mine, tool)) and tools.stamp_of(mine, tool.name) == tool.sha256:
        return mine
    return None


def _link_tree(src, dest):
    """src's files at dest: hard links where the file system allows, else copies; links stay links"""
    tmp = dest + ".part"
    shutil.rmtree(tmp, ignore_errors=True)

    def copy(a, b):
        try:
            os.link(a, b)
        except OSError:
            shutil.copy2(a, b)
    shutil.copytree(src, tmp, symlinks=True, copy_function=copy)
    os.replace(tmp, dest)


def install(missing, tag, environ=os.environ, say=print, getter=None):
    """Each missing tool into the builder's toolchains/<tag>: linked from another version there with the same archive, else
    downloaded (say(text, fraction of the bytes to download)). Returns that folder"""
    home = os.path.join(data_root(environ), "toolchains")
    mine = os.path.join(home, tag)
    os.makedirs(mine, exist_ok=True)
    with open(os.path.join(home, ".lock"), "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)   # (two builders started at once: the second waits, then finds them there)
        todo = [t for t in missing if not (os.path.isdir(_at(mine, t)) and tools.stamp_of(mine, t.name) == t.sha256)]
        others = sorted(d for d in os.listdir(home) if d != tag and not d.startswith(".") and os.path.isdir(os.path.join(home, d)))
        fetch_list = []
        for t in todo:
            dest = _at(mine, t)
            shutil.rmtree(dest, ignore_errors=True)
            src = next((os.path.join(home, d) for d in others if tools.stamp_of(os.path.join(home, d), t.name) == t.sha256
                        and os.path.isdir(_at(os.path.join(home, d), t))), None)
            if src:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                _link_tree(_at(src, t), dest)
                tools.write_stamp(mine, t)
                say("%s: kept from %s" % (t.name, os.path.basename(src)), None)
            else:
                fetch_list.append(t)
        total = max(1, sum(t.size for t in fetch_list))
        done = 0
        cache = os.path.join(home, ".downloads")
        for i, t in enumerate(fetch_list):
            head = "Downloading the build tools (%d of %d, %s, %d MB)" % (i + 1, len(fetch_list), t.name, t.size >> 20)
            say(head, done / total)
            archive = tools.fetch(t, cache, getter, lambda have, d=done: say(None, (d + min(have, t.size)) / total))
            say("Unpacking %s" % t.name, (done + t.size) / total)
            tools.unpack(archive, t.prefix, _at(mine, t))
            tools.write_stamp(mine, t)
            os.remove(archive)   # (unpacked, it is what later versions link from)
            done += t.size
        if fetch_list:
            say("The build tools are ready", 1.0)
    return mine


def environment(found):
    """{variable: path} for the tools found ({tool: folder})"""
    env = {}
    for t, root in found.items():
        name, file = ENV.get(t.name, (None, ""))
        if name and root:
            env[name] = os.path.join(_at(root, t), file) if file else _at(root, t)
    return env


def ensure(do_install, say, tools_root=TOOLS_ROOT, environ=os.environ, getter=None):
    """({tool: folder or None}, error text or None)"""
    tag = version(tools_root)
    wanted = lock(tools_root)
    found = {t: find(t, tag, tools_root, environ) for t in wanted}
    missing = [t for t, root in found.items() if root is None]
    if missing and do_install:
        try:
            mine = install(missing, tag, environ, say, getter)
        except (SystemExit, OSError) as e:
            return found, "The build tools could not be installed (%s). Check the connection and start the builder again." % (
                str(e).replace("tools.py: ", "") or type(e).__name__)
        for t in missing:
            found[t] = mine
    still = [t.name for t, root in found.items() if root is None]
    return found, ("Missing build tools: %s" % ", ".join(still)) if still else None


def text_say():
    """Progress as lines on stderr (stdout is the environment AppRun reads): a line per step, its percentage redrawn"""
    last = {"text": "", "open": False}

    def say(text, fraction):
        percent = "" if fraction is None else " %3d%%" % int(fraction * 100)
        if text:
            sys.stderr.write(("\n" if last["open"] else "") + text + percent)
            last["text"], last["open"] = text, True
        else:
            sys.stderr.write("\r" + last["text"] + percent)
        if fraction is None or fraction >= 1.0:
            sys.stderr.write("\n")
            last["open"] = False
        sys.stderr.flush()
    return say


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("what", choices=("env",))
    p.add_argument("--install", action="store_true", help="download what is missing")
    a = p.parse_args(argv)
    found, error = ensure(a.install, text_say())
    for name, value in sorted(environment({t: r for t, r in found.items() if r}).items()):
        print("export %s=%s" % (name, shlex.quote(value)))
    if error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
