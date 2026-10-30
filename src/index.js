/**
 * EmoEdit 情感标注台 · Cloudflare Worker 版（视频）
 * 数据库：D1    视频：Worker 静态资源（env.ASSETS）
 * 相对图片版的改动：
 *   - /img → /vid，支持 HTTP Range（拖动进度条必需）
 *   - items 增加 intensity / trans_from / duration 语义
 *   - labels 增加 6 个分项维度
 */

const SESSION_TTL = 30 * 86400;   // 30 天
const CLAIM_TTL = 15 * 60;        // 15 分钟

const EMOJI = {
  amusement: "😄", anger: "😠", awe: "😮", contentment: "😌",
  disgust: "🤢", excitement: "🤩", fear: "😨", sadness: "😢",
  happy: "😊", sad: "😢", worried: "😟", surprise: "😮", neutral: "😐",
};
const EMO_ZH = {
  amusement: "愉悦 / 有趣", anger: "愤怒", awe: "惊叹 / 敬畏",
  contentment: "满足 / 安宁", disgust: "厌恶", excitement: "兴奋",
  fear: "恐惧", sadness: "悲伤",
  happy: "开心", sad: "悲伤", worried: "担忧", surprise: "惊讶", neutral: "中性",
};
const INTENSITY_ZH = { L: "轻微", M: "中等", H: "强烈" };
const SUBSET_ZH = { single: "单一情绪", grad: "强度梯度", trans: "情绪过渡" };

/* ---------------------------------------------------------------- 工具 */

function json(data, status = 200, extra = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...extra,
    },
  });
}

function getCookie(request, key) {
  const raw = request.headers.get("Cookie") || "";
  for (const part of raw.split(";")) {
    const i = part.indexOf("=");
    if (i > 0 && part.slice(0, i).trim() === key) {
      return decodeURIComponent(part.slice(i + 1).trim());
    }
  }
  return null;
}

function b64url(bytes) {
  let s = "";
  for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function hmac(payload, secret) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(payload));
  return b64url(sig);
}

async function makeSession(name, secret) {
  const payload = btoa(unescape(encodeURIComponent(
    JSON.stringify({ n: name, exp: Math.floor(Date.now() / 1000) + SESSION_TTL })
  ))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const sig = await hmac(payload, secret);
  return `${payload}.${sig}`;
}

async function readSession(token, secret) {
  if (!token) return null;
  const idx = token.lastIndexOf(".");
  if (idx < 1) return null;
  const payload = token.slice(0, idx);
  const sig = token.slice(idx + 1);
  if ((await hmac(payload, secret)) !== sig) return null;
  try {
    const b = payload.replace(/-/g, "+").replace(/_/g, "/");
    const obj = JSON.parse(decodeURIComponent(escape(atob(b + "=".repeat((4 - (b.length % 4)) % 4)))));
    if (!obj.exp || obj.exp < Date.now() / 1000) return null;
    return obj.n;
  } catch {
    return null;
  }
}

function cleanName(s) {
  return String(s || "").trim().slice(0, 24);
}

async function cfg(env, key) {
  const row = await env.DB.prepare("SELECT v FROM config WHERE k=?").bind(key).first();
  return row ? row.v : null;
}

async function stats(env) {
  const total = (await env.DB.prepare("SELECT COUNT(*) c FROM items").first()).c;
  const done = (await env.DB.prepare("SELECT COUNT(*) c FROM labels").first()).c;
  const per = (await env.DB.prepare(
    "SELECT annotator, COUNT(*) c, SUM(verdict='ok') ok FROM labels GROUP BY annotator ORDER BY c DESC"
  ).all()).results || [];
  return { total, done, remain: Math.max(0, total - done), per };
}

function itemJson(row) {
  const emotion = row.emotion || "";
  return {
    id: row.id,
    subset: row.subset,
    subset_zh: SUBSET_ZH[row.subset] || row.subset,
    emotion,
    emoji: EMOJI[emotion] || "❓",
    emo_zh: EMO_ZH[emotion] || emotion,
    intensity: row.intensity || "",
    intensity_zh: INTENSITY_ZH[row.intensity] || "",
    trans_from: row.trans_from || "",
    trans_from_zh: row.trans_from ? (EMO_ZH[row.trans_from] || row.trans_from) : "",
    origin_id: row.origin_id,
    duration: row.duration || null,
    prompt: row.prompt,
    prompt_zh: row.prompt_zh || "",
    kind: row.kind || "video",
  };
}

/* ---------------------------------------------------------------- 取题 */

async function claimNext(env, name) {
  const now = Date.now() / 1000;
  // 先清掉过期租约：否则 ON CONFLICT DO NOTHING 会让这一题谁也抢不到（取题卡死的根因）
  await env.DB.prepare("DELETE FROM claims WHERE expires <= ?").bind(now).run();
  for (let attempt = 0; attempt < 4; attempt++) {
    const cand = await env.DB.prepare(`
      SELECT i.* FROM items i
      WHERE NOT EXISTS (SELECT 1 FROM labels l WHERE l.item_id = i.id)
        AND NOT EXISTS (SELECT 1 FROM claims c WHERE c.item_id = i.id
                        AND c.expires > ? AND c.annotator <> ?)
        AND NOT EXISTS (SELECT 1 FROM skips s WHERE s.item_id = i.id AND s.annotator = ?)
      ORDER BY i.ord LIMIT 1`).bind(now, name, name).first();
    if (!cand) return null;
    await env.DB.prepare(
      "INSERT INTO claims(item_id,annotator,expires) VALUES(?,?,?) " +
      "ON CONFLICT(item_id) DO UPDATE SET annotator=excluded.annotator, expires=excluded.expires " +
      "WHERE claims.expires <= ?"
    ).bind(cand.id, name, now + CLAIM_TTL, now).run();
    const mine = await env.DB.prepare(
      "SELECT item_id FROM claims WHERE item_id=? AND annotator=?"
    ).bind(cand.id, name).first();
    if (mine) return cand;
  }
  return null;
}

/* ---------------------------------------------------------------- 视频（Range） */

// 浏览器播放/拖动进度条必须支持 206 Partial Content，否则 Safari 直接不播
async function serveVideo(request, env, url, asset, cache) {
  const res = await env.ASSETS.fetch(new URL("/" + asset, url.origin));
  if (!res.ok) return json({ error: "no video" }, 404);

  const buf = await res.arrayBuffer();
  const total = buf.byteLength;
  const headers = {
    "Content-Type": "video/mp4",
    "Accept-Ranges": "bytes",
    "Cache-Control": cache || "private, max-age=86400",
  };

  const range = request.headers.get("Range");
  if (range) {
    const m = /bytes=(\d*)-(\d*)/.exec(range);
    if (m && (m[1] !== "" || m[2] !== "")) {
      let start, end;
      if (m[1] === "") {
        const n = parseInt(m[2], 10) || 0;
        start = Math.max(0, total - n);
        end = total - 1;
      } else {
        start = parseInt(m[1], 10);
        end = m[2] === "" ? total - 1 : Math.min(parseInt(m[2], 10), total - 1);
      }
      if (!(start >= 0 && start <= end && start < total)) {
        return new Response(null, {
          status: 416,
          headers: { "Content-Range": `bytes */${total}` },
        });
      }
      const slice = buf.slice(start, end + 1);
      headers["Content-Range"] = `bytes ${start}-${end}/${total}`;
      headers["Content-Length"] = String(slice.byteLength);
      return new Response(slice, { status: 206, headers });
    }
  }

  headers["Content-Length"] = String(total);
  return new Response(buf, { status: 200, headers });
}

/* ---------------------------------------------------------------- 路由 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = url.pathname;
    const method = request.method;

    if (p === "/health") return json({ ok: true, runtime: "workers", mode: "video" });

    let name = null;
    const secret = await cfg(env, "secret");
    if (secret) name = await readSession(getCookie(request, "anno"), secret);

    /* ---------- 静态页面 ---------- */
    if (method === "GET" && (p === "/" || p === "/login")) {
      const file = p === "/login" || !name ? "/login.html" : "/index.html";
      return env.ASSETS.fetch(new URL(file, url.origin));
    }

    /* ---------- 视频（需要登录，支持 Range） ---------- */
    if (method === "GET" && (p === "/vid" || p === "/img")) {
      if (!name) return json({ error: "login" }, 403);
      const id = parseInt(url.searchParams.get("item") || "0", 10);
      const v = url.searchParams.get("v") === "origin" ? "origin" : "edit";
      const row = await env.DB.prepare(
        "SELECT origin_asset, edited_asset FROM items WHERE id=?"
      ).bind(id).first();
      if (!row) return json({ error: "no item" }, 404);
      const asset = v === "origin" ? row.origin_asset : row.edited_asset;
      if (!asset) return json({ error: "no video" }, 404);
      return serveVideo(request, env, url, asset, "private, max-age=86400");
    }

    /* ---------- 登录 ---------- */
    if (method === "POST" && p === "/api/login") {
      let body = {};
      try { body = await request.json(); } catch {}
      const code = String(body.code || "").trim();
      const nm = cleanName(body.name);
      if (!nm) return json({ error: "请填名字" }, 400);
      const access = await cfg(env, "access_code");
      if (!access || code !== access) return json({ error: "口令不对" }, 403);
      const token = await makeSession(nm, secret);
      return json({ ok: true, me: nm }, 200, {
        "Set-Cookie": `anno=${encodeURIComponent(token)}; Path=/; Max-Age=${SESSION_TTL}; SameSite=Lax; Secure`,
      });
    }

    /* ---------- 一键进站 ---------- */
    if (method === "GET" && p === "/join") {
      const code = (url.searchParams.get("code") || "").trim();
      const nm = cleanName(url.searchParams.get("name"));
      const access = await cfg(env, "access_code");
      if (!nm || !access || code !== access) return json({ error: "链接无效：口令或名字不对" }, 403);
      const token = await makeSession(nm, secret);
      return new Response(null, {
        status: 302,
        headers: {
          Location: "/",
          "Set-Cookie": `anno=${encodeURIComponent(token)}; Path=/; Max-Age=${SESSION_TTL}; SameSite=Lax; Secure`,
        },
      });
    }

    if (method === "POST" && p === "/api/logout") {
      return json({ ok: true }, 200, { "Set-Cookie": "anno=; Path=/; Max-Age=0" });
    }

    /* ---------- 结果查看页：只需管理员口令 ---------- */
    if (p === "/admin" || p === "/api/results" || p === "/admin/img" || p === "/admin/vid") {
      const code = url.searchParams.get("code") || "";
      const admin = (await cfg(env, "admin_code")) || "";
      if (!code || code !== admin) return json({ error: "need admin code" }, 403);

      if (p === "/admin") return env.ASSETS.fetch(new URL("/admin.html", url.origin));

      if (p === "/api/results") {
        const rows = (await env.DB.prepare(`
          SELECT l.item_id, l.annotator, l.verdict, l.new_prompt, l.note, l.ms, l.created_at,
                 l.emo_clarity, l.intensity_fit, l.identity_keep, l.comp_keep,
                 l.audio_keep, l.trans_smooth,
                 i.subset, i.emotion, i.intensity, i.trans_from, i.origin_id, i.prompt
          FROM labels l JOIN items i ON i.id = l.item_id
          ORDER BY l.created_at DESC`).all()).results || [];
        return json({ stats: await stats(env), rows });
      }

      // /admin/img | /admin/vid
      const id = parseInt(url.searchParams.get("item") || "0", 10);
      const v = url.searchParams.get("v") === "origin" ? "origin" : "edit";
      const row = await env.DB.prepare(
        "SELECT origin_asset, edited_asset FROM items WHERE id=?").bind(id).first();
      if (!row) return json({ error: "no item" }, 404);
      const asset = v === "origin" ? row.origin_asset : row.edited_asset;
      if (!asset) return json({ error: "no video" }, 404);
      return serveVideo(request, env, url, asset, "private, max-age=3600");
    }

    // 结果页模板本身不对外暴露
    if (p === "/admin.html") return json({ error: "not found" }, 404);

    /* ---------- 以下需要登录（导出只需管理员口令，和旧版一致） ---------- */
    if (!name && p !== "/export.csv") return json({ error: "login" }, 401);

    if (method === "GET" && p === "/api/next") {
      const row = await claimNext(env, name);
      const st = await stats(env);
      return json({ item: row ? itemJson(row) : null, stats: st, me: name });
    }

    /* ---------- 返修：取回自己最近标注过的样本 ----------
       offset=0 是最近一条，1 是再往前一条，依此类推。
       返回的 item 附带上次的标签内容，前端据此回填表单。 */
    if (method === "GET" && p === "/api/last") {
      const offset = Math.max(0, parseInt(url.searchParams.get("offset") || "0", 10) || 0);
      const cnt = (await env.DB.prepare(
        "SELECT COUNT(*) c FROM labels WHERE annotator=?").bind(name).first()).c;
      if (!cnt) return json({ item: null, label: null, total: 0, offset }, 200);
      const row = await env.DB.prepare(`
        SELECT i.*, l.verdict, l.emo_clarity, l.intensity_fit, l.identity_keep,
               l.comp_keep, l.audio_keep, l.trans_smooth, l.new_prompt, l.note, l.ms
        FROM labels l JOIN items i ON i.id = l.item_id
        WHERE l.annotator = ?
        ORDER BY l.id DESC
        LIMIT 1 OFFSET ?`).bind(name, offset).first();
      if (!row) {
        // offset 越界：夹到边界的最后一条
        return json({ item: null, label: null, total: cnt, offset, outOfRange: true }, 200);
      }
      return json({
        item: itemJson(row),
        label: {
          verdict: row.verdict,
          emo_clarity: row.emo_clarity,
          intensity_fit: row.intensity_fit,
          identity_keep: row.identity_keep,
          comp_keep: row.comp_keep,
          audio_keep: row.audio_keep,
          trans_smooth: row.trans_smooth,
          new_prompt: row.new_prompt || "",
          note: row.note || "",
          ms: row.ms || 0,
        },
        total: cnt,
        offset,
        canOlder: offset + 1 < cnt,
      });
    }

    if (method === "GET" && p === "/api/stats") {
      const st = await stats(env);
      st.me = name;
      st.mine = (await env.DB.prepare("SELECT COUNT(*) c FROM labels WHERE annotator=?").bind(name).first()).c;
      return json(st);
    }

    if (method === "GET" && p === "/api/me") return json({ me: name });

    if (method === "POST" && p === "/api/label") {
      let body = {};
      try { body = await request.json(); } catch {}
      const id = parseInt(body.item_id, 10);
      if (!id) return json({ error: "bad item" }, 400);
      const verdict = body.verdict === "ok" ? "ok" : "bad";
      const newPrompt = String(body.new_prompt || "").trim();
      const note = String(body.note || "").trim();
      const ms = parseInt(body.ms || 0, 10) || 0;

      // 分项维度
      const emoClarity = parseInt(body.emo_clarity || 0, 10) || null;
      const intensityFit = ["weaker", "good", "stronger"].includes(body.intensity_fit)
        ? body.intensity_fit : null;
      const identityKeep = parseInt(body.identity_keep || 0, 10) || null;
      const compKeep = parseInt(body.comp_keep || 0, 10) || null;
      const audioKeep = ["yes", "no", "na"].includes(body.audio_keep) ? body.audio_keep : null;
      const transSmooth = ["yes", "no", "na"].includes(body.trans_smooth) ? body.trans_smooth : null;

      if (verdict === "bad" && !newPrompt) return json({ error: "标为不正确时请写新的 prompt" }, 400);

      const item = await env.DB.prepare("SELECT id FROM items WHERE id=?").bind(id).first();
      if (!item) return json({ error: "样本不存在" }, 404);

      const other = await env.DB.prepare(
        "SELECT annotator FROM labels WHERE item_id=? AND annotator<>?"
      ).bind(id, name).first();
      if (other) return json({ error: `这条已由 ${other.annotator} 标注，自动跳下一条` }, 409);

      await env.DB.prepare(`
        INSERT INTO labels(item_id,annotator,verdict,new_prompt,note,ms,created_at,
                           emo_clarity,intensity_fit,identity_keep,comp_keep,audio_keep,trans_smooth)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(item_id) DO UPDATE SET
          annotator=excluded.annotator, verdict=excluded.verdict,
          new_prompt=excluded.new_prompt, note=excluded.note,
          ms=excluded.ms, created_at=excluded.created_at,
          emo_clarity=excluded.emo_clarity, intensity_fit=excluded.intensity_fit,
          identity_keep=excluded.identity_keep, comp_keep=excluded.comp_keep,
          audio_keep=excluded.audio_keep, trans_smooth=excluded.trans_smooth`
      ).bind(id, name, verdict, newPrompt, note, ms, Date.now() / 1000,
             emoClarity, intensityFit, identityKeep, compKeep, audioKeep, transSmooth).run();

      await env.DB.prepare("DELETE FROM claims WHERE item_id=?").bind(id).run();
      return json({ ok: true, stats: await stats(env) });
    }

    if (method === "POST" && p === "/api/skip") {
      let body = {};
      try { body = await request.json(); } catch {}
      const id = parseInt(body.item_id, 10);
      if (!id) return json({ error: "bad item" }, 400);
      await env.DB.prepare(
        "INSERT OR IGNORE INTO skips(item_id,annotator,created_at) VALUES(?,?,?)"
      ).bind(id, name, Date.now() / 1000).run();
      await env.DB.prepare("DELETE FROM claims WHERE item_id=?").bind(id).run();
      return json({ ok: true });
    }

    /* ---------- 导出 ---------- */
    if (method === "GET" && p === "/export.csv") {
      const code = url.searchParams.get("code") || "";
      const admin = (await cfg(env, "admin_code")) || "";
      if (!code || !admin || code !== admin) return json({ error: "need admin code" }, 403);
      const rows = (await env.DB.prepare(`
        SELECT i.id,i.subset,i.emotion,i.intensity,i.trans_from,i.origin_id,i.prompt,
               i.origin_asset,i.edited_asset,
               l.annotator,l.verdict,l.emo_clarity,l.intensity_fit,l.identity_keep,
               l.comp_keep,l.audio_keep,l.trans_smooth,l.new_prompt,l.note,l.ms,l.created_at
        FROM labels l JOIN items i ON i.id=l.item_id ORDER BY i.id`).all()).results || [];
      const esc = (v) => {
        const s = v === null || v === undefined ? "" : String(v);
        return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
      };
      // 导出用北京时间（UTC+8），和旧版一致
      const bjTime = (ts) => new Date((ts || 0) * 1000 + 8 * 3600 * 1000)
        .toISOString().replace("T", " ").slice(0, 19);
      const head = ["item_id", "subset", "emotion", "intensity", "trans_from", "origin_id",
        "origin_prompt", "verdict", "emo_clarity", "intensity_fit", "identity_keep",
        "comp_keep", "audio_keep", "trans_smooth", "new_prompt", "note", "annotator",
        "seconds", "created_at", "origin_path", "edited_path"];
      const lines = [head.join(",")];
      for (const r of rows) {
        lines.push([
          r.id, r.subset, r.emotion, r.intensity || "", r.trans_from || "", r.origin_id, r.prompt,
          r.verdict === "ok" ? "正确" : "不正确",
          r.emo_clarity ?? "", r.intensity_fit || "", r.identity_keep ?? "",
          r.comp_keep ?? "", r.audio_keep || "", r.trans_smooth || "",
          r.new_prompt || "", r.note || "", r.annotator,
          ((r.ms || 0) / 1000).toFixed(1),
          bjTime(r.created_at),
          r.origin_asset || "", r.edited_asset || "",
        ].map(esc).join(","));
      }
      return new Response("\ufeff" + lines.join("\n"), {
        headers: {
          "Content-Type": "text/csv; charset=utf-8",
          "Content-Disposition": 'attachment; filename="emoedit_video_labels.csv"',
          "Cache-Control": "no-store",
        },
      });
    }

    /* ---------- 兜底：静态资源 ---------- */
    const res = await env.ASSETS.fetch(request);
    return res;
  },
};
