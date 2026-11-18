"""Game-free checks of make_game's NUP cache selection and replacement.

make_game runs as from a checkout of its own, with nothing in its work/: a developer's play profile in the clone's
work/ (CONTRIBUTING.md puts it there) was copied in and probed with clang, a process these checks refuse.

Run with: python -I tests/test_make_game_cache.py
"""
import contextlib
import errno
from functools import partial
import importlib.util
import io
import os
import shutil
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock


SOURCE = Path(os.environ.get("HOOKSHOT_CACHE_TEST_SOURCE", Path(__file__).resolve().parents[1] / "nx2" / "make_game.py"))
spec = importlib.util.spec_from_file_location("make_game_under_test", SOURCE)
make_game = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_game)


class Prepared(Exception):
    """Stop at the first lift request, before compiling or reading any game."""


def module_bytes(supported=True, payload=b"new authored module"):
    header = bytearray(0x60)
    header[:4] = b"NSO0"
    header[0x40:0x44] = bytes.fromhex(make_game.BUILD_ID if supported else "01234567")
    return bytes(header) + payload


HEAPDEF = "System/HeapSize/Product.Nin_Ounce_NVN2.HeapDef.byml.zs"
DEFAULT_HEAPDEF = "System/HeapSize/Default.Nin_Ounce_NVN2.HeapDef.byml.zs"


def game_files(romfs, heapdef=HEAPDEF):
    """What the build and the game's start need from a romfs (make_game.ROMFS_NEEDED), as authored stand-ins. The .zs ones
    start as zstd, so the damaged-file check reads them as whole"""
    (romfs / "Pack").mkdir(parents=True, exist_ok=True)
    (romfs / "Pack" / "ZsDic.pack.zs").write_bytes(b"\x28\xb5\x2f\xfd" + b"authored dictionary stand-in")
    (romfs / "System" / "Resource").mkdir(parents=True, exist_ok=True)
    if heapdef:
        (romfs / heapdef).parent.mkdir(parents=True, exist_ok=True)
        (romfs / heapdef).write_bytes(b"\x28\xb5\x2f\xfd" + b"authored heap definition stand-in")


class NupCacheHarness(unittest.TestCase):
    """An output folder unpacked from old.nup, and make_game run up to the lift with an authored extraction"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hookshot-cache-test-")
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(getattr(make_game, "release_work", lambda: None))   # (Windows deletes no work folder with its lock open)
        self.root = Path(self.temporary.name).resolve()
        self.out = self.root / "output"
        self.work = self.root / "work"
        self.addCleanup(self.assert_owned_fixture)
        self.out.mkdir()
        self.work.mkdir()
        self.old_nup = self.root / "old.nup"
        self.old_nup.write_bytes(b"old authored input")
        self.new_nup = self.root / "new.nup"
        self.new_nup.write_bytes(b"new authored input of a different size")
        (self.out / "romfs").mkdir()
        (self.out / "romfs" / "asset.txt").write_bytes(b"old authored assets")
        game_files(self.out / "romfs")
        (self.out / ".hookshot_exefs").mkdir()
        (self.out / ".hookshot_exefs" / "main").write_bytes(module_bytes(payload=b"old authored module"))
        self.marker = self.out / ".hookshot_romfs"
        self.marker.write_text(self.stamp(self.old_nup) + "\n")
        save = self.out / "user" / "save"
        save.mkdir(parents=True)
        (save / "sentinel.txt").write_bytes(b"authored save sentinel")
        (self.out / "hookshot_options.ini").write_bytes(b"authored options sentinel")
        self.extractions = []
        self.output = ""

    def assert_owned_fixture(self):
        # The builder only receives descendants of this test-owned temporary directory.
        self.assertEqual(self.root.parent, Path(tempfile.gettempdir()).resolve())
        self.assertTrue(self.out.resolve().is_relative_to(self.root))
        self.assertTrue(self.work.resolve().is_relative_to(self.root))

    def stamp(self, nup):
        return "unpacked by this builder: %s %d" % (nup.name, nup.stat().st_size)

    def cache(self):
        return {path.relative_to(self.out).as_posix(): path.read_bytes()
                for path in self.out.rglob("*") if path.is_file() and ".game" not in path.parts}

    def run_to_lift(self, nup, failure=None, supported=True, include_romfs=True, update=False, folders=None,
                    romfs_files=None, start_files=True, romfs_from=None):
        self.assert_owned_fixture()

        def run(cmd, env=None, on_line=None):
            if "nx2/nup.py" in cmd:
                target = Path(cmd[cmd.index("--extract") + 1]).resolve()
                self.assertTrue(target.is_relative_to(self.root))
                self.extractions.append(nup)
                (target / "exefs").mkdir(parents=True)
                (target / "exefs" / "main").write_bytes(module_bytes(supported=supported))
                if failure:
                    (target / "romfs").mkdir()
                    (target / "romfs" / "asset.txt.part").write_bytes(b"incomplete authored asset")
                    make_game.fail(failure)
                if include_romfs:
                    (target / "romfs").mkdir()
                    (target / "romfs" / "asset.txt").write_bytes(b"new authored assets")
                    (target / "romfs" / "new-only.txt").write_bytes(b"new authored file")
                    if start_files:
                        game_files(target / "romfs")
                    for name, data in (romfs_files or {}).items():
                        path = target / "romfs" / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(data)
                return
            if "nx2/unpack.py" in cmd:   # (a chosen exefs folder: its authored module is already unpacked)
                return
            if "nx2/lift.py" in cmd:
                raise Prepared
            self.fail("Unexpected build subprocess: %r" % cmd)

        argv = ["make_game.py", "--work", str(self.work)]
        if update:
            argv += ["--update", str(self.out)]
        elif folders:
            argv += ["--romfs", str(folders[0]), "--exefs", str(folders[1]), "--out", str(self.out)]
        else:
            argv += ["--nup", str(nup), "--out", str(self.out)]
        if romfs_from:
            argv += ["--romfs-from", str(romfs_from)]
        # The only external operation exercised is authored extraction above; no compiler, SDK,
        # translation, power-state update or real game is involved.
        with contextlib.ExitStack() as stack:
            blocked = [
                stack.enter_context(mock.patch.object(make_game.subprocess, "Popen",
                                                     side_effect=AssertionError("Unexpected process launch"))),
                stack.enter_context(mock.patch.object(os, "system",
                                                     side_effect=AssertionError("Unexpected shell command"))),
                stack.enter_context(mock.patch.object(os, "startfile", create=True,
                                                     side_effect=AssertionError("Unexpected file launch"))),
            ]
            stack.enter_context(mock.patch.object(sys, "argv", argv))
            stack.enter_context(mock.patch.object(make_game, "check_windows_sdk"))
            stack.enter_context(mock.patch.object(make_game, "stop_stray_compilers"))   # (Windows: powershell, taskkill)
            stack.enter_context(mock.patch.object(make_game, "drop_stale_objects"))
            stack.enter_context(mock.patch.object(make_game, "no_throttle"))
            stack.enter_context(mock.patch("ctypes.WinDLL", create=True))
            # (the hot list, link order, PGO profile and chunk boundaries come from <checkout>/work: an empty one here. The lift's
            # key hashes nx2/ relative to the checkout, which relpath refuses across drives (Windows CI): not what is checked here)
            stack.enter_context(mock.patch.object(make_game, "ROOT", str(self.root / "checkout")))
            # vk_profile_for's default root was bound at import; use this authored checkout too.
            stack.enter_context(mock.patch.object(make_game, "vk_profile_for",
                                                  partial(make_game.vk_profile_for, root=make_game.ROOT)))
            stack.enter_context(mock.patch.object(make_game, "lift_key", return_value="test key"))
            stack.enter_context(mock.patch.object(make_game, "run", side_effect=run))
            output = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            try:
                make_game.main()
            finally:
                self.output = output.getvalue()
                for launch in blocked:
                    launch.assert_not_called()


class NupCacheTests(NupCacheHarness):
    def test_failed_scratch_exefs_cleanup_stops_before_copy_or_extraction(self):
        scratch = self.work / "exefs"
        scratch.mkdir()
        stale = scratch / "locked"
        stale.write_bytes(b"authored stale module")
        before = self.cache()
        remove = shutil.rmtree

        def remove_with_lock(path, *args, **kwargs):
            if Path(path) == scratch:
                if not kwargs.get("ignore_errors"):
                    raise PermissionError(errno.EACCES, "authored locked file", str(stale))
                return
            return remove(path, *args, **kwargs)

        rename = os.rename

        def rename_locked(src, dst, *args, **kwargs):   # (clear_folder's last resort, moving the folder aside, held too)
            if Path(src) == scratch:
                raise PermissionError(errno.EACCES, "authored locked file", str(stale))
            return rename(src, dst, *args, **kwargs)

        for update in (True, False):
            with self.subTest(update=update), mock.patch.object(shutil, "rmtree", side_effect=remove_with_lock), \
                    mock.patch.object(os, "rename", side_effect=rename_locked), mock.patch.object(make_game.time, "sleep"):
                with self.assertRaises(SystemExit) as result:
                    self.run_to_lift(self.new_nup, update=update)
                self.assertEqual(result.exception.code, 1)
                self.assertIn("@@error Could not clear", self.output)
                self.assertIn(str(scratch), self.output)
                self.assertIn("authored locked file", self.output)
                self.assertEqual(self.extractions, [])
                self.assertEqual(self.cache(), before)
                self.assertEqual(stale.read_bytes(), b"authored stale module")

    def test_update_replaces_clearable_scratch_exefs(self):
        scratch = self.work / "exefs"
        scratch.mkdir()
        stale = scratch / "stale"
        stale.write_bytes(b"authored stale module")
        before = self.cache()
        with self.assertRaises(Prepared):
            self.run_to_lift(None, update=True)
        self.assertFalse(stale.exists())
        self.assertEqual(self.extractions, [])
        after = self.cache()
        # (the one file added: the damaged-texture check's note that this unpack was checked, nup.stand_in_damaged)
        self.assertEqual(after.pop(".hookshot_romfs_checked").decode().splitlines(),
                         ["resolved-v2"] + before[".hookshot_romfs"].decode().splitlines())
        self.assertEqual(after, before)
        self.assertEqual((scratch / "main").read_bytes(), (self.out / ".hookshot_exefs/main").read_bytes())

    def test_changed_source_replaces_romfs_and_exefs_together(self):
        with self.assertRaises(Prepared):
            self.run_to_lift(self.new_nup)
        self.assertEqual(self.extractions, [self.new_nup])
        self.assertEqual((self.out / "romfs" / "asset.txt").read_bytes(), b"new authored assets")
        self.assertTrue((self.out / "romfs" / "new-only.txt").is_file())
        self.assertEqual((self.out / ".hookshot_exefs" / "main").read_bytes(), module_bytes())
        self.assertEqual(self.marker.read_text(), self.stamp(self.new_nup) + "\n")
        self.assertEqual((self.out / "user/save/sentinel.txt").read_bytes(), b"authored save sentinel")
        self.assertEqual((self.out / "hookshot_options.ini").read_bytes(), b"authored options sentinel")

    def test_same_source_reuses_the_cache(self):
        before = self.cache()
        with self.assertRaises(Prepared):
            self.run_to_lift(self.old_nup)
        self.assertEqual(self.extractions, [])
        after = self.cache()
        # (the one file added: the damaged-texture check's note that this unpack was checked, nup.stand_in_damaged)
        self.assertEqual(after.pop(".hookshot_romfs_checked").decode().splitlines(),
                         ["resolved-v2"] + before[".hookshot_romfs"].decode().splitlines())
        self.assertEqual(after, before)
        self.assertEqual((self.work / "exefs/main").read_bytes(),
                         (self.out / ".hookshot_exefs/main").read_bytes())

    def test_unresolved_fresh_extraction_stops_before_lift(self):
        original = self.new_nup.read_bytes()
        with self.assertRaises(SystemExit) as result:
            self.run_to_lift(self.new_nup, romfs_files={"Tex/only_Alb.bntx.zs": bytes(32)})
        self.assertEqual(result.exception.code, 1)
        self.assertIn("@@error The game dump still has 1 damaged file with no replacement", self.output)
        self.assertIn("only_Alb.bntx.zs", self.output)
        self.assertFalse((self.out / ".hookshot_romfs_checked").exists())
        self.assertEqual(self.new_nup.read_bytes(), original)
        self.assertEqual((self.out / "user/save/sentinel.txt").read_bytes(), b"authored save sentinel")
        self.assertEqual((self.out / "hookshot_options.ini").read_bytes(), b"authored options sentinel")

    def test_unresolved_cached_extraction_retries_until_a_donor_is_available(self):
        tex = self.out / "romfs/Tex"
        tex.mkdir()
        broken = tex / "only_Alb.bntx.zs"
        broken.write_bytes(bytes(32))
        heads = self.out / make_game.HEADS
        heads.write_text(self.marker.read_text() + "Tex/only_Alb.bntx.zs\n")
        original_heads = heads.read_bytes()
        original_nup = self.old_nup.read_bytes()
        for update in (False, True):
            with self.subTest(update=update), self.assertRaises(SystemExit) as result:
                self.run_to_lift(None if update else self.old_nup, update=update)
            self.assertEqual(result.exception.code, 1)
            self.assertIn("1 damaged file with no replacement", self.output)
            note = self.out / make_game.DAMAGED_NOTE
            self.assertTrue(note.is_file(), "the unresolved failure must leave the damaged-file report")
            self.assertIn("only_Alb.bntx.zs: no replacement found; build cannot continue", note.read_text(encoding="utf-8"))
            self.assertFalse((self.out / ".hookshot_romfs_checked").exists())
            self.assertEqual(heads.read_bytes(), original_heads)
            self.assertEqual(broken.read_bytes(), bytes(32))
        donor = tex / "other_Alb.bntx.zs"
        donor.write_bytes(b"\x28\xb5\x2f\xfd" + b"authored counterpart")
        with self.assertRaises(Prepared):
            self.run_to_lift(self.old_nup)
        self.assertEqual(broken.read_bytes(), donor.read_bytes())
        self.assertFalse(heads.exists())
        self.assertEqual((self.out / ".hookshot_romfs_checked").read_text(), "resolved-v2\n" + self.marker.read_text())
        self.assertEqual(self.old_nup.read_bytes(), original_nup)
        self.assertEqual((self.out / "user/save/sentinel.txt").read_bytes(), b"authored save sentinel")
        self.assertEqual((self.out / "hookshot_options.ini").read_bytes(), b"authored options sentinel")

    def test_legacy_marker_does_not_hide_unresolved_damage(self):
        checked = self.out / ".hookshot_romfs_checked"
        checked.write_bytes(self.marker.read_bytes())
        tex = self.out / "romfs/Tex"
        tex.mkdir()
        broken = tex / "only_Alb.bntx.zs"
        broken.write_bytes(bytes(32))
        with self.assertRaises(SystemExit) as result:
            self.run_to_lift(self.old_nup)
        self.assertEqual(result.exception.code, 1)
        self.assertIn("1 damaged file with no replacement", self.output)
        self.assertFalse(checked.exists())
        self.assertEqual(broken.read_bytes(), bytes(32))

    def test_legacy_healthy_marker_is_checked_once(self):
        checked = self.out / ".hookshot_romfs_checked"
        checked.write_bytes(self.marker.read_bytes())
        with self.assertRaises(Prepared):
            self.run_to_lift(self.old_nup)
        self.assertIn("checking your game files", self.output)
        self.assertEqual(checked.read_text(), "resolved-v2\n" + self.marker.read_text())
        with mock.patch.object(make_game, "file_progress", side_effect=AssertionError("Unexpected second scan")):
            with self.assertRaises(Prepared):
                self.run_to_lift(self.old_nup)

    def test_fully_repairable_fresh_extraction_reaches_lift(self):
        donor = b"\x28\xb5\x2f\xfd" + b"authored counterpart"
        with self.assertRaises(Prepared):
            self.run_to_lift(self.new_nup, romfs_files={"Tex/only_Alb.bntx.zs": bytes(32),
                                                      "Tex/other_Alb.bntx.zs": donor})
        self.assertIn("in its place other_Alb.bntx.zs", self.output)
        self.assertEqual((self.out / "romfs/Tex/only_Alb.bntx.zs").read_bytes(), donor)
        self.assertTrue((self.out / ".hookshot_romfs_checked").exists())

    def test_mixed_repairs_report_the_unresolved_count(self):
        with self.assertRaises(SystemExit) as result:
            self.run_to_lift(self.new_nup, romfs_files={
                "Tex/only_Alb.bntx.zs": bytes(32),
                "Tex/other_Alb.bntx.zs": b"\x28\xb5\x2f\xfd" + b"authored counterpart",
                "Model/missing.bfres.zs": bytes(32),
            })
        self.assertEqual(result.exception.code, 1)
        self.assertIn("2 game files in it are damaged", self.output)
        self.assertIn("1 damaged file with no replacement", self.output)
        self.assertIn("missing.bfres.zs", self.output)
        self.assertFalse((self.out / ".hookshot_romfs_checked").exists())

    def test_failed_extraction_preserves_the_previous_cache_and_save(self):
        before = self.cache()
        failure = "nup.py stopped (exit status 1): OSError: [Errno 28] No space left on device"
        with self.assertRaises(SystemExit) as result:
            self.run_to_lift(self.new_nup, failure=failure)
        self.assertEqual(result.exception.code, 1)
        self.assertIn("@@error " + failure, self.output)
        self.assertEqual(self.extractions, [self.new_nup])
        self.assertEqual(self.cache(), before)
        self.assertFalse((self.out / ".game").exists())

    def test_unsupported_build_preserves_the_previous_cache_and_save(self):
        before = self.cache()
        with self.assertRaises(SystemExit) as result:
            self.run_to_lift(self.new_nup, supported=False)
        self.assertEqual(self.extractions, [self.new_nup])
        self.assertEqual(result.exception.code, 1)
        self.assertIn("This is build 01234567. Hookshot supports build %s." % make_game.BUILD_ID, self.output)
        self.assertEqual(self.cache(), before)
        self.assertFalse((self.out / ".game").exists())

    def test_missing_romfs_preserves_the_previous_cache_and_save(self):
        before = self.cache()
        with self.assertRaises(SystemExit) as result:
            self.run_to_lift(self.new_nup, include_romfs=False)
        self.assertEqual(self.extractions, [self.new_nup])
        self.assertEqual(result.exception.code, 1)
        self.assertIn("The package did not contain a romfs folder.", self.output)
        self.assertEqual(self.cache(), before)
        self.assertFalse((self.out / ".game").exists())

    def game_files(self, romfs, heapdef=HEAPDEF):
        """What a chosen romfs folder needs (check_romfs_folder), as authored stand-ins"""
        game_files(romfs, heapdef)

    def test_romfs_folder_without_the_game_files_is_refused_before_the_build(self):
        # (issue 467: another tool's packed copy, index.json and one romfs.bin, was built for 15 minutes, then the game
        # stopped at boot)
        shutil.rmtree(self.out)
        exefs = self.root / "dump" / "exefs"
        exefs.mkdir(parents=True)
        (exefs / "main").write_bytes(module_bytes())
        packed, empty, half = self.root / "dump" / "packed", self.root / "dump" / "empty", self.root / "dump" / "half"
        no_heap = self.root / "dump" / "no-heap"   # (#689: no System/HeapSize, and the game crashed at boot)
        packed.mkdir()
        (packed / "index.json").write_text("{}")
        (packed / "romfs.bin").write_bytes(b"authored packed stand-in")
        empty.mkdir()
        self.game_files(half)
        (half / "System" / "Resource").rmdir()
        self.game_files(no_heap, heapdef=None)
        for romfs, said, packed_copy in ((packed, "no Pack/ZsDic.pack.zs", True), (empty, "no Pack/ZsDic.pack.zs", False),
                                         (half, "no System/Resource", False), (no_heap, "no " + HEAPDEF, False)):
            with self.subTest(romfs=romfs.name):
                with self.assertRaises(SystemExit) as result:
                    self.run_to_lift(self.new_nup, folders=(romfs, exefs))
                self.assertEqual(result.exception.code, 1)
                self.assertIn("does not hold the game's files (%s): choose the extracted RomFS." % said, self.output)
                self.assertEqual("a packed copy" in self.output, packed_copy)
                self.assertFalse(self.out.exists())
                self.assertFalse((self.work / "exefs").exists())

    def test_romfs_folder_is_looked_at_as_a_long_path(self):
        # (Windows: a dump's Pack/ZsDic.pack.zs past 260 characters is found only through long_path, as the copy reads it)
        romfs = self.root / "dump" / "romfs"
        self.game_files(romfs)
        named = str(self.root / "dump" / "named-only-through-long-path")
        with mock.patch.object(make_game, "long_path", side_effect=lambda p: str(romfs) if p == named else p):
            make_game.check_romfs_folder(named)

    def test_romfs_folder_with_the_game_files_reaches_lift(self):
        romfs, exefs = self.root / "dump" / "romfs", self.root / "dump" / "exefs"
        self.game_files(romfs)
        exefs.mkdir(parents=True)
        (exefs / "main").write_bytes(module_bytes())
        with self.assertRaises(Prepared):
            self.run_to_lift(self.new_nup, folders=(romfs, exefs))
        self.assertTrue((self.out / "romfs" / "Pack" / "ZsDic.pack.zs").is_file())

    def test_romfs_folder_with_the_default_heap_definition_reaches_lift(self):
        # (the game opens the Product heap definition, then the Default one: either is enough)
        romfs, exefs = self.root / "dump" / "romfs", self.root / "dump" / "exefs"
        self.game_files(romfs, heapdef=DEFAULT_HEAPDEF)
        exefs.mkdir(parents=True)
        (exefs / "main").write_bytes(module_bytes())
        with self.assertRaises(Prepared):
            self.run_to_lift(self.new_nup, folders=(romfs, exefs))
        self.assertTrue((self.out / "romfs" / DEFAULT_HEAPDEF).is_file())

    def test_nup_without_the_start_files_is_refused_and_the_previous_cache_kept(self):
        # (a .nup unpacked into a romfs without the heap definition: refused before it replaces the folder's files)
        before = self.cache()
        with self.assertRaises(SystemExit) as result:
            self.run_to_lift(self.new_nup, start_files=False)
        self.assertEqual(self.extractions, [self.new_nup])
        self.assertEqual(result.exception.code, 1)
        self.assertIn("Your .nup file %s does not hold all of the game's files (no Pack/ZsDic.pack.zs): a game built from "
                      "it could not start. Dump the game again" % self.new_nup, self.output)
        self.assertEqual(self.cache(), before)
        self.assertFalse((self.out / ".game").exists())

    def test_cached_nup_or_update_without_the_start_files_is_refused(self):
        # (a folder unpacked by a builder before this check, or kept for an update: refused before the build)
        (self.out / "romfs" / HEAPDEF).unlink()
        for update, said in ((False, "Your .nup file %s" % self.old_nup),
                             (True, "This game folder's copy of the game files (%s)" % (self.out / "romfs"))):
            with self.subTest(update=update):
                with self.assertRaises(SystemExit) as result:
                    self.run_to_lift(self.old_nup, update=update)
                self.assertEqual(result.exception.code, 1)
                self.assertIn("%s does not hold all of the game's files (no %s)" % (said, HEAPDEF), self.output)
                self.assertEqual(self.extractions, [])

    def test_reparse_cache_is_rejected_before_extraction_or_replacement(self):
        before = self.cache()
        original_lstat = os.lstat

        def reparse_romfs(path, *args, **kwargs):
            result = original_lstat(path, *args, **kwargs)
            if Path(path).absolute() != self.out / "romfs":
                return result

            class ReparseStat:
                st_file_attributes = getattr(result, "st_file_attributes", 0) | 0x400

                def __getattr__(self, name):
                    return getattr(result, name)

            return ReparseStat()

        source_romfs = self.root / "source-romfs"
        source_romfs.mkdir()
        (source_romfs / "new.bin").write_bytes(b"authored source asset")
        self.game_files(source_romfs)
        source_exefs = self.root / "source-exefs"
        source_exefs.mkdir()
        (source_exefs / "main").write_bytes(module_bytes())
        for folders in (None, (source_romfs, source_exefs)):
            with self.subTest(folders=folders), mock.patch.object(os, "lstat", side_effect=reparse_romfs):
                with self.assertRaises(SystemExit) as result:
                    self.run_to_lift(self.new_nup, folders=folders)
                self.assertEqual(result.exception.code, 1)
                self.assertIn("not a normal path inside the build folder", self.output)
                self.assertFalse((self.work / "exefs").exists())
                self.assertEqual(self.extractions, [])
                self.assertEqual(self.cache(), before)


class RomfsFromTests(NupCacheHarness):
    """--romfs-from (HOOKSHOT_ROMFS_FROM): another game folder unpacked from the same .nup gives this build its game files by
    hard links, its kept exefs and its damaged-texture check, and the .nup is not read again"""

    def setUp(self):
        super().setUp()
        self.other = self.root / "other version"
        romfs = self.other / "romfs" / "Data"
        romfs.mkdir(parents=True)
        (romfs / "a.zs").write_bytes(b"authored asset a")
        (self.other / "romfs" / "b.txt").write_bytes(b"authored asset b")
        game_files(self.other / "romfs")
        (self.other / ".hookshot_exefs").mkdir()
        (self.other / ".hookshot_exefs" / "main").write_bytes(module_bytes(payload=b"other authored module"))
        stamp = self.stamp(self.new_nup)
        (self.other / ".hookshot_romfs").write_text(stamp + "\n", encoding="utf-8", newline="")
        (self.other / ".hookshot_romfs_checked").write_text("resolved-v2\n" + stamp + "\n", encoding="utf-8", newline="")
        (self.other / make_game.HEADS).write_text(stamp + "\nData/a.zs\n", encoding="utf-8", newline="")

    def test_the_game_files_are_linked_not_read_again(self):
        with self.assertRaises(Prepared):
            self.run_to_lift(self.new_nup, romfs_from=self.other)
        self.assertEqual(self.extractions, [])
        self.assertIn("linked, not read again", self.output)
        for rel in ("Data/a.zs", "b.txt"):
            mine, theirs = self.out / "romfs" / rel, self.other / "romfs" / rel
            self.assertEqual(mine.read_bytes(), theirs.read_bytes())
            self.assertTrue(os.path.samefile(mine, theirs), rel + " is a hard link, not a copy")
        self.assertFalse((self.out / "romfs" / "asset.txt").exists())   # (the old unpack's files are gone with it)
        self.assertEqual((self.out / ".hookshot_exefs" / "main").read_bytes(), (self.other / ".hookshot_exefs" / "main").read_bytes())
        self.assertEqual((self.work / "exefs" / "main").read_bytes(), (self.other / ".hookshot_exefs" / "main").read_bytes())
        for name in (".hookshot_romfs", ".hookshot_romfs_checked", make_game.HEADS):
            self.assertEqual((self.out / name).read_bytes(), (self.other / name).read_bytes(), name)
        self.assertFalse((self.out / make_game.DAMAGED_NOTE).exists())
        self.assertEqual((self.out / "user" / "save" / "sentinel.txt").read_bytes(), b"authored save sentinel")

    def test_the_variable_a_launcher_sets_does_the_same(self):
        with mock.patch.dict(os.environ, {"HOOKSHOT_ROMFS_FROM": str(self.other)}), self.assertRaises(Prepared):
            self.run_to_lift(self.new_nup)
        self.assertEqual(self.extractions, [])
        self.assertTrue(os.path.samefile(self.out / "romfs" / "b.txt", self.other / "romfs" / "b.txt"))

    def test_a_folder_from_another_nup_is_not_used(self):
        third = self.root / "third.nup"
        third.write_bytes(b"a third authored input, of its own size")
        with self.assertRaises(Prepared):
            self.run_to_lift(third, romfs_from=self.other)
        self.assertEqual(self.extractions, [third])
        self.assertIn("unpacked from another .nup", self.output)
        self.assertFalse((self.out / "romfs" / "b.txt").exists())

    def test_a_folder_without_what_the_game_needs_is_passed_over(self):
        shutil.rmtree(self.other / "romfs" / "Pack")   # (unpacked by a builder before the romfs check)
        with self.assertRaises(Prepared):
            self.run_to_lift(self.new_nup, romfs_from=self.other)
        self.assertEqual(self.extractions, [self.new_nup])
        self.assertIn("this .nup is read", self.output)
        self.assertFalse((self.out / "romfs" / "b.txt").exists())

    def test_a_folder_without_its_code_is_passed_over_and_nothing_goes_first(self):
        (self.other / ".hookshot_exefs" / "main").unlink()   # (a matching stamp, but no code to build from)
        with self.assertRaises(Prepared):
            self.run_to_lift(self.new_nup, romfs_from=self.other)
        self.assertEqual(self.extractions, [self.new_nup])
        self.assertIn("can't be built from (no main): this .nup is read", self.output)
        self.assertEqual((self.out / "romfs" / "new-only.txt").read_bytes(), b"new authored file")
        self.assertFalse((self.out / "romfs" / "b.txt").exists())

    def test_a_link_that_stops_leaves_the_last_copy(self):
        def stop_part_way(src, dst):
            Path(dst, "Data").mkdir(parents=True)
            Path(dst, "Data", "a.zs").write_bytes(b"half")
            raise OSError(errno.ENOSPC, "authored disk-full failure")
        before = self.cache()
        romfs, kept = str(self.out / "romfs"), str(self.out / ".hookshot_exefs")
        said = io.StringIO()
        with mock.patch.object(make_game, "link_or_copy", side_effect=stop_part_way), contextlib.redirect_stdout(said):
            used = make_game.romfs_from_build(str(self.other), str(self.out), self.stamp(self.new_nup), romfs, kept,
                                              str(self.work / "exefs"))
        self.assertFalse(used, "a link that stops part-way leaves the .nup to be read")
        self.assertIn("linking the game files from %s stopped (authored disk-full failure): this .nup is read" % self.other,
                      said.getvalue())
        self.assertEqual(self.cache(), before, "this folder's last usable copy (romfs, kept code, stamp) is as it was")
        self.assertEqual(sorted(p.name for p in self.out.iterdir() if p.name.endswith(".part")), [])

    def test_a_link_that_stops_reads_the_nup_instead(self):
        def stop_part_way(src, dst):
            Path(dst).mkdir(parents=True)
            raise OSError(errno.ENOENT, "authored: the other folder went away")
        with mock.patch.object(make_game, "link_or_copy", side_effect=stop_part_way), self.assertRaises(Prepared):
            self.run_to_lift(self.new_nup, romfs_from=self.other)
        self.assertEqual(self.extractions, [self.new_nup])
        self.assertIn("stopped (authored: the other folder went away): this .nup is read", self.output)
        self.assertEqual((self.out / "romfs" / "new-only.txt").read_bytes(), b"new authored file")
        self.assertFalse((self.out / "romfs" / "b.txt").exists())

    def test_folders_that_cannot_be_hard_linked_read_the_nup(self):
        real_link, tried = os.link, []
        def no_links(src, dst, *args, **kwargs):   # (another drive, or a disk without hard links)
            tried.append(dst)
            raise OSError(errno.EXDEV, "authored: not the same device")
        with mock.patch.object(make_game.os, "link", side_effect=no_links), self.assertRaises(Prepared):
            self.run_to_lift(self.new_nup, romfs_from=self.other)
        self.assertEqual(self.extractions, [self.new_nup])
        self.assertIn("can't be hard-linked into %s (authored: not the same device: another drive, or a disk without hard "
                      "links): this .nup is read" % self.out, self.output)
        self.assertEqual([Path(t).name for t in tried], [".hookshot-link-probe"], "one try, not one a file")
        self.assertFalse((self.out / ".hookshot-link-probe").exists())
        self.assertFalse((self.out / "romfs" / "b.txt").exists())
        self.assertIs(os.link, real_link)

    def test_the_link_probe_leaves_nothing(self):
        probe = self.out / ".hookshot-link-probe"
        why = make_game.link_problem(str(self.other / "romfs"), str(probe))
        if why:
            self.skipTest("no hard links here: %s" % why)
        self.assertFalse(probe.exists())
        self.assertEqual(make_game.link_problem(str(self.root / "empty romfs"), str(probe)), "no files in it")

    def test_a_mark_linked_out_of_the_folder_is_not_written_through(self):
        sentinel = self.root / "outside sentinel.txt"
        sentinel.write_bytes(b"authored sentinel outside the build folder")
        try:
            os.link(sentinel, self.out / ".hookshot_romfs_checked")
        except OSError as e:
            self.skipTest("no hard links here: %s" % e)
        with self.assertRaises(Prepared):
            self.run_to_lift(self.new_nup, romfs_from=self.other)
        self.assertEqual(sentinel.read_bytes(), b"authored sentinel outside the build folder")
        self.assertEqual((self.out / ".hookshot_romfs_checked").read_bytes(), (self.other / ".hookshot_romfs_checked").read_bytes())

    def test_a_mark_that_is_a_symbolic_link_stops_the_build_before_any_write(self):
        sentinel = self.root / "outside sentinel.txt"
        sentinel.write_bytes(b"authored sentinel outside the build folder")
        try:
            os.symlink(sentinel, self.out / make_game.HEADS)
        except OSError as e:
            self.skipTest("no symbolic links here: %s" % e)
        with self.assertRaises(SystemExit):
            self.run_to_lift(self.new_nup, romfs_from=self.other)
        self.assertEqual(sentinel.read_bytes(), b"authored sentinel outside the build folder")
        self.assertEqual((self.out / "romfs" / "asset.txt").read_bytes(), b"old authored assets")

    def test_a_folder_with_no_game_files_is_passed_over(self):
        with self.assertRaises(Prepared):
            self.run_to_lift(self.new_nup, romfs_from=self.root / "nowhere")
        self.assertEqual(self.extractions, [self.new_nup])

    def test_the_folder_itself_is_not_its_own_source(self):
        with self.assertRaises(Prepared):
            self.run_to_lift(self.new_nup, romfs_from=self.out)
        self.assertEqual(self.extractions, [self.new_nup])
        self.assertNotIn("linked, not read again", self.output)

    def test_the_same_nup_in_the_folder_itself_still_wins(self):
        (self.out / ".hookshot_romfs").write_text(self.stamp(self.new_nup) + "\n", encoding="utf-8", newline="")
        with self.assertRaises(Prepared):
            self.run_to_lift(self.new_nup, romfs_from=self.other)
        self.assertEqual(self.extractions, [])
        self.assertIn("reading it again is skipped", self.output)
        self.assertEqual((self.out / "romfs" / "asset.txt").read_bytes(), b"old authored assets")


class RomfsCopyTests(unittest.TestCase):
    def test_interrupted_cross_volume_copy_can_be_retried(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-romfs-copy-") as folder:
            src, dst = Path(folder) / "source", Path(folder) / "destination"
            src.mkdir()
            dst.mkdir()
            payload = b"complete authored asset"
            (src / "asset.bin").write_bytes(payload)
            (src / "existing.bin").write_bytes(b"source asset")
            (dst / "existing.bin").write_bytes(b"existing destination asset")

            def run_out_of_space(source, target):
                Path(target).write_bytes(Path(source).read_bytes()[:4])
                raise OSError(errno.ENOSPC, "authored disk-full failure")

            with mock.patch.object(make_game.os, "link", side_effect=OSError(errno.EXDEV, "different volumes")), \
                    contextlib.redirect_stdout(io.StringIO()):
                with mock.patch.object(make_game.shutil, "copy2", side_effect=run_out_of_space):
                    with self.assertRaises(OSError) as failure:
                        make_game.link_or_copy(src, dst)
                self.assertEqual(failure.exception.errno, errno.ENOSPC)
                self.assertEqual({p.name for p in dst.iterdir()}, {"existing.bin"})
                make_game.link_or_copy(src, dst)

            self.assertEqual((dst / "asset.bin").read_bytes(), payload)
            self.assertEqual((dst / "existing.bin").read_bytes(), b"existing destination asset")
            self.assertEqual({p.name for p in dst.iterdir()}, {"asset.bin", "existing.bin"})

    def test_failed_replacement_removes_the_staged_read_only_copy(self):
        with tempfile.TemporaryDirectory(prefix="hookshot-romfs-replace-") as folder:
            src, dst = Path(folder) / "source", Path(folder) / "destination"
            src.mkdir()
            source = src / "asset.bin"
            source.write_bytes(b"authored read-only asset")
            source.chmod(stat.S_IREAD)
            with mock.patch.object(make_game.os, "link", side_effect=OSError(errno.EXDEV, "different volumes")), \
                    mock.patch.object(make_game.os, "replace", side_effect=PermissionError("authored replacement failure")):
                with self.assertRaisesRegex(PermissionError, "authored replacement failure"):
                    make_game.link_or_copy(src, dst)
            self.assertEqual(list(dst.iterdir()), [])
            self.assertEqual(source.read_bytes(), b"authored read-only asset")
            self.assertFalse(source.stat().st_mode & stat.S_IWRITE)

    def test_links_in_an_extracted_dump_are_refused(self):
        # (a link in --romfs or --exefs was followed: the file it named was hard-linked or copied into the game folder)
        with tempfile.TemporaryDirectory(prefix="hookshot-dump-links-") as folder:
            src, secret = Path(folder) / "romfs", Path(folder) / "secret"
            (src / "Model").mkdir(parents=True)
            (src / "Model" / "a.zs").write_bytes(b"game data")
            secret.write_bytes(b"not the game's")
            make_game.refuse_dump_links(src)   # (plain files and folders)
            for name, target in (("b.zs", secret), ("Link", Path(folder))):
                link = src / "Model" / name
                try:
                    link.symlink_to(target)
                except OSError:
                    self.skipTest("no symbolic links here")
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                    make_game.refuse_dump_links(src)
                link.unlink()

    @unittest.skipUnless(os.name == "nt", "a junction is Windows'")
    def test_a_junction_deep_in_a_dump_is_refused(self):
        # (a junction needs no right to make, unlike a symbolic link: Windows' own way to link a folder. It is read from the
        # folder's listing now, not an lstat per file: its reparse-point attribute must still be seen, three folders down)
        import _winapi
        with tempfile.TemporaryDirectory(prefix="hookshot-dump-junction-") as folder:
            src, elsewhere = Path(folder) / "romfs", Path(folder) / "elsewhere"
            (src / "Model" / "Deep").mkdir(parents=True)
            (src / "Model" / "Deep" / "a.zs").write_bytes(b"game data")
            elsewhere.mkdir()
            make_game.refuse_dump_links(src)
            _winapi.CreateJunction(str(elsewhere), str(src / "Model" / "Deep" / "Door"))
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                make_game.refuse_dump_links(src)
            self.assertIn("Door", out.getvalue())

    def test_a_folder_that_cannot_be_read_is_said_not_passed_over(self):
        # (os.walk passed over a folder it could not list, and its files were missing from the game folder without a word)
        with tempfile.TemporaryDirectory(prefix="hookshot-dump-unreadable-") as folder:
            src = Path(folder) / "romfs"
            (src / "Model" / "Locked").mkdir(parents=True)
            real = os.scandir

            def scandir(path):
                if os.path.basename(str(path)) == "Locked":
                    raise PermissionError(13, "Access is denied")
                return real(path)
            out = io.StringIO()
            with mock.patch.object(make_game.os, "scandir", scandir), contextlib.redirect_stdout(out), \
                    self.assertRaises(SystemExit):
                make_game.refuse_dump_links(src)
            self.assertIn("Could not read the game files", out.getvalue())
            self.assertIn("Access is denied", out.getvalue())


if __name__ == "__main__":
    unittest.main()
