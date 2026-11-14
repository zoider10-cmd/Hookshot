# Releasing

How a maintainer releases **Hookshot** (MagicBeanDev/Hookshot) and the **Hookshot Launcher**
(MagicBeanDev/HookshotLauncher). This file is the same in both repositories. The design (what a release is, the
channels, signing, `tools.lock`, how the launcher reads it) is in [docs/releases.md](docs/releases.md).

| | Hookshot | The launcher |
|---|---|---|
| Repository | [MagicBeanDev/Hookshot](https://git.magicbean.dev/MagicBeanDev/Hookshot) | [MagicBeanDev/HookshotLauncher](https://git.magicbean.dev/MagicBeanDev/HookshotLauncher) |
| First version | `v3.0.0` (rc first: `v3.0.0-rc.1`) | `v1.0.0` (rc first: `v1.0.0-rc.1`) |
| What a release ships | the Windows and Linux builders, `tools.lock` | the launcher: `HookshotLauncher-<v>-windows-x64-setup.exe` (installs itself or runs portable: docs/releases.md, *Installing the launcher*), `HookshotLauncher-<v>-windows-x64-portable.zip`, `HookshotLauncher-<v>-x86_64.AppImage` |
| Nightly count | commits since the fork, e2a4d45 | commits since the first commit |

Both have the same three channels: **stable**, **rc** and **nightly**. In the launcher, players pick a channel for their
builds and, apart from it, a channel for the launcher itself (*Settings > Launcher updates*).

Contents:

- [The commands](#the-commands)
- [A nightly](#a-nightly)
- [A release candidate](#a-release-candidate)
- [A stable from a tested release candidate](#a-stable-from-a-tested-release-candidate)
- [A hotfix](#a-hotfix)
- [Pulling a bad release](#pulling-a-bad-release)
- [When CI refuses a tag](#when-ci-refuses-a-tag)
- [Needs a Windows tester (Hookshot)](#needs-a-windows-tester-hookshot)
- [Bump a tool (Hookshot)](#bump-a-tool-hookshot)
- [Rotate the key](#rotate-the-key)
- [One-time setup](#one-time-setup)
- [Troubleshooting](#troubleshooting)

## The commands

Everything is `scripts/release.py` (the same file in both repositories), and for Hookshot's tools `scripts/tools.py`.
`release.py next` and `notes` need git-cliff:

```sh
export GIT_CLIFF=$(python -I scripts/release.py git-cliff ~/.cache/hookshot-cliff)   # the pinned git-cliff, checked
python -I scripts/release.py next          # the number the commits call for, the next rc's tag, and its notes
python -I scripts/release.py channels      # what stable, rc and nightly offer now, as the launcher reads them
```

The remote is called `forge` here (Hookshot's `scripts/forge.py login` sets it up; in the launcher's checkout, add
`https://git.magicbean.dev/MagicBeanDev/HookshotLauncher.git` under that name). Only maintainers can push tags.

## A nightly

Nothing to do: every push to `main` (every merged pull request) runs `release.yml`. It builds, signs, and publishes
`nightly-<count>-<commit>` as a pre-release, then deletes the nightlies past the newest 5.

**If one fails:**

1. Open the run (repository > *Actions* > *Release*) and read the failed step.
2. If the problem is in the code, fix it in a pull request; its merge makes the next nightly. If it was the runner or the
   network, use *Re-run* on the run.
3. A failed run may leave a **draft** release named after the nightly. Players never see drafts. The next successful run
   of the same commit reuses it; otherwise delete it from *Releases*.

Players on the nightly channel keep the last good nightly until then.

## A release candidate

1. **Preview.** Run `python -I scripts/release.py next` on an up-to-date `main` (`jj git fetch --remote forge` and
   `jj new main@forge`, or `git fetch forge` and `git switch --detach forge/main`). It prints:
   - the number the commits since the last stable call for (feat: minor, fix and perf: patch, `!` or `BREAKING CHANGE:`:
     major; the first release: `v3.0.0` for Hookshot, `v1.0.0` for the launcher);
   - the next tag, e.g. `v3.1.0-rc.1` (or `-rc.2` when `-rc.1` is out);
   - the notes git-cliff will write.

   Read the notes: a wrong title is a wrong line. Fix it before tagging. A title can be edited on the merged pull request
   only for the page; the commit on `main` keeps what was merged.
2. **Tag the commit on main.**

   ```sh
   # git
   git tag -a v3.1.0-rc.1 -m "Hookshot v3.1.0-rc.1" forge/main
   git push forge v3.1.0-rc.1
   # jj: jj does not push tags, so the tag is made and pushed with git (a jj clone is colocated with git)
   jj git fetch --remote forge
   git tag -a v3.1.0-rc.1 -m "Hookshot v3.1.0-rc.1" "$(jj log -r main@forge --no-graph -T commit_id)"
   git push forge v3.1.0-rc.1
   ```

   Or in the web UI: *Releases* > *New release*. Type the tag (`v3.1.0-rc.1`), choose the target `main`, and press
   **Create tag** (the tag only). Do not *Publish release* or *Save draft*: CI makes the release itself, and a release
   made by hand would have none of the files.
3. **What CI does** (`release.yml`): it checks the tag (`check-tag`: its form, on `main`, above every release, as high as the
   commits call for). It builds both systems' files, writes and signs `SHA256SUMS`, checks the signature with the key the
   launcher trusts, writes the notes with git-cliff, uploads everything to a draft, and publishes it as a pre-release.
   The page has a header above the notes: the launcher's links its own files; Hookshot's sends players to the launcher
   of the same channel ([docs/releases.md](docs/releases.md#release-notes)).
   For Hookshot, when the commit's nightly is still published (CI keeps the newest 5), `release.py released-as` finds it
   and checks its signed `SHA256SUMS`: the build checks that ship no file (the Windows Vulkan back end, AMD FSR 4) passed
   in its run and are not run again. The files are built again: each carries its version.
4. **Check it.**
   - The run is green, and the release page shows every file, `SHA256SUMS` and `SHA256SUMS.sig`.
   - `python -I scripts/release.py channels` shows the tag on `rc`.
   - Download `SHA256SUMS`, `SHA256SUMS.sig` and the files, and run
     `python -I scripts/release.py verify SHA256SUMS --files <folder>`.
   - In a launcher set to the rc channel (Settings), Retry offers it.
   - For the launcher: within a minute, `https://hookshot.magicbean.dev/download/launcher/rc` goes to it (and, for a stable,
     `/download/launcher/stable`).
5. Ask testers on the rc channel to try it, and for Hookshot one on Windows for what CI can't check
   ([Needs a Windows tester](#needs-a-windows-tester-hookshot)). Fixes go in as pull requests; each round is a new rc tag
   (`-rc.2`).

## A stable from a tested release candidate

When an rc has been tested and nothing blocks it, tag **the same commit** as stable:

```sh
git tag -a v3.1.0 -m "Hookshot v3.1.0" v3.1.0-rc.2^{}
git push forge v3.1.0
# jj: the commit of the rc tag
git tag -a v3.1.0 -m "Hookshot v3.1.0" "$(jj log -r 'v3.1.0-rc.2' --no-graph -T commit_id)"
git push forge v3.1.0
```

Web UI: *New release*, tag `v3.1.0`, target: the rc's commit, **Create tag**.

CI builds it again from that commit (its files carry the version; for Hookshot, the build checks the rc's run passed are
not run again: `release.py released-as`), signs and publishes it: it appears on **stable** and on **rc**. Its notes cover every
change since the previous stable, the release candidates included. A later commit of `main` can be tagged instead, but
then it was not what testers tried.

## A hotfix

A bad bug in the current stable `v3.1.0`:

1. Fix it on `main` in a pull request titled `fix: ...` (nothing else merged since? then this is the whole release).
2. `python -I scripts/release.py next` says `v3.1.1` (the patch), or the minor when a `feat` is on `main` since `v3.1.0`.
3. Tag `v3.1.1-rc.1`, check it quickly, then `v3.1.1` on the same commit. For an emergency, `v3.1.1` can be tagged directly.

Releases are only made from `main` (CI refuses a tag elsewhere). If `main` has changes not ready to ship, revert them in a
pull request first, or ship them: there is no release branch.

## Pulling a bad release

Players should not get a version that breaks:

1. On the release page, **Edit** and tick *This is a draft* (or **Delete** it, which keeps the tag unless you delete that
   too). Its channel at once falls back to the version before; launchers that have not updated yet stay where they are.
2. Launchers that already installed it keep it (the launcher never downgrades by itself). Say what to do in an issue and
   in the chat: build the previous version from its channel, or for the launcher, `--rollback`.
3. Fix it and release the next number. Never reuse a version number: launchers that installed it would not see the fixed
   files as an update.

## When CI refuses a tag

The *version* step of `release.yml` says why. Nothing was built. Delete the tag (`git push forge :refs/tags/<tag>` and
`git tag -d <tag>`, or *Tags* > delete in the web UI), then:

| The error says | Do |
|---|---|
| `is not vX.Y.Z or vX.Y.Z-rc.N` | A typo, or Hookshot below v3 / the launcher below v1: tag the right name |
| `is not on main` | Tag a commit of `main` (`forge/main`), not of a branch |
| `is not above every release there is` | The number is taken or lower: `release.py next` gives the next one |
| `is lower than the commits since vX call for: at least vY` | A `feat` or a breaking change came in: tag `vY` (or `vY-rc.1`) |
| `no tag ... here` | The tag was pushed without its commit: push `main` first |

To check before pushing: `python -I scripts/release.py check-tag <tag>` (it reads the release list; tag it locally first).

## Needs a Windows tester (Hookshot)

There is no Windows runner: every job runs on Linux, and Hookshot's Windows files are cross-built there (the setup and the
Vulkan back end with llvm-mingw's Linux build of `tools.lock`'s release, the builder (command-line only) with `dotnet publish -r win-x64
-p:EnableWindowsTargeting=true`). CI checks them as Windows files (PE headers, imports, resources, the .NET runtime:
`scripts/check_windows_files.py`) and starts the setup and the builder under Wine, which only shows that they load. For each
release candidate, before its stable, a tester on Windows 10 or 11:

- **Builds and plays.** With the Hookshot Launcher, build this version from your own copy and play to the title screen.
  Then unzip `HookshotBuilder-<v>-windows-x64.zip` and run `HookshotBuilder.exe --cli --prepare --game <your copy>` (as
  RecompLauncher does): the setup installs the builder and downloads the tools, then builds. Started by a double-click,
  the setup and `HookshotBuilder\HookshotBuilder.exe` each show only the message that sends players to the launcher; the
  setup shows its icon.
- **Notes what Windows says.** Nothing is signed: what SmartScreen and the antivirus do with the zip and the setup.
- **Runs the checks only Windows can** (they were `ci.yml`'s `windows-2022` jobs, which nothing could run): the suite on
  Windows' Python, `python -I -B tests/run_all.py --strict` (the 15 checks Linux skips, their `RUN_ALL_SKIP` naming why: the setup's Win32
  file and path handling, the portable homes, structured exceptions; and the `os.name == "nt"` paths of the others, among
  them `tests/test_control.py`'s named pipe), and from a Visual Studio
  2022 developer prompt the MSVC compile of the native checks, `cl /nologo /std:c++17 /W4 /WX /EHsc
  gpu\vk\tests\present_rect_test.cpp && present_rect_test.exe` and `python -I -B tests/test_invalidate_vcore.py --cxx cl`
  (Linux CI compiles both with GCC and Clang).

A failure is an issue, and blocks the stable as any other would.

## Bump a tool (Hookshot)

The builders' tools are in `tools.lock` (docs/releases.md, "tools.lock"): `windows-x64` lines for Windows, `linux-x64`
for Linux. A bump is a pull request that changes its line:

- **An upstream archive** (e.g. a new llvm-mingw):
  1. Edit the line: version, `sha256` and `size` (from the upstream release page, or download it and run `sha256sum`),
     `prefix` (the folder in the archive), and the upstream URL.
  2. `RELEASE_TOKEN=<your token> python -I scripts/tools.py mirror llvm-mingw`: it downloads the archive, checks it against the
     line, uploads the copy as a new package version (`llvm-mingw-windows-x64`, version `20261201`), and makes its URL the
     line's first (the upstream URL stays as the fallback).
  3. For llvm-mingw, the same release's Linux build too: `LINUX_LLVM_MINGW` in `scripts/builder_package.py` (version,
     folder, `sha256`, size, URL), which CI builds the Windows files with (`tests/test_windows_on_linux.py` checks that
     the two versions match).
  4. `python -I scripts/tools.py check --require`, and open the pull request (`build(windows): llvm-mingw 20261201`).
- **An archive Hookshot makes** (Python with new pins, the CPM cache with a new package, the `third_party` prebuilt files,
  the profile):
  ```sh
  python -I scripts/tools.py assemble python --requirements nx2/prompt_requirements.txt --out python.zip
  python -I scripts/tools.py assemble cpm --add <cpm folder> --out cpm.zip   # (its dav1d/<version>: scripts/windows/dav1d.sh <cpm folder>)
  python -I scripts/tools.py assemble third-party --from <an archive with tools/third_party> --out third-party.zip
  python -I scripts/tools.py assemble profile --work work --out profile.zip
  RELEASE_TOKEN=<your token> python -I scripts/tools.py add python 3.14.2-1 python.zip --dest HookshotBuilder/tools/python --prefix python
  ```
  `add` publishes the archive as a new package version (`<name>-<system>/<version>/<sha256>-<name>.zip`, under the
  organization's *Packages*) and writes the line. A version's files never change: new bytes are a new version. Check that nothing made
  from the game is in it (CONTRIBUTING.md): the profile is addresses and counts, never game code.
- **A Linux tool** (LLVM, FFmpeg or dav1d, SDL2, the Vulkan headers, the sysroot): they are all ours, made from
  `scripts/linux/deps.sh`'s pinned downloads, on the system the AppImage is for (Ubuntu 22.04: the sysroot is its C library).
  1. Change the version and its `sha256` pin in `scripts/linux/deps.sh` (a tag archive's pin is what it unpacks to: the
     script prints the new one when it stops).
  2. `scripts/linux/docker.sh tools` (or `scripts/linux/deps.sh tools` in CI's container). It builds the tools into
     `build-linux/docker-deps` and packs each as `tools/<name>.zip`, writing the `tools.py add` lines into
     `tools/add.sh`.
  3. Run the lines of the tools you changed, with your token: `RELEASE_TOKEN=<your token> python -I scripts/tools.py add
     emsdk 23.1.5 build-linux/docker-deps/tools/emsdk.zip --system linux-x64 --dest usr/lib/hookshot/emsdk --prefix emsdk`.
     An archive over 100 MB (emsdk) goes through the address without Cloudflare: `FORGEJO_UPLOAD_API=<it>` (One-time
     setup, the upload address).
  4. `scripts/linux/docker.sh` builds the AppImage with the new lines (`appimage.sh` installs them into
     `build-linux/tools`, and `check_player_build.sh` starts a build from the image with them), then the pull request
     (`build(linux): LLVM 23.1.6`).

  The AppImage itself carries Python with `requirements.txt`'s packages (`deps.sh` without `tools`); a change to
  those is an ordinary pull request.

Uploads over 100 MB (llvm-mingw, both emsdk) go to the address without Cloudflare: `FORGEJO_UPLOAD_API=<it>/api/v1` (One-time
setup, the upload address), from a machine that reaches it. The next release uses the new line; installed versions keep
theirs. Packages are never pruned, so older versions' tools stay downloadable.

## Rotate the key

When the key may have leaked, or on a schedule:

1. `python -I scripts/release.py keygen <safe folder>` makes `release.pem` and `release.pub.pem` and prints the lines.
2. **The launcher first.** Add the new `ReleaseKey.FromSpki("...")` line to `Core/ReleaseTrust.cs`, beside the old one, and
   the same base64 to Hookshot's `scripts/release_keys.json`. Release the launcher (rc, then stable) **signed with the old
   key**. Launchers update to it and then trust both keys.
3. **Then switch.** Wait until most players have that launcher (the stable for a few weeks). Replace the secret
   `RELEASE_SIGNING_KEY` with the new `release.pem`. Remove the old key from both files in a pull request, and release the
   launcher with the new key.
4. A launcher older than step 2 cannot check releases signed with the new key: it says the release is not signed by a
   key it trusts, and the player downloads the new launcher by hand.

If the old key leaked, do steps 2 and 3 at once and say so to players: a release signed by the leaked key could be
anything.

## One-time setup

None of this is done yet. In order (the org secret is shared by both repositories):

1. **The key.** On a PC you trust: `python -I scripts/release.py keygen <safe folder>`. Put the printed line in the launcher's
   `Core/ReleaseTrust.cs` and in Hookshot's `scripts/release_keys.json` (a pull request to each). Keep `release.pem` backed
   up offline. Losing it means a launcher with a new key that every player downloads by hand.
2. **The secret** (MagicBeanDev > *Settings* > *Actions* > *Secrets*): `RELEASE_SIGNING_KEY`, the text of `release.pem`.
   No token secret and no bot account: `release.yml` makes the release with the job's own token (`forgejo.token`, given
   to `release.py` as `RELEASE_TOKEN`), which Forgejo gives write access to its own repository on a push or a tag (never
   on a pull request from a fork). It needs no fallback. Don't protect `nightly-*` tags (*Settings* > *Tags*): that token
   can't delete a protected tag, so the prune would fail. `tools.py` and `release.py` run by hand (`mirror`, `add`,
   `prune`) take your own token as `RELEASE_TOKEN`.
3. **The upload address.** Uploads through Cloudflare are cut at 100 MB, and the builders are larger. Set the variable
   `RELEASE_UPLOAD_API` (organization *Actions* > *Variables*; Forgejo refuses variable names that start with `FORGEJO_`, so the workflow passes it to `release.py` as `FORGEJO_UPLOAD_API`) to the API without Cloudflare, e.g.
   `http://forgejo:3000/api/v1` as the runners reach it on the server's network. Unset, uploads go to
   `https://git.magicbean.dev/api/v1`.
4. **The attachment limits** (Forgejo's `app.ini`): `[attachment] MAX_SIZE` in MB, at least the largest file (2048 now;
   check the AppImage's size after the first build), and `[repository.release] ALLOWED_TYPES` empty, so `.AppImage`, `.exe`,
   `.lock` and `SHA256SUMS` are accepted.
5. **Actions and runners.** Enable Actions on both repositories (*Settings* > *Units*), and register the runners in
   [docs/forgejo-runners.md](https://git.magicbean.dev/MagicBeanDev/Hookshot/src/branch/main/docs/forgejo-runners.md)
   (Linux only, for both: Hookshot's Windows files are cross-built on Linux).
6. **The tools' packages and `tools.lock`.** Done (2026-11-13): `cpm` with dav1d and `third-party` assembled and added,
   llvm-mingw, python, emsdk and wgpu-native mirrored, the Linux tools added, each a generic package of the organization
   (docs/releases.md, "tools.lock"). The play profile is optional and there is none yet (`tools.py assemble profile`,
   then `add`, when there is). `python -I scripts/tools.py check --require` must pass: `release.yml` stops in its first
   job, before any build, until it does.
7. **Try it** on a fork, or with a throwaway key first: `HOOKSHOT_LAUNCHER_TRUST=<test .pub.pem>` makes a launcher accept a
   release signed with it.
8. **The first releases.** The launcher `v1.0.0-rc.1` and Hookshot `v3.0.0-rc.1`, then their stables.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `release.yml` fails at *SHA256SUMS, signed*: "no RELEASE_SIGNING_KEY" | the secret is not set or not visible to the repository | One-time setup, step 2 |
| ... "not signed by a trusted key" at `verify` | the secret's key is not the one in `ReleaseTrust.cs` / `release_keys.json` | put the matching key in the secret, or rotate (above) |
| *Publish* fails with HTTP 413 or a cut connection | an upload over Cloudflare's 100 MB limit | set `RELEASE_UPLOAD_API` (One-time setup, step 3) |
| *Publish* fails with HTTP 400/422 on an upload | the attachment size or type limits | One-time setup, step 4 |
| *Publish* fails with HTTP 401/403 | the job's token is read-only: the run is not a push to this repository (a pull request from a fork, or another repository's workflow) | release from a push or a tag here only |
| "is already published" | a run for a version that is out (a re-run of an old run) | nothing: a version's files never change |
| *The version* fails: "tools.lock is missing: …" or "not in Hookshot's store …" | `tools.lock` lacks a tool a builder needs, or names a package file that was not uploaded | Bump a tool (`tools.py add` or `mirror`) |
| A draft is left after a failed run | the run stopped before *Publish* | re-run it (the draft is reused), or delete the draft |
| The launcher: "not signed by a key this launcher trusts" | a release signed with a key the launcher does not have (a new key, or a test key) | release the launcher with the key first (Rotate the key) |
| The launcher offers nothing on a channel | no published release on it, or its newest was refused (the home says why) | `release.py channels`, then check that release's files |
| A launcher does not see a new release | it checks at start and on Retry; a draft is not seen | publish finished? Retry in the launcher |
| `next` or `notes`: "git-cliff is needed" | git-cliff is not on PATH | `export GIT_CLIFF=$(python -I scripts/release.py git-cliff <folder>)` |
| A Windows install fails at a tool | its upstream URL is gone and it has no mirror, or the archive changed | `tools.py mirror <name>` (its copy in Packages), or bump it |
| Too many nightlies | the prune step failed (HTTP 422: a protected `nightly-*` tag) | unprotect `nightly-*` (step 2), or `RELEASE_TOKEN=<your token> python -I scripts/release.py prune` by hand |
