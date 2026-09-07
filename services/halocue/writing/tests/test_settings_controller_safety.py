"""Execute the production settings-controller methods with synthetic DOM/API IO."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
CASES = [
    "direction_status_timeout_changes_pending_to_unavailable",
    "hanging_production_does_not_block_writing_settings",
    "distinct_model_roles_are_shown_independently",
    "unavailable_direction_model_is_not_claimed_connected",
    "preset_switch_clears_key",
    "manual_endpoint_edit_clears_key",
    "protocol_edit_clears_key",
    "programmatic_endpoint_change_is_guarded_before_send",
    "same_endpoint_model_change_keeps_key",
    "new_key_after_switch_is_allowed",
    "stale_model_list_does_not_replace_new_endpoint_choices",
    "stale_connection_test_does_not_validate_new_credentials",
    "preset_environment_key_never_follows_manual_path_edit",
    "invalid_aa_detection_never_enables_adoption",
    "aa_adoption_requires_current_inspection",
    "valid_executable_detection_adopts_resolved_workspace",
    "edited_aa_selection_invalidates_detected_path",
    "out_of_order_aa_detection_keeps_latest_result",
    "missing_aa_path_or_truthy_valid_flag_is_rejected",
    "aa_adoption_rejection_is_not_success",
    "duplicate_aa_adoption_submits_once",
    "aa_display_escapes_backend_path_and_error",
    "backend_path_spelling_change_does_not_reuse_key",
    "saved_configuration_reload_clears_old_draft_key",
]


@pytest.mark.parametrize("case", CASES)
def test_settings_controller_safety(case):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the settings-controller behavior harness")
    result = subprocess.run(
        [
            node,
            str(HERE / "settings_controller_cases.cjs"),
            case,
            str(HERE.parent / "web" / "app.js"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    observation = json.loads(result.stdout)
    assert observation == {"case": case, "passed": True, "external_requests": 0}
