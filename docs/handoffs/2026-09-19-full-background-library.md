# Full background library — 2026-09-19

Branch: codex/1.0-release-readiness-20260914. Local change, no new issue/PR or push in this turn.

## Root cause
The acceptance runtime used a one-background resource index, and task pickers only read frozen task resources. Fixing a thumbnail did not restore the library.

## Changes
- Background resource requests support `scope=library` and `group=scene|cg|custom`. Default API scope stays frozen for compatibility. Library scope overlays existing frozen entries without replacing their identities.
- Picker and embedded asset browser request the full catalogue; group filtering runs before pagination. Chinese annotations remain searchable.
- Background replacement/insertion stages only the selected resource and its labels under the draft lock. Stale versions and rejected edits leave the resource snapshot unchanged. Invalid insertion anchors are rejected.
- Concurrent thumbnail requests share the parsed resource catalogue (mtime/size invalidation). Library preview checks avoid opening the custom asset DB for every non-task item.
- Real art and catalogue restoration remain outside the repository. Existing runtime index/preview manifest were backed up before background-only merge; character and sound catalogues and existing task snapshots were preserved.

## Verification
Targeted UI/resource suite: 82 passed. Service/API background/resource/insertion selection: 19 passed (88 deselected). Node syntax and git diff whitespace checks passed.
Live embedded picker: 80/2773, load more to 160/2773; Chinese search 教室; group switching; multiple successful image/webp responses; no captured browser console errors.
Live counts: 2773 total entries; 1212 scene-key entries; 1147 CG-key entries; 414 non-BG custom entries. 957 scene entries have a preview. These are index entries, not unique images or a guarantee of official provenance. Existing inspected task snapshot remains one background.
Local evidence: output/2026-09-18-iab-inspection/full-library-counts.json, full-library-2773.png, full-library-chinese-search.png (workspace output outside checkout).

## Limitations
No AI calls, real user task approvals, compilation or installation. Replacement and insertion validated with isolated synthetic tests, not by changing the user's current story. Not every indexed resource has local preview media or a Chinese label. Grouping uses resource-key conventions; full provenance normalization is not part of this patch.

## Gallery information hierarchy follow-up
Background picker cards now default to image, display name, short localized time/space labels and current-use badge only. Source, key and annotation evidence live in a native details disclosure outside the selection button. Conflict confirmation on adoption is retained. No backend or task edits in this follow-up. UI tests: 37 passed; additional embedded compact-gallery checks at 390/1280 widths and light/dark themes: 4 passed (including keyboard disclosure, no mutation, image loading, no horizontal overflow and compact card height). Node syntax/diff whitespace checks passed. Live embedded screenshot: workspace output/2026-09-18-iab-inspection/background-gallery-simplified.png.

## Preview-only defaults and automatic paging
Fixed the scene picker exception that unchecked ready-only filtering on open. Background pickers now default to ready=1; users can explicitly uncheck to inspect missing media. Added an IntersectionObserver sentinel rooted in the actual results scroller; automatic paging guards concurrent requests and empty pages, disconnects on reset/close, and pauses on failure with an explicit retry. Manual paging remains a fallback when observers are unavailable.
Tests: 45 passed across picker, embedded workbench and resource annotation UI suites; scroll paging and failed-page retry covered at 390/1440 widths. Updated the latest-search-wins test to toggle the new default off. Live embedded UI: checked ready filter, 80/1857 to 160/1857 through scrolling only, no missing-preview placeholders in loaded cards, no captured console errors. Screenshot in workspace output/2026-09-18-iab-inspection/background-auto-load.png. This filters missing media, it does not restore unavailable image files. No task changes or model calls.

## Corrected root cause: extra-pack images existed locally
User challenged the missing-media diagnosis. Checked scene_visual_label evidence for the five screenshot examples and found original 1280x900 JPGs in the user-supplied AA overrides/bgs folder. Previews were disconnected, not absent. 509 indexed keys absent from the preview manifest resolved to readable local override files. Created local thumbnails with original source SHA-256 provenance and merged records into the acceptance cache after backup; no AA files, task snapshots or compiler identities changed. Live previewable count is now 2366 (previously 1857). All five example endpoints return 200 image/webp; embedded UI visibly shows day/night monorail images. Remaining 407 entries not diagnosed as missing: other locations/identity mappings still need audit.
Source fix: ResourcePreviewCatalog.background checks the configured AA workspace overrides/bgs before cached official imagery, validates single-component keys and resolved paths. Regression: 9 passed (preview root and full background library); includes precedence and unsafe path rejection. Source fix requires a process restart to load; current live recovery is via the cache merge and has been verified. Evidence outside repo: background-override-repair.json, background-monorail-restored.png.
