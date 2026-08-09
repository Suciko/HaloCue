# Private Spine overlay

公开版不包含 Spine。个人骨骼、个人素材和作品在任何版本都不得包含。
MIT 许可证只适用于 HaloCue 原创代码，不适用于 Spine 或用户文件。

HaloCue's private package builder is local-only and refuses to run without a
positive redistribution attestation containing an authorization basis, Spine
version, and an exact relative-path/SHA-256/classification allowlist.

Spine Editor is proprietary software and is not covered by HaloCue's MIT
License. The standard Spine Editor license prohibits making the editor available
to third parties without written permission. A private transfer is still a
distribution. Do not use this builder unless the distributor has specific legal
authorization covering the intended recipients.

Official terms: <https://esotericsoftware.com/spine-editor-license>

中文结论：只有取得覆盖预定接收人的明确书面授权，才可以考虑制作私发覆盖包；
“不公开上传”本身不构成再分发许可。

The builder never accepts skeletons, atlases, projects, audio, game assets,
activation data, credentials, logs, recent-file state, unlisted files, links, or
hash mismatches. Vendor runtime images require the explicit
`vendor_runtime_resource` classification. The attestation itself is not embedded
in the resulting archive and no upload or publication command is provided.
