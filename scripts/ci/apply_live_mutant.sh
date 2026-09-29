#!/usr/bin/env bash
# Apply a live-only mutant (evals/mutants/live/<name>.patch).
#
# Live-only mutants break the agent in a way the offline suite cannot see
# (a prompt change), but the staging CXAS evals can. They exist to prove the
# "CXAS eval gate" CI step goes red on a real regression. Never merge one.
#
# Usage:
#   scripts/ci/apply_live_mutant.sh <name>                  apply to this repo's working tree
#   scripts/ci/apply_live_mutant.sh <name> --apply-to <dir> apply to <dir>/cxas_app (a copy)
#   scripts/ci/apply_live_mutant.sh <name> --check-offline  apply to a temp copy of cxas_app and
#                                                           run `totto_suite offline` on it; exit 0
#                                                           means the mutant is offline-invisible
#   scripts/ci/apply_live_mutant.sh --list
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MUTANT_DIR="${ROOT}/evals/mutants/live"

list() { for p in "${MUTANT_DIR}"/*.patch; do basename "${p}" .patch; done; }

if [[ "${1:-}" == "--list" ]]; then list; exit 0; fi
name="${1:?usage: $0 <name> [--apply-to <dir> | --check-offline] (see --list)}"
mode="${2:-}"
patch="${MUTANT_DIR}/${name}.patch"
if [[ ! -f "${patch}" ]]; then
  echo "unknown live mutant '${name}'. Available:" >&2
  list >&2
  exit 2
fi

# Applies the patch inside $1 (a directory that contains cxas_app/). The
# fallback with one line of context tolerates unrelated prompt edits above
# the mutated spot.
apply_in() {
  local dir="$1"
  if ! (cd "${dir}" && git apply "${patch}" 2>/dev/null); then
    (cd "${dir}" && git apply -C1 "${patch}")
  fi
}

case "${mode}" in
  "")
    apply_in "${ROOT}"
    echo "[live-mutant] applied ${name} to ${ROOT}"
    git -C "${ROOT}" diff --stat -- cxas_app
    ;;
  --apply-to)
    target="${3:?--apply-to needs a directory containing cxas_app/}"
    apply_in "${target}"
    echo "[live-mutant] applied ${name} to ${target}/cxas_app"
    ;;
  --check-offline)
    tmp="$(mktemp -d)"
    trap 'rm -rf "${tmp}"' EXIT
    cp -R "${ROOT}/cxas_app" "${tmp}/cxas_app"
    apply_in "${tmp}"
    py="${TOTTO_PYTHON:-${ROOT}/.venv/bin/python}"
    [[ -x "${py}" ]] || py="$(command -v python3)"
    echo "[live-mutant] running totto_suite offline on ${name} (temp copy)"
    cd "${ROOT}"
    if "${py}" -m totto_suite offline --app-dir "${tmp}/cxas_app" --no-record; then
      echo "[live-mutant] ${name}: offline suite PASSES -> offline-invisible (only the CXAS gate can catch it)"
    else
      echo "[live-mutant] ${name}: offline suite FAILS -> NOT offline-invisible" >&2
      exit 1
    fi
    ;;
  *)
    echo "unknown mode '${mode}'" >&2
    exit 2
    ;;
esac
