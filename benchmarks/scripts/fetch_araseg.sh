#!/usr/bin/env bash
# Fetch the AraSEG shared-task dev splits (parquet) used by the segmentation
# benchmark, and verify their SHA-256 against the pinned manifest in
# benchmarks/data/araseg_sha256.txt.
#
# Pinning the hashes freezes the evaluated data snapshot: if MBZUAI ever
# re-uploads the dataset, the checksum step fails loudly and the new snapshot
# must be reviewed before any paper number is regenerated (same discipline as
# the engine's golden files).
#
# Usage: bash benchmarks/scripts/fetch_araseg.sh /tmp/araseg
set -euo pipefail

DEST="${1:?usage: fetch_araseg.sh <dest-dir>}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="${REPO_ROOT}/benchmarks/data/araseg_sha256.txt"

mkdir -p "${DEST}/PA" "${DEST}/NP"

curl -sL --fail -o "${DEST}/PA_dev.parquet" \
  "https://huggingface.co/datasets/MBZUAI/AraSeg-2026-Shared-Task-PA/resolve/main/data/dev-00000-of-00001.parquet"
curl -sL --fail -o "${DEST}/NP_dev.parquet" \
  "https://huggingface.co/datasets/MBZUAI/AraSeg-2026-Shared-Task-NP/resolve/main/data/dev-00000-of-00001.parquet"

cp "${MANIFEST}" "${DEST}/araseg_sha256.txt"
cd "${DEST}"
sha256sum --check --strict araseg_sha256.txt
echo "AraSEG fetch OK (checksums verified against benchmarks/data/araseg_sha256.txt)"
