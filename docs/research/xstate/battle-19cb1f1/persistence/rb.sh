#!/bin/sh
# run both kinds; usage: rb.sh script.py [args]
PY="<workspace>/_ref/xstate-statemachine/.venv-main/Scripts/python"
D="$(pwd)"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
n="$1"; shift
( cd /c<home> && XS_SVC=async "$PY" "$D/$n" "$@" >"$D/out/${n%.py}.txt" 2>&1; echo "EXIT $? ${n} [async]" )
( cd /c<home> && XS_SVC=def   "$PY" "$D/$n" "$@" >"$D/out/${n%.py}.DEF.txt" 2>&1; echo "EXIT $? ${n} [def]" )
