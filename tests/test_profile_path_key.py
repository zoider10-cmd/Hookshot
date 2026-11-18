"""The object keys name a play profile by its contents, not its path (nx2/build.py flag_text). make_game.py puts both profiles
in the work folder (RX_PGO=<work>/hookshot_pieces.prof for the eight hot pieces, RX_VK_PGO=<work>/hookshot_vk.shipped.profdata
for the renderer's own objects), so with the path in the key another work folder could share neither through the object store
(nx2/object_store.py) or a dev_packs.py base. The -D..._PROFILE_SHA1 beside the path is what the key needs of the profile.

python -I -B tests/test_profile_path_key.py
"""
import importlib.util
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "nx2"), str(ROOT / "third_party" / "a64-kit" / "tools")]
spec = importlib.util.spec_from_file_location("build_profile_key", ROOT / "nx2" / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class ProfilePathTests(unittest.TestCase):
    def test_the_profiles_path_is_not_in_the_key_and_its_contents_are(self):
        for define in ("-DHOOKSHOT_PROFILE_SHA1=", "-DHOOKSHOT_VK_PROFILE_SHA1="):
            a = ["-O2", "-fprofile-instr-use=C:/one/work/hookshot_pieces.prof", define + "0123456789abcdef"]
            b = ["-O2", "-fprofile-instr-use=/home/two/work/hookshot_pieces.prof", define + "0123456789abcdef"]
            c = ["-O2", "-fprofile-instr-use=C:/one/work/hookshot_pieces.prof", define + "fedcba9876543210"]
            self.assertEqual(build.flag_text(a), build.flag_text(b))
            self.assertNotEqual(build.flag_text(a), build.flag_text(c))
            self.assertEqual(build.object_key(__file__, a, b""), build.object_key(__file__, b, b""))

    def test_every_profile_flag_carries_its_contents_beside_it(self):
        # (each "-fprofile-instr-use=" + <path> in build.py is followed, in the same list, by a -D..._PROFILE_SHA1 of the file's
        # bytes: without it the key would no longer change when the profile does)
        src = (ROOT / "nx2" / "build.py").read_text(encoding="utf-8")
        uses = [m.end() for m in re.finditer(r'"-fprofile-instr-use=" \+', src)]
        self.assertGreaterEqual(len(uses), 2, "the hot pieces' RX_PGO and the renderer's RX_VK_PGO")
        for at in uses:
            rest = src[at:src.index("]", at)]
            self.assertRegex(rest, r'"-DHOOKSHOT_(VK_)?PROFILE_SHA1=" \+ hashlib\.sha1\(f\.read\(\)', src[at - 60:at + 120])


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=1))
