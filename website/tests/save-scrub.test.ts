// The save scrubber (src/lib/save-scrub.ts) against scripts/hookshot_saves.py scrub, the script it ports: the same
// made-up saves (tests/test_hookshot_saves.py's caption() and picture_jpeg()) scrubbed by both must come out byte for
// byte the same, and what the script refuses, the page refuses. Made-up files only, in a temporary folder.
import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  ScrubError, captionDateProblem, captionLayout, crc32, findSlots, greyJpeg, jpegIsMidGrey, jpegSize, scrubSlot, zipStored,
} from '../src/lib/save-scrub.ts';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const python = process.platform === 'win32' ? 'python' : 'python3';

// Runs Python with the script and its tests' helpers loaded as `oot` and `t`.
function py(code: string, ...args: string[]): string {
  const prelude = `
import importlib.util, sys
from pathlib import Path
root = Path(sys.argv[1])
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, root / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
t = load("test_hookshot_saves", "tests/test_hookshot_saves.py")
oot = t.oot
`;
  return execFileSync(python, ['-I', '-B', '-c', prelude + code, root, ...args], { encoding: 'utf8' });
}

const dir = await mkdtemp(path.join(tmpdir(), 'save-scrub-test-'));
test.after(() => rm(dir, { recursive: true, force: true }));

// A made-up profile with slot_02, and the script's scrub of it into scrubbed/.
py(`
src = Path(sys.argv[2]) / "profile"
(src / "slot_02").mkdir(parents=True)
(src / "slot_02" / "progress.sav").write_bytes(t.PROGRESS)
(src / "slot_02" / "caption.sav").write_bytes(t.caption(t.picture_jpeg(543, 306)))
(Path(sys.argv[2]) / "bad-key.sav").write_bytes(t.caption(t.picture_jpeg(64, 32), more=[("day", 400)]))
(Path(sys.argv[2]) / "no-month.sav").write_bytes(t.caption(t.picture_jpeg(64, 32),
    date_at={k: v for k, v in t.DATE_AT.items() if k != "month"}))
(Path(sys.argv[2]) / "grey-33x17.jpg").write_bytes(oot.grey_jpeg(33, 17))
(Path(sys.argv[2]) / "grey-543x306.jpg").write_bytes(oot.grey_jpeg(543, 306))
(Path(sys.argv[2]) / "grey-543x306-l200.jpg").write_bytes(oot.grey_jpeg(543, 306, 200))
import contextlib, io
with contextlib.redirect_stdout(io.StringIO()):
    oot.scrub(str(src), "02", str(Path(sys.argv[2]) / "scrubbed" / "test-save"))
`, dir);
const read = (file: string) => readFile(path.join(dir, file)).then(b => new Uint8Array(b));

test('a slot scrubbed here is byte for byte the script\'s', async () => {
  const progress = await read('profile/slot_02/progress.sav'), caption = await read('profile/slot_02/caption.sav');
  const out = scrubSlot(progress, caption);
  assert.deepEqual(out.caption, await read('scrubbed/test-save/slot_00/caption.sav'));
  assert.deepEqual(out.progress, await read('scrubbed/test-save/slot_00/progress.sav'));
  assert.equal(out.savedAt, '2026-11-14 09:41:07');
  assert.equal(out.scene, 'TestScene');
  assert.equal(out.map, 'TestScene/Room_1');
  assert(out.changes.includes('caption.sav: the save date (month at 280): 11 -> 1'));
  assert.equal(captionDateProblem(out.caption), null);
  assert.equal(jpegIsMidGrey(captionLayout(out.caption).jpeg), null);
  // The inputs are left as they were.
  assert.deepEqual(caption, await read('profile/slot_02/caption.sav'));
  // Scrubbing a scrubbed save changes nothing more.
  assert.deepEqual(scrubSlot(out.progress, out.caption).caption, out.caption);
});

test('the grey JPEG is the script\'s, and reads back flat', async () => {
  for (const [w, h, level, file] of [[33, 17, 128, 'grey-33x17.jpg'], [543, 306, 128, 'grey-543x306.jpg'],
    [543, 306, 200, 'grey-543x306-l200.jpg']] as const) {
    const jpeg = greyJpeg(w, h, level);
    assert.deepEqual(jpeg, await read(file), file);
    assert.deepEqual(jpegSize(jpeg), [w, h]);
    assert.equal(jpegIsMidGrey(jpeg) === null, level === 128, file);
  }
});

test('a real picture is not taken for grey', async () => {
  const caption = await read('profile/slot_02/caption.sav');
  assert.match(jpegIsMidGrey(captionLayout(caption).jpeg) ?? '', /not flat mid-grey \(component 1 has detail\)/);
  assert.match(captionDateProblem(caption) ?? '', /not 2026-01-01 00:00:00 \(month 11, day 14, hour 9, minute 41, second 7\)/);
});

test('what the script refuses is refused', async () => {
  const progress = await read('profile/slot_02/progress.sav');
  const refused = (caption: Uint8Array, why: RegExp) =>
    assert.throws(() => scrubSlot(progress, caption), (e: unknown) => e instanceof ScrubError && why.test(e.message));
  refused(await read('bad-key.sav'), /the date's day key 0xbd46f485 is 2 times in the header/);
  refused(await read('no-month.sav'), /the date's month key 0xdfd840d3 is not in the header/);
  const good = await read('profile/slot_02/caption.sav');
  const noMagic = new Uint8Array(good); noMagic[0] = 0;
  refused(noMagic, /no 04 03 02 01 magic/);
  refused(good.subarray(0, good.length - 1), /does not reach the end of the file/);
  const scene = new Uint8Array(good); scene[684] = 7;
  refused(scene, /no name at 684/);
  assert.throws(() => scrubSlot(new Uint8Array(), good), /progress\.sav is empty/);
});

test('slots are found by folder, and everything else is named and left out', () => {
  const f = (p: string) => ({ path: p, file: { size: 1, arrayBuffer: async () => new ArrayBuffer(1) } });
  const found = findSlots([f('save/account.sav'), f('save/option.sav'), f('save/slot_00/progress.sav'),
    f('save/slot_00/caption.sav'), f('save/slot_03/caption.sav'), f('save/slot_03/progress.sav'), f('save/slot_03/notes.txt')]);
  assert.deepEqual(found.slots.map(s => [s.label, !!s.progress, !!s.caption]), [['slot_00', true, true], ['slot_03', true, true]]);
  assert.deepEqual(found.ignored, ['save/account.sav', 'save/option.sav', 'save/slot_03/notes.txt']);
  const loose = findSlots([f('caption.sav'), f('progress.sav')]);
  assert.deepEqual(loose.slots.map(s => [s.label, !!s.progress, !!s.caption]), [['the files dropped', true, true]]);
  assert.deepEqual(findSlots([f('slot_01/caption.sav')]).slots.map(s => [!!s.progress, !!s.caption]), [[false, true]]);
});

test('the zip is one Python reads, with the entries and dates expected', async () => {
  assert.equal(crc32(new TextEncoder().encode('123456789')), 0xcbf43926);
  const zip = zipStored([{ name: 'a/README.md', data: new TextEncoder().encode('hi\n') },
    { name: 'a/slot_00/caption.sav', data: greyJpeg(8, 8) }]);
  await writeFile(path.join(dir, 't.zip'), zip);
  const listed = py(`
import zipfile, io
z = zipfile.ZipFile(io.BytesIO(Path(sys.argv[2]).read_bytes()))
assert z.testzip() is None
for i in z.infolist():
    print(i.filename, i.file_size, i.compress_type, i.date_time)
`, path.join(dir, 't.zip'));
  assert.equal(listed, `a/README.md 3 0 (2026, 1, 1, 0, 0, 0)\na/slot_00/caption.sav ${greyJpeg(8, 8).length} 0 (2026, 1, 1, 0, 0, 0)\n`);
});
