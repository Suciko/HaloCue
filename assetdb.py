# -*- coding: utf-8 -*-
"""
素材数据库（SQLite）。

打标是一次性成本：谁跑过一次，把 aa_assets.db 拷给别人就行，不用再让 AI 看一遍图。
所有写入都是幂等的，重复跑只补空缺、不覆盖已有标注（除非 --force）。
"""
import json, os, re, sqlite3, threading

from tables import bg_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS bg (
    name       TEXT PRIMARY KEY,   -- BG_ShoppingDistrict
    hash       INTEGER,            -- .aap 里的 bgName
    label      TEXT,               -- 商业街
    place      TEXT,               -- 室内 / 室外
    time       TEXT,               -- 白天 / 黄昏 / 夜晚 / 不明
    mood       TEXT,               -- 日常 / 紧张 / 温馨 / …
    tags       TEXT,               -- 逗号分隔关键词
    labeled_by TEXT                -- name / vision:模型名 / manual
);
CREATE TABLE IF NOT EXISTS popup (
    name       TEXT PRIMARY KEY,   -- Event03_CH0070
    label      TEXT,
    descr      TEXT,
    chars      TEXT,               -- 画面里的角色
    tags       TEXT,
    labeled_by TEXT
);
CREATE TABLE IF NOT EXISTS sound (
    name       TEXT PRIMARY KEY,   -- SE_DoorOpen_01
    label      TEXT,
    tags       TEXT,
    labeled_by TEXT
);
CREATE TABLE IF NOT EXISTS character (
    ident  TEXT PRIMARY KEY,       -- 濑名（私服） / 모모이 / 1516544
    name   TEXT,
    club   TEXT,
    spine  TEXT,
    avatar TEXT NOT NULL DEFAULT '',
    source TEXT                    -- overrides / observed / custom
);
CREATE TABLE IF NOT EXISTS face (
    ident    TEXT,
    face_id  TEXT,                 -- '03'
    raw      TEXT,                 -- '03_smile'
    label    TEXT,                 -- smile
    label_cn TEXT,                 -- 微笑
    source   TEXT,                 -- atlas / observed / vision:模型名
    PRIMARY KEY (ident, face_id)
);
CREATE TABLE IF NOT EXISTS character_variant (
    ident           TEXT,
    spine_signature TEXT,
    outfit_key      TEXT,
    spine           TEXT,
    PRIMARY KEY (ident, spine_signature, outfit_key)
);
CREATE TABLE IF NOT EXISTS face_evidence (
    ident           TEXT,
    spine_signature TEXT,
    outfit_key      TEXT,
    face_id         TEXT,
    source          TEXT,
    raw             TEXT,
    label           TEXT,
    label_cn        TEXT,
    observed_count  INTEGER,
    PRIMARY KEY (ident, spine_signature, outfit_key, face_id, source)
);
CREATE TABLE IF NOT EXISTS face_visual_label (
    ident              TEXT NOT NULL,
    spine_signature    TEXT NOT NULL,
    outfit_key         TEXT NOT NULL,
    face_id            TEXT NOT NULL,
    model              TEXT NOT NULL,
    primary_emotion    TEXT NOT NULL,
    secondary_json     TEXT NOT NULL DEFAULT '[]',
    valence            TEXT,
    arousal            TEXT,
    eyes               TEXT,
    brows              TEXT,
    mouth              TEXT,
    blush              INTEGER NOT NULL DEFAULT 0,
    tears              INTEGER NOT NULL DEFAULT 0,
    confidence         REAL NOT NULL DEFAULT 0,
        description_cn     TEXT,
        semantic_json      TEXT NOT NULL DEFAULT '{}',
        observation_json    TEXT NOT NULL DEFAULT '{}',
        backend_json        TEXT NOT NULL DEFAULT '{}',
        head_path          TEXT,
    reviewed           INTEGER NOT NULL DEFAULT 0,
    manual_json        TEXT NOT NULL DEFAULT '{}',
    version            INTEGER NOT NULL DEFAULT 1,
    updated_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ident, spine_signature, outfit_key, face_id, model)
);
-- 官方语料中该角色/表情的真实使用证据。它是检索提示，不是视觉标注，
-- 因此和 face_visual_label 分表，避免文本语境覆盖眼眉嘴等画面事实。
CREATE TABLE IF NOT EXISTS face_official_usage (
    ident           TEXT NOT NULL,
    spine_signature TEXT NOT NULL DEFAULT '',
    outfit_key      TEXT NOT NULL DEFAULT '',
    face_id         TEXT NOT NULL,
    record_uid      TEXT NOT NULL,
    text_cn         TEXT NOT NULL DEFAULT '',
    silent          INTEGER NOT NULL DEFAULT 0,
    emoticons_json  TEXT NOT NULL DEFAULT '[]',
    actions_json    TEXT NOT NULL DEFAULT '[]',
    closeup         INTEGER NOT NULL DEFAULT 0,
    source          TEXT NOT NULL DEFAULT 'official_corpus',
    PRIMARY KEY (ident, spine_signature, outfit_key, face_id, record_uid)
);
CREATE TABLE IF NOT EXISTS expression_part (
    ident           TEXT NOT NULL,
    spine_signature TEXT NOT NULL,
    outfit_key      TEXT NOT NULL,
    kind            TEXT NOT NULL,
    raw_name        TEXT NOT NULL,
    labels_json     TEXT NOT NULL,
    source          TEXT NOT NULL,
    PRIMARY KEY (ident, spine_signature, outfit_key, raw_name, source)
);
CREATE TABLE IF NOT EXISTS scene_visual_label (
    resource_channel TEXT NOT NULL,
    asset_key        TEXT NOT NULL,
    content_sha256   TEXT NOT NULL DEFAULT '',
    source_kind      TEXT NOT NULL DEFAULT '',
    model            TEXT NOT NULL,
    visual_kind      TEXT NOT NULL DEFAULT 'unknown',
    label_json       TEXT NOT NULL DEFAULT '{}',
    evidence_json    TEXT NOT NULL DEFAULT '{}',
    confidence       REAL NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'pending',
    manual_json      TEXT NOT NULL DEFAULT '{}',
    updated_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (resource_channel, asset_key, content_sha256, model)
);
CREATE TABLE IF NOT EXISTS enum (
    kind     TEXT,                 -- emoticon / action / appear / shape
    value    INTEGER,
    verb     TEXT,                 -- [!] / jump / a / closeup
    label_cn TEXT,
    PRIMARY KEY (kind, value)
);
-- 剧本里的名字 -> AA 标识。内置角色（모모이 之类）没有中文名，靠这张表接上。
-- 用户在界面里每选一次就记一次，用得越多猜得越准；随 .db 一起分发给别人。
CREATE TABLE IF NOT EXISTS name_alias (
    script_name TEXT,
    ident       TEXT,
    kind        TEXT,              -- portrait / voice / narrator
    uses        INTEGER DEFAULT 1,
    PRIMARY KEY (script_name, ident)
);
CREATE INDEX IF NOT EXISTS ix_bg_label    ON bg(label);
CREATE INDEX IF NOT EXISTS ix_face_ident  ON face(ident);
CREATE INDEX IF NOT EXISTS ix_face_evidence_ident ON face_evidence(ident);
CREATE INDEX IF NOT EXISTS ix_face_visual_label_ident ON face_visual_label(ident);
CREATE INDEX IF NOT EXISTS ix_face_official_usage_lookup
ON face_official_usage(ident, spine_signature, outfit_key, face_id);
CREATE INDEX IF NOT EXISTS ix_expression_part_ident ON expression_part(ident);
CREATE INDEX IF NOT EXISTS ix_scene_visual_label_key
ON scene_visual_label(resource_channel, asset_key);
"""

_SCHEMA_VERSION = "5"
_MIGRATE_LOCK = threading.RLock()

# 从用户已完成的工程里核对出来的对应关系，作为初始种子。
SEED_ALIAS = [
    ("桃井", "모모이", "portrait"), ("绿", "미도리", "portrait"),
    ("柚子", "유즈", "portrait"), ("爱丽丝", "아리스N", "portrait"),
    ("旁白", "", "narrator"), ("独白", "", "narrator"),
]


def seed_alias(con):
    for nm, ident, kind in SEED_ALIAS:
        con.execute("INSERT OR IGNORE INTO name_alias(script_name,ident,kind,uses) "
                    "VALUES(?,?,?,3)", (nm, ident, kind))
    con.commit()


def remember_alias(con, script_name, ident, kind):
    con.execute("INSERT INTO name_alias(script_name,ident,kind,uses) VALUES(?,?,?,1) "
                "ON CONFLICT(script_name,ident) DO UPDATE SET uses=uses+1, kind=excluded.kind",
                (script_name, ident or "", kind))
    con.commit()


def _looks_placeholder(value):
    """True for junk/placeholder character names like '???', '???N', '??'."""
    s = str(value or "").strip()
    return not s or (s.count("?") >= 2 and len(s) <= 8)


def best_alias(con, script_name):
    """最高用量的别名；portrait 别名若指向占位垃圾角色则跳过。

    narrator / voice 别名直接放行（语音角色在 character 表里可能没有名字）。"""
    for row in con.execute(
        "SELECT ident,kind FROM name_alias WHERE script_name=? ORDER BY uses DESC LIMIT 5",
        (script_name,)):
        if row["kind"] != "portrait":
            return row
        char = con.execute("SELECT name FROM character WHERE ident=? LIMIT 1",
                           (row["ident"],)).fetchone()
        if char is None or _looks_placeholder(char["name"]):
            continue
        return row
    # Built-in aliases are a read-only fallback.  Do not seed or mutate the
    # user's database during lookup; old databases may contain placeholder
    # targets, so the caller still validates the resolved character.
    for name, ident, kind in SEED_ALIAS:
        if name == script_name:
            return {"ident": ident, "kind": kind}
    return None

FACE_CN = {
    "default": "默认", "eyeclose": "闭眼", "normal": "平常", "respond": "回应",
    "smile": "微笑", "embarrassed": "困窘", "serious": "认真", "depressed": "低落",
    "angry": "生气", "shout": "喊叫", "think": "思考", "sarcastic": "揶揄",
    "damaged": "受创", "peaceful": "平静", "yawn": "打哈欠", "fury": "暴怒",
    "panic": "慌张", "pout": "撅嘴", "absurd": "无语", "sneer": "冷笑",
    "worry": "担忧", "crying": "哭泣", "boring": "无聊", "surprise": "惊讶",
    "shame": "羞耻", "shy": "害羞", "scared": "害怕", "groggy": "恍惚",
    "innocent": "无辜", "proud": "得意", "evilsmile": "坏笑", "annoying": "不耐",
    "irritate": "烦躁", "sigh": "叹气", "thinking": "思索",
}


def _schema_is_current(con) -> bool:
    try:
        row = con.execute(
            "SELECT value FROM meta WHERE key='assetdb_schema_version'"
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    return bool(row and str(row[0]) == _SCHEMA_VERSION)


def connect(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = sqlite3.connect(path, timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    with _MIGRATE_LOCK:
        needs_schema = not _schema_is_current(con)
        if needs_schema:
            con.executescript(SCHEMA)
            migrate_visual_face_labels(con)
            migrate_face_official_usage(con)
            migrate_character_avatar(con)
            con.execute(
                """
                INSERT INTO meta(key,value) VALUES('assetdb_schema_version',?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (_SCHEMA_VERSION,),
            )
        con.commit()
    return con


def connect_readonly(path):
    """Open an existing asset database without migrations or writes.

    Generation and audit passes only need to read the labelled asset facts.
    Keeping this connection genuinely read-only prevents a missing/old output
    directory from creating a second empty ``aa_assets.db`` beside a project
    index, and makes the database used by a run explicit and auditable.
    """
    target = os.path.abspath(os.fspath(path))
    if not os.path.isfile(target):
        raise FileNotFoundError(target)
    con = sqlite3.connect(
        f"file:{target.replace(chr(92), '/') }?mode=ro",
        uri=True,
        timeout=5.0,
    )
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    return con


def migrate_character_avatar(con):
    """Add official portrait metadata without rebuilding existing databases."""
    columns = {
        row["name"] for row in con.execute("PRAGMA table_info(character)")
    }
    if "avatar" not in columns:
        con.execute(
            "ALTER TABLE character ADD COLUMN avatar TEXT NOT NULL DEFAULT ''"
        )


def migrate_visual_face_labels(con):
    """Add editable-label fields to databases created before workbench v2."""
    columns = {
        row["name"] for row in con.execute("PRAGMA table_info(face_visual_label)")
    }
    additions = {
        "semantic_json": "TEXT NOT NULL DEFAULT '{}'",
        "observation_json": "TEXT NOT NULL DEFAULT '{}'",
        "backend_json": "TEXT NOT NULL DEFAULT '{}'",
        "manual_json": "TEXT NOT NULL DEFAULT '{}'",
        "version": "INTEGER NOT NULL DEFAULT 1",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }
    for name, declaration in additions.items():
        if name not in columns:
            con.execute(
                f"ALTER TABLE face_visual_label ADD COLUMN {name} {declaration}"
            )
    con.execute(
        """
        UPDATE face_visual_label
        SET updated_at=CURRENT_TIMESTAMP
        WHERE updated_at IS NULL OR updated_at=''
        """
    )
    con.commit()


_LEGACY_FACE_SOURCE = {
    "atlas": "atlas_candidate",
    "observed": "aap_observed",
    "verified": "aa_verified",
    "aa_verified": "aa_verified",
}


def migrate_face_evidence(con):
    """Add variant evidence without rewriting legacy ``character`` or ``face`` rows."""
    for row in con.execute("SELECT ident,spine FROM character"):
        con.execute(
            """
            INSERT OR IGNORE INTO character_variant(ident,spine_signature,outfit_key,spine)
            VALUES (?, '', '', ?)
            """,
            (row["ident"], row["spine"]),
        )
    for row in con.execute("SELECT ident,face_id,raw,label,label_cn,source FROM face"):
        source = _LEGACY_FACE_SOURCE.get(row["source"])
        if not source:
            continue
        con.execute(
            """
            INSERT OR IGNORE INTO face_evidence
              (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count)
            VALUES (?, '', '', ?, ?, ?, ?, ?, ?)
            """,
            (
                row["ident"], row["face_id"], source, row["raw"], row["label"],
                row["label_cn"], 1 if source == "aap_observed" else 0,
            ),
        )
    con.commit()


def replace_expression_parts(
    con,
    *,
    ident: str,
    spine_signature: str,
    outfit_key: str,
    parts: list[dict],
) -> None:
    """Replace optional semantic part hints for exactly one skeleton variant.

    These rows describe a creator's atlas labels.  They are deliberately kept
    separate from ``face_evidence`` because they do not prove an AA faceId.
    """
    ident = str(ident)
    spine_signature = str(spine_signature or "")
    outfit_key = str(outfit_key or "")
    con.execute(
        """
        INSERT OR IGNORE INTO character_variant(ident,spine_signature,outfit_key,spine)
        VALUES (?, ?, ?, '')
        """,
        (ident, spine_signature, outfit_key),
    )
    con.execute(
        """
        DELETE FROM expression_part
        WHERE ident=? AND spine_signature=? AND outfit_key=?
        """,
        (ident, spine_signature, outfit_key),
    )
    records = []
    for part in parts or []:
        raw_name = str(part.get("raw_name") or "").strip()
        if not raw_name:
            continue
        labels = []
        for label in part.get("labels") or []:
            label = str(label).strip()
            if label and label not in labels:
                labels.append(label)
        records.append((
            ident,
            spine_signature,
            outfit_key,
            str(part.get("kind") or "unknown"),
            raw_name,
            json.dumps(labels, ensure_ascii=False),
            str(part.get("source") or "atlas_semantic"),
        ))
    con.executemany(
        """
        INSERT INTO expression_part
          (ident,spine_signature,outfit_key,kind,raw_name,labels_json,source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        records,
    )


def replace_semantic_face_evidence(
    con,
    *,
    ident: str,
    spine_signature: str,
    outfit_key: str,
    combinations: dict,
) -> None:
    """Store read-only Spine face animation evidence for one exact bone variant.

    A creator may reserve a numerical animation such as ``99`` for a non-face
    purpose.  Such entries receive semantics only after the exact variant has
    been observed or verified in AA; semantic parsing alone never makes them
    legal.
    """
    ident = str(ident)
    spine_signature = str(spine_signature or "")
    outfit_key = str(outfit_key or "")
    con.execute(
        """
        INSERT OR IGNORE INTO character_variant(ident,spine_signature,outfit_key,spine)
        VALUES (?, ?, ?, '')
        """,
        (ident, spine_signature, outfit_key),
    )
    observed_or_verified = {
        row["face_id"]
        for row in con.execute(
            """
            SELECT face_id FROM face_evidence
            WHERE ident=? AND spine_signature=? AND outfit_key=?
              AND source IN ('aap_observed','aa_verified')
            """,
            (ident, spine_signature, outfit_key),
        )
    }
    con.execute(
        """
        DELETE FROM face_evidence
        WHERE ident=? AND spine_signature=? AND outfit_key=? AND source='spine_semantic'
        """,
        (ident, spine_signature, outfit_key),
    )
    records = []
    for face_id, record in sorted((combinations or {}).items()):
        if record.get("special") and str(face_id) not in observed_or_verified:
            continue
        primary = str(record.get("primary_emotion") or "").strip()
        source_labels = record.get("semantic_labels") or record.get("labels") or []
        labels = []
        for label in source_labels:
            label = str(label).strip()
            if label and label not in labels:
                labels.append(label)
        raw = " | ".join(str(value) for value in record.get("raw_parts") or [])
        records.append((
            ident, spine_signature, outfit_key, str(face_id), "spine_semantic",
            raw, primary or (labels[0] if labels else ""), "、".join(labels), 0,
        ))
    con.executemany(
        """
        INSERT INTO face_evidence
          (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        records,
    )


def expression_parts_by_variant(con):
    """Return semantic part hints keyed by their exact skeleton variant."""
    out = {}
    for row in con.execute(
        """
        SELECT ident,spine_signature,outfit_key,kind,raw_name,labels_json,source
        FROM expression_part
        ORDER BY ident,spine_signature,outfit_key,kind,raw_name,source
        """
    ):
        key = (row["ident"], row["spine_signature"], row["outfit_key"])
        out.setdefault(key, []).append({
            "kind": row["kind"],
            "raw_name": row["raw_name"],
            "labels": json.loads(row["labels_json"]),
            "source": row["source"],
        })
    return out


def set_meta(con, **kw):
    con.executemany("INSERT INTO meta(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     [(k, str(v)) for k, v in kw.items()])


def set_active_face_label_model(con, model):
    """Select the visual-label version exposed to catalogs and generators."""
    set_meta(con, active_face_label_model=str(model or "").strip())
    con.commit()


def migrate_face_official_usage(con):
    """Ensure the additive official-usage evidence table exists.

    The table is also present in ``SCHEMA`` for new databases; keeping this
    idempotent migration makes upgrades from a partially-created v3 database
    safe and explicit.
    """
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS face_official_usage (
            ident           TEXT NOT NULL,
            spine_signature TEXT NOT NULL DEFAULT '',
            outfit_key      TEXT NOT NULL DEFAULT '',
            face_id         TEXT NOT NULL,
            record_uid      TEXT NOT NULL,
            text_cn         TEXT NOT NULL DEFAULT '',
            silent          INTEGER NOT NULL DEFAULT 0,
            emoticons_json  TEXT NOT NULL DEFAULT '[]',
            actions_json    TEXT NOT NULL DEFAULT '[]',
            closeup         INTEGER NOT NULL DEFAULT 0,
            source          TEXT NOT NULL DEFAULT 'official_corpus',
            PRIMARY KEY (ident, spine_signature, outfit_key, face_id, record_uid)
        );
        CREATE INDEX IF NOT EXISTS ix_face_official_usage_lookup
        ON face_official_usage(ident, spine_signature, outfit_key, face_id);
        """
    )


def replace_face_official_usage(con, records, *, source="official_corpus"):
    """Replace one imported source while preserving other evidence sources.

    ``records`` may contain role-level evidence (empty spine/outfit) or exact
    variant evidence. Values are normalized before insertion and all writes
    are additive with respect to visual labels.
    """
    source = str(source or "official_corpus")
    con.execute("DELETE FROM face_official_usage WHERE source=?", (source,))
    rows = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        ident = str(record.get("ident") or "").strip()
        face_id = str(record.get("face_id") or "").strip()
        uid = str(record.get("record_uid") or "").strip()
        if not ident or not face_id or not uid:
            continue
        def _json_list(value):
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (TypeError, ValueError):
                    value = []
            if not isinstance(value, (list, tuple)):
                return []
            return [str(item).strip() for item in value if str(item).strip()]
        rows.append((
            ident,
            str(record.get("spine_signature") or ""),
            str(record.get("outfit_key") or ""),
            face_id,
            uid,
            str(record.get("text_cn") or record.get("text") or "").strip(),
            int(bool(record.get("silent"))),
            json.dumps(_json_list(record.get("emoticons")), ensure_ascii=False),
            json.dumps(_json_list(record.get("actions")), ensure_ascii=False),
            int(bool(record.get("closeup"))),
            source,
        ))
    con.executemany(
        """
        INSERT OR REPLACE INTO face_official_usage
          (ident,spine_signature,outfit_key,face_id,record_uid,text_cn,silent,
           emoticons_json,actions_json,closeup,source)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    con.commit()
    return len(rows)


_OFFICIAL_FACE_USAGE_IDENT_ALIASES = {
    # 官方语料使用基础身份，AA 素材库把普通爱丽丝拆成了独立立绘身份。
    "아리스N": ("아리스",),
}


def _official_face_usage_idents(ident):
    primary = str(ident or "").strip()
    return tuple(dict.fromkeys(
        (primary, *_OFFICIAL_FACE_USAGE_IDENT_ALIASES.get(primary, ()))
    ))


def official_face_usage(con, *, ident, face_ids=None, spine_signature="", outfit_key="", representative_limit=3):
    """Return compact, variant-aware official contexts for prompt assembly.

    Exact variant rows win over role-level rows. The limit is retrieval
    relevance per face, not an output-token budget.
    """
    ident = str(ident or "").strip()
    if not ident:
        return {}
    allowed = {str(face_id).strip() for face_id in (face_ids or []) if str(face_id).strip()}
    identities = _official_face_usage_idents(ident)
    placeholders = ",".join("?" for _ in identities)
    params = [*identities, str(spine_signature or ""), str(outfit_key or ""), ident]
    rows = con.execute(
        f"""
        SELECT * FROM face_official_usage
        WHERE ident IN ({placeholders}) AND
          ((spine_signature=? AND outfit_key=?) OR
           (spine_signature='' AND outfit_key=''))
        ORDER BY face_id, CASE WHEN ident=? THEN 0 ELSE 1 END,
                 CASE WHEN spine_signature<>'' OR outfit_key<>'' THEN 0 ELSE 1 END,
                 CASE WHEN text_cn<>'' THEN 0 ELSE 1 END,
                 CASE WHEN emoticons_json<>'[]' OR actions_json<>'[]' OR closeup=1 THEN 0 ELSE 1 END,
                 record_uid
        """, params,
    ).fetchall()
    result = {}
    seen = {}
    for row in rows:
        face_id = str(row["face_id"])
        if allowed and face_id not in allowed:
            continue
        bucket = result.setdefault(face_id, [])
        if len(bucket) >= max(1, int(representative_limit)):
            continue
        keys = seen.setdefault(face_id, set())
        exact = bool(row["spine_signature"] or row["outfit_key"])
        # If an exact variant has evidence, don't pad it with role-level rows.
        if not exact and any(item.get("_exact") for item in bucket):
            continue
        key = (str(row["text_cn"] or ""), int(row["silent"] or 0),
               str(row["emoticons_json"]), str(row["actions_json"]), int(row["closeup"] or 0))
        if key in keys:
            continue
        keys.add(key)
        try:
            emoticons = json.loads(row["emoticons_json"] or "[]")
        except (TypeError, ValueError):
            emoticons = []
        try:
            actions = json.loads(row["actions_json"] or "[]")
        except (TypeError, ValueError):
            actions = []
        bucket.append({
            "text": str(row["text_cn"] or ""),
            "silent": bool(row["silent"]),
            "emoticons": emoticons if isinstance(emoticons, list) else [],
            "actions": actions if isinstance(actions, list) else [],
            "closeup": bool(row["closeup"]),
            "record_uid": str(row["record_uid"] or ""),
            "_exact": exact,
        })
    for examples in result.values():
        for item in examples:
            item.pop("_exact", None)
    return result


_NONLEXICAL_FACE_TEXT_RE = re.compile(
    r"[\s…\.．!！?？,，、:：;；~～—─\-（）()\[\]【】「」『』]+"
)


def _face_text_has_lexical_dialogue(text):
    value = str(text or "").strip()
    if not value:
        return False
    compact = value.replace("#n", "").strip()
    if compact[:1] in {"（", "("} and compact[-1:] in {"）", ")"}:
        inner = _NONLEXICAL_FACE_TEXT_RE.sub("", compact[1:-1])
        if len(inner) <= 2:
            return False
    return bool(_NONLEXICAL_FACE_TEXT_RE.sub("", compact))


def official_face_usage_profiles(
    con, *, ident, face_ids=None, spine_signature="", outfit_key=""
):
    """Return deterministic per-face usage counts from all applicable evidence."""
    ident = str(ident or "").strip()
    if not ident:
        return {}
    allowed = {
        str(face_id).strip() for face_id in (face_ids or []) if str(face_id).strip()
    }
    identities = _official_face_usage_idents(ident)
    placeholders = ",".join("?" for _ in identities)
    rows = con.execute(
        f"""
        SELECT * FROM face_official_usage
        WHERE ident IN ({placeholders}) AND
          ((spine_signature=? AND outfit_key=?) OR
           (spine_signature='' AND outfit_key=''))
        ORDER BY face_id, CASE WHEN ident=? THEN 0 ELSE 1 END, record_uid
        """,
        (*identities, str(spine_signature or ""), str(outfit_key or ""), ident),
    ).fetchall()
    grouped = {}
    for row in rows:
        face_id = str(row["face_id"])
        if allowed and face_id not in allowed:
            continue
        grouped.setdefault(face_id, []).append(row)
    profiles = {}
    for face_id, candidates in grouped.items():
        deduplicated = {}
        for row in candidates:
            key = (
                str(row["record_uid"] or ""), str(row["text_cn"] or ""),
                int(row["silent"] or 0), str(row["emoticons_json"] or "[]"),
                str(row["actions_json"] or "[]"), int(row["closeup"] or 0),
            )
            deduplicated.setdefault(key, row)
        candidates = list(deduplicated.values())
        exact = [
            row for row in candidates
            if row["spine_signature"] or row["outfit_key"]
        ]
        selected = exact or [
            row for row in candidates
            if not row["spine_signature"] and not row["outfit_key"]
        ]
        lexical = 0
        nonlexical = 0
        no_dialogue = 0
        action = 0
        emoticon = 0
        closeup = 0
        for row in selected:
            text = str(row["text_cn"] or "").strip()
            if bool(row["silent"]) or not text:
                no_dialogue += 1
            elif _face_text_has_lexical_dialogue(text):
                lexical += 1
            else:
                nonlexical += 1
            action += int(str(row["actions_json"] or "[]") != "[]")
            emoticon += int(str(row["emoticons_json"] or "[]") != "[]")
            closeup += int(bool(row["closeup"]))
        profiles[face_id] = {
            "total_count": len(selected),
            "lexical_dialogue_count": lexical,
            "nonlexical_dialogue_count": nonlexical,
            "no_dialogue_count": no_dialogue,
            "action_count": action,
            "emoticon_count": emoticon,
            "closeup_count": closeup,
            "variant_exact": bool(exact),
        }
    return profiles


def set_active_scene_label_model(con, model):
    """Select the scene-label version exposed to catalogs and generators."""
    set_meta(con, active_scene_label_model=str(model or "").strip())
    con.commit()


def active_scene_label_model(con):
    row = con.execute(
        "SELECT value FROM meta WHERE key='active_scene_label_model'"
    ).fetchone()
    return str(row[0] or "").strip() if row else ""


def effective_scene_label_rows(con, *, resource_channel=None, asset_key=None):
    """Select one effective visual label per real AA channel/key identity.

    Manual locks win, followed by the explicitly active model, the currently
    installed extra pack, recency, confidence, and a deterministic tie break.
    Model and content hash remain provenance and never leak into the AA key.
    """
    clauses = []
    values = []
    for column, value in (
        ("resource_channel", resource_channel),
        ("asset_key", asset_key),
    ):
        if value is not None:
            clauses.append(f"{column}=?")
            values.append(str(value or ""))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    preferred = active_scene_label_model(con)
    rows = con.execute(
        f"""
        SELECT * FROM scene_visual_label
        {where}
        ORDER BY resource_channel,LOWER(asset_key),
          CASE
            WHEN status='manual_locked'
              OR TRIM(COALESCE(manual_json,'')) NOT IN ('','{{}}','null') THEN 0
            WHEN model=? THEN 1
            ELSE 2
          END,
          CASE source_kind
            WHEN 'extra_pack' THEN 0
            WHEN 'official_base' THEN 1
            ELSE 2
          END,
          updated_at DESC, confidence DESC, model DESC, content_sha256 DESC
        """,
        (*values, preferred),
    )
    selected = {}
    for row in rows:
        key = (str(row["resource_channel"]), str(row["asset_key"]).casefold())
        selected.setdefault(key, row)
    return list(selected.values())


def query_scene_assets(
    con,
    *,
    query="",
    resource_channel=None,
    visual_kind=None,
    generator_only=False,
):
    """Return effective, ready scene semantics without exposing model versions."""
    from scene_asset_labeler import scene_label_from_row

    needle = str(query or "").strip().casefold()
    results = []
    for row in effective_scene_label_rows(
        con, resource_channel=resource_channel
    ):
        if row["status"] not in {"ready", "manual_locked"}:
            continue
        record = scene_label_from_row(row)
        if visual_kind and record["visual_kind"] != str(visual_kind):
            continue
        if generator_only and not (
            record["resource_channel"] == "background"
            and record["visual_kind"] == "background"
            and record["dialogue_suitable"]
        ):
            continue
        if needle:
            haystack = [
                record.get("asset_key"), record.get("label"),
                record.get("source_category"),
                record.get("main_category"), record.get("main_category_cn"),
                record.get("subcategory"), record.get("place"),
                record.get("mood"), record.get("description"),
                record.get("setting_scope"), record.get("affiliation_hint_cn"),
                *(record.get("affiliation_names_cn") or []),
                record.get("reuse_scope"), record.get("reuse_hint_cn"),
                *(record.get("compatible_affiliation_names_cn") or []),
                record.get("category_path_cn"),
                *(record.get("search_terms_cn") or []),
                *(record.get("tags") or []),
            ]
            if not any(needle in str(value or "").casefold() for value in haystack):
                continue
        results.append(record)
    return sorted(
        results,
        key=lambda item: (
            item["resource_channel"], item["label"].casefold(),
            item["asset_key"].casefold(),
        ),
    )


def active_face_label_model(con):
    row = con.execute(
        "SELECT value FROM meta WHERE key='active_face_label_model'"
    ).fetchone()
    return str(row[0] or "").strip() if row else ""


def effective_visual_label_rows(
    con, *, ident=None, spine_signature=None, outfit_key=None
):
    """Select one effective model row per real variant/face identity.

    Model is provenance, not part of the consumer-facing face identity. Manual
    overrides win first. Runtime-usable rows from the explicitly active model
    come next, then usable fallback models. Identity/persona safety blocks on
    the active model never fall back across model versions. Ordinary incomplete
    relabel rows may still fall back, so a partial batch does not hide a
    previously usable label. Rows that merely need review remain usable and are
    downgraded by face_selection.
    """
    clauses = []
    values = []
    for column, value in (
        ("ident", ident),
        ("spine_signature", spine_signature),
        ("outfit_key", outfit_key),
    ):
        if value is not None:
            clauses.append(f"{column}=?")
            values.append(str(value or ""))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    preferred = active_face_label_model(con)
    rows = con.execute(
        f"""
        SELECT * FROM face_visual_label
        {where}
        ORDER BY ident,spine_signature,outfit_key,face_id,
          CASE
            WHEN TRIM(COALESCE(manual_json,'')) NOT IN ('','{{}}','null') THEN 0
            WHEN model=? THEN 1
            ELSE 2
          END,
          updated_at DESC, confidence DESC, model DESC
        """,
        (*values, preferred),
    )
    grouped = {}
    for row in rows:
        key = (
            str(row["ident"]), str(row["spine_signature"]),
            str(row["outfit_key"]), str(row["face_id"]),
        )
        grouped.setdefault(key, []).append(row)

    def has_manual(row):
        return str(row["manual_json"] or "").strip() not in ("", "{}", "null")

    def backend_payload(row):
        # Read-only overlay databases can legitimately come from an older
        # HaloCue schema.  ``backend_json`` was added after the original face
        # labels; absence means there is no newer safety/selection metadata,
        # not that the otherwise valid semantic row is unreadable.
        try:
            value = json.loads(row["backend_json"] or "{}")
        except (IndexError, KeyError, TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def blocks_model_fallback(row):
        if has_manual(row):
            return False
        backend = backend_payload(row)
        blocks = {
            str(value) for value in backend.get("hard_blocks") or [] if str(value)
        }
        return "persona_scope_blocked" in blocks

    def runtime_ready(row):
        if has_manual(row):
            return True
        backend = backend_payload(row)
        if not backend:
            return True
        return bool(backend.get("selection_ready", True))

    selected = []
    for candidates in grouped.values():
        active_safety_block = next((
            item for item in candidates
            if str(item["model"]) == preferred and blocks_model_fallback(item)
        ), None)
        if active_safety_block is not None:
            selected.append(active_safety_block)
            continue
        row = next((item for item in candidates if has_manual(item)), None)
        if row is None:
            row = next((
                item for item in candidates
                if str(item["model"]) == preferred and runtime_ready(item)
            ), None)
        if row is None:
            row = next((item for item in candidates if runtime_ready(item)), None)
        selected.append(row if row is not None else candidates[0])
    return selected


def import_index(con, idx):
    """把 aa_resources.json 里已有的确定信息灌进库（不含需要看图的部分）。"""
    n = {"bg": 0, "sound": 0, "character": 0, "face": 0, "enum": 0}

    # Older scans could mistake arbitrary numeric AAP fields for character
    # identifiers. They have no native label and are only generated data, so
    # discard them before importing the current authoritative index.
    con.execute(
        "DELETE FROM character WHERE source='observed' "
        "AND (name IS NULL OR TRIM(name)='')"
    )

    for name, h in idx.get("bg", {}).items():
        con.execute("INSERT INTO bg(name,hash) VALUES(?,?) "
                    "ON CONFLICT(name) DO UPDATE SET hash=excluded.hash", (name, h))
        n["bg"] += 1

    for s in idx.get("sounds", []):
        con.execute("INSERT OR IGNORE INTO sound(name) VALUES(?)", (s,))
        n["sound"] += 1

    for c in idx.get("characters", []):
        source = str(c.get("source") or "overrides")
        con.execute("INSERT INTO character(ident,name,club,spine,avatar,source) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(ident) DO UPDATE SET name=excluded.name, club=excluded.club, "
                    "spine=excluded.spine, avatar=excluded.avatar, "
                    "source=CASE WHEN character.source IN ('overrides','custom') "
                    "THEN character.source ELSE excluded.source END", (
                        c["identifier"], c.get("name"), c.get("club"),
                        c.get("spine"), c.get("avatar") or "", source,
                    ))
        n["character"] += 1
        for f in c.get("faces", []):
            con.execute("INSERT INTO face(ident,face_id,raw,label,label_cn,source) VALUES(?,?,?,?,?,'atlas') "
                        "ON CONFLICT(ident,face_id) DO UPDATE SET raw=excluded.raw, "
                        "label=excluded.label, label_cn=excluded.label_cn, source='atlas'",
                        (c["identifier"], f["id"], f["raw"], f["label"],
                         FACE_CN.get(f["label"], "")))
            con.execute(
                """
                INSERT INTO face_evidence
                  (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count)
                VALUES (?, '', '', ?, 'atlas_candidate', ?, ?, ?, 0)
                ON CONFLICT(ident,spine_signature,outfit_key,face_id,source) DO UPDATE SET
                  raw=excluded.raw, label=excluded.label, label_cn=excluded.label_cn
                """,
                (c["identifier"], f["id"], f["raw"], f["label"], FACE_CN.get(f["label"], "")),
            )
            n["face"] += 1

    for ident, faces in (idx.get("faces_used") or {}).items():
        con.execute("INSERT OR IGNORE INTO character(ident,source) VALUES(?,'observed')", (ident,))
        for f in faces:
            con.execute("INSERT OR IGNORE INTO face(ident,face_id,raw,label,label_cn,source) "
                        "VALUES(?,?,?,?,?,'observed')",
                        (ident, f["id"], f["raw"], f["label"], FACE_CN.get(f["label"], "")))
            con.execute(
                """
                INSERT INTO face_evidence
                  (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count)
                VALUES (?, '', '', ?, 'aap_observed', ?, ?, ?, 1)
                ON CONFLICT(ident,spine_signature,outfit_key,face_id,source) DO UPDATE SET
                  raw=excluded.raw, label=excluded.label, label_cn=excluded.label_cn,
                  observed_count=MAX(face_evidence.observed_count,excluded.observed_count)
                """,
                (ident, f["id"], f["raw"], f["label"], FACE_CN.get(f["label"], "")),
            )
            n["face"] += 1

    for ident, variants in (idx.get("face_capabilities") or {}).items():
        con.execute("INSERT OR IGNORE INTO character(ident,source) VALUES(?,'observed')", (ident,))
        for variant in variants:
            signature = variant.get("spine_signature") or ""
            outfit_key = variant.get("outfit_key") or ""
            con.execute(
                """
                INSERT INTO character_variant(ident,spine_signature,outfit_key,spine)
                VALUES (?,?,?,?)
                ON CONFLICT(ident,spine_signature,outfit_key) DO UPDATE SET
                  spine=COALESCE(excluded.spine,character_variant.spine)
                """,
                (ident, signature, outfit_key, variant.get("spine") or ""),
            )
            for face in variant.get("faces", []):
                sources = set(face.get("sources") or [])
                for source in sorted(sources & {"atlas_candidate", "aap_observed", "aa_verified"}):
                    con.execute(
                        """
                        INSERT INTO face_evidence
                          (ident,spine_signature,outfit_key,face_id,source,raw,label,label_cn,observed_count)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(ident,spine_signature,outfit_key,face_id,source) DO UPDATE SET
                          raw=excluded.raw, label=excluded.label, label_cn=excluded.label_cn,
                          observed_count=MAX(face_evidence.observed_count,excluded.observed_count)
                        """,
                        (ident, signature, outfit_key, face["id"], source,
                         face.get("raw", face["id"]), face.get("label", ""),
                         face.get("cn", ""), int(face.get("observed_count") or 0)),
                    )

    for kind, table in (idx.get("enums") or {}).items():
        for v, d in table.items():
            con.execute("INSERT INTO enum(kind,value,verb,label_cn) VALUES(?,?,?,?) "
                        "ON CONFLICT(kind,value) DO UPDATE SET verb=excluded.verb, "
                        "label_cn=excluded.label_cn",
                        (kind, int(v), d.get("sym") or d.get("verb"), d.get("cn")))
            n["enum"] += 1

    con.commit()
    return n


def import_bg_files(con, bgs_dir):
    """把素材库磁盘上的背景图也收进来。

    自定义背景的 bgName 是精确文件名 stem 的 xxHash32(UTF-8, seed=0)。
    官方背景仍以游戏表或已有工程映射为准，不在这里重算。"""
    n = 0
    for dp, _, fns in os.walk(bgs_dir):
        for fn in fns:
            stem, ext = os.path.splitext(fn)
            if ext.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
                continue
            con.execute(
                "INSERT INTO bg(name,hash) VALUES(?,?) "
                "ON CONFLICT(name) DO UPDATE SET hash=COALESCE(bg.hash,excluded.hash)",
                (stem, int(bg_id(stem))),
            )
            n += 1
    con.commit()
    return n


def label_bg_from_name(con, force=False):
    """从 BG_XxxYyy_Night 这类命名直接推断，不用看图。看图那步只补剩下的。"""
    TIME = {"night": "夜晚", "dawn": "黎明", "sunset": "黄昏", "evening": "傍晚",
            "morning": "清晨", "day": "白天", "noon": "正午", "rain": "雨天",
            "snow": "雪天", "sunny": "晴天"}
    done = 0
    rows = con.execute("SELECT name FROM bg" if force else
                       "SELECT name FROM bg WHERE labeled_by IS NULL").fetchall()
    for (name,) in rows:
        if not name.startswith("BG_"):
            continue
        body = name[3:]
        parts = body.split("_")
        t = ""
        while len(parts) > 1 and parts[-1].lower() in TIME:
            t = TIME[parts.pop().lower()]
        core = parts[0] if parts else body
        # AbydosRuinArea -> Abydos Ruin Area
        import re
        words = re.sub(r"(?<!^)(?=[A-Z])", " ", core).strip()
        con.execute("UPDATE bg SET label=?, time=?, tags=?, labeled_by='name' WHERE name=?",
                    (words, t, words.lower().replace(" ", ","), name))
        done += 1
    con.commit()
    return done


def stats(con):
    q = lambda s: con.execute(s).fetchone()[0]
    return {
        "背景(可直接用)": (q("SELECT COUNT(*) FROM bg WHERE hash IS NOT NULL"),
                           q("SELECT COUNT(*) FROM bg WHERE hash IS NOT NULL "
                             "AND labeled_by LIKE 'vision%'")),
        "背景(ID待复核)": (q("SELECT COUNT(*) FROM bg WHERE hash IS NULL"),
                           q("SELECT COUNT(*) FROM bg WHERE hash IS NULL "
                             "AND labeled_by LIKE 'vision%'")),
        "CG弹窗": (q("SELECT COUNT(*) FROM popup"),
                   q("SELECT COUNT(*) FROM popup WHERE labeled_by LIKE 'vision%'")),
        "音效": (q("SELECT COUNT(*) FROM sound"),
                 q("SELECT COUNT(*) FROM sound WHERE labeled_by IS NOT NULL")),
        "角色": (q("SELECT COUNT(*) FROM character"), None),
        "表情": (q("SELECT COUNT(*) FROM face"),
                 q("SELECT COUNT(*) FROM face WHERE label_cn <> ''")),
        "枚举": (q("SELECT COUNT(*) FROM enum"), None),
    }


def export_json(con, path):
    """导出成 annotate.py 直接可读的结构，避免运行时依赖 sqlite 查询。"""
    legacy = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            legacy = loaded
    except (FileNotFoundError, OSError, TypeError, ValueError):
        pass
    generated_keys = {
        "bg", "bg_label", "popup_label", "sounds", "sound_label",
        "scene_labels", "characters", "enums",
    }
    out = {key: value for key, value in legacy.items() if key not in generated_keys}
    out.update({
        "bg": {r["name"]: r["hash"] for r in con.execute("SELECT name,hash FROM bg")},
        "bg_label": {r["name"]: {"label": r["label"], "place": r["place"],
                                 "time": r["time"], "mood": r["mood"], "tags": r["tags"]}
                     for r in con.execute("SELECT * FROM bg WHERE label IS NOT NULL")},
        "popup_label": {r["name"]: {"label": r["label"], "descr": r["descr"],
                                    "chars": r["chars"]}
                        for r in con.execute("SELECT * FROM popup WHERE label IS NOT NULL")},
        "sounds": [r["name"] for r in con.execute("SELECT name FROM sound ORDER BY name")],
        "sound_label": {r["name"]: r["label"]
                        for r in con.execute("SELECT * FROM sound WHERE label IS NOT NULL")},
    })
    from scene_asset_labeler import scene_label_from_row
    scene_labels = {"background": {}, "popup": {}}
    for row in effective_scene_label_rows(con):
        if row["status"] not in {"ready", "manual_locked"}:
            continue
        record = scene_label_from_row(row)
        channel = record["resource_channel"]
        scene_labels.setdefault(channel, {})[record["asset_key"]] = record
        if channel == "background":
            out["bg_label"][record["asset_key"]] = record
        elif channel == "popup":
            out["popup_label"][record["asset_key"]] = record
    out["scene_labels"] = scene_labels
    legacy_chars = [
        item for item in (legacy.get("characters") or [])
        if isinstance(item, dict) and str(item.get("identifier") or "")
    ]
    used_legacy_chars = set()

    def legacy_character_for(ident, spine):
        candidates = [
            (index, item) for index, item in enumerate(legacy_chars)
            if index not in used_legacy_chars
            and str(item.get("identifier") or "") == ident
        ]
        normalized_spine = str(spine or "").replace("/", "\\").casefold()
        exact = [
            pair for pair in candidates
            if str(pair[1].get("spine") or "").replace("/", "\\").casefold()
            == normalized_spine
        ]
        selected = exact[0] if exact else (candidates[0] if len(candidates) == 1 else None)
        if selected is None:
            return {}
        used_legacy_chars.add(selected[0])
        return selected[1]

    chars = {}
    for r in con.execute("SELECT * FROM character"):
        record = dict(legacy_character_for(r["ident"], r["spine"]))
        record.update({"identifier": r["ident"], "name": r["name"],
                       "club": r["club"], "spine": r["spine"],
                       "avatar": r["avatar"] or "", "faces": []})
        chars[r["ident"]] = record
    for r in con.execute("SELECT * FROM face ORDER BY ident, face_id"):
        if r["ident"] in chars:
            chars[r["ident"]]["faces"].append(
                {"id": r["face_id"], "raw": r["raw"], "label": r["label"],
                 "cn": r["label_cn"]})
    out["characters"] = list(chars.values()) + [
        record for index, record in enumerate(legacy_chars)
        if index not in used_legacy_chars
    ]
    enums = {}
    for r in con.execute("SELECT * FROM enum"):
        enums.setdefault(r["kind"], {})[str(r["value"])] = (
            {"sym": r["verb"], "cn": r["label_cn"]} if r["kind"] == "emoticon"
            else {"verb": r["verb"], "cn": r["label_cn"]})
    out["enums"] = enums
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    return out
