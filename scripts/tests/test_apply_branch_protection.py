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
            "require_last_push_approval": True,
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
# Regression: encodes E01-Q01 cases 1.1-1.5 (originating case id) -- desired-state
# mutations that must be rejected (review count, code-owner reviews, enforce_admins,
# force pushes, linear history).
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


def test_to_api_payload_includes_restrictions_null_when_absent() -> None:
    payload = abp.to_api_payload(_valid_desired_state())
    assert "restrictions" in payload
    assert payload["restrictions"] is None


def test_to_api_payload_preserves_explicit_restrictions() -> None:
    data = _valid_desired_state()
    data["restrictions"] = {"users": [], "teams": ["release-managers"]}
    payload = abp.to_api_payload(data)
    assert payload["restrictions"] == {"users": [], "teams": ["release-managers"]}


# Regression: encodes E01-Q01 case 1.9 (originating case id) -- re-apply of an
# identical live/desired state must be a no-op diff.
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


# --- Live-state normalisation (finding: diff_state never went empty) -----

def _recorded_get_protection_response() -> dict:
    """Shape modelled on GitHub's documented GET
    .../branches/{branch}/protection response: booleans wrapped as
    `{"enabled": ...}` and nested objects carrying read-only `url` fields."""
    return {
        "url": "https://api.github.com/repos/o/r/branches/main/protection",
        "required_status_checks": {
            "url": "https://api.github.com/repos/o/r/branches/main/protection/required_status_checks",
            "strict": True,
            "contexts": ["governance"],
            "contexts_url": "https://api.github.com/repos/o/r/branches/main/protection/required_status_checks/contexts",
            "checks": [{"context": "governance", "app_id": -1}],
        },
        "required_pull_request_reviews": {
            "url": "https://api.github.com/repos/o/r/branches/main/protection/required_pull_request_reviews",
            "required_approving_review_count": 2,
            "require_code_owner_reviews": True,
            "dismiss_stale_reviews": True,
            "require_last_push_approval": True,
        },
        "enforce_admins": {
            "url": "https://api.github.com/repos/o/r/branches/main/protection/enforce_admins",
            "enabled": True,
        },
        "required_linear_history": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_conversation_resolution": {"enabled": True},
        "restrictions": None,
    }


def test_normalise_live_state_unwraps_bool_enabled_shape() -> None:
    normalised = abp._normalise_live_state(_recorded_get_protection_response())
    assert normalised["enforce_admins"] is True
    assert normalised["allow_force_pushes"] is False
    assert normalised["required_linear_history"] is True
    assert normalised["required_conversation_resolution"] is True


def test_normalise_live_state_strips_nested_readonly_fields() -> None:
    normalised = abp._normalise_live_state(_recorded_get_protection_response())
    assert "url" not in normalised["required_status_checks"]
    assert "contexts_url" not in normalised["required_status_checks"]
    assert "checks" not in normalised["required_status_checks"]
    assert normalised["required_status_checks"]["contexts"] == ["governance"]
    assert "url" not in normalised["required_pull_request_reviews"]


def test_normalise_then_diff_against_matching_desired_is_a_no_op() -> None:
    """AC4: re-applying identical settings must be a genuine no-op, not just
    a no-op between two hand-built flat fixtures."""
    desired = _valid_desired_state()
    payload = abp.to_api_payload(desired)
    live = abp._normalise_live_state(_recorded_get_protection_response())
    diff = abp.diff_state(live, payload)
    assert diff.is_empty(), diff.render()


def test_normalise_then_diff_detects_real_drift() -> None:
    desired = _valid_desired_state()
    payload = abp.to_api_payload(desired)
    raw_live = _recorded_get_protection_response()
    raw_live["required_pull_request_reviews"]["require_code_owner_reviews"] = False
    live = abp._normalise_live_state(raw_live)
    diff = abp.diff_state(live, payload)
    assert not diff.is_empty()
    assert diff.changed["required_pull_request_reviews"][0]["require_code_owner_reviews"] is False


# --- Merge queue (finding: merge_queue never applied or drift-checked) ----

def test_merge_queue_rule_params_shapes_ruleset_body() -> None:
    desired = _valid_desired_state()
    body = abp._merge_queue_rule_params(desired, "main")
    assert body is not None
    assert body["target"] == "branch"
    assert body["conditions"]["ref_name"]["include"] == ["refs/heads/main"]
    rule = body["rules"][0]
    assert rule["type"] == "merge_queue"
    assert rule["parameters"] == desired["merge_queue"]


def test_merge_queue_rule_params_none_when_not_configured() -> None:
    desired = _valid_desired_state()
    del desired["merge_queue"]
    assert abp._merge_queue_rule_params(desired, "main") is None


def test_diff_merge_queue_no_drift_when_matching() -> None:
    desired = _valid_desired_state()
    live_params = dict(desired["merge_queue"])
    diff = abp.diff_merge_queue(live_params, desired)
    assert diff.is_empty()


def test_diff_merge_queue_detects_drift() -> None:
    desired = _valid_desired_state()
    live_params = dict(desired["merge_queue"])
    live_params["merge_method"] = "MERGE"
    diff = abp.diff_merge_queue(live_params, desired)
    assert not diff.is_empty()
    assert diff.changed["merge_method"] == ("MERGE", "SQUASH")
