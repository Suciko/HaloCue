"""Adapt shared first-party model capability rules to this service's errors."""

from __future__ import annotations
import importlib.util
import sys
from pathlib import Path
from .errors import ProductionError

_name = "_halocue_shared_model_capabilities"
if _name not in sys.modules:
    _root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[5]))
    _spec = importlib.util.spec_from_file_location(_name, _root / "model_capabilities.py")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_name] = _module
    _spec.loader.exec_module(_module)
_shared = sys.modules[_name]
LIMIT_FIELDS = _shared.LIMIT_FIELDS
ADVANCED_FIELDS = _shared.ADVANCED_FIELDS
capabilities = _shared.capabilities
model_catalog = _shared.model_catalog
upstream_capabilities = _shared.upstream_capabilities


def normalize_advanced(payload):
    try:
        return _shared.normalize_advanced(payload)
    except _shared.ModelCapabilityError as error:
        raise ProductionError(error.code, error.message) from error


def completion_parameters(config, contents, **kwargs):
    try:
        return _shared.completion_parameters(config, contents, **kwargs)
    except _shared.ModelCapabilityError as error:
        raise ProductionError(error.code, error.message) from error
