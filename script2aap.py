# -*- coding: utf-8 -*-
"""
剧本(.txt/.md) -> AzureArchive 工程(.aap)

用法:
  python script2aap.py 剧本.txt -o "第一章" [--install] [--dry-run]
  python script2aap.py --syntax          打印完整语法说明

覆盖 AA 操作面板上的全部字段：背景 / 弹出图片 / 背景音乐 / 音效 / 背景效果 / 过渡 /
地点名称 / 额外指令，以及每个角色的 表情 / 地位 / 位置 / 表情符号 / 动作 / 效果。
"""
import argparse, copy, hashlib, itertools, json, os, re, shutil, sys, tempfile, uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path, PureWindowsPath

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from stage import Stage, LAYOUT, APPEAR, DISAPPEAR          # noqa: E402
import camera                                                # noqa: E402
from performance_rules import (                               # noqa: E402
    enforce_focusline_shots,
    enforce_persistent_closeups,
)
import aapaths, tables                                       # noqa: E402
from background_requests import (                            # noqa: E402
    UnresolvedBackgroundError,
    collect_background_requests,
)
from aa_registry import (                                    # noqa: E402
    AssetRegistrationError,
    load_manifest,
    register_character,
    register_character_unlocked,
    write_manifest_atomic,
)
from aa_project_assets import (                                # noqa: E402
    assert_aa_closed,
    AAProjectTarget,
    destination_within,
    project_target_lock,
    resolve_project_target,
    validate_windows_path_component,
)
from asset_validation import validate_spine                  # noqa: E402
from document import parse_document_lossless, compile_document  # noqa: E402

T_PROJ = "ProjectData, Assembly-CSharp"
T_NODES = "System.Collections.Generic.List`1[[NodeData, Assembly-CSharp]], mscorlib"
T_ENTRY = "EntryNodeData, Assembly-CSharp"
T_SNODE = "ScriptNodeData, Assembly-CSharp"
T_EXIT = "ExitNodeData, Assembly-CSharp"
T_SLIST = "System.Collections.Generic.List`1[[ScriptData, Assembly-CSharp]], mscorlib"
T_SCRIPT = "ScriptData, Assembly-CSharp"
T_CLIST = "System.Collections.Generic.List`1[[ScriptData+CharacterRecordData, Assembly-CSharp]], mscorlib"
T_CHAR = "ScriptData+CharacterRecordData, Assembly-CSharp"
T_GLIST = "System.Collections.Generic.List`1[[System.Guid, mscorlib]], mscorlib"
T_ILIST = "System.Collections.Generic.List`1[[System.Int32, mscorlib]], mscorlib"

SLOTS = 6
NS = uuid.UUID("6ba7b812-9dad-11d1-80b4-00c04fd430c8")

# 立绘效果是三个可组合的位标记；effect 字段恒为 0，实际写 shapeOverride。
SHAPE = {
    "": 0, "无": 0,
    "通讯": 1, "communication": 1, "sig": 1,
    "黑屏剪影": 2, "黑屏": 2, "剪影": 2, "black": 2,
    "特写": 4, "closeup": 4,
}
EMOTICON_IDS = frozenset(range(20)) | {-1}
ACTION_IDS = frozenset(range(1, 8))
SHAPE_IDS = frozenset(range(8))


class ScriptConversionError(ValueError):
    """A script token cannot be represented by a confirmed AA enum value."""


def _resolve_numeric_enum(token, allowed, kind, line):
    value = int(token)
    if value not in allowed:
        allowed_text = ", ".join(str(item) for item in sorted(allowed))
        raise ScriptConversionError(
            f"line {line}: unknown {kind} numeric ID {value}; allowed: {allowed_text}"
        )
    return value

SYNTAX = """
剧本语法
========

  # 标题                        忽略，纯注释
  ## 场景标题                    新建一个节点，清空舞台

台词
  桃井: 台词
  桃井(05)[惊叹]{jump}<特写>: 台词
        (表情) [气泡] {动作} <效果>   四个都可省略，只作用于说话者
        表情可写编号 05 或语义名 smile；气泡可写中文名、符号或编号

环境（写在台词行前面，作用于其后的行）
  @bg BG_GameDevRoom            换背景
  @trans 淡入淡出                过渡效果（配合 @bg 用）
  @bgfx 雨                       背景效果
  @popup Event03_CH0070          弹出图片，只作用于下一行
  @bgm 999                       背景音乐（999 = 静音）
  @se SE_DoorOpen_01             音效，只作用于下一行
  @place 千年科技学园·游戏开发部    地点名称卡
  @wait 2500                     下一行之前停顿（毫秒）

舞台（作用于下一行）
  @enter 凯伊                     入场
  @enter 凯伊 5 右                入场到位置5，从右边进来（左/右可省）
  @exit 爱丽丝                    退场
  @exit 爱丽丝 左                 向左退场
  @move 桃井 1                    走位到位置1
  @stage 桃井@1 绿@3 柚子@5        钉死站位，关掉自动排布
  @auto                          恢复自动排布
  @fx 绿 特写                     立绘效果：特写 / 剪影 / 变暗 / 无
  @hl 桃井,柚子                   本行高亮谁；@hl - 表示都不高亮
                                 默认是台上除说话者外全部高亮

额外指令（会写进 AA 的"额外指令"框）
  @bgshake                       背景抖一下
  @clearst                       清除屏幕浮现文字
  @hidemenu / @showmenu          隐藏 / 恢复右上角菜单
  @shot 凯伊 / @shot 3            射击特效；角色名会按当前镜站位转换，数字槽位保留给手工使用
  @aronatouch                    ARONA 指纹识别特效
  @st [-1200,-430] serial 60     屏幕文字浮现，左对齐
  @stm [0,-430] instant 90       屏幕文字浮现，居中
                                 模式：instant 瞬现 / smooth 淡入 / serial 逐字
                                 字号 50 = 原大小
  @zoom instant 300,-150 2160        背景平移缩放（instant 不需要时长）
  @zoom smooth -650,-450 1860 500    smooth 需要时长
                                 缩放系数 = 3160 / 倍数，小于 3160 是放大
  @raw #任意指令                  逃生舱，原样写入，可重复

对话框内的文字样式直接写在台词里，转换器不做处理，原样传给 AA：
  [7cd0ff]淡蓝色[-]   [size=100]放大[/size]   [b]加粗[/b]   [ruby=注音]文本[/ruby]
"""

HEAD_RE = re.compile(r"^(?P<head>[^:：]{1,40}?)\s*[:：]\s*(?P<text>.*)$")
ANNO_RE = re.compile(
    r"^(?P<who>.*?)"
    r"(?:[（(](?P<face>[^）)]*)[）)])?"
    r"(?:\[(?P<emo>[^\]]*)\])?"
    r"(?:\{(?P<act>[^}]*)\})?"
    r"(?:<(?P<fx>[^>]*)>)?$"
)


class Warn:
    def __init__(self):
        self.items = []

    def __call__(self, line, msg):
        self.items.append((line, msg))


warn = Warn()


def split_head(head, cast):
    """冒号前的部分 -> 角色 + 演出标注。
    先整体匹配演员表（支持「凯伊（消息）」这类变体名），失败再剥标注。"""
    head = head.strip()
    if head in cast:
        return head, None, None, None, None
    m = ANNO_RE.match(head)
    if not m:
        return head, None, None, None, None
    who, face = m.group("who").strip(), m.group("face")
    # 括号里是中文的当角色变体标记（如「凯伊（消息）」），不是表情
    if face and not re.fullmatch(r"[A-Za-z0-9_]+", face.strip()):
        face = None
    return who, face, m.group("emo"), m.group("act"), m.group("fx")


def load_cast(path):
    cfg = json.load(open(path, encoding="utf-8"))
    cast = dict(cfg.get("cast", {}))
    for a, target in (cfg.get("alias") or {}).items():
        if target in cast:
            cast[a] = cast[target]
    id2name = {v["id"]: k for k, v in cfg.get("cast", {}).items() if v.get("id")}
    return cfg, cast, id2name


def parse_script(path, cast):
    raw = open(path, encoding="utf-8").read()
    nodes = parse_document_lossless(raw)
    events, diagnostics = compile_document(nodes, cast, {})
    for diag in diagnostics:
        if "line_no" in diag and "message" in diag:
            warn(diag["line_no"], diag["message"])
    return events


# ---------------------------------------------------------------- 资源解析
def res_lookup(idx):
    emo_sym, emo_cn = {}, {}
    for k, v in idx["enums"]["emoticon"].items():
        emo_sym[v["sym"]] = int(k)
        if v["cn"]:
            emo_cn[v["cn"]] = int(k)
    act = {v["verb"]: int(k) for k, v in idx["enums"]["action"].items()}
    act_cn = {v["cn"]: int(k) for k, v in idx["enums"]["action"].items() if v["cn"]}
    faces = {c["identifier"]: {f["label"]: f["id"] for f in c["faces"] if f["label"]}
             for c in idx["characters"]}
    return emo_sym, emo_cn, act, act_cn, faces


def parse_bg_argument(arg):
    """Return the complete background name from an ``@bg`` directive.

    Transitions have their own ``@trans`` directive.  Treating the second
    whitespace-separated token as an inline transition made valid custom
    filenames containing spaces impossible to reference.
    """
    return arg.strip()


def merge_project_registered_assets(index, project_dir):
    """Extend an index only with physical assets registered in this project."""
    merged = copy.deepcopy(index)
    merged.setdefault("bg", {})
    merged.setdefault("sounds", [])
    project = Path(project_dir)
    manifest = load_manifest(project)

    for value in manifest["BgOverrides"]:
        relative = PureWindowsPath(value)
        physical = project.joinpath(*relative.parts)
        if physical.is_file():
            merged["bg"][relative.stem] = int(tables.bg_id(relative.stem))
    known_sounds = set(merged["sounds"])
    for value in manifest["SoundOverrides"]:
        relative = PureWindowsPath(value)
        physical = project.joinpath(*relative.parts)
        if physical.is_file() and relative.stem not in known_sounds:
            merged["sounds"].append(relative.stem)
            known_sounds.add(relative.stem)
    return merged


def resolve_emo(tok, emo_sym, emo_cn, no):
    if not tok:
        return -1
    t = tok.strip()
    if re.fullmatch(r"-?\d+", t):
        return _resolve_numeric_enum(t, EMOTICON_IDS, "emoticon", no)
    for table in (emo_sym, emo_cn):
        if t in table:
            return table[t]
    for wrap in (f"[{t}]", "{" + t + "}"):
        if wrap in emo_sym:
            return emo_sym[wrap]
    warn(no, f"未知气泡「{t}」，已忽略")
    return -1


def resolve_act(tok, act, act_cn, no):
    if not tok:
        return 0
    t = tok.strip()
    if re.fullmatch(r"-?\d+", t):
        return _resolve_numeric_enum(t, ACTION_IDS, "action", no)
    if t in act:
        return act[t]
    if t in act_cn:
        return act_cn[t]
    warn(no, f"未知动作「{t}」，已忽略")
    return 0


def resolve_shape(tok, no):
    if not tok:
        return 0
    t = tok.strip()
    if re.fullmatch(r"-?\d+", t):
        return _resolve_numeric_enum(t, SHAPE_IDS, "shape", no)
    if t in SHAPE:
        return SHAPE[t]
    parts = [part.strip() for part in re.split(r"[+＋、,，/]", t) if part.strip()]
    if len(parts) > 1 and all(part in SHAPE and SHAPE[part] for part in parts):
        return sum(SHAPE[part] for part in parts)
    warn(no, f"未知效果「{t}」，可用：通讯 / 黑屏剪影 / 特写 / 无；可用 + 组合")
    return 0


def resolve_face(tok, ident, faces, no):
    if not tok:
        return None
    t = tok.strip()
    if re.fullmatch(r"\d{1,2}", t):
        return t.zfill(2)
    tbl = faces.get(ident, {})
    if t.lower() in tbl:
        return tbl[t.lower()]
    warn(no, f"「{ident}」没有名为「{t}」的表情，已忽略")
    return None


def resolve_named_id(tok, table, kind, no):
    """过渡 / 背景效果：接受名字（查表）或直接写数字 ID。"""
    if not tok:
        return 0
    t = tok.strip()
    if re.fullmatch(r"\d+", t):
        return int(t)
    if t in table:
        return int(table[t])
    warn(no, f"未知{kind}「{t}」" +
         (f"，可用：{'、'.join(list(table)[:6])}" if table else "（索引里还没有对照表）"))
    return 0


# ---------------------------------------------------------------- 构建
def blank_char():
    return {"$type": T_CHAR, "name": "", "faceId": "00", "startingPos": 0,
            "endingPos": 0, "emoticon": -1, "action": 0, "effect": 0,
            "appear": 0, "shapeOverride": 0}


class Pending:
    """攒在下一句台词上的一次性状态。"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.se = ""
        self.popup = ""
        self.place = ""
        self.raw = []            # 额外指令，按顺序
        self.shot = []           # (角色标识, 源文本行号)：等站位确定后再转换为 #N;fx;{shot}
        self.enter = []          # (ident, 位置or None, appear值)
        self.exit = []           # (ident, appear值)
        self.move = {}           # ident -> 目标位置
        self.fx = {}             # ident -> shapeOverride
        self.hl = None           # None=自动；[]=都不高亮；[ident...]=指定

    def prompt(self):
        return "\n".join(self.raw)


def voice_guid(project, n):
    """配音槽的 GUID。用工程名+行号推导，重跑结果不变 —— 否则每生成一次
    配音文件就全部错位，做过 TTS 的人会想打人。"""
    return str(uuid.uuid5(NS, f"{project}/voice/{n}"))


def build(events, cfg, cast, idx, project):
    id2name_g = {v['id']: k for k, v in cast.items() if v.get('id')}
    emo_sym, emo_cn, act, act_cn, faces = res_lookup(idx)
    bgmap = idx.get("bg", {})            # 只作为已知名单，ID 一律现算
    transmap = idx.get("transition", {}) or {}
    bgfxmap = idx.get("bgeffect", {}) or {}

    scenes, cur = [], {"title": None, "ev": []}
    for e in events:
        if e["k"] == "scene":
            if cur["ev"]:
                scenes.append(cur)
            cur = {"title": e["title"], "ev": []}
        elif e["k"] != "title":
            cur["ev"].append(e)
    if cur["ev"]:
        scenes.append(cur)

    out = []
    vseq = itertools.count()          # 全工程连续的配音槽编号
    bg = cfg.get("default_bg", "BG_Black")
    bgm = cfg.get("default_bgm", 999)
    face_state = {}
    scene_bg = cfg.get("scene_bg", {}) or {}

    def ident_of(nm, no, need_portrait=True):
        if nm not in cast:
            warn(no, f"未知角色「{nm}」")
            return None
        c = cast[nm]
        if c.get("narrator") or (need_portrait and not c.get("portrait")):
            warn(no, f"「{nm}」没有立绘，舞台指令对它无效")
            return None
        return c["id"]

    cam_opts = cfg.get("camera") or {}
    cam_on = cam_opts.get("enabled", True)

    for sc in scenes:
        scripts = []
        if sc["title"] in scene_bg:
            bg = scene_bg[sc["title"]]
        # 先给整场算一份镜头计划：每一行画面上该显示谁。
        # 这是 galgame 的剪辑 —— 背景不变，画面里的人变。
        dlg = []
        scene_break = False
        for event in sc["ev"]:
            if event["k"] == "dir" and event["cmd"] in ("bg", "place"):
                scene_break = True
            elif event["k"] == "line":
                row = dict(event)
                row["scene_break"] = scene_break
                dlg.append(row)
                scene_break = False
        if cam_on:
            cam_in = []
            for e in dlg:
                c = cast[e["who"]]
                cam_in.append({"speaker": c["id"] if (c.get("portrait") and
                                                     not c.get("narrator")) else None,
                               "text": e["text"],
                               "scene_break": e.get("scene_break", False)})
            cam_plan = camera.plan_camera(cam_in, cam_opts)
        else:
            cam_plan = None
        cam_i = 0
        st = Stage()
        pend = Pending()
        trans = 0
        bgfx = 0
        pending_place = ""
        # 本场登场顺序（决定自动排布的左右次序）
        seen_order = []
        ever = set()          # 曾经进过画面的（用来区分"首次登场"和"再次入镜"）

        for e in sc["ev"]:
            # ---------------------------------------------------- 指令
            if e["k"] == "dir":
                cmd, arg, no = e["cmd"], e["arg"], e["no"]
                if cmd == "bg":
                    selected_bg = parse_bg_argument(arg)
                    if selected_bg:
                        bg = selected_bg
                    if bg not in bgmap:
                        warn(no, f"背景「{bg}」没在你的素材库里出现过，ID 已按 xxh32 算出；"
                                 f"名字写错的话 AA 里会显示不出来")
                elif cmd == "trans":
                    trans, err = tables.resolve_transition(arg)
                    if err:
                        warn(no, err)
                elif cmd == "bgfx":
                    bgfx, err = tables.resolve_bgeffect(arg)
                    if err:
                        warn(no, err)
                elif cmd == "popup":
                    pend.popup = arg
                elif cmd in ("bgm", "music"):
                    bgm = int(arg) if arg.lstrip("-").isdigit() else bgm
                elif cmd in ("se", "sound"):
                    pend.se = arg
                    if arg and arg not in idx.get("sounds", []):
                        warn(no, f"音效「{arg}」不在索引里")
                elif cmd == "place":
                    pend.place = arg
                elif cmd == "wait":
                    pend.raw.append(f"#wait;{arg}")
                elif cmd == "raw":
                    pend.raw.append(arg)
                elif cmd == "bgshake":
                    pend.raw.append("#bgshake")
                elif cmd == "clearst":
                    pend.raw.append("#clearST")
                elif cmd in ("hidemenu", "showmenu"):
                    pend.raw.append("#" + cmd)
                elif cmd == "aronatouch":
                    pend.raw.append("#fx;AronaTouch")
                elif cmd == "shot":
                    if re.fullmatch(r"[1-5]", arg.strip()):
                        pend.raw.append(f"#{arg.strip()};fx;{{shot}}")
                    else:
                        i = ident_of(arg.strip(), no)
                        if i:
                            pend.shot.append((i, no))
                elif cmd in ("st", "stm"):
                    m = re.match(r"^\[?\s*(-?\d+)\s*,\s*(-?\d+)\s*\]?\s+(\w+)\s+(\d+)", arg)
                    if m:
                        pend.raw.append(
                            f"#{cmd};[{m.group(1)},{m.group(2)}];{m.group(3)};{m.group(4)};")
                    else:
                        warn(no, f"@{cmd} 格式应为:  @{cmd} [X,Y] 模式 字号   模式=instant/smooth/serial")
                elif cmd == "zoom":
                    m = re.match(r"^(\w+)\s+(-?\d+)\s*,\s*(-?\d+)\s+(\d+)(?:\s+(\d+))?", arg)
                    if not m:
                        warn(no, "@zoom 格式应为:  @zoom instant X,Y 缩放系数 [时长]")
                    elif m.group(1) == "instant":
                        pend.raw.append(f"#zmc;instant;{m.group(2)},{m.group(3)};{m.group(4)};")
                    elif m.group(5):
                        pend.raw.append(
                            f"#zmc;smooth;{m.group(2)},{m.group(3)};{m.group(4)};{m.group(5)}")
                    else:
                        warn(no, "@zoom smooth 必须给持续时间")
                elif cmd == "enter":
                    p = arg.split()
                    if not p:
                        warn(no, "@enter 要跟角色名")
                    else:
                        i = ident_of(p[0], no)
                        at = int(p[1]) if len(p) > 1 and p[1].isdigit() else None
                        d = next((x for x in p[1:] if not x.isdigit()), "")
                        if i:
                            pend.enter.append((i, at, APPEAR.get(d, 3)))
                elif cmd == "exit":
                    p = re.split(r"[,，、\s]+", arg)
                    d = p[-1] if p and p[-1] in DISAPPEAR and len(p) > 1 else ""
                    names = p[:-1] if d else p
                    for nm in names:
                        i = ident_of(nm, no) if nm else None
                        if i:
                            pend.exit.append((i, DISAPPEAR.get(d, 6)))
                elif cmd == "move":
                    p = arg.split()
                    if len(p) < 2 or not p[1].isdigit():
                        warn(no, "@move 格式应为:  @move 角色 位置(1-5)")
                    else:
                        i = ident_of(p[0], no)
                        if i:
                            pend.move[i] = int(p[1])
                elif cmd == "stage":
                    st.auto = False
                    for tok in arg.split():
                        mm = re.match(r"^(.+?)@([1-5])$", tok)
                        if not mm:
                            warn(no, f"@stage 的格式是 角色@位置，看不懂「{tok}」")
                            continue
                        i = ident_of(mm.group(1), no)
                        if i:
                            if i not in st.pos:
                                pend.enter.append((i, int(mm.group(2)), 3))
                            else:
                                pend.move[i] = int(mm.group(2))
                            st.pinned[i] = int(mm.group(2))
                elif cmd == "auto":
                    st.auto = True
                    st.pinned.clear()
                elif cmd == "fx":
                    p = arg.split(None, 1)
                    if len(p) < 2:
                        warn(no, "@fx 格式应为:  @fx 角色 效果")
                    else:
                        i = ident_of(p[0], no)
                        if i:
                            pend.fx[i] = resolve_shape(p[1], no)
                elif cmd == "hl":
                    if arg.strip() in ("-", "无", "none"):
                        pend.hl = []
                    else:
                        pend.hl = [i for i in
                                   (ident_of(n, no) for n in re.split(r"[,，、\s]+", arg) if n)
                                   if i]
                else:
                    warn(no, f"未知指令 @{cmd}（跑 --syntax 看全部）")
                continue

            # ---------------------------------------------------- 台词
            c = cast[e["who"]]
            chars = [blank_char() for _ in range(SLOTS)]
            no = e["no"]

            # 1. 退场：这一行它还在台上，钉住不动，标记 appear，行末再移除
            leaving = {}
            for i, ap in pend.exit:
                if i in st.pos:
                    leaving[i] = ap
                else:
                    warn(no, "@exit 的角色不在台上")

            # 2. 入场：只登记，不占位。真正的落位交给下面的统一排布，
            #    否则会跟重排后的目标撞车，角色在数组里互相覆盖。
            entering = {}
            for i, at, ap in pend.enter:
                if i in st.pos:
                    warn(no, "@enter 的角色已经在台上了")
                    continue
                entering[i] = ap
                if at:
                    st.pinned[i] = at
                if i not in seen_order:
                    seen_order.append(i)

            # 3. 镜头计划：本行画面上该有谁。
            #    不在镜的人**直接不写进数组**，编译器会发 #N;hide 让他消失 ——
            #    这就是剪辑。跟 @exit 的进出场动画是两回事：那个表示人离开了房间。
            want = None
            if cam_plan is not None and cam_i < len(cam_plan):
                want = [w for w in cam_plan[cam_i] if w not in leaving]
            cam_i += 1

            # 4. 说话者：立绘角色若还没上台，自动登场
            speaker_ident = None
            if c.get("narrator"):
                speaker = 0
            elif not c.get("portrait"):
                speaker = 0
                chars[0]["name"] = c["id"]
            else:
                speaker_ident = c["id"]
                if speaker_ident not in st.pos and speaker_ident not in entering:
                    # 本场第一个有立绘的说话者直接就位（前面即使有旁白也不淡入）；
                    # 之后的首次入镜才用登场动画，重入镜仍是剪辑。
                    entering[speaker_ident] = (
                        0 if not ever else (3 if speaker_ident not in ever else 0)
                    )
                    if speaker_ident not in seen_order:
                        seen_order.append(speaker_ident)
                ever.add(speaker_ident)

            # 5. 显式走位。角色还没上台就当成"进来时站这儿"
            for i, p in pend.move.items():
                st.pinned[i] = p

            # 6. 统一排布：台上现有的 + 本行入场的，退场的钉住不动
            order = [i for i in seen_order if i in st.pos or i in entering]
            if want is not None:
                # 镜头说了算：不在镜的人从舞台上摘掉（无动画），在镜但不在台上的补进来
                for i in list(st.pos):
                    if i not in want and i not in leaving:
                        st.leave(i)
                        entering.pop(i, None)
                for i in want:
                    if i not in st.pos and i not in entering:
                        entering[i] = 3 if i not in ever else 0
                        if i not in seen_order:
                            seen_order.append(i)
                        ever.add(i)
                order = [i for i in seen_order
                         if (i in want or i in leaving) and (i in st.pos or i in entering)]
            if len(order) > 5:
                drop = order[5:]
                warn(no, f"台上要放 {len(order)} 个立绘，超过 5 个位置，"
                         f"挤掉：{'、'.join(id2name_g.get(d, d) for d in drop)}")
                for d in drop:
                    entering.pop(d, None)
                    st.leave(d)
                order = order[:5]
            target = st.plan(order, hold=set(leaving), entering=set(entering))
            moves = st.apply(target, entering=set(entering))

            if speaker_ident:
                if speaker_ident in moves:
                    speaker = moves[speaker_ident][0]
                else:                       # 被挤掉了，退化成无立绘说话
                    speaker = 0
                    chars[0]["name"] = speaker_ident
                    speaker_ident = None

            # 6. 铺立绘。数组下标 = startingPos
            for i, (src, dst) in moves.items():
                ch = chars[src]
                ch["name"] = i
                ch["startingPos"], ch["endingPos"] = src, dst
                ch["faceId"] = face_state.get(i, "00")
                if i in entering:
                    ch["appear"] = entering[i]
                elif i in leaving:
                    ch["appear"] = leaving[i]
                if i in pend.fx:
                    ch["shapeOverride"] = pend.fx[i]

            # 6. 说话者自己的标注
            if speaker_ident and speaker > 0:
                f = resolve_face(e["face"], speaker_ident, faces, no)
                if f:
                    face_state[speaker_ident] = f
                    chars[speaker]["faceId"] = f
                chars[speaker]["emoticon"] = resolve_emo(e["emo"], emo_sym, emo_cn, no)
                chars[speaker]["action"] = resolve_act(e["act"], act, act_cn, no)
                if e["fx"]:
                    chars[speaker]["shapeOverride"] = resolve_shape(e["fx"], no)
            elif any((e["face"], e["emo"], e["act"], e["fx"])):
                warn(no, f"「{e['who']}」没有立绘，表情/气泡/动作/效果标注被忽略")

            # 7. 高亮：默认台上除说话者外全亮；@hl 可覆盖
            live = set(moves)
            want = live if pend.hl is None else [i for i in pend.hl if i in live]
            hl = sorted({chars_pos(chars, i) for i in want})
            hl = [p for p in hl if p and p != speaker]

            # 自动标注只能给出“谁受击”，这一镜的真实槽位要等排布完成后才能知道。
            # 受击者不在画面上就宁可丢掉；绝不能把射击效果套到错误角色或空槽位。
            shot_raw = []
            for i, shot_no in pend.shot:
                slot = chars_pos(chars, i)
                if i not in live or not slot:
                    warn(shot_no, f"@shot 目标‘{id2name_g.get(i, i)}’不在当前画面，已忽略")
                    continue
                shot_raw.append(f"#{slot};fx;{{shot}}")
            additional_prompt = "\n".join([p for p in (pend.prompt(), *shot_raw) if p])

            scripts.append({
                "$type": T_SCRIPT, "text": e["text"], "popup": pend.popup,
                "bgEffect": bgfx, "bgName": tables.bg_id(bg), "bgFriendlyName": bg,
                "sound": pend.se, "voice": voice_guid(project, next(vseq)),
                "transition": trans, "bgmId": bgm, "selectionGroup": 0,
                "additionalPrompt": additional_prompt,
                "characters": {"$type": T_CLIST, "$values": chars},
                "speakerSlotNum": speaker,
                "highlightedSlotNums": {"$type": T_ILIST, "$values": hl},
                "isDialogScript": True, "placeText": pend.place,
            })

            for i in leaving:
                st.leave(i)
            trans = 0                      # 过渡只作用一行
            pend.reset()

        if scripts:
            enforce_focusline_shots(scripts)
            enforce_persistent_closeups(scripts)
            out.append((sc["title"], scripts))

    return out


def chars_pos(chars, ident):
    for k, c in enumerate(chars):
        if c["name"] == ident:
            return k
    return 0


def wrap_project(scenes, project, preview_bg, bgmap):
    g_exit = str(uuid.uuid5(NS, project + "/exit"))
    guids = [str(uuid.uuid5(NS, f"{project}/scene/{i}")) for i in range(len(scenes))]
    nxt = guids[1:] + [g_exit]

    nodes = [
        {"$type": T_ENTRY, "Title": None, "Header": None,
         "Guid": "00000000-0000-0000-0000-000000000000",
         "ConnectionsTo": {"$type": T_GLIST, "$values": [guids[0] if guids else g_exit]},
         "X": 0.0, "Y": 0.0},
    ]
    for i, ((title, scripts), gid, nid) in enumerate(zip(scenes, guids, nxt)):
        nodes.append({
            "$type": T_SNODE,
            "Scripts": {"$type": T_SLIST, "$values": scripts},
            "NodeName": title or None, "Guid": gid,
            "ConnectionsTo": {"$type": T_GLIST, "$values": [nid]},
            "X": 0.0, "Y": -295.952026 - i * 270.838})
    nodes.append(
        {"$type": T_EXIT, "IsEnding": False, "EndText": "", "NeHeader": "", "NeTitle": "",
         "NeScriptDirty": {
             "$type": T_SCRIPT, "text": "", "popup": "", "bgEffect": 0, "bgName": 0,
             "bgFriendlyName": "", "sound": "", "voice": str(uuid.uuid5(NS, project + "/exitvoice")),
             "transition": 0, "bgmId": 0, "selectionGroup": 0, "additionalPrompt": "",
             "characters": {"$type": T_CLIST, "$values": [blank_char() for _ in range(SLOTS)]},
             "speakerSlotNum": 0,
             "highlightedSlotNums": {"$type": T_ILIST, "$values": []},
             "isDialogScript": False, "placeText": ""},
         "Guid": g_exit, "ConnectionsTo": {"$type": T_GLIST, "$values": []},
         "X": 0.0, "Y": -295.952026 - len(scenes) * 270.838})
    return {"$type": T_PROJ, "ProjectName": project,
            "PreviewBgName": tables.bg_id(preview_bg) if preview_bg else 0,
            "PreviewHeader": None, "PreviewTitle": None,
            "nodes": {"$type": T_NODES, "$values": nodes}}


AUDIO_EXT = (".ogg", ".wav", ".mp3")


def _voice_key(value):
    return str(PureWindowsPath(str(value).replace("/", "\\"))).casefold()


def merge_voice_overrides(manifests, generated):
    """Keep legacy project/save voice registrations and append this run once."""
    merged, seen = [], set()
    for values in [manifest.get("VoiceOverrides", []) for manifest in manifests] + [generated]:
        for value in values:
            text = str(value)
            _voice_relative_components(text)
            key = _voice_key(text)
            if key not in seen:
                merged.append(text)
                seen.add(key)
    return merged


def _voice_relative_components(value):
    relative = PureWindowsPath(str(value).replace("/", "\\"))
    if (
        relative.is_absolute()
        or relative.drive
        or relative.root
        or len(relative.parts) < 2
        or relative.parts[0].casefold() != "voices"
    ):
        raise AssetRegistrationError(f"unsafe VoiceOverrides path: {value!r}")
    try:
        return tuple(
            validate_windows_path_component(part, label="VoiceOverrides path component")
            for part in relative.parts
        )
    except ValueError as exc:
        raise AssetRegistrationError(str(exc)) from exc


def _voice_relative_path(value):
    return Path(*_voice_relative_components(value))


def _voice_destination(root, value):
    """Build an already-resolved safe voice target and prove it stays below root."""
    try:
        destination = destination_within(root, *_voice_relative_components(value))
        destination.relative_to(Path(root).resolve())
    except ValueError as exc:
        raise AssetRegistrationError(str(exc)) from exc
    return destination


def _file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def wire_voices(flat, project, proj_res, src_dir, id2name):
    """导出配音清单，并把已经做好的音频挂上去。

    AA 自己导出的清单格式是  <guid> => [角色] 台词  ——照抄，这样两边能互换。
    挂载支持两种命名：
      <guid>.ogg          直接对上（推荐，重跑也不会错位）
      0001.ogg / 1.wav    按序号对上第 N 条台词（TTS 批量产出常见）
    返回 (清单路径, 挂上的数量, VoiceOverrides 列表)
    """
    vdir = os.path.join(proj_res, "voices")
    os.makedirs(vdir, exist_ok=True)
    lines = []
    for s in flat:
        ch = s["characters"]["$values"][s["speakerSlotNum"]]
        who = id2name.get(ch["name"], ch["name"]) if ch["name"] else "-"
        lines.append(f"{s['voice']} => [{who}] {s['text']}")
    listing = os.path.join(vdir, "voices.txt")
    with open(listing, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    overrides, n = [], 0
    if src_dir and os.path.isdir(src_dir):
        pool = {}
        for fn in os.listdir(src_dir):
            stem, ext = os.path.splitext(fn)
            if ext.lower() in AUDIO_EXT:
                pool[stem] = os.path.join(src_dir, fn)
        by_index = {}
        for stem, p in pool.items():
            if re.fullmatch(r"\d+", stem):
                by_index[int(stem)] = p
        for i, s in enumerate(flat):
            src = pool.get(s["voice"]) or by_index.get(i) or by_index.get(i + 1)
            if not src:
                continue
            ext = os.path.splitext(src)[1].lower()
            shutil.copy2(src, os.path.join(vdir, s["voice"] + ext))
            overrides.append(f"voices/{s['voice']}{ext}")
            n += 1
        extra = len(pool) - n
        if extra > 0:
            warn(0, f"配音目录里有 {extra} 个文件没对上任何台词（命名要么用 guid，要么用序号）")
    return listing, n, overrides


def finalize_project_manifest(
    cast,
    used,
    *,
    story_root,
    project_dir,
    voice_overrides,
    mirror_dir=None,
    character_target=None,
):
    """Merge generated records, optionally keeping an install mirror identical."""
    project = os.path.abspath(project_dir)
    os.makedirs(project, exist_ok=True)
    directories = (project, os.path.abspath(mirror_dir)) if mirror_dir else (project,)
    if mirror_dir:
        os.makedirs(directories[1], exist_ok=True)

    for c in cast.values():
        identifier = str(c.get("id") or "")
        if c.get("narrator") or identifier not in used or not c.get("custom"):
            continue
        custom = c["custom"]
        source = custom["src"].replace("/", os.sep)
        if not os.path.isabs(source):
            source = os.path.join(story_root, source)
        validation = validate_spine(
            os.path.join(source, custom["asset"]),
            identifier=identifier,
        )
        registration = register_character_unlocked if character_target else register_character
        registration(
            validation,
            character_target or project,
            display_name=c.get("name", ""),
            nickname=c.get("club", ""),
        )

    manifests = [load_manifest(directory) for directory in directories]
    by_identifier = [
        {str(row.get("Identifier", "")): row for row in manifest["CharacterOverrides"]}
        for manifest in manifests
    ]
    for c in cast.values():
        identifier = str(c.get("id") or "")
        if (
            c.get("narrator")
            or identifier not in used
            or not c.get("name")
            or (
                c.get("portrait")
                and not c.get("custom")
                and not c.get("spine_signature")
            )
        ):
            continue
        row = {
            "Identifier": identifier,
            "Name": c.get("name", ""),
            "Nickname": c.get("club", ""),
            "CharacterReference": None,
            "OriginalIdentifier": None,
            "SpinePortraitPath": None,
            "SmallPortraitPath": None,
        }
        for manifest, known in zip(manifests, by_identifier):
            existing = known.get(identifier)
            if existing is None:
                manifest["CharacterOverrides"].append(row.copy())
                known[identifier] = row
                continue
            existing["Name"] = row["Name"]
            if row["Nickname"]:
                existing["Nickname"] = row["Nickname"]

    merged_voices = merge_voice_overrides(manifests, voice_overrides)
    for manifest in manifests:
        manifest["VoiceOverrides"] = list(merged_voices)
    for directory, manifest in zip(directories, manifests):
        write_manifest_atomic(directory, manifest)
    return manifests[0]


# ---------------------------------------------------------------- 主流程
def write_project_resource_index(project_dir, index):
    """Persist the exact build allowlist in the generated project's own scope."""
    project = Path(project_dir)
    project.mkdir(parents=True, exist_ok=True)
    target = project / "aa_resources.json"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="aa_resources.", suffix=".tmp", dir=str(project)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(index, output, ensure_ascii=False, indent=2, sort_keys=True)
            output.write("\n")
        json.loads(temporary.read_text(encoding="utf-8"))
        os.replace(temporary, target)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target


def _snapshot_tree(root):
    """Capture only the target tree so a failed install can restore it exactly."""
    root = Path(root)
    if not root.exists():
        return False, {}, set()
    files = {}
    directories = {Path(".")}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if path.is_dir():
            directories.add(relative)
        elif path.is_file():
            files[relative] = path.read_bytes()
    return True, files, directories


def _restore_tree(root, snapshot):
    existed, files, directories = snapshot
    root = Path(root)
    if not existed:
        if root.exists():
            shutil.rmtree(root)
        return
    root.mkdir(parents=True, exist_ok=True)
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        relative = path.relative_to(root)
        if path.is_file() and relative not in files:
            path.unlink()
        elif path.is_dir() and relative not in directories:
            try:
                path.rmdir()
            except OSError:
                pass
    for relative in sorted(directories, key=lambda item: len(item.parts)):
        if relative != Path("."):
            (root / relative).mkdir(parents=True, exist_ok=True)
    for relative, contents in files.items():
        destination = root / relative
        if destination.is_dir():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(contents)


def _snapshot_file(path):
    path = Path(path)
    return path.read_bytes() if path.is_file() else None


def _restore_file(path, contents):
    path = Path(path)
    if contents is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)


@contextmanager
def install_transaction(target: AAProjectTarget, *, aap_path, running_probe=None):
    """Hold the canonical project/save lock and roll back every install write."""
    with project_target_lock(target):
        assert_aa_closed(running_probe=running_probe)
        snapshots = {
            target.project_dir: _snapshot_tree(target.project_dir),
            target.save_dir: _snapshot_tree(target.save_dir),
        }
        aap_snapshot = _snapshot_file(aap_path)
        try:
            yield
        except Exception:
            for directory, snapshot in snapshots.items():
                _restore_tree(directory, snapshot)
            _restore_file(aap_path, aap_snapshot)
            raise


def _reconcile_voice_files(project_dir, save_dir, voice_overrides):
    """Make every registered voice available identically in both install mirrors."""
    for value in voice_overrides:
        source = _voice_destination(project_dir, value)
        destination = _voice_destination(save_dir, value)
        if source.is_file() and destination.is_file():
            if _file_sha256(source) != _file_sha256(destination):
                raise AssetRegistrationError(f"voice mirror content differs: {value}")
        elif source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        elif destination.is_file():
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, source)


def write_aap_atomic(path, payload):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, ensure_ascii=False, separators=(",", ":"))
        json.loads(temporary.read_text(encoding="utf-8"))
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def compile_script(options: dict, *, running_probe=None) -> dict:
    """剧本编译纯函数接口（剥离 sys.argv 与全局状态）"""
    script_path = options["script"]
    out_name = options.get("out")
    cast_path = options.get("cast") or os.path.join(HERE, "cast.json")
    index_path = options.get("index") or os.path.join(HERE, "aa_resources.json")
    aa_data = options.get("aa_data")
    install = options.get("install", False)
    voices = options.get("voices")
    dry_run = options.get("dry_run", False)

    if install:
        unresolved_backgrounds = collect_background_requests(Path(script_path))
        if unresolved_backgrounds:
            raise UnresolvedBackgroundError(unresolved_backgrounds)

    P = aapaths.require(aa_data)
    aa_data = aa_data or P["data"]

    cfg, cast, id2name = load_cast(cast_path)
    build_index = json.load(open(index_path, encoding="utf-8"))
    project = validate_windows_path_component(
        out_name or os.path.splitext(os.path.basename(script_path))[0],
        label="project name",
    )
    story_root = os.path.dirname(os.path.dirname(HERE))
    install_target = None
    outdir = os.path.join(aa_data, "projects") if install else os.path.join(HERE, "out")
    proj_res = os.path.join(outdir, project)
    if install:
        install_target = resolve_project_target(
            Path(aa_data) / "projects" / project,
            saves_root=Path(aa_data) / "saves",
        )
        outdir = str(install_target.project_dir.parent)
        proj_res = str(install_target.project_dir)
    aap = os.path.join(outdir, project + ".aap")
    transaction = (
        install_transaction(install_target, aap_path=aap, running_probe=running_probe)
        if install and not dry_run
        else nullcontext()
    )

    with transaction:
        idx = merge_project_registered_assets(build_index, proj_res)
        events = parse_script(script_path, cast)
        scenes = build(events, cfg, cast, idx, project)
        flat = [s for _, ss in scenes for s in ss]

        used = set()
        for s in flat:
            for c in s["characters"]["$values"]:
                if c["name"]:
                    used.add(c["name"])

        first_bg = flat[0]["bgFriendlyName"] if flat else cfg.get("default_bg", "BG_Black")
        proj = wrap_project(scenes, project, first_bg, idx.get("bg", {}))
        spk = {}
        for s in flat:
            n = s["characters"]["$values"][s["speakerSlotNum"]]["name"]
            n = id2name.get(n, n) if n else "（旁白）"
            spk[n] = spk.get(n, 0) + 1
        nmove = sum(1 for s in flat for c in s["characters"]["$values"] if c["name"] and c["startingPos"] != c["endingPos"])
        nap = sum(1 for s in flat for c in s["characters"]["$values"] if c["appear"])
        nfx = sum(1 for s in flat for c in s["characters"]["$values"] if c["shapeOverride"])
        nemo = sum(1 for s in flat for c in s["characters"]["$values"] if c["emoticon"] >= 0)
        nact = sum(1 for s in flat for c in s["characters"]["$values"] if c["action"])

        print(f"剧本      {script_path}")
        print(f"工程名    {project}")
        print(f"场景/节点 {len(scenes)}     对白行数 {len(flat)}")
        for title, ss in scenes:
            print(f"    · {title or '（无标题）':<24} {len(ss):>4} 行   {ss[0]['bgFriendlyName']}")
        print(f"登场角色  {len(used)}  ->  {'、'.join(sorted(id2name.get(u, u) for u in used))}")
        print("台词分布  " + "  ".join(f"{k}:{v}" for k, v in sorted(spk.items(), key=lambda x: -x[1])))
        print(f"演出      走位 {nmove}  进出场 {nap}  气泡 {nemo}  动作 {nact}  效果 {nfx}"
              f"  额外指令 {sum(1 for s in flat if s['additionalPrompt'])}"
              f"  地点卡 {sum(1 for s in flat if s['placeText'])}")
        if warn.items:
            print(f"\n警告 {len(warn.items)} 条：")
            for no, msg in warn.items[:25]:
                print(f"  第{no}行  {msg}" if no else f"  {msg}")
            if len(warn.items) > 25:
                print(f"  …还有 {len(warn.items)-25} 条")

        if dry_run:
            print("\n[dry-run] 未写文件")
            return {
                "events": events,
                "diagnostics": [],
                "project": project,
                "project_dir": proj_res,
                "aap_file": aap,
            }

        if install_target:
            merge_voice_overrides(
                [load_manifest(install_target.project_dir), load_manifest(install_target.save_dir)],
                [],
            )
        os.makedirs(outdir, exist_ok=True)
        os.makedirs(proj_res, exist_ok=True)
        listing, nvoice, vov = wire_voices(flat, project, proj_res, voices, id2name)
        if install_target:
            vov = merge_voice_overrides(
                [load_manifest(install_target.project_dir), load_manifest(install_target.save_dir)],
                vov,
            )
            _reconcile_voice_files(install_target.project_dir, install_target.save_dir, vov)
        man = finalize_project_manifest(
            cast,
            used,
            story_root=story_root,
            project_dir=proj_res,
            voice_overrides=vov,
            mirror_dir=install_target.save_dir if install_target else None,
            character_target=install_target,
        )
        write_project_resource_index(proj_res, idx)
        write_aap_atomic(aap, proj)

        print(f"\n已写出  {aap}")
        print(f"        {os.path.join(proj_res, 'manifest.json')}  ({len(man['CharacterOverrides'])} 个角色覆盖)")
        print(f"        {listing}  ({len(flat)} 条配音槽" +
              (f"，已挂上 {nvoice} 个音频)" if nvoice else "，还没有音频)"))

        return {
            "events": events,
            "diagnostics": [],
            "project": project,
            "project_dir": proj_res,
            "aap_file": aap,
        }


def main(argv=None, *, running_probe=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("script", nargs="?")
    ap.add_argument("-o", "--out")
    ap.add_argument("--cast", default=os.path.join(HERE, "cast.json"))
    ap.add_argument("--index", default=os.path.join(HERE, "aa_resources.json"))
    ap.add_argument("--aa-data", help="AA 存储目录（不给就自动探测）")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--voices", help="配音音频目录，会拷进工程并登记")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--syntax", action="store_true", help="打印剧本语法说明")
    a = ap.parse_args(argv)

    if a.syntax:
        print(SYNTAX)
        return
    if not a.script:
        ap.error("要给剧本文件（或者用 --syntax 看语法）")

    opts = {
        "script": a.script,
        "out": a.out,
        "cast": a.cast,
        "index": a.index,
        "aa_data": a.aa_data,
        "install": a.install,
        "voices": a.voices,
        "dry_run": a.dry_run,
    }
    compile_script(opts, running_probe=running_probe)


if __name__ == "__main__":
    main()
