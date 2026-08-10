# Android Compact Workbench and Incremental Resource Imports

## Goal

Make the Android WebUI reclaim first-screen space and replace the unusable PC-only AA path configuration with a repeatable Android resource import flow. Multiple imports from the same entry are cumulative, while all published identifiers remain compatible with the PC resource mapping.

## Confirmed constraints

- Android must not probe or write the original AA application's `Android/data` directory.
- Android users import resources they have copied to an accessible location using the system picker.
- The ordinary resource set and later extra resource set use the same import entry; they are separate batches, not separate resource types.
- Existing PC mapping is authoritative: official character identifiers/native keys, AA background keys, sound keys, and face IDs must not be renamed or re-derived.
- Spine rendering remains unavailable on Android; this change only makes the official resource catalog/import path usable.

## Design

### 1. Compact mobile workbench

The mobile topbar keeps its current visual language but uses a compact initial height. The title block and action row are reduced to the minimum touch-safe spacing. The readiness panel is expanded only when a check needs attention; after all required checks are ready it shows a compact summary with an explicit “查看详情” action.

The full topbar scrolls away with the page. A small sticky toolbar remains only while the user scrolls downward, and reappears immediately on upward scroll. It contains the workbench title and compact icon/text entry points. The full model settings drawer is never pinned to the content viewport.

### 2. Android resource batches

Android exposes one “导入 AA 资源” action with two native picker modes: import a directory tree or import a supported archive. The native layer stages the selected content into the app-private incoming area and returns a one-use token to Python. A batch is validated before it changes the active library.

Each accepted batch is recorded in an app-private manifest with:

- batch token and import time;
- source display name;
- catalog file and cache root detected in the batch;
- file count, byte count, duplicate count, replaced count;
- SHA-256 of each replaced bundle.

Validated bundles are merged into one canonical private cache using their existing Addressables outer/content keys. Identical files are skipped. A later file for the same key replaces the active file but does not change the key. The latest compatible catalog is used for lookup, and the merged cache is passed through the existing PC catalog/index functions. This preserves identifier, background AA key, sound key, and face ID compatibility without adding an Android-specific mapping layer.

### 3. Failure behavior

An import that lacks a recognizable catalog/cache, contains a path traversal entry, exceeds configured size limits, or fails UnityFS validation is rejected without changing the active library. The UI reports the batch-level reason and leaves the previous index usable. Preview rebuilding is explicitly separate and can report “无预览” for catalog entries without a bitmap.

## Acceptance criteria

1. On the target phone, the first screen exposes the script picker without the current large blank/title/readiness block.
2. Scrolling down removes the full header and leaves only a compact reappearing toolbar.
3. The settings drawer no longer asks Android users for an AA executable or direct AA installation path.
4. Importing a base batch, then an extra batch through the same entry, produces one active catalog and cache containing both batches.
5. Re-importing the same batch is idempotent.
6. A same-key replacement keeps the PC identifier/key and is reported as replaced.
7. Existing Android and PC mapping/index tests remain green.

