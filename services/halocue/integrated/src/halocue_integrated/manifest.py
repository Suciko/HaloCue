from __future__ import annotations

from datetime import datetime, timezone


INTEGRATION_VERSION = "1.0.0"
INTEGRATION_BUILD_ID = "halocue-integrated/1.0.0+20260821.9"


def build_integration_manifest(*, started_at: str | None = None) -> dict:
    return {
        "schema": "integration-manifest/1.0",
        "product": "HaloCue",
        "component": {
            "id": "halocue-integrated",
            "version": INTEGRATION_VERSION,
        },
        "build": {
            "id": INTEGRATION_BUILD_ID,
            "kind": "workspace_snapshot",
            "git_commit": None,
        },
        "entrypoint": "/",
        "workspaces": {
            "writing": {
                "owner": "09-HaloCue-1.0-Writing",
                "mount": "/",
            },
            "production": {
                "owner": "08-HaloCue-1.0",
                "surface": "#productionModule",
                "api_mount": "/production/api/v1/",
                "asset_prefix": "/production/",
            },
        },
        "navigation": {
            "mode": "same_document",
            "history": "push_state",
            "production_surface": "shadow_root",
        },
        "started_at": started_at or datetime.now(timezone.utc).isoformat(),
    }
