"""The renderer's play profile (RX_VK_PGO, after ProjectReLink) is opt-in at every step: with no work/hookshot_vk.profdata the
renderer is built as it always was, a developer's own RX_VK_PGO (gen, or another profile) is never replaced, a profile this
compiler cannot read is left out rather than stopping the build, and the game module's counters keep their own variable.

What nx2/build.py does with RX_VK_PGO (which files count, the writer, the object keys) is checked on its real branch in
tests/test_shader_stamp_cache.py; that neither profile switch translates the game again, in tests/test_lift_cache.py.
No compiler, no game.

python -I -B tests/test_vk_pgo.py
"""
import importlib.util
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("make_game_under_test", ROOT / "nx2" / "make_game.py")
make_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_game)


def check(what, ok):
    if not ok:
        raise SystemExit("FAIL: " + what)


def check_make_game():
    asked = []

    def readable(prof):
        asked.append(prof)
        return True

    import lzma
    with tempfile.TemporaryDirectory(prefix="hookshot-vk-pgo-") as tmp:
        root, work = os.path.join(tmp, "checkout"), os.path.join(tmp, "work")
        os.makedirs(os.path.join(root, "work"))
        os.makedirs(os.path.join(root, "assets", "profiles"))
        os.makedirs(work)

        def pick(environ=None, can_read=readable):
            return make_game.vk_profile_for(work, environ or {}, can_read, root=root)
        check("neither the committed profile nor the checkout's: RX_VK_PGO is not set", pick() is None)
        check("no profile: the compiler is not asked to read one", not asked)
        # (the committed one, xz: unpacked into the work folder under its own name)
        with lzma.open(os.path.join(root, make_game.VK_PROFILE_SHIPPED), "wb") as f:
            f.write(b"shipped profile")
        unpacked = os.path.join(work, make_game.VK_PROFILE_UNPACKED)
        check("the committed profile is unpacked and passed", pick() == unpacked and open(unpacked, "rb").read() == b"shipped profile")
        stamp = os.stat(unpacked).st_mtime_ns - 10**9
        os.utime(unpacked, ns=(stamp, stamp))
        pick()
        check("the same committed profile is not written again", os.stat(unpacked).st_mtime_ns == stamp)
        with lzma.open(os.path.join(root, make_game.VK_PROFILE_SHIPPED), "wb") as f:
            f.write(b"a newer one")
        check("a new committed profile replaces the unpacked one", pick() == unpacked and open(unpacked, "rb").read() == b"a newer one")
        # (a developer's work/hookshot_vk.profdata: main copies it into the work folder, and it is used in place of the committed one)
        own = os.path.join(work, make_game.VK_PROFILE)
        for path in (own, os.path.join(root, "work", make_game.VK_PROFILE)):
            with open(path, "wb") as f:
                f.write(b"developer's profile")
        check("the checkout's own profile comes first", pick() == own)
        os.remove(os.path.join(root, "work", make_game.VK_PROFILE))
        check("a copy left in the work folder from a profile the checkout no longer has is not used", pick() == unpacked)
        check("a counting build stays one (RX_VK_PGO=gen)", pick({"RX_VK_PGO": "gen"}) is None)
        check("a developer's own profile is not replaced", pick({"RX_VK_PGO": "/else.profdata"}) is None)
        check("a profile this compiler cannot read is left out, the renderer built without it", pick(can_read=lambda p: False) is None)
    shipped = ROOT / make_game.VK_PROFILE_SHIPPED
    check("the renderer's profile is committed (assets/profiles/hookshot_vk.profdata.xz)", shipped.is_file())
    with lzma.open(shipped) as f:
        check("it is an indexed LLVM profile", f.read(8) == b"\xfflprofi\x81")
    check("its note says where it was recorded", "Recorded:" in (ROOT / "assets" / "profiles" / "README.md").read_text(encoding="utf-8"))
    text = (ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8")
    check("the committed profile is checked on every system (another LLVM than llvm-mingw's made it)",
          "profile_readable(p, any_os=True)" in text)
    check("the lift key leaves the renderer's profile switches out (a profile made or taken away translates nothing again)",
          {"RX_VK_PGO", "RX_VK_PGO_FILE"} <= set(make_game.COMPILE_ONLY_ENV))
    check("make_game.py copies the profile from the checkout's work/ with the game's", '"hookshot_pieces.prof", VK_PROFILE,' in text)
    check("make_game.py passes it to the compile", 'env["RX_VK_PGO"] = vk_profile' in text)


def check_dev_packs():
    spec = importlib.util.spec_from_file_location("dev_packs_under_test", ROOT / "scripts" / "dev_packs.py")
    packs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packs)
    with tempfile.TemporaryDirectory(prefix="hookshot-vk-pgo-base-") as work:
        prof = os.path.join(work, make_game.VK_PROFILE)
        shipped = os.path.join(work, make_game.VK_PROFILE_UNPACKED)
        check("a base with no profile: a renderer pack is built with none", packs.renderer_profile(work, {}) == {})
        # (a base of main: make_game.py unpacked the committed profile and built with it)
        with open(shipped, "wb") as f:
            f.write(b"committed profile")
        check("a base built with the committed profile: a renderer pack is built with it too, by the base's path",
              packs.renderer_profile(work, {}) == {"RX_VK_PGO": shipped})
        with open(prof, "wb") as f:
            f.write(b"profile")
        check("a base whose checkout had its own profile: that one, as make_game.py chose it",
              packs.renderer_profile(work, {}) == {"RX_VK_PGO": prof})
        check("a counting pack stays one", packs.renderer_profile(work, {"RX_VK_PGO": "gen"}) == {})
    # (what a pack builds: a profile switch set for it builds, even with no file changed)
    for how, env, want, why in ((None, {}, None, "no change, no switch: nothing to build"),
                                (None, {"RX_VK_PGO": "gen"}, "renderer", "a counting renderer of an unchanged tree is built"),
                                (None, {"RX_VK_PGO": "/other.profdata"}, "renderer", "another renderer profile is built"),
                                ("game", {"RX_VK_PGO": "gen"}, "game", "a game change still builds both modules"),
                                ("renderer", {}, "renderer", "a renderer change, as before"),
                                (None, {"RX_PGO": "gen"}, "game", "the game's counting build of an unchanged tree is built"),
                                ("renderer", {"RX_PGO": "/p.prof"}, "game", "a game profile builds the game")):
        check("pack_route: " + why, packs.pack_route(how, env) == want)
    text = (ROOT / "scripts" / "dev_packs.py").read_text(encoding="utf-8")
    check("the renderer's own build takes it", '**renderer_profile(b["work"], os.environ)' in text)
    check("cmd_pack routes through pack_route", "how = pack_route(route(changed, tree), os.environ)" in text)


def check_writer():
    text = (ROOT / "host" / "pgo_rt.c").read_text(encoding="utf-8")
    check("the game module's counters are still driven by HOS_PGO", '#ifndef PGO_ENV\n#define PGO_ENV "HOS_PGO"\n#endif' in text)
    check("the variable is read through PGO_ENV", "getenv(PGO_ENV)" in text and 'getenv("HOS_PGO")' not in text)
    for section in ("cnts", "data", "names"):   # (Linux: the ELF sections' ends, this module's own)
        for end in ("start", "stop"):
            name = "__%s___llvm_prf_%s" % (end, section)
            check("%s is declared weak and hidden" % name, ("%s[] __attribute__((weak, visibility(\"hidden\")));" % name) in text)
    windows = text[text.index("#ifdef _WIN32"):text.index("#else")]
    check("the COFF sections are Windows' alone", ".lprfc$A" in windows and ".lprfc$A" not in text.replace(windows, ""))


def check_unread_message():
    """A clang that can't read a profile says which clang, which profile and, on Linux when it is older than the build tools'
    LLVM, where the one that reads it is (a distro's clang 18 and the committed LLVM 23 profile)"""
    err = "error: Profile data error: unsupported version\n"
    prof = os.path.join("work", make_game.VK_PROFILE_UNPACKED)
    old = make_game.profile_unread_message(prof, "Ubuntu clang version 18.1.3 (1ubuntu1)\nTarget: x86_64\n", err, True, "23.1.5")
    check("the line names the clang and its version", old.startswith("clang 18.1.3 cannot read the play profile"))
    check("and the profile, by its file name", make_game.VK_PROFILE_UNPACKED in old and "work" + os.sep not in old)
    check("and clang's own reason", "(error: Profile data error: unsupported version)" in old)
    check("and that the build goes on", "building without it" in old)
    check("an older clang on Linux is told where the build tools' LLVM is",
          "LLVM 23.1.5 reads it" in old and "scripts/dev_build.py env" in old and "clang 23 or newer" in old)
    new = make_game.profile_unread_message(prof, "clang version 23.1.4\n", err, True, "23.1.5")
    check("a clang as new as the build tools' gets no advice to install it", "dev_build.py" not in new)
    check("nor does Windows (llvm-mingw is the builder's own)",
          "dev_build.py" not in make_game.profile_unread_message(prof, "clang version 18.1.3\n", err, False, "23.1.5"))
    unknown = make_game.profile_unread_message(prof, "", "", True, "23.1.5")
    check("a clang that names no version is 'this compiler', and an empty reason is said",
          unknown.startswith("this compiler cannot read") and "(no message)" in unknown and "dev_build.py env" in unknown)
    check("without the build tools' version (no deps.sh) the line has no advice",
          "dev_build.py" not in make_game.profile_unread_message(prof, "clang version 18.1.3\n", err, True, None))
    check("the build tools' version comes from scripts/linux/deps.sh",
          make_game.build_tools_llvm(str(ROOT)) and make_game.build_tools_llvm(str(ROOT))[0].isdigit())
    with tempfile.TemporaryDirectory() as empty:
        check("and is None outside a checkout", make_game.build_tools_llvm(empty) is None)


def check_release():
    appimage = (ROOT / "scripts" / "linux" / "appimage.sh").read_text(encoding="utf-8")
    check("the AppImage builds no renderer of its own (every player's build compiles it, with the profile)",
          "RX_VK_ONLY" not in appimage and "RX_VK_PGO" not in appimage)
    check("the AppImage carries assets/ (the committed profile, for every player's own renderer)",
          "cp -a nx2 host scripts LICENSE README.md assets tools.lock" in appimage)
    flow = (ROOT / ".forgejo" / "workflows" / "build-linux.yml").read_text(encoding="utf-8")
    step = flow[flow.index("- name: hookshot_vk.so (build check)"):flow.index("- name: hookshot_vk.so with AMD FSR 4")]
    check("CI's renderer build check takes the profile as a player's build does: the checkout's, else the committed one",
          'RX_VK_PGO="$VK_PGO" ' in step and "\n          VK_PGO=\n" in step and
          'if [ -f work/hookshot_vk.profdata ]; then VK_PGO="$PWD/work/hookshot_vk.profdata"' in step and
          'xz -dc assets/profiles/hookshot_vk.profdata.xz > "$VKW/hookshot_vk.shipped.profdata"' in step)
    check("and a developer's own profile when the checkout has one",
          "for f in hot_funcs.txt hot_order.txt hookshot_pieces.prof hookshot_vk.profdata; do" in appimage)
    docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    for switch in ("RX_VK_PGO=gen", "RX_VK_PGO_FILE=<file>"):
        check("%s is in docs/development.md's switch tables" % switch, switch in docs)


if __name__ == "__main__":
    check_make_game()
    check_dev_packs()
    check_writer()
    check_unread_message()
    check_release()
    print("OK: the renderer's play profile is opt-in, and the game's counters keep their own switch")
