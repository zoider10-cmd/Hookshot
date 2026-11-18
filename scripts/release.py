"""Releases on git.magicbean.dev (docs/releases.md, RELEASING.md), for both products: Hookshot (its builders, released from
MagicBeanDev/Hookshot) and the Hookshot Launcher (MagicBeanDev/HookshotLauncher). The same file is in both repositories; it
finds out which one it is in. Python's standard library, git, and the openssl command line (for keys and signatures) only.

A release is a Forgejo release of the repository: a tag, a page with the notes, and the product's files, with SHA256SUMS (each
file's SHA-256) and SHA256SUMS.sig (an ECDSA P-256 signature of SHA256SUMS by the release key, base64 DER). The channels are
read from the list of published releases: stable is the newest vX.Y.Z, rc the newest vX.Y.Z-rc.N or vX.Y.Z, nightly the
newest nightly-<count>-<commit>.

Versions and notes:
    python -I scripts/release.py next [--tag <tag>]
        the version the commits since the last stable call for (feat: minor, fix and perf: patch, ! or BREAKING CHANGE:
        major), the next release candidate's tag, and the notes git-cliff would write (a preview; nothing is changed)
    python -I scripts/release.py check-tag <tag> [--releases <releases.json>]
        refuses a tag that is not vX.Y.Z or vX.Y.Z-rc.N, not on main, not above every release there is, or lower than the
        commits since the last stable call for (CI runs it before it builds anything)
    python -I scripts/release.py nightly-name
        nightly-<commits since the product's first commit>-<8 hex of HEAD>: the nightly's version
    python -I scripts/release.py nightly-news
        yes when HEAD brings something the notes list since the newest nightly on its history (git-cliff, cliff.toml: a ci:
        or chore: commit is in no notes), else no: the release workflow makes no nightly with nothing new on its page
    python -I scripts/release.py nightly-age
        the seconds since the newest published nightly came out, or none: the release workflow builds a nightly at
        least once an hour while merges keep coming
    python -I scripts/release.py notes <tag> [--out <file>]
        the release notes: git-cliff with cliff.toml, over the commits since the tag before (of the product's numbers); an rc
        after the first also lists what the earlier release candidates since the last stable brought
    python -I scripts/release.py git-cliff <folder>
        the pinned git-cliff (GIT_CLIFF below), downloaded and checked by its SHA-256 into <folder>; prints its path

Files and signatures:
    python -I scripts/release.py sums <file>... --out SHA256SUMS
    python -I scripts/release.py sign SHA256SUMS --key <private .pem> --out SHA256SUMS.sig
    python -I scripts/release.py verify SHA256SUMS [--sig SHA256SUMS.sig] [--pub <.pem>] [--files <folder>]
        the signature, by the key given or a key the launcher trusts (trusted_keys); with --files, every file's SHA-256 too
    python -I scripts/release.py keygen <out folder>
        a new ECDSA P-256 key pair, release.pem (private: keep it out of every repository) and release.pub.pem, and the lines
        for the launcher's Core/ReleaseTrust.cs and Hookshot's scripts/release_keys.json
    python -I scripts/release.py key-id <.pem>

The release on Forgejo ($RELEASE_TOKEN: in CI the job's own token, forgejo.token; $GITHUB_REPOSITORY or the repository
this is; $FORGEJO_API, $FORGEJO_UPLOAD_API):
    python -I scripts/release.py publish <tag> --target <commit> --notes <file> <file>...
        a draft release (pre-release unless a stable), every file uploaded and checked, then published: until that last step
        no launcher sees it. A draft left by a failed run of the same tag is reused. The page is the notes under a header
        (release_page): the launcher's, big download links to its own files; Hookshot's, "to play, get the Hookshot
        Launcher", with hookshot.magicbean.dev's links to the newest launcher of the same channel
    python -I scripts/release.py prune [--keep 5]
        the nightly releases and their tags past the newest <keep>; nothing else is ever deleted
    python -I scripts/release.py released-as <commit> [--not <tag>]
        the published release CI made of that commit (a nightly, or a release candidate under its stable), its SHA256SUMS
        signed by a key the launcher trusts and naming its every file; nothing when there is none. A release of the commit
        that fails those checks stops it
    python -I scripts/release.py channels
        what each channel offers now, as the launcher reads it
    python -I scripts/release.py artifacts <folder> --run <run id> <name>...
        the build jobs' files: the named artifacts of a workflow run (CI: $GITHUB_RUN_ID), each unpacked into <folder>, from
        the address without Cloudflare when $FORGEJO_UPLOAD_API names one (through Cloudflare they come at about 1 MB/s)
"""
import argparse
import base64
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = "https://git.magicbean.dev"
# (each product: its repository, its first version's major number, and the commit its nightlies count from: Hookshot from the
# fork, e2a4d453 "Rename the project to Hookshot"; the launcher from its repository's first commit)
PRODUCTS = {
    "hookshot": {"repo": "MagicBeanDev/Hookshot", "first_major": 3, "display": "Hookshot",
                 "since": "e2a4d45398ffba162f54026bb7e708a7157bbed9"},
    "launcher": {"repo": "MagicBeanDev/HookshotLauncher", "first_major": 1, "display": "Hookshot Launcher", "since": None},
}
CHANNELS = ("stable", "rc", "nightly")
# (git-cliff for the notes, Linux x86-64, pinned: its release page gives the SHA-256)
GIT_CLIFF = ("2.14.2", "24f397c733add5390fdceee3a2088588ab0d5f944ce00d34cb7029b888cf2db4",
             "https://github.com/orhun/git-cliff/releases/download/v2.14.2/git-cliff-2.14.2-x86_64-unknown-linux-gnu.tar.gz")
SUMS, SIG = "SHA256SUMS", "SHA256SUMS.sig"
STABLE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
VERSION = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$")
NIGHTLY = re.compile(r"^nightly-([0-9]{1,9})-([0-9a-f]{8})$")
# (names that look like the game's files, a dump's, or NVIDIA's runtime: never uploaded, CONTRIBUTING.md)
NOT_A_RELEASE_FILE = re.compile(r"(\.(nso|nca|nsp|xci|nsz|xcz|nup|keys|bin)$|romfs|exefs|nvngx|dlss|streamline|^sl\..*\.dll$)",
                                re.IGNORECASE)
# (a Conventional Commit title: type(scope)!: description; scripts/forge.py checks pull request titles with the same types)
TITLE = re.compile(r"^(feat|fix|perf|refactor|docs|test|ci|build|chore|revert)(\([^)]*\))?(!)?: ")


def fail(message):
    raise SystemExit("release.py: " + message)


def product_of(root=ROOT):
    """launcher in the launcher's repository (it has Core/ReleaseTrust.cs), else hookshot"""
    return "launcher" if os.path.isfile(os.path.join(root, "Core", "ReleaseTrust.cs")) else "hookshot"


# ---- versions ----

def version_key(tag):
    """The order of a product's versions: (major, minor, patch, 1 for a stable / 0 for a release candidate, rc number);
    None for anything else"""
    m = VERSION.match(tag or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if m.group(4) else 1, int(m.group(4) or 0)


def is_version(tag, first_major):
    k = version_key(tag)
    return bool(k) and k[0] >= first_major


def channel_of(tag, first_major):
    """the channel a version is made for: nightly, rc (a release candidate) or stable; None when it is no version of the
    product (a git describe name, dev, a 2.x number; the build tools are generic packages, not releases: tools.lock)"""
    if NIGHTLY.match(tag or ""):
        return "nightly"
    if not is_version(tag, first_major):
        return None
    return "stable" if STABLE.match(tag) else "rc"


def newest(releases, channel, first_major):
    """What a channel offers, from a list of releases ({tag_name, draft, prerelease}) as Forgejo's API gives them: drafts never;
    stable the newest vX.Y.Z that is not a pre-release; rc the newest vX.Y.Z-rc.N or vX.Y.Z; nightly the newest nightly by
    its count. The launcher's Core/Releases.cs reads the list by the same rules"""
    tags = [r["tag_name"] for r in releases if not r.get("draft")]
    if channel == "nightly":
        nightlies = [t for t in tags if NIGHTLY.match(t)]
        return max(nightlies, key=lambda t: int(NIGHTLY.match(t).group(1)), default=None)
    pre = {r["tag_name"] for r in releases if r.get("prerelease")}
    ok = [t for t in tags if is_version(t, first_major) and (channel == "rc" or (STABLE.match(t) and t not in pre))]
    return max(ok, key=version_key, default=None)


# ---- git ----

def git(*args, root=ROOT, check=True):
    p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8")
    if check and p.returncode:
        fail("git %s: %s" % (" ".join(args), p.stderr.strip()))
    return p.stdout.strip() if p.returncode == 0 else None


def tags_merged(root=ROOT, ref="HEAD"):
    return [t for t in (git("tag", "--merged", ref, "--list", "v*", root=root) or "").split() if t]


def last_stable(first_major, root=ROOT, ref="HEAD", below=None):
    """The newest stable tag of the product's numbers on ref's history (lower than below, when given: the tag being checked
    is not its own last stable)"""
    return max((t for t in tags_merged(root, ref) if STABLE.match(t) and is_version(t, first_major)
                and (below is None or version_key(t) < version_key(below))), key=version_key, default=None)


def commits(since, root=ROOT, ref="HEAD"):
    """[(subject, body)] of the commits after since (all of ref's history when None), oldest first, merges left out"""
    out = git("log", "--reverse", "--no-merges", "--format=%s%x1f%b%x1e", (since + ".." + ref) if since else ref, root=root) or ""
    return [tuple((c.strip("\n").split("\x1f", 1) + [""])[:2]) for c in out.split("\x1e") if c.strip()]


def bump_of(subjects_bodies):
    """major, minor, patch or None: the largest change a list of commits makes (a squash-merged pull request's title is its
    commit's subject: CONTRIBUTING.md, Pull request titles)"""
    level = None
    for subject, body in subjects_bodies:
        m = TITLE.match(subject)
        if (m and m.group(3)) or re.search(r"^BREAKING[ -]CHANGE: ", body or "", re.M):
            return "major"
        if m and m.group(1) == "feat":
            level = "minor"
        elif m and m.group(1) in ("fix", "perf") and level is None:
            level = "patch"
    return level


def required(first_major, root=ROOT, ref="HEAD", below=None):
    """(the lowest stable number the commits since the last stable allow, as vX.Y.Z; that stable; the bump)"""
    last = last_stable(first_major, root, ref, below)
    if last is None:
        return "v%d.0.0" % first_major, None, None
    level = bump_of(commits(last, root, ref))
    x, y, z = (int(n) for n in STABLE.match(last).groups())
    if level == "major":
        return "v%d.0.0" % (x + 1), last, level
    if level == "minor":
        return "v%d.%d.0" % (x, y + 1), last, level
    return "v%d.%d.%d" % (x, y, z + 1), last, level   # (patch, or nothing a player sees: still a new number)


def base_of(tag):
    k = version_key(tag)
    return (k[0], k[1], k[2]) if k else None


def check_tag(tag, existing, first_major, root=ROOT, main="origin/main"):
    """The problems with releasing tag ([] when none): its form, main, every release there is, and the bump"""
    problems = []
    if not is_version(tag, first_major):
        return ["%s is not vX.Y.Z or vX.Y.Z-rc.N of this product's numbers (from v%d.0.0)" % (tag, first_major)]
    commit = git("rev-list", "-n", "1", tag, root=root, check=False)
    if not commit:
        return ["no tag %s here (git fetch --tags)" % tag]
    if git("merge-base", "--is-ancestor", commit, main, root=root, check=False) is None:
        problems.append("%s is not on main (%s): releases are made from main only" % (tag, main))
    higher = [t for t in existing if t != tag and is_version(t, first_major) and version_key(t) >= version_key(tag)]
    if higher:
        problems.append("%s is not above every release there is: %s" % (tag, ", ".join(sorted(higher, key=version_key))))
    low, last, level = required(first_major, root, commit, below=tag)
    if base_of(tag) < base_of(low):
        problems.append("%s is lower than the commits since %s call for: at least %s (%s)"
                        % (tag, last or "the start", low, level or "a new number"))
    return problems


def next_tag(existing, first_major, root=ROOT):
    """The next release candidate's tag: the next rc of the current one when it is still high enough, else <required>-rc.1"""
    low = required(first_major, root)[0]
    rcs = [t for t in existing if is_version(t, first_major) and not STABLE.match(t) and base_of(t) >= base_of(low)]
    top = max(rcs, key=version_key, default=None)
    if top and not any(STABLE.match(t) and base_of(t) == base_of(top) for t in existing):
        return "%s-rc.%d" % (top.split("-rc.")[0], version_key(top)[4] + 1)
    return low + "-rc.1"


def nightly_name(product, root=ROOT):
    since = PRODUCTS[product]["since"]
    count = git("rev-list", "--count", (since + "..HEAD") if since else "HEAD", root=root)
    return "nightly-%s-%s" % (count, git("rev-parse", "--short=8", "HEAD", root=root))


def nightly_age(rels, now=None):
    """The seconds since the newest published nightly came out (its published_at, else created_at), or None when there is
    none: a nightly that waited for more merges still builds when the one before is an hour old"""
    published = [r for r in rels if NIGHTLY.match(r["tag_name"]) and not r.get("draft")]
    if not published:
        return None
    newest = max(published, key=lambda r: int(NIGHTLY.match(r["tag_name"]).group(1)))
    stamp = newest.get("published_at") or newest.get("created_at")
    if not stamp:
        return None
    when = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return int((time.time() if now is None else now) - when.timestamp())


def previous_tag(tag, first_major, root=ROOT):
    """The tag the notes of tag start after: the newest version tag before it on its history (for a stable, the stable
    before it, so its notes cover its release candidates too)"""
    ref = tag if git("rev-parse", "-q", "--verify", "refs/tags/" + tag, root=root, check=False) else "HEAD"
    if NIGHTLY.match(tag):
        older = [t for t in tags_merged(root, ref) if is_version(t, first_major)]
    else:
        older = [t for t in tags_merged(root, ref) if t != tag and is_version(t, first_major) and version_key(t) < version_key(tag)
                 and (not STABLE.match(tag) or STABLE.match(t))]
    return max(older, key=version_key, default=None)


def previous_nightly(tag, root=ROOT):
    """The newest nightly tag on HEAD's history other than tag (the ones past the newest 5 are pruned, tag and all): a
    nightly's notes list what is new since it first. None for the first nightly"""
    found = [t for t in (git("tag", "--merged", "HEAD", "--list", "nightly-*", root=root) or "").split()
             if NIGHTLY.match(t) and t != tag]
    return max(found, key=lambda t: int(NIGHTLY.match(t).group(1)), default=None)


def nightly_news(product, root=ROOT):
    """Whether HEAD brings anything a nightly's notes list as new since the newest nightly on its history: git-cliff's
    notes over those commits (cliff.toml) have an entry. Only ci: or chore: commits since (nightly-322-5bc54c6c, one
    ci(release) commit): no, and no nightly is made (they are in no notes); the next one comes with what follows. The
    first nightly: yes"""
    previous = previous_nightly(nightly_name(product, root), root)
    if previous is None:
        return True
    if git("rev-list", "--count", previous + "..HEAD", root=root) == "0":
        return False
    return any(line.startswith("- ") for line in git_cliff("--strip", "all", previous + "..HEAD", root=root).splitlines())


RC_TAGS = r"^v[0-9]+\.[0-9]+\.[0-9]+-rc\.[0-9]+$"   # (git-cliff --ignore-tags: the earlier release candidates in one list)


def earlier_rcs(tag, first_major, root=ROOT):
    """The release candidates before an rc since the last stable, oldest first ([] for a stable, a nightly or a first rc):
    an rc's page lists what is new since the one before, then what those brought"""
    if not VERSION.match(tag) or STABLE.match(tag):
        return []
    ref = tag if git("rev-parse", "-q", "--verify", "refs/tags/" + tag, root=root, check=False) else "HEAD"
    stable = last_stable(first_major, root, ref, below=tag)
    return sorted((t for t in tags_merged(root, ref) if t != tag and VERSION.match(t) and not STABLE.match(t)
                   and is_version(t, first_major) and version_key(t) < version_key(tag)
                   and (stable is None or version_key(t) > version_key(stable))), key=version_key)


def git_cliff(*args, root=ROOT):
    cliff = os.environ.get("GIT_CLIFF") or shutil.which("git-cliff")
    if not cliff:
        fail("git-cliff is needed for the notes: python -I scripts/release.py git-cliff <folder>, then GIT_CLIFF=<its path>")
    p = subprocess.run([cliff, "--config", os.path.join(root, "cliff.toml")] + list(args), cwd=root, capture_output=True,
                       text=True, encoding="utf-8")
    if p.returncode:
        fail("git-cliff: " + p.stderr.strip())
    return p.stdout.strip()


def notes(tag, product, root=ROOT):
    """git-cliff's notes for tag (cliff.toml), the commits since the previous tag of the product's numbers (the first:
    since the product's first commit, for Hookshot the fork). An rc after the first has two lists: new since the rc before
    (its heading says so), then "Earlier release candidates", everything those brought since the last stable in one list"""
    first = PRODUCTS[product]["first_major"]
    since = previous_tag(tag, first, root) or PRODUCTS[product]["since"]
    ref = "HEAD" if NIGHTLY.match(tag) or git("rev-parse", "-q", "--verify", "refs/tags/" + tag, root=root, check=False) is None else tag
    # (no tag before and no first commit, the launcher's first release: every commit of the checkout, which is ref's. No
    # range then: git-cliff takes a lone ref for a range and stops, SetCommitRangeError("HEAD", unable to parse OID))
    prev_nightly = previous_nightly(tag, root) if NIGHTLY.match(tag) else None
    text = git_cliff("--tag", tag, "--strip", "all", *([(prev_nightly or since) + ".." + ref] if prev_nightly or since else []), root=root)
    if prev_nightly:   # (a nightly: new since the nightly before, then everything since the last version, like an rc's page)
        head, _, rest = text.partition("\n")
        if head.startswith("## "):
            text = "%s, new since %s\n%s" % (head, prev_nightly, rest)
        older = git_cliff("--tag", prev_nightly, "--strip", "all", *([since + ".." + prev_nightly] if since else []), root=root)
        head, _, rest = older.partition("\n")
        older = rest if head.startswith("## ") else older
        if not older.strip():
            return text + "\n"
        return "%s\n\n## Earlier changes%s\n%s\n" % (text, " (since %s)" % since if since else "", older.rstrip())
    earlier = earlier_rcs(tag, first, root)
    if not earlier:
        return text + "\n"
    last = earlier[-1]
    short = lambda t: t.split("-", 1)[1] if base_of(t) == base_of(tag) else t   # (rc.2; another number's in full)
    head, _, rest = text.partition("\n")
    if head.startswith("## "):
        text = "%s, new since %s\n%s" % (head, short(last), rest)
    stable = last_stable(first, root, last)
    base = stable or PRODUCTS[product]["since"]
    if base:
        span = [base + ".." + last]
    else:   # (the start of the history: no range, and the commits after the last earlier rc skipped)
        span = [a for c in (git("rev-list", last + "..HEAD", root=root) or "").split() for a in ("--skip-commit", c)]
    older = git_cliff("--tag", last, "--ignore-tags", RC_TAGS, "--strip", "all", *span, root=root)
    head, _, rest = older.partition("\n")
    older = rest if head.startswith("## ") else older   # (git-cliff's heading names the last of them only)
    heading = "## Earlier release candidates: %s%s" % (", ".join(short(t) for t in earlier),
                                                       " (since %s)" % stable if stable else "")
    return "%s\n\n%s\n%s\n" % (text, heading, older.rstrip())


# ---- the release page ----

# (hookshot.magicbean.dev's permanent download links, the Hookshot website, website/ in MagicBeanDev/Hookshot: /download/launcher/<channel>[/<os>] goes to that channel's
# newest launcher, by the rules of newest() above)
SITE = "https://hookshot.magicbean.dev"
# (the same release files from Cloudflare's edge: git-cdn serves git.magicbean.dev's release paths from its R2 store, cached)
CDN = "https://git-cdn.magicbean.dev"
LAUNCHER_FILES = {"setup": "-windows-x64-setup.exe", "portable": "-windows-x64-portable.zip", "appimage": "-x86_64.AppImage"}
CHANNEL_SAYS = {"stable": "This is a stable release: it builds Hookshot's stable versions by default.",
                "rc": "This is a release candidate: it builds Hookshot's rc versions by default.",
                "nightly": "This is a nightly, untested: it builds Hookshot's nightlies by default."}


def page_header(tag, product, names, repo=None):
    """The top of a release's page, above git-cliff's notes: big heading links that look like buttons, no tables. The
    launcher's: this release's own files. Hookshot's: "to play, get the Hookshot Launcher", with hookshot.magicbean.dev's links to
    the newest launcher of the same channel (rc to rc, nightly to nightly, stable to stable), and "don't download the files
    below" (above the builder files)"""
    channel = channel_of(tag, PRODUCTS[product]["first_major"]) or "nightly"
    if product == "launcher":
        base = "%s/%s/releases/download/%s/" % (CDN, repo or repo_of(product), urllib.parse.quote(tag))
        url = {k: base + urllib.parse.quote(n) for k, suffix in LAUNCHER_FILES.items() for n in sorted(names)
               if n.startswith("HookshotLauncher-") and n.endswith(suffix)}
        lines = ["# ⬇️ Download Hookshot Launcher", ""]
        if "setup" in url:
            lines += ["### [🪟 &nbsp;Download for Windows](%s)" % url["setup"], ""]
        if "appimage" in url:
            lines += ["### [🐧 &nbsp;Download for Linux (AppImage)](%s)" % url["appimage"], ""]
        if "portable" in url:
            lines += ["Windows without installing: [portable zip](%s)" % url["portable"], ""]
        return "\n".join(lines + [
            "Run it, point it at your own dump of the game (a `.nup`, or its romfs and exefs folders), and press **Build**. "
            "It installs Hookshot and keeps it and itself up to date. %s" % CHANNEL_SAYS[channel], "", "---", ""])
    link = "%s/download/launcher/%s" % (SITE, channel)
    return "\n".join([
        "# 🎮 To play, get the Hookshot Launcher", "",
        "### [🪟 &nbsp;Download the launcher for Windows](%s/windows)" % link, "",
        "### [🐧 &nbsp;Download the launcher for Linux (AppImage)](%s/linux)" % link, "",
        "Windows without installing: [portable zip](%s/windows-portable) · [the launcher's newest %s release](%s)"
        % (link, channel, link), "",
        "**Don't download the files below:** they're the builder the launcher installs for you.", "", "---", ""])


def release_page(tag, product, notes_text, names, repo=None):
    """The release page's text: the header, then git-cliff's notes"""
    return page_header(tag, product, names, repo) + "\n" + notes_text.strip() + "\n"


# ---- keys and signatures ----

def fetch_git_cliff(folder):
    import tarfile
    version, want, url = GIT_CLIFF
    exe = os.path.join(folder, "git-cliff-%s" % version, "git-cliff")
    if os.path.isfile(exe):
        return exe
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "hookshot-release"}), timeout=120) as r:
        data = r.read()
    if hashlib.sha256(data).hexdigest() != want:
        fail("%s: not the SHA-256 GIT_CLIFF names" % url)
    os.makedirs(folder, exist_ok=True)
    with tarfile.open(fileobj=__import__("io").BytesIO(data)) as t:
        t.extractall(folder, filter="data")
    if not os.path.isfile(exe):
        fail("no git-cliff in %s" % url)
    return exe


def openssl(*args, data=None):
    try:
        return subprocess.run(["openssl", *args], input=data, capture_output=True, check=True).stdout
    except FileNotFoundError:
        fail("the openssl command line is needed")
    except subprocess.CalledProcessError as e:
        fail("openssl %s: %s" % (args[0], e.stderr.decode("utf-8", "replace").strip()))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def spki_der(pem_path):
    """The SubjectPublicKeyInfo (DER) of a public or private key file"""
    with open(pem_path, "rb") as f:
        pem = f.read()
    return openssl(*(["pkey", "-pubin"] if b"PUBLIC KEY" in pem else ["pkey"]), "-pubout", "-outform", "DER", data=pem)


def key_id(spki):
    return hashlib.sha256(spki).hexdigest()[:16]


def pem_of(spki):
    body = base64.b64encode(spki).decode()
    return "-----BEGIN PUBLIC KEY-----\n%s\n-----END PUBLIC KEY-----\n" % "\n".join(body[i:i + 64] for i in range(0, len(body), 64))


def strip_cs_comments(text):
    """C# text with its // and /* */ comments blanked out (strings, verbatim strings and chars kept as they are)"""
    return re.sub(r'//[^\n]*|/\*.*?\*/|@"(?:[^"]|"")*"|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'',
                  lambda m: " " if m.group(0)[0] == "/" else m.group(0), text, flags=re.S)


def keys_from_cs(text):
    """[spki] of the launcher's ReleaseKeys.BuiltIn: the ReleaseKey.FromSpki("...") entries inside its initializer's braces
    (comments left out first, so a ; { or } in one changes nothing)"""
    code = strip_cs_comments(text)
    m = re.search(r"\bBuiltIn\s*=[^{;]*\{", code)
    if not m:
        return []
    depth, end = 1, m.end()
    while depth and end < len(code):
        depth += {"{": 1, "}": -1}.get(code[end], 0)
        end += 1
    return [base64.b64decode(k) for k in re.findall(r'ReleaseKey\.FromSpki\(\s*"([A-Za-z0-9+/=]+)"\s*\)', code[m.end():end])]


def trusted_keys(root=ROOT):
    """The keys the launcher is built with: Core/ReleaseTrust.cs in the launcher's repository; in Hookshot's,
    scripts/release_keys.json ({"keys": ["<base64 SubjectPublicKeyInfo>"]}), which must list the same keys"""
    cs = os.path.join(root, "Core", "ReleaseTrust.cs")
    if os.path.isfile(cs):
        with open(cs, encoding="utf-8") as f:
            return keys_from_cs(f.read())
    path = os.path.join(root, "scripts", "release_keys.json")
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [base64.b64decode(k) for k in json.load(f).get("keys", [])]


def sign(path, key):
    with open(path, "rb") as f:
        data = f.read()
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "data")
        with open(src, "wb") as f:
            f.write(data)
        der = openssl("dgst", "-sha256", "-sign", key, src)
    if not verify_sig(data, der, [spki_der(key)]):
        fail("the signature just made does not check: is %s an ECDSA P-256 key?" % key)
    return base64.b64encode(der).decode() + "\n"


def verify_sig(data, der, keys):
    """The SPKI (DER) of the key in keys that signed data, or None"""
    with tempfile.TemporaryDirectory() as tmp:
        src, sig, pub = (os.path.join(tmp, n) for n in ("data", "sig", "pub.pem"))
        with open(src, "wb") as f:
            f.write(data)
        with open(sig, "wb") as f:
            f.write(der)
        for spki in keys:
            with open(pub, "w") as f:
                f.write(pem_of(spki))
            if subprocess.run(["openssl", "dgst", "-sha256", "-verify", pub, "-signature", sig, src], capture_output=True).returncode == 0:
                return spki
    return None


def read_sums(text):
    """{name: sha256} of a SHA256SUMS ("<64 hex>  <name>" lines; sha256sum's format)"""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-f]{64}) [ *]([^/\\]+)$", line)
        if not m:
            fail("not a SHA256SUMS line: %r" % line)
        out[m.group(2)] = m.group(1)
    return out


# ---- Forgejo ----

def repo_of(product):
    return os.environ.get("GITHUB_REPOSITORY") or PRODUCTS[product]["repo"]


UPLOAD_TRIES = 4      # (an upload the server answers with a 5xx, or that the connection drops, is made again: this many times in all)
UPLOAD_PAUSE = 20.0   # (seconds before the second try; twice that before the third, and so on)


class ServerTrouble(Exception):
    """A request the server answered with a 5xx, or that never got its answer: worth making again"""


def api(method, path, body=None, data=None, content_type=None, upload=False, missing_ok=False, again=False):
    """again: a 5xx answer or a lost connection raises ServerTrouble instead of ending the run, for a caller that retries"""
    base = (os.environ.get("FORGEJO_UPLOAD_API") if upload else None) or os.environ.get("FORGEJO_API") or SERVER + "/api/v1"
    headers = {"User-Agent": "hookshot-release", "Accept": "application/json"}
    token = os.environ.get("RELEASE_TOKEN")
    if token:
        headers["Authorization"] = "token " + token
    if body is not None:
        data, content_type = json.dumps(body).encode(), "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            text = r.read()
    except urllib.error.HTTPError as e:
        if missing_ok and e.code == 404:
            return None
        said = "%s %s: HTTP %d %s" % (method, path, e.code, e.read().decode("utf-8", "replace")[:300])
        if again and e.code >= 500:
            raise ServerTrouble(said)
        fail(said)
    except (urllib.error.URLError, OSError) as e:   # (no answer: refused, reset, timed out)
        if again:
            raise ServerTrouble("%s %s: %s" % (method, path, e))
        fail("%s %s: %s" % (method, path, e))
    return json.loads(text) if text else None


def upload_file(repo, rel_id, name, data):
    """One release file, uploaded and its size checked. The server's own trouble (a 5xx, a dropped connection: its storage
    or the proxy in front of it, not this file) is not the end of the release: what that try left under the name is
    removed and the upload made again, UPLOAD_TRIES times in all, after a longer pause each time"""
    form, ctype = multipart(name, data)
    path = "/repos/%s/releases/%d/assets?name=%s" % (repo, rel_id, urllib.parse.quote(name))
    for attempt in range(1, UPLOAD_TRIES + 1):
        try:
            got = api("POST", path, data=form, content_type=ctype, upload=True, again=attempt < UPLOAD_TRIES)
        except ServerTrouble as e:
            pause = UPLOAD_PAUSE * attempt
            print("::warning::%s: upload %d of %d failed (%s): again in %d s" % (name, attempt, UPLOAD_TRIES, e, pause), flush=True)
            time.sleep(pause)
            for rel in releases(repo):   # (a failed upload can leave its file behind: a second one of the name is refused)
                if rel["id"] == rel_id:
                    for asset in rel.get("assets") or []:
                        if asset["name"] == name:
                            api("DELETE", "/repos/%s/releases/%d/assets/%d" % (repo, rel_id, asset["id"]), missing_ok=True)
            continue
        if got.get("size") != len(data):
            fail("%s: uploaded %s bytes of %d" % (name, got.get("size"), len(data)))
        return


def releases(repo, pages=1000):
    """Every release of repo, page by page until an empty one: published ones, and drafts too with a writer token (each
    says which it is in draft and prerelease). No draft= or pre-release= filter is sent: on Forgejo they keep only the
    releases whose field equals the value (draft=true lists the drafts alone)"""
    out, seen = [], set()
    for page in range(1, pages + 1):
        items = api("GET", "/repos/%s/releases?limit=50&page=%d" % (repo, page)) or []
        new = [r for r in items if r["id"] not in seen]
        if not new:
            return out
        seen.update(r["id"] for r in new)
        out += new
    fail("%s: more than %d pages of releases" % (repo, pages))


def multipart(name, data):
    boundary = "hookshot%s" % hashlib.sha256(data[:4096] + name.encode()).hexdigest()[:24]
    head = ('--%s\r\nContent-Disposition: form-data; name="attachment"; filename="%s"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n' % (boundary, name)).encode()
    return head + data + ("\r\n--%s--\r\n" % boundary).encode(), "multipart/form-data; boundary=" + boundary


def publish(tag, target, notes_file, files, product):
    repo = repo_of(product)
    for path in files:
        if NOT_A_RELEASE_FILE.search(os.path.basename(path)):
            fail("%s looks like a game, dump or NVIDIA file: never released (CONTRIBUTING.md)" % path)
    stable = bool(STABLE.match(tag))
    with open(notes_file, encoding="utf-8") as f:
        body = release_page(tag, product, f.read(), [os.path.basename(p) for p in files], repo)
    title = "%s %s" % (PRODUCTS[product]["display"], tag)
    found = [r for r in releases(repo) if r["tag_name"] == tag]
    if found and not found[0]["draft"]:
        fail("%s is already published: a version's files never change (RELEASING.md)" % tag)
    if found:
        rel = found[0]
        for asset in rel.get("assets") or []:   # (a draft a failed run left: its uploads start again)
            api("DELETE", "/repos/%s/releases/%d/assets/%d" % (repo, rel["id"], asset["id"]))
        api("PATCH", "/repos/%s/releases/%d" % (repo, rel["id"]), {"body": body, "name": title, "target_commitish": target})
    else:
        rel = api("POST", "/repos/%s/releases" % repo, {"tag_name": tag, "target_commitish": target, "name": title, "body": body,
                                                         "draft": True, "prerelease": not stable})
    for path in files:
        name = os.path.basename(path)
        with open(path, "rb") as f:
            data = f.read()
        upload_file(repo, rel["id"], name, data)
        print("uploaded %s (%d MB)" % (name, len(data) >> 20))
    api("PATCH", "/repos/%s/releases/%d" % (repo, rel["id"]), {"draft": False, "prerelease": not stable})
    print("published %s: %s/%s/releases/tag/%s" % (tag, SERVER, repo, tag))


def prune(keep, product):
    """The published nightlies past the newest keep, and the drafts of nightlies older than the newest published one (left
    by failed runs), with their tags; never a stable or a release candidate (the build tools are packages, not releases)"""
    repo = repo_of(product)
    count = lambda r: int(NIGHTLY.match(r["tag_name"]).group(1))
    nightlies = sorted((r for r in releases(repo) if NIGHTLY.match(r["tag_name"])), key=count, reverse=True)
    published = [r for r in nightlies if not r.get("draft")]
    gone = published[keep:] + [r for r in nightlies if r.get("draft") and published and count(r) < count(published[0])]
    for r in gone:
        api("DELETE", "/repos/%s/releases/%d" % (repo, r["id"]))
        api("DELETE", "/repos/%s/tags/%s" % (repo, urllib.parse.quote(r["tag_name"])), missing_ok=True)   # (a draft has no tag yet)
        print("pruned %s" % r["tag_name"])


def download(url, limit=1 << 20):
    """A release file's bytes (SHA256SUMS, its signature: small), from the address without Cloudflare when FORGEJO_UPLOAD_API
    names one (the same server: only the scheme and host change), else from url"""
    up = os.environ.get("FORGEJO_UPLOAD_API")
    if up:
        u, base = urllib.parse.urlsplit(url), urllib.parse.urlsplit(up)
        url = urllib.parse.urlunsplit((base.scheme, base.netloc, u.path, u.query, ""))
    headers = {"User-Agent": "hookshot-release"}
    if os.environ.get("RELEASE_TOKEN"):
        headers["Authorization"] = "token " + os.environ["RELEASE_TOKEN"]
    try:
        with _OPENER.open(urllib.request.Request(url, headers=headers), timeout=120) as r:
            data = r.read(limit + 1)
    except (urllib.error.URLError, OSError) as e:
        fail("%s: %s" % (url, e))
    if len(data) > limit:
        fail("%s: larger than %d bytes" % (url, limit))
    return data


class _TokenStaysHome(urllib.request.HTTPRedirectHandler):
    """The token goes to the forge only. Forgejo answers a release file with a redirect to a signed link of its file store
    (Cloudflare R2), which refuses a request that also carries a token (HTTP 400); urllib would pass the header on."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


_OPENER = urllib.request.build_opener(_TokenStaysHome)


def artifacts(run_id, names, out, product, limit=4 << 30):
    """The named artifacts of workflow run run_id (its build jobs' files: upload-artifact's), each unpacked into out. From
    the address without Cloudflare when FORGEJO_UPLOAD_API names one, as download does: through Cloudflare, as
    download-artifact fetches them, they come at about 1 MB/s, a minute and more for a builder. Each name must be the run's
    once, and each file in it a plain name that no other has; nothing is written into out until every one is fetched"""
    repo = repo_of(product)
    # (the run's list; Forgejo gives each artifact's archive_download_url under its public address, which download changes)
    listed = api("GET", "/repos/%s/actions/runs/%d/artifacts?limit=50" % (repo, run_id), upload=True) or []
    items = (listed.get("artifacts") or []) if isinstance(listed, dict) else listed
    files = {}
    for name in names:
        found = [a for a in items if a.get("name") == name and not a.get("expired")]
        if len(found) != 1:
            fail("run %d has %d artifacts named %s, not one" % (run_id, len(found), name))
        data = download(found[0]["archive_download_url"], limit=limit)
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    base = info.filename
                    if not base or base != os.path.basename(base) or "\\" in base or base in (".", ".."):
                        fail("%s: %r is not a plain file name" % (name, info.filename))
                    if base in files:
                        fail("%s: %s is in two artifacts" % (name, base))
                    files[base] = z.read(info)
        except zipfile.BadZipFile as e:
            fail("%s: not a zip (%s)" % (name, e))
        print("%s: %d MB" % (name, len(data) >> 20), flush=True)
    os.makedirs(out, exist_ok=True)
    for base, data in sorted(files.items()):
        with open(os.path.join(out, base), "wb") as f:
            f.write(data)
    return sorted(files)


def released_as(commit, product, root=ROOT, but=None):
    """The tag of the published release CI made of commit (a nightly, or for a stable its release candidate), or None.
    Forgejo's list says a release's tag, git (the tags fetched) which commit it is. CI publishes a release only when every
    job of its run passed, and signs its SHA256SUMS: a release of commit is taken only with SHA256SUMS signed by a key the
    launcher trusts and naming exactly its files. One that is not stops this (fail): a bad release of the commit is never
    passed over"""
    first = PRODUCTS[product]["first_major"]
    keys = trusted_keys(root)
    for rel in releases(repo_of(product)):
        tag = rel["tag_name"]
        if rel.get("draft") or tag == but or channel_of(tag, first) is None:
            continue
        m = NIGHTLY.match(tag)
        if m and not commit.startswith(m.group(2)):
            continue
        if git("rev-list", "-n", "1", "refs/tags/" + tag, root=root, check=False) != commit:
            continue
        assets = {a["name"]: a for a in rel.get("assets") or []}
        if SUMS not in assets or SIG not in assets:
            fail("%s, a release of %s: no %s and %s" % (tag, commit[:8], SUMS, SIG))
        sums = download(assets[SUMS]["browser_download_url"])
        try:
            der = base64.b64decode(download(assets[SIG]["browser_download_url"]).strip(), validate=True)
        except ValueError:
            fail("%s, a release of %s: %s is not base64" % (tag, commit[:8], SIG))
        if not keys:
            fail("no key to check %s with (Core/ReleaseTrust.cs, scripts/release_keys.json)" % tag)
        if not verify_sig(sums, der, keys):
            fail("%s, a release of %s: its %s is not signed by a trusted key" % (tag, commit[:8], SUMS))
        named = set(read_sums(sums.decode("utf-8", "replace")))
        files = set(assets) - {SUMS, SIG}
        if named != files:
            fail("%s, a release of %s: %s names %s, the release has %s"
                 % (tag, commit[:8], SUMS, ", ".join(sorted(named)) or "nothing", ", ".join(sorted(files)) or "nothing"))
        return tag
    return None


# ---- commands ----

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--product", choices=sorted(PRODUCTS), default=None, help="(default: the repository this file is in)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("next")
    s.add_argument("--tag")
    s = sub.add_parser("check-tag")
    s.add_argument("tag")
    s.add_argument("--releases", help="the releases as Forgejo's API lists them (a JSON file), instead of asking it")
    s.add_argument("--main", default="origin/main")
    sub.add_parser("nightly-name")
    sub.add_parser("nightly-news")
    sub.add_parser("nightly-age")
    s = sub.add_parser("notes")
    s.add_argument("tag")
    s.add_argument("--out")
    s = sub.add_parser("sums")
    s.add_argument("files", nargs="+")
    s.add_argument("--out", required=True)
    s = sub.add_parser("sign")
    s.add_argument("file")
    s.add_argument("--key", required=True)
    s.add_argument("--out", required=True)
    s = sub.add_parser("verify")
    s.add_argument("file")
    s.add_argument("--sig")
    s.add_argument("--pub", action="append")
    s.add_argument("--files")
    s = sub.add_parser("keygen")
    s.add_argument("out")
    s = sub.add_parser("key-id")
    s.add_argument("pem")
    s = sub.add_parser("publish")
    s.add_argument("tag")
    s.add_argument("--target", required=True)
    s.add_argument("--notes", required=True)
    s.add_argument("files", nargs="+")
    s = sub.add_parser("prune")
    s.add_argument("--keep", type=int, default=5)
    sub.add_parser("channels")
    s = sub.add_parser("released-as")
    s.add_argument("commit")
    s.add_argument("--not", dest="but")
    s = sub.add_parser("git-cliff")
    s.add_argument("folder")
    s = sub.add_parser("artifacts")
    s.add_argument("out")
    s.add_argument("--run", type=int, required=True)
    s.add_argument("names", nargs="+")
    a = p.parse_args(argv)
    product = a.product or product_of()
    first = PRODUCTS[product]["first_major"]

    if a.cmd == "next":
        existing = [r["tag_name"] for r in releases(repo_of(product)) if not r.get("draft")] if not a.tag else tags_merged()
        low, last, level = required(first)
        tag = a.tag or next_tag(existing + tags_merged(), first)
        print("since %s: %s, so at least %s" % (last or "the start", level or "nothing a player sees", low))
        print("next release candidate: %s (then %s on the release candidate that was good)\n" % (tag, tag.split("-rc.")[0]))
        print(notes(tag, product))
    elif a.cmd == "check-tag":
        if a.releases:
            with open(a.releases, encoding="utf-8") as f:
                existing = [r["tag_name"] for r in json.load(f)]
        else:
            existing = [r["tag_name"] for r in releases(repo_of(product)) if not r.get("draft")]
        problems = check_tag(a.tag, existing, first, main=a.main)
        for problem in problems:
            print("error: " + problem, file=sys.stderr)
        if problems:
            print("RELEASING.md, \"When CI refuses a tag\", says what to do.", file=sys.stderr)
            return 1
        print("%s: ok (%s channel)" % (a.tag, channel_of(a.tag, first)))
    elif a.cmd == "nightly-name":
        print(nightly_name(product))
    elif a.cmd == "nightly-news":
        print("yes" if nightly_news(product) else "no")
    elif a.cmd == "nightly-age":
        age = nightly_age(releases(repo_of(product)))
        print("none" if age is None else age)
    elif a.cmd == "notes":
        text = notes(a.tag, product)
        if a.out:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        else:
            sys.stdout.write(text)
    elif a.cmd == "sums":
        lines = []
        for path in a.files:
            name = os.path.basename(path)
            if name in (SUMS, SIG):
                continue
            lines.append("%s  %s\n" % (sha256_file(path), name))
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(sorted(lines, key=lambda l: l[66:]))
    elif a.cmd == "sign":
        text = sign(a.file, a.key)
        with open(a.out, "w", encoding="ascii", newline="\n") as f:
            f.write(text)
    elif a.cmd == "verify":
        keys = [spki_der(k) for k in a.pub] if a.pub else trusted_keys()
        if not keys:
            fail("no key to check with: the launcher trusts no key yet (Core/ReleaseTrust.cs, scripts/release_keys.json), and no --pub")
        with open(a.file, "rb") as f:
            data = f.read()
        with open(a.sig or a.file + ".sig", encoding="ascii") as f:
            der = base64.b64decode(f.read().strip())
        signer = verify_sig(data, der, keys)
        if not signer:
            fail("%s: not signed by a trusted key" % a.file)
        print("signed by %s" % key_id(signer))
        if a.files:
            for name, want in read_sums(data.decode("utf-8")).items():
                if sha256_file(os.path.join(a.files, name)) != want:
                    fail("%s: not the SHA-256 %s names" % (name, a.file))
            print("every file as %s says" % a.file)
    elif a.cmd == "keygen":
        os.makedirs(a.out, exist_ok=True)
        private, public = os.path.join(a.out, "release.pem"), os.path.join(a.out, "release.pub.pem")
        if os.path.exists(private):
            fail("%s is there already: never over a key" % private)
        pem = openssl("genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-pkeyopt", "ec_param_enc:named_curve")
        fd = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
        spki = spki_der(private)
        with open(public, "w") as f:
            f.write(pem_of(spki))
        b64 = base64.b64encode(spki).decode()
        print("%s (private: the RELEASE_SIGNING_KEY secret, and a safe copy offline) and %s; key id %s" % (private, public, key_id(spki)))
        print("for the launcher's Core/ReleaseTrust.cs, ReleaseKeys.BuiltIn:\n    ReleaseKey.FromSpki(\"%s\")," % b64)
        print("for Hookshot's scripts/release_keys.json, \"keys\":\n    \"%s\"" % b64)
    elif a.cmd == "key-id":
        spki = spki_der(a.pem)
        print("%s %s" % (key_id(spki), base64.b64encode(spki).decode()))
    elif a.cmd == "publish":
        publish(a.tag, a.target, a.notes, a.files, product)
    elif a.cmd == "prune":
        prune(a.keep, product)
    elif a.cmd == "git-cliff":
        print(fetch_git_cliff(a.folder))
    elif a.cmd == "artifacts":
        for name in artifacts(a.run, a.names, a.out, product):
            print(os.path.join(a.out, name))
    elif a.cmd == "released-as":
        if not re.match(r"^[0-9a-f]{40}$", a.commit):
            fail("%s: a full commit hash is needed" % a.commit)
        print(released_as(a.commit, product, but=a.but) or "")
    elif a.cmd == "channels":
        rels = releases(repo_of(product))
        for c in CHANNELS:
            print("%-8s %s" % (c, newest(rels, c, first) or "(none)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
