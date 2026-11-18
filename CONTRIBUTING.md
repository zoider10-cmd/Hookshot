# Contributing to Hookshot

Hookshot is a static recompilation of a supported console game: the game's AArch64
code is lifted to C, the Horizon OS and NVN2 are implemented natively, and the GPU work is replayed on Vulkan. No
emulator is involved, and the game is built on your PC from your own copy.

It lives on the team's Forgejo, [git.magicbean.dev/MagicBeanDev/Hookshot](https://git.magicbean.dev/MagicBeanDev/Hookshot).
This page gets you set up, then covers what to send, how to build and test it, and the rules that keep the project
out of trouble. The [development guide](docs/development.md) has the full pipeline; the [design notes](docs/design.md)
have the architecture.

## The rule with no exceptions

**No game files, keys, or anything made from them leave your PC.** The repository does not contain the game and never
will. That includes:

- the `.nup`, `romfs`, `exefs`, `.nso`, `.nca`, `.nsp`, `.xci` or `.nsz`/`.xcz` files, and any title keys;
- `work/` and everything in it: the extracted dump, `image.bin`, the lifted C, test builds, runs and screenshots;
- `hookshot.exe`, `hookshot_vk.dll` and other build output, and the game folder's `cache/` (`hookshot_programs.bin` and
  its `.idx`, `hookshot_pipelines.bin`, `hookshot_vk_pipelines.bin`);
- saves (`user/`), `hookshot_options.ini`, `hookshot_env.txt` and `language.txt`. The one exception: scrubbed saves
  under `assets/saves/` ([the rules](assets/saves/README.md)): one slot each (`progress.sav` and `caption.sav` only),
  its picture made grey and its date reset by `scripts/hookshot_saves.py scrub`, passing `check-repo-saves`, made fresh
  for the farm (never someone's own adventure), and added through a pull request two maintainers approve.
  `account.sav`, `option.sav`, `hookshot_options.ini`, `hookshot_env.txt` and the rest of `user/` stay banned.

Don't ask in an issue, a pull request or the chat where to get the game, how to decrypt it, or for someone else's
files. A screenshot, a video and `hookshot_log.txt` are fine and often necessary: the log holds no game data.
`.gitignore` covers most of this, but check `git status` (or `jj status`) before you commit. If you aren't sure whether
a file is game data, leave it out.

## Get started

Five minutes, then a first build.

1. **Clone:**

   ```
   git clone --depth 1 https://git.magicbean.dev/MagicBeanDev/Hookshot.git
   cd Hookshot
   ```

   (jj users: `jj git clone --colocate --depth 1 https://git.magicbean.dev/MagicBeanDev/Hookshot.git`.)

   `--depth 1` fetches the newest commit only, not the whole history: about half the download, and half the work for
   git.magicbean.dev. `git pull`, branches and pull requests work as usual. What needs the history: `git log` and
   `git blame` past your clone, a version name from the tags (a shallow build calls itself by its commit, `2331f46`),
   and cutting a release (`scripts/release.py`). For those, `git fetch --unshallow --tags` once.

2. **Get the team's tooling and sign in.** The sign-in, `forge.py` (forks, pull requests, issues) and the team chat live
   in [MagicBeanDev/Tooling](https://git.magicbean.dev/MagicBeanDev/Tooling), shared by every
   MagicBeanDev repository. Clone it beside this checkout, keep it current (`git -C ../Tooling pull --ff-only`), and
   run its scripts from here:

   ```
   git clone https://git.magicbean.dev/MagicBeanDev/Tooling.git ../Tooling
   python -I ../Tooling/scripts/forge.py login
   ```

   Click **Sign in with Discord** (or sign in with the email account you made on git.magicbean.dev) and approve. That
   one sign-in covers git.magicbean.dev (git signs in by itself from then on, and the remote `forge` points at
   Hookshot) and the team chat. The first time creates your account.
   [Tooling's docs/forge.md](https://git.magicbean.dev/MagicBeanDev/Tooling/src/branch/main/docs/forge.md) has the details and the other commands.

   **Using Claude Code?** Install the team's plugin once per PC, for the skills (`/magicbean:team-updates`,
   `/magicbean:release`, `/magicbean:batch-review`) in every MagicBeanDev repository:

   ```
   /plugin marketplace add https://git.magicbean.dev/MagicBeanDev/Tooling.git
   /plugin install magicbean@magicbean
   ```

3. **Check the game-free tests run** (no game needed):

   ```
   python -I -B tests/run_all.py
   ```

4. **Build the game** from your own dump: [Development setup](#development-setup) below, then [Building](#building).

Then say hello in Discord and claim something in `#dev-work` before you start on it.

## Ways to help

What to work on first, and the steps from claiming a problem to its release, are in the [workflow](docs/workflow.md):
priorities by severity and by how many players run the affected hardware, and the hardware tiers a change must not
break.

| | What |
|---|---|
| **Test on other hardware** | NVIDIA cards are the most tested; the README's [status table](README.md#project-status) says what works where, and the [tested configurations catalogue](https://hookshot.magicbean.dev/tested-configurations/) lists the runs behind it. Reports from AMD and Intel cards, other drivers, other distributions and SteamOS help even when everything works. Lend your PC to the [Test Farm](https://beanstalk.magicbean.dev/how): it tests approved pull requests on your hardware by itself. |
| **Play further** | The tested area is the start of the game. Reaching new areas, cutscenes, menus and items finds problems nobody has seen. |
| **Report what is broken** | Use the [issue forms](https://git.magicbean.dev/MagicBeanDev/Hookshot/issues/new/choose): game problem, install or build problem, save problem or idea. Include the version, your hardware, where you were and `hookshot_log.txt`. |
| **Send a fix** | Branch, fix, test, open a pull request from your fork ([how](#commits-and-pull-requests)). Small, focused changes are the easiest to review. |
| **Improve the docs** | The README, the development guide and the design notes are part of the project. |

## Before you open an issue or a PR

- Try current `main` first: it has every fix so far.
- Search the [open issues](https://git.magicbean.dev/MagicBeanDev/Hookshot/issues). If yours is there, add your
  details instead of opening another.
- English, please. One topic per issue or pull request.
- Report the version you actually ran: the first line of `hookshot_log.txt`.
- For a graphics or performance problem, test without ReShade, shader-cache tools, overlays and frame-generation
  injectors: they change what Hookshot does.

## Development setup

After you clone the repository, run **`mise run setup`** once to install the pre-commit and commit-msg hooks.

You need your own supported dump: program `0400486024DEC000`, update v131072, build `e0f3ccfa`. Other versions don't
work, and the build reads the dump where it lies without changing it. A build needs about 60 GB free. For runtime
memory, see the README's [requirements](README.md#what-you-need): the game alone can exceed 16 GiB, depending on the
build, driver and scene. Build on an SSD if you can: a hard drive works but takes much longer.

Where a step below needs files from the Builder, use the Windows builder of the newest
[Hookshot release](https://git.magicbean.dev/MagicBeanDev/Hookshot/releases).

### Tools: mise, CircleCI and AI agents

- **mise** pins every tool this repo uses. Install it ([mise docs](https://mise.jdx.dev/getting-started.html)), then in the repo run `mise install` and, once per clone, `mise run setup` (it installs the pre-commit and commit-msg hooks). `mise run lint` and `mise run test` run the same checks CI does.
- **CircleCI** runs CI for this repo; [docs/ci.md](docs/ci.md) has the flow and what runs when. Sign up at https://circleci.com/signup and ask in Discord to be added to the MagicBeanDev org, so you can see runs, read logs and rerun jobs.
- **CircleCI CLI:** `mise install` installs the pinned version, or see the [official install docs](https://circleci.com/docs/guides/toolkit/circleci-cli/). Run `circleci auth login` once.
- **CircleCI MCP server**, so an AI agent can read failures and logs and rerun jobs. Claude Code: `claude mcp add --transport http circleci-mcp-server https://mcp.circleci.com/v1/mcp`, then `/mcp` and Authenticate. Cursor: search "circleci" in the MCP marketplace.
- **CircleCI docs MCP**, so an agent can look things up in CircleCI's docs (no account needed): `claude mcp add --transport http circleci-docs https://circleci.mcp.kapa.ai`.
- **Chunk CLI** (optional) runs this repo's checks on a remote CircleCI sidecar, handy for an agent or a machine without the toolchain. Install with `brew install CircleCI-Public/circleci/chunk` (Windows: see its [README](https://github.com/CircleCI-Public/chunk-cli)), run `chunk auth login`, then `chunk sidecar create`, `chunk sidecar sync` and `chunk validate`. The commands it runs are in `.chunk/config.json`.

### Windows

1. Install Python 3 from [python.org](https://www.python.org/downloads/) (not the Microsoft Store build: `python -I`
   doesn't see packages installed there), then the pipeline's packages:

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. Get [llvm-mingw](https://github.com/mstorsjo/llvm-mingw) (the `ucrt-x86_64` build) and set `HOOKSHOT_MINGW` to its
   folder. Without it the build falls back to emsdk's clang at `C:\emsdk` with Visual Studio's C++ tools and the
   Windows SDK (`HOOKSHOT_MSVC=1` forces that route).

3. Copy what a clone doesn't carry from the Builder's `tools` folder. Run the Builder once; the folder is
   `%LOCALAPPDATA%\HookshotBuilder\versions\<version>\HookshotBuilder\tools`.

   | From `tools` | To | Variable |
   |---|---|---|
   | `cpm` | anywhere | `RX_CPM` points at it (Vulkan headers and FFmpeg; without it the standalone build stops, unless system headers or `HOOKSHOT_*_HEADERS` are set) |
   | `third_party` | `third_party\` | its `.dll`, `.exe`, `.lib` and `.sha1` files, to the same places: `a64emit`, `lld-link`, `zbic` and SDL2 |
   | `work` | `work\` | hot-function list, link order, profile and icon (without them the game builds but runs slower) |

4. Run everything with `python -I` from the repository root.

### Linux

Build the environment and the AppImage:

```sh
scripts/linux/deps.sh       # LLVM, Python packages, FFmpeg with dav1d, SDL2, Vulkan headers
scripts/linux/appimage.sh   # the AppImage, in build-linux/
```

The scripts expect Ubuntu 22.04: the AppImage carries that system's C library, so the game it builds runs on glibc
2.35 and newer. On another distribution, build in a container with the same system (Docker, or Podman with
`DOCKER=podman`):

```sh
scripts/linux/docker.sh             # deps.sh, then appimage.sh, in scripts/linux/Dockerfile's Ubuntu 22.04
scripts/linux/docker.sh shell       # a shell in that environment, with the checkout at /src
```

The container keeps its own `build-linux/docker-deps` and `build-linux/docker-vk-work` (parts built on the host link
against its newer glibc). Where SELinux is enforcing, the script runs the container with
`--security-opt label=disable` rather than relabelling your checkout. The AppImage needs glibc 2.35 or newer and a
Vulkan 1.3 driver with mesh shaders. `HOOKSHOT_JOBS` sets how many files compile at once. The README's
[Linux section](README.md#on-linux) has the runtime paths.

### NVIDIA DLSS (optional)

DLSS (`gpu/vk/vk_dlss.cpp`) is built in only with NVIDIA's DLSS SDK, which is NVIDIA's, under NVIDIA's own license,
and is never committed, bundled or uploaded: not in a PR, not in a release, not in a CI artifact. Fetch it for your own
builds (it prints NVIDIA's license notice and needs `--accept-nvidia-license` or a typed yes), then build with
`HOOKSHOT_NGX_SDK`:

```powershell
python -I scripts/ngx_sdk.py --platform windows C:\path\ngx-sdk
$env:HOOKSHOT_NGX_SDK = "C:\path\ngx-sdk"
python -I nx2/make_game.py --nup "C:\path\your-game.nup" --out "C:\Games\Hookshot-dlss"
```

On Windows, NVIDIA's static `nvsdk_ngx_s.lib` is linked into `hookshot_vk.dll` (with `gpu/vk/vk_ngx_msvc_rt.cpp` and
`host/mingw_msvc_shims.c` for the runtime it expects), and `make_game.py` copies `nvngx_dlss.dll` and
`nvngx_dlssg.dll` into the game's `ngx` folder; never put NGX's core, `_nvngx.dll`, beside the game. On Linux it is
`--platform linux` (or `scripts/linux/ngx-sdk.sh`). Never share a game folder built with the SDK. A change to the
pinned SDK release updates `scripts/ngx_sdk.py`, `tests/test_ngx_sdk.py` and the release named in the Hookshot
Launcher's license text (MagicBeanDev/HookshotLauncher, `App/ViewModels/SettingsStepViewModel.cs`).

### Hookshot Builder

The Builder has no window: players use the [Hookshot Launcher](https://hookshot.magicbean.dev/download), which builds
and starts the game. What is left is command-line only: on Windows a small .NET 8 program
(`builder/HookshotBuilder`, `dotnet build builder/HookshotBuilder.sln`) whose `--cli` runs `nx2/make_game.py` with
the release's own Python, for RecompLauncher through the setup (`builder/setup/setup.c`); on Linux the AppImage's
`AppRun --cli` (`builder/linux`). Started any other way, both say to get the launcher. For a Builder that keeps its
state on an external SSD, see [portable Builder setup](docs/windows-portable-builder.md).

## Building

| Command | What it does |
|---|---|
| `python -I nx2/make_game.py --nup "C:\path\your-game.nup" --out "C:\Games\Hookshot" --language en-US` | A complete game folder from a `.nup`, in about 15 minutes on a 12-core desktop ([build times](docs/development.md#build-times)). |
| `python -I nx2/make_game.py --romfs "C:\path\romfs" --exefs "C:\path\exefs" --out "C:\Games\Hookshot"` | The same, from extracted folders. |
| `python -I nx2/make_game.py --check --nup "C:\path\your-game.nup"` | Check the game and its version without building. |
| `python -I nx2/dump.py --dump <folder with exefs/ and romfs/> --set` | Record the dump in `work/dump.txt`. |
| `python -I nx2/lift.py --standalone --write` | Lift the game to C in `work/sa/gen`. |
| `python -I nx2/build.py --standalone --jobs 4` | Compile `work/sa/build/hookshot.exe` and `hookshot_vk.dll`. |
| `powershell -File scripts/run-vk.ps1 -Window -Seconds 120` | Run the standalone build and take screenshots in `work/runs/<name>/shots`. |
| `python -I scripts/prof.py <stacks file>` | Read a profile sampled with `HOS_PROFILE_EVERY`, `HOS_SAMPLE` and `HOS_SAMPLE_FILE`. |

Use a separate `--work` folder (or `OOT_WORK`) to keep more than one dump. The lifted C and every build stay local.
Not measuring speed? [A faster build for development](docs/development.md#a-faster-build-for-development) compiles the
hot code at `-O1`, about a quarter less compile time; never use it for fps, timings or a release.

## Testing

### Game-free checks

They need no dump. One command runs them all:

```
python -I -B tests/run_all.py
```

It runs every `tests/test_*.py` and `nx2/test_*.py` in its own process, the C++ unit tests under `gpu/vk/tests` and a
byte-compile of every tracked Python file, keeps going after a failure, and ends with a table and every failure's
output. Name part of a path to run only matching checks (`tests/run_all.py ub_`). While you work, `--changed [BASE]`
runs only the checks that read a file your branch changed since it left `main` (committed, uncommitted or untracked:
by path, by name or as a module they import; every check when the runner or a shared test file changed). Before a pull
request the whole run is still the one that counts. A check whose tool is missing (a
compiler, `spirv-val`, the SPIR-V or Vulkan headers, `zstandard`) is skipped and says so; `--strict` fails it instead.
Checks that can't run everywhere say so in their own file (`RUN_ALL_SKIP`); `--no-skip` runs them anyway.

CircleCI on Forgejo (see [docs/ci.md](docs/ci.md)) runs path-filtered game-free checks on same-repo pull requests and
`main`. Run `mise run ci:smoke` and `mise run test` locally before you push, and put results in
the pull request. Forgejo Actions workflows under `.forgejo/workflows/` remain until cutover; they still match what
CI reproduces.

### Checks that need your dump or a run

Slow and local; they need `work/dump.txt` from `nx2/dump.py --set`:

| Command | What it checks |
|---|---|
| `python -I nx2/test_insn.py` | Every instruction form the game uses, Unicorn against the lifted C. |
| `python -I nx2/test_leaf.py --calls` | Whole functions and call trees, native against Unicorn. |
| `python -I nx2/census.py --nx2` | The instruction census per module. |
| `python -I nx2/lower_test.py work/lowfail` | Shader programs that failed to lower. |
| `powershell -File scripts/run-vk.ps1 -Window` | An in-game run: screenshots, the flash detector, frame dumps and the profiler. |

Screenshots in `work/runs/<name>/shots` reach gigabytes and come from the game: look, then delete them. The switches
for scripted input, screenshots, frame dumps and profiles are in the development guide's
[reference](docs/development.md#switches-for-testing-and-debugging).

### When you add a fix or a check

- Add a game-free test where the behaviour can be tested without the dump: a small Python file under `tests/` or
  `nx2/` that reads source files and runs them, or compiles a tiny C++ fixture.
- Name it `tests/test_*.py` or `nx2/test_*.py`, and `tests/run_all.py` picks it up. What it needs from the runner it
  declares in its own file, after its docstring and imports, as plain literals (the runner's docstring has the
  details):

  ```python
  RUN_ALL_ARGS = ["--cxx", "{cxx}", "--headers", "{vulkan_headers}"]   # a compiler, headers, spirv-val ...
  RUN_ALL_MODULES = ["zstandard"]                                       # packages it imports
  RUN_ALL_SKIP = {"windows": "POSIX signals: the Linux guard"}          # can't run there, and why
  ```

  `{name}` is a tool the runner finds (`cxx`, `vulkan_headers`, `spirv_headers`, `spirv_val`, `glslang`, `dotnet`).
- A check that cuts a function or a block out of a source file by its text uses `tests/srccut.py`: `block(text,
  marker)` from the marker to the brace that closes it (braces in strings, comments and preprocessor lines not
  counted), `between(text, start, end)`. A marker that is missing or appears twice stops the check with one message
  naming the source and the marker, so a renamed function is one clear failure, not a wrong cut.
- Keep it fast, and make it pass on Linux and Windows where it can.
- For a renderer or runtime fix, say what you saw before and after, on which GPU and driver, and where in the game.

## Code and data conventions

- Match the file you're editing: there is no formatter, so follow the indentation, comments and naming around you. Don't
  reformat unrelated code in the same change.
- A function that keeps a rule written in the docs says where, in a comment just above it: `// doc: docs/<file>.md#<heading
  anchor>` (`# doc:` in Python), with the rule's number or a few words after it. `tests/test_doc_anchors.py` fails on an
  anchor whose file or heading is gone, so a renamed heading is fixed in the same change.
- Keep game-specific code in new files where possible. `nx2/`, `host/` and `gpu/` stay close to mkw-recomp so upstream
  fixes apply as a patch; each sync names its mkw-recomp base commit in the commit message.
- Don't modify `third_party/`: its parts are upstream copies with their notices in `PROVENANCE.md` (a64-kit's note lists
  the changes Hookshot and Hookshot made to it). Add a new folder and a provenance note instead. CI checks it
  (`scripts/check_third_party.py`, `.forgejo/workflows/third-party.yml`): every part's files against the `tree-sha256`
  line its note ends with, a part with no note, and a pull request that changes a part without changing its note. For a
  deliberate refresh from upstream, say so in the part's note and run `python -I scripts/check_third_party.py --update
  <part>` in the same commit.
- Treat local mkw-recomp and Eglantine checkouts as read-only references.
- New switches use `RX_` in the renderer and `HOS_` in the runtime. A change that should have one (to A/B it, to turn
  it off, to roll it back) gets one, and it ships at its **recommended** value: on by default when that is what you
  recommend and the measurements back it, off when it is only for testing or not yet measured enough; never off just
  because it is new. It costs nothing while off, and it is documented beside the switches around them. The PR's
  *Flags and settings* says its value before and after, and why.
- The GPU replay rules in [design notes, section 4](docs/design.md#4-the-lessons-from-mkw-as-rules-here) are not
  suggestions: nothing the replay reads may come from live guest memory, waits are honoured per queue, and texture and
  sampler registrations stay in submission order.
- Python runs with `-I`. Tests stay on the standard library. The pipeline's dependencies (lz4, numpy, capstone,
  unicorn, zstandard) are the exception, not a reason to add more; so are the button prompts' (fontTools, Pillow,
  astc-encoder-py, texture2ddecoder: `nx2/prompt_requirements.txt`), for `nx2/prompt_assets.py` and
  `nx2/prompt_draw.py` alone, at build time. Reviewers' agents: flag any other use of those four. Line endings are LF
  (`.gitattributes`).
- New code has to be GPL-compatible ([Licensing](#licensing)).

## Commits and pull requests

Changes to recorded menu, Launcher, font or shared renderer inputs also trigger the
[user-guide screenshot source review](docs/images/guide/README.md#developer-maintenance-plan).
Run the check and review the affected image and written steps before updating its fingerprints;
even an implementation-only header change needs a recorded decision to retain or recapture it.

Every pull request uses the [pull request template](.forgejo/pull_request_template.md): its sections are the
description, its checklist stays whole, and `forge.py pr ready` checks it before review.

Hookshot's `main` takes reviewed pull requests only. You work on a branch, push it to your fork and open the pull
request from there. Set up pushing once: `python -I ../Tooling/scripts/forge.py fork` makes your fork and the remote
`forge-fork` (`pr create` does it too if you haven't).

```
git fetch forge && git switch -c fix/arc-walls forge/main        jj: jj git fetch --remote forge; jj new main@forge
... change, build, test, commit ...
git push forge-fork fix/arc-walls                                 jj: jj bookmark create fix/arc-walls -r @;
                                                                      jj git push --remote forge-fork -b fix/arc-walls
python -I ../Tooling/scripts/forge.py pr create fix/arc-walls --title "fix(vk): walls missing on Intel Arc" --body-file pr.md
```

1. Name the branch for the change: `fix/...`, `linux/...`, `builder/...`, `docs/...`. One topic per pull request: a fix
   doesn't carry a refactor, and two unrelated fixes are two PRs.
2. Write the title as a Conventional Commit ([below](#pull-request-titles)).
3. Fill in the description from [the pull request template](.forgejo/pull_request_template.md): the web page puts it
   in the box, and `forge.py pr create` starts from it when you give no `--body-file` (the type from the title, How to
   reproduce only for a fix, the commits in the Measurements' columns). The comment under each heading says what a
   good answer looks like; in short:
   - the **status line** first: type, risk, where it was tested and where it still needs testing;
   - **Why**, in plain words a player could follow, with the issues that fit linked (search the tracker first);
   - **How to reproduce**, for a fix only: where it was seen, the steps, expected against actual;
   - **What changed**: a two- or three-sentence summary, then the details by area, naming files and functions;
   - **Measurements**: the verdict first, then the setup and a table whose columns name their commits
     ([what counts](#measurements)), or one line saying why there is nothing to measure. Its **Flags and settings**
     says "None", or gives each switch, menu row, ini key or build flag added or changed: its value before and after
     this PR, its effect, where it helps, and your recommendation;
   - **Testing**: what was tested (where and how), what wasn't (and why), and what **must be tested** before merge:
     exactly where (OS, GPU, driver, or a Test Farm tag), the steps for someone else, the result to expect, and who
     runs it: the Test Farm (Beanstalk: a `@Beanstalk <what to test>` comment on the PR) or a person by hand ("None"
     when you covered everything);
   - **Risks**: what could break, how to turn it off, and its **Compatibility** (saves, `hookshot_options.ini`, the
     shader and pipeline caches, the vk ABI, the builder's tools);
   - **Issues**: `Fixes #123` closes the issue on merge, `See #123` links it; delete the section when there is none;
   - the **checklist**: the whole *Everyone* list, every box ticked; from *When it applies*, only the boxes that
     apply to this PR, ticked (delete the rest: a box kept means it applies, so it must be done). `pr create` keeps
     the ones the diff suggests, and the check warns when the diff suggests one that isn't there.
     The author keeps it true: check each box against the PR as it is now, and again after every push (tick what
     holds, untick what no longer does, delete what stopped applying). An *Everyone* box that can't be true yet
     stays unticked with the reason beside it, and the PR stays WIP.
     Every box is the author's to settle: work it out from the diff, the tests and the runs, and ask the person you
     work for only about what you can't settle yourself.
4. **A change the game runs opens as a pull request only once it has run in the game**, at least once where it
   matters: `forge.py pr create --tested-in-game "where it ran and what you saw"` (the PR's first comment). It refuses
   a branch that touches `gpu/`, `host/`, `nx2/`, `assets/` or `third_party/` without it; `--force` opens it anyway.
   **A pull request is work in progress until it is measured and ready for review.** On Forgejo that is a title
   starting with `WIP:` (or `[WIP]`). `pr create` opens it so (`--ready` when the description is complete already);
   `pr ready <n>` marks it ready once the Measurements have real numbers and every *Everyone* box is ticked, and
   refuses until then (the same check runs on every pull request: `scripts/check_pr_description.py`). Reviewers
   don't review a WIP pull request. One that turns out to need more work goes back to WIP (`pr wip <n>`); one without
   measurements also gets the label `needs measurements`.
5. **Keep the description current.** It is the pull request's summary of record: when the change, the measurements or
   what was tested change, edit it (`pr edit <n> --body-file F`), so that it always describes the PR as it is now.
6. **Post a comment for each new thing**: new commits after a review, new measurements, a new test run, an answer to
   a review. A short comment says what changed and why, for the reviewers following the thread. The description
   holds the current state, the comments the history: `pr update <n> --body-file F --comment "..."` does both.
7. When `main` moves, rebase onto it (`git rebase forge/main`, or `jj rebase -d main@forge`) and resolve conflicts in
   your branch; measure again, or say in the comment why the numbers still hold.

A maintainer reviews and squash-merges it. `forge.py pr status <n>`, `pr list --mine` and `pr view <n> --comments`
follow up from the command line ([Tooling's docs/forge.md](https://git.magicbean.dev/MagicBeanDev/Tooling/src/branch/main/docs/forge.md)).

### Measurements

Every pull request shows its effect with numbers or proof, `main` against this PR, in the Measurements section of
the [pull request template](.forgejo/pull_request_template.md):

| Change | What counts as its measurement |
|---|---|
| `perf` | fps (average and 1% low), median and p99 frame time, and the number the change targets |
| `fix` | the bug reproduced on `main` and gone with this PR: a log line, a screenshot, or a test failing on `main` and passing here |
| `feat` | it working in the game, and no cost when off: fps or frame time with it on against off |
| `build`, tools | time or size on `main` and with this PR, or test output |
| `docs`, `test` only | test output on `main` and with this PR (a new test failing on `main` is the best proof) |

Every number says plainly what it was measured on. The section starts with a **Verdict:** line: did it help, by how
much, did it pass. The table's columns name what was run with its commit, `Before: main @ <hash>` and `After: this PR
@ <hash>` (`pr create` fills both in), never a bare Before and After, and the same names caption the screenshots. Add
a column when a variant matters: `After, RX_VK_X=0: this PR @ 992a2420`. A Δ column is optional; its sign is the change
against the before column. When the before column isn't `main` (or the after column isn't this PR), a `Baseline:` line
says what it is and why `main` against this PR wasn't the comparison. When the PR is rebased onto a newer `main`,
measure again, or say why the numbers still hold. A change with nothing to measure (docs only, a script with its own
tests) says so in one line, and that line is the whole of it.

For the two sides to compare:

- `main` at a named commit (the merge base: `pr create` fills it in);
- the same PC, save, scene, settings and build type;
- at least 2 runs each, interleaved (`main`, this PR, `main`, this PR), after a warm-up, and the median reported;
- no overlays, ReShade or shader-cache tools;
- the actual log lines pasted, not only the numbers taken from them.

The numbers come from the FPS counter's **Breakdown** or **Dev** level (Insert menu, Gameplay), the `fps` lines of
`hookshot_log.txt`, `RX_VK_DRAW_STATS`, or a test. A filled-in Measurements section, from a real run (a
full one also names the driver, CPU, RAM, the settings and where each number comes from). This one compares against
another baseline, so it says so:

```
**Verdict:** faster: +31% fps and 4.15 ms off the median frame time, the readback waits gone.

Baseline: nightly @ 55b976c0, the last nightly before #2602: #2602 had merged already, so this is main against it; main also carried about 50 other merges.
Hardware: Windows 11, RTX 3080
Scene: the player character in a demanding outdoor area, Ultra preset, uncapped
Method: fps and frame time from the FPS counter's Breakdown, 120 s each after a warm-up, two interleaved pairs (nightly, main, nightly, main), the median
How to reproduce: a save in that same outdoor area, Ultra preset, the FPS counter at Breakdown

| | Before: nightly @ 55b976c0 | After: main @ 87991bc8 (with #2602) | Δ |
|---|---|---|---|
| fps (run 1 / run 2) | 59.7 / 60.8 | 78.4 / 79.3 | +31% |
| median frame time | 16.35 ms | 12.2 ms | -4.15 ms |
| readback waits | ~5.7 ms | <0.1 ms | -5.6 ms |
```

followed by the log lines themselves. Add one self-contained file under `docs/tested/` for each new run you measured,
following [tested configurations](docs/tested-configurations.md). Leave the existing table frozen and do not commit
the assembled view; the [website catalogue](https://hookshot.magicbean.dev/tested-configurations/) combines both for readers.

### Pull request titles

A pull request is squash-merged, so its title becomes the commit on `main`, and that commit decides the next release
and its changelog line. The title is a [Conventional Commit](https://www.conventionalcommits.org/): a type, an optional
scope in parentheses, a colon, and a short description (`forge.py pr create` refuses anything else).

| Type | For | Example |
|---|---|---|
| `feat` | something new for players or modders | `feat(menu): tabbed category layout for in-game options with bumper and Q/E navigation` |
| `fix` | a bug fix | `fix: preserve the changelog when release generation fails` |
| `perf` | faster, or less memory | `perf(linux): hand guest memory to the GPU as udmabuf dma-bufs, not host pointers` |
| `refactor` | a change with no effect on behaviour | `refactor(vk): ...` |
| `docs` | documentation only | `docs: document the built game's command-line arguments` |
| `test` | tests only | `test: cover pool-less NVN buffer mappings` |
| `ci` | the workflows | `ci: actions pinned by commit, least privilege, realistic timeouts` |
| `build` | the build scripts, the AppImage, the Builder package | `build: scope the shader cache stamp to its consumer` |
| `chore` | anything else | `chore: remove patch backup files added by mistake` |
| `revert` | undoing an earlier change | `revert: ...`, with the reverted PR in the body |

The scope names the part of the project: `vk`, `linux`, `builder`, `menu`, `video`, `runtime` and so on. Commits inside
a branch can say anything: only the title reaches `main`, where it decides the next version and is a line of its notes.

A maintainer releases by pushing a tag ([RELEASING.md](RELEASING.md)), and CI refuses a number lower than the titles
since the last stable call for:

| Since the last stable, a title with | The next version is at least |
|---|---|
| a `!` after the type or scope (`feat(builder)!: ...`), or a `BREAKING CHANGE:` footer | the next major: `v4.0.0` after `v3.2.1` |
| `feat` | the next minor: `v3.3.0` |
| `fix`, `perf`, or any other type | the next patch: `v3.2.2` |

Each is first a release candidate (`v3.3.0-rc.1`). git-cliff turns the titles into the release notes: Features, Fixes,
Performance, and so on (`ci` and `chore` are left out). The details are in [docs/versioning.md](docs/versioning.md) and
[docs/releases.md](docs/releases.md).

AI assistance is recorded with `Assisted-by:` and `Co-Authored-By:` trailers where the account allows it: if you
used a tool, add the trailers that describe it (the template's box is under *When it applies*, since some maintainer
accounts add no attribution); if you wrote the change yourself, there is nothing to add.

## Licensing

Hookshot is free software under the [GNU General Public License, version 3 or later](LICENSE). By submitting a change
you license it under those terms, so only send code you can license that way: nothing from a project with an
incompatible license, and no decompiled game code or anything generated from the dump.

The checklist's license box is the author's own check of the diff against that paragraph: where each new file and
copied passage comes from, and that none of it is the game's code or made from the dump. How the game or the console
behaves (a function's name and arguments, a result code, the order of calls) is a fact and not code, and the host's
replacements for the console's functions are written from such facts; describe them in your own words and cite a
public source when there is one.

The third-party parts (Eden, suyu, Sirit, the Vulkan Memory Allocator, SDL, Opus, Dear ImGui, zstd, the Libertinus
fonts, zbic and the a64-kit tools) keep their own notices: preserve them, and don't relicense their code. NVIDIA's DLSS
SDK is not one of them: it is never in the repository ([NVIDIA DLSS](#nvidia-dlss-optional)). Nor is Intel's
`libxess.dll` (Intel's license): only XeSS's MIT API headers are (`third_party/xess`), and the player puts the DLL beside
the game (the README's Intel XeSS section).

## Where to talk

- **Discord:** https://discord.gg/magicbean. Claim work and discuss pull requests in `#dev-work`; `#prs` shows every
  open pull request, kept up to date.
- **Issues:** [the forms on git.magicbean.dev](https://git.magicbean.dev/MagicBeanDev/Hookshot/issues/new/choose).
- **Agents:** [AGENTS.md](AGENTS.md); they post progress to the team chat (Tooling's `team_chat.py`).

Thanks for testing, reporting and sending fixes. Every report from a different GPU and every area played further than
before moves the port forward.
