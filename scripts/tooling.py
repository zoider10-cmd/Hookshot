"""Where MagicBeanDev/Tooling is: the team's shared scripts (forge.py, team_chat.py and the sign-in)
and the agents' skills live there, not in this repository.

Clone it once beside this checkout and keep it current (AGENTS.md, CONTRIBUTING.md):

    git clone https://git.magicbean.dev/MagicBeanDev/Tooling.git ../Tooling
    git -C ../Tooling pull --ff-only

MAGICBEAN_TOOLING names another folder. Standard library only.
"""
import os
import sys

URL = "https://git.magicbean.dev/MagicBeanDev/Tooling.git"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def folder():
    """Tooling's folder: MAGICBEAN_TOOLING, else Tooling beside this checkout (beside the main checkout for a jj or git
    workspace in a folder of its own, too, as both sit in the same parent folder); None when it isn't there"""
    for path in (os.environ.get("MAGICBEAN_TOOLING"), os.path.join(os.path.dirname(ROOT), "Tooling")):
        if path and os.path.isfile(os.path.join(path, "scripts", "forge.py")):
            return os.path.abspath(path)
    return None


def scripts():
    """Tooling's scripts folder, on sys.path; exits saying how to get it when it is missing"""
    found = folder()
    if not found:
        sys.exit("MagicBeanDev/Tooling is not beside this checkout (%s): git clone %s %s (or set MAGICBEAN_TOOLING)"
                 % (os.path.join(os.path.dirname(ROOT), "Tooling"), URL,
                    os.path.join(os.path.dirname(ROOT), "Tooling")))
    path = os.path.join(found, "scripts")
    if path not in sys.path:
        sys.path.insert(0, path)
    return path
