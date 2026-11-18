---
name: fix-with-test
description: Fix a Hookshot bug as two commits - a game-free test that fails on main for the bug's reason, then the fix - and check the test and the fix the way a reviewer will. Use when fixing a bug, a regression or a crash, when adding or changing a check under tests/, or when a pull request needs its "game-free test, failing on main and passing here".
---

# A fix and its game-free test

A fix shows the bug on `main` and gone with the change ([CONTRIBUTING.md](../../../CONTRIBUTING.md#measurements)), and
the best proof is a test that fails on `main` and passes here. How tests are written and run is
[CONTRIBUTING.md](../../../CONTRIBUTING.md#when-you-add-a-fix-or-a-check) and `tests/run_all.py`'s docstring; this is
the order of the work, and the checks a test passing does not do for you.

## 1. The cause first

Find the cause before writing the fix: a log line, a trace, a measurement, the code path read through
([docs/workflow.md](../../../docs/workflow.md), *Fix*), and search the open pull requests for the same fix before
writing one. Can't reproduce or explain it: stop and say so; don't fix a guess.

## 2. Write the test

- A `tests/test_<topic>.py` on the standard library, its docstring saying what it checks and how to run it, what it
  needs declared at the top (`RUN_ALL_ARGS = ["--cxx", "{cxx}"]` and the others in `tests/run_all.py`'s docstring).
- Most C and C++ checks cut the function out of the real source by its text and compile it with stand-ins for what it
  calls. Start from a check that already reads the same file (`git grep -l <file name> tests`) and copy its way of
  cutting. Cut from the source in the tree, never a copy pasted into the test: the test has to fail when the source
  goes back.
- Check the behaviour the bug broke (what the function returns, writes or calls), not the text of the new line: a
  regex for the fix passes a wrong fix and fails a right one written differently.
- A fix behind a switch is tested both ways: unset (fixed) and with the switch that brings back the old behaviour.
- Fast (seconds), and on Linux and Windows where it can run; `RUN_ALL_SKIP` with the reason where it can't.

## 3. Two commits

1. **The test alone.** Run it at this commit: it must fail, and for the bug's reason. Read the failure; a test that
   fails because it doesn't compile proves nothing.
2. **The fix.** The test passes.

Both carry the trailers that describe the tool used (`git commit --trailer "Assisted-by: <tool>"`). Mechanical changes
(renames, moves) go in commits of their own. When review changes the test or the fix, rewrite the branch so it still
reads test, then fix, rather than adding fix-up commits.

## 4. What the test doesn't check

- **The test against a broken fix.** Undo or change the fix's key line, run the test, see it fail, put the line back.
  A test that passes either way checks nothing.
- **The changed files whole.** The test compiled a cut, so a fix can pass it and not build (a variable declared further
  down the file, a missing include). Build what changed: the renderer alone needs no game
  (`RX_VK_ONLY=1 python -I nx2/build.py --standalone --jobs 4`, with the headers
  [docs/development.md](../../../docs/development.md#use) lists); or compile each changed `.c`/`.cpp` with
  `-fsyntax-only -Wall -Wextra` and the build's include folders, on the branch and on `main`, and compare the warnings.
  Host files can need headers only the game's lift makes. Say what was compiled, for which platform, and what wasn't.
- **Both compilers.** C++ tests compile with `-Werror`, and clang warns where g++ doesn't:
  `CXX=g++ python -I -B tests/run_all.py <name>`, then `CXX=clang++ ...`. The runner falls back to another compiler
  without a word when `CXX` names one it can't find: check `clang++ --version` first, and with no clang say the clang
  run wasn't done.
- **Skips.** A check whose compiler, headers or tool is missing is skipped, and a skip is not a pass. Read the table,
  or run with `--strict`.
- **The other checks that read the file.** Tests read the source: `git grep -l <file name> tests`, run them, and update
  one your change breaks in the same pull request rather than weakening it.
- **The whole suite once**, `python -I -B tests/run_all.py`. A failure there that also fails on `main` is named in the
  pull request; check it on `main` rather than assuming.
- **What the test doesn't model**: threads, timing, the GPU, a driver, the game's real data. Name it under Testing.
  For a fix in memory ownership, threads, timing, saves or anything every player runs, have a second agent review it
  cold before calling it validated: give it the diff and the test, not your conclusion, and ask it to break them.

## 5. In the pull request

- How to reproduce, from `main`.
- Measurements: the test's output at `Before: main @ <hash>` (failing) and `After: this PR @ <hash>` (passing), and the
  in-game evidence when the game runs the change: the log line or the screenshot, before and after.
- Tick *A game-free test added for the fix, failing on `main` and passing here* only after you ran it both ways.

## 6. Stop and ask the person you work for

- When no game-free test can show the bug: say why, and agree on the in-game evidence instead.
- When the fix needs a decision: a new default, a switch, a change to a rule in
  [docs/design.md](../../../docs/design.md).
- When the test needs something outside the standard library or a tool the runner doesn't know.
