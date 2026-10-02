# 2026-09-18 生产流程来源与审查补验

## 范围
- 内嵌 AA 制作工作台第一步与第四步。
- 真实任务：`run-a01e93593a5a`，19 行、1 个场景、草稿 v4、21 张待审卡。
- 只读检查与 UI 修复；未审批、编译、安装、创建任务或调用模型。

## 改动
- 当前任务第一步显示真实来源、审查草稿版本、构建状态，并保留冻结剧本和场景边界。
- 当前任务与新建制作使用显式切换，避免查看来源时误进入可编辑新建表单。
- 审查页增加优先级摘要，并按阻断诊断、素材请求、普通待审、已审排序。
- 修复 390px 深色模式流程步骤 hover 白底和分隔线颜色。

## 验证
- `python -X utf8 -m pytest -q services/halocue/production/tests/test_embedded_workbench_ui.py services/halocue/production/tests/test_ui_information_architecture.py services/halocue/production/tests/test_workspace_polish_layout.py`
- 结果：58 passed。
- 真实内嵌浏览器验证桌面深色与 390×844 移动端；来源页和审查页均无横向溢出。
- 截图位于 `output/2026-09-18-iab-inspection/screenshots/12-*.png` 至 `18-*.png`。

## 边界
- 当前任务来源数据为“直接导入剧本”，不是写作定稿；UI 按真实数据展示。
- 角色动态立绘与表情资源渲染仍需单独核对。
- 本轮不是完整 1.0 真实链路验收。
