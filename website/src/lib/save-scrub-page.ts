// The <save-scrubber> element of /saves/scrub/ (components/SaveScrubber.astro): files or a folder dropped or chosen,
// their slots listed, one scrubbed by save-scrub.ts and handed back as a zip. Everything stays in the browser; text
// from the files is shown with textContent only.
import {
  MAX_SAVE_FILE, REPO_SAVE_NAME, ScrubError, captionLayout, captionSavedAt, findSlots, readmeTemplate, scrubSlot, zipStored,
  type FoundSlot, type PickedFile,
} from './save-scrub.ts';

// (a dropped folder is walked to this many entries at most: a save folder holds a few dozen)
const MAX_ENTRIES = 2000;

interface Entry { isFile: boolean; isDirectory: boolean; name: string }
interface FileEntry extends Entry { file(ok: (f: File) => void, err: (e: unknown) => void): void }
interface DirEntry extends Entry { createReader(): { readEntries(ok: (e: Entry[]) => void, err: (e: unknown) => void): void } }

async function walk(entry: Entry, prefix: string, out: PickedFile[], budget: { left: number }): Promise<void> {
  if (--budget.left < 0) return;
  const at = prefix + entry.name;
  if (entry.isFile) {
    const file = await new Promise<File>((ok, err) => (entry as FileEntry).file(ok, err));
    out.push({ path: at, file });
  } else if (entry.isDirectory) {
    const reader = (entry as DirEntry).createReader();
    for (;;) {
      const batch = await new Promise<Entry[]>((ok, err) => reader.readEntries(ok, err));
      if (!batch.length || budget.left < 0) break;
      for (const e of batch) await walk(e, at + '/', out, budget);
    }
  }
}

const readBytes = async (f: PickedFile) => {
  if (f.file.size > MAX_SAVE_FILE) throw new ScrubError(`${f.path} is ${f.file.size} bytes: larger than any save file`);
  return new Uint8Array(await f.file.arrayBuffer());
};

interface Candidate { slot: FoundSlot; label: string; problem?: string }

export class SaveScrubber extends HTMLElement {
  #url = '';
  #candidates: Candidate[] = [];
  #q = <T extends Element>(s: string) => this.querySelector<T>(s)!;

  connectedCallback() {
    const drop = this.#q<HTMLElement>('[data-drop]');
    for (const input of this.querySelectorAll<HTMLInputElement>('input[type=file]')) {
      input.addEventListener('change', () => {
        const files = [...input.files ?? []].map(file => ({ path: file.webkitRelativePath || file.name, file }));
        input.value = '';
        void this.#load(files);
      });
    }
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.dataset.over = ''; });
    drop.addEventListener('dragleave', () => delete drop.dataset.over);
    drop.addEventListener('drop', e => {
      e.preventDefault();
      delete drop.dataset.over;
      // (the items are only readable during the event: take their entries now)
      const entries = [...e.dataTransfer?.items ?? []].map(i => i.webkitGetAsEntry?.() as Entry | null);
      if (entries.length && entries.every(Boolean)) {
        const out: PickedFile[] = [], budget = { left: MAX_ENTRIES };
        void Promise.all(entries.map(en => walk(en!, '', out, budget)))
          .then(() => this.#load(out, budget.left < 0), err => this.#error(`Couldn't read what was dropped (${err}).`));
      } else {
        void this.#load([...e.dataTransfer?.files ?? []].map(file => ({ path: file.name, file })));
      }
    });
    this.#q<HTMLFormElement>('form').addEventListener('submit', e => { e.preventDefault(); void this.#scrub(); });
    this.#q<HTMLElement>('[data-ready]').hidden = false;
  }

  #status(text: string, error = false) {
    const s = this.#q<HTMLElement>('[data-status]');
    s.textContent = text;
    s.classList.toggle('scrub-error', error);
  }
  #error(text: string) { this.#status(text, true); }

  async #load(files: PickedFile[], truncated = false) {
    this.#reset();
    const { slots, ignored } = findSlots(files);
    const left = this.#q<HTMLElement>('[data-ignored]');
    left.hidden = !ignored.length;
    left.textContent = ignored.length
      ? `Left out (only progress.sav and caption.sav are used; the game makes account.sav and option.sav itself): ` +
        ignored.slice(0, 12).join(', ') + (ignored.length > 12 ? ` and ${ignored.length - 12} more` : '') : '';
    if (!slots.length) {
      this.#error(truncated ? `No save found in the first ${MAX_ENTRIES} files: drop the save folder itself, or one slot.`
        : 'No save found: drop a slot folder (slot_00, slot_01…), the save folder holding them, or a slot\'s progress.sav and caption.sav.');
      return;
    }
    this.#candidates = await Promise.all(slots.map(async (slot): Promise<Candidate> => {
      if (!slot.progress || !slot.caption)
        return { slot, label: slot.label, problem: `has no ${slot.progress ? 'caption.sav' : 'progress.sav'}` };
      try {
        const caption = await readBytes(slot.caption);
        const { scene } = captionLayout(caption);
        return { slot, label: `${slot.label}: ${scene || 'no scene name'}, saved ${captionSavedAt(caption)}` };
      } catch (e) {
        if (e instanceof ScrubError) return { slot, label: slot.label, problem: e.message };
        throw e;
      }
    }));
    const list = this.#q<HTMLElement>('[data-slots]');
    const usable = this.#candidates.filter(c => !c.problem);
    this.#candidates.forEach((c, i) => {
      const row = document.createElement('label');
      const radio = Object.assign(document.createElement('input'), { type: 'radio', name: 'slot', value: String(i) });
      radio.disabled = !!c.problem;
      radio.checked = c === usable[0];
      const text = document.createElement('span');
      text.textContent = c.problem ? `${c.label}: can't be scrubbed: ${c.problem}` : c.label;
      row.append(radio, text);
      list.append(row);
    });
    this.#q<HTMLElement>('[data-pick]').hidden = false;
    this.#q<HTMLButtonElement>('[data-go]').disabled = !usable.length;
    this.#status(usable.length ? `Found ${usable.length === 1 ? 'one slot' : `${usable.length} slots`}: ` +
      (usable.length > 1 ? 'pick the one to scrub.' : 'name the save and scrub it.') : 'No slot here can be scrubbed.', !usable.length);
  }

  #reset() {
    if (this.#url) URL.revokeObjectURL(this.#url);
    this.#url = '';
    this.#candidates = [];
    this.#q<HTMLElement>('[data-slots]').replaceChildren();
    this.#q<HTMLElement>('[data-pick]').hidden = true;
    this.#q<HTMLElement>('[data-result]').hidden = true;
  }

  async #scrub() {
    const form = this.#q<HTMLFormElement>('form');
    const picked = this.#candidates[Number(new FormData(form).get('slot'))];
    const name = String(new FormData(form).get('name') ?? '').trim();
    if (!picked || picked.problem) return this.#error('Pick a slot first.');
    if (!REPO_SAVE_NAME.test(name)) return this.#error('The save\'s name: a–z, 0–9 and -, up to 48, starting with a letter or digit.');
    this.#q<HTMLElement>('[data-result]').hidden = true;
    try {
      const out = scrubSlot(await readBytes(picked.slot.progress!), await readBytes(picked.slot.caption!));
      const slot = /^slot_\d{2,3}$/.test(picked.slot.label) ? picked.slot.label : 'a slot';
      const zip = zipStored([
        { name: `${name}/README.md`, data: new TextEncoder().encode(readmeTemplate(name, slot)) },
        { name: `${name}/slot_00/progress.sav`, data: out.progress },
        { name: `${name}/slot_00/caption.sav`, data: out.caption },
      ]);
      if (this.#url) URL.revokeObjectURL(this.#url);
      this.#url = URL.createObjectURL(new Blob([zip], { type: 'application/zip' }));
      const link = this.#q<HTMLAnchorElement>('[data-download]');
      link.href = this.#url;
      link.download = `${name}.zip`;
      link.textContent = `Download ${name}.zip`;
      const changes = this.#q<HTMLElement>('[data-changes]');
      changes.replaceChildren(...[...out.changes, 'README.md: written from the template: fill in its first line']
        .map(line => Object.assign(document.createElement('li'), { textContent: line })));
      this.#q<HTMLElement>('[data-result]').hidden = false;
      this.#status(`Scrubbed ${picked.slot.label} as ${name}/slot_00.`);
    } catch (e) {
      if (!(e instanceof ScrubError)) throw e;
      this.#error(`Not scrubbed, nothing was made: ${e.message}.`);
    }
  }
}
