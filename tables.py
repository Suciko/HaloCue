# -*- coding: utf-8 -*-
"""
AA 的资源 ID 对照表与哈希。

来源与可信度：
  transition —— 从 GameAssembly.dll 的 Studio.Scripts.EnvProp.TransitionProp::Init()
                反汇编出来的 61 条 Dictionary.Add(name, id)。工程里出现的 29 个值 100% 命中。
                UI 上那 4 个按钮是分组，本地化 CSV 证实：
                  fade=淡入淡出  fadeWhite=淡入淡出（白）  crossfade=交叉渐变  specialTransition=特殊
                注：这一项的独立复核 agent 因连接中断没跑完，属于单源结论。
  bgEffect   —— 从 flatdata_assets_all.bundle 里的 ScenarioBGEffectExcel 解密得到，
                35 个名字全部对应 catalog 里真实存在的 UI_FX_<name>.prefab（已复核）。
  bgName     —— xxHash32(utf8(友好名), seed=0)。579 组实测命中 577，
                两个未命中是大小写漂移（SunSet/Sunset）。已复核。
"""

# ---------------------------------------------------------------- xxHash32
_P1, _P2, _P3, _P4, _P5 = 2654435761, 2246822519, 3266489917, 668265263, 374761393
_M = 0xFFFFFFFF


def _rotl(x, r):
    return ((x << r) | (x >> (32 - r))) & _M


def xxh32(data, seed=0):
    if isinstance(data, str):
        data = data.encode("utf-8")
    n, i = len(data), 0
    if n >= 16:
        v = [(seed + _P1 + _P2) & _M, (seed + _P2) & _M, seed & _M, (seed - _P1) & _M]
        while i <= n - 16:
            for j in range(4):
                k = int.from_bytes(data[i:i + 4], "little")
                i += 4
                x = (v[j] + k * _P2) & _M
                v[j] = (_rotl(x, 13) * _P1) & _M
        h = (_rotl(v[0], 1) + _rotl(v[1], 7) + _rotl(v[2], 12) + _rotl(v[3], 18)) & _M
    else:
        h = (seed + _P5) & _M
    h = (h + n) & _M
    while i <= n - 4:
        h = (h + int.from_bytes(data[i:i + 4], "little") * _P3) & _M
        h = (_rotl(h, 17) * _P4) & _M
        i += 4
    while i < n:
        h = (h + data[i] * _P5) & _M
        h = (_rotl(h, 11) * _P1) & _M
        i += 1
    h ^= h >> 15
    h = (h * _P2) & _M
    h ^= h >> 13
    h = (h * _P3) & _M
    h ^= h >> 16
    return h


def bg_id(friendly_name):
    """背景友好名 -> bgName。算得出来就不用查表了，新背景也能直接用。"""
    return xxh32(friendly_name)


# ---------------------------------------------------------------- 过渡
TRANSITION = {
    "None": 0,
    "Fade 250 >> 250": 1408872282, "Fade 500 >> 500": 2130373248,
    "Fade 1000 >> 1000": 1122508889, "Fade 1500 >> 1500": 509674679,
    "Fade 2000 >> 2000": 2482233134, "Fade 2500 >> 2500": 1606908815,
    "Fade 3000 >> 3000": 2752031158, "Fade 4000 >> 4000": 1238175709,
    "Fade 5000 >> 5000": 3411222921,
    "Fade >> 4000": 259497043, "Fade 4000 >>": 1272583944,
    "Fade >> 3000": 3222392982, "Fade 3000 >>": 3174465279,
    "Fade >> 2000": 2457385855, "Fade 2000 >>": 2243764445,
    "Fade >> 1500": 2127590351, "Fade 1500 >>": 4203358158,
    "Fade >> 1000": 2136104277, "Fade 1000 >>": 348351892,
    "Fade >> 500": 1974926776, "Fade 500 >>": 2046503352,
    "Fade >> 250": 326824049, "Fade 250 >>": 2089682509,
    "Fade White 250 >> 250": 3868567233, "Fade White 500 >> 500": 2246884625,
    "Fade White 1000 >> 1000": 3182852162, "Fade White 1500 >> 1500": 1289388507,
    "Fade White 2000 >> 2000": 3785883235, "Fade White 2500 >> 2500": 3181383424,
    "Fade White 3000 >> 3000": 1346493585, "Fade White 4000 >> 4000": 4075662009,
    "Fade White 5000 >> 5000": 3539052749,
    "Fade White >> 4000": 3765959531, "Fade White 4000 >>": 429693191,
    "Fade White >> 3000": 2259711251, "Fade White 3000 >>": 3657480713,
    "Fade White >> 2000": 2527144513, "Fade White 2000 >>": 704731093,
    "Fade White >> 1500": 457377075, "Fade White 1500 >>": 2160391595,
    "Fade White >> 1000": 1626584722, "Fade White 1000 >>": 2878370298,
    "Fade White >> 500": 3977094957, "Fade White 500 >>": 42187309,
    "Crossfade 200 >>": 375948222, "Crossfade 300 >>": 4187997050,
    "Crossfade 500 >>": 3854440696, "Crossfade 1000 >>": 4004024664,
    "Crossfade 1500 >>": 1173843909, "Crossfade 2000 >>": 1369285246,
    "Crossfade 2500 >>": 3054018111, "Crossfade 3000 >>": 1027503790,
    "Crossfade 3500 >>": 3196842123, "Crossfade 4000 >>": 2091508330,
    "Swipe R": 1127535352, "Swipe L": 3957412172,
    "Swipe D": 3029168926, "Swipe U": 4152299906,
    "Noise": 3344317924, "Circle": 1914875660,
}

# 中文简写 -> 英文名模板。写 "淡入淡出" 默认 1000ms，写 "淡入淡出 2000" 取 2000。
TRANS_CN = {
    "无": ("None", None), "淡入淡出": ("Fade {d} >> {d}", 1000),
    "淡出": ("Fade {d} >>", 1000), "淡入": ("Fade >> {d}", 1000),
    "白淡入淡出": ("Fade White {d} >> {d}", 1000),
    "淡入淡出白": ("Fade White {d} >> {d}", 1000),
    "白淡出": ("Fade White {d} >>", 1000), "白淡入": ("Fade White >> {d}", 1000),
    "交叉渐变": ("Crossfade {d} >>", 1000), "叠化": ("Crossfade {d} >>", 1000),
    "右扫": ("Swipe R", None), "左扫": ("Swipe L", None),
    "下扫": ("Swipe D", None), "上扫": ("Swipe U", None),
    "噪点": ("Noise", None), "圆形": ("Circle", None),
}
TRANS_GROUPS = {"淡入淡出": "Fade", "淡入淡出（白）": "Fade White",
                "交叉渐变": "Crossfade", "特殊": "Special"}


def resolve_transition(tok):
    """接受：英文全名 / 中文简写[+时长] / 纯数字 ID。返回 (值, 错误说明)。"""
    if not tok:
        return 0, None
    t = str(tok).strip()
    if t.isdigit():
        return int(t), None
    if t in TRANSITION:
        return TRANSITION[t], None
    parts = t.replace("　", " ").split()
    head = parts[0]
    if head in TRANS_CN:
        tpl, default_d = TRANS_CN[head]
        if default_d is None:
            return TRANSITION.get(tpl, 0), None
        d = default_d
        if len(parts) > 1 and parts[1].isdigit():
            d = int(parts[1])
        name = tpl.format(d=d)
        if name in TRANSITION:
            return TRANSITION[name], None
        avail = sorted({int(k.split()[-1]) for k in TRANSITION
                        if k.startswith(tpl.split("{")[0].strip()) and k.split()[-1].isdigit()})
        return 0, f"「{head}」没有 {d}ms 这一档，可用：{avail}"
    return 0, (f"未知过渡「{t}」。中文可写：{'、'.join(list(TRANS_CN)[:8])}…；"
               f"英文全名见 tables.TRANSITION")


# ---------------------------------------------------------------- 背景效果
BGEFFECT = {
    "None": 0,
    "BG_Dust_L": 1377724294, "BG_FocusLine": 3550865647, "BG_Mist_L": 2728481130,
    "BG_UnderFire": 3134544579, "BG_UnderFire_R": 2313116516,
    "BG_Filter_Red": 4006301275, "BG_Filter_Red_BG": 2174743540,
    "BG_Ash_Black": 3934311147, "BG_Ash_Red": 736631543,
    "BG_Shining_L": 1061522909, "BG_Shining_L_BGOff": 1870781268,
    "BG_Love_L": 1679852157, "BG_Love_L_BGOff": 3023046476,
    "BG_Flash": 786952175, "BG_Flash_Sound": 1566732214,
    "BG_Teleport": 880081110,
    "BG_Rain_L": 3676184657, "BG_Snow_L": 2675527592,
    "BG_SandStorm_L": 575794762,
    "BG_Wave_F": 866423043, "BG_WaveShort_F": 3610115052,
    "BG_ScrollL_1.0": 176581582, "BG_ScrollR_1.0": 442565896,
    "BG_ScrollB_0.5": 1488006201,
    "BG_Fireworks_L_BGOff_01": 2551519896, "BG_Fireworks_L_BGOff_02": 2499688462,
}

# 中文别名。含义来自资源依赖（贴图/材质/音效）反推，已复核。
BGFX_CN = {
    "无": "None", "烟尘": "BG_Dust_L", "扬尘": "BG_Dust_L",
    "集中线": "BG_FocusLine", "速度线": "BG_FocusLine",
    "烟雾": "BG_Mist_L", "雾": "BG_Mist_L", "朦胧": "BG_Mist_L", "烟感": "BG_Mist_L",
    "枪战": "BG_UnderFire", "被射击": "BG_UnderFire",
    "红滤镜": "BG_Filter_Red", "危机": "BG_Filter_Red",
    "黑灰": "BG_Ash_Black", "灰烬": "BG_Ash_Black",
    "红灰": "BG_Ash_Red",
    "闪光": "BG_Shining_L", "闪光无背景": "BG_Shining_L_BGOff",
    "爱心": "BG_Love_L", "爱心无背景": "BG_Love_L_BGOff",
    "闪白": "BG_Flash", "闪电": "BG_Flash_Sound",
    "传送": "BG_Teleport", "雨": "BG_Rain_L", "雪": "BG_Snow_L",
    "沙尘暴": "BG_SandStorm_L", "水波": "BG_Wave_F", "短水波": "BG_WaveShort_F",
    "烟花": "BG_Fireworks_L_BGOff_01",
}


def resolve_bgeffect(tok):
    if not tok:
        return 0, None
    t = str(tok).strip()
    if t.isdigit():
        return int(t), None
    if t in BGEFFECT:
        return BGEFFECT[t], None
    if t in BGFX_CN:
        return BGEFFECT[BGFX_CN[t]], None
    return 0, f"未知背景效果「{t}」。中文可写：{'、'.join(list(BGFX_CN)[:12])}…"


# ---------------------------------------------------------------- 自动等待
# 编译器会自己插 #wait，规则（134 组配对实测）：
#   有 emoticon              -> #wait;2500   命中 4552/4643 = 98%
#   无 emoticon 但有位移/进出场/动作 -> #wait;1500   命中 1179/1331 = 89%
#   都没有                    -> 不插
# 作者写的 #wait 是**覆盖**不是叠加（119/119）。所以别到处乱加 @wait，
# 只在想改默认时长时才写。
AUTO_WAIT_EMOTICON = 2500
AUTO_WAIT_MOTION = 1500


def implicit_wait(ch_records):
    """给一行的 characters 记录，算编译器会自动插多长的 wait（0 = 不插）。"""
    has_emo = any(c.get("name") and c.get("emoticon", -1) >= 0 for c in ch_records)
    if has_emo:
        return AUTO_WAIT_EMOTICON
    has_motion = any(c.get("name") and (c.get("appear") or c.get("action") or
                                        c.get("startingPos") != c.get("endingPos"))
                     for c in ch_records)
    return AUTO_WAIT_MOTION if has_motion else 0


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    assert xxh32(b"") == 0x02CC5D05
    assert xxh32(b"a") == 0x550D7456
    print("xxh32 自检通过")
    for s in ("BG_Black", "BG_ShoppingDistrict", "BG_GameDevRoom"):
        print(f"  {s:<24} -> {bg_id(s)}")
    for t in ("淡入淡出", "淡入淡出 2000", "白淡入淡出", "交叉渐变 500", "噪点", "Fade 1500 >> 1500"):
        print(f"  过渡 {t:<20} -> {resolve_transition(t)}")
    for t in ("集中线", "雨", "红滤镜", "BG_Dust_L"):
        print(f"  背景效果 {t:<12} -> {resolve_bgeffect(t)}")
