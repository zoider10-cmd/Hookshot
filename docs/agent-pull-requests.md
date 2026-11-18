# Pull requests for agents

Read this before opening, updating, reviewing or marking a pull request ready.
[CONTRIBUTING.md](../CONTRIBUTING.md), the [pull request template](../.forgejo/pull_request_template.md) and
[Tooling's docs/forge.md](https://git.magicbean.dev/MagicBeanDev/Tooling/src/branch/main/docs/forge.md) are canonical. This guide adds only the agent's execution discipline.

## Open and update

- Push your branch to `forge-fork`; Hookshot's `main` takes reviewed pull requests only. Set up the fork as in
  [Tooling's docs/forge.md](https://git.magicbean.dev/MagicBeanDev/Tooling/src/branch/main/docs/forge.md#set-up-pushing), then follow its [change, start to finish](https://git.magicbean.dev/MagicBeanDev/Tooling/src/branch/main/docs/forge.md#a-change-start-to-finish).
- **Run a change the game runs in the game before you open its PR**, at least once where it matters, and say where
  and what you saw: `pr create --tested-in-game "RTX 3080, driver 580.95, Linux: Kakariko, no flicker after a load"`
  (it goes up as the first comment). `pr create` refuses a branch that changes the game's files without it. Use
  `--force` only when the person you work for asks you to open it untested; if you can't run the game, ask them.
- Open the PR as **work in progress**. Keep it WIP until its applicable evidence is complete and every *Everyone* box is
  ticked. `pr ready` enforces the description check; leave its `--force` option unused. A PR that needs more work goes
  back with `pr wip <n>`, and a WIP PR is not ready for review.
- **Mark it ready yourself once it is ready.** When `pr status <n>` passes and the evidence below is complete, run
  `pr ready <n>` in the same session. Forgejo showing a WIP PR as not mergeable is not, by itself, a reason to rebase.
- After each push, measurement or test run, use `pr update` to edit the description and post a short comment saying
  what changed and why. The description states the PR as it is now; the comments hold its history.

## Escalate uncertain checklist boxes

Apply the [canonical checklist rules](../CONTRIBUTING.md#commits-and-pull-requests) after every update. Ask the person
you work for at once about any box you cannot settle yourself: name the box, what you found and what you need from them
(a decision, a run on their hardware or a fact only they have). Update the box with their answer. While evidence is
outstanding, leave the box unticked with the reason beside it and keep the PR WIP; an unticked box with no question or
reason is unfinished work.

## Complete the applicable evidence

Use [Measurements](../CONTRIBUTING.md#measurements) and the template's Testing section as the completion criteria,
including their measurement, switch and tested-configuration requirements. The evidence depends on the change:

- **A change the game doesn't run** (docs, tests only, a script or the checks) is measured by its applicable game-free
  checks; an unrelated game run is not a readiness requirement.
- **A change the game runs** needs the in-game evidence those canonical sections require before it becomes ready. If you
  could not run it, say so and keep the PR WIP until the Test Farm or a person has covered what is missing. The
  [measure skill](../.claude/skills/measure/SKILL.md) has the steps for numbers against `main`.

When the PR needs hardware you do not have, ask the Test Farm on it (`@Beanstalk <what to test, in words>`; a BigBean
approves the request): [how it works](https://beanstalk.magicbean.dev/how).

## Screenshots for visible changes

- **A change that shows on screen carries screenshots in the description**, taken by you: the game, the launcher,
  a menu, a website page. Don't describe a visual change in words alone, and don't leave the pictures for a
  reviewer to take. Caption them like the Measurements columns (`Before: main @ <hash>`, `After: this PR @
  <hash>`), the same spot and settings in each. Shoot a website page from a local build (`npm run build`, then
  `npm run preview` in `website/`) in dark and light and at phone width (390 px), with made-up data where the page
  reads files. Screenshots of the game are fine ([CONTRIBUTING.md](../CONTRIBUTING.md)); game files never are.
  Drop them into the description on the PR's web page, or upload each with the forge sign-in and paste the
  `browser_download_url` it returns as `![caption](url)`:

  ```
  TOKEN=$(printf 'protocol=https\nhost=git.magicbean.dev\n\n' | python -I ../Tooling/scripts/forge.py credential get | sed -n 's/^password=//p')
  curl -s -H "Authorization: token $TOKEN" -F "attachment=@shot.png;type=image/png" \
    "https://git.magicbean.dev/api/v1/repos/MagicBeanDev/Hookshot/issues/<n>/assets?name=shot.png"
  ```
