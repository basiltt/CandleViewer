"""Fixtures for cv-rules-no-dynamic-eval (ADR-0007 R1)."""
import pickle
import re


def bad(src: str, blob: bytes) -> None:
    eval(src)  # ruleid: cv-rules-no-dynamic-eval
    exec(src)  # ruleid: cv-rules-no-dynamic-eval
    compile(src, "x", "eval")  # ruleid: cv-rules-no-dynamic-eval
    __import__(src)  # ruleid: cv-rules-no-dynamic-eval
    pickle.loads(blob)  # ruleid: cv-rules-no-dynamic-eval


def ok(src: str) -> object:
    return re.compile(src)  # ok: cv-rules-no-dynamic-eval
