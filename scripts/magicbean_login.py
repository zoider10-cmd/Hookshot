"""One sign-in for the team's services on magicbean.dev, used by team_chat.py, test_requests.py and forge.py.

Everything there signs in through Forgejo (git.magicbean.dev), which signs people in with Discord. So there is one
trip through the browser: Sign in with Discord on git.magicbean.dev and approve. The browser comes back to a one-time
listener on 127.0.0.1 with a Forgejo token. The team chat's session then comes from that token, with no second trip:
the team's sign-in service (matrix.magicbean.dev/_magicbean/matrix-login) asks Forgejo whose token it is and answers
with a one-minute login for the Matrix server.

Saved in the config folder (Linux: $XDG_CONFIG_HOME/hookshot, default ~/.config/hookshot; Windows: %APPDATA%\\Hookshot;
HOOKSHOT_TEAM_CHAT_DIR overrides it), readable by you only: forge.json (the Forgejo token, renewed by itself when it
runs out) and team_chat.json (the Matrix session; made again from the Forgejo token when it is missing).

    python -I scripts/magicbean_login.py login [--no-browser]     (the same as team_chat.py login)
    python -I scripts/magicbean_login.py whoami

The Forgejo token comes from Forgejo's built-in OAuth application for git (git-credential-oauth's), with PKCE: nothing
secret in the repository. Standard library only; Windows and Linux.
"""
import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

SERVER = "magicbean.dev"                       # the Matrix server name
FORGE_HOST = "git.magicbean.dev"
FORGE = "https://" + FORGE_HOST
GIT_CLIENT_ID = "a4792ccc-144e-407e-86c9-5e7d8d9c3269"   # Forgejo's default public application "git-credential-oauth"
USER_AGENT = "hookshot-login/1"                # (Cloudflare answers 403 to urllib's default agent)
LOGIN_TIMEOUT = 300


class LoginError(Exception):
    pass


def config_dir():
    if os.environ.get("HOOKSHOT_TEAM_CHAT_DIR"):
        return os.environ["HOOKSHOT_TEAM_CHAT_DIR"]
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Hookshot")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "hookshot")


def write_private(path, value):
    """Written whole to a file only the user can read, then moved over the old one."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    if os.name != "nt":
        os.chmod(path, 0o600)


# --- the git token -------------------------------------------------------------------------------------------------

def forge_path():
    return os.path.join(config_dir(), "forge.json")


def forge_load():
    try:
        with open(forge_path(), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def forge_request(method, url, form=None, token=None, body=None):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=headers), timeout=30) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raise LoginError("%s %s: HTTP %d %s" % (method, url.split("?")[0], e.code,
                                                e.read()[:200].decode("utf-8", "replace")))
    except (urllib.error.URLError, OSError) as e:
        raise LoginError("cannot reach %s: %s" % (FORGE_HOST, e))


def forge_tokens(form):
    r = forge_request("POST", FORGE + "/login/oauth/access_token", dict(form, client_id=GIT_CLIENT_ID))
    if not r or "access_token" not in r:
        raise LoginError("no token from %s: %s" % (FORGE_HOST, r))
    return {"access_token": r["access_token"], "refresh_token": r.get("refresh_token"),
            "expires_at": time.time() + int(r.get("expires_in") or 3600)}


class _SessionLock:
    """Only one process renews the sign-in at a time: Forgejo takes each refresh token once, so two renewals at the
    same moment (git's credential helper and forge.py, two agents) used to leave the second with "token was already
    used" and the sign-in lost. The second waits here, then finds the token the first saved."""

    def __enter__(self):
        os.makedirs(config_dir(), exist_ok=True)
        self.f = open(forge_path() + ".lock", "a+b")
        if os.name == "nt":
            import msvcrt
            self.f.seek(0)
            while True:
                try:
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:   # (LK_LOCK gives up after about 10 s: keep waiting)
                    pass
        else:
            import fcntl
            fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        if os.name == "nt":
            import msvcrt
            self.f.seek(0)
            msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        self.f.close()


def forge_session():
    """The saved git sign-in with an access token good for at least a minute (renewed with the refresh token, which
    Forgejo replaces each time), or None."""
    state = forge_load()
    if not state:
        return None
    if state["expires_at"] - 60 >= time.time():
        return state
    with _SessionLock():
        state = forge_load()   # (read again under the lock: another process may have renewed it meanwhile)
        if not state:
            return None
        if state["expires_at"] - 60 >= time.time():
            return state
        if not state.get("refresh_token"):
            return None
        try:
            state.update(forge_tokens({"grant_type": "refresh_token", "refresh_token": state["refresh_token"]}))
        except LoginError as e:
            print("the git.magicbean.dev sign-in could not be renewed (%s): sign in again" % e, file=sys.stderr)
            return None
        write_private(forge_path(), state)
    return state


def forge_expire():
    """The saved token was refused: the next use renews it first."""
    with _SessionLock():
        state = forge_load()
        if state:
            state["expires_at"] = 0
            write_private(forge_path(), state)


# --- the browser trip ----------------------------------------------------------------------------------------------

def listen(server, wanted, forge_url, expect_state, timeout, on_matrix=None):
    """Serve the redirects until each wanted part came back ("matrix": ?loginToken= on /matrix; "forge": ?code= or
    ?error= on /), sending the browser from the first to forge_url. on_matrix(token) runs as the Matrix token comes in:
    it lasts only moments, so it is turned into a session before the browser goes on. Returns what came back."""
    found = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).items()}
            onward = None
            if query.get("loginToken") and "matrix" not in found:
                found["matrix"] = query["loginToken"]   # (kept even if the tab closes before the reply below is sent)
                if on_matrix:
                    try:
                        found["matrix_user"] = on_matrix(query["loginToken"])
                    except Exception as e:   # (reported after the trip; the git part can still go on)
                        found["matrix_error"] = str(e)
                if "forge" in wanted:
                    onward = forge_url
            elif "code" in query or "error" in query:
                if query.get("state") == expect_state:
                    found["forge"] = query
            try:
                if onward:
                    self.send_response(302)
                    self.send_header("Location", onward)
                    self.end_headers()
                    return
                ok = bool(found) and "error" not in found.get("forge", {})
                text = "Signed in. You can close this tab." if ok else "Sign-in failed: %s" % (
                    found.get("forge", {}).get("error") or "nothing to sign in with in this request")
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(("<!doctype html><title>Hookshot</title><p>%s</p>" % text).encode("utf-8"))
            except OSError:
                pass   # (the browser went away first, e.g. WinError 10053; what came in above is what matters)

        def log_message(self, *args):
            pass

    server.RequestHandlerClass = Handler
    server.timeout = 1
    deadline = time.monotonic() + timeout
    try:
        while not all(w in found for w in wanted) and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    return found


def browser_trip(no_browser=False, out=print):
    """Sign in with Discord on git.magicbean.dev: the Forgejo token, saved. Returns the saved state."""
    listener = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
    redirect = "http://127.0.0.1:%d" % listener.server_address[1]   # (no path: Forgejo matches loopback redirects
    verifier = secrets.token_urlsafe(48)                               #  without the port)
    expect = secrets.token_urlsafe(16)
    url = FORGE + "/login/oauth/authorize?" + urllib.parse.urlencode({
        "client_id": GIT_CLIENT_ID, "redirect_uri": redirect, "response_type": "code", "state": expect,
        "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode(),
        "code_challenge_method": "S256"})
    out("Sign in with Discord here (the link works for %d minutes):\n\n  %s\n" % (LOGIN_TIMEOUT // 60, url))
    sys.stdout.flush()
    if not no_browser:
        webbrowser.open(url)
    reply = listen(listener, ["forge"], None, expect, LOGIN_TIMEOUT).get("forge")
    if not reply:
        raise LoginError("no sign-in came back within %d minutes" % (LOGIN_TIMEOUT // 60))
    if "code" not in reply:
        raise LoginError("git.magicbean.dev: %s" % (reply.get("error_description") or reply.get("error")))
    state = forge_tokens({"grant_type": "authorization_code", "code": reply["code"], "code_verifier": verifier,
                          "redirect_uri": redirect})
    state["login"] = forge_request("GET", FORGE + "/api/v1/user", token=state["access_token"])["login"]
    write_private(forge_path(), state)
    return state


def matrix_from_forge(server=SERVER, chat=None):
    """The team chat's session from the saved Forgejo token, no browser: the team's sign-in service turns the token into
    a one-minute JWT, which logs in to Matrix at once. Saved by team_chat; returns the user ID."""
    if chat is None:
        import team_chat as chat
    state = forge_session()
    if not state:
        raise LoginError("not signed in to %s" % FORGE_HOST)
    base = chat.homeserver(server)
    try:
        reply = forge_request("POST", base + "/_magicbean/matrix-login", token=state["access_token"], body={})
    except LoginError as e:
        raise LoginError("team chat sign-in: %s" % e)
    return chat.finish_jwt(server, base, reply["token"])


def sso_matrix(server, chat, no_browser=False, out=print):
    """Another Matrix server's own single sign-on (the chat only; as in the test). Returns the user ID."""
    base = chat.homeserver(server)
    flows = [f.get("type") for f in chat.request("GET", chat.client(base, "/login")).get("flows", [])]
    if "m.login.sso" not in flows:
        raise LoginError("%s offers no single sign-on (flows: %s)" % (base, ", ".join(flows)))
    listener = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
    url = chat.client(base, "/login/sso/redirect?redirectUrl=" +
                      chat.quote("http://127.0.0.1:%d/matrix" % listener.server_address[1]))
    out("Sign in here (the link works for %d minutes):\n\n  %s\n" % (LOGIN_TIMEOUT // 60, url))
    sys.stdout.flush()
    if not no_browser:
        webbrowser.open(url)
    found = listen(listener, ["matrix"], None, None, LOGIN_TIMEOUT,
                   on_matrix=lambda t: chat.finish_sso(server, base, t))
    if "matrix_user" not in found:
        raise LoginError(found.get("matrix_error") or "no sign-in came back within %d minutes" % (LOGIN_TIMEOUT // 60))
    return found["matrix_user"]


def sign_in(server=SERVER, matrix=True, no_browser=False, out=print, chat=None):
    """Sign in with Discord, one trip through the browser. On the team's server: the Forgejo token, then the team
    chat's session from it. Another Matrix server: its own single sign-on, the chat only. Returns {"forge": login,
    "matrix": user ID} for what it signed in to."""
    if chat is None:
        import team_chat as chat   # (same folder; the module that keeps the Matrix session)
    if server != SERVER:
        return {"matrix": sso_matrix(server, chat, no_browser, out)}
    done = {"forge": browser_trip(no_browser, out)["login"]}
    if matrix:
        done["matrix"] = matrix_from_forge(server, chat)
    return done


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("login", help="sign in with Discord to the team chat and git.magicbean.dev")
    s.add_argument("--no-browser", action="store_true", help="print the link only")
    sub.add_parser("whoami")
    args = p.parse_args(argv)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import team_chat
    try:
        if args.cmd == "login":
            done = sign_in(no_browser=args.no_browser)
            for what, who in sorted(done.items()):
                print("%s: signed in as %s" % ({"matrix": "team chat", "forge": FORGE_HOST}[what], who))
        else:
            chat = team_chat.load()
            print("team chat: %s" % (chat.get("user_id") or "not signed in"))
            forge = forge_session()
            print("%s: %s" % (FORGE_HOST, forge["login"] if forge else "not signed in"))
    except (LoginError, team_chat.ChatError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
