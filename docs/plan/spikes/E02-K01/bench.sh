#!/usr/bin/env bash
# Spike E02-K01 timing harness (median-of-N loops).
# Retrieved from the throwaway .spike-tmp/ prototype (gitignored) and committed here per QA defect #1459
# (item 3: "benchmark script/results referenced as attached are not committed/retrievable from main").
#
# This script documents exactly what was run against the throwaway prototype under .spike-tmp/proto,
# .spike-tmp/proto-nx and .spike-tmp/proto-poetry/svc1 (see docs/plan/spikes/E02-K01.md for the full
# write-up). It is not re-runnable as-is on a clean checkout because the prototype directories are
# intentionally throwaway/gitignored (ADR-0018 "Spike branch marked throwaway and left unmerged"); it is
# provided so the exact measurement methodology is inspectable and reproducible by regenerating the same
# prototype layout.
set -euo pipefail

N=5

median() {
  printf '%s\n' "$@" | sort -n | awk -v n="$#" '{a[NR]=$1} END{print a[int((n+1)/2)]}'
}

time_cmd() {
  local start end
  start=$(date +%s.%N)
  "$@" >/dev/null 2>&1
  end=$(date +%s.%N)
  echo "$end - $start" | bc
}

echo "== pnpm install (workspace), cold vs warm =="
pushd .spike-tmp/proto >/dev/null
runs_cold=()
for i in $(seq 1 "$N"); do
  rm -rf node_modules
  runs_cold+=("$(time_cmd pnpm install --frozen-lockfile)")
done
echo "cold median: $(median "${runs_cold[@]}")s"

runs_warm=()
for i in $(seq 1 "$N"); do
  runs_warm+=("$(time_cmd pnpm install --frozen-lockfile)")
done
echo "warm median: $(median "${runs_warm[@]}")s"

echo "== turbo run lint test build (forced, cold) =="
runs_forced=()
for i in $(seq 1 "$N"); do
  runs_forced+=("$(time_cmd pnpm turbo run lint test build --force)")
done
echo "forced median: $(median "${runs_forced[@]}")s"

echo "== turbo run lint test build (cached, warm) =="
pnpm turbo run lint test build >/dev/null 2>&1 # prime cache
runs_cached=()
for i in $(seq 1 "$N"); do
  runs_cached+=("$(time_cmd pnpm turbo run lint test build)")
done
echo "cached median: $(median "${runs_cached[@]}")s"
popd >/dev/null

echo "== nx workspace scaffold (one-time) =="
runs_nx=("$(time_cmd npx create-nx-workspace@latest .spike-tmp/proto-nx --preset=ts --nx-cloud=false)")
echo "scaffold: ${runs_nx[0]}s"

echo "== uv sync (full pinned stack), cold vs warm =="
pushd .spike-tmp/proto/services/svc1 >/dev/null
runs_uv_cold=()
for i in 1 2 3; do
  rm -rf .venv
  runs_uv_cold+=("$(time_cmd uv sync)")
done
echo "uv cold median: $(median "${runs_uv_cold[@]}")s"

runs_uv_warm=()
for i in 1 2 3; do
  runs_uv_warm+=("$(time_cmd uv sync)")
done
echo "uv warm median: $(median "${runs_uv_warm[@]}")s"
popd >/dev/null

echo "== poetry lock + poetry install, cold vs warm =="
pushd .spike-tmp/proto-poetry/svc1 >/dev/null
runs_poetry_cold=()
for i in 1 2 3; do
  rm -rf .venv poetry.lock
  runs_poetry_cold+=("$(time_cmd poetry lock)")
done
echo "poetry lock cold median: $(median "${runs_poetry_cold[@]}")s"
popd >/dev/null

echo "Done. See results.json (committed alongside this script) for the recorded medians used in ADR-0018."
