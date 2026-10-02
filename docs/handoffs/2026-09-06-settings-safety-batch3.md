# Settings safety batch 3 — local handoff

- Date: 2026-09-06; HaloCue application 1.0.0.
- Baseline: `f4199e1`, stacked after recovery batches 1 and 2.
- Branch: `codex/1.0-settings-safety-batch3`.
- Received-review IDs: `06-F01` (typed credentials cross endpoints), `06-F03`
  (AA detection validity and adoption request contract).
- GitHub issue lookup returned `Post https://api.github.com/graphql: EOF`; no
  issue/PR number is claimed. Keep these review IDs until tracker reconciliation.
- Local changes only, not a merged mainline or published desktop build.

## Root causes and changes

### Credential identity at the unified settings form

The backend already rejects implicit reuse of persisted credentials after an
endpoint/protocol change. The UI defeated that boundary by sending a still-filled
password field as an explicitly entered *new* key for the new endpoint.

- A form endpoint identity includes protocol and normalized HTTP(S) endpoint.
  The UI folds only the documented endpoint suffixes/trailing slash and default
  port/host spelling; it keeps raw path spelling instead of allowing URL parsing
  to collapse dot segments that the backend does not collapse.
- Preset changes and endpoint/protocol input/change events clear the unsaved
  password field, reset password visibility and show a re-entry explanation.
- All three send paths (model list, connection test, save/activate) recheck the
  endpoint immediately before building their credential fields. Programmatic
  field edits cannot rely solely on an input event having fired.
- The preset's `api_key_env` is sent only if the form still targets that preset's
  endpoint/protocol. A custom edited address cannot inherit the old preset's
  environment credential reference.
- Same-endpoint model changes keep the typed key. Re-entering a new key after
  changing endpoints works. Backend persisted-key isolation remains unchanged.
- Late model-list/connection-test results do not validate or overwrite an edited
  endpoint/model/key draft; request snapshots contain only nonsecret identity and
  a local draft revision, never a second copy of the key.

This is a form correctness fix, not a complete redesign of writing/direction
settings, pricing, provider capabilities or server-side activation semantics.
The backend still owns endpoint validation and actual encrypted credential storage.

### AA inspection and adoption

- Detection reads `environment.workspace.valid === true` and a nonempty resolved
  `workspace.path`. HTTP 200 / top-level `ok` means only that detection ran.
- The usable result is bound to the original selection plus a local inspection
  revision. Editing the selection clears it; older responses cannot re-enable
  adoption after a later detection or edit.
- Adoption requires a current inspection and sends `{path: resolved_workspace}`
  to the existing `/settings/aa-workspace` endpoint. An EXE/install-directory input
  is not passed as a data path; the old `{aa_data: raw}` request is gone.
- Pending adoption blocks duplicate requests and disables editing/detection until
  its response. The backend still revalidates directory structure at adoption.
- Success requires a valid confirmed workspace with the expected resolved path.
  Rejection/mismatched responses require inspection again, not a success toast.
- Backend paths/error descriptions rendered in the inspection card are escaped.
  The UI does not claim that a structurally valid directory includes all resources.

## Regression method

- First observe RED on the current controller: changing preset retained the key.
  Add manual/programmatic protocol/address changes and old preset environment
  references; apply the minimal fix, then GREEN.
- Add RED tests for model-list/test responses from a previous draft overwriting
  the new endpoint state; suppress stale results and rerun.
- Observe RED for AA HTTP success misread as valid, uninspected adoption, wrong
  resolved path; fix the consumer while preserving server-side validation.
- Additional synthetic cases cover equivalent endpoint/model changes, new-key
  entry, path edits, malformed detection, out-of-order responses, duplicate
  adoption, directory rejection, and escaped display content.
- Node harness evaluates actual `SettingsController` methods with stub DOM/API IO;
  it is not proof of full-browser behavior or real model acceptance.
- A separate headless browser test uses actual `index.html` and the current
  controller in a real DOM, with API/fetch stubs and all network navigation
  blocked. It verifies actual input/click handlers; it does not boot the whole
  application or use production keys/directories.
- A loopback HTTP test verifies the real production detection/adoption contracts,
  including valid resolved path, rejection of the former wrong field, and a
  directory becoming invalid after detection. All directories are synthetic.

## Boundaries deliberately unchanged

- No backend provider/credential-store implementation, schema migration, new
  dependency or API route changes.
- No automatic AA installation, real model call, real credential or user data use.
- No direction/standard/conservative prompt change, teacher/Sel change, or 1.1 edit.
- This does not resolve all of `06-F06` (separate writing vs direction model status),
  all frontend presentation issues, or the still-missing independent group-04 audit.
- `saveModel` still uses the existing explicit activation scope and sequential
  writing/direction activation semantics. This batch does not promise a distributed
  atomic activation across both services or cancel an already-issued request.
- Model/environment settings UI testing is not Windows packaged/WebView2 release
  acceptance and not actual AA playback acceptance.

## Next bounded area

Continue with effective model configuration/retry identity or the writing-vs-direction
settings status mismatch as separate slices; do not expand this branch into adaptation,
usage accounting or acting/compiler semantic changes.


## Final verification (Windows, Python 3.13.12)

- Initial focused backend/UI-related selection before edits: **30 passed** across
  `test_settings_hub.py`, `test_model_candidate_binding.py` and production settings tests.
- Red-to-green controller test: preset endpoint change retained a synthetic key before
  the fix; after the fix, **20 synthetic controller cases passed**, later expanded to
  **20/20** by the scoped review.
- Browser/controller and production contract validation after final edits:
  `python -X utf8 -m pytest services/halocue/writing/tests/test_settings_controller_safety.py services/halocue/writing/tests/test_settings_controller_browser.py services/halocue/production/tests/test_http_api.py -k "settings_controller_safety or settings_controller_browser or detect_then_adopt or file_source_and_aa" -q`
  — **23 passed, 21 deselected**.
- Final broad regression after final source state:
  `python -X utf8 -m pytest services/halocue/writing/tests services/halocue/integrated/tests services/halocue/production/tests/test_settings_direction.py services/halocue/production/tests/test_http_api.py tests/test_direction_profiles.py tests/test_conservative_annotation.py -q`
  — **exit code 0**. The full log is in the maintainer-local batch output; it was run against the final state and completed without reported failures.
- `node --check services/halocue/writing/web/app.js` — passed.
- `node --check services/halocue/writing/tests/settings_controller_cases.cjs` — passed.
- Ruff check/format on new tests — passed; `git diff --check` — passed.
- Scoped read-only code review — no in-scope blockers found.

No real credentials, provider calls, external network, actual AA workspace, install,
playback, or packaged Windows/WebView2 acceptance was performed. The browser test
uses the actual HTML/controller with synthetic API/fetch responses and blocked network.
