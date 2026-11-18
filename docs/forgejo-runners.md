# Forgejo Actions runners

Hookshot's CI runs on Forgejo Actions (`.forgejo/workflows/`), on runners the team registers with git.magicbean.dev. Every
job runs on Linux: **no Windows runner is needed**, and none is registered. These are manual steps for an admin of the
instance or of MagicBeanDev; nothing here needs a game.

## Turn Actions on

Repository *Settings > Units > Actions* (or the API's `has_actions`), on MagicBeanDev/Hookshot and
MagicBeanDev/HookshotLauncher. The secrets and the variable the release workflows read are in [RELEASING.md](../RELEASING.md), *One-time setup*.

## The labels the workflows ask for

| Label | Used by | What it must be |
|---|---|---|
| `ubuntu-latest` | `ci.yml` (its title check and its Linux checks run on `ubuntu-24.04`), `third-party.yml`, the launcher's `ci.yml` | Linux, Docker: e.g. `ubuntu-latest:docker://ghcr.io/catthehacker/ubuntu:act-24.04` (Node for the actions, git, Python 3, curl, sudo and apt) |
| `ubuntu-24.04` | `ci.yml`'s tests (with the Windows Builder's compile and --cli checks), `vulkan-dlss.yml` | the same image |
| `quick` | the short jobs of 5 minutes or less: `ci.yml`'s title check and actionlint, `pr-description.yml`, `third-party.yml`'s check, `release.yml`'s *The version* and *Sign and publish*; the launcher's title check, *The version* and *Sign and publish* | the same image. A runner kept for them only (label `quick`, capacity 1) means they never wait behind a build; the other runners carry `quick` too and take them when they have room |
| `release` | the releases' builds: `build-linux.yml` and `build-windows.yml` (all of it), which `release.yml` calls (or *Run workflow*); the launcher's *The launcher, both systems* | the same image, on a runner kept for releases only (it carries no other label), so CI never takes it. The AppImage job builds inside Ubuntu 22.04 itself (`scripts/linux/deps.sh` runs in its container) and needs Docker or enough disk (about 30 GB). The Windows jobs install Wine and Xvfb with apt, and download llvm-mingw's Linux build and the .NET 8 SDK. A release waits while no `release` runner is online |

### Windows files, built on Linux

There is no `windows-*` label, and a job asking for one would queue forever (`tests/test_windows_on_linux.py` fails on
one). `build-windows.yml` makes the Windows builder's zip on Linux: the setup with llvm-mingw's Linux build of
`tools.lock`'s release (`scripts/builder_package.py llvm-mingw --host linux`, its SHA-256 checked), its icon, manifest
and version with that llvm-mingw's `windres`; the builder (command-line only) with `dotnet publish -r win-x64 -p:EnableWindowsTargeting=true`
(self-contained, as before). `scripts/check_windows_files.py` checks what it made as Windows files and starts the setup
and the builder under Wine. The Windows Vulkan back end (also with DLSS, `vulkan-dlss.yml`) is built with `RX_TARGET=windows`.
What only a Windows PC can check is in RELEASING.md, *Needs a Windows tester*.

## Register a runner

1. Download [forgejo-runner](https://code.forgejo.org/forgejo/runner/releases) for the machine.
2. In MagicBeanDev's *Settings > Actions > Runners*, *Create new runner*, and copy the token.
3. `forgejo-runner register --instance https://git.magicbean.dev --token <token> --name <name> --labels
   'ubuntu-latest:docker://ghcr.io/catthehacker/ubuntu:act-24.04,ubuntu-24.04:docker://ghcr.io/catthehacker/ubuntu:act-24.04,quick:docker://ghcr.io/catthehacker/ubuntu:act-24.04'`
4. Run it as a service (`forgejo-runner daemon`). One Linux runner is enough to start; the builder jobs are long (an hour
   and more) and want 4+ cores, 16 GB of memory and about 50 GB of disk.
5. Releases build only on runners registered with `--labels 'release:docker://ghcr.io/catthehacker/ubuntu:act-24.04'`
   and nothing else, so no pull request's checks take them and no build waits behind CI. At least one must be online for a
   release to build; *The version* and *Sign and publish* stay on `quick`.
6. Keep one runner for the quick jobs: register a second one with `--labels 'quick:docker://ghcr.io/catthehacker/ubuntu:act-24.04'`
   only and `capacity: 1` in its config (it can share the machine and its Docker), so a pull request's checks start at once
   however many builds are queued. A job that takes longer than a few minutes does not belong on `quick`.

## Actions from outside

The workflows name actions by full URL: `https://github.com/actions/...` pinned by commit, and
`https://data.forgejo.org/forgejo/upload-artifact@v4` / `download-artifact@v4` (GitHub's v4 and later refuse a server
that is not github.com). The runners must reach github.com and data.forgejo.org, or those actions must be mirrored and
the URLs changed. `actions/cache` needs the runner's cache server (on by default in forgejo-runner).

Another project's repository is not checked out with `actions/checkout`'s `repository:`: on Forgejo that names a
repository of this instance (`github.server_url`), not GitHub's. `scripts/fetch_commit.sh <URL> <commit> <folder>` fetches
it by its full URL and commit, with no token. The actions are JavaScript (Node 24): a job in a `container:` without Node
(the AppImage's `ubuntu:22.04`) installs Node.js's own build, pinned by its SHA-256, before its first action.

An artifact goes to Forgejo, and comes back, by the address Forgejo signs its links with: its `ROOT_URL`
(git.magicbean.dev, behind Cloudflare), whatever address the runner registered with; Forgejo has no setting for another.
The actions send an artifact in 8 MB blocks, under Cloudflare's 100 MB limit, but a block that fails is not sent again,
so each upload and download step is tried once more when it fails.

## Uploads larger than 100 MB

The release workflows upload the builders (hundreds of MB) to the release. git.magicbean.dev is behind Cloudflare, which
cuts a request body at 100 MB, so a runner on the server's own network should upload to the Forgejo it can reach
directly: set the organization variable `RELEASE_UPLOAD_API` to that address's API (e.g. `http://magicbean-git:3000/api/v1`; a variable can't start with `FORGEJO_`).
RELEASING.md, One-time setup, has the rest (the attachment limits in `app.ini`).
