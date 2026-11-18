"""Intel's XeSS Super Resolution library for Windows (libxess.dll 2.0.2.68, signed by Intel), for Intel XeSS in the Upscaler
row (gpu/vk/vk_xess.cpp).

Intel's files are not part of Hookshot and are not committed: they are Intel's, under the Intel Simplified Software License
(the SDK's LICENSE.txt, fetched beside them as LICENSE-INTEL-XESS-SDK.txt, with the notices of the third-party programs in
the library as THIRD-PARTY-INTEL-XESS-SDK.txt). This fetches them from Intel's XeSS SDK repository at one pinned commit, the
one third_party/xess's headers come from (third_party/xess/PROVENANCE.md), each file checked against its SHA-256, into
<folder>:
  - libxess.dll (XeSS Super Resolution; the game calls its Vulkan API);
  - LICENSE-INTEL-XESS-SDK.txt and THIRD-PARTY-INTEL-XESS-SDK.txt.
gpu/vk/vk_xess.cpp looks for libxess.dll in RX_VK_XESS_DIR, beside the executable, then in the game folder. Windows only:
Intel publishes no XeSS library for Linux.

Usage:  python -I scripts/xess_sdk.py [--accept-intel-license] [--game <game folder>] [<folder>]
  <folder>: default work/xess-sdk
  --accept-intel-license: Intel's license, accepted (without it: asked, and nothing is downloaded without a yes)
  --game: the library copied into <game folder> too (nx2/make_game.py --fetch-xess-runtime does the same for the folder it
          builds)
"""
import argparse
import hashlib
import os
import shutil
import sys
import urllib.request

COMMIT = "de0fb9c1c510661c571164e1418ceca8101dab69"   # (main after the v3.0.2 release: libxess.dll 2.0.2.68)
BASE = "https://raw.githubusercontent.com/intel/xess/" + COMMIT
# Intel's license for these files, at the pinned commit (it grants using and redistributing them unmodified, in binary form,
# with its notice kept and no reverse engineering). It asks for no acceptance step; one is asked all the same, as for AMD's
# and NVIDIA's (scripts/ffx_sdk.py, scripts/ngx_sdk.py): one rule for all three, and nobody gets Intel's files without having
# seen the terms
LICENSE_URL = "https://github.com/intel/xess/blob/" + COMMIT + "/LICENSE.txt"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (path in Intel's repository, its SHA-256, its name here)
FILES = [
    ("bin/libxess.dll", "251659dd84a3e84de67c886a4186e01f3eca49b00641906fe38bb6b807e5d5b7", "libxess.dll"),
    ("LICENSE.txt", "784be42c39a4a4d03cf85d88e15e59d75828fca773ce45b8dbfffbd7eaf208df", "LICENSE-INTEL-XESS-SDK.txt"),
    ("third-party-programs.txt", "e8d8899dbfc4de0e8ca25560be9358e03c1405d7c956d20a1838c3c709b9b51c",
     "THIRD-PARTY-INTEL-XESS-SDK.txt"),
]
DLL = "libxess.dll"

NOTICE = """\
Intel XeSS: this downloads Intel's XeSS Super Resolution library for Windows (libxess.dll 2.0.2.68, 78 MB) from
github.com/intel/xess. Intel's files are Intel's, not Hookshot's, signed by Intel and under the Intel Simplified Software
License (saved as LICENSE-INTEL-XESS-SDK.txt beside them):
  """ + LICENSE_URL

TIMEOUT = 60   # (seconds without an answer, or between two reads, before a download gives up)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch_one(path, digest, dst, opener=urllib.request.urlopen):
    """One file into dst, unless it is there already with that SHA-256. The download goes to dst.part and is moved in only
    when its SHA-256 is the expected one; otherwise it is deleted and ValueError says which"""
    if os.path.isfile(dst) and sha256(dst) == digest:
        return False
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    tmp = dst + ".part"
    try:
        with opener(BASE + "/" + path, timeout=TIMEOUT) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        if sha256(tmp) != digest:
            raise ValueError("xess-sdk: %s is not the file expected (SHA-256): not used" % path)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return True


def fetch(folder, opener=urllib.request.urlopen, say=print, tries=3):
    """Every file into folder (a download cut off is tried again, up to tries times)"""
    for path, digest, name in FILES:
        for attempt in range(tries):
            try:
                if fetch_one(path, digest, os.path.join(folder, name), opener):
                    say("xess-sdk: %s" % name)
                break
            except OSError:
                if attempt + 1 == tries:
                    raise


def complete(folder):
    """Whether folder holds Intel's files, each the one expected"""
    return all(os.path.isfile(os.path.join(folder, n)) and sha256(os.path.join(folder, n)) == d for _, d, n in FILES)


def other(game):
    """Whether game holds a libxess.dll that is not the pinned one (a newer SDK's the player put there by hand, say)"""
    digest = {name: digest for _, digest, name in FILES}[DLL]
    return os.path.isfile(os.path.join(game, DLL)) and sha256(os.path.join(game, DLL)) != digest


def install(folder, game, say=print):
    """Intel's files copied from folder into game (made when missing): where the game finds them (the game folder). A
    libxess.dll the player put there already, other than the pinned one, is left alone and nothing is copied (the game's log
    names the version it loads), and say tells so. Returns game"""
    os.makedirs(game, exist_ok=True)
    if other(game):
        say("xess-sdk: the %s in %s is not 2.0.2.68's: left as it is (delete it to get 2.0.2.68's)" % (DLL, game))
        return game
    for _, digest, name in FILES:
        dst = os.path.join(game, name)
        if not (os.path.isfile(dst) and sha256(dst) == digest):
            shutil.copyfile(os.path.join(folder, name), dst + ".part")
            os.replace(dst + ".part", dst)
    return game


def accepted(flag, ask=input, interactive=None):
    """Intel's license, accepted: the flag, or a typed yes when there is someone to ask (as scripts/ffx_sdk.py's)"""
    if flag:
        return True
    if not (sys.stdin.isatty() if interactive is None else interactive):
        return False
    try:
        return ask("Do you accept Intel's license? Type yes to go on: ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("folder", nargs="?")
    p.add_argument("--game", help="a game folder: Intel's library into it")
    p.add_argument("--accept-intel-license", action="store_true")
    a = p.parse_args(argv)
    folder = os.path.abspath(a.folder or os.path.join(ROOT, "work", "xess-sdk"))
    print(NOTICE, flush=True)
    if not accepted(a.accept_intel_license):
        print("xess-sdk: Intel's license was not accepted (--accept-intel-license, or yes when asked): nothing downloaded",
              file=sys.stderr, flush=True)
        return 2
    try:
        fetch(folder)
    except (OSError, ValueError) as e:
        print("xess-sdk: %s" % e, file=sys.stderr, flush=True)
        return 1
    print("xess-sdk: Intel's XeSS library in %s" % folder, flush=True)
    if a.game:
        print("xess-sdk: copied into %s" % install(folder, a.game), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
