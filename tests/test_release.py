"""scripts/release.py (docs/releases.md, RELEASING.md; the same file in MagicBeanDev/HookshotLauncher), with no network: keys,
SHA256SUMS and its signature; the channels as the launcher reads them from the release list; the version a tag must reach
(the bump from the commits since the last stable), in a git repository made here; the nightly's name; and publish and
prune against a fake Forgejo on 127.0.0.1 (a draft first, every file uploaded and checked, published last; only nightlies
pruned); the release page (the launcher's download links, Hookshot's "download the launcher" notice, per channel); and the
release a tag's commit already has (released-as: found by its tag's commit, taken only signed and whole).
Needs git and the openssl command line.

    python -I tests/test_release.py
"""
import base64
import contextlib
import hashlib
import http.server
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = release.main([str(a) for a in args])
    return code, out.getvalue()


class Keys(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="release-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        run("keygen", self.dir / "keys")
        self.key, self.pub = self.dir / "keys" / "release.pem", self.dir / "keys" / "release.pub.pem"

    def test_keygen_never_overwrites_and_keeps_the_key_private(self):
        with self.assertRaises(SystemExit):
            run("keygen", self.dir / "keys")
        if os.name != "nt":
            self.assertEqual(self.key.stat().st_mode & 0o077, 0)

    def test_sums_sign_verify(self):
        files = self.dir / "files"
        files.mkdir()
        (files / "HookshotLauncher-v1.0.0-x86_64.AppImage").write_bytes(b"launcher")
        (files / "Hookshot-v3.0.0-x86_64.AppImage").write_bytes(b"builder")
        run("sums", *files.iterdir(), "--out", files / "SHA256SUMS")
        sums = (files / "SHA256SUMS").read_text()
        self.assertEqual(sums.splitlines()[0], "%s  Hookshot-v3.0.0-x86_64.AppImage" % hashlib.sha256(b"builder").hexdigest())
        run("sign", files / "SHA256SUMS", "--key", self.key, "--out", files / "SHA256SUMS.sig")
        code, out = run("verify", files / "SHA256SUMS", "--pub", self.pub, "--files", files)
        self.assertEqual(code, 0)
        self.assertIn("every file", out)
        # (a file changed, the list changed, another key)
        (files / "Hookshot-v3.0.0-x86_64.AppImage").write_bytes(b"other")
        with self.assertRaises(SystemExit):
            run("verify", files / "SHA256SUMS", "--pub", self.pub, "--files", files)
        (files / "SHA256SUMS").write_text(sums.replace("Hookshot-v3", "Hookshot-v4"))
        with self.assertRaises(SystemExit):
            run("verify", files / "SHA256SUMS", "--pub", self.pub)
        (files / "SHA256SUMS").write_text(sums)
        run("keygen", self.dir / "other")
        with self.assertRaises(SystemExit):
            run("verify", files / "SHA256SUMS", "--pub", self.dir / "other" / "release.pub.pem")

    def test_the_launcher_test_fixture_is_this_format(self):
        # (the launcher's tests/fixtures/release are signed the same way: a base64 DER signature of SHA256SUMS)
        der = base64.b64decode(release.sign(str(self.pub), str(self.key)))
        self.assertTrue(release.verify_sig(self.pub.read_bytes(), der, [release.spki_der(str(self.pub))]))

    def test_the_trusted_keys(self):
        trusted = release.trusted_keys()
        test_key = ROOT / "tests" / "fixtures" / "release" / "test-key.pub.pem"
        if test_key.is_file():
            self.assertNotIn(release.spki_der(str(test_key)), trusted, "the public test key is trusted")
        cs = self.dir / "Core" / "ReleaseTrust.cs"
        cs.parent.mkdir()
        cs.write_text('x\n    public static readonly IReadOnlyList<ReleaseKey> BuiltIn = new ReleaseKey[]\n    {\n'
                      '        ReleaseKey.FromSpki("QUJD"),\n    };\n')
        self.assertEqual(release.trusted_keys(str(self.dir)), [b"ABC"])
        self.assertEqual(release.product_of(str(self.dir)), "launcher")
        # (comments with ; { } before, inside and after the initializer change nothing; a commented-out key is no key)
        cs.write_text('/* BuiltIn = { ReleaseKey.FromSpki("WFla") }; */\n'
                      '    // the keys; one per line { as keygen prints them }\n'
                      '    public static readonly IReadOnlyList<ReleaseKey> BuiltIn = new ReleaseKey[]\n    {\n'
                      '        // id 5e18330371d7f5aa, keygen 2026-11-13; RELEASING.md { "One-time setup" }\n'
                      '        ReleaseKey.FromSpki("QUJD"),   /* the first; } */\n'
                      '        // ReleaseKey.FromSpki("WFla"),\n'
                      '        ReleaseKey.FromSpki( "REVG" ),\n    };\n'
                      '    static readonly string Other = "ReleaseKey.FromSpki(\\"R0hJ\\")";\n')
        self.assertEqual(release.trusted_keys(str(self.dir)), [b"ABC", b"DEF"])
        cs.write_text('class ReleaseKeys {}\n')
        self.assertEqual(release.trusted_keys(str(self.dir)), [])
        (self.dir / "scripts").mkdir()
        (self.dir / "scripts" / "release_keys.json").write_text('{"keys": ["REVG"]}')
        cs.unlink()
        self.assertEqual(release.trusted_keys(str(self.dir)), [b"DEF"])
        self.assertEqual(release.product_of(str(self.dir)), "hookshot")


class Channels(unittest.TestCase):
    def test_the_version_order(self):
        order = ["v3.0.0-rc.1", "v3.0.0-rc.2", "v3.0.0-rc.10", "v3.0.0", "v3.0.1-rc.1", "v3.0.1", "v3.1.0", "v10.0.0"]
        self.assertEqual(sorted(order, key=release.version_key), order)
        for tag, channel in (("v3.0.0", "stable"), ("v3.1.0-rc.2", "rc"), ("nightly-412-1a2b3c4d", "nightly"), ("v2.9.0", None),
                             ("v3.0.0-3-g1a2b3c4", None), ("dev", None), ("tools", None)):
            self.assertEqual(release.channel_of(tag, 3), channel, tag)
        self.assertEqual(release.channel_of("v1.0.0", 1), "stable")

    def test_what_each_channel_offers(self):
        rels = [{"tag_name": t, "draft": d, "prerelease": p} for t, d, p in (
            ("v3.0.0", False, False), ("v3.1.0-rc.1", False, True), ("v3.1.0-rc.2", True, True), ("v3.2.0", True, False),
            ("nightly-9-aaaaaaaa", False, True), ("nightly-12-bbbbbbbb", False, True), ("nightly-100-cccccccc", True, True),
            ("tools", False, True), ("v2.9.0", False, False))]
        self.assertEqual(release.newest(rels, "stable", 3), "v3.0.0")        # (drafts are not there yet)
        self.assertEqual(release.newest(rels, "rc", 3), "v3.1.0-rc.1")
        self.assertEqual(release.newest(rels, "nightly", 3), "nightly-12-bbbbbbbb")   # (by count, not by text)
        rels.append({"tag_name": "v3.1.0", "draft": False, "prerelease": False})
        self.assertEqual(release.newest(rels, "rc", 3), "v3.1.0")          # (rc offers the stable once it is out)
        # (pulling a bad version: deleted, or back to a draft, the channel falls back to the one before)
        rels[-1]["draft"] = True
        self.assertEqual(release.newest(rels, "stable", 3), "v3.0.0")


class Bump(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="release-git-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.git("init", "-q", "-b", "main")
        self.commit("chore: start")

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "tag.gpgsign=false",
                               *args], cwd=self.dir, check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, subject, body=""):
        self.git("commit", "-q", "--allow-empty", "-m", subject, *(["-m", body] if body else []))

    def check(self, tag, existing=()):
        return release.check_tag(tag, list(existing), 3, root=str(self.dir), main="main")

    def test_the_first_release(self):
        self.commit("feat: something")
        self.git("tag", "v2.9.0")
        self.git("tag", "v3.0.0-rc.1")
        self.assertEqual(self.check("v3.0.0-rc.1"), [])
        self.assertIn("is not vX.Y.Z", self.check("v2.9.0")[0])   # (Hookshot's numbers are not Hookshot's)
        self.assertEqual(release.next_tag([], 3, root=str(self.dir)), "v3.0.0-rc.1")

    def test_the_bump(self):
        self.git("tag", "v3.0.0")
        self.commit("fix(vk): a fix")
        self.assertEqual(release.required(3, str(self.dir))[:3:2], ("v3.0.1", "patch"))
        self.commit("feat(menu): a row")
        self.assertEqual(release.required(3, str(self.dir))[0], "v3.1.0")
        self.git("tag", "v3.0.1-rc.1")
        self.assertIn("at least v3.1.0", self.check("v3.0.1-rc.1", ["v3.0.0"])[0])
        self.git("tag", "v3.1.0-rc.1")
        self.assertEqual(self.check("v3.1.0-rc.1", ["v3.0.0"]), [])
        self.git("tag", "v4.0.0-rc.1")
        self.assertEqual(self.check("v4.0.0-rc.1", ["v3.0.0"]), [])            # (higher than needed is fine)
        self.commit("refactor(vk)!: a new interface")
        self.assertEqual(release.required(3, str(self.dir))[0], "v4.0.0")
        self.commit("fix: x", "BREAKING CHANGE: the options file")
        self.assertEqual(release.bump_of([("fix: x", "BREAKING CHANGE: the options file")]), "major")
        self.assertEqual(release.bump_of([("docs: x", ""), ("Merge branch", "")]), None)

    def test_a_stable_on_its_release_candidate(self):
        self.git("tag", "v3.0.0")
        self.commit("feat: a")
        self.git("tag", "v3.1.0-rc.1")
        self.assertEqual(release.next_tag(["v3.0.0", "v3.1.0-rc.1"], 3, root=str(self.dir)), "v3.1.0-rc.2")
        self.git("tag", "v3.1.0")                         # (the same commit: the normal path)
        self.assertEqual(self.check("v3.1.0", ["v3.0.0", "v3.1.0-rc.1"]), [])
        self.assertIn("not above every release", self.check("v3.1.0-rc.1", ["v3.0.0", "v3.1.0-rc.1", "v3.1.0"])[0])
        self.assertEqual(release.next_tag(["v3.0.0", "v3.1.0-rc.1", "v3.1.0"], 3, root=str(self.dir)), "v3.1.1-rc.1")

    def test_only_from_main(self):
        self.git("tag", "v3.0.0")
        self.git("switch", "-q", "-c", "side")
        self.commit("fix: on a branch")
        self.git("tag", "v3.0.1")
        self.assertIn("not on main", self.check("v3.0.1", ["v3.0.0"])[0])
        self.assertIn("no tag", self.check("v3.0.2", ["v3.0.0"])[0])

    def test_the_nightly_name(self):
        self.commit("fix: a")
        with mock.patch.dict(release.PRODUCTS["launcher"], since=None):
            name = release.nightly_name("launcher", root=str(self.dir))
        self.assertRegex(name, r"^nightly-2-[0-9a-f]{8}$")
        self.assertEqual(release.channel_of(name, 1), "nightly")

    def test_the_notes_start_after_the_previous_tag(self):
        self.git("tag", "v3.0.0")
        self.commit("feat: a")
        self.git("tag", "v3.1.0-rc.1")
        self.commit("fix: b")
        self.git("tag", "v3.1.0-rc.2")
        self.git("tag", "v3.1.0")
        self.assertEqual(release.previous_tag("v3.1.0-rc.2", 3, str(self.dir)), "v3.1.0-rc.1")
        self.assertEqual(release.previous_tag("v3.1.0", 3, str(self.dir)), "v3.0.0")   # (a stable: since the stable before)


    def cliff_stub(self, folder):
        """The environment for a git-cliff in folder that prints its arguments, one a line. Windows runs no #! script: a
        .cmd hands its arguments to Python. The .cmd stays ASCII and reads Python's and the script's paths from the
        environment, which cmd.exe keeps as Unicode: written into the file, a path with an accented letter was read in
        the console's code page and Python got a broken path. It prints in UTF-8, as git-cliff does (a pipe's default
        on Windows is the ANSI code page)"""
        if os.name == "nt":
            script = folder / "git-cliff-stub.py"
            script.write_text("import sys\nsys.stdout.reconfigure(encoding='utf-8')\nfor a in sys.argv[1:]: print(a)\n",
                              encoding="utf-8")
            stub = folder / "git-cliff-stub.cmd"
            stub.write_text('@"%GIT_CLIFF_STUB_PYTHON%" -I "%GIT_CLIFF_STUB_SCRIPT%" %*\n', encoding="ascii")
            return {"GIT_CLIFF": str(stub), "GIT_CLIFF_STUB_PYTHON": sys.executable, "GIT_CLIFF_STUB_SCRIPT": str(script)}
        stub = folder / "git-cliff-stub"
        stub.write_text("#!/bin/sh\nfor a in \"$@\"; do echo \"$a\"; done\n", encoding="utf-8")
        stub.chmod(0o755)
        return {"GIT_CLIFF": str(stub)}

    def test_the_first_notes_give_git_cliff_no_range(self):
        # (git-cliff takes a lone ref for a range and stops: SetCommitRangeError("HEAD", unable to parse OID), the
        # launcher's first nightlies. With no tag before and no first commit, it is given no range: the whole history)
        self.commit("feat: a")
        stub = self.cliff_stub(self.dir)
        with mock.patch.dict(os.environ, stub), mock.patch.dict(release.PRODUCTS["launcher"], since=None):
            args = release.notes("nightly-2-0123abcd", "launcher", root=str(self.dir)).split()
        self.assertEqual(args[-2:], ["--strip", "all"])
        self.git("tag", "v1.0.0")
        self.commit("fix: b")
        with mock.patch.dict(os.environ, stub), mock.patch.dict(release.PRODUCTS["launcher"], since=None):
            args = release.notes("nightly-3-0123abcd", "launcher", root=str(self.dir)).split()
        self.assertEqual(args[-1], "v1.0.0..HEAD")

    def test_the_git_cliff_stand_in_runs_from_a_unicode_path(self):
        # (a temporary folder under a user name such as "Zoë": the stand-in still gets its arguments through)
        folder = Path(tempfile.mkdtemp(prefix="release-cliff-Zoë-"))
        self.addCleanup(shutil.rmtree, folder, True)
        self.commit("feat: a")
        with mock.patch.dict(os.environ, self.cliff_stub(folder)), mock.patch.dict(release.PRODUCTS["launcher"], since=None):
            args = release.notes("nightly-2-0123abcd", "launcher", root=str(self.dir)).split()
        self.assertEqual(args[-2:], ["--strip", "all"])

class ReleasePage(unittest.TestCase):
    """The release page publish writes: the launcher's starts with big download links to its own files; Hookshot's with "to
    play, get the Hookshot Launcher", linking hookshot.magicbean.dev's newest launcher of the same channel, and "don't download the
    files below" (above the builder files)"""

    LAUNCHER = ("HookshotLauncher-%s-windows-x64-setup.exe", "HookshotLauncher-%s-windows-x64-portable.zip",
                "HookshotLauncher-%s-x86_64.AppImage", "SHA256SUMS", "SHA256SUMS.sig")
    HOOKSHOT = ("HookshotBuilder-%s-windows-x64.zip", "Hookshot-%s-x86_64.AppImage", "tools.lock", "SHA256SUMS", "SHA256SUMS.sig")

    def page(self, tag, product, files):
        names = [f % tag if "%s" in f else f for f in files]
        return release.release_page(tag, product, "## %s\n\n### Fixes\n\n- a fix\n" % tag, names, "MagicBeanDev/HookshotLauncher")

    def test_the_launcher_page_links_its_own_files(self):
        for tag, channel in (("v1.0.0", "stable"), ("v1.1.0-rc.2", "rc"), ("nightly-10-968b7963", "nightly")):
            with self.subTest(tag):
                page = self.page(tag, "launcher", self.LAUNCHER)
                head, notes = page.split("\n---\n", 1)
                base = "https://git-cdn.magicbean.dev/MagicBeanDev/HookshotLauncher/releases/download/%s/HookshotLauncher-%s" % (tag, tag)
                self.assertEqual(head.strip().split("\n\n")[:4], [
                    "# ⬇️ Download Hookshot Launcher",
                    "### [🪟 &nbsp;Download for Windows](%s-windows-x64-setup.exe)" % base,
                    "### [🐧 &nbsp;Download for Linux (AppImage)](%s-x86_64.AppImage)" % base,
                    "Windows without installing: [portable zip](%s-windows-x64-portable.zip)" % base])
                self.assertIn(release.CHANNEL_SAYS[channel], head)
                self.assertNotIn("|", head)                     # (no tables: big links)
                self.assertNotIn("SHA256SUMS", head)
                self.assertEqual(notes.strip(), "## %s\n\n### Fixes\n\n- a fix" % tag)   # (git-cliff's notes follow)
        # (a file a release lacks is not linked)
        page = self.page("v1.0.0", "launcher", self.LAUNCHER[2:])
        self.assertIn("Download for Linux", page)
        self.assertNotIn("Download for Windows", page)
        self.assertNotIn("portable zip", page)

    def test_the_hookshot_page_sends_players_to_the_launcher_of_its_channel(self):
        for tag, channel in (("v3.0.0", "stable"), ("v3.0.0-rc.1", "rc"), ("nightly-34-545618fc", "nightly")):
            with self.subTest(tag):
                page = self.page(tag, "hookshot", self.HOOKSHOT)
                head, notes = page.split("\n---\n", 1)
                link = "https://hookshot.magicbean.dev/download/launcher/" + channel
                self.assertEqual(head.strip().split("\n\n")[:5], [
                    "# 🎮 To play, get the Hookshot Launcher",
                    "### [🪟 &nbsp;Download the launcher for Windows](%s/windows)" % link,
                    "### [🐧 &nbsp;Download the launcher for Linux (AppImage)](%s/linux)" % link,
                    "Windows without installing: [portable zip](%s/windows-portable) · [the launcher's newest %s release](%s)"
                    % (link, channel, link),
                    "**Don't download the files below:** they're the builder the launcher installs for you."])
                for other in {"stable", "rc", "nightly"} - {channel}:
                    self.assertNotIn("/download/launcher/" + other, page)
                self.assertNotIn("releases/download", page)   # (no link to a builder file)
                self.assertTrue(notes.strip().startswith("## " + tag))


NIGHTLY_OF = lambda tag: release.NIGHTLY.match(tag)


class FakeForgejo(http.server.BaseHTTPRequestHandler):
    releases, deleted, uploads = [], [], []

    def log_message(self, *a):
        pass

    def answer(self, code, body=None):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    max_items = 50   # (the server's max_response_items: /api/v1/settings/api)
    files, fetched = {}, []   # (the release files under /attachments/<name>, and the hosts they were asked of)

    def do_GET(self):
        if self.path.startswith("/attachments/"):
            self.fetched.append(self.headers.get("Host"))
            data = self.files.get(self.path.rsplit("/", 1)[1])
            if data is None:
                return self.answer(404, {"message": "not found"})
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        # (as Forgejo 17's GET /repos/{owner}/{repo}/releases: drafts only with a writer token; draft= and pre-release= keep
        # only the releases whose field equals the value; limit (default 30, at most max_response_items) and page; newest first)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        rels = sorted(self.releases, key=lambda r: r["id"], reverse=True)
        if not self.headers.get("Authorization"):
            rels = [r for r in rels if not r["draft"]]
        for param, field in (("draft", "draft"), ("pre-release", "prerelease")):
            if param in q:
                rels = [r for r in rels if r[field] == (q[param][0] == "true")]
        limit = min(int(q.get("limit", ["30"])[0]), self.max_items)
        page = int(q.get("page", ["1"])[0])
        self.answer(200, rels[(page - 1) * limit:page * limit])

    def do_POST(self):
        data = self.body()
        if "/assets" in self.path:
            rid = int(self.path.split("/releases/")[1].split("/")[0])
            name = self.path.split("name=")[1]
            payload = data.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
            self.uploads.append((rid, name, payload))
            rel = next(r for r in self.releases if r["id"] == rid)
            rel["assets"].append({"id": len(self.uploads), "name": name, "size": len(payload)})
            return self.answer(201, rel["assets"][-1])
        rel = dict(json.loads(data), id=len(self.releases) + 1, assets=[])
        self.releases.append(rel)
        self.answer(201, rel)

    def do_PATCH(self):
        rid = int(self.path.split("/releases/")[1])
        rel = next(r for r in self.releases if r["id"] == rid)
        rel.update(json.loads(self.body()))
        self.answer(200, rel)

    tags = set()   # (the tags there are: a draft's tag is made when it is published)

    def do_DELETE(self):
        self.deleted.append(self.path)
        if "/tags/" in self.path:
            tag = urllib.parse.unquote(self.path.rsplit("/", 1)[1])
            if tag not in self.tags:
                return self.answer(404, {"message": "tag not found"})
            self.tags.discard(tag)
        elif "/releases/" in self.path and "/assets/" not in self.path:
            FakeForgejo.releases = [r for r in self.releases if r["id"] != int(self.path.rsplit("/", 1)[1])]
        self.answer(204)


class Publish(unittest.TestCase):
    def setUp(self):
        FakeForgejo.releases, FakeForgejo.deleted, FakeForgejo.uploads, FakeForgejo.tags = [], [], [], set()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeForgejo)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.dir = Path(tempfile.mkdtemp(prefix="release-publish-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        env = {"FORGEJO_API": "http://127.0.0.1:%d/api/v1" % self.server.server_port, "RELEASE_TOKEN": "t",
               "GITHUB_REPOSITORY": "MagicBeanDev/Test"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_draft_then_the_files_then_published(self):
        notes = self.dir / "notes.md"
        notes.write_text("## v3.0.0-rc.1\n")
        a, b = self.dir / "Hookshot-v3.0.0-rc.1-x86_64.AppImage", self.dir / "SHA256SUMS"
        a.write_bytes(b"\x7fELF builder")
        b.write_bytes(b"sums\n")
        run("--product", "hookshot", "publish", "v3.0.0-rc.1", "--target", "abc", "--notes", notes, a, b)
        rel = FakeForgejo.releases[0]
        self.assertEqual((rel["tag_name"], rel["draft"], rel["prerelease"], rel["name"]), ("v3.0.0-rc.1", False, True, "Hookshot v3.0.0-rc.1"))
        self.assertEqual([(n, p) for _, n, p in FakeForgejo.uploads], [(a.name, b"\x7fELF builder"), ("SHA256SUMS", b"sums\n")])
        with self.assertRaises(SystemExit):   # (a published version's files never change)
            run("--product", "hookshot", "publish", "v3.0.0-rc.1", "--target", "abc", "--notes", notes, a)
        bad = self.dir / "image.bin"
        bad.write_bytes(b"x")
        with self.assertRaises(SystemExit):
            run("--product", "hookshot", "publish", "v3.0.1-rc.1", "--target", "abc", "--notes", notes, bad)

    def test_the_page_on_the_release(self):
        # (publish puts the notes under the page's header: Hookshot's says to download the launcher of its channel)
        notes = self.dir / "notes.md"
        notes.write_text("### Fixes\n\n- a fix\n")
        f = self.dir / "HookshotBuilder-nightly-34-545618fc-windows-x64.zip"
        f.write_bytes(b"PK zip")
        run("--product", "hookshot", "publish", "nightly-34-545618fc", "--target", "abc", "--notes", notes, f)
        body = FakeForgejo.releases[0]["body"]
        self.assertTrue(body.startswith("# 🎮 To play, get the Hookshot Launcher\n"))
        self.assertIn("https://hookshot.magicbean.dev/download/launcher/nightly/windows", body)
        self.assertIn("### Fixes\n\n- a fix\n", body)
        # (the launcher's: its own files, on its repository)
        FakeForgejo.releases, FakeForgejo.uploads = [], []
        f = self.dir / "HookshotLauncher-v1.0.0-rc.1-windows-x64-setup.exe"
        f.write_bytes(b"MZ setup")
        run("--product", "launcher", "publish", "v1.0.0-rc.1", "--target", "abc", "--notes", notes, f)
        body = FakeForgejo.releases[0]["body"]
        self.assertTrue(body.startswith("# ⬇️ Download Hookshot Launcher\n"))
        self.assertIn("### [🪟 &nbsp;Download for Windows](https://git-cdn.magicbean.dev/MagicBeanDev/Test/releases/download/"
                      "v1.0.0-rc.1/HookshotLauncher-v1.0.0-rc.1-windows-x64-setup.exe)", body)
        self.assertIn(release.CHANNEL_SAYS["rc"], body)

    def test_a_draft_left_by_a_failed_run_is_reused(self):
        FakeForgejo.releases = [{"id": 1, "tag_name": "v3.0.0", "draft": True, "prerelease": False,
                                 "assets": [{"id": 9, "name": "half", "size": 1}]}]
        notes = self.dir / "notes.md"
        notes.write_text("notes\n")
        f = self.dir / "SHA256SUMS"
        f.write_text("x\n")
        run("--product", "hookshot", "publish", "v3.0.0", "--target", "abc", "--notes", notes, f)
        self.assertEqual(len(FakeForgejo.releases), 1)
        self.assertIn("/api/v1/repos/MagicBeanDev/Test/releases/1/assets/9", FakeForgejo.deleted)
        self.assertEqual((FakeForgejo.releases[0]["draft"], FakeForgejo.releases[0]["prerelease"]), (False, False))

    def releases_of(self, *rows):
        """FakeForgejo's releases from (tag, draft, prerelease) rows; a published one has its tag"""
        FakeForgejo.releases = [{"id": i + 1, "tag_name": t, "draft": d, "prerelease": p, "assets": []}
                                for i, (t, d, p) in enumerate(rows)]
        FakeForgejo.tags = {t for t, d, _ in rows if not d}

    def test_prune_keeps_the_newest_nightlies_and_everything_else(self):
        nightly = lambda n: "nightly-%d-%08x" % (n, n)
        self.releases_of(*[(nightly(n), False, True) for n in (3, 12, 7, 100, 50, 9, 1)],
                         ("tools", False, True), ("v3.0.0", False, False), ("v3.1.0-rc.1", False, True), ("v2.9.0", False, False),
                         (nightly(4), True, True), (nightly(101), True, True))   # (drafts a failed run left; 101: still to come)
        run("--product", "hookshot", "prune", "--keep", "5")
        left = sorted(r["tag_name"] for r in FakeForgejo.releases)
        self.assertEqual(left, sorted([nightly(n) for n in (101, 100, 50, 12, 9, 7)] + ["tools", "v3.0.0", "v3.1.0-rc.1", "v2.9.0"]))
        self.assertIn("/api/v1/repos/MagicBeanDev/Test/tags/nightly-1-00000001", FakeForgejo.deleted)
        self.assertIn("/api/v1/repos/MagicBeanDev/Test/tags/nightly-3-00000003", FakeForgejo.deleted)
        self.assertEqual(FakeForgejo.tags, {nightly(n) for n in (100, 50, 12, 9, 7)} | {"tools", "v3.0.0", "v3.1.0-rc.1", "v2.9.0"})
        kept = [r["id"] for r in FakeForgejo.releases if not NIGHTLY_OF(r["tag_name"])]
        self.assertFalse([p for p in FakeForgejo.deleted if p.rsplit("/", 1)[1] in [str(i) for i in kept] + ["tools", "v3.0.0", "v3.1.0-rc.1", "v2.9.0"]])

    def test_every_release_on_every_page(self):
        # (more than a page, at a smaller max_response_items than release.py asks for: pages until an empty one)
        FakeForgejo.max_items = 20
        self.addCleanup(setattr, FakeForgejo, "max_items", 50)
        self.releases_of(*[("nightly-%d-%08x" % (n, n), n % 7 == 0, True) for n in range(1, 46)], ("v3.0.0", False, False))
        got = release.releases("MagicBeanDev/Test")
        self.assertEqual(len(got), 46)
        self.assertEqual(sum(r["draft"] for r in got), 6)
        self.assertEqual(release.newest(got, "nightly", 3), "nightly-45-0000002d")
        self.assertEqual(release.newest(got, "stable", 3), "v3.0.0")

    def test_check_tag_against_the_published_releases(self):
        # (check-tag asks Forgejo: a tag at or below a published release is refused; a draft is no release yet)
        repo = Path(tempfile.mkdtemp(prefix="release-git-"))
        self.addCleanup(shutil.rmtree, repo, True)
        g = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "tag.gpgsign=false",
                                       *a], cwd=repo, check=True, capture_output=True)
        g("init", "-q", "-b", "main")
        g("commit", "-q", "--allow-empty", "-m", "feat: a")
        g("tag", "v3.0.0-rc.1")
        self.releases_of(("v3.0.0", False, False), ("v3.1.0-rc.1", True, True), ("tools", False, True))
        with mock.patch.object(release, "ROOT", str(repo)), mock.patch.object(release, "git",
                lambda *a, root=None, check=True, _g=release.git: _g(*a, root=str(repo), check=check)):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(run("--product", "hookshot", "check-tag", "v3.0.0-rc.1", "--main", "main")[0], 1)
            self.assertIn("not above every release there is: v3.0.0", err.getvalue())
            FakeForgejo.releases[0]["draft"] = True   # (back to a draft: no longer in the way)
            self.assertEqual(run("--product", "hookshot", "check-tag", "v3.0.0-rc.1", "--main", "main")[0], 0)

    def test_publish_refuses_a_published_tag_on_a_later_page(self):
        self.releases_of(("v3.0.0", False, False), *[("nightly-%d-%08x" % (n, n), False, True) for n in range(1, 80)])
        notes = self.dir / "notes.md"
        notes.write_text("notes\n")
        f = self.dir / "SHA256SUMS"
        f.write_text("x\n")
        with self.assertRaises(SystemExit) as e:
            run("--product", "hookshot", "publish", "v3.0.0", "--target", "abc", "--notes", notes, f)
        self.assertIn("already published", str(e.exception))
        self.assertEqual(FakeForgejo.uploads, [])


class ReleasedAs(unittest.TestCase):
    """released-as: a tag's commit that CI released already (its nightly; for a stable, its release candidate). Found by the
    commit its tag is, and taken only when its SHA256SUMS is signed by a trusted key and names exactly its files; a
    release of the commit that is not stops the run"""

    def setUp(self):
        FakeForgejo.releases, FakeForgejo.files, FakeForgejo.fetched = [], {}, []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeForgejo)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.dir = Path(tempfile.mkdtemp(prefix="release-as-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.base = "http://127.0.0.1:%d" % self.server.server_port
        patcher = mock.patch.dict(os.environ, {"FORGEJO_API": self.base + "/api/v1", "RELEASE_TOKEN": "t",
                                               "GITHUB_REPOSITORY": "MagicBeanDev/Test"})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("FORGEJO_UPLOAD_API", None)
        run("keygen", self.dir / "keys")
        run("keygen", self.dir / "other")
        self.repo = self.dir / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        spki = release.spki_der(str(self.dir / "keys" / "release.pub.pem"))
        (self.repo / "scripts" / "release_keys.json").write_text(json.dumps({"keys": [base64.b64encode(spki).decode()]}))
        self.git("init", "-q", "-b", "main")
        self.git("commit", "-q", "--allow-empty", "-m", "feat: a")
        self.a = self.git("rev-parse", "HEAD")
        self.git("commit", "-q", "--allow-empty", "-m", "fix: b")
        self.b = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "tag.gpgsign=false",
                               *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def release(self, tag, commit, files=("Hookshot-%s-x86_64.AppImage", "HookshotBuilder-%s-windows-x64.zip", "tools.lock"),
                key="keys", draft=False, sums_of=None, sig=None):
        """A release of commit as CI publishes it: its files, SHA256SUMS over them (or over sums_of), signed with key"""
        self.git("tag", tag, commit)
        names = [f % tag if "%s" in f else f for f in files]
        sums = "".join("%s  %s\n" % (hashlib.sha256(n.encode()).hexdigest(), n) for n in sorted(sums_of or names))
        sums_file = self.dir / ("sums-" + tag)
        sums_file.write_bytes(sums.encode())   # (the bytes served: in text mode Windows would sign "\r\n" lines)
        rid = len(FakeForgejo.releases) + 1
        assets = []
        for name, data in [(n, n.encode()) for n in names] + [("SHA256SUMS", sums.encode())] + \
                          [("SHA256SUMS.sig", sig if sig is not None else
                            release.sign(str(sums_file), str(self.dir / key / "release.pem")).encode())]:
            FakeForgejo.files["%d-%s" % (rid, name)] = data
            assets.append({"id": len(assets) + 1, "name": name, "size": len(data),
                           "browser_download_url": "%s/attachments/%d-%s" % (self.base, rid, name)})
        FakeForgejo.releases.append({"id": rid, "tag_name": tag, "draft": draft, "prerelease": True, "assets": assets})

    def released_as(self, commit, but=None):
        return release.released_as(commit, "hookshot", root=str(self.repo), but=but)

    def nightly(self, n, commit):
        return "nightly-%d-%s" % (n, commit[:8])

    def test_the_signed_nightly_of_the_commit(self):
        self.assertIsNone(self.released_as(self.b))   # (none at all: the full build)
        self.release(self.nightly(1, self.a), self.a)
        self.release(self.nightly(2, self.b), self.b, draft=True)   # (a failed run's draft: no release)
        self.assertIsNone(self.released_as(self.b))
        self.release(self.nightly(3, self.b), self.b)
        self.assertEqual(self.released_as(self.b), self.nightly(3, self.b))
        self.assertEqual(self.released_as(self.a), self.nightly(1, self.a))
        # (a nightly whose name has the commit's 8 hex but whose tag is another commit is not it)
        self.git("tag", "-d", self.nightly(1, self.a))
        self.git("tag", self.nightly(1, self.a), self.b)
        self.assertIsNone(self.released_as(self.a))

    def test_a_stable_finds_its_release_candidate(self):
        self.release("v3.0.0-rc.1", self.b)
        self.assertEqual(self.released_as(self.b, but="v3.0.0"), "v3.0.0-rc.1")
        self.assertIsNone(self.released_as(self.b, but="v3.0.0-rc.1"))   # (never the tag itself)
        self.release("v2.9.0", self.b)   # (no version of this product: never taken)
        self.assertEqual(self.released_as(self.b, but="v3.0.0"), "v3.0.0-rc.1")

    def test_a_release_not_signed_or_not_whole_stops_the_run(self):
        cases = {
            "untrusted": dict(key="other"),
            "corrupt": dict(sig=b"MEUCIQ=="),
            "not base64": dict(sig=b"\x00not base64"),
            "a file more": dict(sums_of=["tools.lock"]),
            "a file less": dict(sums_of=["tools.lock", "HookshotBuilder.exe", "Hookshot-x-x86_64.AppImage",
                                         "HookshotBuilder-x-windows-x64.zip"]),
        }
        for n, (what, kwargs) in enumerate(cases.items(), 1):
            with self.subTest(what):
                FakeForgejo.releases = []
                tag = self.nightly(n, self.b)
                self.release(tag, self.b, **kwargs)
                with self.assertRaises(SystemExit) as e:
                    self.released_as(self.b)
                self.assertIn(tag, str(e.exception))
        FakeForgejo.releases = []
        self.release(self.nightly(9, self.b), self.b)
        FakeForgejo.releases[0]["assets"] = [a for a in FakeForgejo.releases[0]["assets"] if a["name"] != "SHA256SUMS.sig"]
        with self.assertRaises(SystemExit):
            self.released_as(self.b)
        # (a file that does not answer stops it too)
        FakeForgejo.releases, FakeForgejo.files = [], {}
        self.release(self.nightly(10, self.b), self.b)
        FakeForgejo.files.clear()
        with self.assertRaises(SystemExit):
            self.released_as(self.b)

    def test_the_files_come_from_the_address_without_cloudflare(self):
        # (FORGEJO_UPLOAD_API: the same server by its own address; the release list's links name the public one)
        self.release(self.nightly(1, self.b), self.b)
        for a in FakeForgejo.releases[0]["assets"]:
            a["browser_download_url"] = a["browser_download_url"].replace(self.base, "https://git.example.invalid")
        with mock.patch.dict(os.environ, FORGEJO_UPLOAD_API="http://localhost:%d/api/v1" % self.server.server_port):
            self.assertEqual(self.released_as(self.b), self.nightly(1, self.b))
        self.assertEqual(FakeForgejo.fetched, ["localhost:%d" % self.server.server_port] * 2)

    def test_the_command(self):
        self.release(self.nightly(1, self.b), self.b)
        with mock.patch.object(release, "ROOT", str(self.repo)), mock.patch.object(release, "git",
                lambda *a, root=None, check=True, _g=release.git: _g(*a, root=str(self.repo), check=check)), \
                mock.patch.object(release, "trusted_keys", lambda root=None, _t=release.trusted_keys: _t(str(self.repo))):
            self.assertEqual(run("--product", "hookshot", "released-as", self.b, "--not", "v3.0.0-rc.1"), (0, self.nightly(1, self.b) + "\n"))
            self.assertEqual(run("--product", "hookshot", "released-as", self.a), (0, "\n"))
            with self.assertRaises(SystemExit):
                run("--product", "hookshot", "released-as", self.b[:8])


class TokenStaysHome(unittest.TestCase):
    """Forgejo sends a release file to a signed link of its file store (Cloudflare R2), which refuses a request that also
    carries a token: download() gives the token to the forge, and not to where it redirects"""

    def test_a_redirect_to_the_file_store_goes_without_the_token(self):
        seen = {}

        class Store(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen["store"] = self.headers.get("Authorization")
                body = b"bad request" if self.headers.get("Authorization") else b"the sums"
                self.send_response(400 if self.headers.get("Authorization") else 200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        store = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Store)

        class Forge(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen["forge"] = self.headers.get("Authorization")
                self.send_response(303)
                self.send_header("Location", "http://127.0.0.1:%d/bucket/SHA256SUMS?X-Amz-Signature=x" % store.server_port)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass

        forge = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Forge)
        for s in (store, forge):
            threading.Thread(target=s.serve_forever, daemon=True).start()
            self.addCleanup(s.server_close)
            self.addCleanup(s.shutdown)
        url = "http://127.0.0.1:%d/o/r/releases/download/v1/SHA256SUMS" % forge.server_port
        with mock.patch.dict(os.environ, RELEASE_TOKEN="secret"):
            os.environ.pop("FORGEJO_UPLOAD_API", None)
            self.assertEqual(release.download(url), b"the sums")
        self.assertEqual(seen, {"forge": "token secret", "store": None})


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
