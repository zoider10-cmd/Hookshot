# Report slow performance

If the game runs slowly, stutters or hitches, a normal bug report often isn't enough for the team to find out why. This
page shows how to have the game measure itself while it is slow. You only add a few lines to a text file: you don't need
to build anything again or install any tools.

## 1. Turn on the profiling mode

In the game folder (the folder with `image.bin` in it: `Games\Hookshot` in your user folder on Windows, `~/Games/Hookshot`
on Linux, unless you chose another one), create a text file named **`hookshot_env.txt`** that contains this line:

```
HOS_PROFILE=1
```

While it's on, the game records what each part of it is doing all the time, how long each frame takes and what each
stutter was spent on, into a new folder in the game folder's `logs` folder, named after the time you started the game
(for example `logs/profile-20261116-190312`). Each start makes a new folder. It makes the game a little slower while it
is on, and the folder grows by roughly 10 to 30 MB a minute.

On Windows, check that the file isn't really called `hookshot_env.txt.txt`: in File Explorer, turn on **View → Show →
File name extensions**.

## 2. Play where it's slow

1. Start the game. If it was already running, close it and start it again, because it only reads the file at startup.
2. Go to the place where it runs badly and stay there for **60 to 90 seconds**. Do the same thing the whole time, for
   example stand still, turn the camera or walk one route. Write down what you did.
3. While it's still slow, open the menu (<kbd>F1</kbd>), go to **Gameplay** and choose **Bug report**. This saves a
   folder in `bug-reports` in the game folder with the log, a screenshot and your PC's details, with your user name
   taken out.
4. Quit the game normally.

## 3. Send it

Send the team, on [Discord](https://discord.gg/magicbean) or with a [report](https://git.magicbean.dev/MagicBeanDev/Hookshot/issues/new):

- the **bug report folder** from step 3, and `hookshot_log.txt` from the game folder's `logs` folder;
- the **profile folder** from that run (the newest `profile-...` folder in `logs`), zipped: it shrinks a lot. Say about
  how many minutes into your play the worst slowdowns or stutters were;
- **where** you were in the game, and **what you did** there;
- your **settings**: the quality preset, render resolution, upscaler, frame generation and V-Sync (or a screenshot of
  the menu);
- your **graphics card and driver version**.

Send nothing else from the game folder: no game files, keys or saves. The profile folder holds only times, the names of the
game's threads, addresses in its code and your game settings, nothing of yours.

## 4. Turn it off again

Delete `hookshot_env.txt`, or the lines you added to it. Measuring costs a little speed, so don't leave it on while you
play normally. Delete the `profile-...` folders in `logs` once they are sent: the game doesn't delete them itself.

If you already had a `hookshot_env.txt` before step 1 (with a workaround from [common problems](common-issues.md), for
example), add the lines to it rather than replacing it, and remove only those lines afterwards.
