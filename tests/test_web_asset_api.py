import contextlib
import json
import subprocess
import threading
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen

from PIL import Image

import aa_project_assets
import assetdb
from aa_registry import load_manifest
from asset_import import (
    AssetImportRequestError,
    discover_assets,
    register_asset_request,
    validate_asset_request,
)
import webui
from webui import H, attach_registered_variants, prepare_project_index


@contextlib.contextmanager
def web_server(tmp_path, monkeypatch):
    """Serve the real handler against a disposable AA data root and catalog."""
    monkeypatch.setattr(webui, "DB", str(tmp_path / "assets.db"))
    monkeypatch.setitem(webui.CFG, "aa_data", str(tmp_path / "data"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def post_json(base, path, payload):
    request = Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read())
    except Exception as exc:
        with exc as response:
            return response.status, json.loads(response.read())


def make_wav(path: Path):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(b"\0\0" * 2205)


def make_spine(root: Path, stem: str):
    root.mkdir(parents=True)
    (root / f"{stem}.skel").write_bytes(b"spine 4.2.33")
    (root / f"{stem}.atlas").write_text(
        f"{stem}.png\nsize: 32,32\nformat: RGBA8888\n\n"
        "00_default\n  rotate: false\n",
        encoding="utf-8",
    )
    Image.new("RGBA", (32, 32), "white").save(root / f"{stem}.png")
    Image.new("RGBA", (16, 16), "white").save(
        root / f"{stem}-avatar.png"
    )


def test_discovery_is_read_only(tmp_path):
    Image.new("RGB", (32, 18), "navy").save(tmp_path / "夜景.png")
    make_wav(tmp_path / "敲门.wav")
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    found = discover_assets(tmp_path)

    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert {(row["kind"], row["stem"]) for row in found} == {
        ("background", "夜景"),
        ("sound", "敲门"),
    }


def test_character_validation_requires_user_identifier(tmp_path):
    result = validate_asset_request(
        {"kind": "character", "source": str(tmp_path), "identifier": ""}
    )

    assert result["ok"] is False
    assert "identifier_required" in {issue["code"] for issue in result["issues"]}


def test_registration_requires_explicit_target_project(tmp_path):
    source = tmp_path / "夜景.png"
    Image.new("RGB", (32, 18), "navy").save(source)

    try:
        register_asset_request(
            {"kind": "background", "source": str(source), "project_dir": ""}
        )
    except AssetImportRequestError as exc:
        assert "project" in str(exc).lower()
    else:
        raise AssertionError("registration unexpectedly accepted an empty project")


def test_registration_updates_manifest_and_catalog(tmp_path):
    source = tmp_path / "夜景.png"
    Image.new("RGB", (32, 18), "navy").save(source)
    project = tmp_path / "projects" / "测试工程"
    con = assetdb.connect(tmp_path / "assets.db")

    result = register_asset_request(
        {
            "kind": "background",
            "source": str(source),
            "project_dir": str(project),
            "labels": {"place": "室外", "time": "夜晚"},
        },
        con=con,
    )

    assert result["ok"] is True
    assert result["status"] == "registered"
    assert load_manifest(project)["BgOverrides"] == [r"bgs\夜景.png"]
    row = con.execute(
        "SELECT aa_key,status,metadata_json FROM asset_install"
    ).fetchone()
    assert row["aa_key"] == str(result["aa_key"])
    assert row["status"] == "registered"
    assert json.loads(row["metadata_json"])["labels"]["time"] == "夜晚"
    legacy = con.execute(
        "SELECT hash,place,time FROM bg WHERE name='夜景'"
    ).fetchone()
    assert legacy["hash"] == result["aa_key"]
    assert legacy["place"] == "室外"
    assert legacy["time"] == "夜晚"


def test_web_registration_mirrors_canonical_project_and_save_target(tmp_path, monkeypatch):
    source = tmp_path / "night.png"
    Image.new("RGB", (32, 18), "navy").save(source)

    with web_server(tmp_path, monkeypatch) as base:
        status, result = post_json(
            base,
            "/api/assets/register",
            {"kind": "background", "source": str(source), "project": "native-project"},
        )

    project = (tmp_path / "data" / "projects" / "native-project").resolve()
    save = (tmp_path / "data" / "saves" / "native-project").resolve()
    assert status == 200
    assert result["project_dir"] == str(project)
    assert result["save_dir"] == str(save)
    assert {Path(path) for path in result["install_paths"]} == {
        project / "bgs" / "night.png", save / "bgs" / "night.png"
    }
    assert {Path(path) for path in result["manifest_paths"]} == {
        project / "manifest.json", save / "manifest.json"
    }
    assert result["changed"] is True
    con = assetdb.connect(tmp_path / "assets.db")
    rows = con.execute("SELECT scope,metadata_json FROM asset_install").fetchall()
    assert len(rows) == 1
    assert rows[0]["scope"] == str(project)
    assert set(json.loads(rows[0]["metadata_json"])["manifest_paths"]) == set(result["manifest_paths"])


def test_web_asset_import_accepts_only_the_server_picker_token(tmp_path, monkeypatch):
    """Letting the story UI recover a filesystem path from a token leaks the picker boundary."""
    source = tmp_path / "night.png"
    Image.new("RGB", (32, 18), "navy").save(source)
    script = tmp_path / "Chapter One.txt"
    script.write_text("scene", encoding="utf-8")

    with web_server(tmp_path, monkeypatch) as base:
        _, story_picker = post_json(base, "/api/picker", {"path": str(script)})
        story_status, story = post_json(
            base, "/api/stories/open", {"file_token": story_picker["file_token"]}
        )
        assert story_status == 200
        status, picked = post_json(base, "/api/picker", {"path": str(source)})
        assert status == 200
        status, checked = post_json(
            base, "/api/assets/validate",
            {"kind": "background", "file_token": picked["file_token"]},
        )
        registered_status, registered = post_json(
            base, "/api/assets/register",
            {
                "kind": "background", "file_token": picked["file_token"],
                "story_token": story["story_token"],
            },
        )

    assert status == 200
    assert checked["ok"] is True
    assert registered_status == 200
    assert registered["ok"] is True
    assert "source" not in registered
    assert registered["kind"] == "background"
    assert registered["status"] == "registered"
    assert registered["story_token"] == story["story_token"]
    assert registered["project"] == "Chapter One"
    assert not {"project_dir", "save_dir", "install_path", "manifest_path", "install_paths", "manifest_paths"} & set(registered)


def test_story_token_asset_validation_and_registration_never_disclose_source_paths(tmp_path, monkeypatch):
    """Story-scoped UI payloads must not turn a picker token back into a local path."""
    source = tmp_path / "private-source" / "night.png"
    source.parent.mkdir()
    Image.new("RGB", (32, 18), "navy").save(source)
    script = tmp_path / "Chapter One.txt"
    script.write_text("scene", encoding="utf-8")
    with web_server(tmp_path, monkeypatch) as base:
        _, story_picker = post_json(base, "/api/picker", {"path": str(script)})
        _, story = post_json(base, "/api/stories/open", {"file_token": story_picker["file_token"]})
        _, picker = post_json(base, "/api/picker", {"path": str(source)})
        validated_status, validated = post_json(base, "/api/assets/validate", {
            "kind": "background", "file_token": picker["file_token"], "story_token": story["story_token"],
        })
        registered_status, registered = post_json(base, "/api/assets/register", {
            "kind": "background", "file_token": picker["file_token"], "story_token": story["story_token"],
        })

    assert validated_status == registered_status == 200
    private = str(tmp_path)
    assert private not in json.dumps(validated)
    assert private not in json.dumps(registered)
    assert "source" not in validated
    assert "source" not in registered


def test_story_character_validation_recursively_sanitizes_metadata_file_paths(tmp_path, monkeypatch):
    """Character validation has a nested metadata.files map, which is still browser-facing."""
    source = tmp_path / "private-source" / "character"
    make_spine(source, "hero")
    script = tmp_path / "Chapter One.txt"
    script.write_text("scene", encoding="utf-8")
    with web_server(tmp_path, monkeypatch) as base:
        _, story_picker = post_json(base, "/api/picker", {"path": str(script)})
        _, story = post_json(base, "/api/stories/open", {"file_token": story_picker["file_token"]})
        _, picker = post_json(base, "/api/picker", {"path": str(source)})
        status, validated = post_json(base, "/api/assets/validate", {
            "kind": "character", "file_token": picker["file_token"], "story_token": story["story_token"],
            "identifier": "hero-id", "display_name": "Hero",
        })

    assert status == 200 and validated["ok"] is True
    assert str(tmp_path) not in json.dumps(validated)
    assert set(validated["metadata"]["files"].values()) == {
        "hero.skel", "hero.atlas", "hero.png", "hero-avatar.png",
    }


def test_story_validation_failure_uses_public_issue_messages_without_paths(tmp_path, monkeypatch):
    """Decoder details often repeat an absolute source path and must stay server-side."""
    source = tmp_path / "private-source" / "broken.png"
    source.parent.mkdir()
    source.write_bytes(b"not a png")
    script = tmp_path / "Chapter One.txt"
    script.write_text("scene", encoding="utf-8")
    with web_server(tmp_path, monkeypatch) as base:
        _, story_picker = post_json(base, "/api/picker", {"path": str(script)})
        _, story = post_json(base, "/api/stories/open", {"file_token": story_picker["file_token"]})
        _, picker = post_json(base, "/api/picker", {"path": str(source)})
        status, validated = post_json(base, "/api/assets/validate", {
            "kind": "background", "file_token": picker["file_token"], "story_token": story["story_token"],
        })

    assert status == 200 and validated["ok"] is False
    encoded = json.dumps(validated, ensure_ascii=False)
    assert str(tmp_path) not in encoded
    assert str(source.resolve()) not in encoded
    assert validated["issues"] == [{
        "code": "image_unreadable", "severity": "error", "message": "图片无法读取，请重新选择有效的 PNG 或 JPEG 文件。",
    }]


def test_story_character_register_allowlists_face_analysis_result(tmp_path, monkeypatch):
    """Optional analysis helpers may return command details that are never browser data."""
    source = tmp_path / "private-source" / "character"
    make_spine(source, "hero")
    script = tmp_path / "Chapter One.txt"
    script.write_text("scene", encoding="utf-8")
    private_cli = tmp_path / "tools" / "Spine.com"
    monkeypatch.setattr(webui, "queue_face_analysis", lambda payload: {
        "status": "queued", "queued": True, "job_id": "face-123", "started": True,
        "spine_cli": str(private_cli), "command": [str(private_cli), "--batch"],
        "cwd": str(tmp_path), "input": str(source), "output": str(tmp_path / "out"), "path": str(source),
    })
    with web_server(tmp_path, monkeypatch) as base:
        _, story_picker = post_json(base, "/api/picker", {"path": str(script)})
        _, story = post_json(base, "/api/stories/open", {"file_token": story_picker["file_token"]})
        _, picker = post_json(base, "/api/picker", {"path": str(source)})
        status, registered = post_json(base, "/api/assets/register", {
            "kind": "character", "file_token": picker["file_token"], "story_token": story["story_token"],
            "identifier": "hero-id", "display_name": "Hero", "spine_cli": str(private_cli),
        })

    assert status == 200
    assert registered["face_analysis"] == {"status": "queued", "queued": True, "job_id": "face-123"}
    encoded = json.dumps(registered, ensure_ascii=False)
    assert str(tmp_path) not in encoded
    assert not {"spine_cli", "command", "cwd", "input", "output", "path"} & set(registered["face_analysis"])


def test_story_import_allowlist_retains_normal_safe_metadata_for_all_asset_kinds():
    context = SimpleNamespace(story_token="story-a", project="Chapter One")
    background = webui._public_story_asset_import({
        "ok": True, "kind": "background", "metadata": {"width": 1920, "height": 1080, "format": "PNG", "source": r"C:\private\night.png"}, "issues": [],
    }, context)
    sound = webui._public_story_asset_import({
        "ok": True, "kind": "sound", "metadata": {"duration": 1.25, "codec": "pcm_s16le", "sample_rate": 22050, "channels": 1, "source_path": r"C:\private\rain.wav"}, "issues": [],
    }, context)
    character = webui._public_story_asset_import({
        "ok": True, "kind": "character", "metadata": {"expression_status": "known", "spine_signature": "4.2", "files": {"skel": r"C:\private\hero.skel", "avatar": r"C:\private\hero-avatar.png"}}, "issues": [],
    }, context)

    assert background["metadata"] == {"width": 1920, "height": 1080, "format": "PNG"}
    assert sound["metadata"] == {"duration": 1.25, "codec": "pcm_s16le", "sample_rate": 22050, "channels": 1}
    assert character["metadata"] == {"expression_status": "known", "spine_signature": "4.2", "files": {"skel": "hero.skel", "avatar": "hero-avatar.png"}}


def test_story_scoped_asset_register_rejects_project_mismatch_and_invalid_picker_token(tmp_path, monkeypatch):
    """A browser cannot redirect a story A import to B or forge a filesystem handle."""
    script = tmp_path / "Chapter One.txt"
    script.write_text("scene", encoding="utf-8")
    with web_server(tmp_path, monkeypatch) as base:
        _, story_picker = post_json(base, "/api/picker", {"path": str(script)})
        _, story = post_json(base, "/api/stories/open", {"file_token": story_picker["file_token"]})
        mismatch_status, mismatch = post_json(base, "/api/assets/register", {
            "kind": "background", "file_token": story_picker["file_token"],
            "story_token": story["story_token"], "project": "Other",
        })
        invalid_status, invalid = post_json(base, "/api/assets/register", {
            "kind": "background", "file_token": "expired", "story_token": story["story_token"],
        })

    assert mismatch_status == 409
    assert mismatch["code"] == "project_mismatch"
    assert invalid_status == 400
    assert invalid["code"] == "invalid_file_token"


def test_web_registration_returns_409_when_aa_is_running(tmp_path, monkeypatch):
    source = tmp_path / "night.png"
    Image.new("RGB", (32, 18), "navy").save(source)
    monkeypatch.setattr(aa_project_assets, "is_aa_running", lambda: True)

    with web_server(tmp_path, monkeypatch) as base:
        status, result = post_json(
            base,
            "/api/assets/register",
            {"kind": "background", "source": str(source), "project": "native-project"},
        )

    assert status == 409
    assert result["ok"] is False
    assert result["code"] == "aa_running"
    assert "请关闭 AzureArchive 后重试" in result["e"]


def test_story_character_identifier_conflict_is_a_stable_409(tmp_path, monkeypatch):
    """The task card needs a machine-readable conflict, not a generic register error."""
    source = tmp_path / "character-source"
    make_spine(source, "hero")
    script = tmp_path / "Chapter One.txt"
    script.write_text("scene", encoding="utf-8")
    with web_server(tmp_path, monkeypatch) as base:
        _, story_picker = post_json(base, "/api/picker", {"path": str(script)})
        _, story = post_json(base, "/api/stories/open", {"file_token": story_picker["file_token"]})
        _, picker = post_json(base, "/api/picker", {"path": str(source)})
        first_status, _ = post_json(base, "/api/assets/register", {
            "kind": "character", "file_token": picker["file_token"], "story_token": story["story_token"],
            "identifier": "hero-id", "display_name": "Hero One",
        })
        second_status, second = post_json(base, "/api/assets/register", {
            "kind": "character", "file_token": picker["file_token"], "story_token": story["story_token"],
            "identifier": "hero-id", "display_name": "Hero Two",
        })

    assert first_status == 200
    assert second_status == 409
    assert second["code"] == "same_name_different_content"


def test_web_rejected_registration_keeps_resolved_native_target(tmp_path, monkeypatch):
    with web_server(tmp_path, monkeypatch) as base:
        status, result = post_json(
            base,
            "/api/assets/register",
            {
                "kind": "background",
                "source": str(tmp_path / "missing.png"),
                "project": "native-project",
            },
        )

    project = (tmp_path / "data" / "projects" / "native-project").resolve()
    save = (tmp_path / "data" / "saves" / "native-project").resolve()
    assert status == 200
    assert result["status"] == "rejected"
    assert result["project_dir"] == str(project)
    assert result["save_dir"] == str(save)
    assert result["install_paths"] == []
    assert result["manifest_paths"] == []
    assert result["changed"] is False
    assert "file_missing" in {issue["code"] for issue in result["issues"]}


def _legacy_face_import_presentation_contract():
    ui = Path(__file__).parents[1] / "ui.html"
    script = r'''
const fs=require('fs'), vm=require('vm');
const html=fs.readFileSync(process.argv[1], 'utf8');
const document={querySelector:()=>({style:{},addEventListener:()=>{}}),querySelectorAll:()=>[]};
const fetch=()=>({then(){return this;}});
const sandbox={document,fetch,console};
vm.runInNewContext([...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(x=>x[1]).join('\n'), sandbox);
console.log(sandbox.formatFaceSemantics([
  {face_id:'03',primary_emotion:'惊讶',semantic_labels:['惊讶','意外']},
  {face_id:'42',primary_emotion:'慌张',semantic_labels:['慌张','害羞<img>']}
]));
'''
    output = subprocess.check_output(
        ["node", "-e", script, str(ui)], text=True, encoding="utf-8"
    )

    assert "03" in output
    assert "惊讶、意外" in output
    assert "42" in output
    assert "慌张、害羞&lt;img&gt;" in output
    assert "<img" not in output


def test_web_build_index_contains_only_registered_project_assets(tmp_path):
    source = tmp_path / "夜景.png"
    Image.new("RGB", (32, 18), "navy").save(source)
    project = tmp_path / "projects" / "测试工程"
    con = assetdb.connect(tmp_path / "assets.db")
    register_asset_request(
        {
            "kind": "background",
            "source": str(source),
            "project_dir": str(project),
            "labels": {"label": "夜晚办公室", "tags": "办公室,夜景"},
        },
        con=con,
    )
    official = tmp_path / "official.json"
    official.write_text(
        json.dumps({"bg": {"BG_Black": 1}, "sounds": [], "characters": []}),
        encoding="utf-8",
    )
    output = tmp_path / "merged.json"

    prepare_project_index(official, project, output, con=con)

    merged = json.loads(output.read_text(encoding="utf-8"))
    assert "BG_Black" in merged["bg"]
    assert "夜景" in merged["bg"]
    assert merged["bg_label"]["夜景"]["label"] == "夜晚办公室"


def test_character_web_import_is_idempotent_with_same_user_identifier(tmp_path):
    spine = tmp_path / "spine"
    make_spine(spine, "character")
    project = tmp_path / "projects" / "测试工程"
    request = {
        "kind": "character",
        "source": str(spine),
        "project_dir": str(project),
        "identifier": "用户填写-ID",
        "display_name": "凯伊",
    }

    first = register_asset_request(request)
    second = register_asset_request(request)

    assert first["changed"] is True
    assert second["ok"] is True
    assert second["changed"] is False


def test_web_character_import_queues_background_face_analysis(
    tmp_path, monkeypatch
):
    spine = tmp_path / "spine"
    make_spine(spine, "character")
    captured = {}

    def queue(payload):
        captured.update(payload)
        return {"started": True, "status": "queued", "message": "正在解析"}

    monkeypatch.setattr(webui, "queue_face_analysis", queue)
    monkeypatch.setattr(aa_project_assets, "is_aa_running", lambda: False)

    with web_server(tmp_path, monkeypatch) as base:
        status, result = post_json(
            base,
            "/api/assets/register",
            {
                "kind": "character",
                "source": str(spine),
                "project": "native-project",
                "identifier": "custom-kei",
                "display_name": "凯伊",
                "nickname": "特殊现象调查部",
                "spine_cli": r"E:\Spine3.8.75\Spine.com",
            },
        )

    assert status == 200
    assert result["face_analysis"]["started"] is True
    assert captured["ident"] == "custom-kei"
    assert captured["source"] == str(spine.resolve())
    assert captured["outfit_key"] == "character"
    assert captured["spine_cli"] == r"E:\Spine3.8.75\Spine.com"


def test_web_build_attaches_registered_skeleton_scope_to_cast(tmp_path):
    spine = tmp_path / "spine"
    make_spine(spine, "character")
    project = tmp_path / "projects" / "sample"
    con = assetdb.connect(tmp_path / "assets.db")
    register_asset_request(
        {
            "kind": "character", "source": str(spine), "project_dir": str(project),
            "identifier": "date-kei", "display_name": "Kei",
        },
        con=con,
    )
    cast = {"cast": {"Kei": {"id": "date-kei", "portrait": True}}}

    attach_registered_variants(cast, con, project)

    entry = cast["cast"]["Kei"]
    assert entry["spine_signature"]
    assert entry["outfit_key"] == "character"
