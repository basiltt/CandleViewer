"""Fixtures for cv-rules-no-dynamic-eval (ADR-0007 R1)."""
import builtins
import importlib
import marshal
import pickle
import re

import yaml


def bad(src: str, blob: bytes) -> None:
    eval(src)  # ruleid: cv-rules-no-dynamic-eval
    exec(src)  # ruleid: cv-rules-no-dynamic-eval
    compile(src, "x", "eval")  # ruleid: cv-rules-no-dynamic-eval
    __import__(src)  # ruleid: cv-rules-no-dynamic-eval
    pickle.loads(blob)  # ruleid: cv-rules-no-dynamic-eval


def bad_evasions(src: str, blob: bytes, f: object) -> None:
    builtins.eval(src)  # ruleid: cv-rules-no-dynamic-eval
    importlib.import_module(src)  # ruleid: cv-rules-no-dynamic-eval
    marshal.loads(blob)  # ruleid: cv-rules-no-dynamic-eval
    pickle.Unpickler(f)  # ruleid: cv-rules-no-dynamic-eval
    yaml.load(src)  # ruleid: cv-rules-no-dynamic-eval


from pickle import loads  # ruleid: cv-rules-no-dynamic-eval


def ok(src: str) -> object:
    return re.compile(src)  # ok: cv-rules-no-dynamic-eval


def ok_yaml(src: str) -> object:
    return yaml.safe_load(src)  # ok: cv-rules-no-dynamic-eval
