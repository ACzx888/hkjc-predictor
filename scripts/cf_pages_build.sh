#!/usr/bin/env bash
# Cloudflare Pages build: live HKJC refresh at build time → static dist/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV="${VENV:-$ROOT/.venv}"
PYTHON="${PYTHON:-python3}"

echo "==> HKJC Predictor Cloudflare Pages build"
echo "    root=$ROOT"

if [[ ! -d "$VENV" ]]; then
  echo "==> Creating venv at $VENV"
  "$PYTHON" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo "==> pip install -e ."
pip install -e . -q

LIVE_OK=0
echo "==> python -m hkjc_predictor --live"
set +e
python -m hkjc_predictor --live
LIVE_RC=$?
set -e

if [[ "$LIVE_RC" -eq 0 ]]; then
  LIVE_OK=1
  echo "==> Live refresh succeeded"
else
  echo "WARN: --live failed (exit $LIVE_RC); soft-failing with last known / demo pages"
  if [[ ! -f output/pages/index.html ]]; then
    echo "==> No existing pages; generating demo fallback"
    set +e
    python -m hkjc_predictor --demo
    python -m hkjc_predictor --demo-overseas
    python -m hkjc_predictor pages
    set -e
  else
    echo "==> Keeping last known output/pages"
    # Ensure pages exist / refresh chrome via rebuild from existing tips if needed
    set +e
    python -m hkjc_predictor pages
    set -e
  fi
fi

echo "==> Assemble dist/"
python scripts/prepare_cf_dist.py

# Soft-fail: never leave Cloudflare with an empty publish dir
if [[ ! -f dist/index.html ]]; then
  echo "ERROR: dist/index.html missing after prepare" >&2
  exit 1
fi

echo "==> Build complete (live_ok=$LIVE_OK)"
ls -la dist/ | head -40
