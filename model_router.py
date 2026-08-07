"""Resolve text and vision providers from the dual-role model workbench."""

from __future__ import annotations

import llm
from model_profiles import ModelProfileError, ModelProfileStore, source_context_strategy_for_connection


class ModelRouter:
    """Keep request code independent from connection/model assignment storage."""

    def __init__(self, store: ModelProfileStore):
        self.store = store

    def _state(self) -> dict:
        self.store.migrate_legacy_profiles()
        return self.store.public_state()

    @staticmethod
    def _model(state: dict, model_id: str) -> dict:
        record = next(
            (row for row in state.get("models", []) if str(row.get("id")) == str(model_id)),
            None,
        )
        if record is None:
            raise ModelProfileError("找不到指定模型")
        return record

    @staticmethod
    def _connection(state: dict, connection_id: str) -> dict:
        record = next(
            (row for row in state.get("connections", []) if str(row.get("id")) == str(connection_id)),
            None,
        )
        if record is None:
            raise ModelProfileError("找不到模型所属的供应商连接")
        return record

    def _provider_for(self, state: dict, model: dict):
        connection = self._connection(state, model["connection_id"])
        secret = self.store.resolve_connection_key(connection["id"])
        if not secret:
            raise ModelProfileError("所选模型配置尚未设置 API Key")
        return llm.make_provider_from_settings(connection["protocol"], {
            "model": str(model["model"]),
            "base_url": str(connection.get("base_url") or ""),
            "max_tokens": int(model.get("max_tokens") or 16000),
            "annotation_max_tokens": int(model.get("annotation_max_tokens") or min(int(model.get("max_tokens") or 16000), 16000)),
            "reasoning_mode": str(model.get("reasoning_mode") or "balanced"),
            "reasoning_wire_protocol": "deepseek_thinking" if connection.get("service_preset") == "deepseek" else "none",
            "source_context_strategy": source_context_strategy_for_connection(connection),
            "vision": model.get("vision_status") in {"passed", "untested"},
            "api_key": secret,
        })

    def text_provider(self):
        state = self._state()
        model = self._model(state, state["assignments"].get("base_model_id"))
        if model.get("text_status") == "unsupported":
            raise ModelProfileError("基础模型不支持文字请求")
        return self._provider_for(state, model)

    def vision_provider(self):
        state = self._state()
        assignments = state["assignments"]
        mode = assignments.get("vision_mode") or "disabled"
        if mode == "disabled":
            return None
        if mode == "base":
            model = self._model(state, assignments.get("base_model_id"))
        elif mode == "separate":
            model = self._model(state, assignments.get("vision_model_id"))
        else:
            raise ModelProfileError("图片识别模式无效")
        if model.get("vision_status") != "passed":
            raise ModelProfileError("图片模型必须先通过图片测试")
        return self._provider_for(state, model)

    def one_shot_base_fallback(self):
        state = self._state()
        model = self._model(state, state["assignments"].get("base_model_id"))
        if model.get("vision_status") != "passed":
            raise ModelProfileError("基础模型必须先通过图片测试")
        return self._provider_for(state, model)

    def vision_status(self) -> dict:
        state = self._state()
        assignments = state["assignments"]
        mode = assignments.get("vision_mode") or "disabled"
        if mode == "disabled":
            return {"mode": "disabled", "available": False, "model_id": ""}
        model_id = assignments.get("base_model_id") if mode == "base" else assignments.get("vision_model_id")
        model = self._model(state, model_id)
        return {
            "mode": mode,
            "available": model.get("vision_status") == "passed",
            "model_id": model["id"],
            "model": model["model"],
            "status": model.get("vision_status") or "untested",
        }
