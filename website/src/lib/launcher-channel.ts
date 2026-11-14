// The install page's channel picker (repo-docs/format-install.ts): the download buttons take the chosen channel's
// launcher, /download/launcher/<channel>/<os>, or with no channel /download/launcher/<os>, the best there is.

/** A launcher download link moved to a channel ('' for the best there is); any other link as it was */
export function launcherHref(href: string, channel: string) {
  return href.replace(/^(\/download\/launcher\/)(?:(?:stable|rc|nightly)\/)?(windows|windows-portable|linux)$/,
    (_, base, os) => base + (channel ? channel + '/' : '') + os);
}

export function installLauncherChannel(document: Document) {
  const root = document.querySelector<HTMLElement>('[data-launcher-channel]');
  if (!root) return;
  const links = [...(root.parentElement || document).querySelectorAll<HTMLAnchorElement>('.download-buttons a[href^="/download/launcher/"]')];
  const note = root.querySelector('[data-launcher-channel-note]');
  const update = () => {
    const picked = root.querySelector<HTMLInputElement>('input:checked');
    if (!picked) return;
    for (const link of links) link.setAttribute('href', launcherHref(link.getAttribute('href') || '', picked.value));
    if (note) note.textContent = picked.dataset.note || '';
  };
  root.addEventListener('change', update);
  root.hidden = false;
  // (a page restored from history keeps the radio it had)
  update();
}
