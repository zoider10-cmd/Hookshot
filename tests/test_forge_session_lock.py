"""The git sign-in survives two renewals at once (scripts/magicbean_login.py, forge_session).

Forgejo takes each refresh token once. Before the lock, git's credential helper and forge.py (or two agents) renewing at
the same moment left the second with "token was already used" and the sign-in lost. Here several processes renew an
expired sign-in together against a stand-in for Forgejo that refuses a reused refresh token: every one must come back
with a token, and the stand-in must have been asked once. No network, no forge.

python -I -B tests/test_forge_session_lock.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (one renewing process: Forgejo's token endpoint replaced by a file per refresh token taken, O_EXCL so a second use of
# the same token fails as Forgejo refuses it; slow, so the processes overlap)
CHILD = r'''
import importlib.util, json, os, sys, time
spec = importlib.util.spec_from_file_location("auth", os.path.join(sys.argv[1], "scripts", "magicbean_login.py"))
auth = importlib.util.module_from_spec(spec); spec.loader.exec_module(auth)
used = sys.argv[2]
def forge_tokens(form):
    rt = form["refresh_token"]
    try:
        os.close(os.open(os.path.join(used, rt), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        raise auth.LoginError("POST access_token: HTTP 400 token was already used")
    time.sleep(0.5)
    return {"access_token": "at-after-" + rt, "refresh_token": "rt-after-" + rt, "expires_at": time.time() + 3600}
auth.forge_tokens = forge_tokens
state = auth.forge_session()
print(json.dumps(state["access_token"] if state else None))
'''


class SessionLock(unittest.TestCase):
    def test_renewals_at_once(self):
        with tempfile.TemporaryDirectory() as d:
            conf, used = os.path.join(d, "conf"), os.path.join(d, "used")
            os.makedirs(conf)
            os.makedirs(used)
            with open(os.path.join(conf, "forge.json"), "w", encoding="utf-8") as f:
                json.dump({"login": "someone", "access_token": "old", "refresh_token": "rt0", "expires_at": 0}, f)
            env = dict(os.environ, HOOKSHOT_TEAM_CHAT_DIR=conf)
            procs = [subprocess.Popen([sys.executable, "-I", "-B", "-c", CHILD, ROOT, used], env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
            outs = [p.communicate(timeout=60) for p in procs]
            got = [json.loads(o.strip() or "null") for o, _ in outs]
            self.assertEqual(got, ["at-after-rt0"] * 4, [e for _, e in outs])
            self.assertEqual(sorted(os.listdir(used)), ["rt0"])   # (Forgejo asked once)
            with open(os.path.join(conf, "forge.json"), encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["refresh_token"], "rt-after-rt0")
            self.assertGreater(saved["expires_at"], time.time())
            self.assertEqual([n for n in os.listdir(conf) if n.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()
