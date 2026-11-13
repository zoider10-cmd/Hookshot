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
# (one of the ten slots deleted is that slot, empty, again; a save made beyond them is gone from the list)
Say "slotof" ("" + [SaveSlots]::SlotOf($dir, "save_rando", "Save 4") + [SaveSlots]::SlotOf($dir, "save_rando", "Main") + [SaveSlots]::SlotOf($dir, "save_rando", "Main copy"))
Say "slotrename" ([SaveSlots]::Rename($dir, "save_rando", "Save 4", "Zelda"))
Say "slotkept" ([SaveSlots]::SlotOf($dir, "save_rando", "Zelda"))
Say "slotplay" ([SaveSlots]::Select($dir, "save_rando", "Zelda"))
Slot "save_rando" "zelda"
Say "slotleave" ([SaveSlots]::Select($dir, "save_rando", "Main"))
Say "slotheld" (Get-Content -Raw (Join-Path $dir "user\save_slots\save_rando\Zelda\0001\slot_00\progress.sav"))
Say "slotdelete" ([SaveSlots]::Delete($dir, "save_rando", "Zelda"))
Say "slotgone" ((Test-Path (Join-Path $dir "user\save_slots\save_rando\Zelda")) -eq $false)
Say "slotnames" (Names "save_rando")
Say "slotagain" ("" + [SaveSlots]::SlotOf($dir, "save_rando", "Save 4") + [SaveSlots]::IsEmpty($dir, "save_rando", "Save 4"))
Say "customdelete" ([SaveSlots]::Delete($dir, "save_rando", "Third"))
Say "customnames" (Names "save_rando")
# (the randomizer's seed of a save: its settings and the seed's files go out with it and come back with it; a save
#  without one takes the seed there is; a copy is played on its save's seed)
function Seed($n, $text) {
    Set-Content -Path (Join-Path $dir "hookshot_options.ini") -Value ("vsync=1`r`nrando_on=1`r`nrando_seed=" + $n + "`r`nrando_chests=3`r`noptions_version=2")
    New-Item -ItemType Directory -Force (Join-Path $dir "mods\rando-seed\romfs") | Out-Null
    Set-Content -Path (Join-Path $dir "mods\rando-seed\romfs\map.txt") -Value $text -NoNewline
}
function SeedNow() { ((Get-Content (Join-Path $dir "hookshot_options.ini")) -join ";") + "|" + (Get-Content -Raw (Join-Path $dir "mods\rando-seed\romfs\map.txt")) }
Seed 111 "first seed"
[SaveSlots]::SeedKeep($dir, "Main")
Say "tagmain" (([SaveSlots]::SeedTag($dir, "Main")).Replace([string][char]0xB7, "+"))
# (seen in play: a new seed made for the next save while this one is still the one in the game is not this one's)
Seed 222 "second seed"
Say "seeddiffers" ([SaveSlots]::SeedDiffers($dir, "Main"))
Say "seedto" ([SaveSlots]::Select($dir, "save_rando", "Save 5"))
Say "seedtaken" (SeedNow)
[SaveSlots]::SeedKeep($dir, "Save 5")
Say "tagfive" (([SaveSlots]::SeedTag($dir, "Save 5")).Replace([string][char]0xB7, "+"))
Say "tagnone" ([SaveSlots]::SeedTag($dir, "Save 6"))
Say "seedback" ([SaveSlots]::Select($dir, "save_rando", "Main"))
Say "seedsame" ([SaveSlots]::SeedDiffers($dir, "Main"))
Say "seedfirst" (SeedNow)
Say "seedcopy" ([SaveSlots]::Copy($dir, "save_rando", "Main", "Main on its seed"))
Say "seedagain" ([SaveSlots]::Select($dir, "save_rando", "Save 5"))
Say "seedsecond" (SeedNow)
Say "seedcopied" ([SaveSlots]::Select($dir, "save_rando", "Main on its seed"))
Say "seedofcopy" (SeedNow)
Say "seedhome" ([SaveSlots]::Select($dir, "save_rando", "Main"))
Say "seednormal" ((Test-Path (Join-Path $dir "user\save_slots\seeds\Save 1.txt")) -eq $false)
# (a new seed set for a save: one that waits has it kept for its Play; the one in the game has it set at once)
$new = New-Object 'System.Collections.Generic.List[string]'
$new.Add("rando_chests=1"); $new.Add("rando_seed=777"); $new.Add("rando_on=0"); $new.Add("vsync=9")
Say "seedsetwaiting" ([SaveSlots]::SeedSet($dir, "Save 7", $new))
Say "seedsetkept" ((Get-Content (Join-Path $dir "user\save_slots\seeds\Save 7.txt")) -join ";")
Say "seedsetlive" ((Get-Content (Join-Path $dir "hookshot_options.ini")) -join ";")
Say "seedsetnow" ([SaveSlots]::SeedSet($dir, "Main", $new))
Say "seedsetini" ((Get-Content (Join-Path $dir "hookshot_options.ini")) -join ";")
Say "seedsetmod" ((Test-Path (Join-Path $dir "mods\rando-seed")) -eq $false)
Say "seedof" (([SaveSlots]::SeedOf($dir, "Save 7")) -join ";")
# (a save for a new game: the first that holds nothing and has no seed of its own)
Say "free" ([SaveSlots]::Free($dir, "save_rando"))
# (a save moved in its list)
Say "moveup" ([SaveSlots]::Move($dir, "save_rando", "Save 3", -1))
Say "movednames" (Names "save_rando")
Say "movedown" ([SaveSlots]::Move($dir, "save_rando", "Save 3", 1))
Say "movetop" ([SaveSlots]::Move($dir, "save_rando", "Main", -5))
Say "movegone" ([SaveSlots]::Move($dir, "save_rando", "nothing", 1))
Say "copyleft" ((Test-Path (Join-Path $dir "user\save_slots\save_rando\Third.part")) -or (Test-Path (Join-Path $dir "user\save_slots\save_rando\Main copy.part")))
'''


def main():
    src = (ROOT / "launcher" / "Launcher.cs").read_text(encoding="utf-8")
    # (the save played is named under the left panel's second button; the row's own Save button said the same and is gone)
    check('Now = () => PlayChoiceForm.Modes[PlayMode()] + "  ·  " + SaveSlots.Current(dir, SaveFolder())' in src and
          'Saves = () => "save_mq",' in src and "new SaveSlotsForm(dir, saveFolder)" in src and "Saves = SaveFolder," not in src,
          "the launcher does not name the save played under its second button, has none on Master Quest's page, or the row's Save button is back")
    check('public const string First = "Save 1";' in src and 'return Path.Combine(dir, "user", Folder, saveFolder);' in src and
          'public const string Folder = "save_slots";' in src, "the saves that wait are not kept under the game folder's user folder, apart for each game")
    check('if (list.SelectedIndex < 0 || (string)list.SelectedItem == current || Running()) return;' in src and
          'if (Same(current, names[at])) return "That is the save being played. Choose another first.";' in src,
          "another save is chosen while the game runs, or the save played can be deleted")
    # (seen in play: the Save button lay where the Recommended tab's Apply button is, and a press on it applied the settings.
    #  Since Mako 4.0 the whole row is left out on the Recommended tab, which has Test my PC and Apply in its place)
    check('Text = "Apply these", Style = Btn.Kind.Primary, R = new RectangleF(cx + 312, 612, cw - 312, 42), Page = 0,' in src and
          'Text = "Save copies", HideOn2 = 0,' in src and
          "bool visible = (w.Page < 0 && w.HideOn != PageNow && w.HideOn2 != PageNow) || w.Page == PageNow;" in src,
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
    check(got["slotof"] == "410" and got["slotrename"] == "" and got["slotkept"] == "4" and got["slotplay"] == "" and got["slotleave"] == "" and
          got["slotheld"] == "zelda", "a slot does not keep its number under a new name, or is not played under it: %r" % got)
    check(got["slotdelete"] == "" and got["slotgone"] == "True" and ",Save 3,Save 4,Save 5," in got["slotnames"] and "Zelda" not in got["slotnames"] and
          got["slotagain"] == "4True", "one of the ten slots, deleted, is not that slot, empty and without a name, again: %r" % got)
    check(got["customdelete"] == "" and "Third" not in got["customnames"], "a save made beyond the ten, deleted, is still in the list: %r" % got)
    check("delete.Click += (o, e) => OnDelete();" in src and 'MessageBoxButtons.OKCancel, MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2) != DialogResult.OK) return;\n        string error = SaveSlots.Delete(dir, folder, n);' in src.replace("\r\n", "\n"),
          "the window to choose has no Delete button, or it does not ask first")
    first, second = "vsync=1;rando_on=1;rando_seed=111;rando_chests=3;options_version=2|first seed", "vsync=1;rando_on=1;rando_seed=222;rando_chests=3;options_version=2|second seed"
    check(got["seedto"] == "" and got["seedtaken"] == second and got["seeddiffers"] == "True" and got["seedsame"] == "False",
          "a save without a seed of its own does not take the seed there is, or a seed changed since a save's Play is not told: %r" % got["seedtaken"])
    check(got["tagmain"] != "" and got["tagfive"] != "" and got["tagmain"] != got["tagfive"] and got["tagmain"].count(" + ") == 2 and got["tagnone"] == "",
          "two seeds do not have two tags of three words, or a save without a seed has one: %r %r" % (got["tagmain"], got["tagfive"]))
    check("if (rando) SaveSlots.SeedKeep(dir, played);" in src and "SaveSlots.SeedDiffers(dir, played)" in src and
          "if (!SeedKept(dir, current)) SeedKeep(dir, current); SeedIn(dir, names[at]);" in src,
          "a save's seed is not kept at its Play, or the seed there is when another save is chosen is taken for its own")
    check(got["seedback"] == "" and got["seedfirst"] == first and got["seedagain"] == "" and got["seedsecond"] == second,
          "two of the randomizer's saves made on two seeds are not each played on its own: %r %r" % (got["seedfirst"], got["seedsecond"]))
    check(got["seedcopy"] == "" and got["seedcopied"] == "" and got["seedofcopy"] == first and got["seedhome"] == "" and got["seednormal"] == "True",
          "a copy is not played on its save's seed: %r" % got["seedofcopy"])
    check("LoadAll();   // (a randomizer's save chosen brings its own seed and settings: SaveSlots.Select)" in src,
          "the launcher does not read the settings again after a save is chosen")
    check(got["seedsetwaiting"] == "" and got["seedsetkept"] == "rando_chests=1;rando_seed=777" and "rando_seed=777" not in got["seedsetlive"] and
          got["seedof"] == "rando_chests=1;rando_seed=777",
          "a new seed for a save that waits is not kept for its Play (its settings and number, nothing else), or is set at once: %r" % got)
    check(got["seedsetnow"] == "" and "vsync=1;rando_on=1;rando_chests=1;rando_seed=777;options_version=2" == got["seedsetini"] and got["seedsetmod"] == "True",
          "a new seed for the save in the game is not set at once, the switch or another setting is touched, or the old seed's files stay: %r" % got["seedsetini"])
    check(got["free"] == "Save 2" and 'string made = SaveSlots.Free(dir, SaveCopies.Folders[Mode]);' in src and
          '"Create a new save", "Use this save")' in src and '" is empty. A name for the new game:", name, "Start")) {' in src,
          "a new seed on a save with progress does not offer a new save (the first empty one without a seed), or an empty slot's name is not offered as its own: %r" % got["free"])
    check(got["moveup"] == "" and ",Save 3,Save 2," in got["movednames"] and got["movedown"] == "" and got["movetop"] == "" and got["movegone"] != "",
          "a save is not moved in its list: %r" % got["movednames"])
    check("seed.Click += (o, e) => OnSeed();" in src and "up.Click += (o, e) => OnMove(-1);" in src and
          'lines.Add("rando_seed=" + LauncherForm.NewSeed());' in src and "LoadAll(); Invalidate();   // (a new seed made in the window" in src,
          "the window to choose has no New seed button or no way to move a save, or the launcher does not read the settings after it")
    check(got["copywaiting"] == "" and got["copiedwaiting"] == "one" and got["copyleft"] == "False",
          "a copy of a save that waits is not made, or a half-made folder is left: %r" % got)
    check("copy.Click += (o, e) => OnCopy();" in src and "SaveSlots.Copy(dir, SaveCopies.Folders[Mode], (string)list.SelectedItem, to);" in src and
          "SaveSlots.Copy(dir, saveFolder, from, to);" in src, "the windows have no button to copy a save")
    # (seen in play: Start with no name typed did nothing. The slot keeps its name then; and the window to choose has Rename)
    check("if (f.Value.Length == 0) return true;" in src and "rename.Click += (o, e) => OnRename();" in src and
          "if (!SaveRename.Ask(this, dir, SaveCopies.Folders[Mode], from, out to)) return;" in src and
          "if (!SaveRename.Ask(this, dir, saveFolder, from, out to)) return;" in src,
          "an empty slot is not played under the name it has when none is typed, or the window to choose cannot rename a save")
    print("PASS: the launcher's saves to play")


if __name__ == "__main__":
    main()
