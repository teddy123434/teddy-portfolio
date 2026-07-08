#!/usr/bin/env bash
set -euo pipefail

strict=0
if [[ "${1:-}" == "--strict" ]]; then
  strict=1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

targets=()
while IFS= read -r -d '' dir; do
  targets+=("$dir")
done < <(find "$ROOT" -maxdepth 3 \( -path '*/node_modules' -o -path '*/dist' -o -path '*/.git' \) -prune -o \( -path '*/apps' -o -path '*/frontend/src' -o -path '*/src/app' -o -path '*/src/components' \) -type d -print0)

if (( ${#targets[@]} == 0 )); then
  echo "No frontend targets found."
  exit 0
fi

pattern='<button|<input|<select|<textarea|bg-blue-|bg-purple-|text-gray-|border-slate-|rounded-3xl|style=\{\{'

echo "Checking UI contract patterns under:"
printf '  %s\n' "${targets[@]#$ROOT/}"
echo

set +e
rg -n "$pattern" "${targets[@]}" \
  --glob '!**/node_modules/**' \
  --glob '!**/dist/**' \
  --glob '!**/.next/**' \
  --glob '!**/build/**'
status=$?
set -e

if [[ $status -eq 0 ]]; then
  echo
  echo "Review every match touched by your change. Prefer HeroUI components, semantic tokens, and lucide icons."
  if (( strict )); then
    exit 1
  fi
elif [[ $status -eq 1 ]]; then
  echo "No obvious UI contract violations found."
else
  exit "$status"
fi
