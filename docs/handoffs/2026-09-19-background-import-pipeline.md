# Background import pipeline repair

Date: 2026-09-19. Branch: codex/1.0-release-readiness-20260914. Local changes, no commit/PR.

## Root cause
The production rebuild endpoint only harvested background identities from historical AAP projects. It neither scanned unused overrides/bgs images nor built a matching preview manifest; adapter preview resolvers retained old settings.

## Change
- Import scans the selected workspace overrides/bgs (including subdirectories), validates image decoding, preserves known history/database IDs, and uses the existing bg_id contract only for unregistered installed override stems.
- Reads existing database Chinese labels/scene annotations read-only. Preserves previous same-workspace annotations and tracks source-relative paths, SHA-256 and ready/missing/unreadable/ambiguous status.
- Builds thumbnails and copies validated existing official/avatar cache records into an unpublished import generation, then atomically switches the settings pointer. Failure leaves the prior published generation intact; unselected failed output may remain for diagnosis.
- Same-name file collisions are reported, not arbitrarily selected. Repeat import detects deletion, moved files and broken images rather than resurrecting stale thumbnails. Switching workspaces does not carry over old override keys.
- Refreshes both catalogue and adapter preview resolvers. Existing task snapshots are not overwritten.
- UI import action reports preview-ready/total counts with expandable warnings; allows up to five minutes for the synchronous first import. Not yet a durable background import job.

## Verification
New service integration tests cover unused images, repeat import, labels, deleted/corrupt files, relocation, duplicates, failed settings publication, workspace switch and official-cache linkage. Targeted service/API and preview suite: 121 passed.
Real resource audit invoked the production import helper in a separate output directory, seeded with the existing known IDs: 2773 entries; 2307 ready; 407 unresolved; 59 ambiguous; 0 unreadable; 79.09 seconds. All five originally reported examples were ready. Did not run a full rebuild against the user's current task environment or alter AA projects.
Output outside repo: workspace output/2026-09-19-resource-import-validation/result.json and aa_resources.json.

## Remaining boundary
This patch reuses validated existing official preview caches; it does not newly extract uncached official Unity bundles. Entries with no located image remain reported as unresolved. These are not claimed fixed. The active isolated acceptance workspace is not repointed at the user's real AA installation. Source and UI loaded by restarting the idle integrated runtime; old tasks and settings retained.
