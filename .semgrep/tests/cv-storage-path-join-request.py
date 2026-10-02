"""Fixtures for cv-storage-path-join-request (E07-X02, SR-097)."""
import os


def bad(request, root):
    return os.path.join(root, request.dataset)  # ruleid: cv-storage-path-join-request


def good(root):
    return os.path.join(root, "_manifests")  # ok: cv-storage-path-join-request
