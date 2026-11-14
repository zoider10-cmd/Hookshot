# (Mako) From Project ReLink (github.com/pixl27/ProjectReLink, GPL-3.0, tools/dump_check.py), unchanged but this line.
# The zstd frame structure of .zs files, without decompressing: header fields, then every block header walked to the end.
# A file is sound when its last block carries the last-block flag and the frame (plus its checksum) ends where the file ends.
#   python -I tools/dump_check.py <file or folder> [...]      (a folder: every *.zs in it, only the unsound ones printed, and a count)
import os, struct, sys

def check(path):
    with open(path, 'rb') as f:
        b = f.read()
    n = len(b)
    if n < 6 or b[:4] != b'\x28\xb5\x2f\xfd':
        return False, 'no zstd magic', {}
    fhd = b[4]
    fcs_flag, single, checksum, did_flag = fhd >> 6, (fhd >> 5) & 1, (fhd >> 2) & 1, fhd & 3
    p = 5
    if not single:
        p += 1
    did_size = (0, 1, 2, 4)[did_flag]
    did = int.from_bytes(b[p:p + did_size], 'little') if did_size else None
    p += did_size
    fcs_size = (1 if single else 0, 2, 4, 8)[fcs_flag]
    fcs = int.from_bytes(b[p:p + fcs_size], 'little') if fcs_size else None
    if fcs_size == 2:
        fcs += 256
    p += fcs_size
    info = {'size': n, 'content': fcs, 'dict': did, 'checksum': checksum, 'blocks': 0}
    while True:
        if p + 3 > n:
            return False, 'block header past the end of the file (at %d of %d)' % (p, n), info
        h = b[p] | b[p + 1] << 8 | b[p + 2] << 16
        last, typ, size = h & 1, (h >> 1) & 3, h >> 3
        p += 3
        info['blocks'] += 1
        if typ == 3:
            return False, 'reserved block type at %d' % (p - 3), info
        p += 1 if typ == 1 else size
        if p > n:
            return False, 'block %d runs %d bytes past the end of the file' % (info['blocks'], p - n), info
        if last:
            break
    if checksum:
        p += 4
    if p != n:
        return False, 'frame ends at %d, file has %d bytes' % (p, n), info
    return True, 'sound', info


def main():
    bad = total = 0
    for arg in sys.argv[1:]:
        if os.path.isdir(arg):
            for root, dirs, files in os.walk(arg):
                dirs.sort()
                for name in sorted(files):
                    if not name.endswith('.zs'):
                        continue
                    total += 1
                    ok, why, info = check(os.path.join(root, name))
                    if not ok:
                        bad += 1
                        print('UNSOUND %s: %s %s' % (os.path.relpath(os.path.join(root, name), arg), why, info))
        else:
            total += 1
            ok, why, info = check(arg)
            bad += not ok
            print('%s %s: %s %s' % ('sound  ' if ok else 'UNSOUND', os.path.basename(arg), why, info))
    print('%d file(s), %d unsound' % (total, bad))


if __name__ == '__main__':
    main()
