# Remove standing scene prompt chips — 2026-09-25

Local user-approved simplification on codex/1.0-release-readiness-20260914. Follows scene-composer-polish handoff; no backend or policy changes.

Removed sceneAgentQuickActionsMarkup and its invocation from the current scene composer, including saved-manuscript and pending-candidate generic prompts. Removed now-unused data-scene-agent-prompt click branch. Existing text-selection/review-target affordances, review link, candidate generation, permission menu, stop/send, save notice and auto-height remain unchanged. No new permanent helper text added.

Changed app.js and its index.html resource tag, test_scene_detail_polish.py, test_scene_composer_polish.py, test_scene_message_ui.py. Tests assert absence in empty/ready/existing/pending states. Removed obsolete chip-append tests and updated candidate fixture extraction to the surviving generation handler (first run had 44 passes/4 setup errors due to its old removed anchor; fixed and rerun).

Final command: python -m pytest services/halocue/writing/tests/test_scene_detail_polish.py services/halocue/writing/tests/test_scene_composer_polish.py services/halocue/writing/tests/test_change_review_ui.py services/halocue/writing/tests/test_scene_message_ui.py -q — 48 passed. node --check app.js and scoped git diff --check passed. Existing clean internal-browser preview tab 8 reloaded and screenshot confirms no chips, permission/send retained. Original user tabs untouched. No model calls, user manuscript changes, commit/push/deployment. Local slice, not full-suite verification.
