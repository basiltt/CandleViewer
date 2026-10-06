"""Regenerates depth_bypass_string_brackets.frame (PR #1898 review finding 1)."""

from pathlib import Path

N = 5000
FRAME = '{"x":[' + '"]",[' * N + "]" * N + "]}"
Path(__file__).with_name("depth_bypass_string_brackets.frame").write_text(FRAME, newline="")
