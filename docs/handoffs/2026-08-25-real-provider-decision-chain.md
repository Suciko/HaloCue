# 2026-08-25 真实 Provider 决策链验收

## 范围

在隔离数据目录 `.scratch/browser-acceptance-20260825/` 启动 1.0 集成网关，
通过当前 OpenAI-compatible relay 使用真实 `gemini-3.7-flash`，验证普通讨论、
决策卡选择和人物卡候选的端到端边界。没有使用正式作品数据，也没有修改 08、10
或生产交接对象。

## 真实调用证据

- 健康接口：`can_call_model=true`、`is_simulation=false`、`gemini-3.7-flash (openai)`、`model-config-6`。
- 首轮讨论：`agent-42574e4b6c59`，完成；`input_tokens=4707`、`output_tokens=298`；返回两项 `decision_card`。
- 选项提交：`agent-c25143610c60`，完成；`input_tokens=4787`、`output_tokens=391`；提交内容携带 `decision_response`。
- 人物卡候选：`agent-cde7f0b14da4`，停在 `waiting_user`；`input_tokens=13320`、`output_tokens=944`；执行了 `draft_character_card`，未建立正式 Proposal。
- 三轮合计：`22814` 输入 token、`1633` 输出 token。Provider 没有返回费用，记录为未知；cache 观测为 `0`，未将其解释为命中或未命中。

## 边界验收

- 选项提交持久化了原助手消息 ID、选项 ID 和用户可见标签。
- 隔离作品 `work-3237876a62ed` 的 Proposal、Artifact、Revision 均为 `0`。
- 人物卡候选只出现在助手的候选预览中，运行状态为 `waiting_user`，`proposal_id=null`。
- 真实服务在测试结束后已停止，临时端口 `8916` 已关闭。

## 回归

- `services/halocue/writing`: `581 passed in 332.20s`。
- `services/halocue/production`: `86 passed in 19.99s`。
- `services/halocue/integrated`: `9 passed in 8.52s`。
- `node --check`: `web/app.js`、`web/writing-workbench.js`、`web/production-embed.js`、`web/shell.js` 通过。
- `python -m compileall -q src tests` 通过。
- `git diff --check` 退出码为 0；仅有 Git 的 LF/CRLF 提示。

## 已知限制

本次真实调用验证了 Provider 协议和 Proposal 边界，不代表真实费用 receipt、cache 命中策略、
远端 429/504 恢复或 AA 客户端安装已经完成。WritingPack 必须通过
`HALOCUE_BA_WRITING_SKILL_DIR` 指向完整的只读来源；未配置时服务会安全拒绝真实模型调用。
