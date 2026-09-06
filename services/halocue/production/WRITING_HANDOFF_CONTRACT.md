# HaloCue Writing -> AA Production Handoff

Status: integration baseline for HaloCue 1.0

## Boundary

The writing application owns:

- `Work`, `Volume`, `Chapter`, and `Scene` structure;
- accepted manuscript revisions and review findings;
- the versioned `ba-writing` WritingPack;
- immutable `ScriptRelease` files and their manifest.

The AA production application owns:

- its local frozen source copy;
- cast and resource mapping;
- `PerformanceDraft`, review state, CG segments, and custom assets;
- deterministic compilation, installation, and export.

The handoff is one-way. Production must never edit a writing revision or an
upstream `ScriptRelease`. A new writing release creates or selects a separate
production run; it does not overwrite a reviewed draft.

## HTTP Contract

The writing application submits:

```http
POST /api/v1/production-runs
Content-Type: application/json
```

```json
{
  "project": "作品名 · v1",
  "generation_mode": "format_only",
  "source": {
    "kind": "inline",
    "text": "## 场景 01\n爱丽丝: 我们开始吧。\n"
  },
  "script_release": {
    "schema_version": "1.0",
    "id": "release-000000000001",
    "work_id": "work-000000000001",
    "display_version": "v1",
    "content_hash": "<lowercase sha256 of source.text>",
    "writing_pack_version": "ba-writing.productized/1.0.0"
  }
}
```

Required upstream identity fields are `id`, `display_version`, and
`content_hash`. `work_id`, `schema_version`, and `writing_pack_version` are
optional during the compatibility period.

Production verifies the SHA-256 before creating any local file. A mismatch
returns `409 script_release_hash_mismatch`.

## Identity And Idempotency

The two release IDs have different ownership:

- `run.release_id`: the production-side frozen copy used by the AA pipeline;
- `run.source_summary.upstream_release.release_id`: the writing-side immutable
  release that authorized the handoff.

They must not be merged or reused.

Submitting the same upstream `release_id` and content hash again returns the
existing `ProductionRun` with HTTP 200 and `handoff.idempotent=true`. The first
submission returns HTTP 201. Reusing the same upstream ID with different
content returns `409 script_release_identity_conflict`.

The production capability document exposes `script_release_handoff` so the
writing application can verify compatibility before enabling its handoff
button.

## WritingPack Preparation

The current writing application already has a versioned workflow description,
scene-local context snapshots, runtime character cards, Proposal/Diff writes,
AgentRun audit records, release review gates, and immutable releases.

The current `ba-writing` skill is still a development-time filesystem package.
It must not be loaded from its absolute workstation path in a release build.
Productization should create a distributable WritingPack with:

- a manifest containing pack and template versions;
- exactly one selected mode per scene;
- common writer rules and optional Sensei rules;
- runtime character cards rather than the full character archive;
- prompt assembler and validators as packaged implementation assets;
- source/license metadata for every bundled knowledge asset;
- a content hash for every file and the complete pack.

The writing Provider should receive a fully assembled, version-pinned scene
context. It should not discover skill files dynamically or write directly to
accepted manuscript revisions.

### Baseline recorded on 2026-08-14

- `09-HaloCue-1.0-Writing`: 44 tests passed.
- Focused `ba-writing` contract/validator/prompt tests: 132 passed, 5 failed.
- The five skill failures share one root cause: `knowledge/characters/春原瞬.json`
  has an illegal trailing comma at line 51, column 50. Because the card cannot
  be parsed, its legacy aliases `春原瞬（幼年）`, `春原瞬_幼年`, and `雪玲` also
  fail to resolve.

This character-card defect must be fixed in the skill's own maintenance flow
before creating a distributable WritingPack. The AA integration does not edit
the external skill package.

## Deferred Until UI Merge

- replace the writing-side project-name lookup with release-identity lookup;
- show writing origin and release version in the AA task header;
- add an explicit "return to writing release" link in the shared shell;
- model upgrades from one ScriptRelease to another with an impact Diff;
- unify writing WorkItems and production jobs in the shared task center;
- package and license-review the real `ba-writing` WritingPack.
