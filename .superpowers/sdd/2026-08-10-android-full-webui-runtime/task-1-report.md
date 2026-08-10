# Task 1 Report: Whitelist PC Runtime Synchronization

## Implemented

- Added `scripts/pc-runtime-manifest.json` with explicit `python`, `directories`, and `static` allowlists.
- Added `scripts/sync-pc-runtime.ps1`, which resolves the PC source root, enforces destination containment inside the Android project, copies only allowlisted files, removes only stale files recorded by the previous generated source record, computes uppercase SHA-256 hashes, and writes `app/src/main/python/PC运行时来源.json`.
- Added `scripts/test-pc-runtime-sync.ps1` to assert required runtime files, reject forbidden manifest path segments, and validate manifest/source-record hashes.
- Added Android `.gitignore` protections for generated output, environment files, LLM configuration, and asset databases.
- Synchronized 57 reusable PC runtime/UI files, including `webui.py`, its import-time compatibility dependencies, the full CSS/JS tree, `ui.html`, and the favicon. Android-owned compiler/discovery modules were preserved.

## Tests and Results

### RED evidence

Before implementation:

```text
powershell -ExecutionPolicy Bypass -File scripts/test-pc-runtime-sync.ps1
FAIL: Missing PC runtime manifest
```

### GREEN evidence

```text
powershell -ExecutionPolicy Bypass -File scripts/sync-pc-runtime.ps1
PC runtime synchronized: 57 files

powershell -ExecutionPolicy Bypass -File scripts/test-pc-runtime-sync.ps1
PC runtime sync contract passed

git diff --check
PASS (Git emitted only its normal LF/CRLF warning for .gitignore)
```

## Files Changed

- `.gitignore`
- `scripts/pc-runtime-manifest.json`
- `scripts/sync-pc-runtime.ps1`
- `scripts/test-pc-runtime-sync.ps1`
- `app/src/main/python/` synchronized runtime files, UI files, static assets, and `PC运行时来源.json`

## Self-review

- The manifest excludes `launcher.py`, Windows command files, user configuration, generated data, caches, and official asset/output trees.
- Sync rejects rooted/traversal paths and destinations outside the Android project, and stale cleanup is limited to paths in the prior generated source record.
- Existing Android-owned Python modules were not overwritten.
- Source hashes in both the manifest and generated record are uppercase 64-character SHA-256 values.

## Concerns

- The synchronized PC modules intentionally retain their desktop implementation; Android capability gating and local-server adaptation are deferred to Tasks 2-5.
- Existing pre-task `app/src/main/python/__pycache__/` files remain in the worktree but are neither manifest entries nor synchronized outputs.
