"""The launcher's side of the performance statistics (gpu/vk/perf_report.cpp is the game's): the tick, and sending what
the game left in the game folder's perf_pending/.

  - The launcher's "Send performance statistics" tick is send=1 in the game folder's hookshot_perf.ini, off by default.
    The game reads it at its start: off, it measures nothing and writes nothing.
  - On, the game writes a summary (JSON, the relay's version 1) every 5 minutes and at exit into perf_pending/. The
    launcher sends them at its next start, in a process of its own (start_sending), to perf_reports in nx2/addresses.ini (Hookshot-api's telemetry),
    oldest first, and deletes each one the relay took or refused; one it couldn't reach stays for next time.
  - The sender fills in version and release (the release flag as the crash report has it: a release's version, built
    from the release's own sources), which the game can't know.
  - Each summary the relay took is also kept, as it was sent, in perf_sent/ (the 48 sent last): what went to the team, for the
    player or a tester to read. The launcher's "Keep a copy of what was sent" (keep_sent=0 in hookshot_perf.ini when it is
    off), or HOOKSHOT_PERF_KEEP_SENT, turns that off, and empties perf_sent/.
  - Turning the tick off deletes what is waiting, and what perf_sent/ kept: the player said no.
  - Polite by default: the summaries go over one connection, at most HOOKSHOT_PERF_MAX_SENDS (12) a start, and a relay that
    answers busy (429 or 5xx) is left alone until the time it names (Retry-After), else an hour, doubled each time it is
    busy again up to a day (perf_pending/.next). The switches: docs/performance-statistics.md, "Switches".

python -I nx2/perf_report.py <game folder>            what would be sent, sends nothing
python -I nx2/perf_report.py <game folder> --send     sends it (what the launchers start: start_sending)
python -I nx2/perf_report.py <game folder> --tick on|off [--keep-sent on|off]
                                                      the launcher's tick (set_sending): off deletes what waits
"""
import email.utils
import http.client
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from addresses import address  # noqa: E402

ENDPOINT = address("perf_reports")
CHOICE = "hookshot_perf.ini"   # (send=1: the launcher's tick; the game reads it, gpu/vk/perf_report.cpp)
PENDING = "perf_pending"
SENT = "perf_sent"   # (a copy of each summary the relay took, as sent: the newest MAX_PENDING)
VERSION_FILE = "hookshot_version.txt"
# The game's logs, newest first: in logs/ (host/game_layout.c), else at the top of folders made before it moved there
LOGS = [os.path.join(d, name) for d in ("logs", "") for name in ["hookshot_log.txt"] + ["hookshot_log.%d.txt" % k for k in range(1, 5)]]
MAX_PENDING = 48   # (the newest kept when the launcher hasn't been back for long: older ones go unsent)
MAX_BODY = 60 * 1024   # (the relay's limit is 64 KiB: a bigger one is refused there anyway)
# A release's version (docs/versioning.md), as the crash report has it (host/hos_crash_dialog.h)
RELEASE_VERSION = re.compile(r"^v?\d+\.\d+\.\d+(?:-rc\.\d+)?$|^nightly-\d+-[0-9a-f]{8}$")
FIRST_LINE = re.compile(r"\bhookshot (\S+)(?: \(source ([0-9a-f]+)\))?")
NEXT = ".next"   # (in perf_pending/: when the relay may be asked again after it answered busy, and the wait it took)
BUSY_FIRST, BUSY_MOST = 3600, 86400   # (seconds: a busy relay's first wait without a Retry-After, and the longest)
HEADERS = {"Content-Type": "application/json", "User-Agent": "hookshot-perf-report"}


def env_number(name, default, low, high):
    """A whole-number switch, clamped to [low, high] (said on stderr); unset, empty or not a number: the default"""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        print("%s=%s is not a whole number: %d" % (name, raw, default), file=sys.stderr)
        return default
    if not low <= value <= high:
        value = min(max(value, low), high)
        print("%s=%s is outside %d to %d: %d" % (name, raw, low, high, value), file=sys.stderr)
    return value


def env_switch(name):
    """An on/off switch: True, False, or None when unset or unknown (the caller's default)"""
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "on", "yes", "true"):
        return True
    if raw in ("0", "off", "no", "false"):
        return False
    if raw:
        print("%s=%s is neither on nor off: the default" % (name, raw), file=sys.stderr)
    return None


def endpoint():
    """Where the summaries go: HOOKSHOT_PERF_URL (https, or http to this PC only, for a local relay), else perf_reports in
    nx2/addresses.ini"""
    raw = os.environ.get("HOOKSHOT_PERF_URL", "").strip()
    if not raw:
        return ENDPOINT
    u = urllib.parse.urlsplit(raw)
    if u.scheme == "https" and u.hostname or u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1"):
        return raw
    print("HOOKSHOT_PERF_URL=%s is not https (or http to this PC): %s" % (raw, ENDPOINT or "nowhere"), file=sys.stderr)
    return ENDPOINT


def choices(folder):
    """hookshot_perf.ini's lines as {key: value}; {} without the file"""
    try:
        with open(os.path.join(folder, CHOICE), encoding="utf-8", errors="replace") as f:
            return dict(line.strip().split("=", 1) for line in f if "=" in line)
    except OSError:
        return {}


def sending(folder):
    """The tick: on only with send=1 in the game folder"""
    return choices(folder).get("send") == "1"


def keeping_sent(folder):
    """Whether a copy of each summary sent is kept in perf_sent/: HOOKSHOT_PERF_KEEP_SENT, else the launcher's choice
    (keep_sent=0 in hookshot_perf.ini: off), on by default"""
    env = env_switch("HOOKSHOT_PERF_KEEP_SENT")
    return env if env is not None else choices(folder).get("keep_sent") != "0"


def remove_all(folder, sub, ends):
    """Deletes sub's files whose names end with one of ends; nothing raised"""
    try:
        names = [n for n in os.listdir(os.path.join(folder, sub)) if n.endswith(ends)]
    except OSError:
        names = []
    for name in names:
        try:
            os.remove(os.path.join(folder, sub, name))
        except OSError:
            pass


def set_sending(folder, on, keep_sent=True):
    """The tick, saved for the game (it reads it at its start), and whether copies of what was sent are kept (off empties
    perf_sent/). The tick off deletes what is waiting, and the copies in perf_sent/"""
    path = os.path.join(folder, CHOICE)
    if on:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write("send=1\n" + ("" if keep_sent else "keep_sent=0\n"))
        os.replace(path + ".tmp", path)
        if not keep_sent:
            remove_all(folder, SENT, (".json", ".tmp"))
        return
    try:
        os.remove(path)
    except OSError:
        pass
    remove_all(folder, PENDING, (".json", ".tmp", NEXT))   # (and a file cut short while it was written: its .tmp)
    remove_all(folder, SENT, (".json", ".tmp"))


def order(name):
    """A summary's place, oldest first: its name is <unix time>-<n>.json"""
    m = re.match(r"(\d+)-(\d+)\.json$", name)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def listed(folder, sub):
    """The summaries in the game folder's sub (perf_pending/ or perf_sent/), unsorted; none without the folder"""
    try:
        return [n for n in os.listdir(os.path.join(folder, sub)) if n.endswith(".json")]
    except OSError:
        return []


def waiting(folder):
    """The summaries waiting, oldest first"""
    return sorted(listed(folder, PENDING), key=order)


def build_facts(folder):
    """(version, release) of the game in that folder: hookshot_version.txt's version, and the release flag (a release's
    version and the log's source fingerprint the same as the release's own source= line)"""
    version, expected = "", ""
    try:
        with open(os.path.join(folder, VERSION_FILE), encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("version="):
                    version = line[8:].strip()
                elif line.startswith("source="):
                    expected = line[7:].strip()
    except OSError:
        pass
    source = ""
    for name in LOGS:
        try:
            with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                m = FIRST_LINE.search(f.readline())
        except OSError:
            continue
        if m:
            version = version or m.group(1)
            source = m.group(2) or ""
            break
    return version, bool(RELEASE_VERSION.match(version) and expected and source == expected)


def answer(code, retry_after=None):
    """(result, seconds to wait) of the relay's status: 'sent' (2xx), 'refused' (4xx but 429: never better next time) or
    'busy' (429, 5xx), with its Retry-After in seconds when it gave one"""
    if 200 <= code < 300:
        return "sent", None
    if code == 429 or code >= 500:
        return "busy", wait_of(retry_after)
    return "refused", None


def wait_of(retry_after):
    """Retry-After's seconds (a number, or an HTTP date), None without one or when it can't be read"""
    if not retry_after:
        return None
    if retry_after.strip().isdigit():
        return int(retry_after.strip())
    try:
        return max(0, int(email.utils.parsedate_to_datetime(retry_after).timestamp() - time.time()))
    except (TypeError, ValueError, OverflowError):
        return None


def post(body, url, timeout=10):
    """One summary on a connection of its own (urllib, which takes the system's proxy): answer()'s pair, or ('later', None)
    when not reached or cut short"""
    req = urllib.request.Request(url, data=body, method="POST", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return answer(r.status)
    except urllib.error.HTTPError as e:
        return answer(e.code, e.headers.get("Retry-After"))
    except Exception:   # (not reached, cut short: kept for next time)
        return "later", None


class Relay:
    """The summaries over one kept connection (a handshake for them all, not one each). Through a proxy, urllib's post()
    for each, which knows the system's proxy and http.client doesn't"""

    def __init__(self, url, timeout):
        self.url, self.timeout, self.conn = url, timeout, None
        u = urllib.parse.urlsplit(url)
        self.https, self.host, self.port = u.scheme == "https", u.hostname, u.port
        self.path = (u.path or "/") + ("?" + u.query if u.query else "")
        proxy = urllib.request.getproxies().get(u.scheme)
        self.proxied = bool(proxy) and not urllib.request.proxy_bypass(u.hostname or "")

    def post(self, body):
        if self.proxied:
            return post(body, self.url, self.timeout)
        for again in (False, True):
            reused = self.conn is not None
            if not reused:
                kind = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
                self.conn = kind(self.host, self.port, timeout=self.timeout)
            try:
                self.conn.request("POST", self.path, body, HEADERS)
                r = self.conn.getresponse()
                r.read()   # (all of it: the connection serves the next one)
            except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError):
                # (a kept connection the relay closed while it waited: the summary never arrived, once more on a new one)
                self.close()
                if reused and not again:
                    continue
                return "later", None
            except Exception:   # (not reached, cut short: kept for next time)
                self.close()
                return "later", None
            if r.will_close:
                self.close()
            return answer(r.status, r.getheader("Retry-After"))
        return "later", None

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None


def busy_until(folder):
    """(when the relay may be asked again, the wait that set it): (0, 0) when it wasn't busy"""
    try:
        with open(os.path.join(folder, PENDING, NEXT), encoding="utf-8") as f:
            at, wait = f.read().split()
            return float(at), int(wait)
    except (OSError, ValueError):
        return 0, 0


def note_busy(folder, retry_after):
    """The relay answered busy: not asked again before its Retry-After (at most a day), else an hour, doubled each time it
    is busy again, up to a day"""
    _, before = busy_until(folder)
    wait = min(retry_after, BUSY_MOST) if retry_after is not None else min(max(BUSY_FIRST, before * 2), BUSY_MOST)
    path = os.path.join(folder, PENDING, NEXT)
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write("%d %d\n" % (time.time() + wait, wait))
        os.replace(path + ".tmp", path)
    except OSError:
        pass


def send_waiting(folder, url=None, timeout=None):
    """Sends what is waiting, when the tick is on: {"sent": n, "refused": n, "left": n}. Stops at the first one the relay
    couldn't take now, and after HOOKSHOT_PERF_MAX_SENDS; nothing while the relay asked to be left alone (HOOKSHOT_PERF_BACKOFF)"""
    url = endpoint() if url is None else url
    timeout = env_number("HOOKSHOT_PERF_TIMEOUT", 10, 2, 60) if timeout is None else timeout
    most = env_number("HOOKSHOT_PERF_MAX_SENDS", 12, 1, MAX_PENDING)
    backoff = env_switch("HOOKSHOT_PERF_BACKOFF") is not False
    counts = {"sent": 0, "refused": 0, "left": 0}
    if not folder or not sending(folder):
        return counts
    names = waiting(folder)
    for old in names[:-MAX_PENDING]:   # (too many: the oldest go unsent)
        try:
            os.remove(os.path.join(folder, PENDING, old))
        except OSError:
            pass
    names = names[-MAX_PENDING:]
    keep = keeping_sent(folder)
    if not keep:   # (the player keeps none: what an earlier send kept goes too)
        remove_all(folder, SENT, (".json", ".tmp"))
    if not url or backoff and busy_until(folder)[0] > time.time():
        counts["left"] = len(names)
        return counts
    version, release = build_facts(folder)
    relay = Relay(url, timeout)
    try:
        sent_all = send_these(folder, names[:most], relay, version, release, counts, backoff)
    finally:
        relay.close()
    counts["left"] = len(names) - counts["sent"] - counts["refused"]
    if sent_all:
        try:
            os.remove(os.path.join(folder, PENDING, NEXT))
        except OSError:
            pass
    if counts["sent"] and keep:
        prune_sent(folder)
    return counts


def send_these(folder, names, relay, version, release, counts, backoff):
    """send_waiting's loop: True when the relay took or refused each one, False when it stopped (busy: noted, unless
    HOOKSHOT_PERF_BACKOFF is off; not reached: tried again at the next start)"""
    for name in names:
        path = os.path.join(folder, PENDING, name)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:   # (a bad byte: one field's text, not the summary)
                summary = json.load(f)
            if not isinstance(summary, dict):
                raise ValueError
        except (OSError, ValueError):
            result = "refused"   # (unreadable: dropped)
        else:
            # (the game's own version, of the build that wrote it: the folder may have been updated since. A release only
            # when that is the folder's build, whose fingerprint was checked)
            own = summary.get("version") if isinstance(summary.get("version"), str) else ""
            summary["version"] = own or version
            summary["release"] = release and summary["version"] == version
            body = json.dumps(summary, separators=(",", ":")).encode()
            result, wait = ("refused", None) if len(body) > MAX_BODY else relay.post(body)
            if result == "busy":
                if backoff:
                    note_busy(folder, wait)
                return False
        if result == "later":
            return False
        counts[result] += 1
        try:
            os.remove(path)
        except OSError:
            pass
        if result == "sent":   # (after the remove: nothing between the relay's yes and the summary leaving perf_pending/)
            keep_sent(folder, name, body)
    return True


def keep_sent(folder, name, body):
    """A copy of what the relay took, as sent, in perf_sent/. Best effort: the summary is sent. None once the tick is off
    (unticked during the send: the player said no, and set_sending emptied perf_sent/), or copies are off"""
    if not sending(folder) or not keeping_sent(folder):
        return
    sent = os.path.join(folder, SENT)
    tmp = os.path.join(sent, name + ".tmp")
    try:
        os.makedirs(sent, exist_ok=True)
        with open(tmp, "wb") as f:
            f.write(body)
        os.replace(tmp, os.path.join(sent, name))
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def prune_sent(folder):
    """perf_sent/ down to the MAX_PENDING copies sent last (by when they were written there, not by their names' time: a
    clock that was wrong once would keep the wrong ones)"""
    def written(name):
        try:
            return os.stat(os.path.join(folder, SENT, name)).st_mtime_ns
        except OSError:
            return 0
    for old in sorted(listed(folder, SENT), key=written)[:-MAX_PENDING]:
        try:
            os.remove(os.path.join(folder, SENT, old))
        except OSError:
            pass


def start_sending(folder, python=None, python_args=()):
    """send_waiting in a process of its own, left running: Play closes the launcher at once, and a summary the relay took
    must still be deleted after (or it would be sent, and counted, again). Nothing when the tick is off or nothing waits"""
    if not folder or not sending(folder) or not waiting(folder):
        return None
    cmd = [python or sys.executable, *python_args, "-I", os.path.abspath(__file__), folder, "--send"]
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        kw["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    else:
        kw["start_new_session"] = True
    try:
        return subprocess.Popen(cmd, **kw)
    except OSError:
        return None


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    folder = sys.argv[1]
    if "--send" in sys.argv[2:]:
        print(send_waiting(folder))
        return
    if sys.argv[2:3] == ["--tick"]:
        rest = sys.argv[3:]
        if rest[:1] not in (["on"], ["off"]) or rest[1:] and (rest[1:2] != ["--keep-sent"] or rest[2:] not in (["on"], ["off"])):
            sys.exit("--tick on|off [--keep-sent on|off]")
        keep = rest[2:] != ["off"]
        set_sending(folder, rest[0] == "on", keep)
        print("tick: %s, keep sent: %s" % (rest[0], "on" if keep else "off"))
        return
    version, release = build_facts(folder)
    kept = len(listed(folder, SENT))
    at, _ = busy_until(folder)
    print("tick: %s, waiting: %d, version %s, release %s, to %s; %d sent ones kept in %s (keep sent: %s)%s" % (
        "on" if sending(folder) else "off", len(waiting(folder)), version or "?", release, endpoint() or "nowhere", kept,
        os.path.join(folder, SENT), "on" if keeping_sent(folder) else "off",
        "; the relay was busy: not asked before %s" % time.strftime("%Y-%m-%d %H:%M", time.localtime(at))
        if at > time.time() else ""))


if __name__ == "__main__":
    main()
