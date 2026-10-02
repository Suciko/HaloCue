# HaloCue 1.0 随包创作参考资料

维护者于 2026-10-02 明确要求随源码与发行包提供必要人物卡和 AA 制作数据集。

- `characters/`：102 份完整人物 JSON，来自维护者既有人物参考库。包含同一角色的不同形态，文件数不等于独立角色数。
- `official-staging/records/`：3 个无损 gzip JSONL 分片，共 368,032 条官方剧情演出记录。保留原始脚本、演出事件、台词、资源映射与来源。
- `official-staging/indexes/`：故事分组、指令频次与资源目录。
- `official-staging/derived/face_text_examples.json.gz`：表情与台词的演出参考示例。
- `official-staging/audit/`：提取报告及未知指令、未映射分组、未解决资源记录。原数据包含未解决项，不宣称完全映射。
- `manifest.json`：逐文件压缩前后字节数和 SHA-256，以及原始提取来源、版本与记录数。

人物卡是维护者整理的创作参考，不是游戏发行方发布的官方人物卡。BA 原作文本和角色的权利归原权利人；此目录不适用 HaloCue 代码的 MIT 授权。维护者的随包授权不改变原资料权属。

程序默认读取此包，无须配置本机维护者目录。资料页检索人物后，可查看验证结果并明确导入完整人物卡到当前作品。原作摘录可检索、核对后导入。资料不会自动改写作品事实；模型按本场角色和引用投影，不注入整库。`HALOCUE_BA_CORPUS_DIR` 仍可指定独立的只读原作库。

gzip 是标准无损压缩；可用 Python `gzip.open(path, 'rt', encoding='utf-8')` 逐行读取 JSONL。包内不含 API 密钥、用户作品、游戏图片/音频/Spine 二进制或视频参考。
