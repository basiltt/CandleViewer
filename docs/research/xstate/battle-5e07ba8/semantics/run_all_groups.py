"""Runs every conformance group in one process and writes a combined
matrix to results/all.json plus a markdown table on stdout."""
import importlib, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import conf_harness as H

GROUPS = ["c1_selection", "c2_eventless_done", "c3_history_instate",
          "c4_actors", "c5_ordering"]
for g in GROUPS:
    importlib.import_module(g)
H.run_all("all")
