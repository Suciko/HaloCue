# 初审角色骨骼头像选择器实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 AI 初审的角色映射与骨骼选择弹层中加入头像、来源分组和当前选中状态，让自定义骨骼优先且易于辨认。

**Architecture:** 复用现有 `/api/characters` 的 `avatar`、`source`、`club` 和 `faces` 字段。初审结果先以稳定的文字占位渲染，再由一次按角色标识/名称的候选查询补全头像元数据；选择弹层将结果分成自定义和官方两个列表，选择动作继续写入现有 `state.mapping`。

**Tech Stack:** 原生 JavaScript DOM、现有 CSS 变量与组件、Python `pytest`、Node UI runtime harness。

## Global Constraints

- 自定义骨骼始终排在官方骨骼之前。
- 头像为空或加载失败时使用固定尺寸的角色首字占位，不能造成布局跳动。
- 不把本机文件路径或 API 密钥暴露到页面。
- 保留搜索、旁白、未指定和现有角色映射行为。
- 不改动骨骼导入、表情标注和背景标注流程。

---

### Task 1: Lock the avatar and grouping behavior with failing UI tests

**Files:**
- Modify: `tests/test_ui_preflight_timeline.py` near the existing preflight mapping tests
- Modify: `tests/ui_runtime_harness.js` only if the new image/error DOM behavior is unsupported by the harness

**Interfaces:**
- Consumes: `AppRuntime.renderPreflight`, `AppRuntime.openCastPicker`, and `/api/characters` responses.
- Produces: executable regression coverage for row avatars, custom-first groups, fallback placeholders, and selected state.

- [ ] **Step 1: Write the failing tests**

  Add one runtime test that renders two characters with `avatar`, `source`, `club`, and `faces`, opens the picker, and asserts:

  ```javascript
  const groups = [...h.get('#castResults').children]
    .filter(node => node.dataset.castGroup)
    .map(node => node.dataset.castGroup);
  const cards = [...h.get('#castResults').querySelectorAll('.cast-result')];
  console.log(JSON.stringify({
    groups,
    firstAvatar: cards[0].querySelector('img')?.src || '',
    firstSelected: cards[0].getAttribute('aria-pressed'),
    rowAvatar: h.get('#preflightCast').querySelector('img')?.src || ''
  }));
  ```

  Add a second test with an item lacking `avatar` and assert that `.cast-avatar-fallback` contains the first visible character and remains present after the image error callback.

- [ ] **Step 2: Run the focused tests and verify they fail for the missing behavior**

  Run: `pytest tests/test_ui_preflight_timeline.py -k "cast or avatar" -v`

  Expected: FAIL because the current result rows contain no image and the picker has no group markers or avatar cards.

### Task 2: Add avatar metadata hydration and grouped candidate rendering

**Files:**
- Modify: `js/app.js:730-740` (`renderPreflight` role mapping rows)
- Modify: `js/app.js:899-935` (`openCastPicker`, `searchCharacters`, `pickCharacter`)
- Modify: `css/app.css:205-209` and nearby preflight styles

**Interfaces:**
- Consumes: candidate objects `{ident, name, club, spine, faces, source, avatar}` from `/api/characters`.
- Produces: `.preflight-avatar`, `.cast-avatar`, `.cast-avatar-fallback`, `[data-cast-group]`, and `aria-pressed` UI state.

- [ ] **Step 1: Implement a fixed-size avatar helper**

  Add a small DOM helper in `js/app.js` that creates a wrapper with a fixed 40px/52px size, appends an image when `avatar` is present, and switches to a fallback span containing the first non-whitespace character when the image emits `error`. Set `alt` to the character name and keep the wrapper present for missing images.

- [ ] **Step 2: Hydrate initial preflight rows before rendering**

  Add an async helper that queries `/api/characters?q=<id or name>` once per mapped portrait, caches the first exact `ident` match, and copies only public metadata (`avatar`, `source`, `club`, `faces`) into the preflight character item. Call it in `runPreflight` before `renderPreflight`; failures leave the existing text fallback intact.

- [ ] **Step 3: Render the initial mapping rows with avatars**

  Keep the current speaker, mapped name, source label, reason, and “修改” button. Insert the 40px avatar before the text block. For narrator/unset rows use the same fallback helper with “旁白” or “未指定”.

- [ ] **Step 4: Render picker candidates as custom-first groups**

  Replace the flat `items.forEach` in `searchCharacters` with two groups. Normalize `item.source === 'custom' || item.source === 'current_story_custom'` as custom; unknown sources are official. Hide empty group headings. Each card includes the 52px avatar, name, metadata, `data-ident`, and `aria-pressed="true"` for the current mapping. Preserve the existing click handler and search failure/empty states.

- [ ] **Step 5: Add compact responsive styles**

  Style group headings, avatar wrappers, fallback initials, card selected state, and metadata truncation using existing colors and spacing. Use `min-width: 0`, `overflow-wrap: anywhere`, and a two-column card layout that collapses cleanly on narrow screens without horizontal overflow.

- [ ] **Step 6: Run the focused tests and confirm green**

  Run: `pytest tests/test_ui_preflight_timeline.py -k "cast or avatar" -v`

  Expected: all new tests pass and no existing preflight runtime tests regress.

### Task 3: Verify the complete UI contract and responsive behavior

**Files:**
- Modify: `tests/test_ui_polish_contract.py` only if the contract needs explicit selectors for the new stable classes
- Modify: `tests/test_ui_preflight_timeline.py` for any discovered regression case

**Interfaces:**
- Consumes: the completed picker DOM and CSS classes from Task 2.
- Produces: full focused UI verification and a browser-level layout check.

- [ ] **Step 1: Run the complete UI runtime and contract tests**

  Run: `pytest tests/test_ui_preflight_timeline.py tests/test_ui_polish_contract.py -v`

  Expected: 0 failures.

- [ ] **Step 2: Run syntax and diff checks**

  Run: `node --check js/app.js; git diff --check`

  Expected: both commands exit 0.

- [ ] **Step 3: Verify the picker in the in-app browser**

  Open the preflight view at desktop and 390px widths, click “修改”, and confirm the custom section is above the official section, avatars are visible or use initials, the selected card is marked, and long names do not push the close/action controls off-screen.

- [ ] **Step 4: Commit the implementation**

  ```powershell
  git add js/app.js css/app.css tests/test_ui_preflight_timeline.py tests/test_ui_polish_contract.py
  git commit -m "feat: clarify preflight skeleton choices with avatars"
  ```

