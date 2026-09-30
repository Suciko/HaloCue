# Embedded IAB task isolation and dark-surface acceptance

- Date: 2026-09-18; owner: embedded production/writing UI.
- Status: implemented locally; uncommitted/unpushed; existing dirty tree preserved.
- Branch: codex/1.0-release-readiness-20260914; parent issue #15.
- Scope: user-authorized detailed in-app-browser QA, fixes for demonstrated navigation/context and dark-mode problems. No canonical schema or persisted API contract change.

## Evidence and fix
Real IAB startup showed a 20-card target run with another saved run's 15 approved cards and compiled state. Embedded boot raced restoreSavedRun against simulated recent-row click. It now exposes readiness/open-by-ID on its own shell, suppresses standalone auto-restore only in embedded mode, and gates delayed selection/refresh/preflight/catalog results. Standalone boot retains restoration.
Production emits a browser-only context event from the loaded run. Writing route carries productionWorkId separately from state.work; independent imports do not inherit an unrelated work. The topbar and review title reflect the loaded run. Removed initial-URL label caching; label sanitizer excludes the dynamic runTitle. Full direct-ID selection no longer depends on the latest eight recent-list entries.
Dark fixes cover first-step judgement metrics/cards/footer, narrow-column evidence layout, and writing Agent pending proposal notice. Compile blocker uses existing localized labels. Writing/production scripted scrolls respect reduced motion.

## Validation
- node --test services/halocue/writing/tests/production_context.test.cjs services/halocue/writing/tests/theme_preference.test.cjs: 15 passed. Synthetic delayed IO tests execute shipping functions.
- python -X utf8 -m pytest -q services/halocue/integrated/tests/test_gateway.py: 10 passed.
- python -X utf8 -m pytest -q services/halocue/production/tests/test_service.py services/halocue/production/tests/test_http_api.py: 107 passed.
- node --check on production app, writing app/workbench/embed; scoped diff whitespace check pass.
- Real IAB: independent deep-link and reload show20 pending; standard21 pending; in-page switch synchronizes both titles and URL. Dark first-step/Agent, desktop review,390px mobile candidate navigation verified. Viewport and prior system theme restored. No browser error logs in inspected scope.

## Boundaries / next
No paid model request, new run, proposal adoption, approval, compilation, installation or modification of existing story data. The synthetic first-step input only called read-only script-preflight. Application feedback sync remains its existing startup behavior. No full-suite claim.
Still test live generation cancellation/recovery, focus/scroll under late completion. Card4 preview visibly has background/text/face label but character sprite was not verified; inspect rendering availability separately. Source/new-task versus active-run semantics and startup flash warrant follow-up. No step disappearance reproduced this time.
Maintainer-local evidence: <LOCAL_IAB_INSPECTION>/RESULT.md, ISSUE_LOG.md, final-read-checks.json and11 screenshots. No user data/assets/secrets copied into repository.
