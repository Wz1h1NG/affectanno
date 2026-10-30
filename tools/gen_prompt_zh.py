# -*- coding: utf-8 -*-
"""为每个 request 生成六段式中文 prompt（与英文模板逐句对应）。"""
import glob, json, os, re, sys

B = "/public_hw/share/cit_ztyu/zehengW/emotion_edit_pilot_20261029"
OUT = "/public_hw/share/cit_ztyu/zehengW/prompt_zh.json"

ZH = {
  "neutral": dict(
    name="中性",
    face="面部肌肉放松，眉与下颌没有紧张感，双唇自然平放，目光平视而平静",
    posture="", motion="",
    light="平坦均匀的中性主光，没有强烈的阴影衰减",
    color="中性白平衡，中等饱和度，中等对比度",
    particles="",
    time="固定机位，无手持晃动，速度恒定，不推不拉",
    objects={}),
  "happy": dict(
    name="喜悦",
    face="嘴角上扬，面颊抬起并在眼角外侧挤出笑纹，下眼睑轻微收紧，下颌放松向上",
    posture="", motion="动作变得轻快，手势向外打开",
    light="暖色主光，低光比，柔和的高光，温和的补光",
    color="向暖琥珀至橙色偏移，饱和度提高，肤色透亮",
    particles="",
    time="轻微而稳定的推近，细微自然的机位轻晃，节奏轻快",
    objects={"scattered warm sunlight patches":"散落的暖色阳光斑块",
             "a few soft floating light specks":"少量柔和漂浮的光尘"}),
  "sad": dict(
    name="悲伤",
    face="内眉上扬并靠拢，上眼睑下垂，嘴角下撇，下唇轻微颤动，视线低垂并变得柔和",
    posture="双肩前塌，头部低垂，身体内收", motion="",
    light="柔和冷光，低对比，阴影提升，高光压低",
    color="去饱和的冷蓝灰色调，整体褪色",
    particles="空气中悬浮着一层薄雾或微弱飘动的尘埃",
    time="极慢或固定的机位，几乎察觉不到的向下漂移",
    objects={"a few dry fallen leaves drifting past":"几片干枯的落叶飘过",
             "faint condensation on nearby surfaces":"附近表面上淡淡的凝结水汽"}),
  "angry": dict(
    name="愤怒",
    face="内眉下压并靠拢，鼻翼张开，下颌前顶、咬肌绷紧，眼睑收窄成锐利而固定的目光",
    posture="脊背挺直并前倾，双肩张开，拳头握紧", motion="",
    light="强烈的侧向硬光，高对比，深重的暗部压黑",
    color="红色通道增强，饱和度提高，暗部偏冷、亮点偏暖",
    particles="",
    time="快速向主体推近，明显的手持抖动",
    objects={"a faint red pulse of light washing the background":"背景上泛起一层微弱的红色光脉冲",
             "fine dust or smoke curling in the hard light":"硬光中翻卷的细尘或烟雾"}),
  "surprise": dict(
    name="惊讶",
    face="眉毛向上挑起，眼睑睁大露出虹膜上方的眼白，下颌微微张开，表情凝固一拍",
    posture="", motion="",
    light="主光突然增亮形成亮斑，对比度提高，高光炽亮",
    color="略微去饱和同时高光提亮，呈漂白感",
    particles="",
    time="短暂而锐利的加速，随后凝固静止；只有一次轻微震动",
    objects={}),
  "worried": dict(
    name="忧虑",
    face="内眉以紧张的弧线上抬，眼睛睁大、瞳孔收缩，双唇抿成细线，喉咙发紧",
    posture="身体略微后撤，双肩紧绷上耸，双手收拢", motion="",
    light="冷青色主光，强烈高对比，半张脸没入黑暗",
    color="冷青色调，饱和度回落，黑位加深",
    particles="逐渐浓重的雾霭或飘浮微粒，降低画面通透度",
    time="缓慢而具有压迫感的推近，令人不安的手持晃动",
    objects={"shadows thickening in the corners of the frame":"画面四角的阴影逐渐加深",
             "faint drifting fog low across the floor":"贴近地面缓缓飘动的薄雾"}),
  "disgust": dict(
    name="厌恶",
    face="上唇上提并皱起鼻子，内眉下压，眼睑半垂向侧下方看，一侧嘴角下撇",
    posture="头部与躯干向后躲避，手向面部抬起", motion="",
    light="强烈的顶光在脸上切出刺眼的阴影",
    color="偏黄绿的病态色偏，去饱和，中间调浑浊肮脏",
    particles="空气中可见的污垢或酸腐的薄雾",
    time="短暂后仰然后停住，带有轻微的后退漂移",
    objects={"a faint film of grime and smudges on nearby surfaces":"附近表面上有一层薄薄的污垢与污渍",
             "a few small flies hovering and darting":"几只小飞虫盘旋穿梭"}),
  "awe": dict(
    name="敬畏",
    face="双眼睁大并向上抬，双唇轻轻张开，表情舒展成安静的凝滞",
    posture="头部上仰，胸腔打开，身体在环境之中显得静止而渺小", motion="",
    light="强烈的逆光与低角度光，极高动态范围，主体边缘泛出明亮轮廓光",
    color="深沉浓郁的调色，高光饱和，色调跨度宽广",
    particles="体积光柱与在光中浮动的细尘",
    time="极缓慢的推近或升降臂上移，接近凝固的运动，保持静止",
    objects={}),
}

STRENGTH = {
  "L": "轻微而几乎难以察觉，有所克制，仿佛情绪刚刚开始",
  "M": "",
  "H": "明显而毫不含糊，处在自然表达的边缘",
}


def strength_zh(level):
    s = STRENGTH.get(level, "")
    return f"（{s}）" if s else ""


def single_zh(emo, level, prompt_en):
    z = ZH[emo]
    st = strength_zh(level)
    name = z["name"]
    obj = ""
    for en, zh in z["objects"].items():
        if en in prompt_en:
            obj = zh
            break

    subject_defs = (
        "<Subject 1> 是 <Video 1> 中出现的人物，其身份、发型、服装与配饰均取自 <Video 1>。\n"
        "<Video 1> 是本次编辑任务的源视频。\n"
        "<Audio 1> 是 <Video 1> 的同步音轨。"
    )
    summary = (
        f"[视频编辑] 目标视频是 <Video 1> 的编辑版本。本次编辑只改变 <Subject 1> 的情绪状态，"
        f"使其变为「{name}」{st}。其余全部保留：身份、服装、身体姿态、手势时序、镜头机位与焦段、"
        f"镜头时长、背景布局，以及原始音频。"
    )
    retention = (
        f"<Subject 1>（出现于 [Shot 1]）：partially_preserved — 身份、面部结构、发型、服装与配饰"
        f"完整保留；只有面部表情与身体紧张度向「{name}」转变。\n"
        f"<Video 1>（源视频编辑）：fully_preserved — 原始机位、镜头、视场、主体位置、身体运动、"
        f"镜头时长与背景布局完全保持；不引入新的剪辑点。\n"
        f"<Audio 1>：fully_copy — <Audio 1> 以 1:1 原样复用为最终音轨。"
    )
    parts = [
        "目标视频为写实摄影风格，整体调性承载「" + name + "」。",
        "[Shot 1] 该镜头从 <Video 1> 开始，保持其完全一致的构图与焦段。",
        "<Subject 1> 在画面中的位置不变，身体姿态与手势时序保持不变。",
        "面部表情发生变化：" + z["face"] + "。",
    ]
    if z["posture"]:
        parts.append("姿态：" + z["posture"] + "。")
    if z["motion"]:
        parts.append("动作：" + z["motion"] + "。")
    if obj:
        parts.append(f"场景中另外出现{obj}，它必须自然地出现在既有环境里，并符合该环境的透视、尺度与光照。")
    parts.append("光线变化为：" + z["light"] + "。")
    parts.append("色调变化为：" + z["color"] + "。")
    if z["particles"]:
        parts.append("画面空气中" + z["particles"] + "。")
    parts.append("镜头不重新取景：" + z["time"] + "。")
    parts.append("无剪辑、不新增镜头、不变速。")
    detail = " ".join(parts)

    sound = "与 <Video 1> 完全一致。不引入新的环境声、拟音或人声。"
    music = "无。音轨从 <Video 1> 以 1:1 复制，不添加非画内音乐。"

    return "\n\n".join([
        "subject_definitions:" + subject_defs,
        "summary:\n" + summary,
        "retention_analysis:\n" + retention,
        "detailed_description:\n" + detail,
        "overall_soundscape:\n" + sound,
        "non_diegetic_music:\n" + music,
    ])


def trans_zh(frm, to, prompt_en, duration):
    zf, zt = ZH[frm], ZH[to]
    m1 = re.search(r"At\s+([\d.]+)\s+the transition begins", prompt_en)
    m2 = re.search(r"At\s+([\d.]+)\s+the shift completes", prompt_en)
    t1 = float(m1.group(1)) if m1 else duration * 0.25
    t2 = float(m2.group(1)) if m2 else duration * 0.75

    subject_defs = (
        "<Subject 1> 是 <Video 1> 中出现的人物，其身份、发型、服装与配饰均取自 <Video 1>。\n"
        "<Video 1> 是本次编辑任务的源视频。\n"
        "<Audio 1> 是 <Video 1> 的同步音轨。"
    )
    summary = (
        f"[视频编辑] 目标视频是 <Video 1> 的编辑版本。本次编辑让 <Subject 1> 的情绪在整段中"
        f"从「{zf['name']}」连续过渡到「{zt['name']}」。身份、姿态、手势时序、镜头机位、"
        f"镜头时长、背景布局以及原始音频全部保留。"
    )
    retention = (
        f"<Subject 1>（出现于 [Shot 1]、[Shot 2]、[Shot 3]）：partially_preserved — 身份、"
        f"面部结构、服装与配饰完整保留；只有表情、光线、色调与镜头能量从「{zf['name']}」"
        f"逐渐转向「{zt['name']}」。\n"
        f"<Video 1>（源视频编辑）：fully_preserved — 机位、镜头、视场、主体位置、身体运动、"
        f"镜头时长与背景布局均保持；不重新剪辑。\n"
        f"<Audio 1>：fully_copy — <Audio 1> 以 1:1 原样复用为最终音轨。"
    )
    detail = (
        f"目标视频为写实摄影风格。"
        f"[Shot 1] 该镜头从 <Video 1> 开始，保持「{zf['name']}」状态：{zf['face']}。"
        f"光线为 {zf['light']}，色调为 {zf['color']}，镜头表现为：{zf['time']}。"
        f"<Subject 1> 的位置、姿态与手势时序与 <Video 1> 一致。"
        f"[Shot 2] 在 {t1:.3f} 秒处，过渡在没有任何剪辑的情况下开始：表情由「{zf['name']}」"
        f"向「{zt['name']}」缓和转变，光线从 {zf['light']} 逐渐转为 {zt['light']}，"
        f"色调从 {zf['color']} 漂移到 {zt['color']}。变化连续而缓慢，没有突兀的跳变。"
        f"[Shot 3] 在 {t2:.3f} 秒处，转变完成并稳定在「{zt['name']}」：{zt['face']}。"
        f"此时光线为 {zt['light']}，色调为 {zt['color']}，镜头表现为：{zt['time']}。"
        f"<Subject 1> 全程保持同一位置、同一身体姿态与手势时序。背景布局始终不变。"
        f"不引入剪辑、不新增镜头，总时长与 <Video 1> 一致。"
    )
    sound = "与 <Video 1> 完全一致。不引入新的环境声、拟音或人声。"
    music = "无。音轨从 <Video 1> 以 1:1 复制，不添加非画内音乐。"

    return "\n\n".join([
        "subject_definitions:" + subject_defs,
        "summary:\n" + summary,
        "retention_analysis:\n" + retention,
        "detailed_description:\n" + detail,
        "overall_soundscape:\n" + sound,
        "non_diegetic_music:\n" + music,
    ])


dirs = [os.path.join(B, d) for d in ("requests", "requests_bal_a", "requests_bal_b")]
result = {}
for d in dirs:
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        stem = os.path.basename(f)[:-5]
        req = json.load(open(f, encoding="utf-8"))
        en = req["prompt"]
        dur = req["target"]["duration_seconds"]
        parts = stem.split("__")
        if parts[0] == "trans":
            frm, to = re.match(r"([a-z]+)_to_([a-z]+)$", parts[2]).groups()
            zh = trans_zh(frm, to, en, dur)
        else:
            emo, lvl = parts[2], parts[3]
            zh = single_zh(emo, lvl, en)
        result[stem] = zh

json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("生成中文 prompt:", len(result), "条")
print("写入:", OUT)
print()
print("=== 样例：sad single ===")
print(result["single__sample_00000993__sad__M"][:700])