# EmoEdit 视频情感编辑标注台（Cloudflare Worker 版）

把原来基于**图片**的 EmoEdit 标注台，改成基于**视频**的新数据：
判断 MiniMax H3 生成的编辑视频是否准确表达目标情绪，同时保住身份、构图、动作与音频。

线上地址：<https://wzh.lovezyq.asia>

---

## 存储架构（重要）

三个地方分工明确，**本地不留任何持久数据**：

| 内容 | 存放位置 | 说明 |
|---|---|---|
| 代码（HTML / JS / SQL） | **GitHub** `Wz1h1NG/affectanno` | 只有源码，几百 KB |
| **视频资源** | **Cloudflare R2**（推荐）/ Workers 静态资源（小批量临时用） | 上万条时 R2 是唯一可行方案 |
| 标注结果 | **Cloudflare D1** | SQLite，标签数据 |
| 生成好的原始视频 | **集群** `zehengW/emotion_edit_pilot_*/final/` | 不下载到本地 |

### 为什么媒体不进 git

- git 对二进制不友好，仓库会迅速膨胀，clone/pull 变慢
- GitHub 单文件 100 MB 上限、仓库推荐 < 1 GB
- 上万条视频约 2.5–5 GB，远超舒适区
- 视频是**数据**，不是**代码**；改一次数据不该产生一次代码提交

`.gitignore` 已排除 `public/vid/`、`public/img/`，**部署时临时拉下来、传完就删**。

### 规模上限对照

| 方案 | 文件数上限 | 单文件 | 适用规模 |
|---|---|---|---|
| Workers 静态资源 | 2 万 | 25 MB | ≤ 数千条（当前 59 个 / 17.9 MB）|
| **R2 + Worker 绑定** | **无限** | 5 TB | **上万条以上** |

超过约 500 MB 或 5000 条时，把 `env.ASSETS.fetch()` 换成：

```js
const obj = await env.BUCKET.get(asset, {
  range: request.headers,   // R2 原生支持 Range
});
return new Response(obj.body, {
  status: obj.range ? 206 : 200,
  headers: { "Content-Type": "video/mp4", "Accept-Ranges": "bytes" },
});
```

---

## 与图片版的差异

| 项 | 图片版（旧） | 视频版（现在） |
|---|---|---|
| 媒体 | `public/img/{origin,edit}/<id>.jpg` | `public/vid/{origin,edit}/<name>.mp4` |
| 端点 | `GET /img?item=&v=` | `GET /vid?item=&v=`，**支持 Range/206** |
| 播放 | 两张静态图 | 两路 `<video>` 同步播放、共享进度条 |
| 判断 | 单一「是否准确表达情绪」 | 主判断 + **6 个分项维度** |
| 数据量 | 240 条图片 | **49 条视频**（10 个源 × 情绪/强度/过渡） |
| 音频 | 无 | 可切「编辑 / 源 / 静音」对比 |

后端接口（登录、取题、租约、跳过、导出、`/admin` 结果页）与图片版完全一致，只做了加字段。

## 标注维度

主判断（沿用旧版二选一）：

- ✅ 表达正确
- ❌ 不正确，需要改写 prompt

分项维度（写入 `labels` 表）：

| 列 | 含义 | 取值 |
|---|---|---|
| `emo_clarity` | 情绪可辨识度 | 1..5（1 看不出，5 一眼看出） |
| `intensity_fit` | 强度是否符合档位 | `weaker` / `good` / `stronger` |
| `identity_keep` | 身份保持 | 1..5 |
| `comp_keep` | 构图 / 动作保持 | 1..5 |
| `audio_keep` | 音频与源是否一致 | `yes` / `no` / `na` |
| `trans_smooth` | 过渡是否平滑（仅 trans） | `yes` / `no` / `na` |

前三项（`emo_clarity`、`identity_keep`、`comp_keep`）为必填，未选会拦住提交。

## 样本构成

| subset | 数量 | 含义 |
|---|---|---|
| `single` | 30 | 10 个源 × {happy, sad, worried}，强度 M |
| `grad` | 9 | 3 个源 × sad × 强度 {L, M, H} |
| `trans` | 10 | 5 组过渡 × 2 个源：neutral→{happy, sad, angry, worried}, happy→sad |

源视频来自 MER2025 track1 train，全部为 neutral 片段。

⚠️ 已知冗余：`grad` 的 M 档与 `single` 的 sad M 档 prompt 完全相同，
产出有 3 组重复（00993 / 01295 / 01310）。唯一内容实际 46 条。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 已登录→标注页；未登录→登录页 |
| POST | `/api/login` | `{code, name}`，发 Cookie |
| GET | `/join?code=&name=` | 一键进站（链接里带口令） |
| GET | `/api/next` | 领一道没人标的题（15 分钟租约） |
| POST | `/api/label` | `{item_id, verdict, ...6 个维度}` |
| POST | `/api/skip` | 跳过（只对自己生效） |
| GET | `/api/stats` | 进度与按人统计 |
| GET | `/vid?item=&v=origin\|edit` | 视频（需登录，支持 Range） |
| GET | `/export.csv?code=<admin>` | 导出全部标注（免登录） |
| GET | `/admin?code=<admin>` | 结果查看页 |
| GET | `/api/results?code=<admin>` | 结果 JSON |

## 部署

```bash
export CLOUDFLARE_API_TOKEN=...      # 需要 Workers Scripts:Edit + D1 Edit（+ R2 Edit 若用 R2）
pnpm add -D wrangler
# 媒体从服务器拉到 public/vid/（临时），或改为 R2 后跳过
node node_modules/wrangler/bin/wrangler.js deploy
```

- Worker 名：`emo-anno`
- D1：`anno-db`（database_id 见 `wrangler.jsonc`）
- 静态资源走 `env.ASSETS`，`run_worker_first: true`
  （必须开，否则 `/` 会被静态 index.html 直接命中，绕过登录检查）

## 换数据

1. 改集群上 `build_video_assets.py` 的数据源，生成 `public/vid/` 与 `manifest.json`
2. 用 D1 HTTP API 写 `items`（见集群 `seed_*` 脚本）
3. 媒体上传（Workers 静态资源随 deploy 上传；R2 则 `wrangler r2 object put` 批量传）

旧库升级用 `migrate.sql`（`ALTER TABLE ADD COLUMN`）；全新库用 `schema.sql`。

## 运维

口令存在 D1 的 `config` 表，**不写进仓库**：

| 键 | 用途 |
|---|---|
| `access_code` | 标注口令（发给标注员） |
| `admin_code` | 导出 / 结果页 / 管理与口令 |
| `secret` | 会话签名密钥 |

查看当前口令：

```bash
wrangler d1 execute anno-db --remote \
  --command "SELECT k,v FROM config WHERE k IN ('access_code','admin_code')"
```

改口令：

```sql
UPDATE config SET v='EMO-XXXX' WHERE k='access_code';
```

## 已知限制

- 一人一条只标一次（`labels.item_id` UNIQUE，先到先得），未做多人一致性
- 免费额度 10 万请求/天；视频每条 200–450 KB，5 人标注远低于额度
- 视频为 864×480 / 24fps / H.264 + AAC，浏览器均可直接播放
- 结果页 `/admin` 用 `<video preload="metadata">` 显示首帧，不能直接播放（点开才播）
