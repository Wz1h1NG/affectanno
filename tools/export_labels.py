# -*- coding: utf-8 -*-
"""把 D1 里的标注导出到 GBU 服务器指定目录。

用法（本地跑，数据直接落到 GBU，不在本地留文件）：
    python export_labels.py              # 导出并上传
    python export_labels.py --local-only # 只生成本地临时文件（调试）

产物写到 GBU：
    /public_hw/share/cit_ztyu/zehengW/emoedit_anno_exports/
        latest.csv / latest.json                 <- 总是最新全量
        snapshots/<时间戳>/labels.csv|json       <- 每次导出留档
        snapshots/<时间戳>/summary.txt           <- 进度与分布
"""
import argparse
import base64
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

# ---- Cloudflare 配置 ----
CF = os.environ["CLOUDFLARE_API_TOKEN"]
ACC = os.environ["CLOUDFLARE_ACCOUNT_ID"]
DB = os.environ.get("ANNO_D1_ID", "4c34b1fe-18e8-4270-9af3-6123bfbbaaf8")
D1_URL = f"https://api.cloudflare.com/client/v4/accounts/{ACC}/d1/database/{DB}/query"

# ---- GBU 目标 ----
SSH_HOST = "GBU"
GBU_DIR = "/public_hw/share/cit_ztyu/zehengW/emoedit_anno_exports"

COLUMNS = [
    "item_id", "subset", "emotion", "intensity", "trans_from", "origin_id",
    "origin_prompt", "verdict", "emo_clarity", "intensity_fit", "identity_keep",
    "comp_keep", "audio_keep", "trans_smooth", "new_prompt", "note",
    "annotator", "seconds", "created_at",
]


def d1(sql, retries=4):
    body = json.dumps({"sql": sql, "params": []}).encode()
    for i in range(retries):
        req = urllib.request.Request(
            D1_URL, data=body, method="POST",
            headers={"Authorization": f"Bearer {CF}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
            if data.get("success"):
                return data["result"][0]["results"]
            raise RuntimeError(json.dumps(data)[:300])
        except urllib.error.HTTPError as e:
            print(f"  http {e.code}, retry {i+1}", file=sys.stderr)
        except Exception as e:
            print(f"  {type(e).__name__}, retry {i+1}", file=sys.stderr)
        time.sleep(1.5 * (i + 1))
    raise RuntimeError("D1 查询失败: " + sql[:80])


def fetch():
    stats = {
        "items": d1("SELECT COUNT(*) c FROM items")[0]["c"],
        "labels": d1("SELECT COUNT(*) c FROM labels")[0]["c"],
        "skips": d1("SELECT COUNT(*) c FROM skips")[0]["c"],
    }
    rows = d1("""
        SELECT i.id AS item_id, i.subset, i.emotion, i.intensity, i.trans_from,
               i.origin_id, i.prompt AS origin_prompt,
               l.verdict, l.emo_clarity, l.intensity_fit, l.identity_keep,
               l.comp_keep, l.audio_keep, l.trans_smooth,
               l.new_prompt, l.note, l.annotator, l.ms, l.created_at
        FROM labels l JOIN items i ON i.id = l.item_id
        ORDER BY i.id""")
    for r in rows:
        r["seconds"] = round((r.pop("ms") or 0) / 1000, 1)
        ts = r.pop("created_at", None)
        r["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""
    return stats, rows


def summarize(stats, rows):
    from collections import Counter
    by_emo = Counter(r["emotion"] for r in rows)
    by_verdict = Counter(r["verdict"] for r in rows)
    by_anno = Counter(r["annotator"] for r in rows)

    def avg(key):
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return round(sum(vals) / len(vals), 2) if vals else None

    lines = [
        "EmoEdit 视频标注导出",
        "时间: " + time.strftime("%Y-%m-%d %H:%M:%S"),
        "",
        f"样本总数: {stats['items']}",
        f"已标注:   {stats['labels']}",
        f"未标注:   {stats['items'] - stats['labels']}",
        f"跳过记录: {stats['skips']}",
        "",
        "判定分布:",
    ]
    for k, v in by_verdict.most_common():
        lines.append(f"  {k or '(空)'}: {v}")
    lines.append("")
    lines.append("情绪分布:")
    for k, v in by_emo.most_common():
        lines.append(f"  {k or '(空)'}: {v}")
    lines.append("")
    lines.append("标注员产出:")
    for k, v in by_anno.most_common():
        lines.append(f"  {k}: {v}")
    lines.extend([
        "",
        "维度均值（1-5）:",
        f"  emo_clarity:   {avg('emo_clarity')}",
        f"  identity_keep: {avg('identity_keep')}",
        f"  comp_keep:     {avg('comp_keep')}",
        "",
        "强度是否符合:",
    ])
    for k, v in Counter(r["intensity_fit"] for r in rows if r.get("intensity_fit")).most_common():
        lines.append(f"  {k}: {v}")
    lines.append("过度是否平滑:")
    for k, v in Counter(r["trans_smooth"] for r in rows if r.get("trans_smooth")).most_common():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines) + "\n"


def to_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return "\ufeff" + buf.getvalue()  # BOM 让 Excel 正常识别中文


def gbu_write(local_path, remote_path):
    """scp 到 GBU。返回 True/False。"""
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=25", SSH_HOST,
         f"mkdir -p {os.path.dirname(remote_path)}"],
        capture_output=True, text=True)
    if r.returncode != 0:
        print("  mkdir 失败:", r.stderr.strip()[:200], file=sys.stderr)
        return False
    r = subprocess.run(
        ["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=25",
         local_path, f"{SSH_HOST}:{remote_path}"],
        capture_output=True, text=True)
    if r.returncode != 0:
        print("  scp 失败:", r.stderr.strip()[:200], file=sys.stderr)
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-only", action="store_true")
    ap.add_argument("--no-snapshot", action="store_true", help="只更新 latest，不留快照")
    args = ap.parse_args()

    print("拉取 D1 标注…")
    stats, rows = fetch()
    print(f"  items={stats['items']} labels={stats['labels']}")

    csv_text = to_csv(rows)
    json_text = json.dumps(rows, ensure_ascii=False, indent=1)
    summary = summarize(stats, rows)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    targets = [
        ("labels.csv", csv_text, "latest.csv"),
        ("labels.json", json_text, "latest.json"),
    ]
    if not args.no_snapshot:
        targets += [
            (f"snapshots/{stamp}/labels.csv", csv_text, None),
            (f"snapshots/{stamp}/labels.json", json_text, None),
            (f"snapshots/{stamp}/summary.txt", summary, None),
        ]

    tmpdir = tempfile.mkdtemp(prefix="anno_export_")
    ok = fail = 0
    try:
        for name, text, alias in targets:
            p = os.path.join(tmpdir, os.path.basename(name))
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            dests = [f"{GBU_DIR}/{name}"]
            if alias:
                dests.append(f"{GBU_DIR}/{alias}")
            for d in dests:
                if args.local_only:
                    print(f"  [local] {name} -> {d} ({len(text)} chars)")
                    ok += 1
                elif gbu_write(p, d):
                    print(f"  ok  {d}")
                    ok += 1
                else:
                    fail += 1
    finally:
        for f in os.listdir(tmpdir):
            try:
                os.remove(os.path.join(tmpdir, f))
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass

    print()
    print(summary)
    print(f"上传完成: 成功 {ok} / 失败 {fail}")
    print(f"位置: {GBU_DIR}/latest.csv")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
