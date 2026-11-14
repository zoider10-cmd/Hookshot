"""scripts/oot_saves.py, game-free: finding Hookshot's and every emulator's folders, importing and exporting, the backups,
the guards, and the Hookshot import's checks (the launcher's). Temp folders and made-up saves only: HOME, XDG_DATA_HOME,
APPDATA and LOCALAPPDATA all point into one.

python -I -B tests/test_oot_saves.py
"""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import unittest
from unittest import mock

# (Linux only)
RUN_ALL_SKIP = {
    "windows": "the save script's folder discovery is the Linux one"
               " (on Windows Hookshot's saves are in the game folder: --hookshot)",
}

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("oot_saves", ROOT / "scripts" / "oot_saves.py")
oot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oot)

UID = "0123456789abcdef0123456789abcdef"
PROFILE = "FEDCBA9876543210FEDCBA9876543210"
ACCOUNT = "00112233445566778899aabbccddeeff"


def make_save(folder, tag, slots=("slot_00", "slot_01")):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "account.sav").write_bytes(b"account-" + tag)
    (folder / "option.sav").write_bytes(b"option-" + tag)
    for s in slots:
        (folder / s).mkdir()
        (folder / s / "progress.sav").write_bytes(b"progress-" + tag + s.encode())
        (folder / s / "caption.sav").write_bytes(b"caption-" + tag + s.encode())


def tree(folder):
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def eden_save(data, profile=PROFILE):
    return data / "nand" / "user" / "save" / oot.NO_ACCOUNT / profile / oot.TITLE


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "home"
        self.data = self.home / ".local" / "share"
        self.appdata = self.home / "AppData" / "Roaming"
        self.localappdata = self.home / "AppData" / "Local"
        self.hs = self.data / "hookshot" / "save" / UID
        self.li = eden_save(self.data / "eden")
        make_save(self.hs, b"HS")
        make_save(self.li, b"LI", slots=("slot_00",))
        self.backups = self.tmp / "backups"
        env = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home), "XDG_DATA_HOME": str(self.data),
                                           "APPDATA": str(self.appdata), "LOCALAPPDATA": str(self.localappdata)})
        env.start()
        self.addCleanup(env.stop)
        idle = mock.patch.object(oot, "running_games", return_value=[])
        self.running = idle.start()
        self.addCleanup(idle.stop)

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = oot.main(list(args) + ["--backup-dir", str(self.backups)])
        return code, out.getvalue(), err.getvalue()

    def backup_dirs(self):
        return sorted(self.backups.iterdir()) if self.backups.exists() else []


class Discovery(Case):
    def test_every_entry_on_linux(self):
        make_save(eden_save(self.data / "eglantine"), b"EG")
        nx = self.home / "Games" / "Ocarina" / "profile" / "save" / ACCOUNT
        make_save(nx, b"NX")
        expect = {"lichii": self.li, "frizti": self.li, "orchid": self.li, "pokedinner": self.li, "eden": self.li,
                  "eglantine": eden_save(self.data / "eglantine"), "nx2navi": nx}
        self.assertEqual(sorted(expect), sorted(p.name for p in oot.EMULATORS))
        for program in oot.EMULATORS:
            folder, found = oot.locate(program, None, "--from")
            self.assertEqual(list(found.values()), [str(expect[program.name])], program.name)
        self.assertEqual(oot.locate(oot.HOOKSHOT, None, "--hookshot")[1], {UID: str(self.hs)})

    def test_every_entry_on_windows(self):
        win_li = eden_save(self.appdata / "eden")
        win_eg = eden_save(self.appdata / "eglantine")
        win_nx = self.localappdata / "Programs" / "NX2navi" / "game" / "profile" / "save" / ACCOUNT
        for folder in (win_li, win_eg, win_nx):
            make_save(folder, b"W")
        expect = {"lichii": win_li, "frizti": win_li, "orchid": win_li, "pokedinner": win_li, "eden": win_li,
                  "eglantine": win_eg, "nx2navi": win_nx}
        with mock.patch.object(oot, "WINDOWS", True):
            for program in oot.EMULATORS:
                self.assertEqual(list(oot.locate(program, None, "--from")[1].values()), [str(expect[program.name])])
            with self.assertRaises(oot.Fail) as e:
                oot.locate(oot.HOOKSHOT, None, "--hookshot")
            self.assertIn("--hookshot", str(e.exception))
            self.assertIn(str(self.home / "Games" / "Hookshot"), str(e.exception))
            game = self.tmp / "Hookshot"
            make_save(game / "user" / "save" / UID, b"W")
            self.assertEqual(oot.locate(oot.HOOKSHOT, str(game), "--hookshot")[1], {UID: str(game / "user" / "save" / UID)})
            # (the builder's default game folder, when nothing is passed)
            default = self.home / "Games" / "Hookshot" / "user" / "save" / UID
            make_save(default, b"D")
            self.assertEqual(oot.locate(oot.HOOKSHOT, None, "--hookshot")[1], {UID: str(default)})

    def test_lichii_s_own_folder_first(self):
        # (Lichii from its build 150 on keeps %APPDATA%\\lichii, ~/.local/share/lichii; the others stay in Eden's)
        own = eden_save(self.data / "lichii")
        make_save(own, b"L2", slots=("slot_02",))
        by_name = {p.name: p for p in oot.EMULATORS}
        self.assertEqual(oot.locate(by_name["lichii"], None, "--from"), (str(self.data / "lichii"), {PROFILE: str(own)}))
        for name in ("frizti", "orchid", "pokedinner", "eden"):
            self.assertEqual(list(oot.locate(by_name[name], None, "--from")[1].values()), [str(self.li)], name)
        win_own, win_eden = eden_save(self.appdata / "lichii"), eden_save(self.appdata / "eden")
        make_save(win_own, b"W2")
        make_save(win_eden, b"W1")
        with mock.patch.object(oot, "WINDOWS", True):
            self.assertEqual(list(oot.locate(by_name["lichii"], None, "--from")[1].values()), [str(win_own)])
            self.assertEqual(list(oot.locate(by_name["orchid"], None, "--from")[1].values()), [str(win_eden)])

    def test_lichii_s_own_folder_without_a_save_leaves_the_older_one(self):
        (self.data / "lichii" / "nand" / "user" / "save").mkdir(parents=True)   # (started, the game never saved there)
        by_name = {p.name: p for p in oot.EMULATORS}
        self.assertEqual(list(oot.locate(by_name["lichii"], None, "--from")[1].values()), [str(self.li)])

    def test_lichii_s_copy_goes_to_its_own_folder(self):
        own = eden_save(self.data / "lichii")
        make_save(own, b"L2", slots=("slot_02",))
        before = tree(self.li)
        code, out, err = self.run_main("export", "lichii")
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(own), tree(self.hs))
        self.assertEqual(tree(self.li), before, "Eden's folder was written for Lichii")
        (own / "account.sav").write_bytes(b"played on in Lichii")
        code, out, err = self.run_main("import", "lichii")
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(self.hs), tree(own))
        self.assertEqual(tree(self.li), before)

    def test_aliases_of_names(self):
        self.assertIs(oot.program_named("Fritchii"), oot.program_named("frizti"))
        with self.assertRaises(oot.Fail):
            oot.program_named("ryujinx")

    def test_deeper_and_shallower_folders(self):
        data = self.data / "eden"
        for root in (data, data / "nand", data / "nand" / "user" / "save", self.li.parent.parent, self.li.parent,
                     self.li):
            self.assertEqual(oot.find_saves(str(root)), {PROFILE: str(self.li)}, root)
        for root in (self.data / "hookshot", self.hs.parent, self.hs):
            self.assertEqual(oot.find_saves(str(root)), {UID: str(self.hs)}, root)

    def test_empty_title_folder_is_a_target(self):
        empty = eden_save(self.tmp / "portable" / "user", "11111111111111111111111111111111")
        empty.mkdir(parents=True)
        self.assertEqual(oot.find_saves(str(self.tmp / "portable" / "user")),
                         {"11111111111111111111111111111111": str(empty)})
        self.assertEqual(oot.find_saves(str(empty)), {"11111111111111111111111111111111": str(empty)})

    def test_eden_newer_layout(self):
        data = self.tmp / "newer"
        uuid = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
        save = data / "nand" / "user" / "save" / "account" / uuid / oot.TITLE / "0"
        make_save(save, b"NEW")
        for root in (data, save.parent, save):
            self.assertEqual(oot.find_saves(str(root)), {uuid: str(save)}, root)

    def test_unrelated_folders_are_not_saves(self):
        (self.tmp / "junk" / "a" / "0").mkdir(parents=True)
        (self.tmp / "junk" / "b" / "save" / UID).mkdir(parents=True)
        self.assertEqual(oot.find_saves(str(self.tmp / "junk")), {})

    def test_missing_folders(self):
        with self.assertRaises(oot.Fail):
            oot.locate(oot.FOLDER, str(self.tmp / "nothing"), "--from")
        (self.tmp / "empty").mkdir()
        with self.assertRaises(oot.Fail):
            oot.locate(oot.FOLDER, str(self.tmp / "empty"), "--from")
        with self.assertRaises(oot.Fail) as e:
            oot.locate(oot.program_named("eglantine"), None, "--from")
        self.assertIn(str(self.data / "eglantine"), str(e.exception))

    def test_ambiguous_profiles_listed(self):
        other = "11111111111111111111111111111111"
        make_save(eden_save(self.data / "eden", other), b"O")
        before = tree(self.li)
        code, out, err = self.run_main("export", "lichii")
        self.assertEqual(code, 1)
        self.assertIn(PROFILE, err)
        self.assertIn(other, err)
        self.assertIn("--profile", err)
        self.assertEqual(tree(self.li), before)
        self.assertEqual(self.backup_dirs(), [])
        code, out, err = self.run_main("export", "lichii", "--profile", other.lower())
        self.assertEqual(code, 0, err)

    def test_list(self):
        make_save(self.home / "Games" / "Ocarina" / "profile" / "save" / ACCOUNT, b"NX")
        code, out, err = self.run_main("list")
        self.assertEqual(code, 0, err)
        for text in (UID, PROFILE, ACCOUNT, "slot_01", "Lichii / Frizti (Fritchii) / Orchid / PokeDinner / Eden", "NX2navi",
                     "Eglantine: nothing in"):
            self.assertIn(text, out)

    def test_list_with_lichii_s_own_folder(self):
        make_save(eden_save(self.data / "lichii"), b"L2", slots=("slot_02",))
        code, out, err = self.run_main("list")
        self.assertEqual(code, 0, err)
        self.assertIn("Lichii: %s\n" % (self.data / "lichii"), out)
        self.assertIn("Frizti (Fritchii) / Orchid / PokeDinner / Eden (one shared folder): %s\n" % (self.data / "eden"), out)
        self.assertIn("slot_02", out)
        self.assertEqual(out.count(str(self.data / "eden") + "\n"), 1)

    def test_list_with_no_emulator_save(self):
        for f in sorted(self.li.rglob("*"), reverse=True):
            f.unlink() if f.is_file() else f.rmdir()
        self.li.rmdir()
        code, out, err = self.run_main("list")
        self.assertEqual(code, 0, err)
        self.assertIn("Lichii: nothing in %s, %s\n" % (self.data / "lichii", self.data / "eden"), out)
        self.assertIn("Frizti (Fritchii) / Orchid / PokeDinner / Eden (one shared folder): nothing in %s\n" % (self.data / "eden"), out)

    def test_list_without_hookshot(self):
        (self.hs / "account.sav").unlink()
        for s in ("slot_00", "slot_01"):
            for f in (self.hs / s).iterdir():
                f.unlink()
            (self.hs / s).rmdir()
        code, out, err = self.run_main("list")
        self.assertEqual(code, 0, err)
        self.assertIn("Hookshot: no Hookshot save found", out)
        self.assertIn(PROFILE, out)


class Copy(Case):
    def test_export(self):
        before = tree(self.li)
        code, out, err = self.run_main("export", "lichii")
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(self.li), tree(self.hs))
        (backup,) = self.backup_dirs()
        self.assertTrue(backup.name.startswith("export-lichii-"))
        self.assertEqual(tree(backup), before)

    def test_import(self):
        before = tree(self.hs)
        code, out, err = self.run_main("import", "orchid")
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(self.hs), tree(self.li))
        self.assertNotIn("slot_01", tree(self.hs))
        (backup,) = self.backup_dirs()
        self.assertTrue(backup.name.startswith("import-orchid-"))
        self.assertEqual(tree(backup), before)

    def test_old_names_are_gone(self):
        # (to-lichii, to-hookshot and --lichii were Hookshot-era spellings of export lichii, import lichii and --from/--to)
        for argv in (["to-lichii"], ["to-hookshot"], ["import", "--lichii", str(self.data / "eden")]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                oot.main(argv)
        self.assertEqual(self.backup_dirs(), [])

    def test_import_into_a_hookshot_without_a_save(self):
        # (Hookshot never started: the save goes where it will look, save/<its one user id>, and there is nothing to back up)
        shutil.rmtree(self.data / "hookshot")
        code, out, err = self.run_main("import", "lichii")
        self.assertEqual(code, 0, err)
        made = self.data / "hookshot" / "save" / oot.USER_ID
        self.assertEqual(tree(made), tree(self.li))
        self.assertEqual(self.backup_dirs(), [])
        self.assertIn("there is no save there yet", out)

    def test_export_never_makes_an_emulator_s_folder(self):
        shutil.rmtree(self.data / "eden")
        code, out, err = self.run_main("export", "lichii")
        self.assertEqual(code, 1)
        self.assertIn("no Lichii save found", err)
        self.assertFalse((self.data / "eden").exists())

    def test_from_a_save_folder_and_a_data_folder(self):
        other = self.tmp / "backup of a save"
        make_save(other, b"F", slots=("slot_03",))
        code, out, err = self.run_main("import", "--from", str(other))
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(self.hs), tree(other))
        portable = self.tmp / "Lichii" / "user"
        make_save(eden_save(portable), b"P", slots=("slot_04",))
        code, out, err = self.run_main("import", "--from", str(portable))
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(self.hs), tree(eden_save(portable)))
        self.assertTrue(all(b.name.startswith("import-folder-") for b in self.backup_dirs()))

    def test_to_a_folder(self):
        portable = self.tmp / "Eglantine" / "user"
        target = eden_save(portable)
        target.mkdir(parents=True)   # (the game started once, nothing saved yet)
        code, out, err = self.run_main("export", "eglantine", "--to", str(portable))
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(target), tree(self.hs))

    def test_from_and_to_belong_to_their_command(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                oot.main(["export", "--from", str(self.li)])
            with self.assertRaises(SystemExit):
                oot.main(["import", "--to", str(self.li)])
        code, out, err = self.run_main("import")
        self.assertEqual(code, 1)
        self.assertIn("--from", err)

    def test_links_in_a_save_refused(self):
        secret = self.tmp / "secret.txt"
        secret.write_bytes(b"not a save")
        before = tree(self.hs)
        for make in (lambda o: (o / "slot_00" / "progress.sav").unlink() or (o / "slot_00" / "progress.sav").symlink_to(secret),
                     lambda o: (o / "account.sav").unlink() or (o / "account.sav").symlink_to(secret),
                     lambda o: (o / "slot_00" / "deep").symlink_to(self.tmp, target_is_directory=True)):
            other = self.tmp / ("linked-%d" % len(list(self.tmp.glob("linked-*"))))
            make_save(other, b"L", slots=("slot_00",))
            make(other)
            code, out, err = self.run_main("import", "--from", str(other))
            self.assertEqual(code, 1, out)
            self.assertIn("is a link", err)
            self.assertEqual(tree(self.hs), before)
        self.assertEqual(secret.read_bytes(), b"not a save")

    def test_junction_refused(self):
        # (a Windows junction is a reparse point, not a symbolic link; os.path.isjunction is only in Python 3.12 and newer)
        other = self.tmp / "junction"
        make_save(other, b"J", slots=("slot_00",))
        deep = other / "slot_00" / "deep"
        deep.mkdir()
        real_lstat = os.lstat

        class Junction:
            def __init__(self, st):
                self.st_mode, self.st_file_attributes = st.st_mode, 0x400 | 0x10

        def lstat(path, *a, **k):
            st = real_lstat(path, *a, **k)
            return Junction(st) if os.path.abspath(path) == str(deep) else st
        before = tree(self.hs)
        with mock.patch.object(oot.os, "lstat", lstat):
            code, out, err = self.run_main("import", "--from", str(other))
        self.assertEqual(code, 1, out)
        self.assertIn("is a link", err)
        self.assertEqual(tree(self.hs), before)

    def test_same_folder_refused(self):
        code, out, err = self.run_main("import", "--from", str(self.hs))
        self.assertEqual(code, 1)
        self.assertIn("both the source and the target", err)

    def test_backup_inside_target_refused_before_copy(self):
        self.backups = self.hs / "backups"
        before = tree(self.hs)
        for extra in ((), ("--dry-run",)):
            with self.subTest(extra=extra), mock.patch.object(
                oot.shutil, "copytree", side_effect=AssertionError("recursive backup copy started")
            ):
                code, _, err = self.run_main("import", "--from", str(self.li), "--hookshot", str(self.hs), *extra)
                self.assertEqual(code, 1)
                self.assertIn("--backup-dir outside the target save folder", err)
                self.assertFalse(self.backups.exists())
                self.assertEqual(tree(self.hs), before)

    def test_keep_settings(self):
        code, out, err = self.run_main("export", "lichii", "--keep-settings")
        self.assertEqual(code, 0, err)
        self.assertEqual((self.li / "option.sav").read_bytes(), b"option-LI")
        self.assertEqual((self.li / "account.sav").read_bytes(), b"account-HS")
        self.assertEqual((self.li / "slot_01" / "progress.sav").read_bytes(), b"progress-HSslot_01")

    def test_dry_run_changes_nothing(self):
        before = (tree(self.hs), tree(self.li))
        self.running.return_value = ["Lichii"]   # (a dry run does not mind)
        code, out, err = self.run_main("export", "lichii", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual((tree(self.hs), tree(self.li)), before)
        self.assertEqual(self.backup_dirs(), [])
        self.assertIn("Would copy", out)

    def test_source_without_slots(self):
        for s in ("slot_00", "slot_01"):
            for f in (self.hs / s).iterdir():
                f.unlink()
            (self.hs / s).rmdir()
        before = tree(self.li)
        code, out, err = self.run_main("export", "lichii")
        self.assertEqual(code, 1)
        self.assertEqual(tree(self.li), before)

    def fresh_saves(self):
        for folder in (self.hs, self.li):
            shutil.rmtree(folder)
        make_save(self.hs, b"HS")
        make_save(self.li, b"LI", slots=("slot_00",))

    def failed_copy_leaves_the_target(self, command, target, source, **patch):
        self.fresh_saves()
        before = tree(target)
        with mock.patch.object(oot.shutil, **patch), self.assertRaises(OSError):
            self.run_main(command, "lichii")
        self.assertEqual(tree(target), before)
        self.assertEqual(sorted(p.name for p in target.parent.iterdir()), [target.name])   # (nothing left beside it)
        self.assertEqual(sorted(p.name for p in target.iterdir()), sorted({Path(n).parts[0] for n in before}))   # (or in it)
        code, out, err = self.run_main(command, "lichii")   # (and the same copy works once the disk has room)
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(target), tree(source))

    def test_failed_copy_leaves_the_target(self):
        # (a disk that fills up while the new save is written: before, the old slots were already gone and half a save was left)
        real_copytree, real_replace = shutil.copytree, os.replace

        def full_disk(src, dst, *args, **kw):
            if Path(src).parent in (self.hs, self.li) and "-incoming-" in Path(dst).parent.name:
                real_copytree(src, dst, *args, **kw)
                raise OSError(28, "No space left on device")
            return real_copytree(src, dst, *args, **kw)

        def account_fails(src, dst, **kw):
            raise OSError(28, "No space left on device")

        def last_rename_fails(src, dst):   # (the last move into the target, after its old entries were moved aside)
            if Path(src).name == "account.sav" and "-incoming-" in Path(src).parent.name:
                raise OSError(13, "Permission denied")
            return real_replace(src, dst)

        for command, target, source in (("import", self.hs, self.li), ("export", self.li, self.hs)):
            for name, patch in (("slot", dict(attribute="copytree", side_effect=full_disk)),
                                ("account.sav", dict(attribute="copy2", side_effect=account_fails))):
                with self.subTest(command=command, failing=name):
                    self.failed_copy_leaves_the_target(command, target, source, **patch)
            with self.subTest(command=command, failing="rename"):
                self.fresh_saves()
                before = tree(target)
                with mock.patch.object(oot.os, "replace", side_effect=last_rename_fails), self.assertRaises(OSError):
                    self.run_main(command, "lichii")
                self.assertEqual(tree(target), before)
                self.assertEqual(sorted(p.name for p in target.parent.iterdir()), [target.name])
                self.assertEqual(sorted(p.name for p in target.iterdir()), sorted({Path(n).parts[0] for n in before}))

    def test_target_behind_a_link_or_in_a_read_only_folder(self):
        # (a save folder that links to another disk, as when moved to an SD card, and one in a folder that can't be written:
        # the new save is staged inside the target, where the swap's renames work)
        shm = Path("/dev/shm")
        cases = []
        other = Path(tempfile.mkdtemp(dir=shm)) if shm.is_dir() and os.access(shm, os.W_OK) else None
        if other is not None:
            self.addCleanup(shutil.rmtree, other, True)
            if other.stat().st_dev != self.tmp.stat().st_dev:
                cases.append(("link to another disk", other / "save"))
        cases.append(("link on the same disk", self.tmp / "elsewhere" / "save"))
        for name, real in cases:
            with self.subTest(name):
                self.fresh_saves()
                shutil.rmtree(real, ignore_errors=True)
                real.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(self.hs), real)
                self.hs.symlink_to(real, target_is_directory=True)
                code, out, err = self.run_main("import", "--from", str(self.li), "--hookshot", str(self.hs))
                self.assertEqual(code, 0, err)
                self.assertTrue(self.hs.is_symlink())
                self.assertEqual(tree(real), tree(self.li))
                self.assertEqual(sorted(p.name for p in real.parent.iterdir()), ["save"])
                self.hs.unlink()
                shutil.move(str(real), self.hs)
        if os.name == "posix" and os.geteuid() != 0:
            with self.subTest("a folder that can't be written"):
                self.fresh_saves()
                self.hs.parent.chmod(0o555)
                self.addCleanup(self.hs.parent.chmod, 0o755)
                code, out, err = self.run_main("import", "lichii")
                self.assertEqual(code, 0, err)
                self.assertEqual(tree(self.hs), tree(self.li))
                self.hs.parent.chmod(0o755)
    def rollback_that_fails_too(self, place_option, take_back):
        # (the forward failure: placing option.sav, the last new entry; then the new slot_00 can't be moved out again)
        real_replace = os.replace

        def replace(src, dst):
            if "-incoming-" in Path(src).parent.name and Path(src).name == "option.sav":
                place_option(Path(dst).parent)
            if Path(src).parent == self.hs and Path(src).name == "slot_00" and "-incoming-" in Path(dst).parent.name:
                take_back()
            return real_replace(src, dst)

        before = tree(self.hs)
        with mock.patch.object(oot.os, "replace", side_effect=replace):
            code, out, err = self.run_main("import", "--from", str(self.li), "--hookshot", str(self.hs))
        self.assertEqual(code, 1)
        (aside,) = [p for p in self.hs.iterdir() if p.name.startswith(".")]
        (backup,) = self.backup_dirs()
        self.assertIn("old ones left in %s: slot_00" % aside, err)
        self.assertIn("put the old save back from the backup, %s" % backup, err)
        # (every other old entry is back, the old slot_00 waits in aside, the new one stayed)
        self.assertEqual(sorted(p.name for p in self.hs.iterdir()), sorted([aside.name, "account.sav", "option.sav", "slot_00", "slot_01"]))
        for name, data in before.items():
            self.assertEqual((aside if Path(name).parts[0] == "slot_00" else self.hs).joinpath(name).read_bytes(), data, name)
        self.assertEqual(tree(self.hs / "slot_00"),
                         {str(Path(k).relative_to("slot_00")): v for k, v in tree(self.li).items() if Path(k).parts[0] == "slot_00"})
        self.assertEqual(tree(backup), before)

    def test_rollback_that_fails_too(self):
        def failing(_):
            raise OSError(28, "No space left on device")

        def held():
            raise PermissionError(13, "Access is denied")

        self.rollback_that_fails_too(failing, held)

    @unittest.skipUnless(os.name == "nt", "Windows: a file held open without delete sharing")
    def test_rollback_that_fails_too_with_a_file_held_open(self):
        handles = []
        self.addCleanup(lambda: [h.close() for h in handles])

        def hold_and_fail(target):
            handles.append(open(target / "slot_00" / "progress.sav", "rb"))   # (Python's open shares read and write, not delete)
            raise OSError(28, "No space left on device")

        self.rollback_that_fails_too(hold_and_fail, lambda: None)

    def test_read_only_file_in_the_old_save(self):
        # (on Windows a read-only file can't be deleted as it is: the old entries' folder was left in the target)
        (self.hs / "slot_01" / "progress.sav").chmod(stat.S_IREAD)
        code, out, err = self.run_main("import", "--from", str(self.li), "--hookshot", str(self.hs))
        self.assertEqual(code, 0, err)
        self.assertNotIn("could not delete", out)
        self.assertEqual(tree(self.hs), tree(self.li))
        self.assertEqual(sorted(p.name for p in self.hs.iterdir()), ["account.sav", "option.sav", "slot_00"])
        self.assertEqual(oot.save_problems(str(self.hs)), [])

    def test_old_save_that_cannot_be_deleted(self):
        # (the same on any system: a delete refused once is tried again after the read-only bit is cleared; one refused for
        # good is named, and the copy itself still counts)
        real_unlink = os.unlink
        refusals = []

        def unlink(path, *args, **kw):
            if os.path.basename(path) == "progress.sav" and len(refusals) < limit:
                refusals.append(path)
                raise PermissionError(13, "Access is denied")
            return real_unlink(path, *args, **kw)

        for limit, left in ((1, False), (10 ** 6, True)):
            with self.subTest(left=left):
                self.fresh_saves()
                refusals.clear()
                with mock.patch.object(oot.os, "unlink", side_effect=unlink):
                    code, out, err = self.run_main("import", "--from", str(self.li), "--hookshot", str(self.hs))
                self.assertEqual(code, 0, err)
                self.assertEqual(tree(self.hs) if not left else {k: v for k, v in tree(self.hs).items() if not k.startswith(".")},
                                 tree(self.li))
                leftovers = [p for p in self.hs.iterdir() if p.name.startswith(".")]
                if left:
                    (aside,) = leftovers
                    self.assertIn("Copied, but could not delete %s: delete it by hand." % aside, out)
                else:
                    self.assertEqual(leftovers, [])
                    self.assertNotIn("could not delete", out)
                self.assertIn("Done.", out)

class NX2navi(Case):
    def setUp(self):
        super().setUp()
        self.game = self.home / "Games" / "Ocarina"
        self.nx = self.game / "profile" / "save" / ACCOUNT
        make_save(self.nx, b"NX", slots=("slot_05",))
        (self.game / "profile" / "account.uid").write_bytes(bytes(16))
        (self.game / "profile" / "save-tx").mkdir()

    def test_both_ways(self):
        code, out, err = self.run_main("import", "nx2navi")
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(self.hs), tree(self.nx))
        make_save(self.hs / "slot_00", b"Z", slots=())
        code, out, err = self.run_main("export", "nx2navi", "--to", str(self.game))
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(self.nx), tree(self.hs))
        self.assertEqual((self.game / "profile" / "account.uid").read_bytes(), bytes(16))

    def test_waiting_save_refused(self):
        (self.game / "profile" / "save-tx" / "commit").write_bytes(b"pending")
        before = (tree(self.hs), tree(self.nx))
        for command in ("import", "export"):
            code, out, err = self.run_main(command, "nx2navi")
            self.assertEqual(code, 1)
            self.assertIn("save-tx", err)
        self.assertEqual((tree(self.hs), tree(self.nx)), before)
        self.assertEqual(self.backup_dirs(), [])
        code, out, err = self.run_main("import", "nx2navi", "--force")
        self.assertEqual(code, 0, err)


class Guard(Case):
    def test_refuses_while_running(self):
        self.running.return_value = ["Hookshot"]
        before = (tree(self.hs), tree(self.li))
        code, out, err = self.run_main("export", "lichii")
        self.assertEqual(code, 1)
        self.assertIn("Hookshot", err)
        self.assertEqual((tree(self.hs), tree(self.li)), before)
        self.assertEqual(self.backup_dirs(), [])

    def test_force(self):
        self.running.return_value = ["Lichii"]
        code, out, err = self.run_main("export", "lichii", "--force")
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(self.li), tree(self.hs))

    def real(self):
        # (the real running_games, not the test's mock of it)
        real = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(real)
        return real

    def test_every_process_name_on_windows(self):
        real = self.real()
        names = real.process_names()
        self.assertEqual(names["hookshot"], "Hookshot")
        for program in [real.HOOKSHOT] + real.OTHERS:
            self.assertTrue(program.processes, program.name)
            for p in program.processes:
                self.assertIn(program.display, names[p])
        out = "".join('"%s.exe","%d","Console","1","10 K"\r\n' % (p.upper() if i % 2 else p, i)
                      for i, p in enumerate(names))
        out += '"notepad.exe","4","x","1","1 K"\r\n'
        with mock.patch.object(real, "WINDOWS", True), \
             mock.patch.object(real.subprocess, "run", return_value=mock.Mock(stdout=out)):
            self.assertEqual(real.running_games(), sorted(set(names.values())))

    def test_linux_processes_and_appimages(self):
        real = self.real()
        procs = {"9": ("hookshot", "/home/x/Games/Hookshot/hookshot"), "10": ("orchid", "/opt/orchid/orchid"), "11": ("AppRun", "/home/x/eglantine-linux-x86_64.AppImage"),
                 "12": ("ocarina", "./ocarina"), "13": ("bash", "/bin/bash")}

        def fake_open(path, *a, **k):
            pid, what = path.split("/")[2:4]
            comm, argv0 = procs[pid]
            return io.BytesIO(argv0.encode() + b"\0-g\0") if what == "cmdline" else io.StringIO(comm + "\n")

        with mock.patch.object(real, "WINDOWS", False), \
             mock.patch.object(real.os, "listdir", return_value=list(procs) + ["self"]), \
             mock.patch("builtins.open", fake_open):
            self.assertEqual(real.running_games(), ["Hookshot", "NX2navi", "Orchid", "PokeDinner or Eglantine"])


class Hookshot(Case):
    """Hookshot, the project Hookshot was forked from: the same files in the same layout under its own folders"""

    def setUp(self):
        super().setUp()
        self.hk = self.data / "hookshot" / "save" / oot.USER_ID
        make_save(self.hk, b"HK", slots=("slot_00", "slot_02"))

    def test_user_id_is_the_host_s(self):
        # (host/nn_applet.c's one user, as host/nn_fs.c names its save folder: high word, then low word, 16 hex digits each)
        applet = (ROOT / "host" / "nn_applet.c").read_text(encoding="utf-8")
        low, high = re.search(r"user_uid\[2\] = \{0x([0-9a-fA-F]{16})ULL, 0x([0-9a-fA-F]{16})ULL\}", applet).groups()
        self.assertEqual(oot.USER_ID, (high + low).lower())
        fs = (ROOT / "host" / "nn_fs.c").read_text(encoding="utf-8")
        self.assertIn('"save\\\\%016llx%016llx", (unsigned long long)G64(ARG(1) + 8), (unsigned long long)G64(ARG(1))', fs)

    def test_found_on_linux_and_listed(self):
        self.assertEqual(oot.locate(oot.HOOKSHOT, None, "--hookshot"), (str(self.data / "hookshot"), {oot.USER_ID: str(self.hk)}))
        self.assertIs(oot.program_named("Hookshot"), oot.HOOKSHOT)
        code, out, err = self.run_main("list")
        self.assertEqual(code, 0, err)
        self.assertIn("Hookshot: %s\n" % (self.data / "hookshot"), out)
        self.assertIn("slot_02", out)

    def test_found_on_windows_in_the_game_folder_and_its_version_folders(self):
        games = self.home / "Games" / "Hookshot"
        with mock.patch.object(oot, "WINDOWS", True):
            with self.assertRaises(oot.Fail) as e:
                oot.locate(oot.HOOKSHOT, None, "--hookshot")
            self.assertIn("--hookshot", str(e.exception))
            version = games / "v3.0.1" / "user" / "save" / oot.USER_ID   # (Hookshot's launcher: a folder per version)
            make_save(version, b"V")
            self.assertEqual(oot.locate(oot.HOOKSHOT, None, "--hookshot")[1], {oot.USER_ID: str(version)})
            plain = games / "user" / "save" / oot.USER_ID                # (the 2.x builders' game folder)
            make_save(plain, b"P")
            self.assertEqual(oot.locate(oot.HOOKSHOT, None, "--hookshot")[1], {oot.USER_ID: str(plain)})

    def test_import_copies_byte_for_byte_and_leaves_hookshot_alone(self):
        before = tree(self.hk)
        old = tree(self.hs)
        code, out, err = self.run_main("import", "hookshot")
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(self.hs), before)
        self.assertEqual(tree(self.hk), before)
        (backup,) = self.backup_dirs()
        self.assertTrue(backup.name.startswith("import-hookshot-"))
        self.assertEqual(tree(backup), old)

    def test_import_into_a_hookshot_without_a_save(self):
        shutil.rmtree(self.data / "hookshot")
        code, out, err = self.run_main("import", "hookshot")
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(self.data / "hookshot" / "save" / oot.USER_ID), tree(self.hk))
        self.assertEqual(self.backup_dirs(), [])

    def test_export(self):
        code, out, err = self.run_main("export", "hookshot")
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(self.hk), tree(self.hs))
        (backup,) = self.backup_dirs()
        self.assertTrue(backup.name.startswith("export-hookshot-"))
        shutil.rmtree(self.data / "hookshot")
        code, out, err = self.run_main("export", "hookshot")   # (no Hookshot save yet: made where Hookshot looks)
        self.assertEqual(code, 0, err)
        self.assertEqual(tree(self.hk), tree(self.hs))

    def test_folder_flags(self):
        elsewhere = self.tmp / "Hookshot portable"
        make_save(elsewhere / "save" / oot.USER_ID, b"E", slots=("slot_01",))
        for flag in ("--hookshot", "--from"):
            code, out, err = self.run_main("import", "hookshot", flag, str(elsewhere))
            self.assertEqual(code, 0, err)
            self.assertEqual(tree(self.hs), tree(elsewhere / "save" / oot.USER_ID))
        code, out, err = self.run_main("import", "lichii", "--hookshot", str(elsewhere))
        self.assertEqual(code, 1)
        self.assertIn("--hookshot", err)

    def test_windows_import_into_the_game_folder(self):
        hk = self.home / "Games" / "Hookshot" / "user" / "save" / oot.USER_ID
        make_save(hk, b"W")
        game = self.home / "Games" / "Hookshot"
        with mock.patch.object(oot, "WINDOWS", True):
            code, out, err = self.run_main("import", "hookshot")   # (no Hookshot game folder: nowhere to put it)
            self.assertEqual(code, 1)
            self.assertIn("--hookshot", err)
            game.mkdir(parents=True)
            code, out, err = self.run_main("import", "hookshot")
            self.assertEqual(code, 0, err)
        self.assertEqual(tree(game / "user" / "save" / oot.USER_ID), tree(hk))

    def test_only_a_save_is_imported(self):
        # (the launcher's checks, Core/HookshotSaves.cs: only save files, none empty or over 4 MB, a progress.sav per slot)
        before = tree(self.hs)
        for name, spoil, why in (
                ("extra file", lambda d: (d / "notes.txt").write_bytes(b"x"), "notes.txt is not a save file"),
                ("in a slot", lambda d: (d / "slot_00" / "x.bin").write_bytes(b"x"), "slot_00/x.bin is not a save file"),
                ("empty", lambda d: (d / "account.sav").write_bytes(b""), "account.sav is empty"),
                ("large", lambda d: (d / "slot_00" / "progress.sav").write_bytes(b"\0" * (oot.MAX_SAVE_FILE + 1)),
                 "slot_00/progress.sav is too large"),
                ("no progress", lambda d: (d / "slot_00" / "progress.sav").unlink(), "slot_00 has no progress.sav")):
            with self.subTest(name):
                folder = self.tmp / ("bad " + name)
                make_save(folder / "save" / oot.USER_ID, b"B", slots=("slot_00",))
                spoil(folder / "save" / oot.USER_ID)
                code, out, err = self.run_main("import", "hookshot", "--hookshot", str(folder))
                self.assertEqual(code, 1, out)
                self.assertIn(why, err)
                self.assertIn("Nothing was copied", err)
                self.assertEqual(tree(self.hs), before)
        self.assertEqual(self.backup_dirs(), [])

    def test_refused_while_hookshot_runs(self):
        self.running.return_value = ["Hookshot"]
        before = tree(self.hs)
        code, out, err = self.run_main("import", "hookshot")
        self.assertEqual(code, 1)
        self.assertIn("close Hookshot first", err)
        self.assertEqual(tree(self.hs), before)


if __name__ == "__main__":
    unittest.main()
