# Saves: the files, the script and the emulators

The details behind [moving your saves](saves.md): the save files, where Hookshot, Hookshot and every emulator keep them,
`scripts/hookshot_saves.py` (the command line that does what the launcher's Saves page does, and more), copying by hand,
and what was tested. Most players only need the launcher: see [moving your saves](saves.md).

Hookshot, Hookshot and the supported emulators use the same save-file layout, so a transfer copies the files without
converting them. You can preview any script transfer with `--dry-run` before it changes anything.

## The files

Every program keeps one folder per user profile, holding:

```
account.sav
option.sav            (the game's own settings: camera, text speed, ...)
slot_00/ ... slot_NN/ (one per save slot)
  progress.sav
  caption.sav
```

Only the folder they are in differs.

## Where Hookshot keeps them

| | Where |
|---|---|
| Linux and Steam Deck | `~/.local/share/hookshot/save/<user id>/` (`$XDG_DATA_HOME/hookshot` when it is set). Every build uses it, so a rebuilt game folder keeps its saves |
| Windows | `<game folder>\user\save\<user id>\`. The builder's game folder is `%USERPROFILE%\Games\Hookshot` unless you chose another; each game folder has its own saves |

`<user id>` is `5a3c9e1f0b7d24680000000000000001`, the same in every Hookshot and Hookshot build. Started with
`--user <folder>` ([command line arguments](../README.md#running-the-game-from-the-command-line)), Hookshot keeps its
saves in `<folder>/save/<user id>/` instead.

## The script

`scripts/hookshot_saves.py` needs Python 3 and nothing else. Run it from the Hookshot folder (or a clone):

```sh
python -I scripts/hookshot_saves.py list              # every save it finds, its slots and when each was saved
python -I scripts/hookshot_saves.py import hookshot   # Hookshot -> Hookshot
python -I scripts/hookshot_saves.py import lichii     # Lichii -> Hookshot
python -I scripts/hookshot_saves.py export lichii     # Hookshot -> Lichii
python -I scripts/hookshot_saves.py import --from ~/Downloads/my-save   # any folder holding a save -> Hookshot
python -I scripts/hookshot_saves.py export --to ~/Lichii/user           # Hookshot -> a portable emulator
```

`import` copies into Hookshot, `export` copies out of it. The names are `hookshot`, `lichii`, `frizti` (or `fritchii`),
`orchid`, `pokedinner`, `eden`, `eglantine` and `nx2navi`.

On Windows, a game folder other than `%USERPROFILE%\Games\Hookshot` has to be named:

```powershell
python -I scripts\hookshot_saves.py import lichii --hookshot "D:\Games\Hookshot"
```

| Option | What it does |
|---|---|
| `--dry-run` | Says what it would copy and where, and changes nothing |
| `--keep-settings` | Leaves the target's `option.sav` alone, so each program keeps its own settings |
| `--profile <id>` | The emulator's profile to use. Needed when more than one profile has saves: the script lists them and stops rather than pick one |
| `--from <folder>`, `--to <folder>` | The other side: the save folder itself, or a folder above it to search (a data folder, a portable `user` folder, a game folder). With a name, it replaces where that program is looked for; without one, any folder works |
| `--hookshot <folder>` | Hookshot's data folder (Windows: the game folder), or its `save/<user id>` folder |
| `--hookshot <folder>` | The same for Hookshot, with `import hookshot` or `export hookshot` |
| `--backup-dir <folder>` | Where the backup goes, outside the target save folder |
| `--force` | Copies even if a game seems to be running, or NX2navi has a save waiting |

Every copy:

- **refuses to start while Hookshot, Hookshot or one of the emulators runs**, since a running game can write its save
  again on exit and undo the copy;
- **backs up the side it overwrites first**, to `oot-save-backups/<import or export>-<name>-<date>-<time>/`: in
  `~/.local/share` on Linux, in `%LOCALAPPDATA%\Hookshot` on Windows. To undo a copy, put the backup's contents back;
- replaces the target's `slot_*` folders, `account.sav` and `option.sav`, so a slot that only existed on that side does
  not stay mixed in with the new save;
- copies the new save into a folder inside the target first and swaps it in only when that copy worked, so a copy that
  fails part way (a full disk) leaves the target's save as it was;
- refuses a save that holds a link (it would copy whatever the link points to).

When Hookshot (or, for `export hookshot`, Hookshot) has no save yet, the copy makes its save folder: on Linux in the data
folder, on Windows in the game folder, which has to exist. An emulator has to have been started and saved in once, so
that its own folder exists.

## From Hookshot

[Hookshot](https://github.com/NotRexed/Hookshot) is the project Hookshot was forked from. Its game writes the same files
in the same layout, with the same user id, so a Hookshot save carries on in Hookshot as it is: the files are copied byte
for byte.

```sh
python -I scripts/hookshot_saves.py import hookshot
```

It looks for Hookshot's save in:

| | Where |
|---|---|
| Linux | `~/.local/share/hookshot/save/<user id>/` (`$XDG_DATA_HOME/hookshot`) |
| Windows | `%USERPROFILE%\Games\Hookshot\user\save\<user id>\`, then the version folders Hookshot's launcher made under `%USERPROFILE%\Games\Hookshot` |

For a Hookshot game folder somewhere else, pass it: `import hookshot --hookshot "D:\Games\Hookshot"`.

Hookshot's folder is only read. Before anything is copied, the save is checked as the launcher checks it: only
`account.sav`, `option.sav` and `slot_NN` folders holding `progress.sav` and `caption.sav`, no link, no empty file and
none over 4 MB, at least one slot and a `progress.sav` in each. If it fails, the script says why and copies nothing.

`export hookshot` takes your Hookshot save back to Hookshot the same way.

## From and to the emulators

| Program | Linux | Windows |
|---|---|---|
| [Lichii](https://github.com/zortos293/Lichii) | `~/.local/share/lichii/` + Eden's save path (before build 150: `~/.local/share/eden/`) | `%APPDATA%\lichii\` + Eden's save path (before build 150: `%APPDATA%\eden\`) |
| [Frizti (Fritchii)](https://github.com/Frizti/Lichii), a Lichii fork | (Windows only) | `%APPDATA%\eden\` + Eden's save path |
| [Orchid](https://github.com/MythosOfs/Orchid) | `~/.local/share/eden/` + Eden's save path | `%APPDATA%\eden\` + Eden's save path |
| [PokeDinner](https://git.eden-emu.dev/Franseven/PokeDinner-a-Eglantine-Fork) | `~/.local/share/eden/` + Eden's save path | `%APPDATA%\eden\` + Eden's save path |
| [Eglantine](https://github.com/Djihads80/Eglantine) | `~/.local/share/eglantine/` + Eden's save path | `%APPDATA%\eglantine\` + Eden's save path |
| [NX2navi](https://github.com/tangerineturtle1/NX2navi) | `<game folder>/profile/save/<account>/` (its AppImage builds into `~/Games/Ocarina`) | `<game folder>\profile\save\<account>\` (its launcher's game folder is `%LOCALAPPDATA%\Programs\NX2navi\game` unless you chose another) |

Eden's save path, under that data folder: `nand/user/save/0000000000000000/<profile id>/0400486024DEC000/`.
`0400486024DEC000` is the game's title id, and `<profile id>` the emulator's user profile you play with.

- **Frizti, Orchid and PokeDinner share Eden's folder**: a save there is the same save in all of them. Eglantine has its
  own, and so has Lichii since its build 150 (2026-11-10); the script looks in `lichii` first and uses `eden` when there
  is no save in it.
- **Portable installs.** The emulators use a `user` folder beside the program (Linux: in the folder you start it from)
  instead of the paths above when that folder exists. Point the script at it with `--from`/`--to`.
- Newer Eden code reads a save from `nand/user/save/account/<profile>/0400486024DEC000/0/` first when that folder exists.
  The script looks there too.
- **NX2navi** writes a save to `profile/save-tx` first and moves it into place after. While something is waiting there,
  that is the save the game loads next, so the script refuses to copy until NX2navi has been started and quit (or
  `--force`). NX2navi's launcher also has its own **Import Saves**.
- `$XDG_DATA_HOME` replaces `~/.local/share` when it is set.
- Ryujinx and its forks don't run Switch 2 games. Any other program that keeps these files works through `--from`/`--to`
  with the folder that holds them.

The emulator paths come from each one's source (`src/common/fs/fs_paths.h`, `path_util.cpp`,
`src/core/file_sys/savedata_factory.cpp`), NX2navi's from its documentation (`docs/launcher.md`, `docs/installer.md`,
`docs/README-BuildKit.md`). Official Eden does not run Switch 2 games; its name is accepted because the forks above use
its folder.

## Copy by hand

1. Close both programs.
2. Copy the target save folder somewhere safe.
3. Delete the target's `slot_*` folders, so a slot that only exists on that side does not stay mixed in.
4. Copy the **contents** of the save folder you are leaving (`account.sav`, `option.sav`, the `slot_*` folders) into the
   one you are going to. Skip `option.sav` to keep the target's settings.

## Troubleshooting

| What you see | What to do |
|---|---|
| `close ... first` | Quit the game or emulator it names (from its menu, so it saves), then copy again. `--force` only if it is wrongly seen as running |
| `no Hookshot save found` (Windows) | Your game folder is not `%USERPROFILE%\Games\Hookshot`: pass it with `--hookshot <game folder>` |
| `no <program> save found` | Start the game in that program once and save, or pass its folder with `--from`/`--to` (a portable install, another drive) |
| `... saves in 2 profiles, so pick one` | Pass `--profile <id>` with the profile you play on, from the list it prints |
| `NX2navi still has a save waiting` | Start NX2navi, load and quit from the game, then copy |
| `is not a Hookshot save that can be imported` | The folder holds something besides save files: point `--hookshot` at the save folder itself or at the game folder |
| `is a link` | The save holds a symbolic link or a junction. Copy the real files into a plain folder and import from that |
| The save is wrong after a copy | Close the game, and put the backup's contents (the folder the script named) back into the save folder |
| The settings changed | `option.sav` came with the save. Copy again with `--keep-settings`, or restore `option.sav` from the backup |

Backups pile up, one per copy: delete old ones from `oot-save-backups` when you no longer need them.

## Saves in the repository

A few saves live in the repository, under [`assets/saves/`](../assets/saves/README.md), so the Test Farm, the tests and
everyone can start a run from the same spot: `python -I scripts/hookshot_ctl.py launch <game folder> --repo-save
<name>` ([control](control.md#saves)). They are the one exception to the rule in
[CONTRIBUTING.md](../CONTRIBUTING.md#the-rule-with-no-exceptions), and the rules are on that page: made fresh for the
farm, scrubbed, only `progress.sav` and `caption.sav` of one slot (never `account.sav` or `option.sav`: the game makes
them), checked, and added by a pull request two maintainers approve.

### Making one

1. Start the game with a new, empty profile (`--user` with a new folder, or an empty `XDG_DATA_HOME` on Linux), start
   a new file, play to where the save is needed, save and quit.
2. Scrub that slot into the repository:

   ```sh
   python -I scripts/hookshot_saves.py scrub <the profile's save folder> --slot 00 --out assets/saves/<name>
   ```

   `<name>` is a-z, 0-9 and `-`. It writes `slot_00/progress.sav`, `slot_00/caption.sav` and a `README.md` to fill in
   (its first line says where the save stands), and prints every change it made. Nothing is written when a step fails.

   Without Python, the website's [save scrubber](https://hookshot.magicbean.dev/saves/scrub/) does the same in the
   browser (the files are not uploaded) and gives the folder back as a zip: the same bytes, held to this script's
   output by `website/tests/save-scrub.test.ts`.
3. `python -I scripts/hookshot_saves.py check-repo-saves` must pass. Then open the pull request, saying how the save was made.

### What scrub changes

- **The picture → grey.** `caption.sav`'s JPEG (the Load screen's picture, 543x306) becomes a plain mid-grey JPEG of
  the same size, written by the script (baseline, YCbCr 4:2:0, the standard tables, every block one value), and the
  JPEG's length in the header with it.
- **The date → 2026-01-01 00:00.** The Load screen's date and time come from `caption.sav`'s header, not from the
  files' modification times. Part of that header is a list of 8-byte entries, a 32-bit little-endian key (a hash) and a
  32-bit little-endian value. Six of them are the date: year `0x9811a3f7`, month `0xdfd840d3`, day `0xbd46f485`, hour
  `0x23f3d75e`, minute `0x27853bf7`, second `0x5ee50bed` (none of them occurs in `progress.sav`). Scrub finds each by its
  key, which must be there exactly once before offset 1392 and on the same 8-byte grid as the others, sets it to
  2026-01-01 00:00:00 and prints each change (`caption.sav: the save date (month at 280): 11 -> 1`). It refuses,
  writing nothing, when a key is missing or repeated. It also sets both files' modification times to the same moment,
  so the files themselves say nothing about when they were made.
- **The rest of the header stays:** the scene's and map's names, the hearts (`0x1e55ecc5` looks like the current health
  in quarter hearts) and everything else.
- **No player name exists.** The Load screen shows each slot's picture, date and time, place, hearts and "Autosave",
  and no name, so there is none to scrub. `--name-field progress.sav:OFFSET:LENGTH[:ascii|utf16le]` stays for a field
  found later.
- **No `account.sav` or `option.sav`.** They are never shipped: a slot folder alone in an empty data folder loads
  (title, Load, gameplay), and the game then makes both itself. A first boot with no saves writes no files at all.
- `progress.sav` is copied otherwise unchanged, from a slot renamed `slot_00`.

Tested with a real save and the real game on 2026-11-14 (the AMD lab PC): the scrubbed slot shows a plain grey picture
and loads, from a data folder that held only that slot.

`caption.sav`'s layout is taken from `host/control.c` (`caption_json`) and from every `caption.sav` looked at so far (12
files from Hookshot and Hookshot): the magic `04 03 02 01`; the scene's and the map's names at 684 and 748; a 32-bit
little-endian 1392 at 540; the JPEG's length, 32-bit little-endian, at 1392; the JPEG from 1396 to the end of the file.
No other field in the header holds the JPEG's length or the file's size. Scrub refuses a file laid out any other way,
and `check-repo-saves` does too.

### check-repo-saves

`python -I scripts/hookshot_saves.py check-repo-saves [DIR]` (default: this checkout's `assets/saves`) passes only when:
the folder holds `README.md` and save folders named a-z, 0-9 and `-`, each exactly `README.md` (a first line, not the
template's) and `slot_00/` with `progress.sav` and `caption.sav`; there is no `_profile/` folder and no `account.sav`
or `option.sav` anywhere; nothing is a link; no file is empty or over its cap (`progress.sav` 512 KB, `caption.sav`
16 KB, `README.md` 16 KB); and every `caption.sav` has the layout above with a flat mid-grey picture (its JPEG read to
every block's coefficients: all of them 0) and its six date fields reading 2026-01-01 00:00:00. `tests/test_hookshot_saves.py` runs it on made-up saves.

## What was tested

- Linux (Arch-based), Hookshot v2.0.5 and Lichii built from source on the same day.
- A Hookshot save copied to Lichii loads in Lichii at the same spot (Kokiri Forest, the spawn by the flower patch).
- A Lichii save copied to Hookshot arrives identical, but has not been played through on the Hookshot side.
- The script's discovery for every program above, its copies, backups and checks are covered by
  `tests/test_hookshot_saves.py`, on temporary folders with made-up saves.
- **Not tested:** Windows, every emulator but Lichii, and a Hookshot save played on in Hookshot. That one rests on the
  code: Hookshot's save code is Hookshot's, unchanged by the rename (the same user id and folder layout, and the files
  are the game's own). The emulators' folders come from their source or, for NX2navi, its documentation.
