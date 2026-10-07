#!/bin/sh
PY="<workspace>/_ref/xstate-statemachine/.venv-main/Scripts/python"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
export PYTHONPATH="<workspace>/_ref/xstate-statemachine/src;$(pwd)"
name="$1"; shift
"$PY" "$name" "$@" >"out/${name%.py}.txt" 2>&1
echo "EXIT $? $name"
tail -25 "out/${name%.py}.txt"
