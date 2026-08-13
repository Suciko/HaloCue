# Android Native Custom Asset Picker

## Goal

Replace the PC-style embedded asset browser on Android with Android's system document providers, while preserving the existing story-scoped validation, registration, history, and task flows.

## User Flow

- Background and sound imports open the Android system file picker.
- Character imports open the Android system directory picker so the selected tree can contain the `.skel`, matching `.atlas`, texture pages, and optional avatar.
- "Scan current story asset directory" becomes a system directory selection for batch discovery and import.
- The embedded host filesystem browser is not displayed for these actions on Android. PC behavior remains unchanged.
- A story must still be open because imported custom assets are registered into that story's private project copy.

## Native Picker Contract

The WebView sends a request containing a unique request ID, purpose, asset kind, and accepted suffixes. Kotlin accepts only these explicit purposes:

- `story`: one `.txt` or `.md` document, preserving the existing story picker behavior.
- `asset_file`: one background or sound document.
- `asset_tree`: one character or batch-import directory tree.

Only one native picker request may be active. Cancellation is a normal result. Activity recreation preserves the pending request and an undelivered result.

Background MIME filters include images. Sound filters include common audio types. The suffix allowlist remains authoritative after selection because Android document providers do not consistently honor MIME filters. Character and batch imports use `ACTION_OPEN_DOCUMENT_TREE`.

## Private Staging

Selected content is copied immediately into an app-private incoming directory. Python never receives or retains a `content://` URI.

Single documents use the existing bounded incoming-file staging flow with kind-specific size and suffix checks. Directory trees are copied into a newly allocated staging directory with these protections:

- normalized relative paths only;
- no traversal or absolute paths;
- bounded file count, per-file size, and total byte count;
- bounded recursion depth;
- no symbolic-link assumptions;
- cleanup of only the newly allocated staging directory on failure or cancellation.

The result returned to the WebView is an opaque, one-use incoming token plus safe display metadata. The Python endpoint claims the token, creates a regular private filesystem path/file token, and then calls the existing validation and registration code.

For a character tree, Python discovers a valid `.skel` and matching `.atlas` pair. If zero or multiple independent character bundles are found, the import fails with an actionable message instead of guessing. Batch import uses the existing `bgs`, `sounds`, and `characters` discovery conventions where present and also supports recursive discovery from the selected root.

## WebUI Behavior

On Android, the asset dialog's "Select file" action calls the native picker directly. It does not open the embedded host browser. The character label becomes "Select character folder". The scan action becomes "Select asset folder for batch import".

The current task UI remains responsible for validation, registration, progress, retry, and final status. Failed or cancelled selection does not create an import task. Once staging succeeds, retries reuse the staged private token while it remains valid.

On non-Android platforms, the existing host browser and path-based behavior are unchanged.

## Error Handling

- Unsupported suffix: report that the selected file type is not supported for the chosen asset kind.
- Oversized file/tree: report the configured limit without partially registering content.
- Unreadable provider item: report the item name and discard the new staging area.
- Missing Spine companions: report the missing `.atlas` or texture file.
- Multiple Spine bundles: ask the user to select a folder containing one character bundle.
- Picker unavailable: report that no Android document provider is available.
- Cancellation: close the pending selection state without an error toast.

Existing registered assets and prior staging areas are never deleted by a failed new selection.

## Testing

- JVM tests cover request-purpose validation, MIME selection, active-request exclusion, and restored request state.
- Android instrumentation tests cover single-document staging, directory-tree staging, cancellation, invalid suffixes, size limits, and WebView result delivery.
- JavaScript tests verify Android asset actions invoke the native bridge and never reveal the embedded host browser, while PC actions retain the browser.
- Python tests cover claiming file/tree tokens, one-bundle Spine discovery, ambiguous Spine trees, and batch discovery.
- The Android debug APK is built after focused and regression tests pass.

## Acceptance Criteria

1. Tapping background or sound selection opens the Android system file picker.
2. Tapping character selection opens the Android system directory picker.
3. Tapping batch scan opens the Android system directory picker.
4. The embedded host filesystem browser shown in the reported screenshot never appears in the Android asset flow.
5. Valid background, sound, and complete Spine directory selections register into the open story.
6. Cancellation and invalid selections leave the story and existing asset library unchanged.
7. PC asset selection behavior remains unchanged.
