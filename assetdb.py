# -*- coding: utf-8 -*-
"""
素材数据库（SQLite）。

打标是一次性成本：谁跑过一次，把 aa_assets.db 拷给别人就行，不用再让 AI 看一遍图。
所有写入都是幂等的，重复跑只补空缺、不覆盖已有标注（除非 --force）。
"""
import json, os, sqlite3, threading

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
    head_path          TEXT,
    reviewed           INTEGER NOT NULL DEFAULT 0,
    manual_json        TEXT NOT NULL DEFAULT '{}',
    version            INTEGER NOT NULL DEFAULT 1,
    updated_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ident, spine_signature, outfit_key, face_id, model)
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
CREATE INDEX IF NOT EXISTS ix_expression_part_ident ON expression_part(ident);
"""

_SCHEMA_VERSION = "1"
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
    if not _schema_is_current(con):
        with _MIGRATE_LOCK:
            if not _schema_is_current(con):
                con.executescript(SCHEMA)
                migrate_visual_face_labels(con)
                con.execute(
                    """
                    INSERT INTO meta(key,value) VALUES('assetdb_schema_version',?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    """,
                    (_SCHEMA_VERSION,),
                )
                con.commit()
    return con


def migrate_visual_face_labels(con):
    """Add editable-label fields to databases created before workbench v2."""
    columns = {
        row["name"] for row in con.execute("PRAGMA table_info(face_visual_label)")
    }
    additions = {
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


def import_index(con, idx):
    """把 aa_resources.json 里已有的确定信息灌进库（不含需要看图的部分）。"""
    n = {"bg": 0, "sound": 0, "character": 0, "face": 0, "enum": 0}

    for name, h in idx.get("bg", {}).items():
        con.execute("INSERT INTO bg(name,hash) VALUES(?,?) "
                    "ON CONFLICT(name) DO UPDATE SET hash=excluded.hash", (name, h))
        n["bg"] += 1

    for s in idx.get("sounds", []):
        con.execute("INSERT OR IGNORE INTO sound(name) VALUES(?)", (s,))
        n["sound"] += 1

    for c in idx.get("characters", []):
        con.execute("INSERT INTO character(ident,name,club,spine,source) VALUES(?,?,?,?,'overrides') "
                    "ON CONFLICT(ident) DO UPDATE SET name=excluded.name, club=excluded.club, "
                    "spine=excluded.spine", (c["identifier"], c.get("name"), c.get("club"), c.get("spine")))
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
    out = {
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
    }
    chars = {}
    for r in con.execute("SELECT * FROM character"):
        chars[r["ident"]] = {"identifier": r["ident"], "name": r["name"],
                             "club": r["club"], "spine": r["spine"], "faces": []}
    for r in con.execute("SELECT * FROM face ORDER BY ident, face_id"):
        if r["ident"] in chars:
            chars[r["ident"]]["faces"].append(
                {"id": r["face_id"], "raw": r["raw"], "label": r["label"],
                 "cn": r["label_cn"]})
    out["characters"] = list(chars.values())
    enums = {}
    for r in con.execute("SELECT * FROM enum"):
        enums.setdefault(r["kind"], {})[str(r["value"])] = (
            {"sym": r["verb"], "cn": r["label_cn"]} if r["kind"] == "emoticon"
            else {"verb": r["verb"], "cn": r["label_cn"]})
    out["enums"] = enums
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    return out
