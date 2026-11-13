"""A player's saves across the update that brings the launcher's saves to play (launcher/Launcher.cs: SaveSlots).

A game folder as a player of the release before has it: saves of the normal game (user\\save) and of Master Quest
(user\\save_mq), an options file without a line of the randomizer, and nothing of this launcher's (no user\\save_slots,
no user\\play_mode.txt). The game's side keeps reading user\\save and user\\save_mq (host/oot_rando.c hos_save_folder:
the randomizer off, the folder is the release's own), so what matters is that the launcher leaves those folders alone:

- everything the launcher asks about the saves when it opens and when its windows are shown (the list, the save
  played, which are empty, the slots' numbers, the seeds' words) writes nothing and moves nothing: the folder is
  byte for byte what it was, and no folder of the launcher's is made;
- the save played is "Save 1" and it is not empty: the player's saves are the first of the list;
- choosing another save and coming back brings every file back as it was, and Master Quest's saves are never
  touched by what is done with the normal game's;
- the source: the game's side picks the release's folders with the randomizer off, and the launcher changes the
  saves only from a button.

On Windows the launcher's source is compiled with the .NET Framework's own compiler, as launcher/build.ps1 does. No
game data.

    python -I -B tests/test_save_upgrade.py
"""
import os
import re
import subprocess
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
function Put($rel, $text) {
    $p = Join-Path $dir $rel
    New-Item -ItemType Directory -Force (Split-Path -Parent $p) | Out-Null
    Set-Content -Path $p -Value $text -NoNewline
}
# (every file under the folder with what it holds, in order: the folder's whole state)
function Tree($under) {
    $root = Join-Path $dir $under
    if (-not (Test-Path $root)) { return "none" }
    $files = Get-ChildItem -Path $root -Recurse -File | Sort-Object FullName
    ($files | ForEach-Object { $_.FullName.Substring($root.Length) + ":" + (Get-Content -Raw $_.FullName) }) -join ";"
}
Put "user\save\5a3c9e1f0b7d24680000000000000001\slot_00\progress.sav" "the player's own"
Put "user\save\5a3c9e1f0b7d24680000000000000001\slot_00\caption.sav" "caption"
Put "user\save\5a3c9e1f0b7d24680000000000000001\slot_03\progress.sav" "an autosave"
Put "user\save\5a3c9e1f0b7d24680000000000000001\option.sav" "options"
Put "user\save_mq\5a3c9e1f0b7d24680000000000000001\slot_00\progress.sav" "master quest"
Put "hookshot_options.ini" "vsync=1`r`nfullscreen=1`r`noptions_version=2"
$before = (Tree "user") + "|" + (Tree "")
Say "savebefore" (Tree "user\save")
# ---- what the launcher asks, opening and showing its windows ----
foreach ($folder in "save", "save_rando", "save_mq") {
    $names = [SaveSlots]::Names($dir, $folder)
    $current = [SaveSlots]::Current($dir, $folder)
    foreach ($n in $names) {
        [SaveSlots]::IsEmpty($dir, $folder, $n) | Out-Null
        [SaveSlots]::SlotOf($dir, $folder, $n) | Out-Null
        [SaveSlots]::SeedTag($dir, $n) | Out-Null
        [SaveSlots]::SeedKept($dir, $n) | Out-Null
        [SaveSlots]::SeedDiffers($dir, $n) | Out-Null
    }
    [SaveSlots]::NewName($dir, $folder) | Out-Null
    [SaveSlots]::CopyName($dir, $folder, $current) | Out-Null
    [SaveCopies]::List($dir, $folder) | Out-Null
    [SaveCopies]::Current($dir, $folder) | Out-Null
}
[SaveCopies]::KeepBefore($dir) | Out-Null
Say "asked" (((Tree "user") + "|" + (Tree "")) -eq $before)
Say "nolauncherfolders" ((-not (Test-Path (Join-Path $dir "user\save_slots"))) -and (-not (Test-Path (Join-Path $dir "user\save_copies"))) -and (-not (Test-Path (Join-Path $dir "user\play_mode.txt"))))
Say "played" ([SaveSlots]::Current($dir, "save"))
Say "first" (([SaveSlots]::Names($dir, "save"))[0])
Say "notempty" ([SaveSlots]::IsEmpty($dir, "save", "Save 1"))
Say "mqplayed" ([SaveSlots]::Current($dir, "save_mq"))
Say "mqnotempty" ([SaveSlots]::IsEmpty($dir, "save_mq", "Save 1"))
# ---- another save chosen, a game begun on it, and back ----
Say "away" ([SaveSlots]::Select($dir, "save", "Save 2"))
Say "kept" ((Tree "user\save_slots\save\Save 1") -eq (Tree "user\save.was"))
Say "keptwhole" (Tree "user\save_slots\save\Save 1")
Put "user\save\5a3c9e1f0b7d24680000000000000001\slot_00\progress.sav" "a second game"
Say "mqduring" (Tree "user\save_mq")
Say "back" ([SaveSlots]::Select($dir, "save", "Save 1"))
Say "saveafter" (Tree "user\save")
Say "second" (Tree "user\save_slots\save\Save 2")
Say "mqafter" (Tree "user\save_mq")
Say "optionsafter" ((Get-Content (Join-Path $dir "hookshot_options.ini")) -join ";")
'''


def main():
    launcher = (ROOT / "launcher" / "Launcher.cs").read_text(encoding="utf-8")
    side = (ROOT / "host" / "oot_rando.c").read_text(encoding="utf-8")
    # ---- the game's side: the release's folders, the randomizer off ----
    check('if (hos_master_quest()) return "save_mq";' in side and 'return on ? "save_rando" : "save";' in side and "on = r.on != 0;" in side,
          "the game does not read the normal game's saves from user\\save and Master Quest's from user\\save_mq with the randomizer off")
    # ---- the launcher changes the saves only from a button ----
    # (every call that moves, renames, deletes or writes a save is in a handler of a window's button; the one made when the
    #  launcher opens keeps a seed for a randomizer's save that has progress, which a player of the release has not)
    calls = [m.start() for m in re.finditer(r"SaveSlots\.(Select|Rename|Delete|Add|Copy|Move|SeedSet|SeedIn|SeedKeep|Free)\(", launcher)]
    opening = [at for at in calls if "static " not in launcher[launcher.rfind("\n", 0, at):at] and
               launcher.rfind("void On", 0, at) < launcher.rfind("public LauncherForm(", 0, at) and
               launcher.rfind("public LauncherForm(", 0, at) > launcher.rfind("\n    }\n", 0, at) - 100000 and
               "if (!SaveSlots.SeedKept(dir, had) && !SaveSlots.IsEmpty(dir, \"save_rando\", had))" in launcher[max(0, at - 120):at + 10]]
    check(len(opening) == 1, "the launcher changes saves as it opens, otherwise than for a randomizer's save with progress: %d" % len(opening))
    check('if (!SaveSlots.SeedKept(dir, had) && !SaveSlots.IsEmpty(dir, "save_rando", had)) SaveSlots.SeedKeep(dir, had);' in launcher,
          "the seed kept when the launcher opens is kept for a save without progress too")
    check("void OnPlay() { OnPlay(mqMode); }" in launcher and "try { mqMode = File.ReadAllText(ModeFile).Trim() == \"mq\"; } catch { }" in launcher,
          "with no game chosen yet, Continue does not play the normal game (or the randomizer's, by its switch)")
    csc = Path(os.environ.get("WINDIR", "")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    if os.name != "nt" or not csc.is_file():
        print("PASS: a player's saves across the update (the source only: no .NET Framework compiler here)")
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
        check(ran.returncode == 0, "the update could not be played through:\n" + str(ran.stdout) + str(ran.stderr))
        got = dict(line.split("=", 1) for line in ran.stdout.splitlines() if "=" in line)
    check(got["asked"] == "True" and got["nolauncherfolders"] == "True",
          "what the launcher asks about the saves changes the game folder, or makes a folder of its own: %r" % got)
    check(got["played"] == "Save 1" and got["first"] == "Save 1" and got["notempty"] == "False" and got["mqplayed"] == "Save 1" and got["mqnotempty"] == "False",
          "the player's saves are not the first save of the list, played and with progress: %r" % got)
    check(got["away"] == "" and got["keptwhole"].count(":") == 4 and "the player's own" in got["keptwhole"] and "an autosave" in got["keptwhole"] and
          "options" in got["keptwhole"], "another save chosen does not keep the player's saves whole under the first: %r" % got["keptwhole"])
    check(got["back"] == "" and got["saveafter"] == got["savebefore"], "the player's saves do not come back as they were: %r\n%r" % (got["savebefore"], got["saveafter"]))
    check("a second game" in got["second"], "the game begun on the other save is not kept under it: %r" % got["second"])
    check(got["mqduring"] == got["mqafter"] and "master quest" in got["mqafter"] and got["mqafter"].count(":") == 1,
          "Master Quest's saves are touched by what is done with the normal game's: %r" % got["mqafter"])
    check(got["optionsafter"] == "vsync=1;fullscreen=1;options_version=2", "the options file is changed by choosing a save of the normal game: %r" % got["optionsafter"])
    print("PASS: a player's saves across the update")


if __name__ == "__main__":
    main()
