# 已登记素材约束与角色差分能力 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让模型与编译器只使用当前工程已登记、已验证的 AA 素材，并将自定义骨骼的编号差分、语义部件差分和未知差分明确分层处理。

**Architecture:** `asset_validation.py` 从 atlas 生成两类候选：可作为 face 候选的编号完整差分、仅供理解的语义部件。`assetdb.py` 以骨骼 SHA 与服装键为作用域持久化部件，`asset_catalog.py` 仅把已观察/已验证的 faceId 导出为模型白名单。`prompt.py` 和 `annotate.py` 向模型展示严格资源表并在模型响应后逐字段剔除越界内容；`script2aap.py` 保持纯编译职责。

**Tech Stack:** Python 3、SQLite、pytest、Pillow、现有 AzureArchive `.aap`/atlas 解析代码。

## Global Constraints

- 不改动 `script2aap.py` 的镜头算法、首次入场 `appear=3`、再入镜 `appear=0`、显式 `@enter`/`@exit` 规则。
- 不把 atlas 候选或模型猜测升级为 `aa_verified` / `aap_observed`。
- 所有部件记录按 `(ident, spine_signature, outfit_key)` 隔离。
- 无编号、无语义的骨骼仍可导入；模型只能保持已验证默认 faceId 或留空。
- 不修改用户原始骨骼、剧情文件、既有 AA 验收工程或官方索引。
- 生产代码变更前必须先写对应 pytest 并观察其失败。

---

## File Structure

- Modify: `asset_validation.py` — 解析 atlas 的完整编号差分与任意语义区域，生成 `expression_mode` 和 `expression_parts` 元数据。
- Modify: `assetdb.py` — 新增 `expression_part` SQLite 表和变体作用域的幂等写入/读取接口。
- Modify: `asset_catalog.py` — 注册角色时同步部件记录；导出 `expression_mode` 与语义部件，保持 face 白名单只来自证据表。
- Modify: `prompt.py` — 将角色可用 `faceId`、无编号降级规则、语义能力提示明确给模型。
- Modify: `annotate.py` — 提取可单元测试的逐行约束过滤函数，为 face/emo/act/fx/bg/se 等越界字段提供稳定的丢弃原因；不允许非立绘说话者使用人物演出字段。
- Modify: `tests/test_asset_validation.py` — 覆盖三种骨骼分类及语义部件解析。
- Modify: `tests/test_asset_catalog.py` — 覆盖部件存储、变体隔离、导出不扩大 face 白名单。
- Modify: `tests/test_model_asset_constraints.py` — 覆盖提示词对语义骨骼和未知骨骼的严格说明。
- Create: `tests/test_annotation_constraints.py` — 覆盖结构化模型行的逐字段白名单过滤。
- Create: `tools/inspect_expression_capabilities.py` — 只读诊断 CLI：显示某个骨骼目录的分类、编号候选、语义部件和缺失的 AA 验证映射。
- Create: `tests/test_expression_inspector.py` — 覆盖诊断 CLI 的纯数据格式化函数。

## Task 1: 骨骼差分分类与语义部件解析

**Files:**
- Modify: `asset_validation.py:214-336`
- Modify: `tests/test_asset_validation.py:15-165`

**Interfaces:**
- Produces: `extract_expression_capabilities(atlas_lines: list[str]) -> dict[str, object]`.
- Returns exactly `{"faces": list[str], "parts": list[dict[str, object]], "mode": str}` where `mode` is one of `numbered_composite`, `semantic_modular`, `opaque_custom`.
- Each part contains `kind`, `raw_name`, `labels`, `source`; `labels` preserves ordered unique Chinese semantic labels.

- [ ] **Step 1: Write the failing tests**

```python
def test_spine_classifies_numbered_complete_faces_without_semantic_parts(tmp_path):
    root = make_spine_bundle(tmp_path / "numbered")
    result = validate_spine(root, identifier="1516544")
    assert result.candidate.metadata["expression_mode"] == "numbered_composite"
    assert result.candidate.metadata["faces"] == ["00", "03"]
    assert result.candidate.metadata["expression_parts"] == []


def test_spine_extracts_semantic_modular_parts_from_chinese_atlas(tmp_path):
    root = make_spine_bundle(tmp_path / "date", stem="Kei_Date_Outfit")
    (root / "Kei_Date_Outfit.atlas").write_text(
        "Kei_Date_Outfit.png\\nsize:8,8\\n"
        "圆睁高光眼（惊讶、震惊、期待、好奇）\\n  bounds:0,0,1,1\\n"
        "小幅上扬嘴（微笑、开心、满意、友好）\\n  bounds:1,1,1,1\\n"
        "普通脸红（默认）\\n  bounds:2,2,1,1\\n", encoding="utf-8")
    result = validate_spine(root, identifier="626652156")
    assert result.candidate.metadata["expression_mode"] == "semantic_modular"
    assert result.candidate.metadata["faces"] == []
    assert result.candidate.metadata["expression_parts"] == [
        {"kind": "eyes", "raw_name": "圆睁高光眼（惊讶、震惊、期待、好奇）",
         "labels": ["惊讶", "震惊", "期待", "好奇"], "source": "atlas_semantic"},
        {"kind": "mouth", "raw_name": "小幅上扬嘴（微笑、开心、满意、友好）",
         "labels": ["微笑", "开心", "满意", "友好"], "source": "atlas_semantic"},
        {"kind": "blush", "raw_name": "普通脸红（默认）",
         "labels": ["默认"], "source": "atlas_semantic"},
    ]


def test_spine_classifies_unlabeled_regions_as_opaque_custom(tmp_path):
    root = make_spine_bundle(tmp_path / "opaque", stem="Creator_Character")
    (root / "Creator_Character.atlas").write_text(
        "Creator_Character.png\\nsize:8,8\\nRegionA\\n  bounds:0,0,1,1\\n",
        encoding="utf-8")
    result = validate_spine(root, identifier="opaque-01")
    assert result.candidate.metadata["expression_mode"] == "opaque_custom"
    assert result.candidate.metadata["faces"] == []
    assert result.candidate.metadata["expression_parts"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_asset_validation.py -q`

Expected: FAIL because `expression_mode` and `expression_parts` are absent.

- [ ] **Step 3: Implement the minimum parser**

Add `extract_expression_capabilities`. It must ignore atlas page/configuration lines and indented attribute lines, recognize `^\\d{2}(?:_|$)` only as a face candidate, parse Chinese full-width parentheses `（...）`, split inner labels on `、` / `，` / `,`, and classify raw names by explicit keywords:

```python
_PART_KIND_KEYWORDS = (
    ("eyes", ("眼",)), ("brows", ("眉",)), ("mouth", ("嘴", "唇")),
    ("blush", ("脸红",)), ("tear", ("泪",)),
)
```

Only add a semantic part when there is at least one extracted parenthesized label. `validate_spine` must set `faces`, `expression_parts`, `expression_mode`, and retain `expression_status="known"` only for numbered faces; semantic-only remains `unresolved` for AA face output.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_asset_validation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

No Git repository exists in this workspace. Record this completed task in this plan instead of committing.

## Task 2: 变体作用域的语义部件数据库与模型约束导出

**Files:**
- Modify: `assetdb.py:15-85`, `assetdb.py:130-300`
- Modify: `asset_catalog.py:30-300`
- Modify: `tests/test_asset_catalog.py`

**Interfaces:**
- Produces: `assetdb.replace_expression_parts(con, *, ident: str, spine_signature: str, outfit_key: str, parts: list[dict]) -> None`.
- Produces: `assetdb.expression_parts_by_variant(con) -> dict[tuple[str, str, str], list[dict]]`.
- `export_model_constraints` adds `expression_mode` and `expression_parts` to each custom character record; it must not add parts to `faces` or `face_capabilities`.

- [ ] **Step 1: Write the failing tests**

```python
def test_semantic_parts_are_exported_but_do_not_become_face_ids(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    candidate = AssetCandidate(
        kind="character", source_path=tmp_path, stem="Kei_Date_Outfit", aa_key="626652156", sha256="x",
        metadata={"spine_signature": "date-sha", "outfit_key": "Kei_Date_Outfit",
                  "expression_mode": "semantic_modular", "expression_parts": [
                      {"kind": "eyes", "raw_name": "圆睁高光眼（惊讶）", "labels": ["惊讶"], "source": "atlas_semantic"}
                  ], "faces": []},
    )
    upsert_candidate(con, candidate, scope="sample", status="registered")
    out = export_model_constraints(con, scope="sample")["characters"][0]
    assert out["expression_mode"] == "semantic_modular"
    assert out["expression_parts"][0]["labels"] == ["惊讶"]
    assert out["faces"] == []
    assert out["face_capabilities"] == []


def test_expression_parts_do_not_cross_skeleton_variants(tmp_path):
    con = assetdb.connect(tmp_path / "assets.db")
    migrate(con)
    assetdb.replace_expression_parts(con, ident="626652156", spine_signature="winter", outfit_key="winter", parts=[
        {"kind": "mouth", "raw_name": "冬装笑嘴（微笑）", "labels": ["微笑"], "source": "atlas_semantic"}
    ])
    assetdb.replace_expression_parts(con, ident="626652156", spine_signature="date", outfit_key="date", parts=[
        {"kind": "eyes", "raw_name": "约会服眼（惊讶）", "labels": ["惊讶"], "source": "atlas_semantic"}
    ])
    rows = assetdb.expression_parts_by_variant(con)
    assert rows[("626652156", "winter", "winter")][0]["kind"] == "mouth"
    assert rows[("626652156", "date", "date")][0]["kind"] == "eyes"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_asset_catalog.py -q`

Expected: FAIL because the table/functions/export fields do not exist.

- [ ] **Step 3: Implement the minimum persistence and export**

Add this table to `assetdb.SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS expression_part (
    ident TEXT NOT NULL, spine_signature TEXT NOT NULL, outfit_key TEXT NOT NULL,
    kind TEXT NOT NULL, raw_name TEXT NOT NULL, labels_json TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (ident, spine_signature, outfit_key, raw_name, source)
);
```

Use delete-then-insert only within the exact `(ident, spine_signature, outfit_key)` scope, and only from `upsert_candidate`/registered metadata for that exact candidate. Insert/update the matching `character_variant`. `asset_catalog` must join these parts by the same variant triple and expose them separately from `face_capabilities`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_asset_catalog.py tests/test_face_evidence.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

No Git repository exists in this workspace. Record this completed task in this plan instead of committing.

## Task 3: 严格模型提示词与可测试的标注白名单过滤

**Files:**
- Modify: `prompt.py:build_resources`
- Modify: `annotate.py:15-90`, `annotate.py:250-335`
- Modify: `tests/test_model_asset_constraints.py`
- Create: `tests/test_annotation_constraints.py`

**Interfaces:**
- Produces: `annotation_constraints(idx: dict, cast: dict) -> dict[str, object]`.
- Produces: `filter_annotation_row(row: dict, item: dict, character: dict, constraints: dict) -> tuple[dict, list[str]]`.
- The filter returns only legal fields and a list of exact Chinese reasons; it does not mutate its input arguments.

- [ ] **Step 1: Write the failing tests**

```python
def test_prompt_describes_semantic_parts_without_offering_them_as_face_ids():
    idx = {"bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}}}
    cast = {"凯伊": {"id": "626652156", "portrait": True}}
    text = prompt.build_resources(idx, cast, ["凯伊"], {
        "626652156": {"faces": [], "expression_mode": "semantic_modular",
                        "expression_parts": [{"kind": "eyes", "labels": ["惊讶", "好奇"]}]}
    })
    assert "语义部件：eyes（惊讶、好奇）" in text
    assert "face 一律留空串" in text


def test_filter_rejects_unknown_assets_and_portrait_effects_for_narrator():
    constraints = annotation_constraints(
        {"bg": {"BG_River": 1}, "sounds": ["SE_Wave"],
         "enums": {"emoticon": {"1": {"sym": "[再见]", "cn": "Chat"}},
                   "action": {"6": {"verb": "jump", "cn": "跳跃"}}}},
        {"旁白": {"narrator": True, "portrait": False}},
    )
    clean, dropped = filter_annotation_row(
        {"face": "99", "emo": "Chat", "act": "jump", "fx": "特写", "se": "bad", "bg": "bad"},
        {"who": "旁白", "kind": "line"}, {"narrator": True, "portrait": False}, constraints,
    )
    assert clean == {}
    assert dropped == ["旁白无立绘，不能使用 face", "旁白无立绘，不能使用 emo",
                       "旁白无立绘，不能使用 act", "旁白无立绘，不能使用 fx",
                       "未知音效 bad", "未知背景 bad"]


def test_filter_accepts_only_variant_verified_face_id():
    constraints = annotation_constraints(
        {"bg": {}, "sounds": [], "enums": {"emoticon": {}, "action": {}},
         "face_capabilities": {"626652156": [{"spine_signature": "date", "outfit_key": "date", "faces": [
             {"id": "00", "sources": ["aa_verified"]}, {"id": "01", "sources": ["atlas_candidate"]}
         ]}] }},
        {"凯伊": {"id": "626652156", "portrait": True, "spine_signature": "date", "outfit_key": "date"}},
    )
    clean, dropped = filter_annotation_row({"face": "01"}, {"who": "凯伊", "kind": "line"},
                                            {"id": "626652156", "portrait": True, "spine_signature": "date", "outfit_key": "date"}, constraints)
    assert clean == {}
    assert dropped == ["凯伊 没有已验证表情 01"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_model_asset_constraints.py tests/test_annotation_constraints.py -q`

Expected: FAIL because the new interfaces and resource rendering are absent.

- [ ] **Step 3: Implement the minimum prompt and filter integration**

`build_resources` must accept either the existing `list[face]` shape or a capability dictionary with `faces`, `expression_mode`, and `expression_parts`, retaining backward compatibility for existing callers. For semantic/opaque roles with no verified face IDs, explicitly state that `face` must be empty; semantic parts may be described only as non-output hints.

Move the validation logic currently embedded in `annotate.main` into `annotation_constraints` and `filter_annotation_row`. Replace the loop body with that helper and append returned reasons to `dropped`. Maintain exact prior acceptance for known background/sound/enums and the existing `face_allowlist` variant behavior. Do not add any semantic part as an allowed faceId.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_model_asset_constraints.py tests/test_annotation_constraints.py tests/test_face_evidence.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

No Git repository exists in this workspace. Record this completed task in this plan instead of committing.

## Task 4: 只读差分诊断工具与真实样本静态验证

**Files:**
- Create: `tools/inspect_expression_capabilities.py`
- Create: `tests/test_expression_inspector.py`

**Interfaces:**
- Produces: `inspection_report(result: ValidationResult) -> dict[str, object]`.
- CLI: `python tools/inspect_expression_capabilities.py <skeleton-directory> --identifier <id>` prints JSON and returns non-zero only when file validation fails.

- [ ] **Step 1: Write the failing test**

```python
def test_inspection_report_separates_face_ids_from_semantic_parts(tmp_path):
    result = validate_spine(make_semantic_bundle(tmp_path / "date"), identifier="626652156")
    report = inspection_report(result)
    assert report["expression_mode"] == "semantic_modular"
    assert report["verified_face_ids"] == []
    assert report["semantic_parts"][0]["kind"] == "eyes"
    assert "需要在 AA 中记录实际 faceId" in report["next_step"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_expression_inspector.py -q`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the minimum diagnostic tool**

The tool must call `validate_spine`, print the source files, identifier, skeleton signature, outfit key, classification, numeric candidate face IDs, semantic parts and a conservative next-step message. It must not write to AA data, the SQLite database, or the source directory.

- [ ] **Step 4: Run automatic tests and real static inspection**

Run:

```powershell
pytest -q
python tools/inspect_expression_capabilities.py "D:\桌面\蔚蓝档案二创\角色立绘与美术周边\官方角色立绘\天童凯伊（约会服）\Kei_Date_Outfit" --identifier 626652156
```

Expected: all tests pass; diagnostic reports `semantic_modular`, the real skeleton SHA/outfit key, and non-empty semantic parts but no fabricated verified face IDs.

- [ ] **Step 5: Record generated-sample boundary**

Create a dated report under `04-素材机制实验\实施验证\` containing the input-story SHA-256, skeleton SHA-256, the diagnostic JSON, the generated model constraint summary, and either:

- a generated `.aap` validation report if the user supplies/chooses an AA Identifier and manually confirms face mappings; or
- a clear `blocked_on_aa_face_mapping` result which states that no unverified `faceId` was emitted.

Do not start AA, import assets, or choose a new Identifier without the user’s explicit instruction.

- [ ] **Step 6: Commit**

No Git repository exists in this workspace. Record this completed task in this plan instead of committing.

## Task 5: 计划自检与交付

**Files:**
- Modify: this plan’s task checkboxes as each task completes.
- Modify: `docs/superpowers/specs/2026-07-28-constrained-generation-expression-capabilities-design.md` only if implementation uncovers a corrected fact.

- [ ] **Step 1: Review spec coverage**

Confirm Task 1 covers classification; Task 2 covers storage/scoping; Task 3 covers strict model output; Task 4 covers the requested real skeleton evidence and safe AA boundary.

- [ ] **Step 2: Scan implementation plan for placeholders**

Run: `rg -n "TBD|TODO|implement later|fill in details|Similar to Task" docs/superpowers/plans/2026-07-28-constrained-generation-expression-capabilities.md`

Expected: no matches.

- [ ] **Step 3: Run final verification**

Run: `pytest -q`

Expected: all tests pass.

- [ ] **Step 4: Hand off**

Report changed modules, passed test count, real skeleton diagnostic result, and the only remaining AA-side action (if any): manually record a tested faceId mapping for the semantic modular outfit before the model may emit face changes for it.

## Execution Record — 2026-07-28

- [x] Task 1 — 新增编号完整差分、语义模块差分、无标签骨骼三类解析；测试先失败后通过。
- [x] Task 2 — 新增按骨骼变体隔离的 `expression_part` 数据表与导出；语义部件不进入 faceId 白名单。
- [x] Task 3 — 提示词显示语义部件但禁止将其输出为 faceId；模型响应的 face、背景、音效、气泡、动作、立绘效果均经过独立白名单过滤。
- [x] Task 4 — 新增只读诊断工具，并使用真实剧情与 `Kei_Date_Outfit` 完成静态约束演练。
- [x] 全量验证 — `python -m pytest -q`：147 passed。
- [x] 实际样本记录 — `04-素材机制实验\实施验证\2026-07-28-凯伊约会服严格约束生成演练.md`。
- [ ] AA 写入验证 — 需要用户指定/确认该约会服的 AA Identifier，并在 AA 中实际记录至少一个可用 faceId 后执行；未在本轮擅自写入。
