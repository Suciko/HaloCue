# AA Native Custom Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the web importer reproduce the confirmed AA project/save custom-asset state, preserve user-entered character identity, track bone-specific face evidence including faceId 99, and constrain generation to registered real assets and confirmed symbols.

**Architecture:** Keep validation pure, move AA project/save path and write coordination into a focused `aa_project_assets.py`, and let `aa_registry.py` register one validated candidate into both mirrors transactionally. Add variant-aware face evidence without deleting legacy index fields, then make annotation consume the selected variant or a safe observed/verified union.

**Tech Stack:** Python 3.11+, standard library, Pillow, SQLite, pytest, existing AA JSON/AAP/AAS formats.

## Global Constraints

- Do not modify or overwrite source assets.
- Do not write custom assets to `E:\AzureArchive\资源文件`.
- Do not default to global `data\overrides`; the confirmed UI route is project-local.
- Background identity is exact UTF-8 filename stem plus `xxHash32(seed=0)`.
- Sound identity is exact filename stem; manifest retains filename and extension.
- Character `Identifier`, `Name`, and `Nickname` come from the user; never generate them.
- `faceId 99` is a legal skeleton-provided face number even when no `99_*` atlas region exists.
- Atlas evidence is a candidate source, not the sole face allowlist.
- Do not change camera or shot-planning behavior.
- Registration must refuse to write while `AzureArchive.exe` is running.
- The directory is not a Git repository; use test and artifact checkpoints instead of commit steps.

---

### Task 1: AA Project/Save Registration Target and Write Guard

**Files:**
- Create: `aa_project_assets.py`
- Modify: `aa_registry.py`
- Create: `tests/test_dual_registration.py`
- Create: `tests/test_aa_write_guard.py`
- Modify: `tests/test_aa_registry.py`

**Interfaces:**
- Produces: `AAProjectTarget(project_dir: Path, save_dir: Path, project_name: str)`
- Produces: `resolve_project_target(project_dir, *, saves_root=None) -> AAProjectTarget`
- Produces: `is_aa_running(process_names=("AzureArchive.exe",)) -> bool`
- Produces: `assert_aa_closed(*, running_probe=None) -> None`
- Changes: `RegistrationResult.install_paths` and `manifest_paths` become tuples.
- Changes: all three `register_*` functions accept either `AAProjectTarget` or a legacy directory and an injectable `running_probe`.

- [ ] **Step 1: Write failing target-resolution tests**

Add tests proving that `...\data\projects\Demo` resolves to
`...\data\saves\Demo`, that an explicit `saves_root` works, and that an
unrelated directory cannot be silently treated as an AA project.

- [ ] **Step 2: Run target tests and verify expected import/function failures**

Run:

```powershell
python -m pytest tests/test_dual_registration.py -q
```

Expected: collection or assertion failure because `AAProjectTarget` and
`resolve_project_target` do not exist.

- [ ] **Step 3: Implement target resolution**

Create immutable `AAProjectTarget`, normalize absolute paths, require a
non-empty project name, and derive `save_dir` only from an exact
`projects/<name>` layout or an explicit saves root.

- [ ] **Step 4: Write and verify failing AA-running tests**

Cover an injected `running_probe=lambda: True`, assert
`AssetRegistrationError` contains code `aa_running`, and assert no target
directory or manifest is created.

- [ ] **Step 5: Implement the Windows process guard**

Use `tasklist /FI "IMAGENAME eq AzureArchive.exe" /FO CSV /NH` on Windows.
Keep the probe injectable so tests never inspect the real desktop process.

- [ ] **Step 6: Write failing dual-mirror behavior tests**

Test background, sound, and character copies and manifest entries in both
targets. For character, assert both manifests preserve:

```json
{
  "Identifier": "92707271",
  "Name": "差分凯伊7F3A91",
  "Nickname": "原生导入测试"
}
```

- [ ] **Step 7: Write failing zero-partial-write conflict tests**

Pre-seed a conflicting file in either mirror and assert the other mirror
remains byte-for-byte unchanged. Also test same identifier with different
`Name` or `Nickname` is rejected rather than silently rewritten.

- [ ] **Step 8: Implement dual preflight and mirrored registration**

Preflight both manifests and all target files before any copy. Track files
created and original manifest bytes; on an unexpected write failure, remove
only newly created files and restore only manifests written by this attempt.
Never delete a pre-existing file.

- [ ] **Step 9: Preserve legacy single-directory compatibility explicitly**

Existing direct tests may pass a non-AA temporary directory. Support it only
through an explicit single-target adapter used by tests/offline tools; the
web request path must always resolve a project/save pair.

- [ ] **Step 10: Run registry tests**

```powershell
python -m pytest tests/test_aa_registry.py tests/test_dual_registration.py tests/test_aa_write_guard.py -q
```

Expected: all pass.

---

### Task 2: Web/API Native-Semantic Import

**Files:**
- Modify: `asset_import.py`
- Modify: `webui.py`
- Modify: `ui.html`
- Modify: `tests/test_web_asset_api.py`

**Interfaces:**
- Consumes: `resolve_project_target` and dual `RegistrationResult`.
- Returns: `project_dir`, `save_dir`, `install_paths`, `manifest_paths`,
  `changed`, and validation metadata.
- Maps: `aa_running` to HTTP 409.

- [ ] **Step 1: Write failing request tests**

Assert a web registration request derives `data/saves/<project>`, returns two
install paths, and stores one catalog row scoped only by the canonical project
directory.

- [ ] **Step 2: Write failing UI semantics tests**

Assert background and sound forms contain no editable ID field, character
fields include ID/Name/Nickname, and result text calls background/sound keys
“内部标识” rather than asking the user to provide an ID.

- [ ] **Step 3: Write failing HTTP 409 guard test**

Inject a running probe into the registration request and assert the handler
maps `aa_running` to 409 with “请关闭 AzureArchive 后重试”.

- [ ] **Step 4: Implement request target resolution and response fields**

Pass `CFG["aa_data"]/saves` to `register_asset_request`; preserve existing
`project` name validation; write a single catalog row whose metadata records
both manifest paths.

- [ ] **Step 5: Implement non-technical UI messages**

Show:

- background: filename, computed internal background key, format/dimensions;
- sound: filename stem, codec/rate/channels, no editable ID;
- character: user ID, name, alias, atlas candidates, skeleton signature.

- [ ] **Step 6: Apply the same write guard to generated-project installation**

Before `script2aap --install`, refuse installation while AA is running. Pure
generation without `--install` remains allowed.

- [ ] **Step 7: Run web tests**

```powershell
python -m pytest tests/test_web_asset_api.py tests/test_generator_asset_integration.py -q
```

Expected: all pass.

---

### Task 3: Bone Variant and Face Evidence Model

**Files:**
- Modify: `asset_validation.py`
- Modify: `assetdb.py`
- Modify: `asset_catalog.py`
- Modify: `build_index.py`
- Modify: `annotate.py`
- Modify: `tests/test_asset_validation.py`
- Modify: `tests/test_asset_catalog.py`
- Create: `tests/test_face_evidence.py`

**Interfaces:**
- Adds character metadata: `spine_signature` is SHA-256 of `.skel`;
  `outfit_key` defaults to the skeleton asset stem.
- Adds SQLite tables:

```sql
character_variant(
  ident TEXT, spine_signature TEXT, outfit_key TEXT, spine TEXT,
  PRIMARY KEY(ident, spine_signature, outfit_key)
)
face_evidence(
  ident TEXT, spine_signature TEXT, outfit_key TEXT, face_id TEXT,
  source TEXT, raw TEXT, label TEXT, label_cn TEXT, observed_count INTEGER,
  PRIMARY KEY(ident, spine_signature, outfit_key, face_id, source)
)
```

- Source values: `atlas_candidate`, `aap_observed`, `aa_verified`.
- Adds index field `face_capabilities`, while preserving legacy
  `characters[].faces` and `faces_used`.

- [ ] **Step 1: Write failing validation signature test**

Assert `validate_spine` returns stable `spine_signature` from `.skel` bytes,
`outfit_key` from stem, and does not reject a separately observed faceId 99
because atlas lacks a `99_*` region.

- [ ] **Step 2: Implement validation metadata**

Keep the existing full package digest for content conflict checks. Add the
skeleton-only signature and outfit key without changing `AssetCandidate`.

- [ ] **Step 3: Write failing face-evidence migration tests**

Open a legacy database, migrate it, insert atlas, observed, and verified
evidence for the same face, and assert all evidence rows survive.

- [ ] **Step 4: Implement additive database migration**

Create the two new tables without altering or dropping legacy `character` and
`face`. Import old rows as evidence only when source can be mapped safely.

- [ ] **Step 5: Write failing index-harvest tests for faceId 99**

Use a one-record `.aap` containing faceId `99`. Assert it appears as
`aap_observed` with count 1 even when the atlas has only 00 and 01. Remove the
old `min_hits=2` and “at least three faces” exclusion from evidence collection.

- [ ] **Step 6: Implement variant-aware harvest**

Emit atlas candidates per variant and observed faces per identifier. When an
AAP record cannot identify the exact skeleton, store an empty signature/outfit
as identifier-level evidence rather than assigning it to an arbitrary variant.

- [ ] **Step 7: Write failing model-constraint merge tests**

Assert two variants of one identifier are preserved in `face_capabilities`,
legacy faces are their union, and an existing official character is enriched
rather than skipped.

- [ ] **Step 8: Implement catalog export and merge**

Keep old keys readable. Add `spine_signature`, `outfit_key`, evidence sources,
and verified state. Do not promote atlas candidates or observed faces to
`aa_verified`.

- [ ] **Step 9: Write failing annotation allowlist tests**

Assert:

- observed faceId 99 is accepted when atlas lacks 99;
- a face absent from all evidence is rejected;
- selected variant evidence is preferred;
- without a variant, safe identifier-level observed/verified evidence is used.

- [ ] **Step 10: Implement union-based face lookup**

Replace the current custom-atlas overwrite behavior with an evidence union.
`is_face_allowed` remains strict: an empty evidence set rejects all model face
guesses.

- [ ] **Step 11: Run face tests**

```powershell
python -m pytest tests/test_asset_validation.py tests/test_asset_catalog.py tests/test_face_evidence.py -q
```

Expected: all pass.

---

### Task 4: Symbol Dataset and Strict Generation Constraints

**Files:**
- Modify: `build_index.py`
- Modify: `script2aap.py`
- Modify: `prompt.py`
- Modify: `docs/format.md`
- Modify: `docs/commands.md`
- Modify: `tests/test_script_commands.py`
- Modify: `tests/test_model_asset_constraints.py`
- Create: `tests/test_symbol_constraints.py`

**Interfaces:**
- Canonical emoticon IDs: `0..19`, none `-1`.
- Canonical action IDs: `1..7`, with Jump `6`.
- Chat/chatter is emoticon `1`, not an action.
- Shape generation allowlist contains only confirmed `1`, `2`, and `4`.
- Unknown numeric enum input raises a conversion error instead of passing
  through.

- [ ] **Step 1: Write failing Chat/Jump distinction tests**

Assert Chat resolves to `emoticon=1, action=0`; Jump resolves to
`emoticon=-1, action=6`; compiled commands contain `#N;em;[재잘]` and
`#N;jump` respectively.

- [ ] **Step 2: Write failing numeric-bypass tests**

Feed unknown emoticon/action/shape numeric values and assert conversion rejects
them with the line number. Confirm valid canonical values still work.

- [ ] **Step 3: Remove shape 5/6 from model-visible canonical data**

Keep corpus observations in an evidence section if needed, but do not expose
unconfirmed shape 5/6 as selectable model effects. Correct the current
`shapeOverride 6 -> black` claim.

- [ ] **Step 4: Implement strict resolvers**

All public script syntax resolves through known symbolic/Chinese aliases and
known numeric IDs. `additionalPrompt` remains an explicit advanced escape
hatch but is never generated from an unvalidated model field.

- [ ] **Step 5: Update prompt and docs**

Document Chat as a symbol, Jump as action 6, automatic wait behavior, and
unresolved shape values as non-generatable evidence.

- [ ] **Step 6: Run symbol tests**

```powershell
python -m pytest tests/test_script_commands.py tests/test_model_asset_constraints.py tests/test_symbol_constraints.py -q
```

Expected: all pass.

---

### Task 5: Project/Save Verification and Closed References

**Files:**
- Modify: `verify.py`
- Modify: `tests/test_project_asset_integration.py`
- Create: `tests/test_project_save_verification.py`

**Interfaces:**
- Changes:

```python
verify_project_assets(
    aap_path,
    project_dir,
    *,
    save_dir: str | Path | None = None,
) -> ProjectAssetReport
```

- [ ] **Step 1: Write failing mirror-drift tests**

Cover missing save manifest entry, differing background/sound bytes, differing
character metadata, missing avatar, and duplicated slash variants.

- [ ] **Step 2: Implement semantic manifest normalization**

Normalize path separators only for comparison, deduplicate entries, preserve
the native payload when writing, and report actual duplicate registrations as
warnings/errors without mutating the project during verification.

- [ ] **Step 3: Implement mirrored resource hashing**

For every registered asset, compare project/save relative paths and SHA-256.
Keep the existing project-only behavior when `save_dir` is not supplied.

- [ ] **Step 4: Verify AAP face and symbol references**

For custom characters, require each non-empty faceId to exist in the
variant/identifier evidence allowlist. Accept faceId 99 when observed or
verified even without an atlas region.

- [ ] **Step 5: Run verification tests**

```powershell
python -m pytest tests/test_project_asset_integration.py tests/test_project_save_verification.py -q
```

Expected: all pass.

---

### Task 6: Integration, Real Artifacts, and Regression Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/custom-assets-test-report.md`
- Create: `04-素材机制实验/实施验证/` artifacts outside the program directory.

**Interfaces:**
- Consumes all previous tasks.
- Produces one combined project using the real tested background, sound, and
  Kai skeleton.

- [ ] **Step 1: Run the complete automated suite**

```powershell
python -m pytest -q
```

Expected: all tests pass with no warnings or errors.

- [ ] **Step 2: Register the three real assets into an independent combined project**

Use:

- background `DIFF_BG_7F3A91.png`;
- sound `DIFF_SE_7F3A91.wav`;
- Kai skeleton with ID `92707271`, name `差分凯伊7F3A91`, nickname
  `原生导入测试`.

AA must be closed. A second identical registration must report
`changed=False`.

- [ ] **Step 3: Generate a minimum combined AAP**

The project must reference:

- `bgFriendlyName = DIFF_BG_7F3A91`;
- `bgName = 2894617861`;
- `sound = DIFF_SE_7F3A91`;
- character name `92707271`;
- faceId `01`;
- Chat emoticon `1`;
- Jump action `6`.

- [ ] **Step 4: Run the closed-reference verifier**

Verify both project and save mirrors and record exact input, output, hashes,
and report in `04-素材机制实验/实施验证/`.

- [ ] **Step 5: Ask the user for the final AA manual run**

Open, preview, compile, exit, restart, reopen, and verify all three assets.
Record the result. Do not claim AA acceptance before this step is performed.

- [ ] **Step 6: Confirm regressions remain absent**

Re-run the full suite, verify the existing camera versions and official
`aa_resources.json` counts/files were not overwritten, and update the final
test report with confirmed, inferred, and unresolved findings.

