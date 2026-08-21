# 0.9.4.5 基础文件索引问题交接

本源码包对应 Git 提交 `2a6e532`（`release: publish 0.9.4.5 desktop build`）。

## 现象

有用户反馈 Windows PC 版 0.9.45 无法建立 AA 基础文件的资源索引。当前需要先确认失败发生在路径探测、文件扫描，还是索引文件写入阶段。

## 复现入口

在仓库根目录执行：

```powershell
python -X utf8 build_index.py --data "<AzureArchive data 目录>" --out out/aa_resources.json
```

`<AzureArchive data 目录>` 应直接包含 `projects`、`saves`、`overrides` 等目录。若不传 `--data`，程序会通过 `aapaths.py` 读取 `aa_config.json`、`AA_DATA` 和 AA 的 `user_settings.json` 自动探测。

建议同时记录：

```powershell
python -X utf8 aapaths.py
python -X utf8 launcher.py --check
python -m pytest tests/test_build_index_observations.py tests/test_aa_install_discovery.py
```

## 重点代码

- `build_index.py`: 基础资源索引构建入口，扫描背景、角色、音效和 `.aap` 观测结果。
- `aapaths.py`: AA data 目录及资源缓存的跨机器探测。
- `aa_install_discovery.py`: `workspacePath`、安装目录和 Addressables catalog 的解析。
- `official_catalog.py`: 原生角色表的可选导入。

## 反馈信息

修复前请保留完整的命令行输出、Python 版本、Windows 版本，以及脱敏后的 data 目录结构（只要目录名和文件扩展名即可，不要上传游戏资源）。
