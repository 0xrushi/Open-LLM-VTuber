#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

if ! command -v git >/dev/null 2>&1; then
  echo "Error: git is required." >&2
  exit 1
fi
if ! command -v ssh >/dev/null 2>&1; then
  echo "Error: ssh is required." >&2
  exit 1
fi
if ! command -v scp >/dev/null 2>&1; then
  echo "Error: scp is required." >&2
  exit 1
fi

if [[ ! -d "${ROOT_DIR}/.git" ]]; then
  echo "Error: script must run from inside the Open-LLM-VTuber repo." >&2
  exit 1
fi

declare -A ADDED=()
MANIFEST="$(mktemp)"
trap 'rm -f "${MANIFEST}"' EXIT

add_path() {
  local rel="$1"
  [[ -z "${rel}" ]] && return 0
  [[ "${rel}" = /* ]] && return 0
  [[ "${rel}" == *$'\n'* ]] && return 0
  [[ ! -e "${ROOT_DIR}/${rel}" ]] && return 0
  if [[ -z "${ADDED[${rel}]+x}" ]]; then
    ADDED["${rel}"]=1
    printf '%s\n' "${rel}" >> "${MANIFEST}"
  fi
}

echo "Collecting local override files..."

# Always include key local runtime config files if present.
add_path "conf.yaml"
add_path "mcp_servers.json"
add_path "mcp_servers copy.json"

# Include modified tracked files (staged + unstaged).
while IFS= read -r rel; do
  add_path "${rel}"
done < <(git -C "${ROOT_DIR}" diff --name-only)

while IFS= read -r rel; do
  add_path "${rel}"
done < <(git -C "${ROOT_DIR}" diff --name-only --cached)

# Include untracked files.
while IFS= read -r rel; do
  add_path "${rel}"
done < <(git -C "${ROOT_DIR}" ls-files --others --exclude-standard)

# Include custom Live2D model directories not tracked by git.
if [[ -d "${ROOT_DIR}/live2d-models" ]]; then
  while IFS= read -r model_dir; do
    rel_model_dir="${model_dir#${ROOT_DIR}/}"
    if ! git -C "${ROOT_DIR}" ls-files --error-unmatch "${rel_model_dir}" >/dev/null 2>&1; then
      add_path "${rel_model_dir}"
    fi
  done < <(find "${ROOT_DIR}/live2d-models" -mindepth 1 -maxdepth 1 -type d)
fi

if [[ ! -s "${MANIFEST}" ]]; then
  echo "No local override files found to copy."
  exit 0
fi

echo
echo "Files/directories to copy:"
sed 's/^/  - /' "${MANIFEST}"
echo

read -r -p "Continue? [y/N]: " confirm
if [[ ! "${confirm}" =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 0
fi

read -r -p "Remote SSH target (user@ip): " REMOTE_TARGET
if [[ -z "${REMOTE_TARGET}" ]]; then
  echo "Error: remote target is required." >&2
  exit 1
fi

read -r -p "Remote Open-LLM-VTuber path: " REMOTE_PATH
if [[ -z "${REMOTE_PATH}" ]]; then
  echo "Error: remote path is required." >&2
  exit 1
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE_NAME="openllmvtuber_local_overrides_${STAMP}.tar.gz"
ARCHIVE_PATH="/tmp/${ARCHIVE_NAME}"

echo
echo "Creating archive: ${ARCHIVE_PATH}"
tar -czf "${ARCHIVE_PATH}" -C "${ROOT_DIR}" -T "${MANIFEST}"

echo "Uploading archive to ${REMOTE_TARGET}..."
scp "${ARCHIVE_PATH}" "${REMOTE_TARGET}:/tmp/${ARCHIVE_NAME}"

echo "Extracting on remote host..."
ssh "${REMOTE_TARGET}" "mkdir -p \"${REMOTE_PATH}\" && tar -xzf \"/tmp/${ARCHIVE_NAME}\" -C \"${REMOTE_PATH}\" && rm -f \"/tmp/${ARCHIVE_NAME}\""

rm -f "${ARCHIVE_PATH}"
echo
echo "Done. Local overrides copied to ${REMOTE_TARGET}:${REMOTE_PATH}"
