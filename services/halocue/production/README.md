# HaloCue 1.0 Production Backend

This directory is the isolated HaloCue 1.0 backend for converting an existing
script into a reviewable AzureArchive production draft, then compiling and
installing it after explicit gates pass.

It does not contain the writing backend. The integration boundary is a frozen
`ScriptRelease` submitted to the production API.

## Current vertical slice

- Create and persist a `ProductionRun` from inline script text.
- Scan script structure and speakers with the 0.9.3 document parser.
- Create a real 0.9.3-compatible `PerformanceDraft` in the 1.0 data directory.
- Query production runs, work items, gates, cards, and diagnostics.
- Inspect an AzureArchive executable, install directory, or data workspace with
  the 0.9.3 read-only discovery module, then explicitly adopt the detected workspace.
- Search characters, backgrounds, and sounds from the exported AA resource
  index without returning physical file paths.
- Update one speaker's cast binding with optimistic version checks.
- Edit, insert, move, and delete review cards while preserving stable card IDs.
- Resolve background requests in place and repair or explicitly remove invalid
  sound directives.
- Approve review cards and validate the compile gate.
- Create real immutable build snapshots and run the existing compiler when
  the resource index is configured.
- Install a completed build only when an AA workspace is configured.
- Run the browser workbench from the same service: source import, per-speaker
  mapping, card review/editing, background and sound resolution, real job
  polling, compile gating, install target preflight, and model settings are
  all backed by `/api/v1` rather than simulated client state.
- Keep AI direction model settings owned by 1.0. Public configuration and the
  secret are separate; a Windows-entered key is protected with current-user
  DPAPI, environment-variable secrets are supported, and no API response
  returns a secret.
- Direction jobs expose pause, resume, and end controls. A stop signal closes
  an active model stream when the provider supports it; completed chunks remain
  resumable and staged results are never committed after a stop.
- Each direction attempt keeps a sanitized audit in `result.json`, including
  request counts, retry/subdivision decisions, cache metrics, prompt hashes,
  and bounded request records. Prompts, source text, API keys, and reasoning
  text are not included in the public task log.
- The prompt catalogue is bounded to script-relevant resource candidates while
  the backend still validates every returned key against the complete frozen
  resource index. A compatible AI preflight is reused only when its source
  hash matches the current frozen script.

The 0.9 compatibility modules are loaded from the repository root through the
explicit `HALOCUE_LEGACY_ROOT` boundary (or the repository default). Runtime
data defaults to the repository `.halocue/production` user-data directory.
No AA resource bytes or runtime data are committed here.

## Run

```powershell
cd services/halocue/production
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m halocue_production.server --port 8892
```

Windows users can also run `启动1.0转换后端.cmd` directly.

Optional environment variables:

```text
HALOCUE_DATA_DIR       Persistent 1.0 state. Defaults to ./data
HALOCUE_LEGACY_ROOT    Read-only 0.9.3 Python modules
HALOCUE_RESOURCE_INDEX Resource index used by compilation
HALOCUE_AA_DATA        AA data workspace used by installation
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8892/api/v1/health
```

Open the production workbench at:

```text
http://127.0.0.1:8892/
```

The repository's optional `http.server` preview on port 8891 can render the
same UI files for layout work. It is intentionally allowed to call only the
local 8892 API origin; regular use should open the same-origin 8892 URL above.

## Browser workflow

1. Paste an existing script and create a frozen `ScriptRelease`.
2. Resolve each detected speaker as an AA portrait, a teacher identity, a voice-only role, a
   narrator, or deliberately unmapped. Portrait selection is per speaker;
   its Spine, portrait, and faces are not global settings.
3. For format-only tasks, enter review directly. For AI-direction tasks, the
   real background job runs only after a 1.0 model is configured and mapping
   diagnostics have passed.
4. Review cards one at a time, select frozen-index backgrounds or sounds in
   place, and approve them. Every mutation carries `expected_draft_version`.
5. Compile only after the API compile gate passes. A successful compile exposes
   an installation target preflight; installation remains an explicit write to
   the configured AA workspace.

Create a production run:

```powershell
$body = @{
  project = "第一章"
  generation_mode = "format_only"
  source = @{ kind = "inline"; text = "## 场景 01`n爱丽丝: 你好`n" }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post -ContentType application/json `
  -Body $body http://127.0.0.1:8892/api/v1/production-runs
```

## API contract

All endpoints are under `/api/v1`. Errors use stable codes:

```json
{"ok": false, "error": {"code": "review_pending", "message": "...", "details": {}}}
```

The service binds to `127.0.0.1` by default and sends restrictive local-app
security headers. Source text is accepted only in request bodies; arbitrary
client filesystem paths are not accepted by this first slice.

### Settings and capabilities

```text
GET  /api/v1/health
GET  /api/v1/capabilities
GET  /api/v1/settings/aa-workspace
POST /api/v1/settings/aa-workspace
```

The settings request is `{"path":"E:\\AzureArchive\\...\\data"}`. A valid
workspace must contain `projects`, `saves`, `overrides`, and `settings`.
The selected path is persisted only in `08-HaloCue-1.0/data/settings.json`.

### Production runs

```text
GET  /api/v1/production-runs
POST /api/v1/production-runs
GET  /api/v1/production-runs/{run_id}
POST /api/v1/production-runs/{run_id}/cast-bindings
POST /api/v1/production-runs/{run_id}/review/approve
POST /api/v1/production-runs/{run_id}/validate
POST /api/v1/production-runs/{run_id}/compile
POST /api/v1/production-runs/{run_id}/install
GET  /api/v1/jobs/{job_id}
```

### Teacher identity presets

Select a source speaker explicitly in the mapping dialog, choose Teacher, then
save one of the four presets or a custom name/organization. Opening the dialog
does not create a character. These settings need no model, AA executable or
portrait upload. They prepare a production-local no-portrait character before
generation; they do not rename the source speaker or writing release.

| `preset_id` | Name | Organization |
| --- | --- | --- |
| `sensei_shale` | sensei | 沙勒 |
| `sensei_xialai` | sensei | 夏莱 |
| `teacher_shale` | 老师 | 沙勒 |
| `teacher_xialai` | 老师 | 夏莱 |
| `custom` | User supplied, required | User supplied, may be empty |

Existing `POST /api/v1/production-runs/{run_id}/cast-bindings` request:

```json
{
  "speaker": "SourceTeacher",
  "expected_draft_version": 1,
  "mapping": {
    "kind": "teacher",
    "schema_version": "teacher-identity/1.0",
    "preset_id": "teacher_shale"
  }
}
```

For `custom`, also supply `display_name` and optionally `organization` in the
mapping. Each is single-line text of at most 80 characters. Presets do not accept
overridden display fields. The server, not the client, assigns the stable
`hc-teacher-<32 lowercase hex digits>` character ID.

The response's `draft.cast.teacher_identity` freezes the identity. Explicitly
bound source aliases share it; changing its name/organization updates those
aliases after confirmation. Ordinary voice-only roles are never automatically
converted. Repeating an unchanged choice keeps the ID, versions and review;
real changes require review again and supersede an active generation. The
compiler registers AA `CharacterOverrides` and slot 0 references this ID,
including in CG dialogue, without consuming any of the five portrait positions.

Capabilities expose `teacher_identity` with `state`, `schema_version`, `presets`
and `presentation: "slot_zero"`. Older external compatibility modules report
`unavailable`, while other mapping kinds remain usable. No route or database
schema was replaced. Single-response Sel presentation is a separate follow-up.

Stable errors include `400 teacher_identity_version_unsupported`,
`invalid_teacher_identity`, `invalid_teacher_preset`, `teacher_speaker_not_found`;
`409 revision_conflict`, `teacher_identity_conflict`, `teacher_identity_corrupt`,
`teacher_identity_journal_corrupt`, `teacher_identity_unavailable`,
`teacher_requires_no_portrait`; and `500 teacher_identity_write_failed`,
`teacher_identity_recovery_failed`, `teacher_identity_durability_uncertain`.
For an uncertain durability response, reload the draft before retrying. A
corrupt recovery journal is preserved for repair rather than silently discarded.

Teacher changes use a recoverable five-file transaction in the draft directory.
Old BuildBundles remain immutable and installation is always a separate action.
Native AA playback is manual acceptance; automated tests use synthetic fixtures.

### Review cards

```text
PATCH  /api/v1/production-runs/{run_id}/cards/{card_id}
POST   /api/v1/production-runs/{run_id}/cards
POST   /api/v1/production-runs/{run_id}/cards/move
DELETE /api/v1/production-runs/{run_id}/cards/{card_id}
POST   /api/v1/production-runs/{run_id}/cards/{card_id}/background-resolution
POST   /api/v1/production-runs/{run_id}/cards/{card_id}/sound-resolution
```

Every mutating draft request requires `expected_draft_version`. A stale
request returns HTTP 409 with `revision_conflict`. Background request cards
must be resolved through a dedicated workflow and cannot be deleted as a way
to bypass the compile gate.

Background resolution accepts either
`{"action":"select","background_key":"BG_..."}` or `{"action":"black"}`.
Sound resolution accepts either
`{"action":"select","sound_key":"SE_..."}` or `{"action":"remove"}`.
Every payload also requires `expected_draft_version`. Selected resources must
exist in the frozen resource index.

### Resource catalog

```text
GET /api/v1/resources/characters?q=alice&offset=0&limit=80
GET /api/v1/resources/characters/{identifier}
GET /api/v1/resources/backgrounds?q=classroom&offset=0&limit=80
GET /api/v1/resources/sounds?q=door&offset=0&limit=80
```

Results are paged and contain stable AA identifiers and display metadata. They
do not return local source or installation paths. Draft diagnostics and the
compile gate use the same frozen resource index, so an unregistered `@bg` or
`@se` directive cannot pass compilation merely because the UI missed it.

### Install preparation

```text
GET  /api/v1/production-runs/{run_id}/install-options
POST /api/v1/production-runs/{run_id}/install-check
```

These routes are available only for the run's latest completed build. They
return suggested categories and target conflict state without exposing AA
workspace paths. `install-check` accepts `category`, `story_name`, and an
optional `build_id`; it does not write to AA.

## Generation modes

`format_only` preserves the submitted script and performs deterministic
conversion. `ai_direction` uses the model Provider and credentials owned by
HaloCue 1.0; when the Provider is not configured the UI keeps the mode
selectable and takes the user to the model settings instead of silently
disabling the choice.

### Direction presets

`direction_profile` is independent from `generation_mode`, `story_type`, and
the existing `layout_mode` compatibility field. Supported presets:

| ID | Workbench label | Policy |
| --- | --- | --- |
| `standard` | 标准（原版） | Existing prompt and missing-background review workflow. |
| `conservative` | 简洁（保守） | Stable presentation, existing expression labels, best available frozen backgrounds. |

Create requests without this field remain `standard`. New workbench imports
explicitly select `conservative`; reopening an old run does not change it.
Generation requests without the field inherit the run's persisted selection.

Example body for `POST /api/v1/production-runs/{run_id}/direction-generation`:

```json
{
  "expected_draft_version": 2,
  "story_type": "auto",
  "direction_profile": "conservative"
}
```

The server pins a `direction_profile_snapshot` before calling the model:

```json
{
  "id": "conservative",
  "version": "1.0",
  "rules_sha256": "6bcc19fcda1e65617d3d69639ac5834f6147585f9b8fcef6067841f3d6c5dddf"
}
```

This sample identifies the `auto` rules. The profile version covers its policy;
change it when policy behavior changes. The actual rules hash, full static
prompt hash, resource hash, and background-plan hash also guard checkpoint
reuse. Clients cannot replace the server-owned snapshot by posting another one.
The snapshot is exposed in job/audit responses without prompt text or secrets.

Active requests only deduplicate within the same profile/rules. Pause/retry
retains the old snapshot; switching requires a new generation and confirmation
in the workbench. Rule upgrades reject old recovery with
`409 direction_profile_changed`; invalid selections use
`400 invalid_direction_profile`, active mismatches use
`409 direction_profile_conflict`. Capability discovery reports available
presets; older external annotation modules retain Standard and reject
Conservative with `409 direction_profile_unavailable`.

Conservative generation retains a valid model-selected background. If omitted,
the backend ranks the frozen labels using scene context, respects authored and
confirmed selections and inherited scenes, then supplies an available fallback.
Approximate matches become `background_approximate_match` review advice, not
image-generation requests. Ranking scores are not confidence probabilities.
Empty catalogues and unresolved references fail with stable
`background_catalog_empty` / `background_not_in_manifest` codes. No additional
vision or image-provider call is introduced, and source dialogue is unchanged.

Regeneration works from the current draft and preserves its existing authored
directions; it is not a reset to the original release. Results still require
review, and compilation never implicitly installs the build. Real-provider
quality and monetary savings require a separate user-authorized comparison.

## Ownership boundary

The future writing service owns ideas, outlines, prose, and revisions until it
publishes an immutable `ScriptRelease`. This service owns everything after
that handoff: structure inspection, cast mapping, performance draft review,
deterministic compilation, and explicit installation into AA.

The production API verifies the upstream release content hash, preserves its
identity separately from the production-local frozen release, and returns the
existing run when the same upstream release is submitted again. The complete
compatibility contract is documented in [WRITING_HANDOFF_CONTRACT.md](WRITING_HANDOFF_CONTRACT.md).
