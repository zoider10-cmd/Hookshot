"""The launcher's saves to play (launcher/Launcher.cs: SaveSlots, the Save button).

The game has one save folder a game and its load menu lists six saves and no more. A save of the launcher is that
whole folder under a name: the one played is in the game's folder, the others wait in user\\save_slots. The source is
read on every platform: the button is on the page for the game the Randomizer setting names and on Master Quest's
page, and a change is refused while the game runs. On Windows the launcher's source is compiled with the .NET
Framework's own compiler, as launcher/build.ps1 does, and SaveSlots is run on a made-up game folder:

- with nothing made yet there are ten saves, "Save 1" to "Save 10"; the first is the saves the player had and the
  others are empty slots without a name ("Slot 3:  empty"), named when first played: nothing is moved or written;
- a new save is empty, and choosing it moves the saves played out to their name, whole, and leaves the game's folder
  empty (a new game); choosing the first again brings its saves back and takes the other's out;
- each game's saves are apart (the normal game's, the randomizer's, Master Quest's);
- the randomizer's record of the checks collected goes with its save;
- a name is not used twice, the save played is not deleted, a save can be renamed, played or waiting, and one deleted
  is gone with what it held.

No game data.

    python -I -B tests/test_save_slots.py
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
function Read($folder) {
    $p = Join-Path $dir ("user\" + $folder + "\0001\slot_00\progress.sav")
    if (Test-Path $p) { Get-Content -Raw $p } else { "none" }
}
function Names($folder) { (([SaveSlots]::Names($dir, $folder)) -join ",") + "|" + [SaveSlots]::Current($dir, $folder) }
Slot "save" "normal"
Slot "save_rando" "one"
New-Item -ItemType Directory -Force (Join-Path $dir "rando") | Out-Null
Set-Content -Path (Join-Path $dir "rando\collected.txt") -Value "record one" -NoNewline
Say "first" (Names "save_rando")
Say "untouched" ((Test-Path (Join-Path $dir "user\save_slots")) -eq $false)
Say "emptyfirst" ([SaveSlots]::IsEmpty($dir, "save_rando", "Save 1"))
Say "emptythird" ([SaveSlots]::IsEmpty($dir, "save_rando", "Save 3"))
Say "shown" (([SaveSlots]::Shown("Save 3", $true)) + "|" + ([SaveSlots]::Shown("Save 3", $false)) + "|" + ([SaveSlots]::Shown("Zelda", $true)))
Say "unnamed" ("" + [SaveSlots]::Unnamed("Save 12") + [SaveSlots]::Unnamed("Save one") + [SaveSlots]::Unnamed("My Save 3"))
Say "sameagain" ([SaveSlots]::Select($dir, "save_rando", "Save 1"))
Say "new" ([SaveSlots]::Add($dir, "save_rando", "Second run"))
Say "twice" ([SaveSlots]::Add($dir, "save_rando", "second RUN"))
Say "listed" (Names "save_rando")
Say "stillone" (Read "save_rando")
Say "select" ([SaveSlots]::Select($dir, "save_rando", "Second run"))
Say "empty" (Read "save_rando")
Say "waiting" (Get-Content -Raw (Join-Path $dir "user\save_slots\save_rando\Save 1\0001\slot_00\progress.sav"))
Say "recordout" ((Test-Path (Join-Path $dir "rando\collected.txt")) -eq $false)
Say "playing" (Names "save_rando")
Slot "save_rando" "two"
Set-Content -Path (Join-Path $dir "rando\collected.txt") -Value "record two" -NoNewline
Say "deleteplayed" ([SaveSlots]::Delete($dir, "save_rando", "Second run"))
Say "back" ([SaveSlots]::Select($dir, "save_rando", "Save 1"))
Say "backnow" (Read "save_rando")
Say "recordback" (Get-Content -Raw (Join-Path $dir "rando\collected.txt"))
Say "otherwaits" (Get-Content -Raw (Join-Path $dir "user\save_slots\save_rando\Second run\0001\slot_00\progress.sav"))
Say "gone" ([SaveSlots]::Select($dir, "save_rando", "nothing"))
Say "outside" ([SaveSlots]::Select($dir, "save_rando", "..\..\save"))
Say "normal" (Read "save")
Say "normalnames" (Names "save")
Say "mqnames" (Names "save_mq")
Say "rename" ([SaveSlots]::Rename($dir, "save_rando", "Second run", "Hard seed"))
Say "renamed" (Get-Content -Raw (Join-Path $dir "user\save_slots\save_rando\Hard seed\0001\slot_00\progress.sav"))
Say "renameplayed" ([SaveSlots]::Rename($dir, "save_rando", "Save 1", "Main"))
Say "renametaken" ([SaveSlots]::Rename($dir, "save_rando", "Main", "hard seed"))
Say "names2" (Names "save_rando")
Say "again" ([SaveSlots]::Select($dir, "save_rando", "Hard seed"))
Say "againnow" (Read "save_rando")
Say "againrecord" (Get-Content -Raw (Join-Path $dir "rando\collected.txt"))
Say "back2" ([SaveSlots]::Select($dir, "save_rando", "Main"))
Say "delete" ([SaveSlots]::Delete($dir, "save_rando", "Hard seed"))
Say "names3" (Names "save_rando")
Say "deleted" ((Test-Path (Join-Path $dir "user\save_slots\save_rando\Hard seed")) -eq $false)
Say "end" (Read "save_rando")
# (a copy of a save: of the one played, and of one waiting; the two go their own ways)
Set-Content -Path (Join-Path $dir "rando\collected.txt") -Value "record main" -NoNewline
Say "copyempty" ([SaveSlots]::Copy($dir, "save_rando", "Save 3", "Of nothing"))
Say "copytaken" ([SaveSlots]::Copy($dir, "save_rando", "Main", "save 2"))
Say "copy" ([SaveSlots]::Copy($dir, "save_rando", "Main", "Main copy"))
Say "copied" (Get-Content -Raw (Join-Path $dir "user\save_slots\save_rando\Main copy\0001\slot_00\progress.sav"))
Say "copyrecord" (Get-Content -Raw (Join-Path $dir "user\save_slots\save_rando\Main copy.collected.txt"))
Say "copynames" (Names "save_rando")
Say "copyplayed" (Read "save_rando")
Say "copywaiting" ([SaveSlots]::Copy($dir, "save_rando", "Main copy", "Third"))
Say "copiedwaiting" (Get-Content -Raw (Join-Path $dir "user\save_slots\save_rando\Third\0001\slot_00\progress.sav"))
# (the name's box left empty: one more slot without a name, and "<the save> copy", then "<the save> copy 2")
Say "newname" ([SaveSlots]::NewName($dir, "save_rando"))
Say "blanknew" ([SaveSlots]::Add($dir, "save_rando", " .. "))
Say "blankcopy" ([SaveSlots]::Copy($dir, "save_rando", "Main", " . "))
Say "blankcopied" (Get-Content -Raw (Join-Path $dir "user\save_slots\save_rando\Main copy 2\0001\slot_00\progress.sav"))
Say "blanknames" (Names "save_rando")
Say "copyleft" ((Test-Path (Join-Path $dir "user\save_slots\save_rando\Third.part")) -or (Test-Path (Join-Path $dir "user\save_slots\save_rando\Main copy.part")))
'''


def main():
    src = (ROOT / "launcher" / "Launcher.cs").read_text(encoding="utf-8")
    check("Saves = SaveFolder," in src and 'Saves = () => "save_mq",' in src and "new SaveSlotsForm(dir, saveFolder)" in src,
          "the launcher has no Save button for the game the Randomizer setting names, or none on Master Quest's page")
    check('public const string First = "Save 1";' in src and 'return Path.Combine(dir, "user", Folder, saveFolder);' in src and
          'public const string Folder = "save_slots";' in src, "the saves that wait are not kept under the game folder's user folder, apart for each game")
    check('if (list.SelectedIndex < 0 || (string)list.SelectedItem == current || Running()) return;' in src and
          'if (Same(current, names[at])) return "That is the save being played. Choose another first.";' in src,
          "another save is chosen while the game runs, or the save played can be deleted")
    # (seen in play: the Save button lay where the Recommended tab's Apply button is, and a press on it applied the settings)
    check("new SlotBtn { R = new RectangleF(cx + 426, 612, 116, 42), HideOn = 8," in src and
          'Text = "Apply these", Style = Btn.Kind.Primary, R = new RectangleF(cx + 548, 612, cw - 548, 42), Page = 0,' in src,
          "the Save button and the Recommended tab's Apply button are in one place again")
    # (Continue plays the game and the save played last; the button under it opens the window to choose them, then plays)
    check('playButton = new Btn { Text = "CONTINUE", Style = Btn.Kind.Play,' in src and "void OnPlay() { OnPlay(mqMode); }" in src and
          'new ChoiceBtn { Text = "CHOOSE GAME AND SAVE",' in src and "Click = OnChoose," in src,
          "the left panel has no Continue button for the game played last, or no button to choose the game and the save")
    check("SetPlayMode(f.Mode);" in src and "string error = SaveSlots.Select(dir, SaveFolder(), f.Save);" in src and
          src.index("SetPlayMode(f.Mode);") < src.index("string error = SaveSlots.Select(dir, SaveFolder(), f.Save);") and
          'if (mode != 2 && settings.ContainsKey("rando_on")) settings["rando_on"].Set(mode == 1 ? 1 : 0, true);' in src and
          "ModeStrip" not in src,
          "the game and the save chosen are not made the ones Continue plays before the game starts, or the randomizer's choice is not the Randomizer setting")
    check("AskAtPlay" not in src and "PlaySaveForm" not in src, "the question at Play, tried and left, is still there")
    csc = Path(os.environ.get("WINDIR", "")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    if os.name != "nt" or not csc.is_file():
        print("PASS: the launcher's saves to play (the source only: no .NET Framework compiler here)")
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
        check(ran.returncode == 0, "the saves to play could not be run:\n" + ran.stdout + ran.stderr)
        got = dict(line.split("=", 1) for line in ran.stdout.splitlines() if "=" in line)
    check(got["first"] == "Save 1,Save 2,Save 3,Save 4,Save 5,Save 6,Save 7,Save 8,Save 9,Save 10|Save 1" and got["untouched"] == "True" and got["sameagain"] == "",
          "with nothing made yet there are not ten saves with the first the saves the player had, or something is moved: %r" % got)
    check(got["emptyfirst"] == "False" and got["emptythird"] == "True" and got["shown"] == "Slot 3:  empty|Save 3|Zelda   (empty)" and
          got["unnamed"] == "TrueFalseFalse", "an empty slot is not told from one with saves, or is not shown as a slot without a name: %r" % got)
    check("if (!SaveNameForm.Ask(this, dir, saveFolder, ref n)) return;" in src and
          "if (!SaveNameForm.Ask(this, dir, SaveCopies.Folders[Mode], ref Save)) return;" in src and
          "if (!SaveSlots.Unnamed(name) || !SaveSlots.IsEmpty(dir, saveFolder, name)) return true;" in src and
          "public const int Defaults = 10;" in src,
          "an empty slot is played without being named first, or there are not ten to begin with")
    check(got["new"] == "" and got["twice"] != "" and got["listed"] == "Save 1,Save 2,Save 3,Save 4,Save 5,Save 6,Save 7,Save 8,Save 9,Save 10,Second run|Save 1" and got["stillone"] == "one",
          "a new save is not listed after the first, a name is used twice, or making one changes the saves played: %r" % got)
    check(got["select"] == "" and got["empty"] == "none" and got["waiting"] == "one" and got["playing"] == "Save 1,Save 2,Save 3,Save 4,Save 5,Save 6,Save 7,Save 8,Save 9,Save 10,Second run|Second run",
          "choosing a new save does not move the saves played out, whole, and leave a new game: %r" % got)
    check(got["recordout"] == "True" and got["recordback"] == "record one" and got["againrecord"] == "record two",
          "the randomizer's record of the checks collected does not go with its save: %r" % got)
    check(got["deleteplayed"] != "", "the save being played was deleted")
    check(got["back"] == "" and got["backnow"] == "one" and got["otherwaits"] == "two",
          "choosing the first save again does not bring its saves back and take the other's out: %r" % got)
    check(got["gone"] != "" and got["outside"] != "", "a save that is not there, or a path out of the saves, was chosen")
    check(got["normal"] == "normal" and got["normalnames"] == "Save 1,Save 2,Save 3,Save 4,Save 5,Save 6,Save 7,Save 8,Save 9,Save 10|Save 1" and got["mqnames"] == "Save 1,Save 2,Save 3,Save 4,Save 5,Save 6,Save 7,Save 8,Save 9,Save 10|Save 1",
          "the normal game's saves, or Master Quest's, are not apart from the randomizer's: %r" % got)
    check(got["rename"] == "" and got["renamed"] == "two" and got["renameplayed"] == "" and got["renametaken"] != "" and
          got["names2"] == "Main,Save 2,Save 3,Save 4,Save 5,Save 6,Save 7,Save 8,Save 9,Save 10,Hard seed|Main", "a save is not renamed, played or waiting, or takes another's name: %r" % got)
    check(got["again"] == "" and got["againnow"] == "two" and got["back2"] == "", "a renamed save is not played with its own saves: %r" % got)
    check(got["delete"] == "" and got["names3"] == "Main,Save 2,Save 3,Save 4,Save 5,Save 6,Save 7,Save 8,Save 9,Save 10|Main" and got["deleted"] == "True" and got["end"] == "one",
          "a deleted save is not gone with what it held, or the save played was touched: %r" % got)
    check(got["copyempty"] != "" and got["copytaken"] != "", "a copy of an empty save, or under a name there is already, was made: %r" % got)
    check(got["newname"] == "Save 11" and got["blanknew"] == "" and got["blankcopy"] == "" and got["blankcopied"] == "one" and
          "Main,Main copy 2,Main copy," in got["blanknames"] and got["blanknames"].endswith(",Save 11|Main"),
          "with no name given a new save is not one more slot, or a copy is not named after its save: %r" % got)
    check(got["copy"] == "" and got["copied"] == "one" and got["copyrecord"] == "record main" and got["copyplayed"] == "one" and
          got["copynames"].startswith("Main,Main copy,Save 2,") and got["copynames"].endswith("|Main"),
          "a copy of the save played is not that save, whole, with its record, listed after it, or the save played is touched: %r" % got)
    check(got["copywaiting"] == "" and got["copiedwaiting"] == "one" and got["copyleft"] == "False",
          "a copy of a save that waits is not made, or a half-made folder is left: %r" % got)
    check("copy.Click += (o, e) => OnCopy();" in src and "SaveSlots.Copy(dir, SaveCopies.Folders[Mode], (string)list.SelectedItem, to);" in src and
          "SaveSlots.Copy(dir, saveFolder, from, to);" in src, "the windows have no button to copy a save")
    # (seen in play: Start with no name typed did nothing. The slot keeps its name then; and the window to choose has Rename)
    check("if (f.Value.Length == 0) return true;" in src and "rename.Click += (o, e) => OnRename();" in src and
          "string error = SaveSlots.Rename(dir, SaveCopies.Folders[Mode], from, to);" in src,
          "an empty slot is not played under the name it has when none is typed, or the window to choose cannot rename a save")
    print("PASS: the launcher's saves to play")


if __name__ == "__main__":
    main()
