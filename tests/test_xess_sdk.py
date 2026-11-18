"""scripts/xess_sdk.py: its file table (the commit third_party/xess's headers come from), the SHA-256 checks, the retries, the
copy into a game folder, a player's own libxess.dll left alone, Intel's license accepted first (here, in make_game.py and in
recomplauncher.json's Intel XeSS tick), without the network.

Run with: python -I tests/test_xess_sdk.py
"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("xess_sdk_under_test", ROOT / "scripts" / "xess_sdk.py")
xess_sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xess_sdk)


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Opener:
    """urlopen over a dict of path -> bytes; records what was asked for. fail: paths that raise OSError once each"""
    def __init__(self, contents, fail=()):
        self.contents, self.asked, self.fail = contents, [], set(fail)

    def __call__(self, url, timeout=None):
        if timeout != xess_sdk.TIMEOUT:
            raise AssertionError("urlopen without the timeout (%r)" % (timeout,))
        path = url[len(xess_sdk.BASE) + 1:]
        self.asked.append(path)
        if path in self.fail:
            self.fail.discard(path)
            raise OSError("connection reset")
        return io.BytesIO(self.contents[path])


def fake_table(data):
    """FILES with each file's SHA-256 that of data[path]"""
    return [(p, digest(data[p]), name) for p, _, name in xess_sdk.FILES]


def load_make_game():
    spec = importlib.util.spec_from_file_location("make_game_xess_under_test", ROOT / "nx2" / "make_game.py")
    make_game = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_game)
    return make_game


class TableTests(unittest.TestCase):
    def test_pinned_commit_is_the_headers(self):
        # (the library from the same commit as the API headers the renderer is compiled against)
        self.assertRegex(xess_sdk.COMMIT, r"^[0-9a-f]{40}$")
        self.assertIn(xess_sdk.COMMIT, xess_sdk.BASE)
        self.assertIn(xess_sdk.COMMIT, xess_sdk.LICENSE_URL)
        provenance = (ROOT / "third_party" / "xess" / "PROVENANCE.md").read_text(encoding="utf-8")
        self.assertIn("commit `%s`" % xess_sdk.COMMIT, provenance)

    def test_files(self):
        names = [name for _, _, name in xess_sdk.FILES]
        self.assertEqual(names, ["libxess.dll", "LICENSE-INTEL-XESS-SDK.txt", "THIRD-PARTY-INTEL-XESS-SDK.txt"])
        self.assertEqual(xess_sdk.FILES[0][0], "bin/" + xess_sdk.DLL)
        for _, sha, _ in xess_sdk.FILES:
            self.assertRegex(sha, r"^[0-9a-f]{64}$")

    def test_the_name_the_game_loads(self):
        # (gpu/vk/vk_xess.cpp kLibrary)
        xess = (ROOT / "gpu" / "vk" / "vk_xess.cpp").read_text(encoding="utf-8")
        self.assertIn('kLibrary = "%s";' % xess_sdk.DLL, xess)


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.data = {p: ("file %s" % p).encode() for p, _, _ in xess_sdk.FILES}

    def test_fetch_and_install(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(xess_sdk, "FILES", fake_table(self.data)):
            opener = Opener(self.data)
            said = []
            xess_sdk.fetch(os.path.join(tmp, "sdk"), opener=opener, say=said.append)
            self.assertEqual(len(said), 3)
            self.assertTrue(xess_sdk.complete(os.path.join(tmp, "sdk")))
            xess_sdk.fetch(os.path.join(tmp, "sdk"), opener=opener, say=said.append)   # (there already: nothing asked)
            self.assertEqual(len(opener.asked), 3)
            game = xess_sdk.install(os.path.join(tmp, "sdk"), os.path.join(tmp, "game"))
            self.assertTrue(xess_sdk.complete(game))

    def test_wrong_file_not_kept(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(xess_sdk, "FILES", fake_table(self.data)):
            bad = dict(self.data)
            first = xess_sdk.FILES[0][0]
            bad[first] = b"something else"
            with self.assertRaises(ValueError):
                xess_sdk.fetch(tmp, opener=Opener(bad), say=lambda _: None)
            self.assertFalse(os.path.exists(os.path.join(tmp, xess_sdk.FILES[0][2])))
            self.assertFalse(os.path.exists(os.path.join(tmp, xess_sdk.FILES[0][2] + ".part")))
            self.assertFalse(xess_sdk.complete(tmp))

    def test_players_dll_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(xess_sdk, "FILES", fake_table(self.data)):
            xess_sdk.fetch(os.path.join(tmp, "sdk"), opener=Opener(self.data), say=lambda _: None)
            game = os.path.join(tmp, "game")
            os.makedirs(game)
            theirs = os.path.join(game, xess_sdk.DLL)
            with open(theirs, "wb") as f:
                f.write(b"a newer SDK's libxess.dll")
            said = []
            xess_sdk.install(os.path.join(tmp, "sdk"), game, say=said.append)
            with open(theirs, "rb") as f:
                self.assertEqual(f.read(), b"a newer SDK's libxess.dll")
            self.assertEqual(sorted(os.listdir(game)), [xess_sdk.DLL])   # (nothing of the pinned set beside it)
            self.assertEqual(len(said), 1)
            self.assertIn(xess_sdk.DLL, said[0])

    def test_retry_after_a_reset(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(xess_sdk, "FILES", fake_table(self.data)):
            second = xess_sdk.FILES[1][0]
            opener = Opener(self.data, fail=[second])
            xess_sdk.fetch(tmp, opener=opener, say=lambda _: None)
            self.assertEqual(opener.asked.count(second), 2)
            self.assertTrue(xess_sdk.complete(tmp))


class MakeGameTests(unittest.TestCase):
    """nx2/make_game.py --fetch-xess-runtime: Intel's library goes into the game folder only once it was fetched whole, and
    never over the player's own"""
    def test_place_xess_runtime(self):
        make_game = load_make_game()
        data = {p: ("file %s" % p).encode() for p, _, _ in xess_sdk.FILES}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(xess_sdk, "FILES", fake_table(data)), \
                mock.patch.object(make_game, "xess_script", return_value=xess_sdk), \
                mock.patch.dict(os.environ, {"HOOKSHOT_XESS_SDK": os.path.join(tmp, "sdk")}), \
                mock.patch("sys.stdout", io.StringIO()):
            game = os.path.join(tmp, "game")
            os.makedirs(game)
            self.assertIsNone(make_game.place_xess_runtime(game))   # (nothing fetched: nothing placed)
            xess_sdk.fetch(os.path.join(tmp, "sdk"), opener=Opener(data), say=lambda _: None)
            placed = make_game.place_xess_runtime(game)
            if make_game.LINUX:
                self.assertIsNone(placed)   # (Intel's library is Windows' alone)
                return
            self.assertEqual(placed, game)
            for _, _, name in xess_sdk.FILES:
                self.assertTrue(os.path.isfile(os.path.join(game, name)), name)
            with open(os.path.join(game, xess_sdk.DLL), "wb") as f:
                f.write(b"the player's own")
            self.assertIsNone(make_game.place_xess_runtime(game))
            with open(os.path.join(game, xess_sdk.DLL), "rb") as f:
                self.assertEqual(f.read(), b"the player's own")

    def test_arguments(self):
        make_game = (ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8")
        for flag in ("--fetch-xess-runtime", "--accept-intel-license"):
            self.assertIn('p.add_argument("%s", action="store_true"' % flag, make_game)
        # (the library before the build, into the game folder after it: as AMD's FSR runtime)
        main = make_game[make_game.index("\ndef main("):]
        self.assertLess(main.index("fetch_xess_runtime(a)"), main.index("place_xess_runtime(out)"))


class LicenseTests(unittest.TestCase):
    """Intel's license accepted before anything of Intel's is downloaded: --accept-intel-license, as AMD's and NVIDIA's"""
    def test_accepted(self):
        self.assertTrue(xess_sdk.accepted(True, interactive=False))
        self.assertFalse(xess_sdk.accepted(False, interactive=False))   # (no one to ask: no)
        self.assertTrue(xess_sdk.accepted(False, ask=lambda _: " Yes ", interactive=True))
        self.assertFalse(xess_sdk.accepted(False, ask=lambda _: "no", interactive=True))

        def eof(_):
            raise EOFError
        self.assertFalse(xess_sdk.accepted(False, ask=eof, interactive=True))

    def test_script_downloads_nothing_unaccepted(self):
        with mock.patch.object(xess_sdk, "fetch", side_effect=AssertionError("downloaded without the license")), \
                mock.patch.object(xess_sdk, "accepted", return_value=False), \
                mock.patch("sys.stdout", io.StringIO()), mock.patch("sys.stderr", io.StringIO()) as err:
            self.assertEqual(xess_sdk.main(["--game", "unused"]), 2)
        self.assertIn("--accept-intel-license", err.getvalue())

    def test_make_game_fails_before_any_download(self):
        make_game = load_make_game()
        xess = mock.Mock()
        with mock.patch.object(make_game, "xess_script", return_value=xess), \
                mock.patch.object(make_game, "say") as said, self.assertRaises(SystemExit):
            make_game.fetch_xess_runtime(SimpleNamespace(fetch_xess_runtime=True, accept_intel_license=False))
        xess.fetch.assert_not_called()
        self.assertIn("Intel XeSS needs Intel's license accepted first (--accept-intel-license).", str(said.call_args))

    def test_make_game_fetches_once_accepted(self):
        make_game = load_make_game()
        xess = mock.Mock(NOTICE="notice")
        with mock.patch.object(make_game, "xess_script", return_value=xess), mock.patch("sys.stdout", io.StringIO()):
            make_game.fetch_xess_runtime(SimpleNamespace(fetch_xess_runtime=True, accept_intel_license=True))
        xess.fetch.assert_called_once()

    def test_recomplauncher_tick(self):
        # (RecompLauncher's Intel XeSS tick: starts off, shows Intel's license at the pinned commit, adds both flags; Windows
        # only, as Intel's library is)
        manifest = json.loads((ROOT / "recomplauncher.json").read_text(encoding="utf-8"))
        option = {o["id"]: o for o in manifest["prepare"]["options"]}["xess"]
        self.assertEqual(option["args"], ["--fetch-xess-runtime", "--accept-intel-license"])
        self.assertEqual(option["os"], ["windows"])
        self.assertEqual(option["license"]["url"], xess_sdk.LICENSE_URL)
        self.assertTrue(re.match(r"^https://", option["license"]["url"]))


if __name__ == "__main__":
    unittest.main()
