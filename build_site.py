"""把本地标注台的数据整理成 Cloudflare 版：
- 复制前端页面 → anno_cf/public/
- 复制图片 → anno_cf/public/img/{origin,edit}/<item_id>.jpg
- 生成 seed.sql（D1 初始化数据）
"""
import os
import random
import secrets
import shutil
import sqlite3

ROOT = r"C:\Users\11641\Desktop\deepkseek"
SRC_DB = os.path.join(ROOT, "anno_local", "annotations.db")
SRC_STATIC = os.path.join(ROOT, "anno_local", "static")
OUT = os.path.join(ROOT, "anno_cf")
PUB = os.path.join(OUT, "public")

os.makedirs(PUB, exist_ok=True)
for f in ("index.html", "login.html"):
    shutil.copy2(os.path.join(SRC_STATIC, f), os.path.join(PUB, f))
print("前端页面已复制")

con = sqlite3.connect(SRC_DB)
con.row_factory = sqlite3.Row
items = list(con.execute("SELECT * FROM items ORDER BY id"))
labels = list(con.execute("SELECT * FROM labels"))
cfg = dict(con.execute("SELECT k, v FROM config"))

made = 0
for it in items:
    for kind, path in (("origin", it["origin_path"]), ("edit", it["edited_path"])):
        dst_dir = os.path.join(PUB, "img", kind)
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, f"{it['id']}.jpg")
        if not os.path.exists(dst):
            shutil.copy2(path, dst)
            made += 1
print(f"图片已复制 {made} 个（共 {len(items)} 条样本）")


def q(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


lines = ["PRAGMA foreign_keys=OFF;", "BEGIN TRANSACTION;"]

lines.append("DELETE FROM items; DELETE FROM labels; DELETE FROM claims; DELETE FROM skips;")
for it in items:
    lines.append(
        "INSERT INTO items(id,ord,subset,emotion,origin_id,prompt,origin_asset,edited_asset,kind) "
        f"VALUES({q(it['id'])},{q(it['ord'])},{q(it['subset'])},{q(it['emotion'])},"
        f"{q(it['origin_id'])},{q(it['prompt'])},{q('img/origin/%d.jpg' % it['id'])},"
        f"{q('img/edit/%d.jpg' % it['id'])},{q('image')});"
    )
for lb in labels:
    lines.append(
        "INSERT INTO labels(item_id,annotator,verdict,new_prompt,note,ms,created_at) "
        f"VALUES({q(lb['item_id'])},{q(lb['annotator'])},{q(lb['verdict'])},"
        f"{q(lb['new_prompt'])},{q(lb['note'])},{q(lb['ms'])},{q(lb['created_at'])});"
    )

lines.append("DELETE FROM config;")
for k, v in (("access_code", cfg["access_code"]),
             ("admin_code", cfg["admin_code"]),
             ("secret", secrets.token_hex(32))):
    lines.append(f"INSERT INTO config(k,v) VALUES({q(k)},{q(v)});")

lines.append("COMMIT;")
with open(os.path.join(OUT, "seed.sql"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print("已生成 seed.sql：items=%d labels=%d access_code=%s" %
      (len(items), len(labels), cfg["access_code"]))
total = sum(os.path.getsize(os.path.join(dp, f))
            for dp, _, fs in os.walk(os.path.join(PUB, "img")) for f in fs)
print(f"图片总量 {total / 1024 / 1024:.1f} MB")
