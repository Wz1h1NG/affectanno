# -*- coding: utf-8 -*-
"""构建视频标注站资源：public/vid/{origin,edit}/*.mp4 + manifest.json"""
import glob, json, os, random, re, subprocess, sys

B = "/public_hw/share/cit_ztyu/zehengW/emotion_edit_pilot_20261029"
FF = "/public_hw/share/cit_ztyu/cit_bohandeng/open_generators/tools/ffmpeg/bin"
OUT = "/public_hw/share/cit_ztyu/zehengW/video_anno_site"
PUB = os.path.join(OUT, "public")
ORIG_DIR = os.path.join(PUB, "vid", "origin")
EDIT_DIR = os.path.join(PUB, "vid", "edit")
for d in (ORIG_DIR, EDIT_DIR):
    os.makedirs(d, exist_ok=True)

reqs = sorted(f for f in glob.glob(os.path.join(B, "requests", "*.json")))
items = []
for f in reqs:
    stem = os.path.basename(f)[:-5]
    parts = stem.split("__")
    subset = parts[0]
    src_id = parts[1].replace("sample_", "")
    d = json.load(open(f))
    emo, inten, trans_from = "", "", ""
    if subset == "trans":
        # trans__sample_00001295__neutral_to_sad
        m = re.match(r"([a-z]+)_to_([a-z]+)$", parts[2])
        trans_from, emo = m.group(1), m.group(2)
    else:
        emo, inten = parts[2], parts[3]
    items.append(dict(stem=stem, subset=subset, src_id=src_id, emotion=emo,
                      intensity=inten, trans_from=trans_from, prompt=d["prompt"],
                      duration=d["target"]["duration_seconds"]))

print("items:", len(items))
src_ids = sorted({it["src_id"] for it in items})
print("unique sources:", len(src_ids))

# 1) 源视频统一转 864x480 / 24fps / aac
for sid in src_ids:
    src = os.path.join(B, "src", f"sample_{sid}.mp4")
    dst = os.path.join(ORIG_DIR, f"sample_{sid}.mp4")
    if os.path.exists(dst) and os.path.getsize(dst) > 1000:
        continue
    cmd = [FF + "/ffmpeg", "-nostdin", "-v", "error", "-y", "-i", src,
           "-vf", "scale=864:480:force_original_aspect_ratio=decrease,pad=864:480:(ow-iw)/2:(oh-ih)/2:black",
           "-r", "24", "-c:v", "libx264", "-crf", "24", "-preset", "veryfast",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", dst]
    subprocess.run(cmd, check=True)
    print("origin", sid, os.path.getsize(dst))

# 2) 编辑视频：final/<stem>.mp4
for it in items:
    src = os.path.join(B, "final", it["stem"] + ".mp4")
    dst = os.path.join(EDIT_DIR, it["stem"] + ".mp4")
    if os.path.exists(dst) and os.path.getsize(dst) > 1000:
        continue
    # 重封装 + faststart，便于浏览器边下边播
    cmd = [FF + "/ffmpeg", "-nostdin", "-v", "error", "-y", "-i", src,
           "-c", "copy", "-movflags", "+faststart", dst]
    subprocess.run(cmd, check=True)

# 3) 打乱顺序并写 manifest
rng = random.Random(20261030)
order = list(range(len(items)))
rng.shuffle(order)
manifest = []
for new_ord, idx in enumerate(order, 1):
    it = items[idx]
    manifest.append(dict(
        id=new_ord,
        ord=new_ord,
        subset=it["subset"],
        emotion=it["emotion"],
        intensity=it["intensity"],
        trans_from=it["trans_from"],
        origin_id=it["src_id"],
        stem=it["stem"],
        duration=round(it["duration"], 2),
        origin_asset=f"vid/origin/sample_{it['src_id']}.mp4",
        edited_asset=f"vid/edit/{it['stem']}.mp4",
        prompt=it["prompt"],
    ))
json.dump(manifest, open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

n_o = len(os.listdir(ORIG_DIR)); n_e = len(os.listdir(EDIT_DIR))
tot = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(os.path.join(PUB, "vid")) for f in fs)
print(f"origin={n_o} edit={n_e} total={tot/1048576:.1f} MB")
print("manifest entries:", len(manifest))
from collections import Counter
print("by subset:", dict(Counter(m["subset"] for m in manifest)))
print("by emotion:", dict(Counter(m["emotion"] for m in manifest)))
print("by intensity:", dict(Counter(m["intensity"] for m in manifest)))