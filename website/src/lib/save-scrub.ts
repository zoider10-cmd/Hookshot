// The save scrubber page (/saves/scrub/): scripts/hookshot_saves.py's `scrub`, in the browser. One slot of a save,
// scrubbed as that script does it and checked as its check-repo-saves does: caption.sav's picture made a flat
// mid-grey JPEG of the same size, its six date fields set to 2026-01-01 00:00:00, progress.sav copied unchanged. The
// layout, the keys and the JPEG writer and reader are the script's (docs/saves-script.md, "What scrub changes"); a
// file laid out any other way is refused, not guessed at. Nothing here touches the network: the files never leave
// the browser. tests/save-scrub.test.ts holds it to the script's output.

export class ScrubError extends Error {}
const fail = (message: string): never => { throw new ScrubError(message); };

// caption.sav (hookshot_saves.py: CAPTION_*): the magic 04 03 02 01; the scene's and the map's names at 684 and 748
// (up to 64 printable characters, NUL-ended); 1392 at 540; the JPEG's length at 1392; the JPEG from 1396 to the end.
export const CAPTION_MAGIC = [0x04, 0x03, 0x02, 0x01];
export const CAPTION_SCENE = 684, CAPTION_MAP = 748, CAPTION_NAME_LEN = 64;
export const CAPTION_CHECK = 540, CAPTION_JPEG_LEN = 1392, CAPTION_JPEG = 1396;
export const CAPTION_DATE_KEYS = [['year', 0x9811a3f7], ['month', 0xdfd840d3], ['day', 0xbd46f485],
  ['hour', 0x23f3d75e], ['minute', 0x27853bf7], ['second', 0x5ee50bed]] as const;
export type DateField = typeof CAPTION_DATE_KEYS[number][0];
export const SCRUB_DATE: Record<DateField, number> = { year: 2026, month: 1, day: 1, hour: 0, minute: 0, second: 0 };
// (what a save file may weigh to be read at all, and what each scrubbed file may weigh in the repository)
export const MAX_SAVE_FILE = 4 << 20;
export const REPO_CAPS = { 'progress.sav': 512 << 10, 'caption.sav': 16 << 10 } as const;
export const REPO_SAVE_NAME = /^[a-z0-9][a-z0-9-]{0,47}$/;
export const SLOT = /^slot_\d{2,3}$/;

const u32le = (data: Uint8Array, offset: number) =>
  (data[offset] | data[offset + 1] << 8 | data[offset + 2] << 16 | data[offset + 3] << 24) >>> 0;
const putU32le = (data: Uint8Array, offset: number, value: number) => {
  for (let i = 0; i < 4; i++) data[offset + i] = value >>> 8 * i & 0xff;
};
const u16be = (data: Uint8Array, offset: number) => data[offset] << 8 | data[offset + 1];
const concat = (...parts: (Uint8Array | number[])[]) => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
};
const equal = (a: Uint8Array, b: Uint8Array) => a.length === b.length && a.every((v, i) => v === b[i]);

// -- caption.sav --

function captionText(data: Uint8Array, offset: number): string {
  const raw = data.subarray(offset, offset + CAPTION_NAME_LEN);
  const end = raw.indexOf(0);
  const text = end < 0 ? raw : raw.subarray(0, end);
  if (text.some(c => c < 0x20 || c > 0x7e)) fail(`not the caption.sav layout understood: no name at ${offset}`);
  return String.fromCharCode(...text);
}

export interface CaptionLayout { scene: string; map: string; jpeg: Uint8Array; width: number; height: number }

export function captionLayout(data: Uint8Array): CaptionLayout {
  if (data.length < CAPTION_JPEG + 4 || CAPTION_MAGIC.some((b, i) => data[i] !== b))
    fail('not the caption.sav layout understood: no 04 03 02 01 magic');
  if (u32le(data, CAPTION_CHECK) !== CAPTION_JPEG_LEN)
    fail(`not the caption.sav layout understood: ${u32le(data, CAPTION_CHECK)} at ${CAPTION_CHECK}, not ${CAPTION_JPEG_LEN}`);
  const size = u32le(data, CAPTION_JPEG_LEN);
  if (CAPTION_JPEG + size !== data.length)
    fail(`not the caption.sav layout understood: the JPEG's length at ${CAPTION_JPEG_LEN} (${size}) does not reach the end ` +
      `of the file (${data.length - CAPTION_JPEG} bytes after ${CAPTION_JPEG})`);
  const jpeg = data.subarray(CAPTION_JPEG);
  if (jpeg[0] !== 0xff || jpeg[1] !== 0xd8 || jpeg[jpeg.length - 2] !== 0xff || jpeg[jpeg.length - 1] !== 0xd9)
    fail(`not the caption.sav layout understood: no JPEG at ${CAPTION_JPEG}`);
  const [width, height] = jpegSize(jpeg);
  return { scene: captionText(data, CAPTION_SCENE), map: captionText(data, CAPTION_MAP), jpeg, width, height };
}

/** {field: [entry offset, value]} of the six date entries: each key exactly once before 1392, all on one 8-byte grid. */
export function captionDates(data: Uint8Array): Record<DateField, [number, number]> {
  const header = data.subarray(0, CAPTION_JPEG_LEN);
  const found = {} as Record<DateField, [number, number]>;
  for (const [field, key] of CAPTION_DATE_KEYS) {
    const offsets: number[] = [];
    for (let at = 0; at + 4 <= header.length; at++) if (u32le(header, at) === key) offsets.push(at);
    if (offsets.length !== 1 || offsets[0] + 8 > header.length) {
      const how = offsets.length > 1 ? `${offsets.length} times` : offsets.length ? 'not whole' : 'not';
      fail(`not the caption.sav layout understood: the date's ${field} key 0x${key.toString(16).padStart(8, '0')} is ` +
        `${how} in the header (before ${CAPTION_JPEG_LEN})`);
    }
    found[field] = [offsets[0], u32le(header, offsets[0] + 4)];
  }
  if (new Set(Object.values(found).map(([o]) => o % 8)).size !== 1)
    fail('not the caption.sav layout understood: the date\'s entries are not 8-byte aligned with each other (' +
      Object.entries(found).map(([f, [o]]) => `${f} at ${o}`).join(', ') + ')');
  return found;
}

export function captionDateProblem(data: Uint8Array): string | null {
  let dates;
  try { dates = captionDates(data); } catch (e) { if (e instanceof ScrubError) return e.message; throw e; }
  const wrong = Object.entries(dates).filter(([f, [, v]]) => v !== SCRUB_DATE[f as DateField]).map(([f, [, v]]) => `${f} ${v}`);
  return wrong.length ? `the save date is not 2026-01-01 00:00:00 (${wrong.join(', ')}): not scrubbed` : null;
}

// -- JPEG: the size of any baseline or progressive one, a flat grey baseline one written, a baseline one's
// coefficients read back to tell that every block is flat (no picture in it) --

function* jpegSegments(jpeg: Uint8Array): Generator<[number, Uint8Array, number]> {
  if (jpeg[0] !== 0xff || jpeg[1] !== 0xd8) fail('not a JPEG');
  let i = 2;
  for (;;) {
    if (i + 4 > jpeg.length || jpeg[i] !== 0xff) fail(`not a JPEG: no marker at ${i}`);
    const marker = jpeg[i + 1];
    if (marker === 0xff) { i++; continue; }   // (fill bytes)
    const length = u16be(jpeg, i + 2);
    if (length < 2 || i + 2 + length > jpeg.length) fail('not a JPEG: a segment runs past the end');
    yield [marker, jpeg.subarray(i + 4, i + 2 + length), i + 2 + length];
    if (marker === 0xda) return;
    i += 2 + length;
  }
}

export function jpegSize(jpeg: Uint8Array): [number, number] {
  for (const [marker, payload] of jpegSegments(jpeg)) {
    if (marker === 0xc0 || marker === 0xc1 || marker === 0xc2) {
      if (payload.length < 6) break;
      const height = u16be(payload, 1), width = u16be(payload, 3);
      if (!width || !height) break;
      return [width, height];
    }
  }
  return fail('not a JPEG this understands: no frame size');
}

// ITU T.81 Annex K: the example quantization tables and the standard Huffman tables (counts by length, then values)
const ZIGZAG = [0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7,
  14, 21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61,
  54, 47, 55, 62, 63];
const QUANT_LUMA = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56, 14,
  17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92, 49, 64, 78, 87, 103,
  121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99];
const QUANT_CHROMA = [17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99, 24, 26, 56, 99, 99, 99, 99, 99, 47,
  66, 99, 99, 99, 99, 99, 99, ...Array(32).fill(99)];
const hex = (s: string) => Array.from({ length: s.length / 2 }, (_, i) => parseInt(s.slice(2 * i, 2 * i + 2), 16));
type Table = [number[], number[]];
const range = (n: number) => Array.from({ length: n }, (_, i) => i);
export const DC_LUMA: Table = [[0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0], range(12)];
export const DC_CHROMA: Table = [[0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0], range(12)];
export const AC_LUMA: Table = [[0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7d], hex(
  '01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a' +
  '434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9' +
  'aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9fa')];
export const AC_CHROMA: Table = [[0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77], hex(
  '000102031104052131061241510761711322328108144291a1b1c109233352f0156272d10a162434e125f11718191a262728292a3536373839' +
  '3a434445464748494a535455565758595a636465666768696a737475767778797a82838485868788898a92939495969798999aa2a3a4a5a6a7' +
  'a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9fa')];

/** {value: [code, length]} from a table's counts and values (T.81 Annex C). */
export function huffmanCodes(counts: ArrayLike<number>, values: ArrayLike<number>): Map<number, [number, number]> {
  const codes = new Map<number, [number, number]>();
  let code = 0, k = 0;
  for (let length = 1; length <= 16; length++) {
    for (let n = 0; n < counts[length - 1]; n++) codes.set(values[k++], [code++, length]);
    code <<= 1;
  }
  return codes;
}

const segment = (marker: number, payload: number[]) =>
  [0xff, marker, (payload.length + 2) >> 8, (payload.length + 2) & 0xff, ...payload];
const bitLength = (n: number) => n ? 32 - Math.clz32(n) : 0;
const roundHalfEven = (x: number) => { const r = Math.round(x); return Math.abs(x % 1) === 0.5 && r % 2 ? r - 1 : r; };

/** A baseline JPEG of width x height, every pixel grey `level`: YCbCr 4:2:0, the Annex K tables, each block one DC
 * value and no AC. Byte for byte hookshot_saves.py's grey_jpeg. */
export function greyJpeg(width: number, height: number, level = 128): Uint8Array {
  if (!(width > 0 && width < 65536 && height > 0 && height < 65536 && level >= 0 && level <= 255))
    fail('grey_jpeg: a size of 1..65535 and a level of 0..255');
  const out: number[] = [0xff, 0xd8];
  out.push(...segment(0xe0, [...'JFIF'].map(c => c.charCodeAt(0)).concat([0, 1, 1, 0, 0, 1, 0, 1, 0, 0])));
  out.push(...segment(0xdb, [0, ...ZIGZAG.map(z => QUANT_LUMA[z])]));
  out.push(...segment(0xdb, [1, ...ZIGZAG.map(z => QUANT_CHROMA[z])]));
  out.push(...segment(0xc0, [8, height >> 8, height & 0xff, width >> 8, width & 0xff, 3, 1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1]));
  for (const [id, [counts, values]] of [[0x00, DC_LUMA], [0x10, AC_LUMA], [0x01, DC_CHROMA], [0x11, AC_CHROMA]] as const)
    out.push(...segment(0xc4, [id, ...counts, ...values]));
  out.push(...segment(0xda, [3, 1, 0x00, 2, 0x11, 3, 0x11, 0, 63, 0]));
  const dc = [huffmanCodes(...DC_LUMA), huffmanCodes(...DC_CHROMA)];
  const eob = [huffmanCodes(...AC_LUMA).get(0)!, huffmanCodes(...AC_CHROMA).get(0)!];
  const lumaDc = roundHalfEven((level - 128) * 8 / QUANT_LUMA[0]);
  let bits = 0, nbits = 0;
  const put = (code: number, length: number) => {
    bits = bits * 2 ** length + code;
    nbits += length;
    while (nbits >= 8) {
      nbits -= 8;
      const byte = Math.floor(bits / 2 ** nbits) & 0xff;
      out.push(byte);
      if (byte === 0xff) out.push(0);   // (byte stuffing)
    }
    bits %= 2 ** nbits;
  };
  const block = (table: number, diff: number) => {
    const size = bitLength(Math.abs(diff));
    put(...dc[table].get(size)!);
    if (size) put(diff > 0 ? diff : diff + (1 << size) - 1, size);
    put(...eob[table]);
  };
  let first = true;
  const mcus = Math.ceil(height / 16) * Math.ceil(width / 16);
  for (let m = 0; m < mcus; m++) {
    for (let y = 0; y < 4; y++) { block(0, first ? lumaDc : 0); first = false; }
    block(1, 0);
    block(1, 0);
  }
  if (nbits) put((1 << (8 - nbits)) - 1, 8 - nbits);   // (padded with ones)
  out.push(0xff, 0xd9);
  return Uint8Array.from(out);
}

/** A baseline JPEG's scan read to its coefficients: {component id: [DC values, whether any block has an AC
 * coefficient]}. Refuses progressive, restart intervals, several scans, a short scan or data after it. */
export function jpegBlocks(jpeg: Uint8Array): Map<number, [number[], boolean]> {
  const tables = new Map<number, Map<string, number>>();
  let frame: [number, number, [number, number, number][]] | null = null;
  let scan: [number, number, number][] | null = null, end = 0;
  for (const [marker, payload, after] of jpegSegments(jpeg)) {
    if (marker === 0xc4) {
      let p = 0;
      while (p < payload.length) {
        const counts = payload.subarray(p + 1, p + 17);
        const n = counts.reduce((a, b) => a + b, 0);
        if (counts.length < 16 || p + 17 + n > payload.length) fail('JPEG: a Huffman table runs past its segment');
        const codes = huffmanCodes(counts, payload.subarray(p + 17, p + 17 + n));
        tables.set(payload[p], new Map([...codes].map(([v, [code, length]]) => [`${length}:${code}`, v])));
        p += 17 + n;
      }
    } else if (marker === 0xc0) {
      if (payload.length < 6 || payload[0] !== 8 || payload.length !== 6 + 3 * payload[5])
        fail('JPEG: a frame header this does not read');
      frame = [u16be(payload, 3), u16be(payload, 1), range(payload[5]).map(k =>
        [payload[6 + 3 * k], payload[7 + 3 * k] >> 4, payload[7 + 3 * k] & 15] as [number, number, number])];
    } else if (marker >= 0xc1 && marker <= 0xc3 || marker >= 0xc5 && marker <= 0xcf && marker !== 0xc8) {
      fail('JPEG: not baseline');
    } else if (marker === 0xdd && u16be(payload, 0)) {
      fail('JPEG: restart intervals are not read here');
    } else if (marker === 0xda) {
      scan = range(payload[0]).map(k => [payload[1 + 2 * k], payload[2 + 2 * k] >> 4, payload[2 + 2 * k] & 15]);
      end = after;
    }
  }
  if (!frame || !scan) return fail('JPEG: no baseline frame or scan');
  const [width, height, comps] = frame;
  if (comps.map(c => c[0]).join() !== scan.map(s => s[0]).join())
    fail('JPEG: the scan does not hold every component (several scans)');
  if (comps.some(c => ![1, 2].includes(c[1]) || ![1, 2].includes(c[2]))) fail('JPEG: a sampling factor this does not read');
  const hmax = Math.max(...comps.map(c => c[1])), vmax = Math.max(...comps.map(c => c[2]));
  const [mcus, layout] = comps.length === 1
    ? [Math.ceil(width / 8) * Math.ceil(height / 8), [[comps[0][0], 1]]]
    : [Math.ceil(width / (8 * hmax)) * Math.ceil(height / (8 * vmax)), comps.map(c => [c[0], c[1] * c[2]])];
  const dcTab = new Map(scan.map(s => [s[0], tables.get(s[1])]));
  const acTab = new Map(scan.map(s => [s[0], tables.get(0x10 | s[2])]));
  if ([...dcTab.values(), ...acTab.values()].includes(undefined)) fail('JPEG: a Huffman table the scan uses is missing');
  let pos = end, acc = 0, have = 0;
  const bit = () => {
    if (!have) {
      if (pos >= jpeg.length) fail('JPEG: the scan ends early');
      const byte = jpeg[pos];
      if (byte === 0xff) {
        if (pos + 1 >= jpeg.length || jpeg[pos + 1] !== 0) fail('JPEG: the scan ends early');
        pos++;
      }
      pos++;
      acc = byte; have = 8;
    }
    have--;
    return acc >> have & 1;
  };
  const decode = (table: Map<string, number>) => {
    let code = 0;
    for (let length = 1; length <= 16; length++) {
      code = code << 1 | bit();
      const v = table.get(`${length}:${code}`);
      if (v !== undefined) return v;
    }
    return fail('JPEG: not a Huffman code');
  };
  const receive = (size: number) => {
    let v = 0;
    for (let i = 0; i < size; i++) v = v << 1 | bit();
    return v >= 1 << size - 1 ? v : v - (1 << size) + 1;
  };
  const out = new Map<number, [number[], boolean]>(layout.map(([c]) => [c, [[], false]]));
  const pred = new Map(layout.map(([c]) => [c, 0]));
  for (let m = 0; m < mcus; m++) {
    for (const [c, count] of layout) {
      for (let b = 0; b < count; b++) {
        const size = decode(dcTab.get(c)!);
        if (size > 11) fail('JPEG: a DC difference out of range');
        pred.set(c, pred.get(c)! + (size ? receive(size) : 0));
        out.get(c)![0].push(pred.get(c)!);
        let k = 1, ac = false;
        while (k < 64) {
          const rs = decode(acTab.get(c)!);
          const run = rs >> 4, sz = rs & 15;
          if (!sz) { if (run !== 15) break; k += 16; continue; }
          k += run;
          if (k > 63) fail('JPEG: an AC coefficient past the block');
          if (receive(sz)) ac = true;
          k++;
        }
        if (ac) out.get(c)![1] = true;
      }
    }
  }
  const rest = jpeg.subarray(pos);
  if (!(rest.length === 2 && rest[0] === 0xff && rest[1] === 0xd9)) {
    const endsRight = rest.length >= 2 && rest[rest.length - 2] === 0xff && rest[rest.length - 1] === 0xd9;
    fail(`JPEG: ${endsRight ? rest.length - 2 : rest.length} byte(s) after the scan, not just its end`);
  }
  return out;
}

/** null when jpeg is a flat mid-grey picture (every coefficient of every block 0), else why not. */
export function jpegIsMidGrey(jpeg: Uint8Array): string | null {
  let blocks;
  try { blocks = jpegBlocks(jpeg); } catch (e) { if (e instanceof ScrubError) return e.message; throw e; }
  for (const [c, [dcs, ac]] of [...blocks].sort((a, b) => a[0] - b[0]))
    if (ac || dcs.some(Boolean)) return `the picture is not flat mid-grey (component ${c} has ${ac ? 'detail' : 'another shade'})`;
  return null;
}

// -- the scrub --

export interface Scrubbed {
  progress: Uint8Array; caption: Uint8Array; changes: string[];
  scene: string; map: string; savedAt: string;
}

/** What the save date reads, as YYYY-MM-DD HH:MM:SS (for telling slots apart before scrubbing). */
export function captionSavedAt(caption: Uint8Array): string {
  const d = captionDates(caption);
  const p = (f: DateField, n = 2) => String(d[f][1]).padStart(n, '0');
  return `${p('year', 4)}-${p('month')}-${p('day')} ${p('hour')}:${p('minute')}:${p('second')}`;
}

/** One slot's progress.sav and caption.sav, scrubbed as hookshot_saves.py scrub does: the same bytes, the same
 * change lines. Throws ScrubError, with nothing made, when any step is refused. The inputs are not changed. */
export function scrubSlot(progress: Uint8Array, caption: Uint8Array): Scrubbed {
  for (const [name, data] of [['progress.sav', progress], ['caption.sav', caption]] as const) {
    if (!data.length) fail(`${name} is empty`);
    if (data.length > MAX_SAVE_FILE) fail(`${name} is ${data.length} bytes: larger than any save file, refused`);
  }
  const before = captionLayout(caption);
  const savedAt = captionSavedAt(caption);
  const cap = new Uint8Array(caption);
  const changes = ['no player name to set: this game\'s saves show none (the Load screen: picture, date, place, hearts)'];
  for (const [field, [offset, old]] of Object.entries(captionDates(cap)) as [DateField, [number, number]][]) {
    putU32le(cap, offset + 4, SCRUB_DATE[field]);
    changes.push(`caption.sav: the save date (${field} at ${offset}): ${old} -> ${SCRUB_DATE[field]}`);
  }
  const { width, height } = before;
  if (width > 2048 || height > 2048) fail(`caption.sav's picture is ${width}x${height}: larger than a file-select picture, refused`);
  const grey = greyJpeg(width, height);
  const length = new Uint8Array(4);
  putU32le(length, 0, grey.length);
  const out = concat(cap.subarray(0, CAPTION_JPEG_LEN), length, grey);
  if (!equal(captionLayout(out).jpeg, grey) || jpegIsMidGrey(grey) || captionDateProblem(out))
    fail('the scrubbed caption.sav did not read back: nothing was made');
  changes.push(`caption.sav: the picture at ${CAPTION_JPEG} (JPEG ${width}x${height}, ${before.jpeg.length} bytes) replaced ` +
    `by a mid-grey JPEG ${width}x${height} of ${grey.length} bytes`);
  changes.push(`caption.sav: the JPEG's length at ${CAPTION_JPEG_LEN}: ${before.jpeg.length} -> ${grey.length}`);
  changes.push(`caption.sav: ${caption.length} -> ${out.length} bytes; the rest of its header kept as it was ` +
    `(scene ${before.scene || '-'}, map ${before.map || '-'})`);
  const files = { 'progress.sav': progress, 'caption.sav': out };
  for (const [name, data] of Object.entries(files))
    if (data.length > REPO_CAPS[name as keyof typeof REPO_CAPS])
      fail(`the scrubbed ${name} is ${data.length} bytes, over the ${REPO_CAPS[name as keyof typeof REPO_CAPS]} a repo save ` +
        'allows: nothing was made');
  changes.push('progress.sav: copied unchanged');
  changes.push('progress.sav, caption.sav: modification times set to 2026-01-01 00:00 (the files\' own; the Load screen\'s ' +
    'date is caption.sav\'s, above)');
  return { progress: new Uint8Array(progress), caption: out, changes, scene: before.scene, map: before.map, savedAt };
}

/** The README.md the script starts a repo save with: its first line is to be filled in. */
export const readmeTemplate = (name: string, slot: string) =>
  `${name}: <where the save stands, in one line>\n\nMade fresh for the Test Farm from ${slot} of a new profile; ` +
  'scrubbed with the website\'s save scrubber (hookshot_saves.py scrub).\n';

// -- picking the slots out of what was dropped --

export interface PickedFile { path: string; file: { size: number; arrayBuffer(): Promise<ArrayBuffer> } }
export interface FoundSlot { key: string; label: string; progress?: PickedFile; caption?: PickedFile }
export interface Found { slots: FoundSlot[]; ignored: string[] }

/** Groups dropped files (path relative to what was dropped, '/'-separated) by the folder each is in: a slot is a
 * folder with progress.sav and caption.sav (loose files are one slot). account.sav, option.sav and anything else are
 * left out, and named. */
export function findSlots(files: PickedFile[]): Found {
  const groups = new Map<string, FoundSlot>();
  const ignored: string[] = [];
  for (const f of files) {
    const parts = f.path.split('/').filter(Boolean);
    const name = parts.pop() ?? '';
    const key = parts.join('/');
    if (name !== 'progress.sav' && name !== 'caption.sav') { ignored.push(f.path); continue; }
    let slot = groups.get(key);
    if (!slot) groups.set(key, slot = { key, label: parts.at(-1) ?? 'the files dropped' });
    if (slot[name === 'progress.sav' ? 'progress' : 'caption']) ignored.push(f.path);
    else slot[name === 'progress.sav' ? 'progress' : 'caption'] = f;
  }
  const slots = [...groups.values()].sort((a, b) => a.key.localeCompare(b.key));
  return { slots, ignored };
}

// -- a zip of the scrubbed save (stored, no compression), its entries dated 2026-01-01 00:00 --

const CRC_TABLE = Uint32Array.from(range(256), n => {
  for (let k = 0; k < 8; k++) n = n & 1 ? 0xedb88320 ^ n >>> 1 : n >>> 1;
  return n >>> 0;
});
export function crc32(data: Uint8Array): number {
  let c = 0xffffffff;
  for (const b of data) c = CRC_TABLE[(c ^ b) & 0xff] ^ c >>> 8;
  return (c ^ 0xffffffff) >>> 0;
}

const DOS_DATE = (2026 - 1980) << 9 | 1 << 5 | 1, DOS_TIME = 0;

export function zipStored(entries: { name: string; data: Uint8Array }[]): Uint8Array {
  const enc = new TextEncoder();
  const locals: Uint8Array[] = [], centrals: Uint8Array[] = [];
  let offset = 0;
  for (const { name, data } of entries) {
    const n = enc.encode(name), crc = crc32(data);
    const head = (sig: number, central: boolean) => {
      const h = new DataView(new ArrayBuffer(central ? 46 : 30));
      let at = 0;
      const u16 = (v: number) => { h.setUint16(at, v, true); at += 2; };
      const u32 = (v: number) => { h.setUint32(at, v, true); at += 4; };
      u32(sig);
      if (central) u16(20);              // (made by: 2.0)
      u16(20); u16(0x0800); u16(0);      // (needed: 2.0; UTF-8 names; stored)
      u16(DOS_TIME); u16(DOS_DATE); u32(crc); u32(data.length); u32(data.length); u16(n.length); u16(0);
      if (central) { u16(0); u16(0); u16(0); u32(0); u32(offset); }
      return new Uint8Array(h.buffer);
    };
    const local = concat(head(0x04034b50, false), n, data);
    centrals.push(concat(head(0x02014b50, true), n));
    locals.push(local);
    offset += local.length;
  }
  const dir = concat(...centrals);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, entries.length, true); end.setUint16(10, entries.length, true);
  end.setUint32(12, dir.length, true); end.setUint32(16, offset, true);
  return concat(...locals, dir, new Uint8Array(end.buffer));
}
