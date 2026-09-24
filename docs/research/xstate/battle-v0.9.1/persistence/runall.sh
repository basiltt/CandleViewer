#!/bin/sh
PY="C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/.venv-main/Scripts/python"
D="$(cd "$(dirname "$0")" && pwd)"
SRC="${SRC:-$D}"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
TO="${TO:-100}"
for n in "$@"; do
  b="$(basename "${n%.py}")"
  for k in async def; do
    sfx=""; [ "$k" = def ] && sfx=".DEF"
    ( cd /c/Users/basil && XS_SVC=$k timeout $TO "$PY" "$SRC/$n" >"$D/out/${b}${sfx}.txt" 2>&1; echo "EXIT $? $b [$k]" )
  done
done
