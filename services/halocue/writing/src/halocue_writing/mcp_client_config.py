"""Client-native setup artifacts for the existing local MCP bridge."""

import json

from .errors import DomainError


def client_profile(config, client):
    server = config["mcpServers"]["halocue"]
    if client == "codex":
        # JSON basic strings/arrays are also TOML basic strings/arrays. Keeping
        # Unicode literal avoids JSON surrogate escapes unsupported by TOML.
        def literal(value):
            return json.dumps(value, ensure_ascii=False)

        lines = [
            "[mcp_servers.halocue]",
            "command = " + literal(server["command"]),
            "args = " + literal(server["args"]),
            "",
            "[mcp_servers.halocue.env]",
            *(key + " = " + literal(value) for key, value in server["env"].items()),
        ]
        return {
            "client": client,
            "filename": "HaloCue-Codex.toml",
            "content_type": "application/toml",
            "text": "\n".join(lines) + "\n",
            "instructions": "将这段合并到用户目录 .codex/config.toml（已有 halocue 时替换该节），保留其他配置。Codex 桌面、CLI 和 IDE 共用本机配置；重新打开 Agent 会话后生效。CLI 可用 codex mcp get halocue 检查。",
        }
    if client in {"claude-code", "generic"}:
        return {
            "client": client,
            "filename": "HaloCue-Claude-Code.json"
            if client == "claude-code"
            else "HaloCue-MCP.json",
            "content_type": "application/json",
            "text": json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            "instructions": (
                "将 mcpServers.halocue 合并到你的项目 .mcp.json，保留其他服务。重新打开 Claude Code 会话并批准该项目的连接；用 /mcp 检查。也可保存此文件后使用 claude --mcp-config <文件路径>；这是当前会话配置。"
                if client == "claude-code"
                else "在支持 stdio MCP 的 Agent 软件中添加此配置，然后重新打开会话。"
            ),
        }
    raise DomainError("mcp_client_invalid", "请选择 Codex、Claude Code 或通用 MCP。")
