"""E08-Q02 feed-rot guard (risk R6) and corpus-coverage meta-test.

* The field-path *set* of every fixture stream must equal the checked-in expectations
  (`schema_expectations.json`, owned by E08-T05, CODEOWNERS-reviewed): a Bybit field that is
  added, renamed or removed fails here with a diff and a pointer to `README.md`.
* Every corpus manifest entry must be referenced by at least one pack test.
* No fixture may carry anything matching the secret patterns.
"""

from __future__ import annotations

import copy
import importlib
import json
import re
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest

from tests._corpus import CAPTURE_DATE, CORPUS_ROOT, corpus_path, frames, manifest

_REPO = Path(__file__).resolve().parents[5]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_drift = importlib.import_module("tools.fixtures.drift_check")
_redact = importlib.import_module("tools.fixtures.redact")
Schema = dict[str, dict[str, dict[str, Any]]]  # stream -> field path -> {types, required}
infer: Callable[[Iterable[tuple[str, Any]]], Schema] = _drift.infer
load_docs: Callable[[Path], list[tuple[str, Any]]] = _drift.load_docs
find_leaks: Callable[[str], list[str]] = _redact.find_leaks

PACK = Path(__file__).resolve().parent
README_HINT = "tests/contract/bybit/README.md#feed-rot-triage"


def _expected() -> Schema:
    data: Schema = json.loads(corpus_path("schema_expectations.json").read_text(encoding="utf-8"))
    return data


def field_drift(expected: Schema, sample: Schema) -> list[str]:
    """Exact set comparison per stream (stricter than `drift_check.diff`, which tolerates
    absent delta-only fields): added, removed (renamed shows as one of each) and retyped."""
    out: list[str] = []
    for stream in sorted(set(expected) | set(sample)):
        want, got = expected.get(stream), sample.get(stream)
        if want is None:
            out.append(f"{stream}: unexpected stream")
            continue
        if got is None:
            out.append(f"{stream}: stream missing from sample")
            continue
        out += [f"{stream}: added field {p}" for p in sorted(set(got) - set(want))]
        out += [f"{stream}: removed field {p}" for p in sorted(set(want) - set(got))]
        for p in sorted(set(got) & set(want)):
            if not set(got[p]["types"]) <= set(want[p]["types"]):
                out.append(f"{stream}: retyped field {p}")
    return out


def assert_no_drift(expected: Schema, sample: Schema) -> None:
    drift = field_drift(expected, sample)
    if drift:
        pytest.fail(
            "Bybit payload drift (R6 feed rot):\n  "
            + "\n  ".join(drift)
            + f"\nTriage procedure: {README_HINT}",
            pytrace=False,
        )


def test_committed_corpus_matches_the_expected_field_manifest() -> None:
    assert_no_drift(_expected(), infer(load_docs(CORPUS_ROOT / CAPTURE_DATE)))


def _planted_sample() -> Schema:
    """A fixture edited to add an unknown field and rename an existing one."""
    docs = load_docs(CORPUS_ROOT / CAPTURE_DATE)
    out: list[tuple[str, Any]] = []
    for stream, doc in docs:
        doc = copy.deepcopy(doc)
        if stream == "publicTrade" and isinstance(doc.get("data"), list):
            for row in doc["data"]:
                row["newVenueField"] = "x"  # added
                row["qty"] = row.pop("v")  # renamed (Bybit's `v` -> `qty`) on every frame
        out.append((stream, doc))
    return infer(out)


def test_planted_add_and_rename_fail_naming_both_fields_and_the_triage_link() -> None:
    with pytest.raises(pytest.fail.Exception) as info:
        assert_no_drift(_expected(), _planted_sample())
    message = str(info.value)
    assert "added field data[].newVenueField" in message
    assert "added field data[].qty" in message and "removed field data[].v" in message
    assert README_HINT in message


def test_a_removed_optional_delta_field_is_still_caught() -> None:
    docs = [(s, copy.deepcopy(d)) for s, d in load_docs(CORPUS_ROOT / CAPTURE_DATE)]
    for stream, doc in docs:
        if stream == "tickers":
            doc["data"].pop("fundingRate", None)
    assert "removed field data.fundingRate" in "\n".join(field_drift(_expected(), infer(docs)))


# ---- every manifest entry is exercised by a pack test --------------------------------------


def _pack_sources() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(PACK.glob("test_contract_*.py"))
        if p.name != Path(__file__).name  # this meta-test must not satisfy itself
    )


def unreferenced(entries: list[str], source: str) -> list[str]:
    return [rel for rel in entries if rel not in source]


def test_every_manifest_fixture_is_referenced_by_at_least_one_pack_test() -> None:
    missing = unreferenced([e["path"] for e in manifest()["fixtures"]], _pack_sources())
    assert not missing, f"fixtures with no contract test: {missing}"


def test_an_unreferenced_fixture_fails_the_meta_check_with_its_name() -> None:
    entries = [e["path"] for e in manifest()["fixtures"]] + ["ws/brand_new_stream.jsonl"]
    assert unreferenced(entries, _pack_sources()) == ["ws/brand_new_stream.jsonl"]


# ---- security: fixtures are untrusted input and must hold no secrets -----------------------


def test_no_fixture_contains_secret_shaped_content() -> None:
    leaks = {
        e["path"]: find_leaks(corpus_path(e["path"]).read_text(encoding="utf-8"))
        for e in manifest()["fixtures"]
    }
    assert {k: v for k, v in leaks.items() if v} == {}


def test_no_fixture_frame_carries_auth_headers_or_account_ids() -> None:
    pattern = re.compile(r"X-BAPI-|api[_-]?key|\"(uid|accountId|userId)\"", re.I)
    for e in manifest()["fixtures"]:
        text = corpus_path(e["path"]).read_text(encoding="utf-8")
        assert not pattern.search(text), e["path"]
    assert frames("ws/tickers_BTCUSDT.jsonl")  # corpus is really readable
