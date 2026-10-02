# Local character-card reuse

Status: implemented in the overnight experience slice; additive writing-service endpoint.
Owner: writing context. No project-model migration or production contract change.

## User flow

In a work's **创作 → 资料 → 人物库 → 添加人物 → 从其他作品选取**,
choose a source work and character, then explicitly copy it. The result is an
independent card in the target work, initially `unverified`. Confirm adoption
separately in the existing character editor. The source work is never modified.

This is reuse of local curated material, not certification that a publisher
issued the card or that every character interpretation is an official fact.

## Endpoint

`POST /api/v1/works/{target_work_id}/character-cards:reuse`

Required body:
- `expected_version`: target work version shown during selection.
- `source_work_id`: existing distinct source work.
- `source_card_id`: stable character scope ID in that source work.
- `source_revision_id`: exact current revision reviewed in the picker.

Response uses the existing mutation envelope: `card_id`, `revision_id`, `work`.
No automatic update by name, no model invocation, no source-work mutation.

## Guarantees

- Target version, source ownership/current revision, archive state and target
  name/alias collision are checked inside one repository transaction.
- A conflict returns 409. The client can refresh both target version and source
  material, then explicitly select again. No automatic resubmission.
- Full `ba_profile`, source type, source hash, source references and validation
  report are retained. Adoption state is reset to `unverified` in the target.
- Raw/cleaned import files are checked against their existing byte hashes and
  copied into the target's import directory. Missing/mismatched files fail;
  reuse does not replace missing source evidence with fabricated JSON.
- `reuse_origin` and revision provenance retain source work/card/revision/hash.
  Evidence status on individual samples is not upgraded.
- Source-work relationship IDs are not bound to target-work characters.
  Descriptive relationships with names are retained; original structured profile
  remains intact and the source revision is traceable.
- Repeated requests cannot create duplicate identity cards: stale target
  versions or name/alias collisions fail instead of overwriting.
- The normal edit/adoption form retains structured source references and import
  metadata; textual source editing never stringifies evidence objects.

File writes use the existing atomic artifact writer. As in the existing import
path, a storage failure after one file write may leave an unreferenced artifact;
a rolled-back transaction never exposes a partially created character card.

## Evidence

- `services/halocue/writing/tests/test_character_card_reuse.py`: independent
  persistent bytes, profile/provenance, duplicate/stale/archive/missing-file/hash
  rejection, source-work immutability, relationship scope.
- `services/halocue/integrated/tests/test_production_navigation.py`: desktop and
  mobile picker, cancellation, long-list scrolling, pending-to-adopted flow,
  source/target conflict refresh without overwriting newer data.

All fixtures are synthetic and stored in temporary test directories. The real
reference library remains external user data; neither profiles nor story
corpus bytes are included in this repository.
