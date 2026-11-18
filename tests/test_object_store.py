"""The object store shared by every work folder (nx2/object_store.py, HOOKSHOT_OBJ_STORE): a work folder takes the objects it
needs from it and gives it its own, the folder's clean-up (make_game.py prune_object_cache) never takes an object from the
store, and the store's own clean-up lets go only what no folder holds and nobody used lately, oldest first over its size.

    python -I -B tests/test_object_store.py
"""
import ast
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import object_store  # noqa: E402

tree = ast.parse((ROOT / "nx2" / "make_game.py").read_text(encoding="utf-8"))
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "prune_object_cache")
ns = {"os": os}
exec(compile(ast.Module([fn], []), "make_game.py", "exec"), ns)
prune_folder = ns["prune_object_cache"]

STAMP = "0123456789abcdef" + "0" * 24
A, B, C = "a" * 40, "b" * 40, "c" * 40


def work_folder(top, name, keys=(), used=()):
    w = Path(top, name)
    (w / "objcache").mkdir(parents=True)
    (w / "system_headers.txt").write_text(STAMP + "\n")
    for k in keys:
        (w / "objcache" / (k + ".o")).write_bytes(k.encode())
    obj = w / "sa" / "build" / "obj"
    obj.mkdir(parents=True)
    for i, k in enumerate(used):
        (obj / ("f%d.o.sha1" % i)).write_text(k)
    return w


with tempfile.TemporaryDirectory() as top:
    store_root = Path(top, "store")
    with mock.patch.dict(os.environ, {"HOOKSHOT_OBJ_STORE": ""}):
        assert object_store.root() is None and object_store.folder(top) is None   # (off unless set)
    with mock.patch.dict(os.environ, {"HOOKSHOT_OBJ_STORE": "0"}):
        assert object_store.root() is None
    with mock.patch.dict(os.environ, {"HOOKSHOT_OBJ_STORE": str(store_root)}):
        first = work_folder(top, "first", keys=(A, B), used=(A, B))
        store = object_store.folder(str(first))
        assert store == str(store_root / STAMP[:16]), store   # (one folder per compiler and headers)
        assert object_store.folder(top) is None   # (a work folder without the note uses no store)

        assert object_store.share(str(first / "objcache"), store) == 2
        assert object_store.share(str(first / "objcache"), store) == 0   # (what the store has is left as it is)
        assert sorted(os.listdir(store)) == [A + ".o", B + ".o"]

        second = work_folder(top, "second", used=(A,))
        assert object_store.fetch(store, str(second / "objcache"), [A, C]) == 1   # (C: in no store, compiled)
        assert (second / "objcache" / (A + ".o")).read_bytes() == A.encode()
        assert object_store.fetch(store, str(second / "objcache"), [A]) == 0

        # (the second folder's clean-up keeps what it used and lets go of its other links; the store keeps every object)
        (second / "objcache" / (B + ".o")).write_bytes(b"other")
        prune_folder(str(second))
        assert sorted(os.listdir(second / "objcache")) == [A + ".o"]
        assert sorted(os.listdir(store)) == [A + ".o", B + ".o"]
        assert (Path(store) / (B + ".o")).read_bytes() == B.encode()

        # (a link that failed takes its objects out of the store; the folders' own links stay)
        object_store.forget(store, [B])
        assert not (Path(store) / (B + ".o")).exists() and (first / "objcache" / (B + ".o")).exists()

        # (the store's clean-up: an object a folder holds stays whatever its age, where the file system has hard links)
        now = time.time()
        for f in os.listdir(store):
            os.utime(os.path.join(store, f), (now - 100 * 86400, now - 100 * 86400))
        linked = os.stat(os.path.join(store, A + ".o")).st_nlink > 1
        removed, _ = object_store.prune(str(store_root), now=now)
        assert (removed == 0) == linked and (Path(store) / (A + ".o")).exists() == linked

    with mock.patch.dict(os.environ, {"HOOKSHOT_OBJ_STORE": str(store_root), "HOOKSHOT_OBJ_STORE_GB": "0.000001",
                                      "HOOKSHOT_OBJ_STORE_DAYS": "14"}):
        # (objects only the store holds: the oldest go first while they are over the size; one used in the last hour stays)
        d = store_root / "fedcba9876543210"
        d.mkdir(parents=True)
        now = time.time()
        for i, (k, age) in enumerate(((A, 3 * 86400), (B, 2 * 86400), (C, 60))):
            p = d / (k + ".o")
            p.write_bytes(b"x" * 1000)
            os.utime(p, (now - age, now - age))
        removed, freed = object_store.prune(str(store_root), now=now)
        assert sorted(os.listdir(d)) == [C + ".o"] and removed >= 2 and freed >= 2000, (os.listdir(d), removed, freed)

    with mock.patch.dict(os.environ, {"HOOKSHOT_OBJ_STORE": str(store_root), "HOOKSHOT_OBJ_STORE_GB": "100",
                                      "HOOKSHOT_OBJ_STORE_DAYS": "14"}):
        # (under the size: only what nobody used for the days goes)
        d = store_root / "0000000000000001"
        d.mkdir(parents=True)
        now = time.time()
        for k, age in ((A, 20 * 86400), (B, 2 * 86400)):
            p = d / (k + ".o")
            p.write_bytes(b"x")
            os.utime(p, (now - age, now - age))
        object_store.prune(str(store_root), now=now)
        assert sorted(os.listdir(d)) == [B + ".o"], os.listdir(d)

    with mock.patch.dict(os.environ, {"HOOKSHOT_OBJ_STORE": str(store_root), "HOOKSHOT_OBJ_STORE_GB": "100",
                                      "HOOKSHOT_OBJ_STORE_DAYS": "14"}):
        # (a namespace the clean-up cannot list, removed meanwhile or without permission: skipped, the others cleaned, nothing
        # raised; the build has already compiled and installed by then)
        now = time.time()
        readable, gone = store_root / "0000000000000002", store_root / "0000000000000003"
        for d in (readable, gone):
            d.mkdir(parents=True)
            p = d / (A + ".o")
            p.write_bytes(b"x")
            os.utime(p, (now - 20 * 86400, now - 20 * 86400))
        listdir = os.listdir

        def vanished(path):
            if Path(path) == gone:
                raise FileNotFoundError(2, "No such file or directory", str(path))
            return listdir(path)

        with mock.patch.object(object_store.os, "listdir", vanished):
            removed, _ = object_store.prune(str(store_root), now=now)
        assert removed == 1 and not (readable / (A + ".o")).exists() and (gone / (A + ".o")).exists(), removed
        if os.name != "nt" and os.geteuid() != 0:   # (mode 000 stops neither Windows nor root)
            p = readable / (B + ".o")
            p.write_bytes(b"x")
            os.utime(p, (now - 20 * 86400, now - 20 * 86400))
            os.chmod(gone, 0)
            try:
                removed, _ = object_store.prune(str(store_root), now=now)
            finally:
                os.chmod(gone, 0o755)
            assert removed == 1 and not p.exists(), removed
            # (a store the clean-up cannot read at all: nothing removed)
            os.chmod(store_root, 0)
            try:
                assert object_store.prune(str(store_root), now=now) == (0, 0)
            finally:
                os.chmod(store_root, 0o755)
        with mock.patch.object(object_store.os, "listdir", side_effect=PermissionError(13, "Permission denied")):
            assert object_store.prune(str(store_root), now=now) == (0, 0)
    # (a store root that is a file: nothing to clean)
    not_dir = Path(top, "store-file")
    not_dir.write_bytes(b"")
    assert object_store.prune(str(not_dir)) == (0, 0)
print("ok: one object store for every work folder, and its clean-up, also past a folder it cannot read")
