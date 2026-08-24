# BA editor context

## Responsibility

The BA editor provides a beginner-friendly story editor plus an advanced node
and event view. It imports user-provided or explicitly permitted BA data and
maps semantic story lines to AA and MMT presentation fields.

## Invariants

- The editor edits `HaloCueProject`; StoryForge `StudioProject v2` is generated
  only at the adapter boundary.
- Every node, line, character, asset, and branch has a stable ID.
- Validation reports errors, warnings, and informational findings with stable
  diagnostic codes before preview or export.
- Importers are explicit and schema-versioned. They do not silently scrape,
  decrypt, or copy private game formats.
- The editor can reproduce AA-style BA presentation coordinates, logical
  resource keys, relative locations, and resource roles. Real BA/AA images,
  audio, models, and bundles are loaded from a user-owned or authorized local
  manifest; verified staging stays in user data and public fixtures remain
  placeholders.
- Simple mode hides implementation-heavy controls; advanced mode exposes them
  without changing their semantics.

## Stage layout contract

- The editor has five visible portrait positions: `1`, `2`, `3`, `4`, and `5`.
- Position `0` is reserved for narration or an off-screen speaker with no
  portrait. It is a compatibility slot, not a visible stage position.
- AAP compatibility serializes `characters` as six entries (`0..5`), but the
  user-facing model and all 1.1 copy must say “five visible positions”.
- A shot may contain at most five visible characters. `@move` and `@stage`
  validation use the same `1..5` range.

## Collaboration

The primary implementation stream is `feature/1.1-ba-editor`. Shared model or
contract changes land through `chore/contracts` and must include migrations and
consumer tests.
