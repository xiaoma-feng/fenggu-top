# 锋股top

锋股top是一个零成本部署的A股涨停情绪数据中心。主站使用腾讯 EdgeOne Makers，行情采用静态 JSON + Edge Functions；用户反馈可使用 EdgeOne KV 保存，不需要购买服务器。GitHub Pages 保留为备用站。

## 当前功能

- 今日涨停数、连板数、炸板数、炸板率、市场最高板
- 今日涨停股票汇总
- 连板筛选：首板、2板、3板、4板、5板+
- 连板分布
- 个股涨停统计
- 最高连板排行
- 涨停热力图
- 断板 / 炸板观察
- 用户反馈：匿名提交、实时展示、点赞、管理员删除

## 本地预览

在项目目录运行：

```powershell
python -m http.server 8080
```

然后打开：

```text
http://localhost:8080
```

## 手动更新数据

安装依赖：

```powershell
pip install -r requirements.txt
```

更新当天数据：

```powershell
python scripts/update_data.py
```

更新指定交易日：

```powershell
python scripts/update_data.py --date 2026-07-06
```

脚本会更新：

- `data/latest.json`
- `data/history/YYYY-MM-DD.json`

## GitHub Actions 自动更新

`.github/workflows/update-data.yml` 已配置：

- 每周一到周五，北京时间 15:30 自动运行
- 也可以在 GitHub Actions 页面手动运行
- 更新完成后自动提交 `data/` 里的 JSON 文件

GitHub Actions 的 cron 使用 UTC 时间，所以配置为：

```yaml
cron: "30 7 * * 1-5"
```

## EdgeOne Makers 部署（国内分享主站）

1. 注册并登录腾讯云账号，进入 EdgeOne Makers。
2. 选择“导入 Git 仓库”，授权并选择 `xiaoma-feng/fenggu-top`。
3. 项目名使用 `fenggu-top`，生产分支使用 `main`。
4. 这是根目录静态项目：构建命令留空，输出目录使用 `.`。
5. 部署完成后使用平台分配的 `*.edgeone.app` HTTPS 地址。
6. 后续 `main` 分支更新会自动触发 EdgeOne 重新部署。

项目已经包含：

- `edgeone.json`：静态资源和数据缓存策略。
- `edge-functions/api/realtime.js`：东方财富实时行情同源中转。
- `edge-functions/api/feedbacks*`：反馈、点赞和管理员删除接口。

如需所有访问者共享反馈，在 EdgeOne 控制台创建 KV 命名空间并绑定：

```text
Variable name: FENGGU_FEEDBACK
```

同时添加管理员环境变量：

```text
FEEDBACK_ADMIN_TOKEN=自行设置的管理员密钥
```

KV 尚未绑定或接口暂时失败时，网页会自动使用浏览器本地反馈，不会卡在加载中。

## Cloudflare Pages 部署（可选）

1. 新建 GitHub 仓库，例如 `fenggu-top`
2. 上传本项目所有文件
3. 登录 Cloudflare
4. 进入 Workers & Pages
5. 选择 Pages，连接 GitHub 仓库
6. 构建设置：
   - Framework preset: `None`
   - Build command: 留空
   - Build output directory: `/`
7. 部署后优先使用：
   - `https://fenggu.pages.dev`
   - 如果被占用，使用 `https://fenggu-top.pages.dev`

## 用户反馈 D1 配置

部署公开反馈前，需要在 Cloudflare 免费创建一个 D1 数据库：

1. Cloudflare 后台进入 `Workers & Pages` -> `D1 SQL Database`。
2. 创建数据库，例如 `fenggu-feedback`。
3. 打开数据库控制台，执行 `migrations/0001_feedback.sql` 里的 SQL。
4. 回到 Pages 项目 `fenggu` 的 `Settings`。
5. 在 `Functions` 里添加 D1 binding：
   - Variable name: `FEEDBACK_DB`
   - D1 database: 选择刚创建的 `fenggu-feedback`
6. 在 `Environment variables` 里添加管理员密钥：
   - Name: `FEEDBACK_ADMIN_TOKEN`
   - Value: 自己设置一串不容易猜的密码
7. 重新部署一次 Pages。

## 注意事项

- 第一版使用 AKShare 做原型数据源，免费但不保证生产级稳定。
- 如果 AKShare 字段变化，可能需要调整 `scripts/update_data.py` 里的字段映射。
- 第一版不做登录注册，默认公开访问。
- 管理员删除反馈通过 `FEEDBACK_ADMIN_TOKEN` 控制，不要公开这个密钥。
- 历史统计依赖每日归档数据，刚开始运行时历史次数会偏少，运行时间越久越准确。
