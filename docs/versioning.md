# Versioning

Hookshot follows [Semantic Versioning 2.0.0](https://semver.org/). Its first version is **v3.0.0**. Hookshot's versions
(0.1.0 to 2.x, NotRexed/Hookshot) are Hookshot's history and are not Hookshot versions. How a version is built, signed and
published, and how the Hookshot Launcher installs it, is in [releases.md](releases.md).

## Versions and channels

| Channel | Versions | Made by |
|---|---|---|
| `stable` | `vX.Y.Z` | a tag `vX.Y.Z` pushed on a commit of `main` |
| `rc` | `vX.Y.Z-rc.N`, and the stables: it offers the newest of both | a tag `vX.Y.Z-rc.N` on `main` (a stable moves it too) |
| `nightly` | `nightly-<commits since the fork>-<8 hex of the commit>`, e.g. `nightly-412-1a2b3c4d` | every push to `main` |

The `v` belongs to the tag, not to the version. Build metadata is not used. A nightly's count starts at the fork, the commit
that renamed the project (`e2a4d45`), so it says how far Hookshot is past it. A build from a checkout is named by
`git describe --tags --long` (`v3.0.0-3-g1a2b3c4`) or `dev`: it is on no channel, and the launcher never offers it as an
update.

One version covers the game (`hookshot.exe` / `hookshot`), the Vulkan back end, the lift pipeline and its scripts, and the
builders: they are built from the same commit and released together. The **Hookshot Launcher is released apart**, from
MagicBeanDev/HookshotLauncher, with its own numbers (from v1.0.0) on the same three channels.

The order (the launcher's `Core/Versions.cs`): stables and release candidates in semver order (`v3.1.0-rc.1` <
`v3.1.0-rc.2` < `v3.1.0`), nightlies by their count. A nightly and a stable are not ordered: the launcher never offers one
as an update of the other, and a build stays on its channel unless the player picks another.

The "public" surface the rules protect is the command line of `make_game.py` and the builders, the `RX_` and `HOS_`
switches, the settings file (`hookshot_options.ini`, in the user folder `--user` names, else the game folder), the files a build writes into a game folder (`hookshot_env.txt`, `language.txt`,
`hookshot_version.txt`), saves, the release files' names, `SHA256SUMS` and `tools.lock`, `recomplauncher.json`, and the format of
`hookshot_log.txt`. The C sources and internal headers are not an API and may change in any release.

## Choosing the next version

There are no release pull requests: a maintainer pushes a tag, and CI does the rest
([RELEASING.md](../RELEASING.md)). Pull requests are squash-merged and their titles are
[Conventional Commits](https://www.conventionalcommits.org/) (`.forgejo/workflows/ci.yml`,
[CONTRIBUTING.md](../CONTRIBUTING.md#pull-request-titles)), so the commits on `main` say what changed, and CI
(`scripts/release.py check-tag`) refuses a tag lower than they call for:

| Since the last stable | The next version is at least |
|---|---|
| any `!` or `BREAKING CHANGE:` | the next major: `v4.0.0` after `v3.2.1` |
| a `feat` | the next minor: `v3.3.0` |
| only `fix`, `perf` and the rest | the next patch: `v3.2.2` |

It also refuses a tag that is not on `main` or not above every release there is. Every stable is first a release
candidate: `vX.Y.Z-rc.1`, then `-rc.2` and so on while fixes come in, then `vX.Y.Z` on the candidate that was good (the
same commit). `python -I scripts/release.py next` prints the number and the notes before tagging.

## Where the version appears

| Place | Where it comes from |
|---|---|
| the tag | the maintainer; the source of truth |
| `hookshot_log.txt` and the Insert menu | `nx2/version.py`: `HOOKSHOT_VERSION`, then `VERSION`/`version.txt`, then `git describe --tags --match "v[0-9]*"` |
| `hookshot_version.txt` in a build | the `VERSION` file written when the tools are packaged (`nx2/make_game.py`) |
| the Windows builder's `VERSION` | the release workflow's name for the version (`scripts/builder_package.py zip`) |
| the release | its tag; the release page and its files are named after it (docs/releases.md) |

`nx2/version.py` also appends a fingerprint of the source files, `(source 1a2b3c4d)`. It is not a version: it tells two
builds of the same release apart, and it is the only identifier a build from a modified checkout has.

## The changelog

Hookshot keeps no changelog file. Its changes are on each release's page, written by git-cliff (`cliff.toml`,
`scripts/release.py notes`) when it is released; nothing is committed back to `main`. Hookshot's history up to the fork
(its entries up to 2.2.0-rc.1) stays in [NotRexed/Hookshot](https://github.com/NotRexed/Hookshot)'s
[`CHANGELOG.md`](https://github.com/NotRexed/Hookshot/blob/main/CHANGELOG.md).

## Rules

- Do not move or reuse a tag. A version's files never change: a fix is the next version.
- Do not put game files, keys, builds or anything made from a dump in a release (CONTRIBUTING.md).
