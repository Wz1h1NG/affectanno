# EmoEdit 情感标注台（Cloudflare Worker 版）

判断「AI 编辑后的图像是否准确表达目标情绪」，并为不合格样本收集**新的编辑 prompt**，
供后续重新生成。零服务器：Worker + D1 + 静态资源，全部在 Cloudflare 免费额度内。

线上地址：`https://wzh.lovezyq.asia`

## 架构

| 层 | 实现 | 说明 |
|---|---|---|
| 后端 | Cloudflare Worker（`src/index.js`） | 纯 JS，无框架 |
| 数据库 | Cloudflare D1（SQLite） | 样本、标注、抢占、口令 |
| 图片 | Worker 静态资源（`public/img/`） | 每张约 25–60 KB，480 张约 18 MB |
| 认证 | HMAC 签名 Cookie（30 天） | 共享口令 + 标注员姓名 |

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 已登录→标注页；未登录→登录页 |
| POST | `/api/login` | `{code, name}`，发 Cookie |
| GET | `/join?code=&name=` | 一键进站（链接里带口令） |
| GET | `/api/next` | 领一道没人标的题（15 分钟租约） |
| POST | `/api/label` | `{item_id, verdict, new_prompt, note, ms}` |
| POST | `/api/skip` | 跳过（只对自己生效） |
| GET | `/api/stats` | 进度与按人统计 |
| GET | `/img?item=&v=origin\|edit` | 图片（需登录） |
| GET | `/export.csv?code=<admin>` | 导出全部标注 |

## 数据结构

- `items`：样本（`ord` 决定出题顺序，`origin_asset` / `edited_asset` 指向静态图）
- `labels`：`item_id` 唯一，一张图只采一次；`verdict` 为 `ok` / `bad`
- `claims`：抢题租约，避免两人同时标同一张
- `skips`：跳过记录
- `config`：`access_code`、`admin_code`、`secret`

## 部署

```bash
npm i -g wrangler                     # 或 pnpm add wrangler
export CLOUDFLARE_API_TOKEN=...       # 需要 Workers Scripts / D1 Edit
wrangler d1 create anno-db            # 把返回的 database_id 填进 wrangler.jsonc
wrangler d1 execute anno-db --remote --file=./schema.sql
# 导入样本与图片后
wrangler deploy
```

绑定自定义域名（Dashboard）：Workers & Pages → 该 Worker → Settings →
Domains & Routes → Add Domain → 子域名 + 根域。

## 出题逻辑

`labels.item_id` 唯一 → 一张图只收一份标签；`claims` 表 15 分钟租约防止并发重复；
`skips` 只影响跳过的那个标注员。取题按 `ord` 升序，`ord` 在导入时随机打散。

## 换数据 / 扩量

1. 在 `build_site.py` 里改数据源，生成 `public/img/{origin,edit}/<item_id>.jpg`
2. 用 `seed_via_api.py`（需自带 token）把 `items` 写进 D1
3. `wrangler deploy` 上传新图

⚠️ 图片超过 10 万张或单批 > 500 MB 时，改用 R2 + `env.ASSETS` 替换为 R2 绑定。

## 已知限制

- 图片走 Worker 静态资源，单文件 ≤ 25 MB、总文件数 ≤ 2 万
- 免费额度：10 万请求/天；5 人标注远低于此
- 未做多人同时标注同一张的「一致性」模式（当前是先去先得）
