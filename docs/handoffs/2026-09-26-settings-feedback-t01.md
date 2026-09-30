# T01 设置反馈修复与独立验收

- kind: handoff
- scope: HaloCue 1.0 / T01
- status: completed for this bounded slice
- observed_at: 2026-09-26
- source: 用户授权一个 GPT-6 Sol 子 Agent；[重构计划](../1.0-authoring-rework-plan-2026-09-26.md) 第 11 节 T01；当前工作树和内部浏览器检查
- 实施：同一个 Sol 子 Agent；代码审阅、补充问题复现、浏览器验收：主代理。
- 未提交或推送。保留工作树既有修改；本报告不表示整体重构完成。

## 改动

业务文件限于 `services/halocue/writing/web/app.js`、`web/index.html`、`web/settings-center.css`，测试为 `services/halocue/writing/tests/settings_controller_cases.cjs`。

- 空模型在字段旁报错并聚焦输入，不发模型请求。
- 获取模型/测试失败在设置内部现有诊断卡展示，保留输入、原因、脱敏详情和重试入口，不随全局 toast 超时消失。
- 修改配置标记旧结果；已有请求快照检查继续拒绝过期响应。
- 异步结果完成时聚焦诊断卡，只调整设置内容滚动，留出底部固定工具栏空间。关闭设置或切页时不抢焦点。
- 测试成功分项识别后端真实 `passed` 状态；重试进入明确 pending 状态；模型列表失败使用对应标题。

## 主代理验收发现并退回的问题

1. 第一版模拟通过，但真实本机 fixture 返回 `passed` 时，成功标题下面三个分项显示“需要检查”。已修正并新增真实响应形状回归。
2. 1920×1080 下固定测试按钮可见，但结果落到可视区域外。已修正结果定位并新增回归。不能仅凭诊断卡存在于 DOM 判为可见。

## 验证证据

- 主代理独立运行设置控制器所有命名用例：29/29 通过；`node --check services/halocue/writing/web/app.js` 通过。
- `python -X utf8 -m pytest services/halocue/writing/tests/test_settings_hub.py services/halocue/writing/tests/test_ui_density_contract.py -q`：21 passed。
- 主代理检查范围内 `git diff --check` 通过；Git 提示现有 Windows LF/CRLF 转换。
- 浏览器使用既有 `in_app_browser_model_picker_fixture_server.py`，经 reviewer_environment 清理继承环境，临时数据、本机模拟 provider；未调用真实模型、未保存用户实例配置。
- AC01：空模型字段内提示，焦点为 settingsModelName；零请求由控制器测试验证。
- AC02：本机错误端点获取列表失败，超过 toast 时限仍保留错误与输入，可键盘展开详情。
- AC03/04/05：错误分类、脱敏、双用途部分失败、过期请求由控制器模拟覆盖。实际页面另验证配置变化标记上次结果，重载未写入未保存配置。
- AC06/07：主代理亲验 1366×768 错误结果 bottom=660.97，工具栏 top=672.67；1920×1080 成功结果 bottom=906.70，工具栏 top=918.67，均留约 12px。成功网络/鉴权/响应分项均为正常；Tab 可从详情到重试；关闭后焦点返回 openSettingsButton。

## 边界

这是错误反馈呈现和状态修复。真实服务商的测试/启用失败原因、token 能力、协议适配、大纲/资料/整章重构尚未实施。模拟环境没有制作服务，制作状态不可读为夹具边界，不计真实双用途接入通过。没有进行全仓回归或重新打包 EXE。
