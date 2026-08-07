# Structured Preflight Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent malformed model responses from appearing as a successful empty scene plan, retry once with a strict JSON repair prompt, and expose an actionable diagnostic when the provider cannot honor the structured-output contract.

**Architecture:** Keep provider parsing and schema validation in `llm.py`, where every structured call can share the same contract check. Keep preflight-specific retry and user-facing diagnostics in `webui.py`; valid responses continue through the existing normalization path unchanged. The UI only needs the existing `ai_status`, `ai_diagnostics`, and issue fields.

**Tech Stack:** Python standard library, existing `pytest` suite, existing OpenAI-compatible provider abstraction.

## Global Constraints

- Preserve all unrelated dirty-worktree changes.
- Do not parse arbitrary Markdown into executable scene directives.
- A response is successful only when it is a JSON object with the required preflight fields and valid nested scene entries.
- Keep credentials and physical source paths out of diagnostics returned to the browser.

### Task 1: Add failing structured-response tests

**Files:**
- Modify: `tests/test_preflight.py`
- Modify: `tests/test_llm.py` if the existing provider tests are located there; otherwise add the smallest focused test module beside the existing LLM tests.

**Interfaces:**
- Tests will exercise a public or module-level validator in `llm.py` and the existing `_preflight_result` flow with a fake provider.

- [ ] Add a test proving Markdown or a JSON object missing `usage_chain` is rejected as an incompatible structured response.
- [ ] Add a test proving a valid four-segment response is accepted unchanged.
- [ ] Add a test proving preflight retries once after an incompatible response and reports `ai_status=completed` when the retry is valid.
- [ ] Run the focused tests and confirm they fail before production changes.

### Task 2: Implement local structured-response validation

**Files:**
- Modify: `llm.py`

**Interfaces:**
- Add a validator that accepts the parsed response and schema, returning the response or raising `LLMError` with a bounded diagnostic.
- `Provider._complete` will invoke validation after JSON parsing and before returning the value.

- [ ] Validate the top-level object and required keys from the supplied schema.
- [ ] Validate `usage_chain` segment objects and `needs` objects when present, including required string/array/number types.
- [ ] Keep the error message free of model output and secrets; include only the missing/invalid field path.
- [ ] Run the focused validator tests and confirm they pass.

### Task 3: Add one bounded preflight retry and user-facing diagnostics

**Files:**
- Modify: `webui.py`
- Modify: `tests/test_preflight.py`

**Interfaces:**
- `_preflight_result` will retry `provider.complete_json` once with a strict JSON-only repair instruction after a structured-response `LLMError`.
- On a second failure it will set `ai_status="failed"`, `usage_chain_status="unavailable"`, and populate `ai_diagnostics.stage="structured_output"`.

- [ ] Ensure the first call uses the existing prompt unchanged.
- [ ] Ensure the retry adds explicit JSON-only instructions without asking the user to write AA directives.
- [ ] Preserve the existing rule-analysis fallback and show an issue whose action tells the user to change/test the model profile.
- [ ] Run focused preflight tests.

### Task 4: Verify the real workflow and regression suite

**Files:**
- No new production files.

- [ ] Run all focused LLM and preflight tests.
- [ ] Run the complete `pytest -q` suite.
- [ ] Submit the real `本日行程全部作废.txt` preflight request and verify the UI result is either a valid scene chain or an explicit structured-output failure, never a false empty success.
- [ ] Record the final test counts and remaining external-provider risk.
