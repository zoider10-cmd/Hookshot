"""forge.py moved to MagicBeanDev/Tooling, the team's shared scripts: run it from there,

    python -I ../Tooling/scripts/forge.py ...        (scripts/tooling.py says how to get it)

This forwarder runs it for the commands and git credential helpers that still name this file, so a sign-in made before
the move keeps working; forge.py login points git at Tooling's copy."""
import os
import runpy
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tooling  # noqa: E402  (same folder; python -I does not add it to the path)

if __name__ == "__main__":
    script = os.path.join(tooling.scripts(), "forge.py")
    if sys.argv[1:2] != ["credential"]:   # (git reads a helper's output: no note there)
        print("note: forge.py is now %s (MagicBeanDev/Tooling); this copy only forwards to it" % script,
              file=sys.stderr)
    sys.argv[0] = script
    runpy.run_path(script, run_name="__main__")
