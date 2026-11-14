// The people behind Hookshot, for the team page: the authors of Hookshot's commits on Forgejo (Hookshot's history
// included), most commits first. Collected once per build, like the progress feed; if Forgejo can't be reached, the
// page says so. Merge commits are left out: they credit whoever merged, not who wrote the change.
import { REPOSITORY } from './progress.ts';

const API = `https://git.magicbean.dev/api/v1/repos/${REPOSITORY}`;
const PER_PAGE = 50;

export interface Contributor { name: string; avatar: string | null; profile: string | null; commits: number }

/** A Forgejo account if the commit's email belongs to one, else a GitHub account from its noreply address. */
function identify(commit: any): Omit<Contributor, 'commits'> & { key: string } {
  const user = commit.author;
  if (user?.login) {
    return { key: `forgejo:${user.login.toLowerCase()}`, name: user.full_name || user.login, avatar: user.avatar_url,
      profile: `https://git.magicbean.dev/${encodeURIComponent(user.login)}` };
  }
  const { name = 'Unknown', email = '' } = commit.commit?.author ?? {};
  const github = email.match(/^(?:(\d+)\+)?([A-Za-z0-9-]+)@users\.noreply\.github\.com$/i);
  if (github) {
    return { key: `github:${github[2].toLowerCase()}`, name: name || github[2],
      avatar: github[1] ? `https://avatars.githubusercontent.com/u/${github[1]}?s=112` : `https://github.com/${github[2]}.png?size=112`,
      profile: `https://github.com/${github[2]}` };
  }
  return { key: `email:${email.toLowerCase() || name}`, name, avatar: null, profile: null };
}

export async function collectContributors({ fetcher = fetch, maxPages = 200 } = {}): Promise<Contributor[]> {
  const people = new Map<string, Contributor>();
  for (let page = 1; page <= maxPages; page++) {
    const url = `${API}/commits?limit=${PER_PAGE}&page=${page}&stat=false&verification=false&files=false`;
    const response = await fetcher(url, { headers: { Accept: 'application/json', 'User-Agent': 'Hookshot-website' },
      signal: AbortSignal.timeout(20000), redirect: 'error' });
    if (!response.ok) throw new Error(`Forgejo commits: HTTP ${response.status}`);
    const commits = await response.json();
    if (!Array.isArray(commits)) throw new Error('Unexpected Forgejo response.');
    for (const commit of commits) {
      if ((commit.parents?.length ?? 1) > 1) continue;
      const { key, ...person } = identify(commit);
      const known = people.get(key);
      if (known) known.commits++;
      else people.set(key, { ...person, commits: 1 });
    }
    if (commits.length < PER_PAGE) break;
  }
  // One person can appear under two identities (a Forgejo account and a GitHub address): join them by name, keeping
  // the one with a profile and picture.
  const byName = new Map<string, Contributor>();
  for (const person of people.values()) {
    const key = person.name.trim().toLowerCase();
    const known = byName.get(key);
    if (!known) { byName.set(key, { ...person }); continue; }
    known.commits += person.commits;
    if (!known.profile && person.profile) { known.profile = person.profile; known.avatar = person.avatar; }
  }
  return [...byName.values()].sort((a, b) => b.commits - a.commits || a.name.localeCompare(b.name, 'en'));
}

let built: Promise<Contributor[] | null> | undefined;
/** One collection per build (or dev server). */
export function buildContributors() {
  built ??= collectContributors().catch((error) => {
    console.warn(`Contributors unavailable for this build: ${error.message}`);
    return null;
  });
  return built;
}
