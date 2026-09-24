#!/bin/sh
PY="C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/.venv-main/Scripts/python"
D="$(pwd)"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
for n in "$@"; do
  b="${n%.py}"
  for k in async def; do
    sfx=""; [ "$k" = def ] && sfx=".DEF"
    ( cd /c/Users/basil && XS_SVC=$k timeout 115 "$PY" "$D/$n" >"$D/out/${b}${sfx}.txt" 2>&1; echo "EXIT $? $n [$k]" )
  done
done
