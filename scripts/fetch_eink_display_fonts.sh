#!/usr/bin/env bash
# Fetch display fonts used by the Pillow e-ink renderer.
#
# Downloads Source Serif 4 (regular/semibold/bold + italic/bolditalic) and
# Inter (medium/bold) TTFs into backend/services/eink/static/fonts/. Both
# families are SIL Open Font License 1.1, so redistribution is fine -- the
# expected workflow is:
#
#   1. Run this script once.
#   2. `git add backend/services/eink/static/fonts/source-serif-4/`
#      `git add backend/services/eink/static/fonts/inter/`
#   3. Commit the TTFs so the renderer works on a fresh checkout without
#      network access.
#
# Idempotent: already-present files are left alone.
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
FONTS_DIR="${REPO_ROOT}/backend/services/eink/static/fonts"

SS_DIR="${FONTS_DIR}/source-serif-4"
INTER_DIR="${FONTS_DIR}/inter"
WI_DIR="${FONTS_DIR}/weather-icons"
TRMNL_DIR="${FONTS_DIR}/trmnl"

mkdir -p "${SS_DIR}" "${INTER_DIR}" "${WI_DIR}" "${TRMNL_DIR}"

# Pin versions so hashes don't drift unexpectedly across checkouts.
SS_VER="4.005R"
SS_BASE="https://github.com/adobe-fonts/source-serif/raw/${SS_VER}/TTF"

SS_FILES=(
  "SourceSerif4-Regular.ttf"
  "SourceSerif4-Semibold.ttf"
  "SourceSerif4-Bold.ttf"
  "SourceSerif4-It.ttf"
  "SourceSerif4-SemiboldIt.ttf"
  "SourceSerif4-BoldIt.ttf"
)

INTER_VER="v4.0"
INTER_ZIP_URL="https://github.com/rsms/inter/releases/download/${INTER_VER}/Inter-4.0.zip"
INTER_FILES=(
  "Inter-Medium.ttf"
  "Inter-Bold.ttf"
)

fetch_if_missing() {
  local url="$1"
  local dest="$2"
  if [[ -f "${dest}" ]]; then
    echo "skip  ${dest} (present)"
    return 0
  fi
  echo "fetch ${dest}"
  curl -fSL --retry 3 --retry-delay 1 --connect-timeout 10 -o "${dest}" "${url}"
}

echo "Source Serif 4 @ ${SS_VER} -> ${SS_DIR}"
for f in "${SS_FILES[@]}"; do
  fetch_if_missing "${SS_BASE}/${f}" "${SS_DIR}/${f}"
done

# Inter ships its TTFs inside a release zip at extras/ttf/.
need_any_inter=0
for f in "${INTER_FILES[@]}"; do
  if [[ ! -f "${INTER_DIR}/${f}" ]]; then
    need_any_inter=1
  fi
done

# Weather Icons (Erik Flowers) -- icon font used by the e-ink dashboard
# for weather glyphs. SIL OFL 1.1.
WI_VER="2.0.10"
WI_URL="https://github.com/erikflowers/weather-icons/raw/${WI_VER}/font/weathericons-regular-webfont.ttf"
fetch_if_missing "${WI_URL}" "${WI_DIR}/weathericons-regular-webfont.ttf"

if [[ "${need_any_inter}" -eq 1 ]]; then
  echo "Inter @ ${INTER_VER} -> ${INTER_DIR} (via release zip)"
  tmp_zip="$(mktemp --suffix=.zip)"
  trap 'rm -f "${tmp_zip}"' EXIT
  curl -fSL --retry 3 --retry-delay 1 --connect-timeout 10 -o "${tmp_zip}" "${INTER_ZIP_URL}"
  python3 - "${tmp_zip}" "${INTER_DIR}" "${INTER_FILES[@]}" <<'PY'
import os
import sys
import zipfile

zip_path = sys.argv[1]
dest_dir = sys.argv[2]
wanted = set(sys.argv[3:])

with zipfile.ZipFile(zip_path) as z:
    for name in z.namelist():
        base = os.path.basename(name)
        if base in wanted and name.endswith(".ttf"):
            out_path = os.path.join(dest_dir, base)
            if os.path.exists(out_path):
                print(f"skip  {out_path} (present)")
                continue
            print(f"fetch {out_path}")
            with z.open(name) as src, open(out_path, "wb") as dst:
                dst.write(src.read())
PY
else
  for f in "${INTER_FILES[@]}"; do
    echo "skip  ${INTER_DIR}/${f} (present)"
  done
fi

# TRMNL pixel font (Day Ahead portrait design). Three native bitmap sizes
# (12 / 16 / 21), Regular + Bold. TRMNL has no canonical download URL, so the
# TTFs are committed to the repo and are the source of truth -- this block only
# verifies they're present and warns (without failing) if any are missing.
TRMNL_FILES=(
  "TRMNL12-Regular.ttf"
  "TRMNL12-Bold.ttf"
  "TRMNL16-Regular.ttf"
  "TRMNL16-Bold.ttf"
  "TRMNL21-Regular.ttf"
  "TRMNL21-Bold.ttf"
)
echo "TRMNL (committed in-repo) -> ${TRMNL_DIR}"
trmnl_missing=0
for f in "${TRMNL_FILES[@]}"; do
  if [[ -f "${TRMNL_DIR}/${f}" ]]; then
    echo "skip  ${TRMNL_DIR}/${f} (present)"
  else
    echo "WARN  ${TRMNL_DIR}/${f} missing (commit it from the Day Ahead package server-fonts/trmnl/)"
    trmnl_missing=1
  fi
done
if [[ "${trmnl_missing}" -eq 1 ]]; then
  echo "WARN  TRMNL fonts incomplete; the Day Ahead display will fail to render until they are added."
fi

echo "done."
