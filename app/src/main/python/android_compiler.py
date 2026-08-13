"""Android-owned adapter around the shared script2aap compiler core."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import android_resource_mapping
import script2aap


_COMPILE_LOCK = threading.Lock()
_MODULE_DIR = Path(__file__).resolve().parent
_CAST_FILE = _MODULE_DIR / "cast.json"
_INDEX_FILE = _MODULE_DIR / "aa_resources.json"


def compile_text(text: str, *, project: str, workspace: str | Path) -> dict:
    """Compile screenplay text inside HaloCue's private writable workspace.

    The returned project has not been copied into AzureArchive.  Callers must
    preserve that distinction in their UI.
    """
    root = Path(workspace).resolve()
    exports = root / "exports"
    inputs = root / "inputs"
    exports.mkdir(parents=True, exist_ok=True)
    inputs.mkdir(parents=True, exist_ok=True)

    safe_project = script2aap.validate_windows_path_component(
        project,
        label="project name",
    )
    script_file = inputs / f"{safe_project}.txt"
    script_file.write_text(str(text), encoding="utf-8", newline="\n")

    with _COMPILE_LOCK:
        script2aap.warn.items.clear()
        cfg, cast, _id_to_name = script2aap.load_cast(_CAST_FILE)
        index = json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
        try:
            index = android_resource_mapping.merge_mapping(
                index, android_resource_mapping.load_mapping()
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        events = script2aap.parse_script(script_file, cast)
        scenes = script2aap.build(events, cfg, cast, index, safe_project)
        script2aap.apply_identifier_aliases(
            scenes, script2aap.identifier_aliases_for_cast(index, cfg)
        )
        flat = [entry for _title, scripts in scenes for entry in scripts]

        first_background = (
            flat[0]["bgFriendlyName"]
            if flat
            else cfg.get("default_bg", "BG_Black")
        )
        payload = script2aap.wrap_project(
            scenes,
            safe_project,
            first_background,
            index.get("bg", {}),
        )

        project_dir = exports / safe_project
        aap_file = exports / f"{safe_project}.aap"
        project_dir.mkdir(parents=True, exist_ok=True)
        script2aap.finalize_project_manifest(
            cast,
            {
                character["name"]
                for entry in flat
                for character in entry["characters"]["$values"]
                if character["name"]
            },
            story_root=root,
            project_dir=project_dir,
            voice_overrides=[],
        )
        script2aap.write_project_resource_index(project_dir, index)
        script2aap.write_aap_atomic(aap_file, payload)

    return {
        "project": safe_project,
        "aap_file": str(aap_file),
        "project_dir": str(project_dir),
        "dialogue_count": len(flat),
        "warnings": [message for _line, message in script2aap.warn.items],
        "imported": False,
    }
