# 峰股top上线清单

## 已确认

- GitHub 用户名：`xiaoma-feng`
- GitHub 仓库：`xiaoma-feng/fenggu-top`
- 推荐访问地址：`https://fenggu.pages.dev`
- 备选访问地址：`https://fenggu-top.pages.dev`
- 更新任务：每个交易日北京时间 15:30
- GitHub Actions：已配置，可自动更新 `data/latest.json`

## 当前状态

- GitHub 仓库已经上传完成。
- 数据自动更新任务已经跑通。
- 远端数据已包含涨停、炸板、跌停、上市板块、题材排行等字段。
- 现在只差 Cloudflare Pages 连接 GitHub 仓库并部署。

## Cloudflare Pages 部署步骤

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
- 盘中实时数据通过 Cloudflare Pages Functions 的 `/api/realtime` 中转。
- 15:30 后以 GitHub Actions 固化生成的 `data/latest.json` 为准。
