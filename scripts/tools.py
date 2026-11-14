"""tools.lock: the build tools the Hookshot Builders need, for Windows (windows-x64) and Linux (linux-x64) (docs/releases.md,
"tools.lock"; RELEASING.md, "Bump a tool"). Python's standard library only. --system picks a system's lines (windows-x64
unless named); the Linux builder reads its lines with this file too (builder/linux/linux_tools.py).

    python -I scripts/tools.py check [--require <name> ...]
        reads tools.lock and refuses a bad line (a name, a SHA-256, a size, a path that leaves the install, a link that is not
        https) or a missing tool. The release workflow requires every tool each builder needs (REQUIRED), and each line's
        copy in Hookshot's store to be there with its size and SHA-256 (the package API)
    python -I scripts/tools.py fetch <name> [--system <s>] [--cache <folder>]
        the tool's archive, from the first of its URLs that answers, checked by its size and SHA-256; prints its path
    python -I scripts/tools.py install <install folder> [--system <s>] [--cache <folder>] [--only <name> ...]
        every tool of the system (or the ones named) unpacked into a builder install, as the setup and the launcher do:
        <prefix> of the archive becomes <dest>
    python -I scripts/tools.py mirror <name> [--system <s>]
        puts the tool's archive, fetched from its URLs, in Hookshot's store (the organization's generic package
        <name>-<system>, version <version>, file <sha256>-<name>.zip), and makes that copy its line's first URL, the others
        the fallback ($RELEASE_TOKEN: your own token)
    python -I scripts/tools.py add <name> <version> <archive> --dest <folder> [--prefix <folder in the archive>] [--system <s>]
        an archive Hookshot made, uploaded to Hookshot's store and written into tools.lock in place of the tool's line
    python -I scripts/tools.py pack <folder> --out <zip>
        a folder as a tool's archive, under its own name: its files with their modes (executable or not) and its relative
        links, deterministic (scripts/linux/deps.sh tools packs the Linux builder's tools with it). Then `add` it
    python -I scripts/tools.py assemble python --requirements nx2/prompt_requirements.txt --out <zip>
    python -I scripts/tools.py assemble cpm --add <CPM folder> --out <zip>
    python -I scripts/tools.py assemble third-party --from <archive with tools/third_party> --out <zip>
    python -I scripts/tools.py assemble profile --work <folder> --out <zip>
        a new archive from the tool's current one with what Hookshot adds: the pinned prompt packages (installed by this
        Python's pip for the archive's Python version and win_amd64), packages for the CPM cache (dav1d, scripts/windows/
        dav1d.sh), the prebuilt files of third_party (a64emit.dll, lld-link.exe, SDL2.dll, SDL3.dll, zbic.dll) only, or the
        play profile (work/: hookshot_pieces.prof, hot_funcs.txt, hot_order.txt, hookshot.res; addresses and counts, no game
        data). Then `add` it. Each archive is deterministic: the same files give the same bytes
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK = os.path.join(ROOT, "tools.lock")
CACHE = os.path.join(ROOT, "build-tools-cache")
REPO = "MagicBeanDev/Hookshot"
SERVER = "https://git.magicbean.dev"
# (the same files from Cloudflare's edge: git-cdn serves git.magicbean.dev's package paths from its R2 store, cached)
CDN = "https://git-cdn.magicbean.dev"
OWNER = REPO.split("/")[0]
SYSTEMS = ("windows-x64", "linux-x64")
# (the tools each builder needs: the release workflow refuses a lock without one of them. The Linux builder's AppImage carries
# its Python; the rest is here, builder/linux/linux_tools.py). The play profile is not required: without its line the game is
# built without one (nx2/make_game.py copies work/'s files only when they are there), a little slower in play; `assemble
# profile` and `add` put one in when there is one
REQUIRED = {"windows-x64": ("llvm-mingw", "python", "emsdk", "cpm", "wgpu-native", "third-party"),
            "linux-x64": ("emsdk", "cpm", "ffmpeg", "sdl2", "sysroot")}
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$")
PREBUILT_EXT = (".dll", ".exe", ".lib", ".sha1")


class Tool(object):
    def __init__(self, name, version, system, sha256, size, dest, prefix, urls):
        self.name, self.version, self.system, self.sha256 = name, version, system, sha256
        self.size, self.dest, self.prefix, self.urls = size, dest, prefix, urls

    def line(self):
        return "tool %s %s %s %s %d %s %s %s" % (self.name, self.version, self.system, self.sha256, self.size, self.dest,
                                                self.prefix, " ".join(self.urls))


def fail(message):
    raise SystemExit("tools.py: " + message)


def path_ok(p):
    """a relative path with / that stays inside the folder it is under (as builder/setup/setup.c's list_name_ok)"""
    parts = p.split("/")
    return bool(p) and not p.startswith("/") and "\\" not in p and ":" not in p and all(x not in ("", ".", "..") for x in parts) \
        and all(re.match(r"^[0-9A-Za-z._+-]+$", x) for x in parts)


def parse(text):
    tools = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        w = line.split()
        if w[0] != "tool" or len(w) < 9:
            fail("tools.lock line %d: not 'tool <name> <version> <system> <sha256> <size> <dest> <prefix> <url>...'" % n)
        name, version, system, sha, size, dest, prefix, urls = w[1], w[2], w[3], w[4], w[5], w[6], w[7], w[8:]
        problems = [why for ok, why in (
            (NAME.match(name), "name"), (VERSION.match(version), "version"), (system in SYSTEMS, "system"),
            (re.fullmatch(r"[0-9a-f]{64}", sha), "sha256"), (size.isdigit() and 0 < int(size) < (1 << 34), "size"),
            (path_ok(dest), "dest"), (prefix == "-" or path_ok(prefix), "prefix"),
            (all(u.startswith("https://") and " " not in u for u in urls), "url")) if not ok]
        if problems:
            fail("tools.lock line %d (%s): bad %s" % (n, name, ", ".join(problems)))
        if any(t.name == name and t.system == system for t in tools):
            fail("tools.lock line %d: %s for %s twice" % (n, name, system))
        tools.append(Tool(name, version, system, sha, int(size), dest, prefix, urls))
    return tools


def load(path=LOCK):
    with open(path, encoding="utf-8") as f:
        return parse(f.read())


def named(tools, name, system="windows-x64"):
    for t in tools:
        if t.name == name and t.system == system:
            return t
    fail("no %s for %s in tools.lock" % (name, system))


def of_system(tools, system):
    return [t for t in tools if t.system == system]


def write_line(tool, path=LOCK):
    """tool's line in place of the one with its name, or added at the end; the comments stay"""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out, done = [], False
    for line in lines:
        w = line.split()
        if len(w) > 3 and w[0] == "tool" and w[1] == tool.name and w[3] == tool.system:
            out.append(tool.line())
            done = True
        else:
            out.append(line)
    if not done:
        out.append(tool.line())
    parse("\n".join(out))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def get(url, timeout=600):
    req = urllib.request.Request(url, headers={"User-Agent": "hookshot-tools"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def download(url, path, size, progress=None, timeout=600):
    """url into path, streamed, stopped past size; its SHA-256. progress(bytes so far) after each block"""
    req = urllib.request.Request(url, headers={"User-Agent": "hookshot-tools"})
    h, have = hashlib.sha256(), 0
    with urllib.request.urlopen(req, timeout=timeout) as r, open(path, "wb") as f:
        for block in iter(lambda: r.read(1 << 20), b""):
            have += len(block)
            if have > size:
                raise OSError("larger than tools.lock gives")
            h.update(block)
            f.write(block)
            if progress:
                progress(have)
    return have, h.hexdigest()


def fetch(tool, cache=CACHE, getter=None, progress=None):
    """The tool's archive in cache as <sha256>.zip (the same cache for every version), from its first URL that gives the
    right bytes. getter(url) -> bytes in place of the download (the tests); progress(bytes so far) while it downloads"""
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, tool.sha256 + ".zip")
    if os.path.isfile(path) and os.path.getsize(path) == tool.size and sha256_file(path) == tool.sha256:
        return path
    last = "no URL"
    for url in tool.urls:
        try:
            if getter is None:
                size, sha = download(url, path + ".part", tool.size, progress)
            else:
                data = getter(url)
                size, sha = len(data), hashlib.sha256(data).hexdigest()
                with open(path + ".part", "wb") as f:
                    f.write(data)
        except (urllib.error.URLError, OSError) as e:
            last = "%s: %s" % (url, e)
            continue
        if size != tool.size or sha != tool.sha256:
            os.remove(path + ".part")
            last = "%s: not the size and SHA-256 tools.lock gives" % url
            continue
        os.replace(path + ".part", path)
        return path
    fail("%s: %s" % (tool.name, last))


def link_ok(rel, target):
    """A link at rel (inside the folder) to target: relative, its ".." first, and landing inside the folder (as the launcher's
    Toolchains.Symlink)"""
    parts = target.split("/")
    ups = 0
    while ups < len(parts) and parts[ups] == "..":
        ups += 1
    if not target or target.startswith("/") or "\\" in target or ".." in parts[ups:]:
        return False
    return ups <= len(rel.split("/")) - 1


def unpack(archive, prefix, dest):
    """The archive's members under prefix ("-": all) into dest, which must not exist yet; nothing outside dest is written. A
    member made on Linux keeps its mode (executable or not) and, when it is a link, stays a link, relative and inside dest"""
    if os.path.exists(dest):
        fail("%s is there already" % dest)
    tmp = dest + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    lead = "" if prefix == "-" else prefix.rstrip("/") + "/"
    os.makedirs(tmp)
    try:
        n = _unpack_into(archive, lead, tmp)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)   # (nothing half unpacked is left)
        raise
    if not n:
        shutil.rmtree(tmp, ignore_errors=True)
        fail("%s has nothing under %s" % (archive, prefix))
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    os.replace(tmp, dest)
    return n


def _unpack_into(archive, lead, tmp):
    root = os.path.realpath(tmp)
    n = 0
    with zipfile.ZipFile(archive) as z:
        for m in z.infolist():
            if m.is_dir() or not m.filename.startswith(lead):
                continue
            rel = m.filename[len(lead):]
            out = os.path.join(tmp, *rel.split("/"))
            if ".." in rel.split("/") or os.path.commonpath([os.path.realpath(os.path.dirname(out)), root]) != root \
                    or os.path.lexists(out):
                fail("%s: %s leaves the folder, or is there twice" % (archive, m.filename))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            mode = m.external_attr >> 16
            if (mode & 0o170000) == 0o120000:
                target = z.read(m).decode("utf-8")
                if not link_ok(rel, target):
                    fail("%s: %s links outside the folder (%s)" % (archive, m.filename, target))
                os.symlink(target, out)
                n += 1
                continue
            with z.open(m) as src, open(out, "wb") as f:
                shutil.copyfileobj(src, f)
            if mode & 0o111:
                os.chmod(out, 0o755)
            n += 1
    return n


STAMPS = ".tools"


def stamp_of(folder, name):
    """The SHA-256 of the archive the tool in folder was unpacked from (folder/.tools/<name>), or None"""
    try:
        with open(os.path.join(folder, STAMPS, name), encoding="utf-8") as f:
            return f.read().split()[0]
    except (OSError, IndexError):
        return None


def write_stamp(folder, tool):
    os.makedirs(os.path.join(folder, STAMPS), exist_ok=True)
    with open(os.path.join(folder, STAMPS, tool.name), "w", encoding="utf-8", newline="\n") as f:
        f.write("%s %s %s\n" % (tool.sha256, tool.prefix, tool.dest))


def install(folder, tools, cache=CACHE, getter=None):
    """Each tool's archive unpacked at its dest under folder, its stamp beside (folder/.tools/<name>). A tool there with
    another stamp (tools.lock changed) is unpacked again; one with none (an install made before the stamps) is kept"""
    for t in tools:
        dest = os.path.join(folder, *t.dest.split("/"))
        had = stamp_of(folder, t.name)
        if os.path.isdir(dest) and had in (None, t.sha256):
            print("%-12s there already" % t.name)
            continue
        if os.path.isdir(dest):
            print("%-12s %s: tools.lock names another archive, unpacked again" % (t.name, t.version))
            shutil.rmtree(dest)
        n = unpack(fetch(t, cache, getter), t.prefix, dest)
        write_stamp(folder, t)
        print("%-12s %s: %d files into %s" % (t.name, t.version, n, t.dest))


def write_zip(path, files, prefix):
    """files {relative path: bytes or a file's path} into a deterministic zip under prefix/ (sorted, fixed dates)"""
    with zipfile.ZipFile(path + ".new", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in sorted(files):
            info = zipfile.ZipInfo(prefix + "/" + rel, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            data = files[rel]
            if not isinstance(data, bytes):
                with open(data, "rb") as f:
                    data = f.read()
            z.writestr(info, data, compresslevel=6)
    os.replace(path + ".new", path)
    return sha256_file(path), os.path.getsize(path)


def members(archive, prefix):
    lead = "" if prefix == "-" else prefix.rstrip("/") + "/"
    with zipfile.ZipFile(archive) as z:
        return {m.filename[len(lead):]: z.read(m) for m in z.infolist() if not m.is_dir() and m.filename.startswith(lead)}


def pack(folder, out):
    """folder as an archive under its own name (the tool's prefix): each file with its mode, 0755 when it is executable, else
    0644, and each link as a link (relative, inside the folder; anything else stops). Sorted, fixed dates: the same files give
    the same bytes"""
    folder = os.path.abspath(folder)
    top = os.path.basename(folder)
    entries = []
    for d, dirs, names in os.walk(folder):
        for name in list(dirs):
            if os.path.islink(os.path.join(d, name)):
                dirs.remove(name)
                names.append(name)
        for name in names:
            full = os.path.join(d, name)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            if os.path.islink(full):
                target = os.readlink(full)
                if not link_ok(rel, target):
                    fail("%s: %s links outside the folder (%s)" % (folder, rel, target))
                entries.append((rel, 0o120777, target.encode("utf-8")))
            elif os.path.isfile(full):
                entries.append((rel, 0o100755 if os.access(full, os.X_OK) else 0o100644, full))
            else:
                fail("%s: %s is not a file" % (folder, rel))
    if not entries:
        fail("%s is empty" % folder)
    with zipfile.ZipFile(out + ".new", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel, mode, data in sorted(entries):
            info = zipfile.ZipInfo(top + "/" + rel, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = mode << 16
            if not isinstance(data, bytes):
                with open(data, "rb") as f:
                    data = f.read()
            z.writestr(info, data, compresslevel=6)
    os.replace(out + ".new", out)
    sha, size = sha256_file(out), os.path.getsize(out)
    print("%s: %d files, %d bytes, sha256 %s (prefix %s)" % (out, len(entries), size, sha, top))
    return sha, size


# ---- assembling Hookshot's own archives ----

def assemble_python(tool, archive, requirements, out, pip=None):
    """The Python archive with requirements' pins (name==version) installed into Lib/site-packages, when it lacks one"""
    with open(requirements, encoding="utf-8") as f:
        pins = [p for p in (l.split("#")[0].strip() for l in f.read().splitlines()) if p]
    files = members(archive, tool.prefix)
    have = {m.split("/")[-2].lower() for m in files if "/" in m and m.split("/")[-2].endswith(".dist-info")}
    missing = [p for p in pins if "%s-%s.dist-info" % tuple(x.strip().lower().replace("-", "_") for x in p.split("==")) not in have]
    if not missing:
        print("the Python archive has %s already" % ", ".join(pins))
        return None
    dll = [m for m in files if "/" not in m and m.lower().startswith("python3") and m[7:-4].isdigit()]
    if len(dll) != 1:
        fail("%s: no pythonXY.dll to give the version" % archive)
    version = "3." + dll[0][7:-4]
    stage = out + ".site"
    shutil.rmtree(stage, ignore_errors=True)
    (pip or subprocess.run)([sys.executable, "-m", "pip", "install", "--no-deps", "--only-binary", ":all:", "--no-compile",
                             "--no-cache-dir", "--disable-pip-version-check", "-q", "--platform", "win_amd64", "--python-version",
                             version, "--implementation", "cp", "--target", stage] + missing, check=True)
    for d, _, names in os.walk(stage):
        for n in names:
            full = os.path.join(d, n)
            files["Lib/site-packages/" + os.path.relpath(full, stage).replace(os.sep, "/")] = full
    result = write_zip(out, files, "python")
    shutil.rmtree(stage, ignore_errors=True)
    print("python %s with %s: %s" % (version, ", ".join(missing), out))
    return result


def assemble_cpm(tool, archive, add, out):
    """The CPM cache archive with the <package>/<version> folders of add (dav1d), when it lacks one"""
    want = sorted((n, v) for n in os.listdir(add) if os.path.isdir(os.path.join(add, n))
                  for v in os.listdir(os.path.join(add, n)) if os.path.isdir(os.path.join(add, n, v)))
    if not want:
        fail("%s: no <package>/<version> folders" % add)
    files = members(archive, tool.prefix)
    have = {tuple(m.split("/")[:2]) for m in files}
    missing = [nv for nv in want if nv not in have]
    if not missing:
        print("the CPM archive has %s already" % ", ".join("/".join(nv) for nv in want))
        return None
    for name, version in missing:
        top = os.path.join(add, name, version)
        for d, _, names in os.walk(top):
            for n in names:
                full = os.path.join(d, n)
                files["%s/%s/%s" % (name, version, os.path.relpath(full, top).replace(os.sep, "/"))] = full
    result = write_zip(out, files, "cpm")
    print("cpm with %s: %s" % (", ".join("/".join(nv) for nv in missing), out))
    return result


def assemble_third_party(source, prefix, out, tracked):
    """The prebuilt files of a tools/third_party (rebuilt on the player's PC when their sources' stamps differ), never a
    source file: third_party/'s sources are the repository's"""
    files = {rel: data for rel, data in members(source, prefix).items()
             if rel.lower().endswith(PREBUILT_EXT) and ("third_party/" + rel) not in tracked}
    if not files:
        fail("%s: no prebuilt files under %s" % (source, prefix))
    result = write_zip(out, files, "third_party")
    print("third-party: %s (%s)" % (out, ", ".join(sorted(files))))
    return result


PROFILE = ("hookshot_pieces.prof", "hot_funcs.txt", "hot_order.txt", "hookshot.res", "hookshot.ico")


def assemble_profile(work, out):
    files = {n: os.path.join(work, n) for n in PROFILE if os.path.isfile(os.path.join(work, n))}
    if "hot_order.txt" not in files:
        fail("%s: no hot_order.txt (make_game.py's profile)" % work)
    result = write_zip(out, files, "work")
    print("profile: %s (%s)" % (out, ", ".join(sorted(files))))
    return result


# ---- Hookshot's store: Forgejo's generic package registry ----
# Each archive Hookshot keeps a copy of, or makes, is a file of a generic package of the MagicBeanDev organization (its
# Packages tab): the package <name>-<system>, its version the tool's version, the file <sha256>-<name>.zip. A package
# version's files never change (Forgejo refuses a second upload of a name, HTTP 409), and nothing prunes them: an older
# version's tools stay downloadable. Anyone downloads them, with no account (the organization is public). Each system has its
# own package because a tool's Windows and Linux builds have versions of their own (emsdk: Hookshot v2.1.0's, LLVM 23.1.5).

def file_name(tool):
    return "%s-%s.zip" % (tool.sha256, tool.name)


def package_url(tool, server=SERVER):
    return "%s/api/packages/%s/generic/%s-%s/%s/%s" % (server, OWNER, tool.name, tool.system, tool.version, file_name(tool))


def store_url(tool):
    """The tool's copy in Hookshot's store, as the package API names it (where it is uploaded and checked)"""
    return package_url(tool)


def store_urls(tool):
    """tools.lock's first URLs for a tool in Hookshot's store: the edge's copy, then the store's own address"""
    return [package_url(tool, CDN), package_url(tool)]


def store_of(t):
    """The store address among a line's URLs, or None (a tool only upstream has)"""
    return next((u for u in t.urls if in_store(u)), None)


def in_store(url):
    return url.startswith("%s/api/packages/%s/generic/" % (SERVER, OWNER))


def exists(url, timeout=60):
    """(there, size, sha256) of a file in the store, from the package API's list of its version's files (anonymous: the
    organization is public; a HEAD through Cloudflare gives no size). (False, None, None) when it is not there"""
    head = "%s/api/packages/%s/generic/" % (SERVER, OWNER)
    package, version, name = url[len(head):].split("/")
    req = urllib.request.Request("%s/api/v1/packages/%s/generic/%s/%s/files" % (SERVER, OWNER, package, version),
                                 headers={"User-Agent": "hookshot-tools", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            files = json.load(r)
    except (urllib.error.URLError, OSError, ValueError):
        return False, None, None
    for f in files if isinstance(files, list) else ():
        if isinstance(f, dict) and f.get("name") == name:
            return True, f.get("Size", f.get("size")), f.get("sha256")
    return False, None, None


def store(path, tool):
    """The archive at path, put in Hookshot's store as the tool's copy (PUT; a copy there already, 409, is kept when it is the
    same size: its bytes cannot change). FORGEJO_UPLOAD_API: the server without Cloudflare in front (its 100 MB limit), as
    <address>/api/v1. Returns the copy's URL"""
    url = store_url(tool)
    base = (os.environ.get("FORGEJO_UPLOAD_API") or "").rstrip("/")
    put = package_url(tool, base[:-len("/api/v1")] if base.endswith("/api/v1") else SERVER)
    token = os.environ.get("RELEASE_TOKEN") or fail("RELEASE_TOKEN is needed (your token, with write access to %s's packages)" % OWNER)
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        req = urllib.request.Request(put, data=f, method="PUT", headers={
            "Authorization": "token " + token, "User-Agent": "hookshot-tools", "Content-Type": "application/zip",
            "Content-Length": str(size)})
        try:
            with urllib.request.urlopen(req, timeout=1800):
                pass
            print("uploaded %s" % url)
        except urllib.error.HTTPError as e:
            if e.code != 409:
                fail("PUT %s: HTTP %d %s" % (url, e.code, e.read().decode("utf-8", "replace")[:300]))
            there, got, sha = exists(url)
            if not there or got != size or sha != tool.sha256:
                fail("%s is in the package registry already with other bytes (%s bytes, SHA-256 %s): a new version, then"
                     % (url, got, sha))
            print("%s is in the package registry already" % url)
    return url


def tracked_files(*paths):
    out = subprocess.run(["git", "ls-files", *paths], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return set(out.split())


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--lock", default=LOCK)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("check")
    s.add_argument("--require", nargs="*")
    s = sub.add_parser("fetch")
    s.add_argument("name")
    s.add_argument("--system", choices=SYSTEMS, default="windows-x64")
    s.add_argument("--cache", default=CACHE)
    s = sub.add_parser("install")
    s.add_argument("folder")
    s.add_argument("--system", choices=SYSTEMS, default="windows-x64")
    s.add_argument("--cache", default=CACHE)
    s.add_argument("--only", nargs="*")
    s = sub.add_parser("mirror")
    s.add_argument("name")
    s.add_argument("--system", choices=SYSTEMS, default="windows-x64")
    s.add_argument("--cache", default=CACHE)
    s = sub.add_parser("add")
    s.add_argument("name")
    s.add_argument("version")
    s.add_argument("archive")
    s.add_argument("--dest", required=True)
    s.add_argument("--prefix", default="-")
    s.add_argument("--system", choices=SYSTEMS, default="windows-x64")
    s = sub.add_parser("pack")
    s.add_argument("folder")
    s.add_argument("--out", required=True)
    s = sub.add_parser("assemble")
    s.add_argument("what", choices=("python", "cpm", "third-party", "profile"))
    s.add_argument("--requirements")
    s.add_argument("--add")
    s.add_argument("--from", dest="source")
    s.add_argument("--from-prefix", default="HookshotBuilder/tools/third_party")
    s.add_argument("--work")
    s.add_argument("--out", required=True)
    s.add_argument("--cache", default=CACHE)
    a = p.parse_args(argv)
    tools = load(a.lock)

    if a.cmd == "check":
        have = {(t.name, t.system) for t in tools}
        if a.require == []:
            missing = ["%s (%s)" % (n, s) for s in SYSTEMS for n in REQUIRED[s] if (n, s) not in have]
        else:
            missing = [n for n in a.require or () if n not in {t.name for t in tools}]
        for t in tools:
            print("%-12s %-22s %s %6d MB  %s" % (t.name, t.version, t.system, t.size >> 20, t.urls[0]))
        if missing:
            print("error: tools.lock is missing: %s (a builder needs them); RELEASING.md, One-time setup" % ", ".join(missing),
                  file=sys.stderr)
            return 1
        if a.require is not None:
            # (each copy in Hookshot's store answers with its size: a line whose package was never uploaded fails here, not on
            # every player's PC. Upstream fallbacks are not asked)
            gone = []
            for t in tools:
                url = store_of(t)
                if url:
                    if t.urls[:2] != store_urls(t):
                        gone.append("%s (%s): its first URLs are not %s" % (t.name, t.system, " ".join(store_urls(t))))
                        continue
                    there, size, sha = exists(url)
                    if not there or size != t.size or sha != t.sha256:
                        gone.append("%s (%s): %s" % (t.name, t.system, "not there" if not there else
                                                     "%s bytes, SHA-256 %s" % (size, sha)))
            if gone:
                print("error: not in Hookshot's store as tools.lock names them: %s; RELEASING.md, Bump a tool" % "; ".join(gone),
                      file=sys.stderr)
                return 1
    elif a.cmd == "fetch":
        print(fetch(named(tools, a.name, a.system), a.cache))
    elif a.cmd == "install":
        install(a.folder, [t for t in of_system(tools, a.system) if not a.only or t.name in a.only], a.cache)
    elif a.cmd == "pack":
        pack(a.folder, a.out)
    elif a.cmd == "mirror":
        t = named(tools, a.name, a.system)
        store(fetch(t, a.cache), t)
        first = store_urls(t)
        if t.urls[:2] != first:
            t.urls = first + [u for u in t.urls if u not in first]
            write_line(t, a.lock)
        print("%s: %s" % (t.name, " ".join(t.urls)))
    elif a.cmd == "add":
        sha, size = sha256_file(a.archive), os.path.getsize(a.archive)
        t = Tool(a.name, a.version, a.system, sha, size, a.dest, a.prefix, [])
        store(a.archive, t)
        t.urls = store_urls(t)
        write_line(t, a.lock)
        print("tools.lock: %s %s %s" % (a.name, a.version, sha))
    elif a.cmd == "assemble":
        if a.what == "python":
            t = named(tools, "python")
            assemble_python(t, fetch(t, a.cache), a.requirements or os.path.join(ROOT, "nx2", "prompt_requirements.txt"), a.out)
        elif a.what == "cpm":
            t = named(tools, "cpm")
            assemble_cpm(t, fetch(t, a.cache), a.add or fail("--add <CPM folder>"), a.out)
        elif a.what == "third-party":
            assemble_third_party(a.source or fail("--from <archive>"), a.from_prefix, a.out, tracked_files("third_party"))
        else:
            assemble_profile(a.work or fail("--work <folder>"), a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
