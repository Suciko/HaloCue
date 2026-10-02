"""Execute the production settings-controller methods with synthetic DOM/API IO."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
CASES = [
    "provider_free_access_badges_are_visible_searchable_and_escaped",
    "paid_or_custom_providers_do_not_keep_free_access_labels",
    "known_model_auto_fills_limits_and_maximum_output",
    "switching_unknown_model_drops_previous_limits",
    "fetched_provider_limits_override_catalog_automatically",
    "id_only_provider_does_not_mislabel_catalog_parameters",
    "stale_capability_response_never_fills_new_model",
    "manual_override_is_not_replaced_by_inflight_detection",
    "automatic_limits_finish_before_activation_payload",
    "preset_connections_are_automatic_custom_stays_editable",
    "provider_links_reject_non_https_and_embedded_credentials",

    "activation_replaces_old_test_with_current_result",
    "expanding_saved_writing_model_to_aa_uses_server_side_credential_relay",
    "activation_failure_focuses_visible_result_after_refresh",
    "activation_result_scrolls_inside_settings_above_footer",
    "advanced_limits_are_identical_in_test_and_activation",
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


@pytest.mark.parametrize(
    "case",
    [
        "preference_load_failure_is_visible_and_nonblocking",
        "preference_success_clears_warning_but_keeps_readonly",
        "preference_missing_payload_is_not_silent_success",
        "preference_stale_load_does_not_replace_latest_warning",
    ],
)
def test_user_preferences_controller_safety(case):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the preferences-controller behavior harness")
    result = subprocess.run(
        [
            node,
            str(HERE / "user_preferences_controller_cases.cjs"),
            case,
            str(HERE.parent / "web" / "app.js"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"case": case, "passed": True, "external_requests": 0}
