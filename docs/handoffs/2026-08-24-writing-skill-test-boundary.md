# 1.0 Writing Skill test boundary handoff

- Status: implemented and verified locally
- Branch: `feature/1.0-runtime`
- Related issue: GitHub #16
- Owner contexts: backend and AI GalGame

## Objective

Make the migrated 1.0 writing suite reproducible without requiring a
maintainer's private `ba-writing` checkout, while preserving the production
rule that real BA writing fails closed unless an authorized external Skill is
configured.

## Changes

- `services/halocue/writing/tests/conftest.py` creates a complete synthetic
  WritingPack under the process temporary directory and points the test process
  at it.
- `services/halocue/writing/tests/test_ba_skill_runtime.py` verifies that the
  default test registry can materialize and assemble the synthetic pack.
- The integrated and writing READMEs document the external Skill startup
  boundary and the synthetic-only test behavior.
- No character data, official corpus, model credential, API key, local path, or
  private Skill body was added to the repository.

## Runtime verification

An authorized maintainer-local Skill checkout was injected through
`HALOCUE_BA_WRITING_SKILL_DIR` without recording its absolute path. The migrated
integrated runtime reported:

```text
ba_writing_skill.status = ready
available_file_count = 16
missing_files = []
configured_by = HALOCUE_BA_WRITING_SKILL_DIR
```

A temporary copy of the legacy 1.0 writing state loaded the existing real model
configuration. One synthetic work-discussion request completed through the real
Provider with 9,361 input tokens and 727 output tokens. The assistant message,
question, and tool activity were persisted. It created no Proposal and no
formal write was accepted. Dollar cost remains unverified because the active
model has no configured pricing table.

## Verification

```text
PYTHONPATH=services/halocue/writing/src
python -m pytest -q services/halocue/writing/tests
558 passed in 287.09s

PYTHONPATH=services/halocue/production/src
python -m pytest -q services/halocue/production/tests
84 passed in 20.95s

PYTHONPATH=services/halocue/production/src;services/halocue/writing/src;services/halocue/integrated/src
python -m pytest -q services/halocue/integrated/tests
9 passed in 10.85s

python -m ruff check services/halocue/writing/tests/conftest.py services/halocue/writing/tests/test_ba_skill_runtime.py
All checks passed

node --check services/halocue/writing/web/app.js
node --check services/halocue/writing/web/writing-workbench.js
node --check services/halocue/writing/web/production-embed.js
node --check services/halocue/writing/web/shell.js
node --check services/halocue/production/ui/app.js
node --check services/halocue/integrated/static/integration-shell.js
All checks passed

python -m compileall -q services/halocue
Passed
```

## Remaining boundary

- Each maintainer must configure an authorized local Skill checkout before real
  BA writing. The repository must not discover or persist a machine-specific
  absolute path.
- `/api/v1/health` is the startup authority for both Provider and Skill
  readiness.
- A completed Provider run with token usage is not evidence of dollar cost when
  the model pricing table is unavailable.

## Next action

Run browser acceptance against the migrated repository using the maintainer's
normal writing data directory, then continue the Issue #16 scene Proposal slice
without changing the Proposal-to-Revision boundary.
