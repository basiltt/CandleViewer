"""Fixtures for cv-storage-unsafe-exec (E07-X02)."""
import pickle


def bad(blob, code):
    pickle.loads(blob)  # ruleid: cv-storage-unsafe-exec
    eval(code)  # ruleid: cv-storage-unsafe-exec
    exec(code)  # ruleid: cv-storage-unsafe-exec


def good(blob):
    return blob.decode()  # ok: cv-storage-unsafe-exec
