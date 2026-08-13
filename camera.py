# -*- coding: utf-8 -*-
"""
镜头切换：决定每一行画面上显示哪些角色。

背景不变、画面里的人变 —— 这是 galgame 多人戏能不能看的关键。
在 AA 里，一行的立绘名单换了，上一行有本行没有的人会被编译器自动隐藏
（#N;hide，1752/1756 实测），所以换名单就是剪辑，不需要进出场动画。

规则最初从 131 个 AA 人工工程、18089 行反推。以下是 AA 人工工程基线，
不是官方游戏命令流的分布：
    同屏 0人 23.4%  1人 38.0%  2人 24.7%  3人 12.1%  4人 1.3%  5人 0.6%
    镜头长度中位数约 3 行，平均 6.1 行，共 2963 次切

四条规则（在 AA 人工工程基线序列上逐条对过）：

  R1 新面孔第一次开口，且当前镜头已经端了一阵子 -> 硬切成单人镜头
     让观众看清是谁。第 15 行柚子（镜头端了 9 行）切了，第 21 行爱丽丝
     （端了 3 行）切了，第 23 行凯伊（才端了 1 行）没切。所以门槛在 3 行。

  R2 太久没说话的人下镜
     第 26 行桃井说话时爱丽丝被拿掉，她上一次开口是 3 行前。

  R3 同屏上限 3 人，满了就踢最久没说话的
     4 人以上在真实用法里只占 1.9%。

  R4 连续旁白就退空镜
     AA 人工工程基线里"同屏 0 人"占 23.4%，而且**只出现在旁白/无立绘行**
     （立绘角色说话时同屏必有人，8036/8036 零例外）。
     旁白行里 42.1% 是空镜。单独一行旁白不清（那是对话中间的插叙），
     连着两行以上就说明镜头离开人物了，退到只剩背景。
"""

DEFAULTS = {
    "max_on_cam": 4,      # 同屏上限（硬上限 5）。参数扫描出来 4 最贴近 AA 人工基线
    "new_face_hold": 3,   # 新面孔触发硬切所需的"当前镜头已保持行数"
    "stale_after": 6,     # 多少行没说话就下镜
    "min_solo": 1,        # 镜头里至少留几个人（旁白行除外）
    "narration_clear": 0,  # 空镜必须由显式演出决定；0 = 不因旁白自动清空
}


def plan_camera(lines, opts=None):
    """
    lines: [{"speaker": str|None, "text": str, "is_narration": bool}, ...]
           speaker 是立绘角色标识；旁白和无立绘角色为 None
    返回:  [list[str], ...]  与 lines 等长，每项是该行画面上显示的角色，
           按屏幕从左到右排列
    """
    o = dict(DEFAULTS)
    o.update(opts or {})
    MAX = max(1, int(o["max_on_cam"]))
    NEW_HOLD = int(o["new_face_hold"])
    STALE = int(o["stale_after"])

    NARR = int(o["narration_clear"])

    # 先算出每一行往后连着几行旁白 —— 用来判断"这是插叙还是镜头真的离开了"
    runs = [0] * len(lines)
    r = 0
    for i in range(len(lines) - 1, -1, -1):
        r = r + 1 if not lines[i].get("speaker") else 0
        runs[i] = r

    cam = []                 # 当前在镜，保持左右顺序
    last_spoke = {}          # ident -> 最后开口的行号
    seen = set()             # 已经登场过的
    held = 0                 # 当前镜头已保持几行
    out = []

    for i, ln in enumerate(lines):
        if ln.get("scene_break"):
            cam = []
            held = 0
        sp = ln.get("speaker")

        if "visible_characters" in ln and isinstance(ln["visible_characters"], (list, tuple)):
            before = list(cam)
            cam = list(dict.fromkeys(
                str(name) for name in ln["visible_characters"] if str(name)
            ))[:5]
            seen.update(cam)
            if sp:
                seen.add(sp)
                last_spoke[sp] = i
            held = 1 if cam != before else held + 1
            out.append(list(cam))
            continue

        # 旁白 / 无立绘角色
        if not sp:
            # 连着两行以上旁白 = 镜头离开人物，退空镜。
            # 只有一行的话是对话中间的插叙，画面不动。
            if NARR and runs[i] >= NARR and cam:
                cam = []
                held = 1
            else:
                held += 1
            out.append(list(cam))
            continue

        before = list(cam)
        first_time = sp not in seen
        seen.add(sp)

        if first_time and cam and held >= NEW_HOLD:
            # R1 新面孔亮相：硬切单人
            cam = [sp]
        elif sp in cam:
            # 说话者已经在镜：镜头基本不动，只做**渐进收缩** ——
            # 超过 2 人时，每行最多请走一个太久没说话的。
            # 完全不收缩的话镜头会一路填满再也不下来（4 人占比会飙到 24%，
            # AA 人工基线只有 1.3%）；每行全清会让平均镜头长掉到 3 行（基线 6.1）。
            # 两害相权，一次一个。
            if len(cam) > 2:
                stale = [c for c in cam
                         if c != sp and (i - last_spoke.get(c, i)) >= STALE]
                if stale:
                    cam.remove(min(stale, key=lambda c: last_spoke.get(c, -1)))
        else:
            # R2 + R3 说话者要入镜。先清掉太久没说话的腾位置，还不够就踢最久的。
            if len(cam) >= MAX:
                cam = [c for c in cam if (i - last_spoke.get(c, i)) < STALE] or cam
            cam.append(sp)
            while len(cam) > MAX:
                victim = min((c for c in cam if c != sp),
                             key=lambda c: last_spoke.get(c, -1), default=None)
                if victim is None:
                    break
                cam.remove(victim)

        last_spoke[sp] = i
        held = 1 if cam != before else held + 1
        out.append(list(cam))

    return out


# ---------------------------------------------------------------- 自测
def profile(shots):
    """算出同屏人数分布与镜头长度分布，用来跟 AA 人工工程基线比。"""
    from collections import Counter
    size = Counter(len(s) for s in shots)
    lens, cuts = Counter(), 0
    prev, run = None, 0
    for s in shots:
        cur = frozenset(s)
        if prev is None or cur == prev:
            run += 1
        else:
            lens[run] += 1
            cuts += 1
            run = 1
        prev = cur
    if run:
        lens[run] += 1
    n = sum(size.values())
    return {
        "size_pct": {k: round(v * 100 / n, 1) for k, v in sorted(size.items())},
        "cuts": cuts,
        "lines": n,
        "avg_shot": round(n / max(cuts, 1), 1),
        "len_cum": _cum(lens),
    }


def _cum(lens):
    tot = sum(lens.values())
    acc, out = 0, {}
    for k in sorted(lens):
        acc += lens[k]
        out[k] = round(acc * 100 / tot, 1)
    return out


GOLD = {
    "size_pct": {0: 23.4, 1: 38.0, 2: 24.7, 3: 12.1, 4: 1.3, 5: 0.6},
    "len_cum": {1: 25.5, 2: 42.9, 3: 55.2, 4: 63.7, 5: 70.2, 6: 76.2, 8: 82.9},
    "avg_shot": 6.1,
}


def compare(p):
    out = ["            本算法    AA人工基线"]
    for k in range(6):
        a = p["size_pct"].get(k, 0.0)
        b = GOLD["size_pct"].get(k, 0.0)
        flag = "  " if abs(a - b) <= 8 else " ←"
        out.append(f"  同屏 {k} 人   {a:5.1f}%   {b:5.1f}%{flag}")
    out.append(f"  平均镜头长  {p['avg_shot']:5.1f} 行 {GOLD['avg_shot']:5.1f} 行（AA人工基线）")
    out.append(f"  切换次数    {p['cuts']}  ({p['lines']} 行)")
    out.append("  镜头长度累计分布：")
    for k in (1, 2, 3, 4, 6):
        a = p["len_cum"].get(k)
        near = min((x for x in p["len_cum"] if x >= k), default=None)
        a = p["len_cum"].get(k, p["len_cum"].get(near, 0)) if a is None else a
        out.append(f"    {k} 行以内 {a:5.1f}%   AA人工基线 {GOLD['len_cum'].get(k, 0):5.1f}%")
    return "\n".join(out)


if __name__ == "__main__":
    import json, os, re, sys
    sys.stdout.reconfigure(encoding="utf-8")
    HERE = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, HERE)
    from script2aap import HEAD_RE, split_head, load_cast

    script = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(HERE)), "第一节剧本试运行_节奏最终优化版.txt")
    castf = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "cast.json")
    _, cast, id2name = load_cast(castf)

    lines = []
    for raw in open(script, encoding="utf-8").read().splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("@"):
            continue
        m = HEAD_RE.match(s)
        if not m:
            continue
        who, *_ = split_head(m.group("head"), cast)
        if who not in cast:
            continue
        c = cast[who]
        sp = c["id"] if (c.get("portrait") and not c.get("narrator")) else None
        lines.append({"speaker": sp, "text": m.group("text"),
                      "is_narration": sp is None})

    shots = plan_camera(lines)
    print(f"剧本 {os.path.basename(script)}   {len(lines)} 行\n")
    print(compare(profile(shots)))

    N = {v: k for k, v in id2name.items()} if False else id2name
    print("\n前 40 行镜头序列：")
    prev = None
    for i, (ln, sh) in enumerate(zip(lines, shots), 1):
        if i > 40:
            break
        who = N.get(ln["speaker"], ln["speaker"]) if ln["speaker"] else "旁白"
        names = "、".join(N.get(x, x) for x in sh) or "（空）"
        cut = "  ✂" if prev is not None and set(sh) != set(prev) else ""
        print(f"  [{i:>3}] {who:<5}｜{names}{cut}")
        prev = sh
