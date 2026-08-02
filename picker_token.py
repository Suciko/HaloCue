# -*- coding: utf-8 -*-
"""
AA 剧本编译器 - File Token 管理器 (picker_token.py)
用于对话框/选择器返回 file_token，隐藏物理暴露的绝对路径，带超时过期机制。
"""

import datetime
import os
import threading
import uuid
from typing import Dict, Optional


class TokenRegistry:
    def __init__(self, ttl_seconds: int = 600):
        self.ttl_seconds = ttl_seconds
        self._tokens: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def register(self, realpath: str) -> str:
        real_abs = os.path.realpath(str(realpath))
        token = f"ft-{uuid.uuid4().hex}"
        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = now + datetime.timedelta(seconds=self.ttl_seconds)

        with self._lock:
            self._tokens[token] = {
                "realpath": real_abs,
                "created_at": now,
                "expires_at": expires_at,
            }
        return token

    def resolve(self, file_token: str) -> Optional[str]:
        now = datetime.datetime.now(datetime.timezone.utc)
        with self._lock:
            info = self._tokens.get(file_token)
            if not info:
                return None
            if now > info["expires_at"]:
                del self._tokens[file_token]
                return None
            return info["realpath"]

    def clean_expired(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        with self._lock:
            expired_keys = [
                k for k, v in self._tokens.items() if now > v["expires_at"]
            ]
            for k in expired_keys:
                del self._tokens[k]


# 全局默认 TokenRegistry
global_token_registry = TokenRegistry(ttl_seconds=600)


def register_file_token(realpath: str) -> str:
    return global_token_registry.register(realpath)


def resolve_file_token(file_token: str) -> Optional[str]:
    return global_token_registry.resolve(file_token)
