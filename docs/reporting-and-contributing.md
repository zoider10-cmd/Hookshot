# Reporting and contributing

## Not sure it's a bug?

[Ask on Discord](https://discord.gg/magicbean) first: the team and other players are there, and someone may know the
fix already. Check [common problems](common-issues.md) and [search the reports](https://git.magicbean.dev/MagicBeanDev/Hookshot/issues)
too.

## Report a bug

Open a [new report](https://git.magicbean.dev/MagicBeanDev/Hookshot/issues/new) and include:

- **The version:** the first line of `hookshot_log.txt`, in the game folder's `logs` folder.
- **Your PC:** the operating system, the graphics card and its driver version.
- **What happened,** and where in the game, with the steps to make it happen again if you can.
- **`hookshot_log.txt`** from the run, and a screenshot or a short video.

**Gameplay → Bug report** in the in-game menu gathers the log and your PC's details into one folder in one press, with
your user name taken out. Never attach game files, keys or saves.

If the problem is that the game runs slowly or stutters, [report slow performance](performance-report.md) shows how to
have the game measure itself first.

## Help with testing

Fixes often need checking on hardware the developer doesn't have: another graphics card, Linux, a Steam Deck. Lend your
PC to the Test Farm, Beanstalk: a small app builds approved pull requests next to `main` from your own copy of the game,
plays the same scenes on both, and posts the numbers on the pull request, while you do something else.
[How it works, and the download](https://beanstalk.magicbean.dev/how).

## Improve the documentation or the code

Read the [contribution guide](../CONTRIBUTING.md) and the [development guide](development.md), then send a pull request
on [Forgejo](https://git.magicbean.dev/MagicBeanDev/Hookshot). For this site, see the
[website instructions](../website/README.md). Questions are welcome on Discord.
