# 峰股top上线清单

## 已确认

- GitHub 用户名：`xiaoma-feng`
- 建议仓库名：`fenggu-top`
- 推荐访问地址：`https://fenggu.pages.dev`
- 备选访问地址：`https://fenggu-top.pages.dev`
- 更新任务：每个交易日北京时间 15:30

## 本地预览

推荐这样打开，不建议直接双击 `index.html`：

```powershell
python -m http.server 8080
```

然后访问：

```text
http://localhost:8080
```

如果直接双击 `index.html`，页面会使用内置演示数据，不会读取 `data/latest.json`。

## 上传到 GitHub

1. 打开 GitHub，使用账号 `xiaoma-feng`
2. 新建仓库：`fenggu-top`
3. 仓库设置为 Public
4. 上传当前文件夹里的所有文件
5. 进入 Actions 页面，确认 `Update market data` 工作流存在
6. 手动运行一次工作流，确认能生成并提交 `data/latest.json`

## Cloudflare Pages

1. 登录 Cloudflare
2. 进入 Workers & Pages
3. 创建 Pages 项目
4. 连接 GitHub 仓库 `xiaoma-feng/fenggu-top`
5. 构建设置：
   - Framework preset: `None`
   - Build command: 留空
   - Build output directory: `/`
6. 部署后优先设置项目名为 `fenggu`
7. 如果 `fenggu.pages.dev` 被占用，改为 `fenggu-top.pages.dev`

## 重要提醒

- 当前电脑没有检测到 `git` 命令，所以本地不能直接推送仓库。
- 可以先用 GitHub 网页上传文件，后面再安装 Git。
- AKShare 是免费原型数据源，后续如果要更稳定，需要再接第二个数据源做对账。
