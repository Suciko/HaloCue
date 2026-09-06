# HaloCue 发布清单

本文件供维护者使用。核心原则是：**公开代码和必要知识，不公开素材、作品、秘密或机器状态。**

## 两种发布物

| 发布物 | 固定名称 | 可否上传 GitHub |
|---|---|---|
| 公开源码 | GitHub 仓库 | 可以，先通过公开导出和扫描 |
| 公开 Windows ZIP | `HaloCue-1.0.0-windows-x64.zip` | 可以，作为 GitHub Release 附件 |
| 私发包 | `HaloCue-1.0.0-private-windows-x64.zip` | 不公开；仅在授权明确时定向交付 |

公开版不包含 Spine。私发覆盖包也绝不能包含个人骨骼、图集、纹理、音频、游戏资源、作品、密钥、激活信息、个人配置或日志；这些内容在任何版本都不得包含。

## 许可边界

MIT 许可证只适用于 HaloCue 原创代码。第三方依赖保留自己的许可证，详见
`THIRD_PARTY_NOTICES.md`。

Spine Editor 是专有软件。即使只发给少数人，仍属于向第三方提供软件。没有覆盖具体接收人的明确书面授权，不得生成或发送私发覆盖包。官方条款：
<https://esotericsoftware.com/spine-editor-license>。

## 公开源码导出

公开源码只能从 Git 暂存区索引导出，不能直接复制当前工作目录。这样未提交的个人文件不会混入候选版本。

```powershell
python tools/export_public_source.py --source . --output build/public-source/HaloCue
python tools/scan_release.py build/public-source/HaloCue --mode source
python tools/verify_clean_source.py --source build/public-source/HaloCue
```

导出清单必须排除：

- `.superpowers/`、`docs/superpowers/` 和内部测试报告；
- 本机路径、配置、密钥、缓存、草稿和输出；
- 未脱敏数据库、资源索引和演员表；
- 骨骼、图集、图片、音频、AssetBundle 和创作原稿。

唯一允许公开的数据库是经过确定性脱敏构建的 `data/halocue_labels.db`。不要手工取消 `.gitignore` 来上传原始 `aa_assets.db`。

## Windows ZIP

从已经扫描通过的公开源码候选构建，完成后核对：

- ZIP 名称、SHA-256 旁车文件和清单一致；
- ZIP 只有一个 `HaloCue/` 顶层目录；
- `HaloCue.exe`、网页资源、图标、许可证和脱敏数据库齐全；
- 不含 Spine、个人骨骼、游戏资源或机器路径；
- 在干净中文/空格路径中完成两次启动、导入、审查、编译和退出验证；
- Windows ZIP 不需要安装 Python。

## 私发覆盖包

私发构建器只接受逐文件相对路径、SHA-256、分类和授权依据组成的白名单。授权声明不得伪造；未取得书面授权时，保持此发布物为空缺。参见 `docs/private-release.md`。

## GitHub 发布前最后确认

- [ ] 分支上的公开源码测试和扫描通过。
- [ ] `LICENSE` 为 `Copyright (c) 2026 Suciko` 的标准 MIT 文本。
- [ ] 第三方清单与最终 Windows 包实际内容一致。
- [ ] `git status` 中没有意外文件。
- [ ] Release 附件的 SHA-256 已重新计算并核对。
- [ ] 仓库与 Release 里都没有私人素材或 Spine。
- [ ] 发布说明明确这是 `1.0.0` 稳定版或对应 beta 版本。

远程仓库目标是 `https://github.com/Suciko/HaloCue`。创建仓库、推送分支和发布 Release 都属于外部写入；执行前需由仓库所有者最终确认。
