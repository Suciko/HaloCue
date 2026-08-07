# Official Staging Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Build a deterministic, lossless JSONL extractor for all official Blue Archive scenario staging records and place the machine-readable corpus under `05-官方演出语料库`.

**Architecture:** A standalone Python extractor reads the three ScenarioScriptExcel shards plus official lookup tables, reuses the existing story-catalog builder and Traditional-to-Simplified conversion, and writes shard-preserving JSONL records. Parsing is additive: raw source values remain intact, normalized ordered events and audit indexes are generated from them, and output is promoted only after count/hash/audit checks pass.

**Tech Stack:** Python 3.11+, stdlib `json`, `hashlib`, `argparse`, `pathlib`, existing `render_global_chinese_corpus.py` helpers, pytest.

## Global Constraints

- Input data is read-only; do not modify `官方剧情文档/bluearchive-data-global`.
- All 368,032 source rows must be emitted, including empty-text and unknown-command rows.
- Preserve raw `script_kr` byte-for-character as decoded Unicode, and preserve resource hashes/IDs.
- Use UTF-8 JSON with `ensure_ascii=false`, stable ordering, and streaming JSONL output.
- Use `apply_patch` for manual edits; no third-party dependency additions.
- Existing dirty worktree changes are user-owned and must remain untouched.

---

### Task 1: Define parser and extractor contracts with failing tests

**Files:**
- Create: `tests/test_official_staging_corpus.py`
- Create: `official_staging_corpus.py`

**Interfaces:**
- `parse_script_events(script_kr: str, text_tw: str = "") -> list[dict]`
- `normalize_command(command: str) -> tuple[str, str]`
- `class OfficialStagingExtractor`
- `OfficialStagingExtractor.extract_row(row, source_file, shard, row_index, global_index) -> dict`

- [ ] Write tests for character declaration plus ordered `#3;em`, `#3;m2`, `#wait`; empty-text staging nodes; `#Title`/unknown command status; raw-line preservation; and top-level resource fields.
- [ ] Run `pytest tests/test_official_staging_corpus.py -q` and verify it fails because the module/API is absent.
- [ ] Implement only parser data-shape helpers sufficient for those tests; unknown and malformed lines must still return events.
- [ ] Run the focused tests and verify they pass.

### Task 2: Add official resource and story lookup layers

**Files:**
- Modify: `official_staging_corpus.py`
- Test: `tests/test_official_staging_corpus.py`

**Interfaces:**
- `load_resource_catalog(repo_root: Path) -> dict`
- `load_story_memberships(repo_root: Path) -> dict[str, list[dict]]`

- [ ] Add failing tests using temporary miniature ExcelDB tables for background, effect, transition, and BGM mappings, plus one mapped and one unmapped `group_id`.
- [ ] Run the focused tests and verify the expected lookup failures.
- [ ] Implement lookup loading with `data_list`/list/object JSON shapes, conflict-preserving candidates, and reuse of `build_story_catalog` when the real repo is supplied.
- [ ] Add `resolved`, `mapping_status`, and story membership fields without changing raw values.
- [ ] Run focused tests and verify they pass.

### Task 3: Implement deterministic shard-preserving JSONL export

**Files:**
- Modify: `official_staging_corpus.py`
- Test: `tests/test_official_staging_corpus.py`

**Interfaces:**
- `extract_corpus(repo_root: Path, output_root: Path, *, replace: bool = False) -> dict`
- CLI: `python official_staging_corpus.py --repo-root ... --output-root ... [--replace]`

- [ ] Add a failing integration test with three tiny shard fixtures asserting one output file per shard, stable `record_uid`, previous/next links within groups, and manifest counts.
- [ ] Run it and verify it fails before export exists.
- [ ] Implement streaming writes to a temporary output directory, deterministic JSON serialization, per-file SHA-256, and atomic promotion only after validation.
- [ ] Generate `manifest.json`, `indexes/story_units.jsonl`, `indexes/command_catalog.json`, `indexes/resource_catalog.json`, and all audit files.
- [ ] Run the integration test and verify it passes.

### Task 4: Validate against the full official corpus

**Files:**
- Modify: `official_staging_corpus.py` only if validation exposes a defect.
- Create: `05-官方演出语料库/` generated outputs.

- [ ] Run the extractor against the real official repo with `--replace`.
- [ ] Verify manifest source-row count is 368,032 and shard counts match 140,277 / 140,277 / 87,478.
- [ ] Recompute `script_kr` event totals from JSONL and compare with extraction report; verify unknown commands are audited, not dropped.
- [ ] Run focused tests plus the existing AA test suite relevant to touched modules.
- [ ] Inspect output sizes, representative records, `command_catalog.json`, and `unmapped_groups.jsonl` without loading the complete corpus into memory.

### Task 5: Final verification and handoff

- [ ] Run `python -m pytest tests/test_official_staging_corpus.py -q`.
- [ ] Run a fresh manifest/hash audit command and capture exit code/output.
- [ ] Confirm official data repo status is unchanged and report generated paths, counts, and any residual unknown/unmapped items.
