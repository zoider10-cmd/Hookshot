"""scripts/forge.py's pull request commands, game-free and offline: the HTTP layer (forge.api) is a stand-in Forgejo
that keeps the pull requests, labels and comments in memory, and a real request fails the test. pr create opens as work
in progress (WIP: title) with the template as the description when none is given (main's and this PR's commits filled
in), and --ready only when the description passes check_pr_description.py; pr ready runs that check with the PR's diff,
refuses an incomplete description (--force goes on with a warning), prints the check's warnings, and takes WIP: and the
'needs measurements' label off; pr wip puts WIP: back (and the label, when asked); pr
edit keeps the WIP state; pr update edits the description and comments in one step, or only comments; pr comment takes
--body-file, and with --attach posts the comment, puts each picture up as its attachment and edits it to show them
(attach:NAME in the text becomes the picture's link, the rest go at the end), refusing before anything is posted a file
that is missing, not a picture by name and bytes, or too big, and an attach: with no file; an upload that fails stops
there and names the comment, what went up and what didn't (the upload itself: a stand-in urlopen reads its form); the
fork and the PR's head use the login Forgejo has now, not the one saved at sign-in (an
account can be renamed); pr status shows the state, the check, the checklist, the reviews and the last comments (and
for a work-in-progress PR, which Forgejo never calls mergeable, whether main has moved past its base); pr
review posts one review (approve, comment or request changes) with its inline comments on lines of the diff, refusing
a line outside the diff's hunks before posting anything, and an approval of a work-in-progress PR.

    python -I -B tests/test_forge_pr.py
"""
import contextlib
import email.parser
import email.policy
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


forge = load("forge", ROOT / "scripts" / "forge.py")
samples = load("test_check_pr_description", ROOT / "tests" / "test_check_pr_description.py")
TEMPLATE = samples.TEMPLATE
FILLED = samples.GOOD
DIFF = samples.DIFF
REAL_API_UPLOAD = forge.api_upload
# (the first bytes of each kind of picture --attach takes, and a little more)
PNG = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + bytes(24)
JPEG = b"\xff\xd8\xff\xe0\0\x10JFIF\0" + bytes(24)
GIF = b"GIF89a" + bytes(24)
WEBP = b"RIFF\x24\0\0\0WEBPVP8 " + bytes(24)
ATTACHMENT = "https://git.magicbean.dev/attachments/0f3c-%d"


class Forgejo:
    """The API calls forge.py's pr commands make, against pull requests kept in memory"""

    def __init__(self):
        self.prs, self.comments, self.calls = {}, {}, []
        self.labels = [{"id": 7, "name": "testing wanted"}, {"id": 9, "name": "needs measurements"}]
        self.reviews, self.diffs = {}, {}
        self.assets, self.refuse, self.refuse_edit = [], set(), False   # (comment attachments; names to fail; edits)
        self.wip_prefixes = ("WIP:", "[WIP]")
        self.main_head = "7afe6ae1" + "2" * 32

    def add(self, number, title, body, labels=()):
        self.prs[number] = {"number": number, "title": title, "body": body, "state": "open", "merged": False,
                            "mergeable": True, "user": {"login": "alice"}, "head": {"label": "alice:fix"},
                            "base": {"ref": "main"}, "labels": [l for l in self.labels if l["name"] in labels],
                            "html_url": "https://git.magicbean.dev/MagicBeanDev/Hookshot/pulls/%d" % number}
        self.prs[number]["draft"] = self.draft(title)
        self.comments[number] = []
        return self.prs[number]

    def draft(self, title):
        return any(title.upper().startswith(p) for p in self.wip_prefixes)

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        base = "/repos/MagicBeanDev/Hookshot"
        if method == "GET" and path == "/user":
            return {"login": "alice"}
        if method == "GET" and path.startswith("/repos/alice/Hookshot/branches/"):
            return {"name": path.rsplit("/", 1)[1]}
        assert path.startswith(base), path
        path = path[len(base):]
        parts = path.split("?")[0].strip("/").split("/")
        if method == "POST" and parts == ["pulls"]:
            assert body["head"].startswith("alice:"), body["head"]   # (the login Forgejo has now)
            pr = self.add(len(self.prs) + 1, body["title"], body["body"])
            pr["head"]["sha"], pr["merge_base"] = "992a2420" + "1" * 32, "7afe6ae1" + "2" * 32
            return dict(pr)
        if parts == ["branches", "main"]:
            return {"name": "main", "commit": {"id": self.main_head}}
        if parts[:2] == ["git", "commits"]:
            return {"commit": {"committer": {"date": "2026-11-10T12:00:00Z"}}}
        if parts[0] == "labels":
            return self.labels
        if parts[:2] == ["issues", "comments"] and method == "PATCH":
            if self.refuse_edit:
                raise forge.ForgeError("PATCH %s: HTTP 502 Bad Gateway" % path)
            self.comment(int(parts[2]))["body"] = body["body"]
            return dict(self.comment(int(parts[2])))
        number = int(parts[1])
        pr = self.prs[number]
        if parts[0] == "pulls" and len(parts) == 2:
            if method == "PATCH":
                pr.update(body)
                pr["draft"] = self.draft(pr["title"])
            return dict(pr)
        if parts[2:] == ["reviews"]:
            if method == "POST":
                self.reviews.setdefault(number, []).append(dict(body, user={"login": "alice"}, state=body["event"]))
                return {"html_url": pr["html_url"] + "#issuecomment-%d" % (100 + len(self.reviews[number]))}
            return self.reviews.get(number, [])
        if parts[2:] == ["comments"]:
            if method == "POST":
                cid = sum(len(c) for c in self.comments.values()) + 1
                self.comments[number].append({"id": cid, "body": body["body"], "user": {"login": "alice"},
                                              "created_at": "2026-11-12T18:00:00Z",
                                              "html_url": pr["html_url"] + "#issuecomment-%d" % cid})
                return dict(self.comments[number][-1])
            return self.comments[number]
        if parts[2] == "labels":
            if method == "POST":
                pr["labels"] += [l for l in self.labels if l["id"] in body["labels"]]
            elif method == "DELETE":
                pr["labels"] = [l for l in pr["labels"] if l["id"] != int(parts[3])]
            return None
        raise AssertionError("unexpected call %s %s" % (method, path))

    def comment(self, cid):
        found, = [c for comments in self.comments.values() for c in comments if c["id"] == cid]
        return found

    def upload(self, path, name, data, content_type):
        """forge.api_upload: a picture put up as an attachment of a comment"""
        self.calls.append(("POST", path, {"name": name, "bytes": data, "content_type": content_type}))
        where, _, query = path.partition("?name=")
        assert where.startswith("/repos/MagicBeanDev/Hookshot/issues/comments/") and where.endswith("/assets"), path
        assert urllib.parse.unquote(query) == name, path   # (the real name, which Forgejo takes before the form's)
        self.comment(int(where.split("/")[-2]))
        if name in self.refuse:
            raise forge.ForgeError("POST %s: HTTP 500 the attachment storage is full" % where)
        self.assets.append(name)
        return {"name": name, "size": len(data), "browser_download_url": ATTACHMENT % len(self.assets)}

    def text(self, path):
        self.calls.append(("GET", path, None))
        number = int(path.rsplit("/", 1)[1].split(".")[0])
        return self.diffs.get(number, "")

    def writes(self):
        return [(m, p, b) for m, p, b in self.calls if m != "GET"]


def no_network(*args, **kwargs):
    raise AssertionError("a real request in a test: %r" % (args,))


class PR(unittest.TestCase):
    def setUp(self):
        self.forgejo = Forgejo()
        self.patches = [mock.patch.object(forge, "api", self.forgejo),
                        mock.patch.object(forge, "api_text", self.forgejo.text),
                        mock.patch.object(forge, "api_upload", self.forgejo.upload),
                        # (the login saved at sign-in, from before the account was renamed: the server's is the one used)
                        mock.patch.object(forge, "token", lambda: {"login": "alice-before", "access_token": "t"}),
                        mock.patch.object(forge, "ensure_fork", lambda login: ("%s/Hookshot" % login, False)),
                        mock.patch.object(forge.auth, "forge_request", no_network),
                        mock.patch.object(forge.auth, "forge_session", no_network),
                        mock.patch.object(forge.urllib.request, "urlopen", no_network)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.tmp = tempfile.mkdtemp()

    def run_forge(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = forge.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def file(self, text, name="body.md"):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def picture(self, name, data=PNG, folder=""):
        os.makedirs(os.path.join(self.tmp, folder), exist_ok=True)
        path = os.path.join(self.tmp, folder, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    # --- create ---

    def test_create_opens_as_wip_with_the_template(self):
        code, out, _ = self.run_forge("pr", "create", "fix", "--title", "fix(menu): text cut off at 4K")
        self.assertEqual(code, 0)
        pr = self.forgejo.prs[1]
        self.assertEqual(pr["title"], "WIP: fix(menu): text cut off at 4K")
        self.assertTrue(pr["draft"])
        # (no --body-file: the description starts from the template, with the commits filled in)
        # (and If applicable down to the boxes the diff suggests: none for this one)
        self.assertEqual(pr["body"], forge.desc.keep_applicable(
            TEMPLATE.replace("main: <commit> (<date>)", "main: 7afe6ae1 (2026-11-10)")
            .replace("this PR: <branch> @ <commit>", "this PR: fix @ 992a2420")
            .replace("| | main @ <commit> | this PR @ <commit> |", "| | main @ 7afe6ae1 | this PR @ 992a2420 |"), []))
        self.assertIn("<what was measured>", pr["body"])
        self.assertIn("pr ready 1", out)

    def test_create_keeps_the_boxes_the_diff_suggests(self):
        self.forgejo.diffs[1] = "--- a/gpu/vk/vk_api.h\n+++ b/gpu/vk/vk_api.h\n@@ -1 +1 @@\n+x\n"
        self.assertEqual(self.run_forge("pr", "create", "fix", "--title", "fix: x")[0], 0)
        lists = forge.desc.sections(forge.desc.sections(self.forgejo.prs[1]["body"])["Checklist"], "###")
        self.assertEqual([item.split(" ")[0] for _, item in forge.desc.boxes(lists["If applicable"])],
                         ["`MKWVK_API_VERSION`", "A", "Host"])
        self.forgejo.diffs[5] = self.forgejo.diffs[1]
        self.forgejo.add(5, "WIP: fix: x", FILLED.replace("- [x] Docs updated.\n", ""))
        out = self.run_forge("pr", "status", "5")[1]
        self.assertIn("Checklist, If applicable: 5 kept, 5 ticked", out)
        self.assertIn("  hint: If applicable: the diff suggests '`MKWVK_API_VERSION` bumped", out)

    def test_create_draft_is_the_default_and_wip_is_not_doubled(self):
        self.assertEqual(self.run_forge("pr", "create", "fix", "--title", "fix: x", "--draft", "--body", "b")[0], 0)
        self.assertEqual(self.run_forge("pr", "create", "fix", "--title", "WIP: fix: y", "--wip")[0], 0)
        self.assertEqual(self.forgejo.prs[1]["title"], "WIP: fix: x")
        self.assertEqual(self.forgejo.prs[1]["body"], "b")
        self.assertEqual([m for m, _, _ in self.forgejo.writes()], ["POST", "POST", "PATCH"], "only the template is filled")
        self.assertEqual(self.forgejo.prs[2]["title"], "WIP: fix: y")

    def test_create_ready_needs_a_complete_description(self):
        code, _, err = self.run_forge("pr", "create", "fix", "--title", "fix: x", "--ready")
        self.assertEqual(code, 1)
        self.assertIn("not ready for review", err)
        self.assertIn("## Why still holds the template's placeholders", err)
        self.assertEqual(self.forgejo.writes(), [], "nothing is opened")
        code, _, _ = self.run_forge("pr", "create", "fix", "--title", "fix: x", "--ready", "--body-file", self.file(FILLED))
        self.assertEqual(code, 0)
        self.assertEqual(self.forgejo.prs[1]["title"], "fix: x")
        code, _, err = self.run_forge("pr", "create", "fix", "--title", "fix: y", "--ready", "--force")
        self.assertEqual((code, self.forgejo.prs[2]["title"]), (0, "fix: y"))
        self.assertIn("warning", err)

    def test_create_refuses(self):
        self.assertIn("Conventional Commit", self.run_forge("pr", "create", "fix", "--title", "Fix things")[2])
        self.assertIn("--force goes with --ready", self.run_forge("pr", "create", "fix", "--title", "fix: x", "--force")[2])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            forge.main(["pr", "create", "fix", "--title", "fix: x", "--ready", "--wip"])
        self.assertEqual(self.forgejo.writes(), [])

    # --- ready and wip ---

    def test_ready_refuses_an_incomplete_description(self):
        self.forgejo.add(5, "WIP: fix: x", TEMPLATE)
        code, _, err = self.run_forge("pr", "ready", "5")
        self.assertEqual(code, 1)
        for want in ("## Why still holds the template's placeholders", "not ticked: One topic.", "pr edit 5 --body-file", "--force"):
            self.assertIn(want, err)
        self.assertEqual(self.forgejo.prs[5]["title"], "WIP: fix: x")
        self.assertEqual(self.forgejo.writes(), [])
        body = FILLED.replace("- [x] Rebased on current `main`.", "- [ ] Rebased on current `main`.")
        self.forgejo.prs[5]["body"] = body
        self.assertIn("not ticked: Rebased on current `main`.", self.run_forge("pr", "ready", "5")[2])

    def test_ready_checks_the_diff_and_warns(self):
        self.forgejo.add(5, "WIP: fix: x", FILLED)["merge_base"] = "0123456789abcdef"
        self.forgejo.diffs[5] = DIFF
        out = self.run_forge("pr", "status", "5")[1]
        self.assertIn("  note: the diff adds RX_VK_NEW_THING, which ## Flags and settings does not list", out)
        self.assertIn("  warning: measured on main 7afe6ae1", out)
        code, _, err = self.run_forge("pr", "ready", "5")
        self.assertEqual(code, 0, err)   # (the Flags note never stops it, nor does a warning)
        self.assertIn("warning: the diff adds RX_VK_NEW_THING, which ## Flags and settings does not list", err)
        self.assertIn("warning: measured on main 7afe6ae1, but the PR is now on main 01234567", err)
        self.assertIn(("GET", "/repos/MagicBeanDev/Hookshot/pulls/5.diff", None), self.forgejo.calls)

    def test_ready_waits_for_the_test_requests(self):
        body = FILLED.replace("(T-9MZ4)", "(request to open)")
        self.forgejo.add(5, "WIP: fix: x", body)
        code, _, err = self.run_forge("pr", "ready", "5")
        self.assertEqual(code, 1)
        self.assertIn("## Testing's 'Needs other testers:' still has a request to open: Steam Deck", err)
        self.assertIn("scripts/test_requests.py request --pr", err)
        self.assertNotIn("warning: ## Testing", err, "said once, as the reason")
        self.assertIn("Description: complete but for 1 test request to open", self.run_forge("pr", "status", "5")[1])
        self.forgejo.prs[5]["body"] = FILLED
        self.assertEqual(self.run_forge("pr", "ready", "5")[0], 0)
        out = self.run_forge("pr", "status", "5")[1]
        self.assertIn("Testing: Tested filled in, Not tested filled in; needs other testers: 2 (2 with a test request, "
                      "0 to open)", out)

    def test_ready_force(self):
        self.forgejo.add(5, "WIP: fix: x", TEMPLATE)
        code, out, err = self.run_forge("pr", "ready", "5", "--force")
        self.assertEqual(code, 0)
        self.assertIn("warning", err)
        self.assertEqual(self.forgejo.prs[5]["title"], "fix: x")

    def test_ready_takes_wip_and_the_label_off(self):
        self.forgejo.add(5, "[WIP] WIP: fix: x", FILLED, labels=["needs measurements", "testing wanted"])
        code, out, _ = self.run_forge("pr", "ready", "5")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.forgejo.prs[5]["title"], "fix: x")
        self.assertFalse(self.forgejo.prs[5]["draft"])
        self.assertEqual([l["name"] for l in self.forgejo.prs[5]["labels"]], ["testing wanted"])
        self.assertIn("ready for review", out)
        code, out, _ = self.run_forge("pr", "ready", "5")
        self.assertIn("already", out)

    def test_ready_when_the_server_reads_another_prefix(self):
        self.forgejo.wip_prefixes += ("DRAFT:",)
        self.forgejo.add(5, "WIP: DRAFT: fix: x", FILLED)
        code, _, err = self.run_forge("pr", "ready", "5")
        self.assertEqual(code, 1)
        self.assertIn("WORK_IN_PROGRESS_PREFIXES", err)

    def test_wip(self):
        self.forgejo.add(5, "fix: x", FILLED)
        code, out, _ = self.run_forge("pr", "wip", "5")
        self.assertEqual((code, self.forgejo.prs[5]["title"]), (0, "WIP: fix: x"))
        self.assertEqual(self.forgejo.prs[5]["labels"], [])
        writes = len(self.forgejo.writes())
        code, out, _ = self.run_forge("pr", "wip", "5", "--needs-measurements")
        self.assertIn("already", out)
        self.assertEqual(self.forgejo.prs[5]["title"], "WIP: fix: x")
        self.assertEqual([l["name"] for l in self.forgejo.prs[5]["labels"]], ["needs measurements"])
        self.assertEqual(len(self.forgejo.writes()), writes + 1, "only the label")

    def test_closed_or_merged(self):
        self.forgejo.add(5, "WIP: fix: x", FILLED)["merged"] = True
        self.assertIn("merged", self.run_forge("pr", "ready", "5")[2])
        self.assertEqual(self.forgejo.writes(), [])

    # --- edit, update, comment ---

    def test_edit_keeps_the_wip_state(self):
        self.forgejo.add(5, "WIP: fix: x", TEMPLATE)
        self.forgejo.add(6, "fix: y", FILLED)
        self.assertEqual(self.run_forge("pr", "edit", "5", "--title", "fix(vk): x")[0], 0)
        self.assertEqual(self.forgejo.prs[5]["title"], "WIP: fix(vk): x")
        self.assertEqual(self.run_forge("pr", "edit", "6", "--title", "WIP: fix(vk): y")[0], 0)
        self.assertEqual(self.forgejo.prs[6]["title"], "fix(vk): y", "pr wip, not pr edit, makes it WIP")
        self.assertIn("Conventional Commit", self.run_forge("pr", "edit", "6", "--title", "no")[2])
        self.assertIn("nothing to change", self.run_forge("pr", "edit", "6")[2])

    def test_edit_the_description(self):
        self.forgejo.add(5, "WIP: fix: x", TEMPLATE)
        self.forgejo.add(6, "fix: y", FILLED)
        code, out, err = self.run_forge("pr", "edit", "5", "--body-file", self.file(FILLED))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.forgejo.prs[5]["body"], FILLED)
        code, out, err = self.run_forge("pr", "edit", "6", "--body", "short")
        self.assertEqual(code, 0)
        self.assertEqual(self.forgejo.prs[6]["body"], "short")
        self.assertIn("no longer passes", err, "a PR marked ready whose description stops passing")
        self.assertIn("pr wip 6", err)

    def test_update_edits_and_comments(self):
        self.forgejo.add(5, "WIP: fix: x", TEMPLATE)
        code, out, _ = self.run_forge("pr", "update", "5", "--body-file", self.file(FILLED),
                                      "--comment", "Measured on an RX 6700 XT: the table is in the description.")
        self.assertEqual(code, 0)
        self.assertEqual(self.forgejo.prs[5]["body"], FILLED)
        self.assertEqual([c["body"] for c in self.forgejo.comments[5]],
                         ["Measured on an RX 6700 XT: the table is in the description."])
        self.assertEqual([m for m, _, _ in self.forgejo.writes()], ["PATCH", "POST"])
        self.assertIn("#issuecomment-1", out)

    def test_update_comment_only(self):
        self.forgejo.add(5, "WIP: fix: x", TEMPLATE)
        code, _, _ = self.run_forge("pr", "update", "5", "--comment-file", self.file("Rebased on main.\n", "c.md"))
        self.assertEqual(code, 0)
        self.assertEqual(self.forgejo.prs[5]["body"], TEMPLATE)
        self.assertEqual([m for m, _, _ in self.forgejo.writes()], ["POST"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            forge.main(["pr", "update", "5", "--body", "b"])   # (a comment is required)
        self.assertIn("say what changed", self.run_forge("pr", "update", "5", "--comment", "  ")[2])
        self.assertEqual(len(self.forgejo.comments[5]), 1)

    def test_comment_from_a_file(self):
        self.forgejo.add(5, "fix: x", FILLED)
        self.assertEqual(self.run_forge("pr", "comment", "5", "--body-file", self.file("Tested: fixed.\n"))[0], 0)
        self.assertEqual(self.run_forge("pr", "comment", "5", "Second.")[0], 0)
        self.assertEqual([c["body"] for c in self.forgejo.comments[5]], ["Tested: fixed.\n", "Second."])
        self.assertIn("empty", self.run_forge("pr", "comment", "5")[2])

    # --- comment --attach: pictures in the comment ---

    def test_comment_without_attach_is_as_before(self):
        self.forgejo.add(5, "fix: x", FILLED)
        text = "![not a file here](attach:nothing.png)"
        code, out, err = self.run_forge("pr", "comment", "5", text)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.forgejo.writes(),
                         [("POST", "/repos/MagicBeanDev/Hookshot/issues/5/comments", {"body": text})])
        self.assertEqual(out, self.forgejo.comments[5][0]["html_url"] + "\n")

    def test_comment_attach_shows_the_pictures(self):
        self.forgejo.add(5, "fix: x", FILLED)
        shot, kokiri, extra = (self.picture("main-21x9.png"), self.picture("kokiri.jpg", JPEG),
                               self.picture("extra.webp", WEBP))
        text = ("Test request T-XXXX: pass\n\n![main at 21:9](attach:main-21x9.png)\n\n"
                "![Kokiri](attach:kokiri.jpg \"Kokiri Forest\") and again ![same](attach:main-21x9.png)\n")
        code, out, err = self.run_forge("pr", "comment", "5", "--body-file", self.file(text),
                                        "--attach", shot, kokiri, "--attach", extra)
        self.assertEqual((code, err), (0, ""))
        comment = self.forgejo.comments[5][0]
        writes = self.forgejo.writes()
        self.assertEqual([(m, p.split("?")[0]) for m, p, _ in writes],
                         [("POST", "/repos/MagicBeanDev/Hookshot/issues/5/comments")]
                         + [("POST", "/repos/MagicBeanDev/Hookshot/issues/comments/%d/assets" % comment["id"])] * 3
                         + [("PATCH", "/repos/MagicBeanDev/Hookshot/issues/comments/%d" % comment["id"])])
        self.assertEqual([(b["name"], b["content_type"]) for _, _, b in writes[1:4]],
                         [("main-21x9.png", "image/png"), ("kokiri.jpg", "image/jpeg"), ("extra.webp", "image/webp")])
        self.assertEqual([b["bytes"] for _, _, b in writes[1:4]], [PNG, JPEG, WEBP], "each file whole, once")
        # (posted first with the placeholders, the picture the text doesn't show added at the end; then edited)
        self.assertEqual(writes[0][2]["body"], text.rstrip() + "\n\n![extra.webp](attach:extra.webp)\n")
        self.assertEqual(comment["body"], "Test request T-XXXX: pass\n\n![main at 21:9](%s)\n\n![Kokiri](%s \"Kokiri "
                         "Forest\") and again ![same](%s)\n\n![extra.webp](%s)\n"
                         % (ATTACHMENT % 1, ATTACHMENT % 2, ATTACHMENT % 1, ATTACHMENT % 3))
        self.assertEqual(out.splitlines(),
                         [comment["html_url"], "3 pictures in the comment: main-21x9.png, kokiri.jpg, extra.webp"])

    def test_comment_attach_names(self):
        self.forgejo.add(5, "fix: x", FILLED)
        odd = self.picture("Zélda [1] (2).gif", GIF)
        code, _, err = self.run_forge("pr", "comment", "5", "--attach", odd)   # (pictures alone)
        self.assertEqual(code, 0, err)
        (_, _, posted), (_, path, _), _ = self.forgejo.writes()
        self.assertEqual(posted["body"], "![Zélda \\[1\\] (2).gif](attach:Z%C3%A9lda%20%5B1%5D%20%282%29.gif)\n")
        self.assertTrue(path.endswith("/assets?name=Z%C3%A9lda%20%5B1%5D%20%282%29.gif"), path)
        self.assertEqual(self.forgejo.comments[5][0]["body"], "![Zélda \\[1\\] (2).gif](%s)\n" % (ATTACHMENT % 1))
        # (a name with a space is referred to percent-encoded; TEXT before --attach)
        spaced = self.picture("main 21x9.png")
        code, _, err = self.run_forge("pr", "comment", "5", "![main](attach:main%2021x9.png)", "--attach", spaced)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.forgejo.comments[5][1]["body"], "![main](%s)" % (ATTACHMENT % 2))

    def test_comment_attach_refuses_before_posting(self):
        self.forgejo.add(5, "fix: x", FILLED)
        shot = self.picture("shot.png")
        os.makedirs(os.path.join(self.tmp, "folder.png"))
        missing, nso = os.path.join(self.tmp, "missing.png"), self.picture("main.nso", b"NSO0" + bytes(60))
        for paths, want in (([missing], "missing.png: no such file"),
                            ([os.path.join(self.tmp, "folder.png")], "folder.png: not a file"),
                            ([nso], "main.nso: not a picture by its name"),
                            ([self.picture("hookshot_programs.bin", PNG)],
                             "hookshot_programs.bin: not a picture by its name"),
                            ([self.picture("dump.png", b"\x7fELF" + bytes(60))],
                             "dump.png: named as a PNG, but its bytes are no picture's"),
                            ([self.picture("photo.png", JPEG)],
                             "photo.png: named as a PNG, but its bytes are a JPEG's: rename it"),
                            ([self.picture("empty.webp", b"")], "empty.webp: named as a WEBP, but its bytes are no"),
                            ([shot, self.picture("shot.png", PNG, "other")], "a second file named shot.png"),
                            ([missing, nso], "main.nso: not a picture")):   # (every problem at once)
            code, out, err = self.run_forge("pr", "comment", "5", "Results.", "--attach", *paths)
            self.assertEqual((code, out), (1, ""), want)
            for line in (want, "--attach: nothing was posted", "no game files, keys or anything made from them",
                         "CONTRIBUTING.md, The rule with no exceptions"):
                self.assertIn(line, err)
        self.assertIn("missing.png: no such file", err)
        with mock.patch.object(forge, "ATTACH_MAX", len(PNG) - 1):
            self.assertIn("shot.png: 0.0 MiB, over the 0 MiB a picture may have",
                          self.run_forge("pr", "comment", "5", "x", "--attach", shot)[2])
        code, _, err = self.run_forge("pr", "comment", "5", "![a](attach:shot.png) ![b](attach:other.png)",
                                      "--attach", shot)
        self.assertEqual(code, 1)
        self.assertIn("the comment shows attach:other.png, but --attach gives no file of that name: nothing was "
                      "posted", err)
        self.assertEqual(self.forgejo.writes(), [])

    def test_comment_attach_upload_fails(self):
        self.forgejo.add(5, "fix: x", FILLED)
        a, b, c = (self.picture(n) for n in ("a.png", "b.png", "c.png"))
        self.forgejo.refuse = {"b.png"}
        code, out, err = self.run_forge("pr", "comment", "5", "Shots: ![b](attach:b.png)", "--attach", a, b, c)
        self.assertEqual(code, 1)
        comment = self.forgejo.comments[5][0]
        self.assertEqual(out.splitlines(), [comment["html_url"]], "the link first: the comment is there")
        for want in ("the comment is posted, but not all its pictures show: " + comment["html_url"],
                     "  uploaded: a.png",
                     "  failed: b.png (POST /repos/MagicBeanDev/Hookshot/issues/comments/1/assets: HTTP 500",
                     "  not tried: c.png", "the others still read attach:NAME", "Don't post it again",
                     "pr comment 5 --attach FILE"):
            self.assertIn(want, err)
        # (each tried once, no retry, and none after the failure; the comment shows the one that went up)
        self.assertEqual([b["name"] for _, p, b in self.forgejo.writes() if "/assets" in p], ["a.png", "b.png"])
        self.assertEqual(comment["body"], "Shots: ![b](attach:b.png)\n\n![a.png](%s)\n\n![c.png](attach:c.png)\n"
                         % (ATTACHMENT % 1))
        # (the first fails: nothing to show, so no edit)
        self.forgejo.refuse = {"a.png"}
        writes = len(self.forgejo.writes())
        code, _, err = self.run_forge("pr", "comment", "5", "Shots.", "--attach", a, b)
        self.assertEqual(code, 1)
        self.assertIn("  uploaded: none\n  failed: a.png", err)
        self.assertIn("  not tried: b.png", err)
        self.assertEqual([m for m, _, _ in self.forgejo.writes()[writes:]], ["POST", "POST"])
        self.assertEqual(self.forgejo.comments[5][1]["body"],
                         "Shots.\n\n![a.png](attach:a.png)\n\n![b.png](attach:b.png)\n")
        # (all went up but the edit fails: their links, to put in by hand)
        self.forgejo.refuse, self.forgejo.refuse_edit = set(), True
        code, _, err = self.run_forge("pr", "comment", "5", "Shots.", "--attach", a)
        self.assertEqual(code, 1)
        self.assertIn("  uploaded: a.png\nThe edit that shows them failed too (PATCH", err)
        self.assertIn("\n  a.png %s\n" % (ATTACHMENT % 2), err)

    def test_upload_sends_the_form(self):
        sent, answer = [], {"size": len(PNG), "browser_download_url": ATTACHMENT % 1}

        def urlopen(req, timeout):
            sent.append((req, timeout))
            return io.BytesIO(json.dumps(answer).encode())

        with mock.patch.object(forge, "api_upload", REAL_API_UPLOAD), \
                mock.patch.object(forge.urllib.request, "urlopen", urlopen):
            self.assertEqual(forge.upload_picture(12, "Zélda 1.png", PNG, "image/png"), ATTACHMENT % 1)
            (req, timeout), = sent
            self.assertEqual(req.full_url, "https://git.magicbean.dev/api/v1/repos/MagicBeanDev/Hookshot/issues/"
                                           "comments/12/assets?name=Z%C3%A9lda%201.png")
            self.assertEqual((req.get_method(), req.get_header("User-agent"), req.get_header("Authorization")),
                             ("POST", forge.auth.USER_AGENT, "Bearer t"))
            ctype = req.get_header("Content-type")
            self.assertTrue(ctype.startswith("multipart/form-data; boundary=hookshot-"), ctype)
            form = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + req.data)
            part, = form.iter_parts()
            self.assertEqual((part.get_param("name", header="content-disposition"), part.get_filename(),
                              part.get_content_type(), part.get_payload(decode=True)),
                             ("attachment", "Z_lda_1.png", "image/png", PNG))
            answer["size"] = 3   # (the server kept part of it)
            with self.assertRaisesRegex(forge.ForgeError, r"Zélda 1.png: the server's answer is not this picture's"):
                forge.upload_picture(12, "Zélda 1.png", PNG, "image/png")

            def refused(req, timeout):
                raise urllib.error.HTTPError(req.full_url, 413, "Too Large", {}, io.BytesIO(b"too big"))

            def down(req, timeout):
                raise urllib.error.URLError("connection refused")

            for opener, want in ((refused, r"issues/comments/12/assets: HTTP 413 too big"), (down, "cannot reach")):
                with mock.patch.object(forge.urllib.request, "urlopen", opener), \
                        self.assertRaisesRegex(forge.ForgeError, want):
                    forge.upload_picture(12, "a.png", PNG, "image/png")

    # --- review ---

    REVIEW_DIFF = """diff --git a/gpu/vk/a.cpp b/gpu/vk/a.cpp
index 1111111..2222222 100644
--- a/gpu/vk/a.cpp
+++ b/gpu/vk/a.cpp
@@ -10,4 +10,5 @@ void f() {
 int a;
--- removed, though it reads like a header
+++ added, though it reads like a header
+int c;
 int d;
@@ -40,2 +41,2 @@
-old();
+new_();
diff --git a/docs/new.md b/docs/new.md
new file mode 100644
--- /dev/null
+++ b/docs/new.md
@@ -0,0 +1,2 @@
+# New
+text
diff --git a/old.txt b/old.txt
deleted file mode 100644
--- a/old.txt
+++ /dev/null
@@ -1,2 +0,0 @@
-gone
-too
"""

    def review_pr(self, title="fix: x"):
        self.forgejo.add(5, title, FILLED)["head"]["sha"] = "abc123" + "0" * 34
        self.forgejo.diffs[5] = self.REVIEW_DIFF

    def test_diff_lines(self):
        lines = forge.diff_lines(self.REVIEW_DIFF)
        self.assertEqual(lines["gpu/vk/a.cpp"], ({10, 11, 12, 13, 41}, {10, 11, 12, 40}))
        self.assertEqual(lines["docs/new.md"], ({1, 2}, set()))
        self.assertEqual(lines["old.txt"], (set(), {1, 2}))

    def test_review_approve_with_line_comments(self):
        self.review_pr()
        inline = self.file('[{"path": "docs/new.md", "line": 2, "body": "typo"},'
                           ' {"path": "gpu/vk/a.cpp", "old_line": 40, "body": "why remove it?"}]', "inline.json")
        code, out, err = self.run_forge("pr", "review", "5", "--approve", "--body", "Looks right.", "--inline", inline,
                                        "--at", "gpu/vk/a.cpp:12", "c is never read", "--at", "old.txt:-2", "fine")
        self.assertEqual(code, 0, err)
        self.assertIn("approved, 4 inline comments: https://git.magicbean.dev/MagicBeanDev/Hookshot/pulls/5#issuecomment-101", out)
        (method, path, body), = self.forgejo.writes()
        self.assertEqual((method, path), ("POST", "/repos/MagicBeanDev/Hookshot/pulls/5/reviews"))
        self.assertEqual((body["event"], body["body"], body["commit_id"]), ("APPROVED", "Looks right.", "abc123" + "0" * 34))
        self.assertEqual(body["comments"], [
            {"path": "docs/new.md", "body": "typo", "new_position": 2, "old_position": 0},
            {"path": "gpu/vk/a.cpp", "body": "why remove it?", "new_position": 0, "old_position": 40},
            {"path": "gpu/vk/a.cpp", "body": "c is never read", "new_position": 12, "old_position": 0},
            {"path": "old.txt", "body": "fine", "new_position": 0, "old_position": 2}])

    def test_review_refuses_lines_off_the_diff(self):
        self.review_pr()
        for at in (["gpu/vk/a.cpp:30", "x"], ["gpu/vk/a.cpp:-41", "x"], ["README.md:1", "x"]):
            code, _, err = self.run_forge("pr", "review", "5", "--comment", "--at", *at)
            self.assertEqual(code, 1)
            self.assertIn("off the diff", err)
        for bad in (["--at", "gpu/vk/a.cpp", "x"], ["--at", "a.cpp:x", "x"], ["--at", "gpu/vk/a.cpp:12", " "],
                    ["--inline", self.file('{"path": "a"}', "bad.json")], ["--inline", self.file("not json", "bad2.json")],
                    ["--inline", self.file('[{"path": "docs/new.md", "line": 1, "old_line": 1, "body": "x"}]', "both.json")]):
            self.assertEqual(self.run_forge("pr", "review", "5", "--comment", *bad)[0], 1, bad)
        self.assertEqual(self.forgejo.writes(), [])

    def test_review_wip_empty_and_closed(self):
        self.review_pr("WIP: fix: x")
        code, _, err = self.run_forge("pr", "review", "5", "--approve")
        self.assertEqual(code, 1)
        self.assertIn("work in progress", err)
        self.assertIn("empty", self.run_forge("pr", "review", "5", "--request-changes")[2])
        self.assertEqual(self.forgejo.writes(), [])
        code, out, _ = self.run_forge("pr", "review", "5", "--request-changes", "--at", "gpu/vk/a.cpp:41", "breaks Linux")
        self.assertEqual(code, 0)
        self.assertIn("request changes, 1 inline comment:", out)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            forge.main(["pr", "review", "5", "--body", "no verdict"])
        self.forgejo.prs[5].update(title="fix: x", draft=False, state="closed")
        self.assertIn("#5 is closed", self.run_forge("pr", "review", "5", "--approve")[2])
        self.forgejo.prs[5]["state"] = "open"
        self.assertEqual(self.run_forge("pr", "review", "5", "--approve")[0], 0)   # (an approval may say nothing more)
        self.assertEqual([r["event"] for r in self.forgejo.reviews[5]], ["REQUEST_CHANGES", "APPROVED"])

    # --- status ---

    def test_status(self):
        self.forgejo.add(5, "WIP: fix: x", TEMPLATE, labels=["needs measurements"])
        self.forgejo.reviews[5] = [{"user": {"login": "bob"}, "state": "REQUEST_CHANGES"},
                                   {"user": {"login": "bob"}, "state": "APPROVED"},
                                   {"user": {"login": "carol"}, "state": "PENDING"}]
        for i in range(5):
            self.forgejo.comments[5].append({"body": "comment %d" % i, "user": {"login": "bob"},
                                             "created_at": "2026-11-12T18:0%d:00Z" % i})
        code, out, _ = self.run_forge("pr", "status", "5")
        self.assertEqual(code, 0)
        for want in ("work in progress", "to fix before pr ready", "For everyone: 0 of 10 ticked", "Mergeable: yes",
                     "Labels: needs measurements", "Reviews: bob approved", "Last comments (5 in all)", "comment 4"):
            self.assertIn(want, out)
        self.assertNotIn("carol", out)
        self.assertNotIn("comment 1", out)
        self.forgejo.add(6, "fix: y", FILLED)
        out = self.run_forge("pr", "status", "6")[1]
        for want in ("ready for review", "Description: complete", "For everyone: 10 of 10 ticked", "Reviews: none"):
            self.assertIn(want, out)

    def test_status_mergeable_of_a_wip_pr(self):
        # (Forgejo answers not mergeable for any WIP PR: a rebase is named only where one can be needed)
        head = self.forgejo.main_head
        for title, merge_base, want in (("fix: x", head, "Mergeable: no (rebase onto main)"),
                                        ("WIP: fix: x", head, "work in progress (Forgejo merges no WIP PR); it is on "
                                                              "main's head, no rebase needed"),
                                        ("WIP: fix: x", "0" * 40, "main has moved past its base: rebase if it conflicts"),
                                        ("WIP: fix: x", None, "whether it needs a rebase shows once it is ready")):
            pr = self.forgejo.add(7, title, TEMPLATE)
            pr.update(mergeable=False, merge_base=merge_base)
            self.assertIn(want, self.run_forge("pr", "status", "7")[1], title)

    def test_view_shows_wip(self):
        self.forgejo.add(5, "[wip] fix: x", FILLED)
        self.assertIn("work in progress, by alice", self.run_forge("pr", "view", "5")[1])

    def test_view_into_a_cp1252_pipe(self):
        # into a pipe on Windows, stdout is cp1252, which has no robot: pr view used to stop with a UnicodeEncodeError
        self.forgejo.add(6, "fix: y", FILLED + "\n\N{ROBOT FACE} Generated\n")
        pipe = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with contextlib.redirect_stdout(pipe), contextlib.redirect_stderr(io.StringIO()):
            code = forge.main(["pr", "view", "6"])
        pipe.flush()
        text = pipe.buffer.getvalue().decode("utf-8")
        self.assertEqual((code, pipe.encoding), (0, "utf-8"))
        self.assertIn("\N{ROBOT FACE} Generated", text)


if __name__ == "__main__":
    unittest.main()
