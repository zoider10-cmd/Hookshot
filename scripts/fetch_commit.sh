#!/bin/bash
# One commit of another project's git repository, by its full URL, into a folder: what the workflows had actions/checkout do
# with `repository:`, which on Forgejo names a repository of the Forgejo instance (github.server_url), not of GitHub, so
# KhronosGroup/Vulkan-Headers was looked for on git.magicbean.dev and not found. Pinned the same way, by the commit's hash:
# the folder holds that commit or the script fails. No credentials are sent (actions/checkout would send the job's Forgejo
# token to the other host).
#
#   scripts/fetch_commit.sh <https://... repository URL> <40-hex commit> <folder>
#
# Each fetch is tried three times, 15 s apart: a host briefly out of reach does not fail the job.
set -euo pipefail
[ $# -eq 3 ] || { echo "usage: $0 <repository URL> <commit> <folder>" >&2; exit 2; }
url=$1 commit=$2 dir=$3
[[ $url == https://* ]] || { echo "fetch_commit.sh: $url is not an https:// URL" >&2; exit 2; }
[[ $commit =~ ^[0-9a-f]{40}$ ]] || { echo "fetch_commit.sh: $commit is not a full commit hash" >&2; exit 2; }
rm -rf "$dir"
mkdir -p "$dir"
git -C "$dir" init -q
git -C "$dir" remote add origin "$url"
for try in 1 2 3; do
    if git -C "$dir" -c protocol.version=2 fetch -q --no-tags --depth=1 origin "$commit"; then break; fi
    [ "$try" = 3 ] && { echo "fetch_commit.sh: $url $commit could not be fetched" >&2; exit 1; }
    echo "fetch_commit.sh: fetch $try of 3 failed; trying again in 15 s"
    sleep 15
done
git -C "$dir" -c advice.detachedHead=false checkout -q FETCH_HEAD
got=$(git -C "$dir" rev-parse HEAD)
[ "$got" = "$commit" ] || { echo "fetch_commit.sh: $url gave $got, not $commit" >&2; exit 1; }
echo "$url $commit -> $dir"
