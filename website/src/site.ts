// Where the site and the project live. Pages are served from the root of the site's own domain.
export const siteUrl = 'https://hookshot.magicbean.dev';
export const repository = 'https://git.magicbean.dev/MagicBeanDev/Hookshot';
export const issueUrl = `${repository}/issues/new`;
/** A file in the repository on Forgejo, on main. */
export const sourceUrl = (file: string) => `${repository}/src/branch/main/${file}`;
/** Forgejo's editor for a file on main: saving it proposes the change as a pull request. */
export const editUrl = (file: string) => `${repository}/_edit/main/${file}`;
