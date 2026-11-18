"""check_updates.py: which of the other ports moved since their last survey.

Reads ../sources.json, asks each repo for its head with `git ls-remote` (nothing is downloaded or run), and prints
one line per source. --write <file> also writes the lines as markdown, for the weekly report. --mark <name> <commit>
records a survey as done. Exit 0 always; the lines say what moved."""
import json, os, subprocess, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "sources.json")


def head(url):
    try:
        out = subprocess.run(["git", "ls-remote", url, "HEAD"], capture_output=True, text=True, timeout=60,
                             env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)
    if out.returncode != 0 or not out.stdout.strip():
        return None, (out.stderr.strip().splitlines() or ["no answer"])[-1]
    return out.stdout.split()[0], ""


def main(argv):
    data = json.load(open(SRC, encoding="utf-8"))
    if argv[:1] == ["--mark"] and len(argv) == 3:
        for s in data["sources"]:
            if s["name"].lower() == argv[1].lower():
                s["surveyed"] = argv[2]
                s["surveyed_on"] = datetime.date.today().isoformat()
                json.dump(data, open(SRC, "w", encoding="utf-8"), indent=1)
                print("marked", s["name"], argv[2])
                return 0
        print("no source named", argv[1])
        return 1
    rows = []
    for s in data["sources"]:
        if not s["url"]:
            rows.append((s["name"], "?", "no link yet", s["kind"]))
            continue
        h, err = head(s["url"])
        if h is None:
            rows.append((s["name"], "?", "unreachable: " + err, s["kind"]))
        elif s["surveyed"] and h.startswith(s["surveyed"]):
            rows.append((s["name"], h[:8], "unchanged", s["kind"]))
        else:
            rows.append((s["name"], h[:8], "NEW since " + (s["surveyed"] or "never surveyed"), s["kind"]))
    for r in rows:
        print("%-16s %-9s %-10s %s" % (r[0], r[1], r[3], r[2]))
    if argv[:1] == ["--write"] and len(argv) == 2:
        with open(argv[1], "w", encoding="utf-8") as f:
            f.write("# Other ports: updates (%s)\n\n| Port | Head | Kind | State |\n|---|---|---|---|\n"
                    % datetime.date.today().isoformat())
            for r in rows:
                f.write("| %s | `%s` | %s | %s |\n" % (r[0], r[1], r[3], r[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
