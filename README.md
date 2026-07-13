# 峰股top

峰股top是一个零成本部署的A股涨停情绪数据中心。行情数据采用静态 JSON + Cloudflare Pages Functions；用户反馈使用 Cloudflare 免费 D1 保存，不需要购买服务器。

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

## Cloudflare Pages 部署

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
