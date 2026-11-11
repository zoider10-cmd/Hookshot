"""The launcher's kept copies of the saves (launcher/Launcher.cs: SaveCopies, the Save copies button).

The source is read on every platform: the button is there, opens the copies of the save folder the Randomizer setting
names, and a restore keeps what was there first and is refused while the game runs; a copy can be updated to the saves as they are. On Windows the launcher's source
is compiled with the .NET Framework's own compiler, as launcher/build.ps1 does, and SaveCopies is run on a made-up
save folder: a copy is whole and under its name, a name is made safe, a copy is not replaced, a restore puts the
copy in the save folder's place and keeps what was there, the randomizer's copies and the normal game's are apart,
and a copy can be deleted. No game data.

    python -I -B tests/test_save_copies.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(ok, what):
    if not ok:
        raise SystemExit("FAIL: " + what)


SCRIPT = r'''
$ErrorActionPreference = "Stop"
[Reflection.Assembly]::LoadFile($args[0]) | Out-Null
$dir = $args[1]
function Say($what, $value) { Write-Output ("{0}={1}" -f $what, $value) }
function Slot($folder, $text) {
    $p = Join-Path $dir ("user\" + $folder + "\0001\slot_00")
    New-Item -ItemType Directory -Force $p | Out-Null
    Set-Content -Path (Join-Path $p "progress.sav") -Value $text -NoNewline
}
function Read($folder) { Get-Content -Raw (Join-Path $dir ("user\" + $folder + "\0001\slot_00\progress.sav")) }
Say "empty" ([SaveCopies]::Keep($dir, "save_rando", "first"))
Slot "save_rando" "one"
Slot "save" "normal"
Say "clean" ([SaveCopies]::Clean('  a/b\c:d*e?f"g<h>i|j. . '))
Say "noname" ([SaveCopies]::Keep($dir, "save_rando", " .. "))
Say "keep1" ([SaveCopies]::Keep($dir, "save_rando", "first"))
Say "copy1" (Get-Content -Raw (Join-Path $dir "user\save_copies\save_rando\first\0001\slot_00\progress.sav"))
Say "again" ([SaveCopies]::Keep($dir, "save_rando", "first"))
Slot "save_rando" "two"
Start-Sleep -Milliseconds 1100
Say "keep2" ([SaveCopies]::Keep($dir, "save_rando", "second"))
Say "list" (([SaveCopies]::List($dir, "save_rando")) -join ",")
Say "listnormal" (([SaveCopies]::List($dir, "save")) -join ",")
Slot "save_rando" "three"
Start-Sleep -Milliseconds 1100
$now = [DateTime]::new(2026, 11, 11, 9, 8, 7)
Say "restore" ([SaveCopies]::Restore($dir, "save_rando", "first", $now))
Say "now" (Read "save_rando")
Say "normal" (Read "save")
Say "list2" (([SaveCopies]::List($dir, "save_rando")) -join ",")
Say "before" (Get-Content -Raw (Join-Path $dir "user\save_copies\save_rando\Before restore 2026-11-11 09.08.07\0001\slot_00\progress.sav"))
Say "leftover" ((Test-Path (Join-Path $dir "user\save_rando.old")) -or (Test-Path (Join-Path $dir "user\save_copies\save_rando\first.part")))
Say "gone" ([SaveCopies]::Restore($dir, "save_rando", "nothing", $now))
Say "outside" ([SaveCopies]::Restore($dir, "save_rando", "..\..\save", $now))
Say "now2" (Read "save_rando")
Slot "save_rando" "four"
Say "update" ([SaveCopies]::Update($dir, "save_rando", "second"))
Say "updated" (Get-Content -Raw (Join-Path $dir "user\save_copies\save_rando\second\0001\slot_00\progress.sav"))
Say "updategone" ([SaveCopies]::Update($dir, "save_rando", "nothing"))
Say "updateoutside" ([SaveCopies]::Update($dir, "save_rando", "..\..\save"))
Say "updateleft" ((Test-Path (Join-Path $dir "user\save_copies\save_rando\second.part")) -or (Test-Path (Join-Path $dir "user\save_copies\save_rando\second.old")))
Say "list4" (([SaveCopies]::List($dir, "save_rando")) -join ",")
Say "keepdefault" ([SaveCopies]::KeepBefore($dir))
[SaveCopies]::SetKeepBefore($dir, $false)
Say "keepoff" ([SaveCopies]::KeepBefore($dir))
Slot "save_rando" "five"
$count = ([SaveCopies]::List($dir, "save_rando")).Count
Say "restoreplain" ([SaveCopies]::Restore($dir, "save_rando", "first", $now, $false))
Say "nowplain" (Read "save_rando")
Say "noextra" (([SaveCopies]::List($dir, "save_rando")).Count -eq $count)
[SaveCopies]::SetKeepBefore($dir, $true)
Say "keepon" ([SaveCopies]::KeepBefore($dir))
Say "delete" ([SaveCopies]::Delete($dir, "save_rando", "second"))
Say "deleteoutside" ([SaveCopies]::Delete($dir, "save_rando", "..\..\save"))
Say "list3" (([SaveCopies]::List($dir, "save_rando")) -join ",")
Say "normal2" (Read "save")
'''


def main():
    src = (ROOT / "launcher" / "Launcher.cs").read_text(encoding="utf-8")
    check('Text = "Save copies"' in src and "new SaveCopiesForm(dir, SaveFolder())" in src,
          "the launcher has no Save copies button for the save folder the Randomizer setting names")
    check('return Path.Combine(dir, "user", Folder, saveFolder);' in src and 'public const string Folder = "save_copies";' in src,
          "the copies are not kept under the game folder's user folder, apart for each save folder")
    check('keepFirst.Checked = SaveCopies.KeepBefore(dir);' in src and "SaveCopies.Restore(dir, saveFolder, n, DateTime.Now, first);" in src and
          "if (keepFirst && HasFiles(to)) {" in src, "the window has no tick box for keeping the saves before a restore, or does not use it")
    check('if (LauncherForm.GameRunning())' in src and "string error = Keep(dir, saveFolder, kept);" in src,
          "a restore is not refused while the game runs, or does not keep what was there first")
    csc = Path(os.environ.get("WINDIR", "")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    if os.name != "nt" or not csc.is_file():
        print("PASS: the launcher's save copies (the source only: no .NET Framework compiler here)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        exe, game, script = Path(tmp) / "launcher_test.exe", Path(tmp) / "game", Path(tmp) / "run.ps1"
        game.mkdir()
        built = subprocess.run([str(csc), "/nologo", "/target:winexe", "/out:" + str(exe), "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll",
                                "/r:System.IO.Compression.dll", "/r:System.IO.Compression.FileSystem.dll", str(ROOT / "launcher" / "Launcher.cs")],
                               capture_output=True, text=True)
        check(built.returncode == 0, "the launcher does not compile:\n" + built.stdout + built.stderr)
        script.write_text(SCRIPT, encoding="utf-8")
        ran = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), str(exe), str(game)],
                             capture_output=True, text=True)
        check(ran.returncode == 0, "the save copies could not be run:\n" + ran.stdout + ran.stderr)
        got = dict(line.split("=", 1) for line in ran.stdout.splitlines() if "=" in line)
    check(got["empty"] != "" and got["noname"] != "", "a copy of no saves, or one without a name, was made")
    check(got["clean"] == "abcdefghij", "a name is not made safe for a folder: %r" % got["clean"])
    check(got["keep1"] == "" and got["copy1"] == "one", "a copy is not the saves, whole, under its name")
    check(got["again"] != "", "a copy of the same name was replaced")
    check(got["keep2"] == "" and got["list"] == "second,first", "the copies are not listed the newest first: %r" % got["list"])
    check(got["listnormal"] == "", "the normal game's copies show the randomizer's")
    check(got["restore"] == "" and got["now"] == "one", "a restore does not put the copy in the save folder's place")
    check(got["before"] == "three" and got["list2"] == "Before restore 2026-11-11 09.08.07,second,first",
          "a restore does not keep the saves that were there first: %r" % got["list2"])
    check(got["leftover"] == "False", "a restore leaves a half-made folder behind")
    check(got["gone"] != "" and got["outside"] != "" and got["now2"] == "one", "a copy that is not there, or a path out of the copies, was restored")
    check(got["update"] == "" and got["updated"] == "four" and got["updateleft"] == "False" and len(got["list4"].split(",")) == 3,
          "an update does not make the copy the saves as they are now, or leaves a half-made folder: %r" % got)
    check(got["updategone"] != "" and got["updateoutside"] != "", "a copy that is not there, or a path out of the copies, was updated")
    check(got["keepdefault"] == "True" and got["keepoff"] == "False" and got["keepon"] == "True",
          "a restore's keeping of the saves first is not on until turned off, or is not kept as set")
    check(got["restoreplain"] == "" and got["nowplain"] == "one" and got["noextra"] == "True",
          "a restore asked not to keep the saves first kept them, or did not put the copy in their place")
    check(got["delete"] == "" and got["deleteoutside"] != "" and got["list3"] == "Before restore 2026-11-11 09.08.07,first",
          "a copy is not deleted, or a path out of the copies was")
    check(got["normal"] == "normal" and got["normal2"] == "normal", "the normal game's saves were touched by the randomizer's copies")
    print("PASS: the launcher's save copies")


if __name__ == "__main__":
    main()
