# -*- coding: utf-8 -*-
"""校验生成的 .aap：结构是否与 AA 原生工程一致；可选与参照工程逐行比对。

用法: python verify.py 生成的.aap [--ref 手工做的.aap]
"""
import argparse, hashlib, json, sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from aa_registry import load_manifest
from asset_validation import validate_spine
from tables import bg_id

sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_KEYS = ["$type", "text", "popup", "bgEffect", "bgName", "bgFriendlyName",
               "sound", "voice", "transition", "bgmId", "selectionGroup",
               "additionalPrompt", "characters", "speakerSlotNum",
               "highlightedSlotNums", "isDialogScript", "placeText"]
CHAR_KEYS = ["$type", "name", "faceId", "startingPos", "endingPos",
             "emoticon", "action", "effect", "appear", "shapeOverride"]
NODE_TYPES = {"EntryNodeData, Assembly-CSharp", "ScriptNodeData, Assembly-CSharp",
              "ExitNodeData, Assembly-CSharp"}

errs, warns = [], []


@dataclass(frozen=True)
class ProjectAssetReport:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def ok(self):
        return not self.errors


def _project_path(project_dir, relative):
    return Path(project_dir).joinpath(*PureWindowsPath(relative).parts)


def _normalized_relative(value):
    """Comparison-only manifest spelling; never write this representation back."""
    return str(PureWindowsPath(str(value).replace("/", "\\"))).casefold()


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _duplicates(values):
    seen, duplicates = set(), set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _normalized_manifest_paths(values):
    by_normalized = {}
    for value in values:
        by_normalized.setdefault(_normalized_relative(value), []).append(str(value))
    return by_normalized


def _character_comparison_row(row):
    normalized = dict(row)
    for key in ("SpinePortraitPath", "SmallPortraitPath"):
        if normalized.get(key):
            normalized[key] = _normalized_relative(normalized[key])
    return normalized


def _mirror_registered_file(project, save, relative, errors, *, manifest_key=None):
    project_path = _project_path(project, relative)
    save_path = _project_path(save, relative)
    if not project_path.is_file():
        return
    if not save_path.is_file():
        errors.append(f"save {manifest_key + ' ' if manifest_key else ''}asset missing: {relative} ({save_path.name})")
    elif _sha256(project_path) != _sha256(save_path):
        errors.append(f"save {manifest_key + ' ' if manifest_key else ''}asset SHA-256 differs: {relative}")


def _verify_mirror(project, save, manifest, save_manifest, errors):
    for key in ("BgOverrides", "SoundOverrides", "VoiceOverrides"):
        project_paths = _normalized_manifest_paths(manifest[key])
        save_paths = _normalized_manifest_paths(save_manifest[key])
        for normalized, native in project_paths.items():
            if len(native) > 1:
                errors.append(f"manifest.{key} duplicate registration: {native[0]}")
            if normalized not in save_paths:
                errors.append(f"save manifest missing {key}: {native[0]}")
                continue
            _mirror_registered_file(project, save, native[0], errors, manifest_key=key)
        for normalized, native in save_paths.items():
            if len(native) > 1:
                errors.append(f"save manifest.{key} duplicate registration: {native[0]}")
            if normalized not in project_paths:
                errors.append(f"save-only manifest {key}: {native[0]}")

    project_characters = {}
    for row in manifest["CharacterOverrides"]:
        identifier = str(row.get("Identifier") or "")
        project_characters.setdefault(identifier, []).append(row)
    save_characters = {}
    for row in save_manifest["CharacterOverrides"]:
        identifier = str(row.get("Identifier") or "")
        save_characters.setdefault(identifier, []).append(row)
    for row in manifest["CharacterOverrides"]:
        identifier = str(row.get("Identifier") or "")
        matching = save_characters.get(identifier, [])
        if not matching:
            errors.append(f"save manifest missing CharacterOverrides: {identifier}")
            continue
        if len(matching) > 1:
            errors.append(f"save manifest.CharacterOverrides duplicate registration: {identifier}")
            continue
        if _character_comparison_row(row) != _character_comparison_row(matching[0]):
            errors.append(f"save character metadata differs: {identifier}")
        spine = row.get("SpinePortraitPath")
        if spine:
            for suffix in (".skel", ".atlas", ".png"):
                _mirror_registered_file(project, save, str(spine) + suffix, errors)
        avatar = row.get("SmallPortraitPath")
        if avatar:
            _mirror_registered_file(project, save, avatar, errors)
    for identifier, matching in save_characters.items():
        if identifier not in project_characters:
            errors.append(f"save-only manifest CharacterOverrides: {identifier}")


def _face_evidence_ids(capabilities, identifier, *, spine_signature, outfit_key):
    variants = (capabilities or {}).get(identifier, [])
    if spine_signature or outfit_key:
        selected = [
            variant for variant in variants
            if (not spine_signature or variant.get("spine_signature") == spine_signature)
            and (not outfit_key or variant.get("outfit_key") == outfit_key)
        ]
    else:
        selected = [
            variant for variant in variants
            if not variant.get("spine_signature") and not variant.get("outfit_key")
        ]
    all_ids, observed_or_verified = set(), set()
    for variant in selected:
        for face in variant.get("faces") or []:
            face_id = str(face.get("id") or "")
            if not face_id:
                continue
            all_ids.add(face_id)
            sources = set(face.get("sources") or [])
            if sources & {"aap_observed", "aa_verified"}:
                observed_or_verified.add(face_id)
    return all_ids, observed_or_verified


def _verify_aap_faces(payload, project, characters, atlas_faces, errors):
    capabilities = payload.get("face_capabilities") or {}
    index_path = project / "aa_resources.json"
    if index_path.is_file():
        try:
            index_capabilities = json.loads(index_path.read_text(encoding="utf-8-sig")).get("face_capabilities", {})
            capabilities = {**index_capabilities, **capabilities}
        except (OSError, ValueError, TypeError):
            pass
    for script in scripts_of(payload):
        for char in (script.get("characters") or {}).get("$values", []):
            identifier = str(char.get("name") or "")
            face_id = str(char.get("faceId") or "")
            if not identifier or not face_id or identifier not in characters:
                continue
            spine = str(characters[identifier].get("SpinePortraitPath") or "")
            if not spine:
                continue
            spine_file = _project_path(project, spine + ".skel")
            signature = _sha256(spine_file) if spine_file.is_file() else ""
            all_ids, observed_or_verified = _face_evidence_ids(
                capabilities, identifier, spine_signature=signature,
                outfit_key=PureWindowsPath(spine).name,
            )
            all_ids.update(atlas_faces.get(identifier, set()))
            allowed = observed_or_verified if face_id == "99" else all_ids
            if face_id not in allowed:
                errors.append(f"custom character {identifier} faceId {face_id} lacks evidence")


def verify_project_assets(aap_path, project_dir, *, save_dir=None):
    """验证工程私有 manifest、文件与 .aap 引用是否形成闭包。"""
    errors, warnings = [], []
    project = Path(project_dir)
    manifest = load_manifest(project)
    payload = json.loads(Path(aap_path).read_text(encoding="utf-8-sig"))

    bg_paths = manifest["BgOverrides"]
    sound_paths = manifest["SoundOverrides"]
    voice_paths = manifest["VoiceOverrides"]
    char_rows = manifest["CharacterOverrides"]
    if save_dir is not None:
        _verify_mirror(project, Path(save_dir), manifest, load_manifest(save_dir), errors)
    for key, values in (("BgOverrides", bg_paths), ("SoundOverrides", sound_paths), ("VoiceOverrides", voice_paths)):
        for native in _normalized_manifest_paths(values).values():
            if len(native) > 1:
                errors.append(f"manifest.{key} duplicate registration: {native[0]}")
    for key, values in (
        ("BgOverrides", bg_paths),
        ("SoundOverrides", sound_paths),
        ("VoiceOverrides", voice_paths),
    ):
        for value in _duplicates(values):
            errors.append(f"manifest.{key} 重复登记：{value}")

    bgs = {}
    for relative in bg_paths:
        path = _project_path(project, relative)
        stem = PureWindowsPath(relative).stem
        if stem in bgs:
            errors.append(f"背景 stem 重复：{stem}")
        bgs[stem] = path
        if not path.is_file():
            errors.append(f"背景文件不存在：{path}")

    sounds = {}
    for relative in sound_paths:
        path = _project_path(project, relative)
        stem = PureWindowsPath(relative).stem
        if stem in sounds:
            errors.append(f"音效 stem 重复：{stem}")
        sounds[stem] = path
        if not path.is_file():
            errors.append(f"音效文件不存在：{path}")

    for relative in voice_paths:
        path = _project_path(project, relative)
        if not path.is_file():
            errors.append(f"配音文件不存在：{path}")

    characters, atlas_faces = {}, {}
    for row in char_rows:
        identifier = str(row.get("Identifier") or "")
        if identifier in characters:
            errors.append(f"角色 Identifier 重复：{identifier}")
            continue
        characters[identifier] = row
        spine_rel = row.get("SpinePortraitPath")
        if not spine_rel:
            continue
        spine_base = _project_path(project, spine_rel)
        validation = validate_spine(
            Path(str(spine_base) + ".skel"),
            identifier=identifier,
        )
        if validation.candidate is not None:
            atlas_faces[identifier] = set(validation.candidate.metadata.get("faces") or [])
        for issue in validation.issues:
            errors.append(f"角色 {identifier}：{issue.message}")

    for script in scripts_of(payload):
        friendly = str(script.get("bgFriendlyName") or "")
        if friendly in bgs:
            expected = int(bg_id(friendly))
            actual = int(script.get("bgName") or 0)
            if actual != expected:
                errors.append(
                    f"自定义背景 {friendly} 的 bgName 错误：{actual}，应为 {expected}"
                )
        sound = str(script.get("sound") or "")
        if sound in sounds and not sounds[sound].is_file():
            errors.append(f"音效文件不存在：{sounds[sound]}")
        for char in (script.get("characters") or {}).get("$values", []):
            identifier = str(char.get("name") or "")
            if identifier and identifier in characters:
                row = characters[identifier]
                if not row.get("SpinePortraitPath"):
                    warnings.append(f"角色 {identifier} 只有说话标识，没有 Spine 立绘")

    _verify_aap_faces(payload, project, characters, atlas_faces, errors)
    return ProjectAssetReport(tuple(dict.fromkeys(errors)), tuple(dict.fromkeys(warnings)))


def scripts_of(proj):
    out = []
    for n in proj["nodes"]["$values"]:
        for s in (n.get("Scripts") or {}).get("$values", []):
            out.append(s)
    return out


def check(proj):
    if proj.get("$type") != "ProjectData, Assembly-CSharp":
        errs.append("根节点 $type 不对")
    for k in ("ProjectName", "PreviewBgName", "PreviewHeader", "PreviewTitle", "nodes"):
        if k not in proj:
            errs.append(f"根节点缺字段 {k}")

    nodes = proj["nodes"]["$values"]
    guids = {n["Guid"] for n in nodes}
    entries = [n for n in nodes if n["$type"].startswith("EntryNodeData")]
    exits = [n for n in nodes if n["$type"].startswith("ExitNodeData")]
    if len(entries) != 1:
        errs.append(f"入口节点应为 1 个，实际 {len(entries)}")
    elif entries[0]["Guid"] != "00000000-0000-0000-0000-000000000000":
        errs.append("入口节点 Guid 必须为全 0")
    if len(exits) != 1:
        errs.append(f"出口节点应为 1 个，实际 {len(exits)}")

    for n in nodes:
        if n["$type"] not in NODE_TYPES:
            errs.append(f"未知节点类型 {n['$type']}")
        for g in n["ConnectionsTo"]["$values"]:
            if g not in guids:
                errs.append(f"节点 {n['Guid'][:8]} 指向不存在的 {g[:8]}")

    # 可达性
    seen, stack = set(), [entries[0]["Guid"]] if entries else []
    byguid = {n["Guid"]: n for n in nodes}
    while stack:
        g = stack.pop()
        if g in seen:
            continue
        seen.add(g)
        stack += byguid[g]["ConnectionsTo"]["$values"]
    for n in nodes:
        if n["Guid"] not in seen:
            warns.append(f"节点 {n.get('NodeName') or n['Guid'][:8]} 从入口不可达")

    for i, s in enumerate(scripts_of(proj), 1):
        if list(s.keys()) != SCRIPT_KEYS:
            errs.append(f"第{i}行 ScriptData 字段不匹配: {set(SCRIPT_KEYS) ^ set(s.keys())}")
        ch = s["characters"]["$values"]
        if len(ch) != 6:
            errs.append(f"第{i}行 characters 应为 6 个槽位，实际 {len(ch)}")
        for c in ch:
            if list(c.keys()) != CHAR_KEYS:
                errs.append(f"第{i}行 CharacterRecordData 字段不匹配")
                break
            if not isinstance(c["faceId"], str):
                errs.append(f"第{i}行 faceId 必须是字符串")
        sp = s["speakerSlotNum"]
        if not 0 <= sp <= 5:
            errs.append(f"第{i}行 speakerSlotNum 越界: {sp}")
        if sp in s["highlightedSlotNums"]["$values"]:
            warns.append(f"第{i}行 说话者 {sp} 同时出现在高亮列表里")
        if s["bgFriendlyName"] and not s["bgName"]:
            warns.append(f"第{i}行 背景「{s['bgFriendlyName']}」哈希为 0，AA 里需手动重选")


def compare(gen, ref):
    a, b = scripts_of(gen), scripts_of(ref)
    ta = [s["text"] for s in a]
    tb = [s["text"] for s in b]
    sa, sb = set(ta), set(tb)
    only_a, only_b = [t for t in ta if t and t not in sb], [t for t in tb if t and t not in sa]
    print(f"\n=== 与参照工程比对 ===")
    print(f"  生成 {len(a)} 行 / 参照 {len(b)} 行")
    print(f"  文本完全一致的行: {len(sa & sb)}")
    if only_b:
        print(f"  参照有、生成没有 ({len(only_b)}):")
        for t in only_b[:8]:
            print(f"      {t[:52]}")
    if only_a:
        print(f"  生成有、参照没有 ({len(only_a)}):")
        for t in only_a[:8]:
            print(f"      {t[:52]}")

    # 对齐共有文本，比说话者
    pos_b = {}
    for s in b:
        if s["text"]:
            pos_b.setdefault(s["text"], s)
    same = diff = 0
    for s in a:
        r = pos_b.get(s["text"])
        if not r or not s["text"]:
            continue
        na = s["characters"]["$values"][s["speakerSlotNum"]]["name"]
        nb = r["characters"]["$values"][r["speakerSlotNum"]]["name"]
        if na == nb:
            same += 1
        else:
            diff += 1
            if diff <= 5:
                print(f"  说话者不一致: 「{s['text'][:28]}」 生成={na or '旁白'} 参照={nb or '旁白'}")
    print(f"  说话者判定: 一致 {same} 行，不一致 {diff} 行")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("aap")
    ap.add_argument("--ref")
    a = ap.parse_args()

    gen = json.load(open(a.aap, encoding="utf-8"), object_pairs_hook=OrderedDict)
    check(gen)

    print(f"=== 结构校验: {a.aap} ===")
    print(f"  节点 {len(gen['nodes']['$values'])} 个，对白 {len(scripts_of(gen))} 行")
    if errs:
        print(f"  ✗ 错误 {len(errs)} 条")
        for e in errs[:20]:
            print("      " + e)
    else:
        print("  ✓ 结构完全合法")
    if warns:
        print(f"  ! 提示 {len(warns)} 条")
        for w in warns[:10]:
            print("      " + w)
        if len(warns) > 10:
            print(f"      …还有 {len(warns)-10} 条")

    if a.ref:
        compare(gen, json.load(open(a.ref, encoding="utf-8")))
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
