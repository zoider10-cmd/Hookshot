"""The home folder and the user's name out of a log line, as the game writes its own (gpu/vk/compat/hookshot_redact.h, the
same rule and the same output): the home folder, as a whole, written ~ (%USERPROFILE% on Windows), and the user's name as a
folder of any path <user>. The rest of the line, the rest of each path too, stays. make_game.py's --log file is written so:
players attach it to build problems (the console, which the launcher reads, is left as it is)."""
import os
import sys


def _sep(c):
    return c in "/\\"


def _name_char(c):
    return c.isascii() and c.isalnum() or c in "._-" or ord(c) >= 0x80


def _matches_at(s, at, what, windows):
    if not what or at + len(what) > len(s):
        return False
    for a, b in zip(s[at:at + len(what)], what):
        if _sep(a) and _sep(b):
            if not windows and a != b:
                return False
            continue
        if windows:
            # (ASCII letters only, as the C rule)
            a = a.lower() if "A" <= a <= "Z" else a
            b = b.lower() if "A" <= b <= "Z" else b
        if a != b:
            return False
    return True


def redact_line(line, home, user, windows):
    """line with home and user taken out (either may be empty)"""
    home = home or ""
    while len(home) > 1 and _sep(home[-1]):
        home = home[:-1]
    with_home = len(home) > 1
    out, i, n = [], 0, len(line)
    while i < n:
        if (with_home and (i == 0 or (not _name_char(line[i - 1]) and not _sep(line[i - 1])))
                and _matches_at(line, i, home, windows) and (i + len(home) >= n or not _name_char(line[i + len(home)]))):
            out.append("%USERPROFILE%" if windows else "~")
            i += len(home)
            continue
        if (user and i > 0 and _sep(line[i - 1]) and _matches_at(line, i, user, windows)
                and (i + len(user) >= n or not _name_char(line[i + len(user)]))):
            out.append("<user>")
            i += len(user)
            continue
        out.append(line[i])
        i += 1
    return "".join(out)


def who(environ=None, windows=None):
    """(home, user, the home folder's own name when it differs from user, windows) for this PC"""
    environ = os.environ if environ is None else environ
    windows = sys.platform == "win32" if windows is None else windows
    if windows:
        home, user = environ.get("USERPROFILE", ""), environ.get("USERNAME", "")
    else:
        home, user = environ.get("HOME", ""), environ.get("USER", "")
        if not home or not user:
            try:
                import pwd
                pw = pwd.getpwuid(os.getuid())
                home, user = home or pw.pw_dir, user or pw.pw_name
            except (ImportError, KeyError, OSError):
                pass
    leaf = home.rstrip("/\\")
    leaf = leaf[max(leaf.rfind("/"), leaf.rfind("\\")) + 1:]
    folder = leaf if len(leaf) >= 2 and leaf != user else ""
    return home, user, folder, windows


def redact(line, here=None):
    """line without this PC's home folder and user name (here: who()'s answer, to reuse it)"""
    home, user, folder, windows = here or who()
    line = redact_line(line, home, user, windows)
    return redact_line(line, "", folder, windows) if folder else line


class RedactedLines:
    """A text file's write() that writes whole lines, each redacted; what is left without its line break goes out at close"""

    def __init__(self, f, here=None):
        self.f, self.here, self.rest = f, here or who(), ""

    def write(self, text):
        given = len(text)
        text = self.rest + text
        cut = text.rfind("\n") + 1
        if cut:
            self.f.write("".join(redact(l + "\n", self.here) for l in text[:cut - 1].split("\n")))
        self.rest = text[cut:]
        return given

    def flush(self):
        self.f.flush()

    def close(self):
        if self.rest:
            self.f.write(redact(self.rest, self.here))
            self.rest = ""
        self.f.flush()
