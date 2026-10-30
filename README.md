# EmoEdit 视频情感编辑标注台（Cloudflare Worker 版）

把原来基于**图片**的 EmoEdit 标注台，改成基于**视频**的新数据：
判断 MiniMax H3 生成的编辑视频是否准确表达目标情绪，同时保住身份、构图、动作与音频。

线上地址：<https://wzh.lovezyq.asia>

---

## 存储架构（重要）

四个地方分工明确，**本地不留任何持久数据**：

| 内容 | 存放位置 | 说明 |
|---|---|---|
| 代码（HTML / JS / SQL） | **GitHub** `Wz1h1NG/affectanno` | 只有源码，约 40 KB |
| **视频母本** | **GBU** `zehengW/video_anno_site/public/vid/` | 唯一的权威副本 |
| 站点媒体 | **Cloudflare Workers 静态资源** | 部署时从 GBU 同步上去 |
| 标注结果 | **Cloudflare D1** + **GBU** `zehengW/emoedit_anno_exports/` | D1 在线，CSV 定期归档到 GBU |

### GBU 的实际限制（实测结论）

| 事实 | 后果 |
|---|---|
| **计算节点完全没有外网**（gpuh03 访问 nodejs / npm / Cloudflare API 全部超时）| 部署**不能**放在计算节点 |
| 只有登录节点 `login02` 能联外网，但不允许跑代码 | 部署**不能**放在登录节点 |
| `cit_ztyu` 不在 `HW_910b`（NPU 分区）的 AllowAccounts 里 | 用不了 NPU 节点 |

因此 **`wrangler deploy` 必须在本地机器执行**（本机有 node + 外网）。
这不是把数据放本地，而是把 GBU 的媒体**临时同步过来上传、传完即删**：

```
GBU 母本  --scp-->  本地临时 public/vid  --wrangler deploy-->  Cloudflare

                    ↑ 上传完成后立刻删除
```

`tools/deploy.ps1` 就是把这三步串起来的一条命令。

### 为什么媒体不进 git

- git 对二进制不友好，仓库会迅速膨胀，clone/pull 变慢
- GitHub 单文件 100 MB 上限、仓库推荐 < 1 GB
- GitHub 只放代码；视频是**数据**，改一次数据不该产生一次代码提交

`.gitignore` 已排除 `public/vid/`、`public/img/`。

### 分批方案：每次 1000 条

Workers 静态资源上限 **2 万个文件**（每条样本占 2 个：源 + 编辑），所以一次最多约 1 万条。
实际按 **1000 条/批** 滚动：

| 步骤 | 操作 | 位置 |
|---|---|---|
| 1 | 生成第 N 批视频（约 1000 条）→ `video_anno_site/public/vid/` | GBU |
| 2 | `tools/deploy.ps1` 同步媒体并部署 | 本地 → Cloudflare |
| 3 | 写 `items` 表（该批 1000 条） | D1 |
| 4 | 标注员标注 | 浏览器 |
| 5 | `tools/export_labels.py` 导出标签 | D1 → GBU |
| 6 | 归档并清空 labels，换第 N+1 批 | D1 |

1000 条 × 2 × 250 KB ≈ **500 MB/批**，上传时间几分钟，完全可接受。

⚠️ Workers 静态资源是**目录快照**：部署时目录里有什么就上传什么，没有的会被删掉。
所以每批部署前必须保证 `public/vid` 是完整的目标批次（`deploy.ps1` 会先清空再同步）。

### 规模上限对照

| 方案 | 文件数上限 | 单文件 | 适用规模 |
|---|---|---|---|
| Workers 静态资源 | 2 万 | 25 MB | ≤ 1 万条（每批 1000 条滚动即可）|
| R2 + Worker 绑定 | 无限 | 5 TB | 十几万条以上 |

**R2 当前未开通**（`code 10042: Please enable R2 through the Cloudflare Dashboard`）。
若以后要一次性挂十几万条，去控制台启用 R2（需绑卡，免费 10 GB + 出网免费），然后把
`env.ASSETS.fetch()` 换成：

```js
const obj = await env.BUCKET.get(asset, { range: request.headers });
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
