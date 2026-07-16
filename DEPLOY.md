# 锋股top上线清单

## 已确认

- GitHub 用户名：`xiaoma-feng`
- GitHub 仓库：`xiaoma-feng/fenggu-top`
- 主站地址：EdgeOne 部署后分配的永久 `*.edgeone.app` 地址
- 备用地址：`https://xiaoma-feng.github.io/fenggu-top/`
- 更新任务：每个交易日北京时间 15:30
- GitHub Actions：已配置，可自动更新 `data/latest.json`

## 当前状态

- GitHub 仓库已经上传完成。
- 数据自动更新任务已经跑通。
- 远端数据已包含涨停、炸板、跌停、上市板块、题材排行等字段。
- 现在只差 EdgeOne Makers 连接 GitHub 仓库并完成首次部署。

## EdgeOne Makers 主站部署步骤

1. 注册并完成腾讯云账号实名认证。
2. 打开 EdgeOne Makers，选择“导入 Git 仓库”。
3. 授权 GitHub 后选择 `xiaoma-feng/fenggu-top`。
4. 项目名填写 `fenggu-top`，生产分支选择 `main`。
5. 构建命令留空，输出目录填写 `.`，开始部署。
6. 部署完成后记录平台分配的永久 `*.edgeone.app` 地址。
7. 创建 KV 命名空间 `fenggu-feedback`，绑定变量名 `FENGGU_FEEDBACK`。
8. 添加环境变量 `FEEDBACK_ADMIN_TOKEN`，然后重新部署一次。

部署后检查这些地址：

```text
https://你的地址.edgeone.app/
https://你的地址.edgeone.app/data/latest.json
https://你的地址.edgeone.app/api/realtime?date=YYYY-MM-DD
https://你的地址.edgeone.app/api/feedbacks
```

GitHub Pages 继续作为备用站：

```text
https://xiaoma-feng.github.io/fenggu-top/
```

## Cloudflare Pages 部署步骤（可选）

1. 打开 Cloudflare 并登录。
2. 进入左侧菜单 `Workers & Pages`。
3. 点击 `Create application`。
4. 选择 `Pages`。
5. 选择 `Connect to Git`。
6. 选择 GitHub 账号 `xiaoma-feng`。
7. 选择仓库 `fenggu-top`。
8. 如果提示安装或授权 GitHub，选择允许访问 `fenggu-top` 仓库。
9. 项目名优先填：`fenggu`。
10. 如果 `fenggu` 被占用，改成：`fenggu-top`。
11. 构建设置填写：
    - Framework preset: `None`
    - Build command: 留空
    - Build output directory: `/`
12. 点击 `Save and Deploy`。

部署完成后访问：

- `https://fenggu.pages.dev`
- 或 `https://fenggu-top.pages.dev`

## 部署后检查

- 首页能打开。
- 左侧菜单显示：涨停汇总、炸板汇总、跌停汇总。
- 数据日期显示最近收盘交易日。
- 页面里有 `上市板块` 筛选。
- 题材排行下方显示 `题材为系统识别，仅供参考`。
- 盘中访问时，页面会尝试请求 `/api/realtime`。
- 左侧用户反馈能打开弹窗；完成 D1 配置后可公开提交、展示、点赞。

## 用户反馈数据库配置

用户反馈不是存在本地浏览器，而是存在 Cloudflare 免费 D1。Pages 首次部署后按下面做：

1. Cloudflare 后台进入 `Workers & Pages`。
2. 进入 `D1 SQL Database`。
3. 点击 `Create database`，名称建议填：`fenggu-feedback`。
4. 进入这个数据库的 `Console`。
5. 打开项目里的 `migrations/0001_feedback.sql`，复制全部 SQL 并执行。
6. 回到 Pages 项目 `fenggu` 或 `fenggu-top`。
7. 进入 `Settings` -> `Functions` -> `D1 database bindings`。
8. 添加绑定：
   - Variable name: `FEEDBACK_DB`
   - D1 database: `fenggu-feedback`
9. 进入 `Settings` -> `Environment variables`。
10. 添加管理员删除密钥：
    - Name: `FEEDBACK_ADMIN_TOKEN`
    - Value: 自己设置一串密码
11. 点击重新部署。

管理员删除反馈的方法：

1. 打开网站。
2. 左侧“用户反馈”标题右边点 `管理`。
3. 输入 `FEEDBACK_ADMIN_TOKEN`。
4. 每条反馈旁边会出现 `删除`。

## 本地预览

推荐这样打开，不建议直接双击 `index.html`：

```powershell
python -m http.server 8080
```

然后访问：

```text
http://localhost:8080
```

## 重要提醒

- AKShare 是免费原型数据源，后续如果要更稳定，需要再接第二个数据源做对账。
- EdgeOne 主站的盘中实时数据通过 Edge Functions 的 `/api/realtime` 同源中转；GitHub Pages 会自动回退到现有免费行情源。
- 15:30 后以 GitHub Actions 固化生成的 `data/latest.json` 为准。
