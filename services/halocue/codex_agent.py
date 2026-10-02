"""Subscription-only Codex App Server boundary; never read or return OAuth tokens."""

from __future__ import annotations

import atexit
import json
import os
import platform
import queue
import shutil
import subprocess
import threading
import time
import weakref
from pathlib import Path

from services.halocue.runtime_layout import integrated_data_root


class CodexError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


def codex_home() -> Path:
    return Path(os.environ.get("HALOCUE_CODEX_HOME") or integrated_data_root() / "codex").resolve()


def subscription_only_enabled() -> bool:
    return (codex_home() / "subscription-only.enabled").is_file()


def enable_subscription_only():
    home = codex_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "subscription-only.enabled").touch(exist_ok=True)


def require_subscription_provider(provider: str):
    if subscription_only_enabled() and provider != "codex":
        raise CodexError(
            "subscription_only_required",
            "HaloCue 已启用仅订阅模式；此任务不能使用旧 API 配置，请选择 Codex。",
        )


def discover_cli(explicit: str = "") -> Path | None:
    """Resolve native binaries, including npm installations, without shell quoting."""
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if candidate.is_file() and (os.name != "nt" or candidate.suffix.lower() == ".exe"):
            return candidate
        raise CodexError("codex_cli_invalid", "请选择 Codex 原生程序；Windows 下需要 codex.exe。")
    direct = shutil.which("codex.exe" if os.name == "nt" else "codex")
    if direct:
        return Path(direct).resolve()
    if os.name == "nt":
        arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
        triple = "aarch64-pc-windows-msvc" if arch == "arm64" else "x86_64-pc-windows-msvc"
        roots = [Path(os.environ.get("APPDATA", "")) / "npm"]
        roots.extend(Path(part) for part in os.environ.get("PATH", "").split(os.pathsep) if part)
        for root in dict.fromkeys(roots):
            package = root / "node_modules" / "@openai" / "codex"
            for vendor in (
                package / "vendor",
                package / "node_modules" / "@openai" / f"codex-win32-{arch}" / "vendor",
                root / "node_modules" / "@openai" / f"codex-win32-{arch}" / "vendor",
            ):
                candidate = vendor / triple / "bin" / "codex.exe"
                if candidate.is_file():
                    return candidate.resolve()
    return None


def child_environment(home: Path) -> dict[str, str]:
    # Do not mutate the parent process or the user's normal Codex environment.
    env = {
        key: value
        for key, value in os.environ.items()
        if not (
            key.upper().endswith(("API_KEY", "AUTH_TOKEN", "ACCESS_TOKEN"))
            or key.upper().startswith(("OPENAI_", "ANTHROPIC_", "CODEX_", "HALOCUE_"))
        )
    }
    env["CODEX_HOME"] = str(home)
    return env


_CONFIG = {
    "forced_login_method": "chatgpt",
    "cli_auth_credentials_store": "file",
    "model_provider": "openai",
    "model_providers": {},
    "mcp_servers": {},
    "web_search": "disabled",
    "project_doc_max_bytes": 0,
    "features.shell_tool": False,
    "features.unified_exec": False,
    "features.apply_patch_freeform": False,
    "features.apps": False,
    "features.multi_agent": False,
    "features.hooks": False,
    "features.goals": False,
    "features.remote_plugin": False,
    "features.browser_use": False,
    "features.browser_use_external": False,
    "features.computer_use": False,
    "features.view_image": False,
    "features.image_generation": False,
    "features.shell_snapshot": False,
}

_CLIENTS: weakref.WeakSet = weakref.WeakSet()


def command(cli: Path) -> list[str]:
    args = [str(cli), "app-server", "--listen", "stdio://"]
    for key, value in _CONFIG.items():
        # JSON scalar syntax is valid TOML; empty tables use TOML's inline table.
        args.extend(["-c", f"{key}=" + ("{}" if isinstance(value, dict) else json.dumps(value))])
    return args


class AppServerClient:
    """One owned process/stdio connection. Requests and turns have bounded deadlines."""

    def __init__(self, cli: Path, home: Path, *, timeout: float = 30, cancelled=None):
        self.timeout = timeout
        self._inbox: queue.Queue = queue.Queue()
        self._pending: list[dict] = []
        self._write_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._serial = 0
        self._closed = False
        home.mkdir(parents=True, exist_ok=True)
        work = home / "workspace"
        work.mkdir(exist_ok=True)
        try:
            self.process = subprocess.Popen(
                command(cli),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=work,
                env=child_environment(home),
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            raise CodexError(
                "codex_start_failed", "无法启动 Codex，请检查安装和程序路径。"
            ) from error
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        _CLIENTS.add(self)
        try:
            self.request(
                "initialize",
                {
                    "clientInfo": {"name": "halocue", "title": "HaloCue", "version": "1.0"},
                    "capabilities": {"experimentalApi": True},
                },
                cancelled=cancelled,
            )
            self.send({"method": "initialized"})
        except Exception:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        self._inbox.put(value)
                except ValueError:
                    self._inbox.put({"_invalid": True})
        finally:
            self._inbox.put({"_eof": True})

    def _drain_stderr(self):
        # Drain so a full pipe cannot deadlock; raw diagnostics can contain secrets.
        for _ in self.process.stderr:
            pass

    def send(self, value: dict):
        with self._write_lock:
            if self._closed:
                raise CodexError("codex_disconnected", "Codex 连接已关闭，请重新连接。")
            try:
                self.process.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError) as error:
                raise CodexError("codex_disconnected", "Codex 连接中断，请重新连接。") from error

    def receive(self, deadline: float, cancelled=None) -> dict:
        while True:
            if cancelled and cancelled():
                raise CodexError("codex_cancelled", "已停止 Codex 任务。")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodexError("codex_timeout", "Codex 响应超时；任务已停止，没有转用 API。")
            try:
                value = self._inbox.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue
            if value.get("_eof") or self._closed:
                raise CodexError("codex_disconnected", "Codex 进程已结束，请重新连接。")
            if value.get("_invalid"):
                raise CodexError("codex_protocol_invalid", "Codex 返回了无效的协议消息。")
            return value

    def request(
        self, method: str, params: dict | None = None, *, deadline=None, cancelled=None
    ) -> dict:
        self._serial += 1
        request_id = self._serial
        self.send({"id": request_id, "method": method, "params": params or {}})
        limit = deadline or time.monotonic() + self.timeout
        while True:
            message = self.receive(limit, cancelled)
            if message.get("id") == request_id and "method" not in message:
                if "error" in message:
                    raise CodexError(
                        "codex_request_failed",
                        "Codex 拒绝了请求，请检查登录状态和 CLI 版本。",
                        details={
                            "method": method,
                            "rpc_code": (message["error"] or {}).get("code"),
                        },
                    )
                return message.get("result") or {}
            if "id" in message and "method" in message:
                self.reject(message)
            else:
                self._pending.append(message)

    def next_event(self, deadline: float, cancelled=None) -> dict:
        return self._pending.pop(0) if self._pending else self.receive(deadline, cancelled)

    def reject(self, request: dict):
        self.send(
            {
                "id": request["id"],
                "error": {
                    "code": -32601,
                    "message": "HaloCue only permits its registered proposal tools.",
                },
            }
        )

    def close(self):
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                if pipe:
                    pipe.close()


def check_account(client: AppServerClient, cancelled=None) -> dict:
    account = client.request("account/read", {"refreshToken": False}, cancelled=cancelled).get(
        "account"
    )
    if not account:
        raise CodexError("codex_login_required", "请先使用 ChatGPT 账号登录 Codex。")
    if account.get("type") != "chatgpt":
        raise CodexError(
            "codex_subscription_required",
            "此连接只接受 ChatGPT 登录，不能使用 API Key 或其他计费账号。",
        )
    return {"type": "chatgpt", "plan_type": account.get("planType")}


def check_limits(client: AppServerClient, cancelled=None) -> dict:
    receipt = client.request("account/rateLimits/read", cancelled=cancelled)
    limits = receipt.get("rateLimitsByLimitId") or {}
    if not limits and receipt.get("rateLimits"):
        limits = {"codex": receipt["rateLimits"]}
    for bucket in limits.values():
        for window in (bucket.get("primary"), bucket.get("secondary")):
            if isinstance(window, dict) and float(window.get("usedPercent") or 0) >= 100:
                raise CodexError(
                    "codex_quota_exhausted",
                    "Codex 订阅额度已用完，请等待额度恢复；不会转用 API 或购买点数。",
                    details={"resets_at": window.get("resetsAt")},
                )
    public_limits = {
        str(name): {
            key: {
                field: window[field]
                for field in ("usedPercent", "windowDurationMins", "resetsAt")
                if field in window
            }
            for key in ("primary", "secondary")
            if isinstance(window := bucket.get(key), dict)
        }
        for name, bucket in limits.items()
        if isinstance(bucket, dict)
    }
    return {
        "rate_limits": public_limits,
        "status": "reported" if public_limits else "not_reported",
    }


def usage_receipt(value: dict | None) -> dict:
    value = value or {}
    fields = {
        "input_tokens": "inputTokens",
        "output_tokens": "outputTokens",
        "cache_read_tokens": "cachedInputTokens",
        "cache_write_tokens": "cacheWriteInputTokens",
    }
    counts = {}
    for target, source in fields.items():
        count = value.get(source)
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            counts[target] = count
    valid = (
        "input_tokens" in counts
        and "output_tokens" in counts
        and counts.get("cache_read_tokens", 0) <= counts.get("input_tokens", 0)
    )
    return {
        **dict.fromkeys(fields, 0),
        **counts,
        "usage_status": "reported" if valid else "invalid" if value else "not_reported",
        "cache_status": ("supported_hit" if counts.get("cache_read_tokens") else "supported_miss")
        if valid and "cachedInputTokens" in value
        else "unknown",
        "estimated_cost": None,
    }


class CodexTurn:
    def __init__(
        self, config: dict, system: str, user: str, *, schema=None, tools=None, cancelled=None
    ):
        # Resolve bundled capabilities only for a native Codex turn. Eager root
        # imports would pollute the independently selected legacy code family.
        from model_capabilities import ModelCapabilityError, compact_request_context

        self.client = connection().new_client(
            timeout=float(config.get("timeout") or 120), cancelled=cancelled
        )
        self.thread_id = self.turn_id = ""
        self.pending: dict | None = None
        self.usage: dict = {}
        self._prior_usage: dict = {}
        self.text = ""
        self._lease: threading.Timer | None = None
        self.deadline = time.monotonic() + float(
            config.get("wall_timeout") or config.get("timeout") or 120
        )
        self.tools = {tool["name"] for tool in tools or []}
        self.cancelled = cancelled
        try:
            try:
                bounded, self.context_compaction = compact_request_context(
                    config,
                    {
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "tools": tools or [],
                        "output_schema": schema,
                    },
                )
            except ModelCapabilityError as error:
                raise CodexError(error.code, str(error), details=error.details) from error
            system, user = (message["content"] for message in bounded["messages"])
            check_account(self.client, cancelled)
            check_limits(self.client, cancelled)
            if config.get("subscription_only_acknowledged") is not True:
                raise CodexError(
                    "codex_extra_usage_confirmation_required", "请先确认账号已关闭额外付费用量。"
                )
            thread = self.client.request(
                "thread/start",
                {
                    "model": config["model"],
                    "modelProvider": "openai",
                    "cwd": str(codex_home() / "workspace"),
                    "sandbox": "read-only",
                    "approvalPolicy": "never",
                    "ephemeral": True,
                    "baseInstructions": system
                    + "\nYou are HaloCue's narrative assistant. Use only the supplied HaloCue tools. Never use shell, file mutation, web search or other agents. Return the requested JSON as the final answer. All story edits are reviewable proposals.",
                    "dynamicTools": [
                        {
                            "type": "function",
                            "name": tool["name"],
                            "description": tool["description"],
                            "inputSchema": tool["input_schema"],
                        }
                        for tool in tools or []
                    ],
                },
                deadline=self.deadline,
                cancelled=cancelled,
            )
            self.thread_id = thread["thread"]["id"]
            params = {"threadId": self.thread_id, "input": [{"type": "text", "text": user}]}
            if schema is not None:
                params["outputSchema"] = schema
            effort = config.get("reasoning_effort")
            if effort and effort not in {"auto", "none"}:
                params["effort"] = effort
            # Keep the stable policy shared by CLI 0.153 and 0.159. Restricted
            # read roots moved to named permission profiles in 0.159. Native
            # tools stay disabled; all data retrieval uses checked HaloCue tools.
            params["sandboxPolicy"] = {"type": "readOnly"}
            started = self.client.request(
                "turn/start", params, deadline=self.deadline, cancelled=cancelled
            )
            self.turn_id = started["turn"]["id"]
        except Exception:
            self.close()
            raise

    def step(self, *, cancelled=None, on_activity=None) -> dict:
        try:
            while True:
                message = self.client.next_event(self.deadline, cancelled or self.cancelled)
                params = message.get("params") or {}
                method = message.get("method")
                if method == "item/tool/call" and "id" in message:
                    if (
                        params.get("threadId") != self.thread_id
                        or params.get("turnId") != self.turn_id
                        or params.get("tool") not in self.tools
                        or not isinstance(params.get("arguments"), dict)
                    ):
                        self.client.reject(message)
                        raise CodexError(
                            "codex_tool_not_allowed", "Codex 请求了未授权的工具，已停止任务。"
                        )
                    self.pending = message
                    self._lease = threading.Timer(
                        min(60, max(1, self.deadline - time.monotonic())), self.close
                    )
                    self._lease.daemon = True
                    self._lease.start()
                    return {"text": "", "tool": params, "usage": self._usage_delta()}
                if "id" in message and method:
                    self.client.reject(message)
                    raise CodexError(
                        "codex_tool_not_allowed",
                        "Codex 请求了 HaloCue 之外的权限或操作，已停止任务。",
                    )
                if params.get("threadId") not in {None, self.thread_id}:
                    continue
                if method == "thread/tokenUsage/updated":
                    self.usage = (params.get("tokenUsage") or {}).get("total") or {}
                elif method == "item/agentMessage/delta":
                    if on_activity:
                        on_activity(
                            {
                                "state": "receiving",
                                "received_chars": len(str(params.get("delta") or "")),
                            }
                        )
                elif method == "item/completed":
                    item = params.get("item") or {}
                    if item.get("type") in {"commandExecution", "fileChange", "mcpToolCall"}:
                        raise CodexError(
                            "codex_tool_not_allowed", "Codex 请求了未授权的原生操作，已停止任务。"
                        )
                    if item.get("type") == "agentMessage" and item.get("phase") != "commentary":
                        self.text = str(item.get("text") or "")
                elif method == "turn/completed":
                    turn = params.get("turn") or {}
                    if turn.get("id") != self.turn_id:
                        continue
                    if turn.get("status") != "completed":
                        error = turn.get("error") or {}
                        info = error.get("codexErrorInfo")
                        code = (
                            "codex_quota_exhausted"
                            if info in ("usageLimitExceeded", "rateLimitExceeded")
                            else "codex_cancelled"
                            if turn.get("status") == "interrupted"
                            else "codex_turn_failed"
                        )
                        raise CodexError(
                            code,
                            "Codex 任务未完成；已停止，没有转用 API。",
                            details={"status": turn.get("status")},
                        )
                    if not self.text.strip():
                        raise CodexError(
                            "codex_output_empty", "Codex 未返回有效内容，没有生成候选。"
                        )
                    result = {
                        "text": self.text,
                        "tool": None,
                        "usage": self._usage_delta(),
                        "total_usage": usage_receipt(self.usage),
                    }
                    self.close()
                    return result
        except CodexError as error:
            error.details = {**error.details, "usage": self._usage_delta()}
            self.close()
            raise
        except Exception:
            self.close()
            raise

    def _usage_delta(self) -> dict:
        current = self.usage
        delta = {
            key: max(0, value - self._prior_usage.get(key, 0))
            for key, value in current.items()
            if isinstance(value, int)
        }
        self._prior_usage = dict(current)
        return usage_receipt(delta)

    def resume_tool(self, results: list[dict]):
        if not self.pending:
            raise CodexError("codex_tool_exchange_missing", "工具上下文已失效，请重新发起任务。")
        if self._lease:
            self._lease.cancel()
        call = self.pending["params"]
        matched = [
            item
            for item in results
            if item.get("id") == call["callId"] and item.get("tool") == call["tool"]
        ]
        if len(matched) != 1:
            self.close()
            raise CodexError("codex_tool_exchange_invalid", "工具结果与 Codex 请求不匹配。")
        result = matched[0]
        self.client.send(
            {
                "id": self.pending["id"],
                "result": {
                    "success": result.get("status") == "succeeded",
                    "contentItems": [
                        {"type": "inputText", "text": json.dumps(result, ensure_ascii=False)}
                    ],
                },
            }
        )
        self.pending = None

    def close(self):
        if self._lease:
            self._lease.cancel()
        self.client.close()


class CodexConnection:
    def __init__(self):
        self._lock = threading.RLock()
        self._client: AppServerClient | None = None
        self._path = ""

    def new_client(self, *, timeout=30, cancelled=None) -> AppServerClient:
        cli = discover_cli(self._path)
        if cli is None:
            raise CodexError(
                "codex_not_installed", "未找到 Codex CLI，请安装官方 Codex，或指定 codex.exe。"
            )
        return AppServerClient(cli, codex_home(), timeout=timeout, cancelled=cancelled)

    def client(self) -> AppServerClient:
        if self._client is None or self._client._closed or self._client.process.poll() is not None:
            self._client = self.new_client()
        return self._client

    def configure(self, payload: dict):
        allowed = {"cli_path"}
        if set(payload) - allowed:
            raise CodexError(
                "codex_config_invalid", "Codex 连接不接受 API Key、接口地址或登录令牌。"
            )
        path = str(payload.get("cli_path") or "").strip()
        discover_cli(path)
        with self._lock:
            if self._client:
                self._client.close()
            self._path = path
            home = codex_home()
            home.mkdir(parents=True, exist_ok=True)
            destination = home / "halocue-connection.json"
            temporary = destination.with_suffix(".tmp")
            temporary.write_text(json.dumps({"cli_path": path}), encoding="utf-8")
            os.replace(temporary, destination)
        return self.status()

    def status(self) -> dict:
        with self._lock:
            cli = discover_cli(self._path)
            if cli is None:
                return {
                    "schema_version": "codex-connection/1.0",
                    "installed": False,
                    "logged_in": False,
                    "billing": "chatgpt_subscription",
                    "models": [],
                    "state": "not_installed",
                }
            client = self.client()
            try:
                account = check_account(client)
            except CodexError as error:
                if error.code not in {"codex_login_required", "codex_subscription_required"}:
                    raise
                return {
                    "schema_version": "codex-connection/1.0",
                    "installed": True,
                    "logged_in": False,
                    "billing": "chatgpt_subscription",
                    "models": [],
                    "state": error.code,
                }
            models, cursor = [], None
            while True:
                page = client.request(
                    "model/list", {"limit": 100, "includeHidden": False, "cursor": cursor}
                )
                models.extend(
                    {
                        "id": item["model"],
                        "name": item.get("displayName") or item["model"],
                        "default": bool(item.get("isDefault")),
                    }
                    for item in page.get("data", [])
                    if isinstance(item, dict) and item.get("model")
                )
                cursor = page.get("nextCursor")
                if not cursor:
                    break
            try:
                limits = check_limits(client)
                state = "ready"
            except CodexError as error:
                if error.code != "codex_quota_exhausted":
                    raise
                limits, state = error.details, "quota_exhausted"
            return {
                "schema_version": "codex-connection/1.0",
                "installed": True,
                "logged_in": True,
                "billing": "chatgpt_subscription",
                "account": account,
                "models": models,
                "limits": limits,
                "state": state,
            }

    def login(self):
        with self._lock:
            # The provider owns OAuth and refresh. HaloCue never receives tokens.
            result = self.client().request("account/login/start", {"type": "chatgpt"})
            return {"type": result.get("type"), "auth_url": result.get("authUrl")}

    def logout(self):
        with self._lock:
            self.client().request("account/logout")
            return self.status()

    def close(self):
        with self._lock:
            if self._client:
                self._client.close()


_CONNECTIONS: dict[Path, CodexConnection] = {}
_CONNECTION_LOCK = threading.Lock()


def connection() -> CodexConnection:
    home = codex_home()
    with _CONNECTION_LOCK:
        if home not in _CONNECTIONS:
            value = CodexConnection()
            settings = home / "halocue-connection.json"
            if settings.is_file():
                try:
                    value._path = str(
                        json.loads(settings.read_text(encoding="utf-8")).get("cli_path") or ""
                    )
                except (OSError, ValueError):
                    raise CodexError(
                        "codex_config_invalid", "Codex 连接配置损坏，请重新设置程序路径。"
                    )
            _CONNECTIONS[home] = value
        return _CONNECTIONS[home]


def close_connections():
    for value in tuple(_CONNECTIONS.values()):
        value.close()
    for client in tuple(_CLIENTS):
        client.close()


atexit.register(close_connections)


def validate_config(payload: dict) -> dict:
    if any(payload.get(key) for key in ("api_key", "api_key_env", "base_url")):
        raise CodexError(
            "codex_subscription_required", "Codex 订阅连接不接受 API Key 或自定义接口。"
        )
    model = str(payload.get("model") or "").strip()
    if not model or len(model) > 160:
        raise CodexError("invalid_model_name", "请选择一个 Codex 模型。")
    if payload.get("subscription_only_acknowledged") is not True:
        raise CodexError(
            "codex_extra_usage_confirmation_required",
            "请确认账号已关闭额外付费用量，才能启用仅订阅连接。",
        )
    try:
        timeout = int(payload.get("timeout") or 120)
    except (TypeError, ValueError) as error:
        raise CodexError("invalid_model_limits", "Codex 超时必须是有效秒数。") from error
    if not 5 <= timeout <= 600:
        raise CodexError("invalid_model_limits", "Codex 超时必须在 5 到 600 秒之间。")
    return {
        "preset_id": "codex",
        "provider": "codex",
        "model": model,
        "base_url": "",
        "api_key_env": "",
        "max_tokens": 8192,
        "timeout": timeout,
        "subscription_only_acknowledged": True,
        "billing": "chatgpt_subscription",
    }


def test_connection(config: dict) -> dict:
    started = time.monotonic()
    turn = CodexTurn(
        config,
        "Return JSON only.",
        'Return exactly {"ok":true}.',
        schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
    )
    try:
        result = turn.step()
        try:
            parsed = json.loads(result["text"])
        except (TypeError, ValueError) as error:
            raise CodexError("codex_output_invalid", "Codex 连接测试未返回有效 JSON。") from error
        if not isinstance(parsed, dict) or parsed.get("ok") is not True:
            raise CodexError("codex_output_invalid", "Codex 连接测试未返回有效结果。")
        return {
            "ok": True,
            "provider": "codex",
            "model": config["model"],
            "latency_ms": round((time.monotonic() - started) * 1000),
            "usage": result["usage"],
            "billing": "chatgpt_subscription",
        }
    finally:
        turn.close()
