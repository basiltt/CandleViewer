#!/usr/bin/env bash
set -e
export PATH="$PATH:/c/Program Files/GitHub CLI"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
cd "$(dirname "$0")"
REPO="basiltt/xstate-statemachine"
FOOTER='---
Filed from round 12 of our adoption audit (#26) on main @ de2da4e — the library is adopted; this is one of the items between "adopt with constraints" and "nothing open". Where a repro is attached it exits 1 while present, 0 once fixed.'

mkbody () {
  local f="$1" out="$2"
  local vline
  vline=$(grep -n "^## Verification" "$f" | head -1 | cut -d: -f1)
  local fmend
  fmend=$(awk '/^---$/{c++; if(c==2){print NR; exit}}' "$f")
  tail -n +$((fmend+1)) "$f" | head -n $((vline - fmend - 1)) > "$out"
  printf '\n%s\n' "$FOOTER" >> "$out"
}

getfield () {
  local f="$1" key="$2"
  awk -v k="$key" 'NR==1{next} /^---$/{exit} $0 ~ "^"k":"{sub("^"k": *",""); print}' "$f"
}

getlabels () {
  local f="$1"
  awk '/^labels:/{print; exit}' "$f" | sed 's/^labels: *\[//; s/\]$//; s/,/ /g'
}

echo "id,number" > /tmp/idmap.csv
