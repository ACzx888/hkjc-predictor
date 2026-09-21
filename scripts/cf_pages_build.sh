#!/usr/bin/env bash
# Cloudflare Pages build — avoid venv (often breaks on CF); soft-fail live fetch.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONUNBUFFERED=1
export PIP_DISABLE_PIP_VERSION_CHECK=1

echo "==> HKJC Predictor Cloudflare Pages build"
echo "    root=$ROOT"
echo "    python=$(command -v python3 || true) $(python3 --version 2>&1 || true)"

# Prefer plain pip on the build image (no venv).
python3 -m pip install --upgrade pip setuptools wheel -q
if [[ -f requirements.txt ]]; then
  echo "==> pip install -r requirements.txt"
  python3 -m pip install -r requirements.txt -q
fi
echo "==> pip install ."
python3 -m pip install . -q

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# Always ensure some pages exist (demo) before attempting live.
echo "==> Ensure demo pages exist (safety net)"
set +e
python3 -m hkjc_predictor --demo
python3 -m hkjc_predictor --demo-overseas
python3 -m hkjc_predictor pages
set -e

LIVE_OK=0
echo "==> Try live GraphQL refresh"
set +e
python3 -m hkjc_predictor --live
LIVE_RC=$?
set -e
if [[ "$LIVE_RC" -eq 0 ]]; then
  LIVE_OK=1
  echo "==> Live refresh succeeded"
  set +e
  python3 -m hkjc_predictor pages
  set -e
else
  echo "WARN: --live failed (exit $LIVE_RC); continuing with demo / last pages"
fi

echo "==> Assemble dist/"
python3 scripts/prepare_cf_dist.py

if [[ ! -f dist/index.html ]]; then
  echo "ERROR: dist/index.html missing after prepare" >&2
  ls -la output/pages 2>&1 || true
  exit 1
fi

echo "==> Build complete (live_ok=$LIVE_OK)"
ls -la dist/ | head -40
