// The install page's channel picker (repo-docs/format-install.ts): the download buttons take the chosen channel's
// launcher, /download/launcher/<channel>/<os>, or with no channel /download/launcher/<os>, the best there is.

/** A launcher download link moved to a channel ('' for the best there is); any other link as it was */
export function launcherHref(href: string, channel: string) {
  return href.replace(/^(\/download\/launcher\/)(?:(?:stable|rc|nightly)\/)?(windows|windows-portable|linux)$/,
    (_, base, os) => base + (channel ? channel + '/' : '') + os);
}

interface LauncherRelease { tag: string; downloads: Record<string, string>; sizes?: Record<string, number>; url?: string }
interface LauncherVersions { bestChannel: string | null; channels: Record<string, LauncherRelease | null> }

/** Reject malformed metadata instead of showing a version beside unrelated download links. */
export function validateLauncherVersions(value: any): LauncherVersions {
  const channels = ['stable', 'rc', 'nightly'];
  if (!value || (value.bestChannel !== null && !channels.includes(value.bestChannel)) || !value.channels) throw new Error('Invalid launcher versions');
  for (const channel of channels) {
    const release = value.channels[channel];
    if (release === null) continue;
    if (!release || typeof release.tag !== 'string' || !release.tag.trim() || !release.downloads || typeof release.downloads !== 'object') throw new Error('Invalid launcher release');
    for (const [kind, href] of Object.entries(release.downloads)) {
      if (!['windows', 'windows-portable', 'linux'].includes(kind) || typeof href !== 'string') throw new Error('Invalid launcher file');
      const url = new URL(href);
      if (url.protocol !== 'https:' || !['git.magicbean.dev', 'git-cdn.magicbean.dev'].includes(url.hostname) || url.username || url.password || url.port) throw new Error('Invalid launcher URL');
    }
  }
  if (value.bestChannel && !value.channels[value.bestChannel]) throw new Error('Missing best launcher release');
  for (const release of Object.values(value.channels) as (LauncherRelease | null)[]) {
    if (release?.sizes && Object.entries(release.sizes).some(([kind, size]) => !['windows', 'windows-portable', 'linux'].includes(kind) || !Number.isSafeInteger(size) || size <= 0)) throw new Error('Invalid launcher size');
    if (release?.url) {
      const url = new URL(release.url);
      if (url.origin !== 'https://git.magicbean.dev' || !url.pathname.startsWith('/MagicBeanDev/HookshotLauncher/releases/') || url.username || url.password) throw new Error('Invalid release URL');
    }
  }
  return value;
}

export function installLauncherChannel(document: Document, fetcher = fetch) {
  const root = document.querySelector<HTMLElement>('[data-launcher-channel]');
  if (!root) return;
  const links = [...(root.parentElement || document).querySelectorAll<HTMLAnchorElement>('.download-buttons a[href^="/download/launcher/"]')];
  const note = root.querySelector('[data-launcher-channel-note]');
  const version = root.parentElement?.querySelector('[data-launcher-version]');
  const originals = links.map(link => ({ link, href: link.getAttribute('href') || '', label: link.textContent || '' }));
  let versions: LauncherVersions | null = null;
  let changedByUser = false;
  const radios = [...root.querySelectorAll<HTMLInputElement>('input[type="radio"]')];
  const os = preferredPlatform(document.defaultView?.navigator.userAgent || '');
  const update = () => {
    const picked = root.querySelector<HTMLInputElement>('input:checked');
    if (!picked && !versions) return;
    const channel = picked?.value || versions?.bestChannel;
    const release = channel && versions?.channels[channel];
    for (const { link, href, label } of originals) {
      const kind = href.split('/').at(-1)!;
      const download = release && release.downloads[kind];
      if (versions && !download) {
        link.removeAttribute('href');
        link.setAttribute('role', 'link');
        link.setAttribute('tabindex', '-1');
        link.setAttribute('aria-disabled', 'true');
        link.textContent = `${label} — unavailable`;
      } else {
        // Pin each link to the displayed release: a new publication cannot change it after reading the version.
        link.setAttribute('href', download || launcherHref(href, changedByUser ? picked?.value || '' : ''));
        link.removeAttribute('aria-disabled');
        link.removeAttribute('role');
        link.removeAttribute('tabindex');
        const size = release && release.sizes?.[kind];
        const format = kind === 'linux' ? 'AppImage' : kind === 'windows-portable' ? 'ZIP' : 'EXE';
        link.textContent = label;
        if (size) {
          const detail = document.createElement('small');
          detail.textContent = `${format} · ${Math.round(size / 1048576)} MB`;
          link.append(detail);
        }
        link.classList.toggle('primary', os ? kind === os : kind !== 'windows-portable');
      }
    }
    if (note) note.textContent = picked?.dataset.note || 'The recommended channel is chosen when you download.';
    if (version && versions) version.textContent = release
      ? `Available now: Hookshot Launcher ${release.tag}`
      : 'No launcher release is available for this channel yet.';
  };
  root.addEventListener('change', () => { changedByUser = true; update(); });
  // Channel routes work even when metadata fails or this is a static preview.
  root.hidden = false;
  for (const radio of radios) radio.disabled = false;
  update();
  if (!version) return;
  version.textContent = 'Checking the current launcher version…';
  return fetcher('/download/launcher/versions.json', { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(10000) })
    .then(response => {
      if (!response.ok) throw new Error('Launcher versions unavailable');
      return response.json();
    })
    .then(data => {
      versions = validateLauncherVersions(data);
      for (const radio of radios) {
        const channel = radio.value || versions.bestChannel;
        radio.disabled = !channel || !versions.channels[channel];
        const availability = radio.parentElement?.querySelector('small');
        if (availability) availability.textContent = radio.disabled ? 'unavailable' : '';
        if (!changedByUser) radio.checked = radio.value === versions.bestChannel;
      }
      root.hidden = false;
      update();
    })
    .catch(() => { version.textContent = 'Version information is unavailable. Try refreshing this page.'; });
}

/** Only suggest a desktop platform; phones, tablets and unsupported systems keep both choices. */
export function preferredPlatform(userAgent: string): 'windows' | 'linux' | null {
  if (/Android|iPhone|iPad|CrOS/i.test(userAgent)) return null;
  if (/Windows/i.test(userAgent)) return 'windows';
  return /Linux|X11/i.test(userAgent) ? 'linux' : null;
}

export async function installLauncherStatus(document: Document, fetcher = fetch) {
  // (the front page shows it twice: under the hero and in the release section's version numbers)
  const statuses = [...document.querySelectorAll<HTMLElement>('[data-launcher-status]')];
  if (!statuses.length) return;
  try {
    const response = await fetcher('/download/launcher/versions.json', { signal: AbortSignal.timeout(10000) });
    if (!response.ok) return;
    const versions = validateLauncherVersions(await response.json());
    const channel = versions.bestChannel;
    const release = channel && versions.channels[channel];
    const text = release
      ? `Hookshot Launcher ${release.tag} · ${channel === 'stable' ? 'stable' : channel === 'rc' ? 'release candidate' : 'nightly'}`
      : 'No launcher release is available yet.';
    for (const status of statuses) status.textContent = text;
  } catch { /* Keep the working download-page link when metadata cannot be reached. */ }
}
