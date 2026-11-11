"""Read an NXAR (.nx) game package and extract its exefs/ and romfs/ trees.

    python -I nx2/nx.py <file.nx>
    python -I nx2/nx.py <file.nx> --extract <dir> [--build e0f3ccfa] [--only exefs|romfs]

NXAR is a chunk-deduplicated container. Its NXMF metadata holds directory records,
file records, a shared node tree, chunk-index lists, and names. File records point
into the NXMF auxiliary chunk-index list, whose entries select physical NXAR chunks.
Multiple roots may share the same files; --build selects the
root whose exefs/main NSO build id starts with the requested prefix.
"""
import argparse
from contextlib import suppress
import hashlib
import os
import shutil
import struct
import sys
from time import monotonic


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # python -I leaves the script folder off

MAGIC = b"NXAR"
NXMF = b"NXMF"
NSO = b"NSO0"
ZSTD = b"\x28\xb5\x2f\xfd"
DIR = 1
FILE = 2


class Nxar:
    def __init__(self, path, *, strict=False):
        self.path = path
        self.f = open(path, "rb")
        h = self.f.read(0x200)
        if len(h) < 0x80 or h[:4] != MAGIC:
            self.f.close()
            raise SystemExit("%s: not an NXAR package (magic %r)" % (path, h[:4]))

        self.file_size = struct.unpack_from("<Q", h, 0x10)[0]
        self.nxct_offset, self.nxct_size = struct.unpack_from("<QQ", h, 0x18)
        self.nxmd_offset, self.nxmd_size = struct.unpack_from("<QQ", h, 0x28)
        self.data_offset = struct.unpack_from("<Q", h, 0x38)[0]
        self.nxmf_offset, self.nxmf_size = struct.unpack_from("<QQ", h, 0x48)
        self.chunks_offset, self.chunk_count = struct.unpack_from("<QQ", h, 0x58)
        self.hashes_offset, self.hashes_size = struct.unpack_from("<QQ", h, 0x68)

        physical = os.fstat(self.f.fileno()).st_size
        if self.file_size and physical < self.file_size:
            self.f.close()
            raise SystemExit("the .nx file is incomplete: it is %d MB, its header says %d MB. Copy/dump it again and make sure the drive has room"
                             % (physical >> 20, self.file_size >> 20))
        if strict and self.file_size != physical:
            self.f.close()
            raise ValueError("NXAR physical size does not match its header")
        self._range(self.nxmf_offset, self.nxmf_size, physical, "NXMF")
        self._range(self.chunks_offset, self.chunk_count * 24, physical, "chunk table")

        self.f.seek(self.nxmf_offset)
        meta = self.f.read(self.nxmf_size)
        if len(meta) != self.nxmf_size or meta[:4] != NXMF:
            self.f.close()
            raise ValueError("invalid or truncated NXMF metadata")
        if struct.unpack_from("<H", meta, 6)[0] < 0x60:
            self.f.close()
            raise ValueError("unsupported NXMF header")
        declared = struct.unpack_from("<Q", meta, 8)[0]
        if declared and declared != self.nxmf_size:
            self.f.close()
            raise ValueError("NXMF size does not match NXAR header")

        self.nd, self.nf, self.nn, self.naux = struct.unpack_from("<4I", meta, 0x10)
        self.dirs_at = struct.unpack_from("<Q", meta, 0x20)[0]
        self.files_at = struct.unpack_from("<Q", meta, 0x28)[0]
        self.nodes_at = struct.unpack_from("<Q", meta, 0x30)[0]
        self.aux_at = struct.unpack_from("<Q", meta, 0x38)[0]
        self.strings_at = struct.unpack_from("<Q", meta, 0x40)[0]
        self.strings_size = struct.unpack_from("<Q", meta, 0x48)[0]

        self._meta_range(self.dirs_at, self.nd * 16, "directory table")
        self._meta_range(self.files_at, self.nf * 64, "file table")
        self._meta_range(self.nodes_at, self.nn * 24, "node table")
        self._meta_range(self.aux_at, self.naux * 4, "auxiliary table")
        self._meta_range(self.strings_at, self.strings_size, "string table")

        self.meta = meta
        self.dirs = [struct.unpack_from("<4I", meta, self.dirs_at + i * 16) for i in range(self.nd)]
        self.files = []
        for i in range(self.nf):
            at = self.files_at + i * 64
            size, first, count, shift = struct.unpack_from("<QIII", meta, at)
            digest = meta[at + 20:at + 52]
            reserved = meta[at + 52:at + 64]
            self.files.append((size, first, count, shift, digest, reserved))
        self.nodes = [struct.unpack_from("<6I", meta, self.nodes_at + i * 24) for i in range(self.nn)]
        self.chunk_refs = list(struct.unpack_from("<%dI" % self.naux, meta, self.aux_at)) if self.naux else []
        self.strings = meta[self.strings_at:self.strings_at + self.strings_size]

        # A directory record with no node referring to it is a filesystem root. The
        # observed OoT NXAR has two roots (base and updated view), with unchanged file
        # records shared between them.
        referenced_dirs = {link for _, _, _, link, kind, _ in self.nodes if kind == DIR}
        self.roots = [i for i in range(self.nd) if i not in referenced_dirs]
        if not self.roots:
            self.f.close()
            raise ValueError("NXMF contains no filesystem root")

        self.f.seek(self.chunks_offset)
        raw = self.f.read(self.chunk_count * 24)
        if len(raw) != self.chunk_count * 24:
            self.f.close()
            raise ValueError("truncated NXAR chunk table")
        self.chunks = [struct.unpack_from("<QIIII", raw, i * 24) for i in range(self.chunk_count)]

        if strict:
            self._verify_tree(physical)

    @staticmethod
    def _range(off, size, limit, what):
        if off < 0 or size < 0 or off > limit or size > limit - off:
            raise ValueError("%s lies outside the NXAR file" % what)

    def _meta_range(self, off, size, what):
        if off < 0 or size < 0 or off > self.nxmf_size or size > self.nxmf_size - off:
            raise ValueError("%s lies outside NXMF" % what)

    def name(self, node):
        off, zero, length, link, kind, flags = node
        if off < self.strings_at or off + length > self.strings_at + self.strings_size:
            raise ValueError("NXMF node name lies outside the string table")
        return self.strings[off - self.strings_at:off - self.strings_at + length].decode("utf-8")

    def children(self, directory):
        if not 0 <= directory < self.nd:
            raise ValueError("directory index outside NXMF")
        first, count, r0, r1 = self.dirs[directory]
        if first > self.nn or count > self.nn - first:
            raise ValueError("directory node range outside NXMF")
        return range(first, first + count)

    def child_dir(self, directory, wanted):
        for i in self.children(directory):
            node = self.nodes[i]
            if node[4] == DIR and self.name(node) == wanted:
                return node[3]
        return None

    def child_file(self, directory, wanted):
        for i in self.children(directory):
            node = self.nodes[i]
            if node[4] == FILE and self.name(node) == wanted:
                return node[3]
        return None

    def parts(self, root):
        return self.child_dir(root, "exefs"), self.child_dir(root, "romfs")

    def walk(self, directory):
        """Yield (relative path, file-record index) below a directory, iteratively."""
        pending = [(directory, "")]
        while pending:
            d, prefix = pending.pop()
            entries = []
            for i in self.children(d):
                node = self.nodes[i]
                name = self.name(node)
                if node[4] == DIR:
                    entries.append((True, node[3], prefix + name + "/"))
                elif node[4] == FILE:
                    if node[3] >= self.nf:
                        raise ValueError("file index outside NXMF")
                    yield prefix + name, node[3]
                else:
                    raise ValueError("unsupported NXMF node type %d" % node[4])
            for _, child, child_prefix in reversed(entries):
                pending.append((child, child_prefix))

    def _verify_tree(self, physical):
        for d in range(self.nd):
            list(self.children(d))
        for node in self.nodes:
            if node[1] or node[5]:
                raise ValueError("unsupported NXMF node flags/reserved fields")
            self.name(node)
            if node[4] == DIR and node[3] >= self.nd:
                raise ValueError("directory node points outside directory table")
            if node[4] == FILE and node[3] >= self.nf:
                raise ValueError("file node points outside file table")
            if node[4] not in (DIR, FILE):
                raise ValueError("unsupported NXMF node type")
        for size, first, count, shift, digest, reserved in self.files:
            if first > self.naux or count > self.naux - first:
                raise ValueError("file points outside NXMF chunk-index list")
            if reserved.strip(b"\0"):
                raise ValueError("unsupported NXMF file flags/reserved fields")
            if count:
                refs = self.chunk_refs[first:first + count]
                if any(i >= self.chunk_count for i in refs):
                    raise ValueError("NXMF chunk-index list points outside chunk table")
                total = sum(self.chunks[i][2] for i in refs)
                if total != size:
                    raise ValueError("file chunk sizes total %d, expected %d" % (total, size))
        for off, stored, raw, codec, aux in self.chunks:
            self._range(off, stored, physical, "chunk data")
            if raw and not stored:
                raise ValueError("non-empty chunk has no stored data")
            if codec not in (0, 1):
                raise ValueError("unsupported NXAR chunk codec %d" % codec)
            if codec == 0 and stored != raw:
                # Some producers may leave codec zero for a self-describing Zstd extent;
                # extraction recognizes that form, but strict verification calls it out.
                self.f.seek(off)
                if self.f.read(4) != ZSTD:
                    raise ValueError("raw NXAR chunk has different stored/unpacked sizes")

    def copy_chunk(self, index, out):
        off, stored, raw, codec, aux = self.chunks[index]
        self.f.seek(off)
        data = self.f.read(stored)
        if len(data) != stored:
            raise SystemExit("the .nx file ends early while reading chunk %d" % index)
        packed = codec == 1 or stored != raw
        if not packed:
            out.write(data)
            return len(data)
        if data[:4] != ZSTD:
            raise SystemExit("NXAR chunk %d uses an unsupported compression/codec (codec %d, %d -> %d bytes)" %
                             (index, codec, stored, raw))
        import zstandard
        try:
            unpacked = zstandard.ZstdDecompressor().decompress(data, max_output_size=raw)
        except zstandard.ZstdError as e:
            raise SystemExit("could not decompress NXAR chunk %d: %s" % (index, e))
        if len(unpacked) != raw:
            raise SystemExit("NXAR chunk %d expanded to %d bytes, %d expected" % (index, len(unpacked), raw))
        out.write(unpacked)
        return len(unpacked)

    def copy_file(self, index, out, limit=None):
        size, first, count, shift, digest, reserved = self.files[index]
        left = size if limit is None else min(size, limit)
        wrote = 0
        if first > self.naux or count > self.naux - first:
            raise SystemExit("NXAR file record %d points outside the NXMF chunk-index list" % index)
        for ref in range(first, first + count):
            if left <= 0:
                break
            chunk = self.chunk_refs[ref]
            if chunk >= self.chunk_count:
                raise SystemExit("NXMF chunk-index entry %d points outside the NXAR chunk table" % ref)
            if left >= self.chunks[chunk][2]:
                got = self.copy_chunk(chunk, out)
            else:
                import io
                tmp = io.BytesIO()
                self.copy_chunk(chunk, tmp)
                b = tmp.getvalue()[:left]
                out.write(b)
                got = len(b)
            wrote += got
            left -= got
        if left:
            raise SystemExit("NXAR file record %d ended %d bytes early" % (index, left))
        return wrote

    def read_file(self, index, n=None):
        import io
        b = io.BytesIO()
        self.copy_file(index, b, n)
        return b.getvalue()

    def build_id(self, root):
        exefs = self.child_dir(root, "exefs")
        if exefs is None:
            return None
        main = self.child_file(exefs, "main")
        if main is None:
            return None
        head = self.read_file(main, 0x60)
        if head[:4] != NSO or len(head) < 0x60:
            return None
        return head[0x40:0x60].hex()

    def pick_root(self, build=None, root=None):
        if root is not None:
            root = int(root)
            if root not in self.roots:
                raise SystemExit("NXAR root %d is not one of the filesystem roots (%s)" % (root, ", ".join(map(str, self.roots))))
            return root
        candidates = []
        for r in self.roots:
            bid = self.build_id(r)
            if build is None or bid and bid.startswith(build.lower()):
                candidates.append((r, bid))
        if not candidates:
            builds = ", ".join("root %d: %s" % (r, self.build_id(r) or "no main NSO") for r in self.roots)
            raise SystemExit("the .nx has no filesystem root for build %s (%s)" % (build, builds))
        return candidates[-1][0]


class ProgressSink:
    def __init__(self, output, report):
        self.output, self.report = output, report
    def write(self, data):
        n = self.output.write(data)
        self.report(n)
        return n


def extract(nx, root, out, only=None, quiet=False):
    # Reuse the same Windows long-path/path-safety rules as NUP extraction.
    import nup
    total = done = written = 0
    next_report = monotonic() + 2

    def progress(n):
        nonlocal written, next_report
        written += n
        now = monotonic()
        if not quiet and now >= next_report:
            print("  %.1f MiB written (%d files completed)" % (written / (1 << 20), done), flush=True)
            next_report = now + 2

    exefs, romfs = nx.parts(root)
    if exefs is None or romfs is None:
        raise SystemExit("NXAR root %d does not contain both exefs and romfs" % root)
    for part, directory in (("exefs", exefs), ("romfs", romfs)):
        if only and only != part:
            continue
        for rel, record in nx.walk(directory):
            size = nx.files[record][0]
            dst = nup.extraction_path(out, part, rel)
            if os.path.exists(dst) and os.path.getsize(dst) == size:
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".part"
            try:
                with open(tmp, "wb") as g:
                    nx.copy_file(record, g if quiet else ProgressSink(g, progress))
                os.replace(tmp, dst)
            except BaseException as error:
                with suppress(OSError):
                    os.unlink(tmp)
                raise
            done += 1
            total += size
    return done, total


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("nx")
    ap.add_argument("--extract", metavar="DIR")
    ap.add_argument("--build", help="select the filesystem root whose exefs/main build id starts with this hex prefix")
    ap.add_argument("--root", type=int, help="select an NXMF filesystem root index directly")
    ap.add_argument("--only", choices=("exefs", "romfs"))
    ap.add_argument("--verify", action="store_true", help="validate NXAR/NXMF/chunk bounds and file sizes without extracting")
    a = ap.parse_args()
    try:
        nx = Nxar(a.nx, strict=a.verify)
    except (OSError, ValueError, struct.error, UnicodeDecodeError, IndexError, SystemExit) as error:
        if not a.verify:
            raise
        print("BAD package: %s" % error)
        return 1
    try:
        print("%s: %.2f GB, %d filesystem roots, %d dirs, %d files, %d chunks" %
              (os.path.basename(a.nx), nx.file_size / 1e9, len(nx.roots), nx.nd, nx.nf, nx.chunk_count))
        for r in nx.roots:
            ex, ro = nx.parts(r)
            bid = nx.build_id(r)
            print("root %d: build %s%s" % (r, bid[:8] if bid else "unknown",
                                            "  exefs+romfs" if ex is not None and ro is not None else ""))
        root = nx.pick_root(a.build, a.root)
        if a.verify:
            print("verified NXAR structure; selected root %d (build %s)" % (root, (nx.build_id(root) or "unknown")[:8]))
            return 0
        if not a.extract:
            return 0
        folder = os.path.realpath(a.extract)
        while not os.path.isdir(folder):
            parent = os.path.dirname(folder)
            if parent == folder:
                break
            folder = parent
        free = shutil.disk_usage(folder).free
        print("extracting root %d (build %s) to %s (%.0f GB free)" %
              (root, (nx.build_id(root) or "unknown")[:8], a.extract, free / 1e9))
        n, total = extract(nx, root, a.extract, a.only)
        print("done: %d files written, %.2f GB" % (n, total / 1e9))
        if a.only != "romfs":
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import nup
            import unpack
            for m in unpack.NAMES:
                p = nup.extraction_path(a.extract, "exefs", m, temporary_suffix=".plain")
                if os.path.exists(p) and unpack.unpack_nso(p):
                    print("  %s: ZBIC -> plain NSO" % m)
        return 0
    finally:
        nx.f.close()


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
