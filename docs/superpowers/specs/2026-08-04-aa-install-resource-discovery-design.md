# 从 AA 安装位置自动发现工作区与资源包设计

日期：2026-08-04

## 目标

让用户只需要选择 `AzureArchive.exe` 或它所在的 AA 安装目录，程序即可自动定位并验证：

1. AA 当前使用的数据工作区。
2. `projects`、`saves`、`overrides` 和 `settings`。
3. `.aap` 项目、`.aas` 存档及 AA 最近打开过的外部项目文件。
4. 用户已经安装的 AA 官方资源包缓存。
5. 为背景和角色预览生成的本地索引与缩略图缓存。

本功能不得要求其他用户预先导出 AA 资源，也不得把当前开发机器提取出的资源随程序分发。

## 现状

当前 `aapaths.py` 已能从显式 `data` 路径、`aa_config.json`、`AA_DATA` 和 LocalLow 配置中发现 AA 数据目录，并根据 `workspacePath`、`cachePath` 返回工作区子目录与资源缓存。

当前设置界面只接受包含 `projects` 的 AA `data` 目录，不能接受 `AzureArchive.exe` 或 AA 安装根目录。缺失的是“从 AA 程序定位 Unity 身份，再读取 AA 自己的配置”的前半段。

已在实际安装上验证以下发现链：

```text
E:\AzureArchive\App\AzureArchive.exe
  -> AzureArchive_Data\app.info
  -> foxxlight / AzureArchive
  -> %USERPROFILE%\AppData\LocalLow\foxxlight\AzureArchive
  -> data\settings\user_settings.json
  -> workspacePath = E:\AzureArchive\存储文件
  -> cachePath = E:\AzureArchive\资源文件
```

## 方案比较与选择

### 方案 A：只扫描 EXE 周围目录

从安装目录递归寻找 `data`、`projects` 和资源包。实现直观，但 AA 允许把工作区和缓存移动到其他磁盘；目录名称也可能被用户修改。该方案会漏掉合法安装，并可能误认无关的大型目录。

### 方案 B：写死 AzureArchive 的 LocalLow 路径

直接读取 `%USERPROFILE%\AppData\LocalLow\foxxlight\AzureArchive`。这能覆盖当前版本，但没有验证用户选择的程序是否真是 AA，也把厂商名和产品名永久写死，不利于兼容安装结构变化。

### 方案 C：EXE 身份验证与 AA 配置联合发现

先从 EXE 对应的 Unity `app.info` 读取厂商名和产品名，再定位 LocalLow，并以 `user_settings.json` 中的 `workspacePath`、`cachePath` 为路径真源。只有配置缺失或字段为空时，才使用有限且可验证的回退候选。

本轮选择方案 C。EXE 是发现入口，AA 自己的配置是权威路径来源。

## 输入规范化

设置入口统一接受以下输入：

- `AzureArchive.exe` 文件。
- 直接包含 `AzureArchive.exe` 的目录。
- 包含 `App\AzureArchive.exe` 的 AA 安装根目录。
- 为兼容旧设置，仍接受 `data` 目录或其工作区父目录。

目录查找只检查明确的有限位置，不做整盘或无界递归扫描。找到 EXE 后必须同时验证：

- 文件名为 `AzureArchive.exe`，不区分大小写。
- 同级存在 `AzureArchive_Data`。
- `AzureArchive_Data\app.info` 可读取，并至少包含厂商名和产品名。

验证失败时不根据相似文件名继续猜测，而是保留用户输入并显示具体缺失项。

## 自动发现流程

### 1. 识别 AA 程序

将选中的文件或目录规范化为 EXE 绝对路径和安装根目录。读取 `app.info` 得到 Unity 厂商名与产品名；当前预期值为 `foxxlight` 和 `AzureArchive`。

### 2. 定位 LocalLow 配置

根据当前 Windows 用户定位：

```text
%USERPROFILE%\AppData\LocalLow\<vendor>\<product>
```

优先读取其 `data\settings\user_settings.json`。该 `data` 可能是普通目录，也可能是 AA 建立的重定向目录或目录联接，读取方必须支持两者。

### 3. 解析数据工作区

用户本次直接选择的 `data` 或工作区目录一旦验证通过，就作为本次显式选择采用，不再被旧配置覆盖。用户选择 EXE 或安装目录时，数据目录候选按以下顺序处理：

1. `user_settings.workspacePath\data`。
2. LocalLow 下的默认 `data`。
3. 兼容旧设置的 `aa_config.json.aa_data`。

候选必须至少包含 `projects`。`saves`、`overrides`、`settings` 分别记录存在状态；缺少非关键目录时显示不完整状态，不擅自创建目录。

### 4. 解析资源包缓存

资源缓存候选按以下顺序处理：

1. 非空的 `user_settings.cachePath`。
2. 工作区同级的 `资源文件`。
3. `data\BundleCache` 等已知候选，但只有通过资源缓存特征验证后才能采用。

资源缓存验证分为快速验证和建索引两个阶段：

- 快速验证只确认目录存在、包含 AA 缓存结构，并抽样检查 `__data` 的 UnityFS 文件头，避免设置页扫描数 GB 数据。
- 建索引阶段异步遍历资源，生成本机素材索引和缩略图；索引结果写入本程序缓存，不写入或修改 AA 资源目录。

“已安装资源包”和“已经生成预览索引”是两个独立状态。没有缩略图不能被表述为没有安装资源。

### 5. 定位项目与剧本文件

发现结果明确区分以下来源：

- `.aap`：默认来自 `data\projects`。
- `.aas`：默认来自 `data\saves`。
- 项目自定义素材：来自 `data\projects\<项目名>` 及对应存档目录。
- AA 最近打开的外部 `.aap/.aas`：从 `user_settings.visitedFiles` 补充，逐项验证存在性和扩展名。
- 原始 TXT/Markdown：不假定由 AA 管理，继续由本程序的剧情工作区索引记录源文件路径、大小和修改时间。

`visitedFiles` 只用于补充可见历史，不覆盖 `projects`、`saves` 的规范目录，也不把不存在的旧记录显示为可用文件。

## 发现结果模型

路径发现模块返回结构化结果，而不是让各调用方自行拼接路径。结果至少包含：

- `executable`：验证后的 AA EXE。
- `install_root`：AA 安装根目录。
- `vendor`、`product`：来自 `app.info` 的 Unity 身份。
- `local_low_root`：本次使用的 AA LocalLow 根目录。
- `data`、`projects`、`saves`、`overrides`、`settings`。
- `resource_cache`：验证后的资源包缓存目录。
- `recent_project_files`：仍然存在的外部 `.aap/.aas`。
- 每个路径的 `source`、`exists`、`valid` 和错误原因。
- 总体状态与资源索引状态。

路径优先级和验证集中在一个模块中。启动器、Web 设置接口、项目安装器、历史素材浏览器和资源索引器只消费该结果，不重复实现发现规则。

## 配置持久化与刷新

`aa_config.json` 同时保存：

- 用户选择的 `aa_executable` 或安装入口。
- 已解析的 `aa_data`。
- 已验证的 `aa_cache`。
- 最近一次发现来源和必要的索引版本信息。

程序每次启动都快速重新验证已保存路径，并重新读取 AA 的 `user_settings.json`。如果用户在 AA 中移动了工作区或资源缓存，程序自动更新解析结果，不静默沿用失效旧路径。只有自动发现失败时才回退到上次仍然有效的显式路径，并在设置页说明来源。

## 多安装处理

同一 Windows 用户下的多个 AA EXE 可能具有相同的 `app.info` 身份，因此会共享同一个 LocalLow 配置。选中的 EXE 负责证明程序身份；LocalLow 中当前启用的 `workspacePath` 和 `cachePath` 仍代表 AA 当前实际使用的位置。

如果发现多个不同且有效的数据工作区，程序不得根据目录新旧自行切换。设置页显示候选来源，让用户明确选择，并保存该选择。不存在冲突时不增加额外确认步骤。

## 设置界面

现有“AA 数据目录”改为“AA 安装与资源”，主要操作为“选择 AA 程序或安装目录”。仍保留高级手动选择 `data` 的入口，用于配置损坏或非标准安装。

发现完成后显示以下摘要：

- AA 程序：已识别或未识别。
- 项目位置：`.aap` 所在的 `projects`。
- 存档位置：`.aas` 所在的 `saves`。
- 资源包：已安装、未安装或路径不可用。
- 素材预览：可用、尚未建立或正在建立索引。

状态文案不得把“预览尚未生成”写成“素材不存在”，也不得把配置不完整统一写成“AA 错误”。设置页可以显示规范化路径供本机用户核对，但普通业务接口不返回哈希缓存内部的任意文件路径。

## 资源索引边界

- 只读取用户本机已经安装的 AA 资源。
- 不随本程序分发解包出的背景、角色、表格或 AssetBundle。
- 不修改 AA 的缓存、配置和原始 AssetBundle。
- 缩略图、解析表和检索特征写入本程序自己的缓存目录。
- 本地索引与资源目录及资源结构版本绑定；路径或版本变化后增量刷新或重建。
- 官方资源中没有合适背景时，继续提供自定义背景导入和生成提示词，不把低置信度素材强制当成正确答案。

## 错误处理

- EXE 无对应 `_Data` 或 `app.info`：说明所选位置不是完整 AA 安装，允许重新选择。
- `user_settings.json` 不存在：回退默认 LocalLow `data` 和已保存的显式路径。
- JSON 损坏或字段类型错误：忽略损坏字段，显示配置无法读取，不让程序崩溃。
- `workspacePath` 已失效：列出失效来源，允许手动选择 `data`。
- 工作区有效但资源包缺失：项目生成能力与素材预览能力分别报告，不阻止用户使用自定义素材。
- 资源包有效但索引缺失：标记为“资源包已安装，正在/等待建立预览”，不得标记为错误。
- `visitedFiles` 含旧路径：跳过不存在或扩展名不受支持的条目。
- 资源扫描中单个 Bundle 损坏：记录并跳过该文件，索引任务报告部分成功及损坏数量。

## 测试设计

### 路径发现单元测试

使用临时目录构造以下安装布局：

1. 直接选择 EXE。
2. 选择直接包含 EXE 的目录。
3. 选择包含 `App\AzureArchive.exe` 的安装根目录。
4. `workspacePath` 指向其他磁盘结构。
5. LocalLow `data` 为目录联接或等价重定向。
6. 显式 `cachePath`、空 `cachePath` 和同级 `资源文件`。
7. 缺失或损坏的 `app.info`、`user_settings.json`。
8. 多个有效候选造成冲突。
9. `visitedFiles` 中混合有效、失效和错误扩展名条目。
10. 旧配置只包含 `aa_data`。

### 资源验证测试

- 资源目录抽样包含合法 UnityFS `__data` 时识别为已安装。
- 普通目录、空目录和伪造文件不被识别为 AA 资源包。
- 快速验证不遍历和读取所有大型 Bundle 内容。
- 索引写入本程序缓存，AA 源目录保持字节和时间戳不变。
- 未建索引与未安装资源返回不同状态。

### 接口与界面测试

- 设置接口接受 EXE、安装目录、工作区和 `data` 四类输入。
- 设置页正确显示项目、存档、资源包和预览索引状态。
- 自动发现失败时给出具体原因和手动入口。
- 启动后 AA 配置发生变化时能刷新解析结果。
- 普通素材接口不泄露任意本机缓存文件路径。
- 桌面和窄屏布局无文字重叠或横向溢出。

### 实机只读验证

在实际 AA 安装上执行只读集成测试，验证 EXE、LocalLow、工作区、资源包和项目目录的完整链路。测试不得改写 `E:\AzureArchive`、LocalLow 配置或现有 `.aap/.aas`。

## 验收标准

1. 新用户只选择 `AzureArchive.exe` 或 AA 安装根目录即可完成路径配置。
2. 工作区和资源包不在 EXE 所在磁盘时仍能正确发现。
3. 程序能明确定位 `.aap`、`.aas`、项目素材和仍存在的外部历史文件。
4. 资源包已安装但未生成预览时，界面显示正确的等待状态。
5. 其他用户无需获得当前开发机器导出的资源即可使用自己的 AA 资源包。
6. 多安装或配置冲突时由用户选择，不静默猜测。
7. 所有自动化测试通过，实际 AA 目录在验证前后保持不变。
