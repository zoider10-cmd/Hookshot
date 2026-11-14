# Working on git.magicbean.dev

Hookshot lives on the team's Forgejo, [git.magicbean.dev/MagicBeanDev/Hookshot](https://git.magicbean.dev/MagicBeanDev/Hookshot).
Its `main` takes reviewed pull requests only. You work on branches of your own fork and open pull requests from there,
as on GitHub.

One sign-in covers everything on magicbean.dev: Forgejo signs people in with Discord, and the team chat (Matrix) asks
Forgejo who you are. So you sign in once, with **Sign in with Discord**, and git, the team chat and test requests all
use it. The first time creates your account.

## Set up once

From the repository folder:

```
python -I scripts/forge.py login
```

It prints a link and opens it: click **Sign in with Discord** and approve. Then it:

- adds the remote `forge` (MagicBeanDev/Hookshot: fetch `main` from it, never push to it);
- becomes git's credential helper for git.magicbean.dev only, so `git push`, `git fetch` and `jj git push` sign in by
  themselves. The token renews itself when it runs out.

The sign-in is saved in your config folder (Linux `~/.config/hookshot/`, Windows `%APPDATA%\Hookshot\`), readable by
you only, never in the repository. `python -I scripts/forge.py whoami` shows who is signed in, and `logout` undoes it.

## Set up pushing

Reading, building and testing need only the sign-in. When you have something to send:

```
python -I scripts/forge.py fork
```

It makes your fork, `<you>/Hookshot`, if you have none, and adds the remote `forge-fork` for it: push your branches
there. (`pr create` does this too if it hasn't been done.)

## A change, start to finish

```
jj git fetch --remote forge                                      (or: git fetch forge)
jj new main@forge -m "Fix the walls on Intel Arc"                (or: git switch -c fix-arc-walls forge/main)
... edit, build, test ...
jj bookmark create fix-arc-walls -r @
jj git push --remote forge-fork -b fix-arc-walls                 (or: git push forge-fork fix-arc-walls)
python -I scripts/forge.py pr create fix-arc-walls --title "fix(vk): walls missing on Intel Arc"
... measure, fill in the description ...
python -I scripts/forge.py pr update 12 --body-file pr.md --comment "Measured on an Arc A770: the table is in."
python -I scripts/forge.py pr ready 12
```

`pr create` prints the pull request's link. Title and description follow
[CONTRIBUTING.md](../CONTRIBUTING.md#commits-and-pull-requests). It opens the PR as **work in progress** (a `WIP: `
title, Forgejo's draft mark), with the description started from
[the template](../.forgejo/pull_request_template.md) when you give no `--body-file`, and main's and the branch's
commits filled in where the Measurements name them. `--ready` opens it ready, when the description is complete already
(`--draft`, the earlier flag, is now the default and still accepted).

## Work in progress, ready, and keeping the PR current

```
python -I scripts/forge.py pr ready 12 [--force]                 take WIP: off once the description passes the check
python -I scripts/forge.py pr wip 12 [--needs-measurements]      put WIP: back: it needs more work (the label: maintainers)
python -I scripts/forge.py pr edit 12 [--title T] [--body-file F]   the title or the description; WIP stays as it is
python -I scripts/forge.py pr update 12 [--body-file F] --comment "what changed and why"
python -I scripts/forge.py pr comment 12 ("text" | --body-file F) [--attach FILE ...]   with pictures (below)
python -I scripts/forge.py pr status 12                          WIP or ready, the check, the checklist, reviews, comments
python -I scripts/forge.py pr review 12 (--approve | --comment | --request-changes) [--body-file F] [--at PATH:LINE TEXT]...
```

- `pr ready` runs the PR description check (`scripts/check_pr_description.py`, the same one the `PR description`
  workflow runs) on the description and the PR's diff, and refuses while a section is empty or still holds the
  template's `<...>`, the Measurements don't name `main @ <hash>` and `this PR @ <hash>`, Testing lacks its Tested,
  Not tested or Needs other testers part, a test request is still "request to open", a *For everyone* box is
  missing or unticked, or an *If applicable* box kept is unticked (a box the diff suggests but that isn't there is a
  hint). It prints what is missing; `--force` goes on with a warning. Flags and settings is a note, never a reason
  to refuse: what it leaves out (a switch the diff adds and the table doesn't list, say) is a warning. `pr create`
  keeps only the *If applicable* boxes the diff suggests (none: the heading and a comment). It also takes off the label `needs measurements`.
- `pr update` is the "I pushed more" step: it edits the description (with `--body-file`) and posts the comment saying
  what changed, so the description stays the PR as it is now and the comments keep the history. With `--comment` only,
  it only comments.
- `pr edit` and `pr update` warn when a PR marked ready no longer passes the check: `pr wip` it if it needs more work.
- Take your PR out of WIP yourself (`pr ready`) as soon as it is complete: a WIP PR isn't reviewed, so it waits until
  you do. Forgejo shows a WIP PR as not mergeable, whether or not it needs a rebase.

## Reviewing a pull request

```
python -I scripts/forge.py pr checkout 12                         read it: jj diff -r pr/12, jj file show -r pr/12 <path>
python -I scripts/forge.py pr review 12 --request-changes --body-file review.md \
    --at gpu/vk/vk_draw.cpp:3598 "This runs 64 lookups per draw: ..." \
    --at docs/old.md:-12 "Why remove this?"
python -I scripts/forge.py pr review 12 --comment --body-file review.md --inline comments.json
python -I scripts/forge.py pr review 12 --approve [--body "Looks right."]
```

One review: the verdict (`--approve`, `--comment` or `--request-changes`), a summary, and comments on lines of the
diff, which Forgejo shows beside those lines. `--at PATH:LINE TEXT` (repeatable) puts one on line LINE of the PR's
version of the file, `PATH:-LINE` on a line the PR removes (main's numbering). `--inline F` takes many from a JSON
file:

```json
[{"path": "gpu/vk/vk_draw.cpp", "line": 3598, "body": "..."},
 {"path": "docs/old.md", "old_line": 12, "body": "..."}]
```

A line outside the diff's hunks is refused before anything is posted, since the comment would land on no line. The
review is tied to the PR's head commit, so a later push marks its comments outdated. A work-in-progress PR can be
commented on, not approved: it isn't measured yet.

Pick the verdict by what the review asks for:

- `--request-changes` when it asks for a change that has to land before the merge: a bug, a broken rule from
  CONTRIBUTING.md, a check that fails. Forgejo then shows the PR as blocked until the reviewer approves it. Use it on a
  work-in-progress PR too, so the author sees the blocker before marking the PR ready.
- `--comment` for questions and suggestions the author may take or leave.
- `--approve` when the PR can merge as it is. Nits may ride along as inline comments; a blocking change may not.

## Other commands

```
python -I scripts/forge.py pr list [--mine] [--state open|closed|all]
python -I scripts/forge.py pr view 12 [--comments]
python -I scripts/forge.py pr comment 12 "Tested on an RX 6700 XT: fixed."   (or --body-file F)
python -I scripts/forge.py pr comment 12 --body-file result.md --attach main.png pr.png   with pictures
python -I scripts/forge.py pr checkout 12                         its head as the bookmark (jj) or branch (git) pr/12
python -I scripts/forge.py issue list [--label kind/bug]
python -I scripts/forge.py issue view 40 --comments
python -I scripts/forge.py issue create --title "..." --body-file issue.md
python -I scripts/forge.py issue comment 40 "..."
```

## Pictures in a comment

A test result or a review often needs screenshots: `pr comment --attach` puts them in the comment. In the text,
`![main @ 7afe6ae1](attach:main.png)` shows the file `main.png` there (a name with a space is written percent-encoded,
`attach:main%2021x9.png`); a file the text doesn't show goes at the end. forge.py posts the comment, puts each file up
as an attachment of it, then edits the comment so the pictures show. Put the text before `--attach`, or give it with
`--body` or `--body-file`.

Only pictures go up: PNG, JPEG, GIF or WebP, checked by name and by their first bytes, so that no game file, key or
build goes up by mistake ([the rule with no exceptions](../CONTRIBUTING.md#the-rule-with-no-exceptions): screenshots
are fine). Each is 25 MiB at most: a 4K PNG of the game fits (crop a larger one, or save it as JPEG or
WebP). Anything else, a missing file and an `attach:` with no file of its name are refused before anything is posted.
If an upload fails, it stops there, prints the comment's link and says which pictures went up: the comment shows those,
and the rest go in by hand (Edit on the comment) or in a new comment, not by posting it again.

## fj, the Forgejo command line

For more than the above (reviews, labels, releases, browsing), install [fj](https://codeberg.org/forgejo-contrib/forgejo-cli/wiki/Installation):
a release binary for Windows or Linux, `cargo install --locked forgejo-cli`, `brew install forgejo-cli`, or your
distribution's `forgejo-cli` package.

fj's browser sign-in works only on servers it knows, and git.magicbean.dev isn't one of them, so give it a token: make one on
[git.magicbean.dev/user/settings/applications](https://git.magicbean.dev/user/settings/applications) (repository and
issue access), then run `fj -H git.magicbean.dev auth add-token` and paste it. Inside the repository, fj finds the host
from the remotes. For example, `fj pr create --base ^ "Title"` opens a pull request from your fork's branch into
Hookshot.

## If something goes wrong

- `not signed in`, or git asks for a password: run `python -I scripts/forge.py login --again`.
- `no branch ... on <you>/Hookshot`: push the branch to `forge-fork` first.
- A push to `forge` is refused: that is Hookshot itself. Push to `forge-fork` and open a pull request.
