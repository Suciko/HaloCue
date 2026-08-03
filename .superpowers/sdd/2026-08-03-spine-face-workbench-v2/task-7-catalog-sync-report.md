# Task 7 Catalog Label Count Synchronization Report

## Result

The real `GET /api/assets/library` response now includes persisted visual-label
summaries for character variants. `labeled_count` counts distinct face IDs across
model rows, and `labels_updated_at` reports the latest persisted update time.

Characters without persisted labels report `labeled_count: 0`. This does not
invent a semantic face total: an unknown character keeps `face_count: null`, while
a character with known semantic metadata keeps its existing `file_count`,
`face_count`, and `expression_status` values.

## Root Cause

`asset_catalog.list_library_assets()` joined `face_visual_label`, but the HTTP
route does not call that function. It calls `HistoryAssetBrowser.list_library()`,
which independently rebuilt the catalog payload and omitted both label-summary
fields.

## TDD Evidence

RED was reproduced in a detached worktree at the pre-fix commit `a6ec068` with
the API-level regression test:

```text
python -m pytest -q tests/test_asset_library.py::test_library_api_includes_visual_label_summary_without_inventing_face_count
FAILED ... KeyError: 'labeled_count'
1 failed in 1.73s
```

GREEN on the task worktree:

```text
python -m pytest -q tests/test_asset_library.py::test_library_api_includes_visual_label_summary_without_inventing_face_count
1 passed in 0.92s
```

## Implementation

- Extracted the visual-label aggregation and detail merge into shared catalog
  helpers in `asset_catalog.py`.
- Reused those helpers from both catalog aggregation paths, keeping the SQL and
  variant-key behavior in one place.
- Added a real HTTP-server regression test that seeds labeled and known-unlabeled
  characters and requests `/api/assets/library`.
- Asserted that the payload preserves semantic/file counts and does not expose
  temporary filesystem paths.

## Verification

```text
python -m pytest -q tests/test_asset_library.py
15 passed in 3.92s

python -m pytest -q tests/test_history_assets.py tests/test_asset_copy_removal.py
21 passed, 2 skipped in 4.97s

python -m compileall -q asset_catalog.py history_assets.py tests/test_asset_library.py
passed

git diff --check
passed
```

## Self-review

- The join key matches label persistence: `(ident, spine_signature, outfit_key)`.
- `COUNT(DISTINCT face_id)` prevents multiple model records for one face from
  inflating the saved-face count.
- Only character details receive label fields; background and sound contracts are
  unchanged.
- No database paths or preview paths are added to the public response.
- The query runs once per library request, not once per character.

## Concerns

None for this task. The skipped tests are existing platform-conditional cases and
were not introduced by this change.
