"""Who reports problems: the GPU vendor, card class and OS named in the issue forms (docs/workflow.md, "Reach").

    python -I scripts/hardware_report.py [--limit 1000] [--state all|open|closed]

Reads MagicBeanDev/Hookshot's issues on git.magicbean.dev through the Forgejo API, signed in as scripts/forge.py is (run
`python -I scripts/forge.py login` once), and counts the "Graphics card and driver version" and "CPU, RAM and operating
system" answers. It counts reports, not players: hardware where things break shows up more. Standard library only.
"""
import argparse
import collections
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forge  # noqa: E402  (same folder: its signed-in API client and REPO, MagicBeanDev/Hookshot)


def issues(state, limit):
    """[{number, title, body}] of the repository's issues (not pull requests), newest first, at most limit"""
    out, page = [], 1
    while len(out) < limit:
        items = forge.api("GET", "/repos/%s/issues?type=issues&state=%s&limit=50&page=%d"
                          % (forge.REPO, urllib.parse.quote(state), page)) or []
        out += [{"number": i["number"], "title": i.get("title") or "", "body": i.get("body") or ""} for i in items]
        if len(items) < 50:
            break
        page += 1
    return out[:limit]


def section(body: str, name: str) -> str:
    m = re.search(r"### " + re.escape(name) + r"[^\n]*\n+(.*?)(\n### |\Z)", body or "", re.S)
    return m.group(1).strip() if m else ""


def classify(gpu: str):
    g = gpu.lower()
    if re.search(r"nvidia|rtx|gtx|geforce", g):
        cls = ("RTX 50" if re.search(r"rtx ?50\d0", g) else "RTX 40" if re.search(r"rtx ?40\d0", g) else
               "RTX 30" if re.search(r"rtx ?30\d0", g) else "RTX 20" if re.search(r"rtx ?20\d0", g) else
               "GTX 10/16 (no mesh shaders)" if re.search(r"gtx ?1[06]\d0", g) else "NVIDIA other")
        return "NVIDIA", cls
    if re.search(r"amd|radeon|\brx ?\d|rdna|780m|680m|890m|860m|8060s|z1|steam deck|legion|ally", g):
        cls = ("AMD APU / handheld" if re.search(r"780m|680m|890m|860m|8060s|z1|steam deck|legion|ally|apu|vega", g) else
               "RX 9000" if re.search(r"9070|9060", g) else "RX 7000" if re.search(r"7900|7800|7700|7600", g) else
               "RX 6000" if re.search(r"6[5-9]\d0|6600|6650|6700|6800|6900", g) else
               "RX 5000 or older (no mesh shaders)" if re.search(r"5[5-7]00|rx ?5[78]0|rx ?4[78]0", g) else "AMD other")
        return "AMD", cls
    if re.search(r"intel|arc\b|iris|uhd", g):
        return "Intel", "Intel"
    return "unknown", "unknown"


def os_of(text: str) -> str:
    t = text.lower()
    if re.search(r"linux|ubuntu|arch|fedora|steamos|bazzite|cachy|nixos|mint|pop!?_os|steam deck", t):
        return "Linux / SteamOS"
    if re.search(r"windows|win ?1[01]", t):
        return "Windows"
    return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=1000)
    ap.add_argument("--state", default="all", choices=("all", "open", "closed"))
    a = ap.parse_args()
    try:
        found = issues(a.state, a.limit)
    except forge.ForgeError as e:
        print(e, file=sys.stderr)
        return 1
    vendor, cls, oses = collections.Counter(), collections.Counter(), collections.Counter()
    n = 0
    for i in found:
        gpu = section(i["body"], "Graphics card")
        sysinfo = section(i["body"], "CPU, RAM and operating system")
        if not gpu and not sysinfo:
            continue
        n += 1
        v, c = classify(gpu + " " + i["title"])
        vendor[v] += 1
        cls[c] += 1
        oses[os_of(sysinfo + " " + gpu + " " + i["title"])] += 1
    print(f"{len(found)} issues read, {n} with hardware fields")
    for title, counter in (("vendor", vendor), ("card class", cls), ("OS", oses)):
        print(f"\n{title}:")
        for k, v in counter.most_common():
            print(f"  {k:36s} {v:5d}  {100 * v / max(n, 1):5.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
