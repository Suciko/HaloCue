# HaloCue Android Local AAP Compiler Plan

**Goal:** 在不访问原版 AA 私有目录的前提下，让安卓 APK 使用现有 `script2aap` 编译核心，在 HaloCue 自身目录内完成“剧本文本 → `.aap` + 工程附属文件”的最小闭环。

**Scope:** 本阶段只支持内置资源与官方角色映射，不迁移 Windows 安装逻辑、自定义 Spine 导入、配音目录和自动复制到 AA。

## Task 1：建立可追溯的编译核心快照

- [x] 先写失败测试，定义 `android_compiler.compile_text(...)` 的返回契约和文件输出。
- [x] 从电脑端同步最小纯 Python 依赖集与 `cast.json`、`aa_resources.json`，记录来源和同步方式。
- [x] 给安卓适配层提供可写工作目录，不修改桌面端编译器的默认行为。
- [x] 在 Windows 主机上用实际编译器生成并解析一份最小 `.aap`。

## Task 2：在 Chaquopy 真机运行编译器

- [x] 先写失败的 Android 仪器测试，要求真机生成 `.aap` 并返回绝对路径。
- [x] 由 Kotlin 把应用 files 目录交给 Python，调用 `android_compiler.compile_text(...)`。
- [x] 验证生成文件位于 `com.halocue.android` 自身目录，JSON 可解析且至少包含一个台词节点。
- [x] 保持不申请存储权限、不写 AA 项目目录。

## Task 3：接到安卓页面的最小生成入口

- [x] 先写页面/仪器失败测试，定义输入框、工程名、生成按钮和结果状态。
- [x] 页面只在用户点击后调用原生桥；编译在后台线程运行，完成后回传结果。
- [x] 显示生成路径和明确状态“已生成，尚未导入 AA”。
- [x] 真机生成一次示例工程并保存截图证据。

## 完成标准

- 主机 Python 测试通过。
- vivo X100s Pro / Android 16 仪器测试通过。
- APK 内可离线生成结构有效的 `.aap`。
- 生成物只位于 HaloCue 自身目录；界面不误报已导入原版 AA。
- 接手记忆记录同步来源、限制和下一步导出方案。
