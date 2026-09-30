# Authoring workspace / 1.0

Status: implementing, user-authorized 2026-09-26. Owner: writing service. This extends the existing local database and immutable artifact revisions; it does not create a second manuscript model.

## World drafts

- `GET /api/v1/world-drafts` → `data: [{id,title,version,current_revision_id,created_at,updated_at}]`.
- `POST /api/v1/world-drafts` → `data: world`. Body: `title` (optional, defaults 未命名世界), `overview` (plain text), optional `world_seed: ba_starter`, or existing normalized world fields (`source_type`, `entities`, `rules`, `timeline`).
- `GET /api/v1/world-drafts/{id}` → `data: world`.
- `POST /api/v1/world-drafts/{id}` → `data: world`. Body: `expected_version` and edited fields. Omitted content fields retain their prior values. Stale versions fail with 409.
- `POST /api/v1/world-drafts/{id}:create-work` → `data: {work}`. Body: `expected_version`, optional `title`. Creates the normal work/volume/chapter shell and copies the selected world revision in the same work-creation transaction. No model call. The copy records original world and revision IDs; later edits are independent.

`world` includes `schema_version: world-draft/1.0`, list metadata, `content: {title,overview,source_type,entities,rules,timeline}`, and `history: [{id,world_id,ordinal,created_at,content}]` newest first. Drafts can exist when there are zero works. Draft authoring can begin with the overview alone.

Migration is additive (`world_drafts`, `world_draft_revisions`); normal repository initialization and restore initialization both create the tables. Existing per-work world IDs/revisions remain unchanged. Per-work `world_bible` now preserves `overview`; an older card editor that omits the field does not erase it.

## Outlines

- `GET /api/v1/works/{work_id}/outline` → `data: {schema_version: authoring-outline/1.0,work_id,version,documents}`.
- `documents` are ordered work → volume → chapters. Each contains `scope_type` (`work|volume|chapter`), `scope_id`, `title`, `text`, `revision_id`, `history`, `adopted_text`, `source_refs`, `source_changed`.
- With no saved outline document, work text is projected from adopted brief/blueprint, and chapter text from adopted chapter_plan. No AI call or write occurs on read.
- `POST` to the same outline URL takes `{expected_version,scope_type,scope_id,expected_base_revision_id,text}` and returns `{revision_id,outline,work}`. First save uses null/omitted base ID. Later saves require the current base ID. `text` permits empty text and up to 500,000 characters.
- Saved text is an `outline_document` artifact in the existing revision system. Further adopted planning does not silently overwrite it; `source_changed` indicates new source revisions and `adopted_text` exposes those contents for author-controlled merging. History is the normal revision array.
- Manual volume/chapter creation no longer requires a confirmed AI blueprint. AI generation still performs its own readiness checks.

## UI integration

Keep unsaved text by scope; switching sections or importing must not discard it. After 409 preserve the local draft and offer reload/compare rather than replacing the input. Use a fixed world-draft entry on the home/library surfaces, and a scope tree with readable multiline outline editor. Surface source_changed as a small compare/merge action; never auto-replace manual text.

Frontend main navigation and forms are owned by the Sol implementation agent. Backend module and the API contract are owned by the primary agent during this slice.

## Chapter manuscript and review

- `POST /api/v1/works/{work}/chapters/{chapter}/manuscript` accepts `{expected_version,scenes:[{scene_id,expected_base_revision_id,blocks}]}`. Send edited scenes only. Every scene must belong to this chapter. All revisions commit in one transaction, work version increments once, and any stale scene base causes the entire save to roll back. Response `{work,scene_revisions,superseded_proposal_ids}`. Existing block and scene IDs remain canonical; there is no separate chapter text store.
- Queue the one chapter check through existing `POST /api/v1/works/{work}/agent-jobs` with `{operation:"chapter.review",scope_id:chapter,request:{expected_version}}`. Existing job polling, lifecycle and provider pinning remain in use. The source snapshot is captured when queued.
- `GET /api/v1/works/{work}/chapters/{chapter}/review` returns `{schema_version:"chapter-review/1.0",id?,chapter_id,status,stale?,findings?,proposal?,result?,updated_at?}`. Status: `not_checked|running|failed|stale|blocked|awaiting_changes|complete`. Result includes progress step, completed scene IDs, continuity gate and memory proposal ID; failed states include an error. No poll may automatically adopt a proposal.
- The worker checks scenes internally, performs chapter-scoped continuity review, and produces one existing chapter `memory_bundle` proposal. Author-facing UI exposes a chapter action, not a chain of scene buttons. Completed stages can be reused on retry only for the same snapshot. Read-only review does not write manuscript revisions.
- `POST /api/v1/works/{work}/chapters/{chapter}/review:decide` accepts `{review_id,expected_version,decision:"accept"|"keep",selected_item_ids?}`. `accept` adopts the existing bundle through its normal validation; `keep` records the explicit author decision to keep current knowledge. With no proposed items, present “确认无新增变化” and send `keep`. Response `{review,work}`.
- Existing review finding resolution endpoints remain available. Results with blocking findings stay blocked even after changes are decided. Editing chapter text/order/contract or cited planning/knowledge marks the review stale. Existing scene histories remain intact.
- Once chapter changes are explicitly decided, release memory-maintenance checks can resolve that decision for the exact current chapter scene revisions. This is evidence from the chapter workflow, not an automatic skipped scene flag. Editing any scene removes that aggregate evidence for the whole chapter until rechecked.

## Unified document import

- `POST /api/v1/document-import/preview` with `{filename,content_base64}` parses TXT, Markdown or DOCX. Returns the existing story preview including `source_digest`, `normalized_text`, counts and chapter/scene analysis. No writes or model calls.
- `POST /api/v1/document-import/adopt` repeats those fields with `{source_digest,confirm:true,purpose,title?,work_id?,expected_version?}`. Purpose `manuscript` creates a new work through existing staged story adoption (use a stable `idempotency_key` per file). `world_draft` creates a new independent draft. `world` appends to the current work world overview, preserving cards/rules. `outline` appends to the chosen `scope_type/scope_id`, also requiring `expected_base_revision_id`. `reference` adds an unverified source attachment. Existing work mutations require its expected version. Never overwrite existing text implicitly.
- UI must display destination and append/new semantics before adoption, retain preview on errors, and refresh/open the target after success. Character/world JSON card import continues to use its existing validate/import endpoints and can be selected from this same entry. File selection alone must not persist a formal artifact. Unsupported formats should be clearly rejected, not silently treated as prose.

## Model capabilities and advanced configuration

- `GET /api/v1/settings/model-capabilities?model=...&provider=openai|anthropic&base_url=...` returns `known`, `source`, `source_url`, `catalog_version`, `context_window`, `max_input_tokens`, `max_output_tokens`, and protocol hints. Settings GET also returns `capability_catalog`.
- Existing fetch-models request accepts `include_metadata:true` and returns `{models:[ids],model_details:[capabilities]}`. Provider metadata overrides offline catalog for that model. Unknown values remain null.
- Existing test/save payload now accepts `context_window`, `max_input_tokens`, `max_output_tokens` (model capabilities), `max_tokens` (per-request output allowance), `temperature`, `top_p`, `thinking_budget`, `reasoning_effort` (`auto|none|minimal|low|medium|high|xhigh|max`), and `token_limit_parameter` (`auto|max_tokens|max_completion_tokens`). Null/empty optional values are permitted. Limits are independent of timeout. Keep prior saved custom overrides on reopening; offer a deliberate reset-to-preset action.
- Set a newly selected known model's request output allowance to its verified maximum. Never copy another model's limits while switching; provider-specific overrides are possible. Unknown models display capacity unknown and accept author supplied limits. Inputs/outputs cannot exceed context, nor can the request allowance exceed model output maximum.
- Protocol and service URL are primary fields above API key/model, always visible. Advanced fields can be grouped compactly. Connection probe uses the same transport parameter rules with a smaller probe allowance; real requests reserve remaining context for output and return a context error instead of silently dropping authored text.

The new APIs still require frontend integration and broader regression before the feature can be reported complete.

## Verification

`python -X utf8 -m pytest services/halocue/writing/tests/test_authoring_workspace.py -q`

Tests cover world-first creation, independent copies, stale world/outline conflicts, restore initialization, no-AI manual structure, adopted-direction projection and protected manual text, and HTTP round trips.
