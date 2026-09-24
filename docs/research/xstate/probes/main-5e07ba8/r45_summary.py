import sys, glob, subprocess, os
P="C:/Users/basil/Desktop/Projects/FullStackProjects/_ref/xstate-statemachine/.venv-main/Scripts/python"
for f in sorted(glob.glob("r*.py")):
    if f=="r45_summary.py": continue
    print("="*70); print(f)
