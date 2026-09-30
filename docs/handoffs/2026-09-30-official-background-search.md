# 官方背景预览、搜索与时间线验收

## 范围与状态

维护者要求继续修复当前 AA 制作中的背景来源、搜索速度、整页异常边框，并必须在 Codex 内部浏览器实际操作、查看截图。
当前本地 2969 服务运行的是本仓库，不是独立的 HaloCue-1.1 仓库。本次保持已有未提交修改，不修改其他仓库或用户 AA 工程。

本次修改已应用到 2969；未提交、未合并。没有调用收费模型。

## 根因和实现

- 预览解析之前没有完整读取绑定工作区的官方缓存；历史项目扫描又误把私人剧情图片加入全局背景库。
- `background_library.py` 统一来源范围：官方 metadata、AA 官方缓存 manifest 和工作区共享 `BgOverrides` 资源包注册。拒绝显式私人来源和越界路径；不扫描 projects/saves。已冻结旧任务仍可解析其精确登记素材。
- `resource_previews.py` 回退到绑定 AA 官方缓存，保留合法资源包覆盖优先级。预览可用性批量检查复用同一代文件签名；缓存仍检查实际文件是否存在；并发请求只解析一次 manifest。
- `legacy_adapter.py` 缓存背景搜索元数据，文件代变化时失效，先匹配再读取预览，分页不携带内部搜索字段。新任务冻结时排除私人历史背景。
- `background_search.py` 支持中文多关键词、常用同义词及英文 BA 地点键的中文检索。不索引 `avoid_when`：实际浏览器发现“不适合深夜”使白天车站误匹配夜景，已修正并增加回归。
- 搜索输入防抖 180ms，Enter 立即检索，支持中文输入法合成事件，取消旧请求、防止旧结果覆盖；保留滚动分页。
- AA 工作面外框是程序化聚焦 section 引发的默认 outline。仅移除该容器轮廓，保留控件键盘焦点。
- 实际采用发现时间线“更换”错误使用普通 PATCH，后端正确拒绝资源指令。按钮和历史素材更换现使用专用 `background-resolution` POST，传入实际点击的卡片，避免误改当前选中卡。

## 检查命令

```text
E:\Miniconda3\python.exe -m pytest services/halocue/production/tests/test_background_search.py services/halocue/production/tests/test_official_background_scope.py services/halocue/production/tests/test_preview_resource_root.py services/halocue/production/tests/test_background_import.py services/halocue/production/tests/test_full_background_library.py services/halocue/production/tests/test_background_names.py -q
```

结果：34 passed。覆盖来源排除、额外资源包保留、路径校验、冻结预览、缓存失效、并发解析、搜索别名和负面说明误匹配。

```text
E:\Miniconda3\python.exe -m pytest services/halocue/production/tests/test_scene_background_picker_ui.py -q
```

结果：8 passed。新增时间线采用测试确认专用 POST、目标卡片和版本参数；包含布局与滚动分页测试。首次新增用例缺少生成完成 fixture，审查阶段被禁用；修正为 completed=True 后通过。

针对新增搜索/范围模块及测试的 ruff check：All checks passed。没有跑全套测试，不宣称可合并。

## 真实服务与内部浏览器证据

最终服务重启后的顺序测量（资源库 2366 项，毫秒是本地接口响应，不含输入防抖、图片解码）：

| 查询 | 响应时间 | 结果数 |
| --- | ---: | ---: |
| 首次完整库 | 2002 ms | 2366 |
| 车站 夜晚 | 36 ms | 15 |
| 阿拜多斯 教室 | 44 ms | 11 |
| 教室 | 41 ms | 105 |
| 缓存后完整库 | 118 ms | 2366 |
| 已知私人 key 00000-1392481605 | 33 ms | 0 |

首次仍需解析索引和官方 manifest，约 2 秒；不能描述为所有首次请求瞬时返回。

使用 Codex 内部浏览器 tab 9 操作真实 2969 服务：

- 昼夜主题各截取入口整页，异常外框消失；恢复原来的暗色主题，无缩放/viewport 更改。
- “车站 夜晚”和“阿拜多斯 教室”实际组合查询与接口结果一致。截图看到真实夜景原图，筛选栏高度正常。
- 全库初始 80/2366，向下滚动自动增加到 160/2366，新增缩略图正常显示。
- 既有代理验收任务 run-92bd5802c175 的三张示意背景通过 UI 替换为 `bg_abydoscouncilroom3_sunset`、`bg_railway_night`、`bg_schoolrooftop_night`。时间线及剧情预览显示真实 AA 图像；不写入原始 AA 工程。
- 浏览器捕获的 error 日志为空。

截图仅保存维护者本地，不纳入仓库、不作为其他协作者运行前提：
`C:/Users/Sakura/.codex/visualizations/2026/09/30/halocue-background-scope/`
包括 `light-layout.jpg`、`dark-layout.jpg`、`official-resource-pack.jpg`、`chinese-background-search.jpg`、`background-pagination.jpg`、`real-background-timeline.jpg`。

## 限制与下一步

- 这轮验收针对背景问题，不代表此前广泛 API/成本/写作问题全部解决。
- 旧代理短片仍有 5 行不符合 AA 编译语法的叙述，尚未转换，未编译/安装。资源索引完整性提示仍存在，需独立诊断。
- 当前时间线名称仍显示逻辑 key；后续应复用正式中文素材 metadata，技术标识收进详情。
- 共享资源包按绑定工作区注册表判断；不会仅凭文件名推断“官方”，也不会扫描历史剧情里的私人图片。
- 2969 服务保留运行。已停止本轮自己的临时 3527 QA helper。实际用户设置、密钥和其他用户工程保持现有内容。
