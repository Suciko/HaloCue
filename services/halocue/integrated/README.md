# HaloCue 1.0 Integrated

This directory is the composition root for HaloCue 1.0. It does not duplicate
the writing and AA production domain implementations; it imports the sibling
packages under `services/halocue`.

- `/` serves the writing workbench from `services/halocue/writing`.
- `/api/v1/*` serves the writing API.
- `/?section=production` opens AA production inside the writing-owned shell.
- `/production/api/v1/*` serves the AA production API.
- `/production/*` also carries production-owned static assets; it is not a page entry.

The browser receives one origin. The writing service still hands off only an
immutable `ScriptRelease`; production owns its own frozen source copy and
`ProductionRun`.

The writing document is the single application page. Selecting AA production
mounts the production workbench into that document without navigating to a
second page: the full-width top bar and primary navigation stay mounted, while
the contextual second column and central task surface switch to production.
The production UI runs in an isolated ShadowRoot and continues to call its own
`/production/api/v1` domain. Opening `/production`, `/production/`, or
`/production/index.html` redirects to the single application entry at
`/?section=production`; the embed-only HTML fragment requires an internal
request marker and is not a second browser entry. Mobile uses the same
single-page route and preserves the current Work, ScriptRelease, and
ProductionRun.

`GET /integration/manifest` returns the composition identity and ownership
boundary. Its `build.id` is the stable integrated workspace build ID, not a Git
commit: this directory and the workspace root are not Git repositories. The
page also exposes `window.HaloCueIntegrationDiagnostics.snapshot()` for
read-only acceptance checks of the document, shell node, History navigation,
ShadowRoot mount, and visible work surface. It does not include work content,
Provider inputs, cache payloads, tokens, credentials, or internal parameters.

The four-viewport same-document baseline for build
`halocue-integrated/1.0.0+20260819.1` is stored under
`artifacts/acceptance/integrated-shell/2026-08-17/`. Build `.2` closes the
remaining standalone production entry; its redirect and internal-fragment
contracts are covered by `tests/test_gateway.py`. Build `.3` makes section
switching single-owner: the integrated shell only closes the embedded
production surface, while the writing router owns the destination URL and
active navigation. A user navigation during startup also cancels a stale
production deep-link restore. Build `.4` prepares the local production
ShadowRoot during browser idle time, or immediately when its navigation item
receives pointer or keyboard intent. Warm-up performs only the production
client's existing read-only boot requests; it does not create a run, call a
model, install content, or change writing data. Its state and elapsed time are
available through the existing integration diagnostics snapshot.
Build `.5` preserves unsaved scene blocks across writing-surface redraws and
requires an explicit discard decision before leaving the scene, work, asset
library, or production surface. Reload and window close use the browser's
native unsaved-change warning. No draft is silently written to a Revision.
Build `.6` adds the scene-asset handoff adapter at the composition boundary.
It verifies frozen resource identities and hashes, creates a ProductionRun
receipt, and writes the confirmed task-copy identity back through the writing
service's existing reconciliation contract. Custom-library references must
match their frozen source snapshot and file SHA-256 before a run is created.
Build `.7` corrects the embedded production mapping cards to use each
speaker's parsed line count instead of the whole script's dialogue count. The
underlying production summary already owns this data; the integration layer
only adapts the embedded presentation and does not add production state.
Build `.8` preserves writing deep links while the integrated shell restores a
selected Work. Build `halocue-integrated/1.0.0+20260821.9` also preserves the
production deep link while its ShadowRoot and selected ProductionRun restore;
the writing router no longer replaces that URL with the Works overview. The
gateway regression now continues the one-sentence closed loop through isolated
production review, deterministic compile, install preflight, installation, and
duplicate-install rejection without writing to a user AA workspace.

## Start

```powershell
$env:PYTHONPATH='services/halocue/integrated/src;services/halocue/writing/src;services/halocue/production/src'
$env:HALOCUE_BA_WRITING_SKILL_DIR='<LOCAL_BA_WRITING_SKILL_DIR>'
python -m halocue_integrated.server --port 8910
```

The default runtime writes to `.halocue/integrated/writing` and
`.halocue/integrated/production`. Use `--writing-data-dir` and
`--production-data-dir` for isolated QA.

`HALOCUE_BA_WRITING_SKILL_DIR` must point to an authorized local Skill checkout.
The repository does not contain or discover a maintainer-specific absolute
path. After startup, `GET /api/v1/health` is the authority: its
`ba_writing_skill.status` must be `ready` and `missing_files` must be empty
before real BA writing operations are available.

## Current model boundary

The integrated runtime mounts the writing Provider configuration owned by
`services/halocue/writing`; it does not select or copy a second Provider. The
current durable configuration may be Fake or a real OpenAI-compatible model,
and the `/api/v1/health` response is the authority for the active runtime.
Real model calls, token accounting, cache observations, and cost evidence are
only claims when that response and a completed agent run provide them. The
current Gemini relay run has usage evidence, while pricing remains unavailable
because the relay's billing table and a user cost ceiling were not supplied.

## Feedback server

The writing side stores feedback locally first. To sync it to the dedicated
HaloCue endpoint in `work buddyapi反代`, set these variables before starting
the integrated runtime:

```powershell
$env:HALOCUE_FEEDBACK_REMOTE_URL = "https://your-server.example/api/halocue/feedback"
$env:HALOCUE_FEEDBACK_REMOTE_TOKEN = "the-server-bearer-password"
启动HaloCue1.0.cmd
```

The token is read only by the local Python service and is never sent to the
browser. When the remote endpoint is unavailable, the local report remains in
`writing.db` with `remote_status=pending` and is retried on the next startup.
