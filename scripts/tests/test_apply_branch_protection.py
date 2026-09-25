"""Unit tests for scripts/apply_branch_protection.py (GOV-005 support)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import apply_branch_protection as abp


def _valid_desired_state() -> dict:
    return {
        "branch": "main",
        "required_pull_request_reviews": {
            "required_approving_review_count": 2,
            "require_code_owner_reviews": True,
            "dismiss_stale_reviews": True,
        },
        "required_conversation_resolution": True,
        "required_linear_history": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "enforce_admins": True,
        "required_status_checks": {"strict": True, "contexts": ["governance"]},
        "x-pending-contexts": ["lint"],
        "merge_queue": {"merge_method": "SQUASH"},
        "$comment": "ignored",
    }


def test_load_desired_state_valid_file_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "branch-protection.json"
    path.write_text(json.dumps(_valid_desired_state()), encoding="utf-8")
    data = abp.load_desired_state(str(path))
    assert data["enforce_admins"] is True


def test_load_desired_state_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(abp.DesiredStateError):
        abp.load_desired_state(str(tmp_path / "does-not-exist.json"))


def test_load_desired_state_invalid_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(abp.DesiredStateError):
        abp.load_desired_state(str(path))


@pytest.mark.parametrize(
    "mutation,message_fragment",
    [
        (lambda d: d["required_pull_request_reviews"].update(required_approving_review_count=1), "review_count"),
        (lambda d: d["required_pull_request_reviews"].update(require_code_owner_reviews=False), "code_owner"),
        (lambda d: d.update(enforce_admins=False), "enforce_admins"),
        (lambda d: d.update(allow_force_pushes=True), "force_pushes"),
        (lambda d: d.update(required_linear_history=False), "linear_history"),
    ],
)
def test_validate_desired_state_rejects_weakened_settings(mutation, message_fragment) -> None:
    data = _valid_desired_state()
    mutation(data)
    with pytest.raises(abp.DesiredStateError):
        abp.validate_desired_state(data)


def test_validate_desired_state_requires_contexts_list() -> None:
    data = _valid_desired_state()
    data["required_status_checks"]["contexts"] = "not-a-list"
    with pytest.raises(abp.DesiredStateError):
        abp.validate_desired_state(data)


def test_to_api_payload_strips_internal_keys() -> None:
    payload = abp.to_api_payload(_valid_desired_state())
    for key in abp.NON_API_KEYS:
        assert key not in payload
    assert "required_pull_request_reviews" in payload


def test_diff_state_no_changes_is_empty() -> None:
    live = {"enforce_admins": True, "allow_force_pushes": False}
    desired = {"enforce_admins": True, "allow_force_pushes": False}
    diff = abp.diff_state(live, desired)
    assert diff.is_empty()


def test_diff_state_detects_added_removed_and_changed() -> None:
    live = {"enforce_admins": False, "stale_key": 1}
    desired = {"enforce_admins": True, "new_key": 2}
    diff = abp.diff_state(live, desired)
    assert diff.added == {"new_key": 2}
    assert diff.removed == {"stale_key": 1}
    assert diff.changed == {"enforce_admins": (False, True)}
    assert not diff.is_empty()
    assert "enforce_admins" in diff.render()
