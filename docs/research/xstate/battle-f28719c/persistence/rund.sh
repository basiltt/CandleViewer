#!/bin/sh
PY="C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/.venv-main/Scripts/python"
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1 XS_SVC=def
export PYTHONPATH="C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/src;$(pwd)"
name="$1"; shift
"$PY" "$name" "$@" >"out/${name%.py}.DEF.txt" 2>&1
echo "EXIT $? $name [def]"
tail -12 "out/${name%.py}.DEF.txt"
