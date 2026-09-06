# 2026-08-27 生产工作台可见性与纯旁白闭环修复

## 范围

- Release/context: HaloCue 1.0，client + backend + AI GalGame。
- Branch: `feature/1.0-runtime`。
- Issue/PR: 本地用户请求，未提供 GitHub Issue；未创建 PR。
- 最小切片：修复集成生产工作台被 DOM 观察器饿死的问题，并允许显式纯旁白方向在没有人物卡时完成确认和场景上下文配置。

## 根因与修复

1. `production-embed.js` 的素材上下文恢复函数运行在 subtree `MutationObserver` 中，却无条件重写相同标题、搜索标签和 placeholder。相同值写入仍会产生新的 DOM 变更，形成微任务循环，使生产工作台保持隐藏并阻塞浏览器主线程。
2. 三处写入现在仅在值实际变化时执行；`production-embed.js` 缓存版本更新为 `20260827-10`。
3. StoryBlueprint 新增可选的显式 `narrator_only=true` 语义。只有该值严格为 true 且 `characters=[]` 时才允许无主要角色；普通方向缺少角色仍返回 `provider_output_invalid`。
4. Brief 确认、场景上下文和写作 UI 都识别纯旁白方向：人物卡可为空，老师不能作为角色出场；普通方向仍至少需要一张已确认人物卡。
5. 真实 Provider 提示明确要求纯旁白时返回 `narrator_only=true`、空角色数组；本地模拟 Provider采用同一规则。`app.js` 缓存版本更新为 `20260827-126`。

## 真实 Provider 证据

- 隔离作品：`work-080cd9937743`。
- Provider：真实 `gemini-3.7-flash`，非 simulation。
- 生成结果：`narrator_only=true`、`characters=[]`、`mode=text_reading`。
- 确认结果：StoryBlueprint `accepted`，Brief 的 `character_card_ids=[]`、`has_sensei=false`。
- API key 仅从本机 DPAPI 加密配置读取，未写入仓库或报告。

## 验证

- `python tools/quality_regression.py --base-url http://127.0.0.1:8932 --run-project "未命名作品 · v1" --output ".scratch/clean-final-loop-20260827-01/report-final"`
  - 通过：4 个视口、5 个加载/失败/深链边界。
- `pytest -q services/halocue/writing/tests/test_conversation_slice.py services/halocue/writing/tests/test_http_api.py services/halocue/writing/tests/test_provider_http_recovery.py services/halocue/writing/tests/test_release_integrity.py services/halocue/production/tests/test_http_api.py services/halocue/integrated/tests/test_gateway.py`
  - 通过：`198 passed in 99.62s`。
- `node --check services/halocue/writing/web/app.js`
  - 通过。
- `node --check services/halocue/writing/web/production-embed.js`
  - 通过。
- `git diff --check`
  - 退出码 0；仅有现有 LF/CRLF 提示。

## 变更路径

- `services/halocue/writing/src/halocue_writing/providers.py`
- `services/halocue/writing/src/halocue_writing/service.py`
- `services/halocue/writing/web/app.js`
- `services/halocue/writing/web/index.html`
- `services/halocue/writing/web/production-embed.js`
- `services/halocue/writing/tests/test_conversation_slice.py`
- `services/halocue/writing/tests/test_http_api.py`

## 提交状态与剩余外部项

当前工作树在本切片开始前已有同文件的大量未提交改动，因此没有创建会混入他人工作的提交。修复保留在当前工作树中。

下列项目不是本切片可安全伪造的代码闭环：正式 AA 工作区写入、Windows 打包应用中的原生选择器、真实 Spine CLI/授权素材、Provider 实际费用与缓存 receipt。429/504 的受控 HTTP 恢复路径已由 `test_provider_http_recovery.py` 覆盖，但没有故意攻击真实 Gemini relay。

下一步：在干净分支按上述标记选择性整理提交，或在具备正式 AA/Spine 环境的机器上执行人工验收。

## 下一对话启动说明

1. 从仓库根目录读取本交接文档、`AGENTS.md` 和 `.agents/skills/halocue-session-governance/SKILL.md`。
2. 不要重置或覆盖当前工作树；本切片开始前已经存在大量同文件修改。
3. 先确认 `.scratch/clean-final-loop-20260827-01/report-final/report.json` 仍存在，再决定后续任务是整理提交，还是补正式 AA、Windows 原生选择器或 Spine 环境验收。
4. 如果整理提交，必须按本交接的“变更路径”和具体标记逐块审查，不能把整个脏工作树直接提交。
5. 不要把 Gemini API key、DPAPI 文件、正式 AA 数据或测试生成物加入 Git。
