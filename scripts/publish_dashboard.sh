#!/usr/bin/env bash
# Publish a built dashboard site to the `dashboard` branch of origin.
#
#   scripts/publish_dashboard.sh [--update-baseline] [--dry-run] <site-dir>
#
# The site comes from `python -m totto_suite dashboard build --out <site-dir>`.
# Run it from inside the target git repository (cwd). It:
#   1. fetches `<remote> dashboard` if the branch exists (first publish works
#      without it),
#   2. stages "previous branch files + new site files" in a temp dir, merges
#      data/history.json (dedupe by run key), optionally moves
#      data/baseline.json (only if this run's gate verdict is PASS), re-renders
#      and re-runs the identifier check (`dashboard merge`),
#   3. commits that tree with plumbing (temporary GIT_INDEX_FILE +
#      commit-tree, parent = current remote tip) and pushes it fast-forward.
# It never touches the caller's working tree, HEAD or index. It exits 0 without
# a new commit when nothing changed, and retries 3x if the push loses a race.
#
# Auth: whatever `git push <remote>` uses from this repo: SSH locally, or the
# GITHUB_TOKEN that actions/checkout persists in .git/config in GitHub Actions.
#
# Environment:
#   DASHBOARD_UPDATE_BASELINE=1|true   same as --update-baseline
#   DASHBOARD_REMOTE (default origin), DASHBOARD_BRANCH (default dashboard)
#   DASHBOARD_DENY   extra identifier literals the check must reject
#   PYTHON           interpreter (default: <repo of this script>/.venv/bin/python, else python3)
set -euo pipefail

usage() { echo "usage: $0 [--update-baseline] [--dry-run] <site-dir>" >&2; exit 2; }

update_baseline=0
dry_run=0
site=""
case "${DASHBOARD_UPDATE_BASELINE:-0}" in 1|true|TRUE|yes) update_baseline=1 ;; esac
while [ $# -gt 0 ]; do
  case "$1" in
    --update-baseline) update_baseline=1 ;;
    --dry-run) dry_run=1 ;;
    -h|--help) usage ;;
    -*) echo "unknown flag: $1" >&2; usage ;;
    *) [ -z "$site" ] || usage; site="$1" ;;
  esac
  shift
done
[ -n "$site" ] || usage
[ -f "$site/data/latest.json" ] || { echo "$site/data/latest.json missing: run 'dashboard build' first" >&2; exit 2; }
site="$(cd "$site" && pwd)"

remote="${DASHBOARD_REMOTE:-origin}"
branch="${DASHBOARD_BRANCH:-dashboard}"
code_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # where totto_suite lives
if [ -z "${PYTHON:-}" ]; then
  if [ -x "$code_root/.venv/bin/python" ]; then PYTHON="$code_root/.venv/bin/python"; else PYTHON=python3; fi
fi
git_dir="$(git rev-parse --absolute-git-dir)"
g() { git --git-dir="$git_dir" "$@"; }

# Bot identity for the dashboard commits (not the caller's identity).
export GIT_AUTHOR_NAME="${DASHBOARD_GIT_NAME:-totto-dashboard-bot}"
export GIT_AUTHOR_EMAIL="${DASHBOARD_GIT_EMAIL:-dashboard-bot@users.noreply.github.com}"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

tmp="$(mktemp -d "${TMPDIR:-/tmp}/publish_dashboard.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT

publish_once() {
  local n="$1" stage="$tmp/stage-$1" prev="$tmp/prev-$1" parent="" heads tree commit msg
  mkdir -p "$stage" "$prev"

  if ! heads="$(g ls-remote --heads "$remote" "refs/heads/$branch")"; then
    echo "cannot reach remote '$remote'" >&2
    return 2
  fi
  if [ -n "$heads" ]; then
    g fetch --quiet --no-tags "$remote" "+refs/heads/$branch:refs/remotes/$remote/$branch" || return 2
    parent="$(g rev-parse "refs/remotes/$remote/$branch^{commit}")" || return 2
    g archive --format=tar "$parent" | tar -x -C "$stage" || return 2
    if [ -d "$stage/data" ]; then cp -R "$stage/data" "$prev/data" || return 2; fi
    echo "[publish] existing $branch at ${parent:0:12}"
  else
    echo "[publish] $remote has no $branch branch yet: creating it"
  fi

  cp -R "$site/." "$stage/" || return 2
  local merge_args=(--site "$stage")
  if [ -d "$prev/data" ]; then merge_args+=(--previous-data "$prev/data"); fi
  if [ "$update_baseline" = 1 ]; then merge_args+=(--update-baseline); fi
  # Merges history, re-renders and re-runs the identifier check; a leak => exit 2 => no commit.
  PYTHONPATH="$code_root${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -m totto_suite dashboard merge "${merge_args[@]}" || return 2
  : > "$stage/.nojekyll"

  export GIT_INDEX_FILE="$tmp/index-$n"
  rm -f "$GIT_INDEX_FILE"
  (cd "$stage" && git --git-dir="$git_dir" --work-tree="$stage" add -A -f .) || { unset GIT_INDEX_FILE; return 2; }
  tree="$(g write-tree)" || { unset GIT_INDEX_FILE; return 2; }
  unset GIT_INDEX_FILE

  if [ -n "$parent" ] && [ "$tree" = "$(g rev-parse "$parent^{tree}")" ]; then
    echo "[publish] no changes; $branch stays at ${parent:0:12}"
    return 0
  fi
  msg="$(PYTHONPATH="$code_root" "$PYTHON" -c '
import json, sys
d = json.load(open(sys.argv[1]))
print("dashboard: %s %s%s" % ((d.get("commit") or "unknown")[:7], d.get("verdict"),
      " (" + d["run_url"] + ")" if d.get("run_url") else ""))
' "$stage/data/latest.json")" || return 2
  if [ -n "$parent" ]; then
    commit="$(g commit-tree --no-gpg-sign "$tree" -p "$parent" -m "$msg")" || return 2
  else
    commit="$(g commit-tree --no-gpg-sign "$tree" -m "$msg")" || return 2
  fi
  if [ "$dry_run" = 1 ]; then
    echo "[publish] dry run: would push $commit ($msg) to $remote $branch"
    return 0
  fi
  if g push --quiet "$remote" "$commit:refs/heads/$branch"; then
    g update-ref "refs/remotes/$remote/$branch" "$commit"
    echo "[publish] pushed $branch ${commit:0:12}: $msg"
    return 0
  fi
  echo "[publish] push rejected (attempt $n)" >&2
  return 75
}

for attempt in 1 2 3; do
  rc=0
  publish_once "$attempt" || rc=$?
  [ "$rc" = 0 ] && exit 0
  [ "$rc" = 75 ] || exit "$rc"
  sleep "$attempt"
done
echo "[publish] giving up after 3 attempts" >&2
exit 1
