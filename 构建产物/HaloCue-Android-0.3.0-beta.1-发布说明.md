# HaloCue Android 0.3.0-beta.1

这是第一版可分发测试版，适用于 Android 7.0 及以上的 64 位 ARM 设备。

## 已包含

- PC 窄屏工作流、剧情读取、AI 初审、人工审查、草稿和历史记录。
- PC 官方资源索引与额外资源包 identifier 映射。
- 自定义人物、背景和音效的 Android 系统文件/目录选择器导入。
- 官方表情 ID/语义读取，以及自定义人物表情的手工编辑与文本模型建议。
- `.aap` 编译、发布到 `Download/HaloCue/` 和系统分享。
- Android Keystore 密钥保存、旋转状态保持和系统安全区适配。

## 已知限制

- 不自动写入原版 AA 的受限目录。生成后由用户在原版 AA 中手动导入。
- 暂不提供 Spine 实时渲染或动态表情预览。
- 当前 APK 只包含 `arm64-v8a`，不支持 32 位或 x86 Android 设备。
- 早期 `0.3.0-dev` 调试包使用不同签名，不能直接覆盖安装本测试版。卸载调试包会清除其应用内数据，请先导出需要保留的文件。

## 文件校验

- APK：`HaloCue-Android-0.3.0-beta.1-arm64-v8a.apk`
- 大小：57,229,553 字节
- SHA-256：`77405A3F279C34131E88FD9FA9CAECD4F7E90CB2811329018A127CCB44861891`
- 签名证书 SHA-256：`BF0A5C4DD4114B0AB48FC79D0B41C56CA49A324F3FE27C019BA80B5FFC7ACB09`
