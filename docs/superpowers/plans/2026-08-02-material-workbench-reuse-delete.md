# Material Workbench Reuse and Copy Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有抽屉式素材库升级为应用内全屏素材工作台，让用户安全地浏览、预览、复制和按章节移除自定义素材，并与 AI 初审、草稿审查、背景时间线及独立骨骼表情标注工作区联动。

**Architecture:** 后端继续以 `asset_install` 为自定义素材事实来源，复用 `HistoryAssetBrowser` 的历史发现、内容指纹、不透明令牌和 `copy_to_story()` 事务；新增系列聚合、安全预览、章节副本与引用检查接口，并在 `aa_registry.py` 中提供对称的副本移除事务。前端将 `library.js` 拆为工作区路由、预览、复制、副本管理和表情标注模块；全屏工作台只持有浏览器安全标识，通过结构化返回上下文刷新 AI 初审或草稿审查。

**Tech Stack:** Python 3 标准库、SQLite、原生 JavaScript、HTML、CSS、`http.server` 路由、pytest、Node VM 前端行为测试、Playwright 真实浏览器验收。

## Global Constraints

- 界面文案与新增注释使用中文。
- 严格 CSP：禁止内联脚本、内联事件和 `eval`；事件使用 `addEventListener`，不可信文本使用 `textContent`。
- 浏览器不得接收 `source_path`、`install_path`、`scope`、AA 数据目录或任何服务器绝对路径。
- 文件选择与剧情恢复继续使用 `file_token` / `story_token` 不透明令牌；不得破坏 `/api/story/current` 不返回 `source_path` 的契约。
- 自定义素材必须是当前/历史剧情作用域内 `status='registered'` 且来源属于 `overrides`、`custom`、本地导入或 `history_import` 的条目；`observed`、`verified`、`builtin`、`database`、`library` 不得进入自定义素材展示面。
- 每个 AA 剧情工程必须拥有独立素材副本和登记记录；素材工作台不得创建跨工程运行时引用。
- BGM 原生登记契约未开放，本轮不把 BGM 显示为可复制或可删除的工作台资产。
- 删除默认只移除一个明确章节副本；有草稿引用时必须阻止并返回安全引用位置；本轮不提供“删除所有章节副本”或“自动替换引用后删除”。
- 所有文件系统写入必须有原子提交或可回滚事务；同内容重复复制幂等，同名不同内容不得静默覆盖。
- 每个生产行为先写失败测试并确认按预期失败，再写最小实现；每个任务结束运行相关回归并单独提交。
- 修改已有文件前复制到 `backup-20260802-material-workbench/` 对应相对路径；该目录已由 Git 忽略。
- 最终必须运行 `python -m pytest`、逐个 `node --check js/*.js`，并用真实浏览器在宽屏、`900px`、`680px`、`470px`、`390px` 验收无页面级横向滚动。

---

### Task 1: 系列素材聚合、当前剧情状态和安全令牌

**Files:**
- Modify: `asset_catalog.py`
- Modify: `history_assets.py`
- Modify: `webui.py`
- Test: `tests/test_asset_library.py`
- Test: `tests/test_story_asset_api.py`

**Interfaces:**
- Consumes: `asset_catalog._is_story_custom_row(row, metadata) -> bool`、`StoryWorkspaceRegistry.resolve_story_token(token) -> StoryContext`、`HistoryAssetBrowser` 已有历史记录指纹和令牌缓存。
- Produces: `HistoryAssetBrowser.list_library(con, *, current_context: StoryContext | None) -> dict`、`HistoryAssetBrowser.preview_path(preview_token: str) -> tuple[Path, str]`、`GET /api/assets/library?story_token=...`、`GET /api/assets/library/preview?preview_token=...`。

- [ ] **Step 1: 备份将修改的后端文件**

```powershell
$backup = 'backup-20260802-material-workbench'
New-Item -ItemType Directory -Force "$backup\tests" | Out-Null
Copy-Item asset_catalog.py,history_assets.py,webui.py $backup
Copy-Item tests\test_asset_library.py,tests\test_story_asset_api.py "$backup\tests"
```

- [ ] **Step 2: 写系列聚合和安全令牌失败测试**

在 `tests/test_asset_library.py` 增加真实 SQLite 目录夹具，断言当前剧情状态、章节安全标识和内置素材过滤：

```python
def test_library_groups_custom_copies_and_marks_current_story(tmp_path):
    con, current, browser = library_fixture(tmp_path)
    payload = browser.list_library(con, current_context=current)
    rain = payload["backgrounds"][0]
    assert rain["name"] == "雨夜天台"
    assert rain["registered_in_current"] is True
    assert rain["copy_count"] == 2
    assert all(copy["copy_token"].startswith("copy-") for copy in rain["copies"])
    assert "scope" not in repr(payload)
    assert str(tmp_path) not in repr(payload)


def test_library_excludes_observed_verified_and_bgm_rows(tmp_path):
    con, current, browser = mixed_source_library_fixture(tmp_path)
    payload = browser.list_library(con, current_context=current)
    assert payload["counts"] == {
        "characters": 0, "backgrounds": 1, "sounds": 0, "bgms": 0
    }
```

在 `tests/test_story_asset_api.py` 增加令牌篡改与路径泄漏测试：

```python
def test_library_preview_uses_opaque_token_and_rejects_tampering(running_server):
    base, story_token, project_root = running_server
    status, payload = _request(base, "/api/assets/library?story_token=" + story_token)
    token = payload["backgrounds"][0]["preview_token"]
    assert status == 200
    assert str(project_root) not in repr(payload)
    assert _request_bytes(base, "/api/assets/library/preview?preview_token=" + token)[0] == 200
    assert _request_bytes(base, "/api/assets/library/preview?preview_token=" + token + "x")[0] == 404
```

- [ ] **Step 3: 运行测试并确认按预期失败**

Run: `python -m pytest tests/test_asset_library.py tests/test_story_asset_api.py -k "library_groups or library_excludes or library_preview" -q`

Expected: FAIL，原因是 `HistoryAssetBrowser.list_library` / `preview_path` 和预览路由尚不存在，而不是夹具或语法错误。

- [ ] **Step 4: 实现聚合记录与进程内不透明令牌**

在 `history_assets.py` 增加只保存在服务进程内的安全记录，不把路径序列化给浏览器：

```python
@dataclass(frozen=True)
class _LibraryCopy:
    kind: str
    aa_key: str
    sha256: str
    scope: str
    chapter: str
    install_path: Path
    preview_path: Path | None


def list_library(self, con, *, current_context: StoryContext | None) -> dict:
    """聚合已登记自定义副本，并为预览、复制和副本管理签发不透明令牌。"""
    rows = self._custom_catalog_rows(con)
    current_scope = str(current_context.scope) if current_context else ""
    groups = self._group_library_rows(rows)
    return self._public_library_payload(groups, current_scope=current_scope)


def preview_path(self, preview_token: str) -> tuple[Path, str]:
    """重新核验目录边界和内容指纹后返回预览文件与 MIME 类型。"""
    copy = self._library_copy_for_preview_token(preview_token)
    current = self._reload_library_copy(copy)
    if current.sha256 != copy.sha256 or current.preview_path is None:
        raise HistoryAssetError("preview_changed", "素材预览已变化，请刷新工作台", 409)
    if not self._inside(current.install_path, current.preview_path):
        raise HistoryAssetError("preview_outside_copy", "素材预览位置无效", 404)
    return current.preview_path, self._preview_mime(current.kind, current.preview_path)
```

`list_library()` 必须按 `(kind, aa_key, sha256)` 聚合，返回的单项结构固定为：

```python
{
    "kind": "background", "aa_key": "rain_roof", "sha256": "digest-001",
    "name": "雨夜天台", "asset_role": "chapter_only", "series_name": "",
    "details": {"resolution": "1920×1080"},
    "registered_in_current": True, "preview_available": True,
    "preview_token": "preview-opaque-token", "copy_count": 2,
    "copies": [{"chapter": "第二章", "is_current": True, "copy_token": "copy-opaque-token"}],
}
```

预览解析必须重新查询 catalog，确认仍为 `registered` 自定义素材、真实文件仍位于已登记副本目录内且内容未变。更新 `webui.py`：`GET /api/assets/library` 可选解析 `story_token`，预览路由只接受 `preview_token`，并复用现有 Range 响应辅助函数支持音效。

- [ ] **Step 5: 运行后端测试并确认通过**

Run: `python -m pytest tests/test_asset_library.py tests/test_story_asset_api.py -q`

Expected: PASS，API JSON 中无物理路径，篡改令牌返回稳定 404。

- [ ] **Step 6: 提交**

```powershell
git add asset_catalog.py history_assets.py webui.py tests/test_asset_library.py tests/test_story_asset_api.py
git commit -m "feat: add safe reusable asset catalog"
```

### Task 2: 统一复制到当前剧情事务和结构化进度

**Files:**
- Modify: `history_assets.py`
- Modify: `webui.py`
- Test: `tests/test_history_assets.py`
- Test: `tests/test_story_asset_api.py`

**Interfaces:**
- Consumes: Task 1 的 `copy_token`、`StoryContext`、现有 `HistoryAssetBrowser.copy_to_story(history_asset_token, story_context, *, con, running_probe)`。
- Produces: `HistoryAssetBrowser.copy_library_asset(copy_token, story_context, *, con, running_probe) -> dict`、`POST /api/assets/library/copy-to-story`；成功结果含 `state='registered'` 和浏览器安全素材卡。

- [ ] **Step 1: 备份本任务首次修改的测试文件**

```powershell
Copy-Item tests\test_history_assets.py backup-20260802-material-workbench\tests
```

- [ ] **Step 2: 写复制幂等、冲突和剧情切换失败测试**

```python
def test_library_copy_reuses_history_transaction_and_is_idempotent(tmp_path):
    browser, con, source_token, current = reusable_background_fixture(tmp_path)
    first = browser.copy_library_asset(source_token, current, con=con)
    second = browser.copy_library_asset(source_token, current, con=con)
    assert first["state"] == "registered"
    assert second["state"] == "already_registered"
    assert second["asset"]["aa_key"] == "rain_roof"


def test_library_copy_refuses_stale_target_story(tmp_path):
    base, source_token, old_story_token, new_story_token = switched_story_server(tmp_path)
    status, body = _post(base, "/api/assets/library/copy-to-story", {
        "story_token": old_story_token, "source_copy_token": source_token,
        "kind": "background", "aa_key": "rain_roof", "sha256": "digest",
    })
    assert status == 409
    assert body["code"] == "story_context_changed"
```

同时保留现有背景、音效、完整 Spine 角色、源缺失、源变化、AA 运行中和同名冲突测试，不复制测试实现。

- [ ] **Step 3: 运行失败测试**

Run: `python -m pytest tests/test_history_assets.py tests/test_story_asset_api.py -k "library_copy" -q`

Expected: FAIL，原因是统一复制方法和路由不存在。

- [ ] **Step 4: 用已有事务实现统一复制入口**

```python
def copy_library_asset(
    self,
    copy_token: str,
    story_context: StoryContext,
    *,
    con=None,
    running_probe=None,
) -> dict[str, Any]:
    record = self._library_copy_for_token(copy_token)
    history_token = self._history_token_for_copy(record)
    result = self.copy_to_story(
        history_token, story_context, con=con, running_probe=running_probe
    )
    return {"state": "registered", "asset": result, **result}
```

实际实现不得只转调旧 token：必须在复制前重新发现源副本、核对 `kind`、`aa_key`、`sha256`、自定义来源和剧情 token 对应的不可变目标 scope。`webui.py` 的请求体只接受：

```json
{
  "story_token": "story-opaque-token",
  "kind": "background",
  "aa_key": "rain_roof",
  "sha256": "digest-001",
  "source_copy_token": "copy-opaque-token"
}
```

错误统一为 `{ok:false, code, message, action}`，例如 `aa_running` 的 `action` 为“关闭 AA 后在原位置重试”。成功后服务端用 `list_story_assets()` 返回该素材的新安全卡，前端无需猜测路径。

- [ ] **Step 5: 运行复制相关回归**

Run: `python -m pytest tests/test_history_assets.py tests/test_story_asset_api.py -q`

Expected: PASS；完整角色四类文件仍作为一组复制，同名不同内容仍返回 409。

- [ ] **Step 6: 提交**

```powershell
git add history_assets.py webui.py tests/test_history_assets.py tests/test_story_asset_api.py
git commit -m "feat: copy library assets into current story"
```

### Task 3: 草稿素材引用扫描

**Files:**
- Modify: `draft_store.py`
- Test: `tests/test_draft_store.py`

**Interfaces:**
- Consumes: `DraftStore.get(token)` 返回的真实 cards、已有草稿锁和 card_id。
- Produces: `DraftStore.find_asset_references(*, token: str, kind: str, aa_key: str) -> list[dict]`；引用项只含 `card_id`、`kind`、`label`、`line_hint`。

- [ ] **Step 1: 备份并写失败测试**

```powershell
Copy-Item draft_store.py backup-20260802-material-workbench
Copy-Item tests\test_draft_store.py backup-20260802-material-workbench\tests
```

```python
def test_find_asset_references_reports_background_sound_and_character_cards(tmp_path):
    store, token = populated_draft(tmp_path, cards=[
        dir_card("bg-1", "bg", "rain_roof"),
        dir_card("se-1", "se", "door_open"),
        line_card("line-1", "阿洛娜", "欢迎回来"),
    ], cast={"阿洛娜": {"kind": "character", "key": "custom_arona"}})
    assert store.find_asset_references(token=token, kind="background", aa_key="rain_roof") == [
        {"card_id": "bg-1", "kind": "directive", "label": "@bg rain_roof", "line_hint": 1}
    ]
    assert store.find_asset_references(token=token, kind="sound", aa_key="door_open")[0]["card_id"] == "se-1"
    assert store.find_asset_references(token=token, kind="character", aa_key="custom_arona")[0]["card_id"] == "line-1"
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest tests/test_draft_store.py -k find_asset_references -q`

Expected: FAIL，`DraftStore` 尚无该方法。

- [ ] **Step 3: 在同一草稿锁内扫描规范化引用**

```python
def find_asset_references(self, *, token: str, kind: str, aa_key: str) -> list[dict]:
    """返回删除素材前可公开展示的草稿引用，不返回剧本文本路径。"""
    with self._lock:
        session = self._require(token)
        cards = session["cards"]
        keys = {"background": {"bg"}, "sound": {"se", "sound"}}
        if kind in keys:
            return self._directive_asset_references(cards, keys[kind], aa_key)
        if kind == "character":
            speakers = self._speakers_bound_to_asset(session, aa_key)
            return self._character_asset_references(cards, speakers)
        raise ValueError("不支持的素材类型")
```

背景匹配 `kind='dir'` 且 `current.cmd == 'bg'`；音效匹配 `se` / `sound`；角色先通过 session 的最终 cast/bindings 找到映射到 `aa_key` 的说话者，再报告对应台词卡。结果按卡片顺序排序，`line_hint` 是 1 起始的卡片序号，不包含原剧本物理路径或全文。

- [ ] **Step 4: 运行草稿测试**

Run: `python -m pytest tests/test_draft_store.py -q`

Expected: PASS，读取引用不改变 `draft_version` 或 `content_revision`。

- [ ] **Step 5: 提交**

```powershell
git add draft_store.py tests/test_draft_store.py
git commit -m "feat: report draft asset references"
```

### Task 4: 指定章节副本的安全移除事务

**Files:**
- Modify: `aa_registry.py`
- Modify: `asset_catalog.py`
- Modify: `history_assets.py`
- Modify: `webui.py`
- Test: `tests/test_aa_registry.py`
- Create: `tests/test_asset_copy_removal.py`
- Modify: `tests/test_story_asset_api.py`

**Interfaces:**
- Consumes: Task 1 的 `copy_token`、Task 3 的 `find_asset_references()`、`AAProjectTarget`、`asset_install` 当前副本记录。
- Produces: `aa_registry.remove_registered_asset(...) -> RemovalResult`、`HistoryAssetBrowser.describe_copy(copy_token, *, con) -> dict`、`HistoryAssetBrowser.remove_copy(copy_token, *, con, draft_store, running_probe) -> dict`、`GET /api/assets/library/copies`、`POST /api/assets/library/remove-copy`。

- [ ] **Step 1: 备份并写事务失败测试**

```powershell
Copy-Item aa_registry.py backup-20260802-material-workbench
Copy-Item tests\test_aa_registry.py backup-20260802-material-workbench\tests
```

```python
def test_remove_registered_background_updates_both_manifests_and_files(tmp_path):
    target, registration = registered_background_target(tmp_path, key="rain_roof")
    result = remove_registered_asset(
        target, kind="background", aa_key="rain_roof",
        expected_sha256=registration.sha256, running_probe=lambda: False,
    )
    assert result.changed is True
    for root in (target.project_dir, target.save_dir):
        assert "rain_roof" not in load_manifest(root)["BackgroundOverrides"]
        assert not (root / "backgrounds" / "rain_roof.png").exists()


def test_remove_registered_asset_rolls_back_files_and_manifests_on_failure(tmp_path, monkeypatch):
    target = registered_sound_target(tmp_path, key="door_open")
    original_replace = aa_registry.os.replace
    calls = 0
    def fail_second_manifest(source, destination):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("simulated manifest replacement failure")
        return original_replace(source, destination)
    monkeypatch.setattr(aa_registry.os, "replace", fail_second_manifest)
    with pytest.raises(AssetRemovalError):
        remove_registered_asset(target, kind="sound", aa_key="door_open",
                                expected_sha256="digest")
    assert_target_still_registered(target, "sound", "door_open")
```

在新文件 `tests/test_asset_copy_removal.py` 写引用阻止和只删一章测试：

```python
def test_remove_copy_is_blocked_when_current_draft_references_asset(tmp_path):
    fixture = removal_fixture(tmp_path, referenced=True)
    with pytest.raises(HistoryAssetError) as error:
        fixture.browser.remove_copy(
            fixture.copy_token, con=fixture.con, draft_store=fixture.store
        )
    assert error.value.code == "asset_in_use"
    assert error.value.details["references"][0]["card_id"] == "bg-1"


def test_remove_copy_only_removes_selected_chapter(tmp_path):
    fixture = removal_fixture(tmp_path, chapters=("第一章", "第二章"))
    fixture.browser.remove_copy(
        fixture.second_chapter_token, con=fixture.con, draft_store=fixture.store
    )
    payload = fixture.browser.list_library(fixture.con, current_context=fixture.first)
    assert payload["backgrounds"][0]["copy_count"] == 1
    assert payload["backgrounds"][0]["copies"][0]["chapter"] == "第一章"
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest tests/test_aa_registry.py tests/test_asset_copy_removal.py -q`

Expected: FAIL，移除事务、稳定异常类型和副本 API 尚不存在。

- [ ] **Step 3: 实现对称、可回滚移除事务**

在 `aa_registry.py` 增加：

```python
@dataclass(frozen=True)
class RemovalResult:
    kind: str
    aa_key: str
    install_dirs: tuple[Path, ...]
    manifest_paths: tuple[Path, ...]
    changed: bool


def remove_registered_asset(
    target: AAProjectTarget,
    *,
    kind: str,
    aa_key: str,
    expected_sha256: str,
    running_probe: Callable[[], bool] | None = None,
) -> RemovalResult:
    directories = target.directories()
    with _removal_transaction(directories, running_probe) as transaction:
        entries = transaction.validate_registered_copy(kind, aa_key, expected_sha256)
        transaction.stage_files(entries)
        transaction.remove_manifest_entries(kind, aa_key)
        transaction.commit()
    return RemovalResult(kind, aa_key, directories, target.manifest_paths(), True)
```

事务顺序固定为：校验标识和 AA 未运行；核对 project/save manifest 条目一致；核对目标文件均位于对应工程根目录；把待删文件移动到同盘 staging；写两个临时 manifest 并原子替换；删除 staging。任一步失败时恢复原 manifest 和文件。成功后 `asset_catalog.remove_story_copy(con, *, scope, kind, aa_key, sha256)` 在单个 SQLite 事务中删除对应 `asset_install` 行；只有最后一个副本消失时才清理孤立 profile。

- [ ] **Step 4: 实现引用检查、确认描述和 API**

`GET /api/assets/library/copies?preview_token=...` 返回安全副本列表和 `references`。`POST /api/assets/library/remove-copy` 请求体：

```json
{"copy_token":"copy-opaque-token","confirm_chapter":"第二章"}
```

服务端必须比较 `confirm_chapter` 与 token 绑定章节，且重新扫描草稿引用。`HistoryAssetError` 扩展可选 `details` 字段，路由返回 `{code,message,action,details}`；`asset_in_use` 的 `details.references` 供前端跳转卡片。

- [ ] **Step 5: 运行移除和 API 回归**

Run: `python -m pytest tests/test_aa_registry.py tests/test_asset_copy_removal.py tests/test_story_asset_api.py -q`

Expected: PASS；被引用素材和 AA 运行时不会产生部分删除，其他章节副本与 profile 保留。

- [ ] **Step 6: 提交**

```powershell
git add aa_registry.py asset_catalog.py history_assets.py webui.py tests/test_aa_registry.py tests/test_asset_copy_removal.py tests/test_story_asset_api.py
git commit -m "feat: safely remove one story asset copy"
```

### Task 5: 应用内全屏工作台骨架和模块边界

**Files:**
- Modify: `ui.html`
- Modify: `js/library.js`
- Create: `js/library_preview.js`
- Create: `js/library_transfer.js`
- Create: `js/library_copies.js`
- Rename responsibility in: `js/library.js` (保留全局初始化入口)
- Modify: `css/layout.css`
- Modify: `css/app.css`
- Modify: `tests/test_ui_asset_library.py`
- Modify: `tests/test_csp_headers.py`

**Interfaces:**
- Consumes: Task 1/2/4 API；现有 `window.Api`、`window.StoryStore` 和 `AssetLibraryWorkbench` 打开入口。
- Produces: `window.StoryUI.AssetWorkbench.open(context)`、`.close()`、`.refresh()`；模块事件 `assetworkbench:copied`、`assetworkbench:removed`；三栏全屏 `<section id="assetWorkbench">`。

- [ ] **Step 1: 备份前端文件和测试**

```powershell
Copy-Item ui.html backup-20260802-material-workbench
Copy-Item js\library.js backup-20260802-material-workbench
Copy-Item css\layout.css,css\app.css backup-20260802-material-workbench
Copy-Item tests\test_ui_asset_library.py,tests\test_csp_headers.py backup-20260802-material-workbench\tests
```

- [ ] **Step 2: 写全屏导航、返回焦点和 CSP 失败测试**

在 `tests/test_ui_asset_library.py` 的 Node VM 夹具中加载全部新模块并断言真实 DOM 状态：

```javascript
const workbench = new window.StoryUI.AssetWorkbench(document.getElementById('assetWorkbench'));
await workbench.open({origin: 'preflight', story_token: 'story-1', tasks: []});
assert.equal(document.getElementById('assetWorkbench').hidden, false);
assert.equal(document.getElementById('appShell').hidden, true);
await workbench.close();
assert.equal(document.getElementById('appShell').hidden, false);
assert.equal(document.activeElement, triggerButton);
```

在 `tests/test_csp_headers.py` 扩展实际 HTML/JS 检查，确保新脚本通过外链加载且不存在 `onclick=`、`innerHTML =` 或 `eval(`。

- [ ] **Step 3: 运行失败测试**

Run: `python -m pytest tests/test_ui_asset_library.py tests/test_csp_headers.py -q`

Expected: FAIL，全屏工作区节点和拆分模块尚不存在。

- [ ] **Step 4: 创建全屏 DOM 和工作区路由**

`ui.html` 将原 `assetLibraryDrawer` 改为：

```html
<section id="assetWorkbench" class="asset-workbench" aria-label="素材工作台" hidden>
  <header class="asset-workbench-header">
    <button id="assetWorkbenchBack" type="button" aria-label="返回">返回</button>
    <div><h2>素材工作台</h2><p id="assetWorkbenchContext"></p></div>
    <button id="assetWorkbenchTaskToggle" type="button" aria-controls="assetWorkbenchTasks">当前任务</button>
  </header>
  <div id="assetWorkbenchBody" class="asset-workbench-body">
    <section class="asset-workbench-catalog" aria-label="素材目录"><div id="assetWorkbenchFilters"></div><div id="assetWorkbenchList"></div></section>
    <section id="assetWorkbenchDetail" class="asset-workbench-detail" aria-label="素材详情"></section>
    <aside id="assetWorkbenchTasks" class="asset-workbench-tasks" aria-label="当前剧情任务"></aside>
  </div>
</section>
```

`library.js` 只管理上下文、筛选、选择、加载和进入/退出：

```javascript
function AssetWorkbench(root) {
  this.root = root;
  this.context = null;
  this.assets = [];
  this.selectedKey = null;
  this.returnFocus = null;
}
AssetWorkbench.prototype.open = async function (context) {
  this.context = sanitizeWorkbenchContext(context);
  this.returnFocus = document.activeElement;
  document.getElementById('appShell').hidden = true;
  this.root.hidden = false;
  await this.refresh();
};
AssetWorkbench.prototype.close = async function () {
  this.preview.stop();
  this.root.hidden = true;
  document.getElementById('appShell').hidden = false;
  await refreshWorkbenchOrigin(this.context);
  if (this.returnFocus && this.returnFocus.focus) this.returnFocus.focus();
};
AssetWorkbench.prototype.refresh = async function () {
  const query = '?story_token=' + encodeURIComponent(this.context.story_token || '');
  const payload = await window.Api.request('/api/assets/library' + query);
  this.assets = flattenLibraryPayload(payload);
  this.renderCatalog();
  this.restoreSelection();
};
```

返回上下文只允许 `origin`、`story_token`、`draft_token`、`card_id`、`asset_kind`、`request_id`、`tasks`；用白名单复制，拒绝存储路径字段。新脚本按依赖顺序在 `ui.html` 外链加载。

- [ ] **Step 5: 实现基础三栏和稳定尺寸**

在 CSS 使用工作区容器查询：

```css
.asset-workbench { container-type: inline-size; overflow: hidden; }
.asset-workbench-body {
  display: grid;
  grid-template-columns: clamp(330px, 28cqw, 360px) minmax(360px, 1fr) clamp(280px, 24cqw, 300px);
  min-width: 0;
}
@container (max-width: 900px) { .asset-workbench-body { grid-template-columns: 340px minmax(0, 1fr); } .asset-workbench-tasks { display: none; } }
@container (max-width: 680px) { .asset-workbench-body { display: block; } .asset-workbench-detail { display: none; } }
```

标题字号必须大于类型和状态标签；卡片 8px 或更小圆角；无卡片嵌套卡片。

- [ ] **Step 6: 运行前端行为、CSP 和语法测试**

Run: `python -m pytest tests/test_ui_asset_library.py tests/test_csp_headers.py -q`

Run: `Get-ChildItem js\*.js | ForEach-Object { node --check $_.FullName }`

Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```powershell
git add ui.html js/library.js js/library_preview.js js/library_transfer.js js/library_copies.js css/layout.css css/app.css tests/test_ui_asset_library.py tests/test_csp_headers.py
git commit -m "feat: add full-screen asset workbench shell"
```

### Task 6: 类型化目录、详情预览、复制进度和副本管理 UI

**Files:**
- Modify: `js/library.js`
- Modify: `js/library_preview.js`
- Modify: `js/library_transfer.js`
- Modify: `js/library_copies.js`
- Modify: `css/layout.css`
- Modify: `tests/test_ui_asset_library.py`

**Interfaces:**
- Consumes: `GET /api/assets/library` 返回的统一 item、Task 5 `AssetWorkbench`。
- Produces: 类型化目录行、详情预览、`TransferController.copy(item)`、`CopyManager.open(item)`、可执行中文错误反馈。

- [ ] **Step 1: 写目录信息层级和复制状态失败测试**

```javascript
await workbench.open({origin: 'topbar', story_token: 'story-1'});
const row = document.querySelector('[data-asset-key="background:rain:digest"]');
assert.equal(row.querySelector('.asset-name').textContent, '雨夜天台');
assert.equal(row.querySelector('.asset-kind').textContent, '背景');
assert.equal(row.querySelector('.asset-state').textContent, '未登记');
row.click();
assert.match(document.getElementById('assetWorkbenchDetail').textContent, /1920×1080/);
await workbench.transfer.copy(workbench.selected());
assert.deepEqual(progressStates, ['正在校验', '正在复制', '正在登记', '本章已登记']);
```

增加删除确认测试，断言按钮文案是“移除该章节副本”，有引用时显示卡片跳转按钮而不发删除请求。

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest tests/test_ui_asset_library.py -k "catalog or preview or copy or remove" -q`

Expected: FAIL，模块只有骨架。

- [ ] **Step 3: 实现类型化目录行和过滤**

目录始终显示名称、中文类型、当前剧情状态和一条弱辅助信息；背景使用 16:9 缩略图，角色使用头像/明确占位，音效使用 Lucide 已存在图标库中的播放图标或项目既有图标组件并显示时长。搜索覆盖名称、系列、章节和安全标签；类型用横向分段控制，窄屏不得把按钮文字压成竖排。

所有节点用 `document.createElement` 创建，用户数据只赋给 `textContent`、`alt` 和经过编码的 token URL；不得使用字符串拼 HTML。

- [ ] **Step 4: 实现详情预览和可访问音频控制**

`library_preview.js` 导出：

```javascript
function AssetPreview(root) { this.root = root; this.audio = null; }
AssetPreview.prototype.render = function (item) {
  this.stop();
  clearElement(this.root);
  if (item.kind === 'background') this.renderBackground(item);
  else if (item.kind === 'character') this.renderCharacter(item);
  else if (item.kind === 'sound') this.renderSound(item);
};
AssetPreview.prototype.stop = function () {
  if (!this.audio) return;
  this.audio.pause();
  this.audio.removeAttribute('src');
  this.audio.load();
  this.audio = null;
};
window.StoryUI.AssetPreview = AssetPreview;
```

背景展示可检查的大图；角色展示头像、文件完整度、表情数量和“打开表情标注”；音效提供播放/暂停、时长和加载错误。预览不可用时详情仍可管理，明确显示“预览不可用，副本记录仍可管理”。

- [ ] **Step 5: 实现复制进度和副本移除交互**

`library_transfer.js` 的复制状态机只使用四个稳定阶段；网络失败保留原位“重试”。`library_copies.js` 先 GET 副本描述，再显示包含素材名和章节名的确认句；确认按钮必须写“移除该章节副本”。删除成功后触发：

```javascript
window.dispatchEvent(new CustomEvent('assetworkbench:removed', {
  detail: {kind: item.kind, aa_key: item.aa_key, chapter: copy.chapter}
}));
```

复制成功同理触发 `assetworkbench:copied`，并刷新目录的 `registered_in_current`、副本列表和任务状态。

- [ ] **Step 6: 运行前端测试和语法检查**

Run: `python -m pytest tests/test_ui_asset_library.py -q`

Run: `Get-ChildItem js\*.js | ForEach-Object { node --check $_.FullName }`

Expected: PASS；错误信息均是中文可执行提示，不显示异常类名或服务器路径。

- [ ] **Step 7: 提交**

```powershell
git add js/library.js js/library_preview.js js/library_transfer.js js/library_copies.js css/layout.css tests/test_ui_asset_library.py
git commit -m "feat: complete asset workbench interactions"
```

### Task 7: AI 初审任务面板、返回刷新和明确等待反馈

**Files:**
- Modify: `js/app.js`
- Modify: `js/library.js`
- Modify: `ui.html`
- Modify: `css/app.css`
- Modify: `tests/test_ui_preflight_timeline.py`
- Modify: `tests/test_ui_asset_library.py`

**Interfaces:**
- Consumes: 现有 `state.preflight.assets/issues`、Task 5 `AssetWorkbench.open(context)`、Task 6 `assetworkbench:copied`。
- Produces: `buildPreflightAssetTasks(preflight) -> Array<Task>`、`openAssetWorkbench(context)`、`refreshAfterAssetWorkbench(context)`；初审“去补素材”入口和任务解决状态。

- [ ] **Step 1: 备份并写初审联动失败测试**

```powershell
Copy-Item js\app.js backup-20260802-material-workbench
Copy-Item tests\test_ui_preflight_timeline.py backup-20260802-material-workbench\tests
```

```javascript
renderPreflight({assets: [{kind:'background', name:'雨夜天台', status:'missing', location:'第 46 行'}], issues:[]});
document.querySelector('[data-preflight-action="open-workbench"]').click();
assert.equal(openedContext.origin, 'preflight');
assert.deepEqual(openedContext.tasks[0], {
  task_id: 'background:雨夜天台:第 46 行', kind: 'background',
  requested_name: '雨夜天台', source_location: {label: '第 46 行'},
  reason: '剧本引用但当前剧情未登记', candidate_keys: []
});
window.dispatchEvent(new CustomEvent('assetworkbench:copied', {detail:{kind:'background', aa_key:'rain'}}));
assert.equal(preflightRequests, 1);
assert.match(statusText, /正在重新核对/);
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest tests/test_ui_preflight_timeline.py tests/test_ui_asset_library.py -k "preflight and workbench" -q`

Expected: FAIL，初审尚未构造工作台任务上下文。

- [ ] **Step 3: 实现任务构造和进入/返回状态**

初审缺失背景、音效、角色生成统一任务；BGM 显示“当前版本尚未开放自定义 BGM 登记”，不提供虚假工作台候选。点击“去补素材”时保存当前滚动位置和焦点，打开全屏工作台并自动过滤到任务类型/候选。

复制成功不在前端自行把问题改成已解决：关闭工作台时重新调用 `/api/story/assets` 和 `/api/preflight`，以服务端结果为准。等待期间显示稳定阶段：

```text
正在读取当前剧情素材 → AI 正在重新核对全文 → 初审结果已刷新
```

失败时保留“重试初审”和“返回工作台”两个明确动作。

- [ ] **Step 4: 运行初审和工作台测试**

Run: `python -m pytest tests/test_ui_preflight_timeline.py tests/test_ui_asset_library.py -q`

Expected: PASS；当前剧情切换后旧工作台事件被 `story_token` 校验忽略。

- [ ] **Step 5: 提交**

```powershell
git add js/app.js js/library.js ui.html css/app.css tests/test_ui_preflight_timeline.py tests/test_ui_asset_library.py
git commit -m "feat: connect preflight tasks to asset workbench"
```

### Task 8: 草稿审查、背景时间线和快速历史抽屉联动

**Files:**
- Modify: `js/app.js`
- Modify: `js/history.js`
- Modify: `js/library.js`
- Modify: `js/cards.js`
- Modify: `tests/test_ui_preflight_timeline.py`
- Modify: `tests/test_ui_asset_tasks.py`

**Interfaces:**
- Consumes: 已有背景时间线、`HistoryDrawer.copy()`、`DraftStore.resolve_background_request()` 路由、Task 6 复制事件。
- Produces: `openAssetWorkbench({origin:'review', draft_token, card_id, asset_kind:'background'})`；复制后以最新 revision 原地更新对应 `@bg` 卡并保持 card_id。

- [ ] **Step 1: 写背景时间线进入工作台和版本冲突失败测试**

```javascript
timelineNode.querySelector('[data-bg-action="open-workbench"]').click();
assert.equal(openedContext.origin, 'review');
assert.equal(openedContext.card_id, 'bg-card-2');
assert.equal(openedContext.asset_kind, 'background');

await copiedFromWorkbench({kind:'background', aa_key:'rain_roof'}, openedContext);
assert.deepEqual(resolvePayload, {
  token:'draft-1', card_id:'bg-card-2', bg_name:'rain_roof', expected_draft_version:7
});
assert.equal(renderedCards.find(card => card.card_id === 'bg-card-2').current.arg, 'rain_roof');
```

另写 409 revision 冲突测试：素材保留在当前剧情，界面刷新草稿并提示“素材已复制；草稿已变化，请再次确认应用”。

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest tests/test_ui_preflight_timeline.py tests/test_ui_asset_tasks.py -k "workbench or timeline" -q`

Expected: FAIL，时间线尚无全屏工作台上下文和返回应用逻辑。

- [ ] **Step 3: 保留快速抽屉并增加完整工作台入口**

每个时间线节点继续提供“更换”打开当前剧情自定义背景选项；“从历史导入”继续打开紧凑 `HistoryDrawer`；新增“在素材工作台中查找”进入全屏工作区。用户选择/复制后，先重新 GET `/api/draft` 获取最新版本，再用已有 resolve 路由原地修改对应卡；永远不创建新 card_id。

点击时间线节点仍滚动到卡片并高亮；待补节点同时关联 `background_request` 的补背景动作。工作台返回后统一刷新 `/api/draft`、`/api/story/assets`、审查素材面板和时间线。

- [ ] **Step 4: 运行草稿联动回归**

Run: `python -m pytest tests/test_ui_preflight_timeline.py tests/test_ui_asset_tasks.py -q`

Expected: PASS；历史抽屉原有短流程不退化，版本冲突不会回滚已成功的素材复制。

- [ ] **Step 5: 提交**

```powershell
git add js/app.js js/history.js js/library.js js/cards.js tests/test_ui_preflight_timeline.py tests/test_ui_asset_tasks.py
git commit -m "feat: link review timeline with asset workbench"
```

### Task 9: 骨骼表情标注迁入独立工作区模块

**Files:**
- Create: `js/library_faces.js`
- Modify: `js/library.js`
- Modify: `ui.html`
- Modify: `css/layout.css`
- Modify: `tests/test_ui_asset_library.py`

**Interfaces:**
- Consumes: 现有 `/api/assets/library/character/face-analysis` 作业、Task 6 角色详情。
- Produces: `window.StoryUI.FaceWorkspace` 独立模块；从角色详情打开，关闭后返回同一素材和滚动位置。

- [ ] **Step 1: 写独立入口、进度和返回状态失败测试**

```javascript
workbench.select('character:custom_arona:digest');
document.querySelector('[data-asset-action="annotate-faces"]').click();
assert.equal(document.getElementById('faceWorkspace').hidden, false);
assert.equal(document.getElementById('assetWorkbench').hidden, true);
await faceWorkspace.start(false);
assert.deepEqual(phases, ['正在读取骨骼', '正在生成联系表', 'AI 正在识别表情', '标注完成']);
faceWorkspace.close();
assert.equal(document.getElementById('assetWorkbench').hidden, false);
assert.equal(workbench.selected().aa_key, 'custom_arona');
```

- [ ] **Step 2: 运行失败测试**

Run: `python -m pytest tests/test_ui_asset_library.py -k face -q`

Expected: FAIL，`FaceWorkspace` 尚未从旧 `library.js` 拆出且返回上下文不完整。

- [ ] **Step 3: 拆分而不改变后端标注契约**

把现有 `FaceWorkspace` 完整迁移到 `library_faces.js`，保持服务器作业轮询、取消、重试和结果渲染行为。角色详情只显示摘要和“打开表情标注”；标注本身占用独立大型工作区，不嵌入三栏详情。关闭时刷新当前角色 `details.expression_status/face_count`，失败时保留处理记录与重试按钮。

- [ ] **Step 4: 运行表情、CSP 和语法回归**

Run: `python -m pytest tests/test_ui_asset_library.py tests/test_csp_headers.py -q`

Run: `Get-ChildItem js\*.js | ForEach-Object { node --check $_.FullName }`

Expected: PASS；无内联事件或脚本，骨骼标注不进入主生成步骤。

- [ ] **Step 5: 提交**

```powershell
git add js/library_faces.js js/library.js ui.html css/layout.css tests/test_ui_asset_library.py
git commit -m "refactor: isolate spine face annotation workspace"
```

### Task 10: 响应式、真实浏览器 QA、用户手册和全量验证

**Files:**
- Modify: `css/layout.css`
- Modify: `css/app.css`
- Modify: `ui.html`
- Modify: `docs/superpowers/specs/2026-08-02-material-workbench-reuse-delete-design.md`（仅记录实际差异）
- Modify: `AA剧本编译器_用户测试反馈_2026-08-02.md`
- Create: `tests/test_ui_asset_workbench_responsive.py`

**Interfaces:**
- Consumes: 前九个任务的完整工作区和现有 Web 服务。
- Produces: 可复现的窄屏布局断言、更新后的用户帮助与验收记录；无新运行时 API。

- [ ] **Step 1: 写浏览器尺寸和溢出失败测试**

`tests/test_ui_asset_workbench_responsive.py` 启动真实服务，用 Playwright 注入确定性素材 API 数据后逐尺寸断言：

```python
@pytest.mark.parametrize("width,columns", [(1200, 3), (900, 2), (680, 1), (470, 1), (390, 1)])
def test_asset_workbench_has_no_page_overflow_and_expected_columns(page, app_url, width, columns):
    page.set_viewport_size({"width": width, "height": 900})
    open_populated_workbench(page, app_url)
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    assert page.locator(".asset-workbench-body").get_attribute("data-visible-columns") == str(columns)
```

再断言搜索框和分段按钮文字 `writing-mode` 为水平、最长名称不覆盖状态、详情层在窄屏可返回目录、任务栏在 `<900px` 可通过明确按钮打开而非彻底丢失。

- [ ] **Step 2: 运行失败测试并记录真实截图**

Run: `python -m pytest tests/test_ui_asset_workbench_responsive.py -q`

Expected: 初次可能因真实尺寸/溢出或缺少 `data-visible-columns` 失败；保存每个失败尺寸截图到 pytest 临时目录，先确认根因再改 CSS。

- [ ] **Step 3: 按容器实际宽度修正响应式细节**

只针对测试暴露的根因调整 tracks、`min-width:0`、文本两行截断、窄屏详情层和任务面板入口。不得用缩小字体随 viewport 变化规避布局；固定按钮和缩略图使用稳定尺寸/宽高比。用 `ResizeObserver` 只设置安全状态属性 `data-visible-columns`，不拼接样式文本。

- [ ] **Step 4: 更新帮助和项目反馈文档**

用户帮助明确说明：

- 推荐剧本格式及非标准格式会由 AI 初审通读；
- 每章都需要独立导入/复制并登记自定义素材；
- 素材工作台“复制到当前剧情”不是全局引用；
- 类型、系列/章节归属、预览、删除阻止和表情标注入口；
- 各等待阶段以及失败后的明确重试方式；
- 自定义 BGM 本轮仍未开放。

用户测试反馈文档记录已完成项、已知限制和真实验证结果；不要写尚未实现的状态。

- [ ] **Step 5: 运行专项和全量自动验证**

Run: `python -m pytest tests/test_asset_library.py tests/test_history_assets.py tests/test_asset_copy_removal.py tests/test_story_asset_api.py tests/test_ui_asset_library.py tests/test_ui_preflight_timeline.py tests/test_ui_asset_tasks.py tests/test_ui_asset_workbench_responsive.py tests/test_csp_headers.py -q`

Run: `Get-ChildItem js\*.js | ForEach-Object { node --check $_.FullName }`

Run: `python -m pytest`

Expected: 全部 PASS，skipped 数量只允许保持已知平台跳过，不新增失败。

- [ ] **Step 6: 用真实浏览器人工核对关键路径**

启动 `python webui.py`，在桌面和移动尺寸依次完成：顶部进入工作台；搜索和类型过滤；背景/角色/音效预览；历史副本复制到当前剧情；AI 初审任务返回刷新；背景时间线复制并原卡应用；有引用副本删除被阻止；无引用副本只删指定章节；进入和退出表情标注。检查浏览器控制台无 CSP、404、布局或未捕获异常。

- [ ] **Step 7: 检查工作区和提交最终改动**

```powershell
git diff --check
git status --short
git add css/layout.css css/app.css ui.html docs/superpowers/specs/2026-08-02-material-workbench-reuse-delete-design.md AA剧本编译器_用户测试反馈_2026-08-02.md tests/test_ui_asset_workbench_responsive.py
git commit -m "test: verify responsive asset workbench workflow"
```

提交前确认不包含 `aa_config.json`、`llm.json`、用户剧本、AA 数据、截图临时文件、绝对路径或凭据。
